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
import threading
from typing import Optional

import requests
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

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
log = logging.getLogger("sniper")

try:
    keypair = Keypair.from_base58_string(PRIVATE_KEY)
    PUBKEY = str(keypair.pubkey())
except Exception as exc:
    log.warning("Invalid SOL private key: %s", exc)
    keypair = None
    PUBKEY = ""


class PersistentBoughtMints:
    """Fast in-memory dedupe store backed by a small on-disk file."""

    def __init__(self, path: Optional[str] = None):
        self._path = path or os.path.join(os.path.dirname(__file__), "bought_mints.txt")
        self._mints: set[str] = set()
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        with open(self._path, "r", encoding="utf-8") as fh:
            for line in fh:
                mint = line.strip()
                if mint:
                    self._mints.add(mint)

    def contains(self, mint: str) -> bool:
        with self._lock:
            return mint in self._mints

    def mark_pending(self, mint: str) -> None:
        with self._lock:
            self._mints.add(mint)

    def mark_bought(self, mint: str, confirmed: bool = True) -> None:
        with self._lock:
            if not confirmed:
                return
            if mint in self._mints:
                return
            self._mints.add(mint)
            self._append_to_disk(mint)

    def remove(self, mint: str) -> None:
        with self._lock:
            self._mints.discard(mint)

    def _append_to_disk(self, mint: str) -> None:
        directory = os.path.dirname(self._path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(self._path, "a", encoding="utf-8") as fh:
            fh.write(f"{mint}\n")


bought = PersistentBoughtMints(
    os.environ.get("BOUGHT_MINTS_FILE", os.path.join(os.path.dirname(__file__), "bought_mints.txt"))
)

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
    if keypair is None:
        log.error("Cannot send transaction: wallet key is unavailable")
        return None

    r = requests.post(TRADE_LOCAL, data={
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
    resp = requests.post(RPC_URL, headers={"Content-Type": "application/json"},
                         data=payload, timeout=10)
    return resp.json().get("result")


def buy(mint: str) -> Optional[str]:
    return _send("buy", mint, BUY_SOL, "true")


def sell_all(mint: str) -> Optional[str]:
    return _send("sell", mint, "100%", "false")

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
    if not mint or bought.contains(mint):
        return
    bought.mark_pending(mint)
    log.info("CALL detected: %s", mint)
    # requests is blocking -> use executor to avoid freezing the loop
    sig = await asyncio.get_event_loop().run_in_executor(None, buy, mint)
    if sig:
        bought.mark_bought(mint, confirmed=True)
        log.info("BUY sent: https://solscan.io/tx/%s", sig)
        # prepare enhanced notification
        try:
            channel = str(getattr(event, 'chat_id', ''))
                deep_link_base = os.getenv('GMGN_DEEP_LINK', 'https://gmgn.ai/sol/token')
            deep_link = deep_link_base.rstrip('/') + '/' + mint
            text_lines = [
                f"🟩 BUY executed",
                f"Mint: {mint}",
                f"Bet: {BUY_SOL} SOL",
                f"Tx: https://solscan.io/tx/{sig}",
                f"GMGN: {deep_link}",
                f"Channel: {channel}",
            ]
            # entry price not available immediately; leave placeholder
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
        bought.remove(mint)              # failure -> allow retry if reposted


async def main():
    async with client:
        log.info("Listening on %s | wallet %s | %s SOL/snipe", CHANNELS, PUBKEY, BUY_SOL)
        await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
