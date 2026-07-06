# KOL Sniper
### A SOLANA sniper bot designed to frontrun telegram channels announcements
Files: `sniper.py` (auto-buy) · `logger.py` (call log) · `montecarlo.py` (projection) · `calls.csv` (data) · `.env` (config)

## Setup (once)
```
pip install -r requirements.txt
cp .env.example .env          # then fill TG_API_ID, TG_API_HASH, TG_CHANNELS, SOL_PRIVATE_KEY...
```

## Sniper — listen + auto-buy
```
python sniper.py              # 1st run: asks for your Telegram number + login code
```
Settings in `.env`: `BUY_SOL` (bet), `SLIPPAGE`, `PRIORITY_FEE` (raise it if txs don't land),
`AUTOSELL=true` + `TP_MULT` / `SL_MULT` + `PUMPPORTAL_API_KEY` for auto-exit.

## Logger — record every call
```
python logger.py add --mint <CA> --bet <size> --pnl <gain%> --note "<KOL/time>"
python logger.py add --mint <CA> --bet <size> --entry <price> --exit <price> --ath <price>
python logger.py list         # history
python logger.py stats        # win-rate, avg win/loss, % rugs, growth/call
```

## Monte Carlo — project the bankroll
```
# Now (assumptions; sweep --p-tail 0/0.03/0.05/0.08)
python montecarlo.py --p-win 0.85 --win 50 --loss -40 --p-tail 0.05 --tail -90 --start 3 --bet-frac 0.30

# Later (30+ logged calls — runs on YOUR real numbers)
python montecarlo.py --empirical --start 3 --bet-frac 0.30
```
Options: `--horizons 5,10,20` · `--sims 50000` · `--ruin 1.0`
Read in the output: **Kelly ratio** (>2x = over-betting) and the **<capital** column.

## Handy env vars
```
BET_FRAC=0.20 python logger.py stats             # growth computed at 20% bet size
CALLS_CSV=/path/my.csv python logger.py stats    # use another log file
```

## The 2 rules that make it all work
1. Log losses and rugs **too** — an all-green log overstates your edge and makes you over-bet.
2. `--pnl` is **buy→sell actual**, never buy→ATH (you don't sell the perfect top).

## Risk reminders
- Dedicated **burner wallet**, funded at the minimum (private key sits in RAM while the bot runs).
- Telethon userbot = your account on autopilot → run it on a **secondary account**.
- Set a bankroll stop (e.g. cut at ~1.5 SOL) and a **fixed-fraction** bet size.
- None of this is financial advice.

## Telegram token notifier

Add a small Telegram bot that watches messages for token contract addresses and replies with token info + a GMGN deep link.

Setup:
```
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="<your-bot-token>"       # Windows: set TELEGRAM_BOT_TOKEN=...
export GMGN_DEEP_LINK="https://gmgn.app/token"     # optional deep link base
python telegram_bot.py
```

Notes:
- Add the bot to the channel or chat you want to monitor and give it permission to read messages.
- The script uses CoinGecko's public API to fetch token metadata. If CoinGecko doesn't know the contract, you'll only get the deep link.
