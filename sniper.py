"""
KOL Telegram Sniper — auto-buy Solana tokens posted in a Telegram channel.

Pipeline: Telethon userbot listens to the channel -> parse the mint -> buy via
PumpPortal /api/trade-local (transaction signed locally) -> optional TP/SL auto-sell.

Setup: see .env.example and requirements.txt
Wallet: use a dedicated burner wallet funded with only what you can afford to lose.
         The private key stays in RAM while the bot runs.
"""
import os
import re
import json
import asyncio
import logging
import time
from typing import Optional

import requests
from requests.adapters import HTTPAdapter
import websockets
from dotenv import load_dotenv
from telethon import TelegramClient, events
from notify import send_telegram_notification
from logger import log_call
from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.transaction import VersionedTransaction
from solders.commitment_config import CommitmentLevel
from solders.rpc.requests import SendVersionedTransaction
from solders.rpc.config import RpcSendTransactionConfig

load_dotenv()

# ---------------------------------------------------------------- Config
API_ID = int(os.environ["TG_API_ID"])
API_HASH = os.environ["TG_API_HASH"]
# Channels to listen to: @handle, numeric id, or t.me/xxx separated by commas
CHANNELS = [c.strip() for c in os.environ["TG_CHANNELS"].split(",") if c.strip()]

PRIVATE_KEY = os.environ["SOL_PRIVATE_KEY"]                      # base58 burner wallet key
# Prefer a low-latency Helius RPC when a key is provided; the public RPC is slow
# and rate-limits precisely when calls hit. Falls back to SOL_RPC_URL / public.
HELIUS_API_KEY = os.environ.get("HELIUS_API_KEY", "").strip()
HELIUS_NETWORK = os.environ.get("HELIUS_NETWORK", "mainnet").strip()      # mainnet / devnet
if HELIUS_API_KEY:
    RPC_URL = f"https://{HELIUS_NETWORK}.helius-rpc.com/?api-key={HELIUS_API_KEY}"
else:
    RPC_URL = os.environ.get("SOL_RPC_URL", "https://api.mainnet-beta.solana.com")
BUY_SOL = float(os.environ.get("BUY_SOL", "0.5"))              # buy size per snipe (SOL)
SLIPPAGE = int(os.environ.get("SLIPPAGE", "15"))               # %
PRIORITY_FEE = float(os.environ.get("PRIORITY_FEE", "0.001"))  # SOL (raise if txs don't land)
POOL = os.environ.get("POOL", "auto")                          # pump / raydium / auto...

# Auto-sell optional; requires PumpPortal API key for the price feed
AUTOSELL = os.environ.get("AUTOSELL", "false").lower() == "true"
TP_MULT = float(os.environ.get("TP_MULT", "2.0"))              # take-profit multiplier
SL_MULT = float(os.environ.get("SL_MULT", "0.5"))             # stop-loss multiplier
PUMPPORTAL_KEY = os.environ.get("PUMPPORTAL_API_KEY", "")

TRADE_LOCAL = "https://pumpportal.fun/api/trade-local"
WS_DATA = "wss://pumpportal.fun/api/data"
SOL_MINT = "So11111111111111111111111111111111111111112"

keypair = Keypair.from_base58_string(PRIVATE_KEY)
PUBKEY = str(keypair.pubkey())

session = requests.Session()
_adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
session.mount("https://", _adapter)
session.mount("http://", _adapter)
session.headers.update({"Connection": "keep-alive"})

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("sniper")

bought: set[str] = set()          # dedupe: avoid buying the same mint twice

# ---------------------------------------------------------------- mint parsing
_URL_RE = re.compile(
    r"(?:pump\.fun/(?:coin/)?|dexscreener\.com/solana/|birdeye\.so/token/|solscan\.io/token/)"
    r"([1-9A-HJ-NP-Za-km-z]{32,44})"
)
_B58_RE = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")


def _valid(s: str) -> bool:
    try:
        Pubkey.from_string(s)
        return True
    except Exception:
        return False


def extract_mint(text: str) -> Optional[str]:
    """Extract the token address from a message.

    Priority: known link > mint in 'pump'/'bonk' > first valid base58 string.
    """
    if not text:
        return None
    m = _URL_RE.search(text)
    if m and _valid(m.group(1)):
        return m.group(1)
    cands = [c for c in _B58_RE.findall(text) if c != SOL_MINT and _valid(c)]
    if not cands:
        return None
    for c in cands:                       # launchpads often append suffixes to the mint
        if c.endswith(("pump", "bonk", "moon")):
            return c
    return cands[0]

# ---------------------------------------------------------------- Exécution on-chain
def _send(action: str, mint: str, amount, denominated_in_sol: str) -> Optional[str]:
    r = session.post(TRADE_LOCAL, data={
        "publicKey": PUBKEY,
        "action": action,
        "mint": mint,
        "amount": amount,
        "denominatedInSol": denominated_in_sol,
        "slippage": SLIPPAGE,
        "priorityFee": PRIORITY_FEE,
        "pool": POOL,
    }, timeout=10)
    if r.status_code != 200:
        log.error("PumpPortal %s: %s", r.status_code, r.text[:200])
        return None
    tx = VersionedTransaction(VersionedTransaction.from_bytes(r.content).message, [keypair])
    cfg = RpcSendTransactionConfig(preflight_commitment=CommitmentLevel.Confirmed)
    payload = SendVersionedTransaction(tx, cfg).to_json()
    resp = session.post(RPC_URL, headers={"Content-Type": "application/json"},
                        data=payload, timeout=10)
    return resp.json().get("result")


def _warm_connections() -> None:
    """Open the PumpPortal + RPC sockets before the first call so we don't pay
    the TLS handshake on the hot path. Best-effort; failures are non-fatal."""
    try:
        session.get(TRADE_LOCAL.rsplit("/api/", 1)[0], timeout=5)
    except Exception as exc:
        log.debug("warm PumpPortal failed: %s", exc)
    try:
        session.post(RPC_URL, headers={"Content-Type": "application/json"},
                     data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": "getHealth"}),
                     timeout=5)
    except Exception as exc:
        log.debug("warm RPC failed: %s", exc)


def buy(mint: str) -> Optional[str]:
    return _send("buy", mint, BUY_SOL, "true")


def sell_all(mint: str) -> Optional[str]:
    return _send("sell", mint, "100%", "false")


def estimate_entry_price(mint: str, timeout: float = 2.0) -> Optional[float]:
    """Best-effort, low-cost price estimate from PumpPortal data.

    This uses a single short live fetch and returns None if the feed is unavailable,
    so it does not slow the buy flow materially.
    """
    if not PUMPPORTAL_KEY:
        return None
    uri = f"{WS_DATA}?api-key={PUMPPORTAL_KEY}"
    try:
        import websockets
        start = time.monotonic()
        async def _fetch() -> Optional[float]:
            async with websockets.connect(uri) as ws:
                await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))
                async for raw in ws:
                    if time.monotonic() - start >= timeout:
                        break
                    d = json.loads(raw)
                    vsol, vtok = d.get("vSolInBondingCurve"), d.get("vTokensInBondingCurve")
                    if vsol and vtok:
                        return float(vsol) / float(vtok)
                return None

        return asyncio.get_event_loop().run_until_complete(_fetch())
    except Exception as exc:
        log.debug("entry price fetch failed for %s: %s", mint[:6], exc)
        return None

# ---------------------------------------------------------------- Auto-sell TP/SL
async def monitor_and_sell(mint: str):
    """Track price via PumpPortal WS and sell on TP or SL.

    Requires PUMPPORTAL_API_KEY.
    """
    if not PUMPPORTAL_KEY:
        log.warning("AUTOSELL enabled but PUMPPORTAL_API_KEY missing — no monitoring for %s", mint)
        return
    uri = f"{WS_DATA}?api-key={PUMPPORTAL_KEY}"
    entry = None
    loop = asyncio.get_event_loop()
    try:
        async with websockets.connect(uri) as ws:
            await ws.send(json.dumps({"method": "subscribeTokenTrade", "keys": [mint]}))
            async for raw in ws:
                d = json.loads(raw)
                vsol, vtok = d.get("vSolInBondingCurve"), d.get("vTokensInBondingCurve")
                if not vsol or not vtok:
                    continue
                price = vsol / vtok
                if entry is None:
                    entry = price
                    log.info("[%s] entrée ~%.10f SOL", mint[:6], entry)
                    continue
                mult = price / entry
                if mult >= TP_MULT:
                    log.info("[%s] TP x%.2f -> sell", mint[:6], mult)
                    sig = await loop.run_in_executor(None, sell_all, mint)
                    log.info("SELL: https://solscan.io/tx/%s", sig)
                    return
                if mult <= SL_MULT:
                    log.info("[%s] SL x%.2f -> sell", mint[:6], mult)
                    sig = await loop.run_in_executor(None, sell_all, mint)
                    log.info("SELL: https://solscan.io/tx/%s", sig)
                    return
    except Exception as e:
        log.error("monitor %s: %s", mint[:6], e)

# ---------------------------------------------------------------- Listener Telegram
client = TelegramClient("sniper_session", API_ID, API_HASH)


@client.on(events.NewMessage(chats=CHANNELS))
async def handler(event):
    mint = extract_mint(event.raw_text)
    if not mint or mint in bought:
        return
    bought.add(mint)
    log.info("CALL detected: %s", mint)
    # requests is blocking -> use executor to avoid freezing the loop
    sig = await asyncio.get_event_loop().run_in_executor(None, buy, mint)
    if sig:
        log.info("BUY sent: https://solscan.io/tx/%s", sig)
        # prepare enhanced notification
        try:
            channel = str(getattr(event, 'chat_id', ''))
            deep_link_base = os.getenv('GMGN_DEEP_LINK', 'https://gmgn.ai/sol/token')
            deep_link = deep_link_base.rstrip('/') + '/' + mint
            entry_price = await asyncio.get_event_loop().run_in_executor(None, estimate_entry_price, mint)
            text_lines = [
                f"🟩 BUY executed",
                f"Mint: {mint}",
                f"Bet: {BUY_SOL} SOL",
            ]
            if entry_price is not None:
                text_lines.append(f"Entry price: {entry_price:.10f} SOL")
            text_lines.extend([
                f"GMGN: {deep_link}",
                f"Tx: https://solscan.io/tx/{sig}",
                f"Channel: {channel}",
            ])
            text = "\n".join(text_lines)
            notified = await asyncio.get_event_loop().run_in_executor(None, send_telegram_notification, text)
        except Exception as e:
            notified = False
            log.error("Telegram notify failed: %s", e)
        # persist the trade row (atomic)
        try:
            log_call(mint=mint, bet_sol=BUY_SOL, channel=channel, tx=sig, notified=bool(notified), note=deep_link)
        except Exception:
            log.exception("Failed to log call for %s", mint)
        if AUTOSELL:
            asyncio.create_task(monitor_and_sell(mint))
    else:
        bought.discard(mint)              # failure -> allow retry if reposted


async def main():
    async with client:
        await asyncio.get_event_loop().run_in_executor(None, _warm_connections)
        rpc_label = "Helius" if HELIUS_API_KEY else RPC_URL
        log.info("Listening on %s | wallet %s | %s SOL/snipe | RPC %s",
                 CHANNELS, PUBKEY, BUY_SOL, rpc_label)
        await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
