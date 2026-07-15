# Scaling Plan — Running KOL-SNIPER at 2+ SOL per Call

Goal stated: bigger size (> 2 SOL / call), land *first in the queue* on a KOL
call, and be net profitable.

This document is split into (1) a blunt reality check so you size the bet
correctly, (2) the latency/landing work that actually decides who buys first,
(3) what changes when the ticket is 2+ SOL instead of 0.5, and (4) the
risk-management that keeps you alive long enough for edge to matter.

> "Frontrunning" here = reacting to a **public** Telegram post faster than the
> other people reacting to the same post. That's a latency race on public
> information. It is *not* mempool/sandwich attacking of a specific victim, and
> this plan does not build that.

---

## 0. Reality check (read before increasing size)

- **You are late by design.** The KOL, their group admins, and their private
  pre-call bots are already in before the message hits your `handler`. The
  public post is frequently the *exit liquidity event* for people who bought
  cheaper. At 2 SOL you become a large, slow, visible bag holder for insiders.
- **You are racing professionals.** Colocated bots with Jito bundles, staked
  RPC, and pre-signed templates land in the same block the post appears. Beating
  *humans* is easy; beating *them* to a good entry is the actual game.
- **Size cuts both ways on a bonding curve.** 2+ SOL into a fresh pump.fun curve
  moves the price meaningfully — you pay your own slippage on the way in, and you
  need someone to buy *above* your average to exit. Bigger entry = you need a
  bigger pump just to break even.
- **Expected value is dominated by the losers.** Rugs/honeypots go to ~-100%.
  One un-sellable 2 SOL position erases many good 2x trades. Survival math, not
  win rate, is what makes this profitable.

Implication for sizing: don't jump from 0.5 → 2.0 globally. Make size a function
of signal quality and safety checks (see §3), and cap total exposure (§4).

---

## 1. Current bottlenecks (measured against `sniper.py`)

The buy path today (`_send`, lines ~100-119) is the whole problem:

1. `requests.post(TRADE_LOCAL, ...)` — **blocking** HTTP to PumpPortal to *build*
   the transaction. Round-trip #1.
2. `requests.post(RPC_URL, ...)` to `api.mainnet-beta.solana.com` — the free
   public RPC, rate-limited and slow, no priority routing. Round-trip #2.
3. New TCP/TLS handshake on every call (no connection reuse).
4. Static `PRIORITY_FEE=0.001` and no Jito tip — you land wherever the leader
   feels like putting you.
5. Signal → order latency also includes Telethon MTProto delivery, which depends
   on which Telegram data center you connect to.

You are losing the race at steps 1, 2, and 4. Everything below targets those.

---

## 2. Winning the "first in queue" race

Priority order — do them top-to-bottom; each line is roughly ordered by
latency-per-effort.

### 2.1 Kill the double round-trip (biggest single win)
- Keep a **persistent `requests.Session`** (or `httpx`/`aiohttp` async client)
  with HTTP keep-alive to PumpPortal and to the RPC so you're not paying
  TLS setup on every snipe.
- Better: use PumpPortal's **Lightning / hosted transaction** API (server signs
  and sends) *or* build the buy transaction **locally** so you skip the
  build-round-trip entirely. Local build means you hold the pump.fun program
  layout + your ATA and sign in-process — one network hop (send) instead of two.
- Move the whole hot path off blocking `requests` in a threadpool onto a native
  async client so the event loop isn't parked during the buy.

### 2.2 Use a real RPC / dedicated sender (do this before raising size)
- Replace `api.mainnet-beta.solana.com` with a paid low-latency provider:
  **Helius, Triton, QuickNode, or Jito**. Use their **staked / dedicated send
  endpoint** — public RPC drops and delays transactions under load, which is
  exactly when calls happen.
- Send to **multiple RPC endpoints in parallel** for the same signed tx (dedupe
  by signature). First one to land wins; costs nothing but a little bandwidth.

### 2.3 Land at the top of the block with Jito
- Submit the buy as a **Jito bundle with a tip**. The tip is a direct bid for
  block position — this is the legitimate mechanism to jump ahead of everyone
  else reacting to the same post. Start with a tip in the 0.001–0.01 SOL range
  and tune from landing stats.
- Make **priority fee dynamic**: sample recent priority fees (e.g. Helius
  `getPriorityFeeEstimate`) and bid the 75th–90th percentile, not a fixed
  0.001. Static fees lose during congestion.

### 2.4 Colocation & signal latency
- Run the bot on a VPS **physically near your RPC/Jito region** (commonly
  Frankfurt, Amsterdam, or NY-metro depending on provider). Cross-continent RTT
  alone can cost you the block.
- Let Telethon connect to the **nearest Telegram DC** and keep the session warm
  and connected (it already reuses `sniper_session`). Persistent process, no
  cold starts.
- Pre-warm everything that isn't call-specific: fee estimates, tip account,
  blockhash refresh loop, and your token ATA existence — so at call time the
  only new work is "insert mint, sign, fire."

### 2.5 Parse faster / earlier
- `extract_mint` runs two regexes; that's already sub-millisecond, fine. The win
  is not re-doing async setup per call. Notably `estimate_entry_price` opens a
  **new websocket every buy** — keep that **off the buy path** (it already runs
  after send, good; keep it that way, never before the buy).

---

## 3. What changes at 2+ SOL per call

Raising `BUY_SOL` is one line; doing it *safely* is the work.

### 3.1 Slippage & price impact
- `SLIPPAGE=15` is a % ceiling, not your actual cost. At 2 SOL into a thin curve
  your realized impact can be far worse than at 0.5. Either raise the ceiling so
  the tx doesn't fail, or (better) **split the order** into 2–3 sends to reduce
  average entry and detect a honeypot with the first small slice.
- Consider an **entry cap**: skip if projected price impact for your size exceeds
  a threshold (curve too thin to absorb 2 SOL without wrecking your average).

### 3.2 Pre-buy safety filters (mandatory at this size)
Before firing 2 SOL, gate on cheap, fast checks. One bad fill at 2 SOL wipes
several good trades:
- **Mint authority renounced** / **freeze authority null** (freeze authority =
  they can lock your tokens = guaranteed honeypot).
- **LP status** (burned/locked vs. pullable).
- **Top-holder concentration** — one wallet holding most supply = imminent dump.
- **Sellability probe** — the split-order trick above: buy a small first slice,
  confirm you can quote a sell, then send the rest.
Providers like Helius/Birdeye/RugCheck expose most of this in one fast call.
Cache nothing that changes per-token; keep the check under a few hundred ms or it
costs you the race — run it in parallel with tx build and abort the send if it
fails.

### 3.3 Position accounting
- Log realized average entry (you already estimate entry price post-buy) and
  actual fill from the confirmed tx, not just `BUY_SOL`, so PnL is real.

---

## 4. Staying profitable (risk management)

Being first is worthless without disciplined exits. The current auto-sell
(`monitor_and_sell`) is a naive single-shot TP/SL on one websocket. Upgrade:

- **Partial take-profit + trailing stop.** e.g. sell 50% at 2x to recover
  principal, let the rest ride a trailing stop. Recovering principal early is
  what survives the rug tail.
- **Time-based exit.** If it hasn't moved in N seconds/minutes, exit — dead calls
  bleed via slippage and opportunity cost.
- **Hard stop-loss that actually fires fast.** The sell must use the same
  low-latency send path as the buy (Jito/priority), or you'll stop-loss into a
  cliff. Right now sell reuses the slow `_send`; fix that.
- **Resilient monitoring.** One WS with no reconnect = you go blind and hold
  through a dump. Add reconnect + a fallback price source.
- **Global guardrails:**
  - `MAX_CONCURRENT_POSITIONS` and a **total SOL exposure cap**.
  - **Daily loss limit / kill switch** — stop trading after X SOL down in a day.
  - **Per-channel sizing** — size by historical hit-rate of each KOL from your
    own `calls.csv`, not a flat 2 SOL for everyone.
  - Keep a SOL buffer for fees/tips so buys never fail on empty balance.

---

## 5. Concrete change list (in this repo)

Config (`.env`):
- [ ] `SOL_RPC_URL` → paid low-latency provider (Helius/Triton/QuickNode).
- [ ] Add `JITO_TIP_SOL`, `JITO_BUNDLE_URL`, dynamic-fee toggle.
- [ ] Make `BUY_SOL` a base; add `MAX_BUY_SOL`, `MAX_CONCURRENT_POSITIONS`,
      `MAX_DAILY_LOSS_SOL`, per-channel size overrides.
- [ ] Split-order params: `ENTRY_SLICES`, `PROBE_SOL` (small first slice).

Code (`sniper.py`):
- [ ] Persistent HTTP client (keep-alive) for PumpPortal + RPC; drop per-call
      `requests`.
- [ ] Build tx locally or use Lightning to cut a round-trip; async send.
- [ ] Multi-RPC / Jito-bundle send with tip; dynamic priority fee.
- [ ] Pre-buy safety gate (authorities, LP, top holders, sell probe), run in
      parallel with build, abort on fail.
- [ ] Split large orders; record real average entry from confirmed tx.
- [ ] Rewrite exits: partial TP + trailing stop + time stop, fast-path sells,
      reconnecting price feed.
- [ ] Guardrails: exposure cap, daily loss kill-switch, per-channel sizing.

Ops:
- [ ] VPS colocated near your RPC/Jito region; keep the process + Telethon
      session warm 24/7.
- [ ] Instrument **signal→sent** and **sent→landed** latency and Jito landing
      rate; tune tip/fee from the numbers, not vibes.
- [ ] Dry-run at 0.5 SOL with the new path first; only scale to 2+ once landing
      rate and exit discipline are proven on small size.

---

## 6. Suggested rollout order

1. Paid RPC + persistent client + async send.  *(lands you competitively at all)*
2. Dynamic priority fee, then Jito tip/bundle.  *(gets you first)*
3. Safety gate + split orders.  *(makes 2 SOL survivable)*
4. Exit rewrite + guardrails.  *(makes it profitable over many trades)*
5. Colocate, measure, then scale size.

Do **not** reorder by raising `BUY_SOL` first. Size last, after the machine that
lands fast and exits well is proven on small money.
