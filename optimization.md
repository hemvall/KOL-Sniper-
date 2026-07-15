# Latency Optimization — Signal → Buy

Current measured end-to-end: **~1.0–1.2 s** from call detection to bought.

This doc breaks that down into hops, then quantifies how much each optimization
saves. Numbers are grounded in **real measurements** taken from this machine to
the actual endpoints (median of 3 runs), not guesses.

## Measured endpoint timings (this machine, cold connection)

| Hop | TCP connect | +TLS handshake | Full round-trip |
|---|---|---|---|
| Public RPC `api.mainnet-beta.solana.com` | ~55 ms | ~120 ms | ~160 ms |
| PumpPortal `pumpportal.fun` (builds the tx) | ~125 ms | **~260 ms** | **~450 ms+** |
| Helius `mainnet.helius-rpc.com` (send) | ~25 ms | ~65 ms | **~85 ms** |

Two things jump out:
1. **A fresh TLS handshake costs 120–260 ms per host.** Today the bot opens a
   new connection on *every* call (blocking `requests`, no pooled session), so it
   pays this twice per snipe (~380 ms) before doing anything useful.
2. **Helius is ~2–3× faster than public RPC** on the send hop and much more
   reliable when everyone is buying at once (public RPC rate-limits exactly then).

## Where the ~1.0–1.2 s goes today (estimated budget)

| Stage | Est. time | Why |
|---|---|---|
| Parse mint + executor handoff | ~5 ms | regex is sub-ms |
| **PumpPortal build round-trip** | ~400–550 ms | fresh TLS (~260 ms) + build/return the tx |
| Sign tx locally | ~5–10 ms | fast |
| **Public RPC send round-trip** | ~200–400 ms | fresh TLS (~120 ms) + submit (rate-limited during calls) |
| **On-chain confirmation** | ~400–600 ms | ~1 slot ≈ 400 ms — chain physics |
| **Total (signal → confirmed)** | **~1.0–1.2 s** | matches your measurement |

> Note: if you measure to *tx sent* rather than *confirmed*, drop the
> confirmation row — your controllable budget is ~600–950 ms today.

## Optimizations, ranked by savings-per-effort

| # | Optimization | Est. saving | Effort | How |
|---|---|---|---|---|
| 1 | **Persistent keep-alive session** (reuse TCP+TLS to both hosts) | **~300–500 ms** | Low | One `requests.Session()` / `httpx` client reused across calls; handshakes amortized to ~0 after warm-up |
| 2 | **Send via Helius instead of public RPC** | **~100–250 ms** | Trivial | Set `SOL_RPC_URL=https://mainnet.helius-rpc.com/?api-key=…`; also removes rate-limit stalls during calls |
| 3 | **Build the buy tx locally** (drop the PumpPortal hop) | **~150–300 ms** | High | Construct the pump.fun buy instruction in-process; eliminates the whole ~450 ms build round-trip (keep only the send) |
| 4 | **Pre-fetched blockhash** (background refresh loop) | **~40–90 ms** | Low* | Only relevant once you build locally (#3); keep a fresh blockhash cached so it's not a call-time round-trip |
| 5 | **Colocate VPS near Helius region** | **~50–150 ms** | Med | Cuts every remaining RTT; your ~25–125 ms connect times imply real geographic distance right now |
| 6 | **Async HTTP client** (drop blocking `requests`+executor) | **~5–20 ms** | Med | Marginal on a single call; the real win is not parking the loop when calls arrive back-to-back |

\* Low effort *given* #3 is already done.

### Not latency-to-submit, but wins the actual race
| Optimization | Effect |
|---|---|
| **Jito bundle + tip** | Doesn't shrink your submit time, but buys **block position** — lands you ahead of equal-latency competitors and avoids "missed the block, wait ~400 ms for the next slot." In contested calls this is the difference between fill #3 and fill #30. |
| **Dynamic priority fee** | Landing *reliability* under congestion, not raw latency — prevents dropped txs when it matters most. |

## What you can realistically get to

| Path | What it includes | Signal → sent | Signal → confirmed |
|---|---|---|---|
| **Today** | current code | ~600–950 ms | ~1.0–1.2 s |
| **Quick wins** | #1 + #2 (a session + Helius URL) | **~250–450 ms** | **~650–850 ms** |
| **+ Local build** | #1 #2 #3 #4 | **~120–250 ms** | **~550–700 ms** |
| **+ Colocation** | all of the above + #5 | **~80–180 ms** | **~500–620 ms** |

**Headline: the two cheapest changes (#1 keep-alive session + #2 Helius send)
save ~400–650 ms — roughly halving your current time — in maybe an hour of
work.** Everything past that fights diminishing returns against the ~400 ms
on-chain confirmation floor, which is chain physics you can't compress. Once
you're near that floor, **Jito** (not latency) is what actually puts you first in
the block.

## Recommended order

1. **#1 + #2** — pooled session + Helius URL. Biggest win, lowest effort. Do today.
2. **#3 + #4** — local tx build + cached blockhash. Removes the PumpPortal hop.
3. **Jito tip/bundle** — to win ties once you're near the confirmation floor.
4. **#5 colocation** — last, once the software path is proven.
