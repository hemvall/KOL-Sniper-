# Bot roadmap

## Highest priority

These are the most important improvements to implement first because they directly affect safety, reliability, and profitability.

- **Persistent buy dedupe across restarts**: save bought mints to disk so the bot never buys the same token again after a successful purchase.
- **Risk controls**: add global daily spend limits, per-trade max bet, and an emergency kill switch.
- **Buy confirmation and retry logic**: distinguish confirmed buys from failed or pending ones, and retry transient failures with backoff.
- **Robust notifications**: send richer Telegram alerts with mint, bet size, entry price, tx link, and success/failure state.

## High priority

- **Persistent trade logging**: append buy/sell events atomically to calls.csv with timestamp, channel, tx, bet, and notification flag.
- **Improved mint parsing**: reduce false positives with better regexes, ignore lists, and heuristics.
- **Secure secret handling**: avoid plain env dumps and document safe secret storage or secret manager support.
- **Auto-sell controls**: add configurable take-profit and stop-loss logic with safer defaults.

## Medium priority

- **Smart alert deduplication**: collapse repeated or near-duplicate signals from the same token or channel into a compact digest.
- **Per-token configuration**: allow token-specific overrides for bet size, slippage, and autosell behavior.
- **Auto-notify on failure**: retry notifications or fall back to an alternate channel when Telegram alerts fail.
- **Health and restart supervision**: add a simple health-check endpoint and recommend process supervision.

## Low priority

- **Web dashboard**: show recent calls, open positions, P&L, and logs in a simple web UI.
- **Metrics and alerts**: expose basic Prometheus-style metrics for buys, sells, and failures.
- **Multi-channel notifications**: add Discord, SMS, or email alerts.
- **Dry-run mode**: simulate buys locally without spending funds.

## Fun / cool feature ideas

- **Mood-based trading mode**: let the bot switch between aggressive and conservative behavior based on a simple mode toggle.
- **Profit snapshot summaries**: send a daily or weekly recap with wins, losses, and best-performing tokens.
- **Token vibe score**: score incoming tokens by hype, volume, and price movement signals for a more “sniper” feel.
- **Auto-generated trade commentary**: add playful or structured commentary to notifications such as “early entry”, “strong momentum”, or “watchlist spike”.
- **Mini leaderboard**: track the top-performing tokens or the most profitable runs in a simple internal leaderboard.
