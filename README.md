# Telegram Sniper Bot

A Python Telegram bot that listens to selected channels, extracts Solana token mint addresses, sends buy transactions through PumpPortal, and optionally notifies and monitors the position.

## Features

- Listen to Telegram channels for token announcements
- Extract token mint addresses from messages
- Send buy transactions via PumpPortal
- Notify the user after a successful buy
- Log trades to CSV
- Optional auto-sell with take-profit and stop-loss monitoring

## Project structure

- `sniper.py` — main bot logic and buy flow
- `notify.py` — Telegram notification helper
- `logger.py` — trade logging and CSV handling
- `telegram_bot.py` — additional Telegram bot utilities
- `requirements.txt` — Python dependencies
- `FEATURES.md` — feature ideas and roadmap
- `ROADMAP.md` — prioritized implementation plan
- `SPECIFICATIONS.md` — project requirements

## Requirements

Python 3.10+ is recommended.

Install dependencies:

```bash
pip install -r requirements.txt
```

## Configuration

Set the required environment variables before running the bot:

```bash
TG_API_ID=...
TG_API_HASH=...
TG_CHANNELS=...
SOL_PRIVATE_KEY=...
SOL_RPC_URL=...
BUY_SOL=0.5
SLIPPAGE=15
PRIORITY_FEE=0.001
AUTOSELL=false
TP_MULT=2.0
SL_MULT=0.5
PUMPPORTAL_API_KEY=...
```

## Run

Start the sniper bot:

```bash
python sniper.py
```

## Usage notes

- Use a dedicated wallet with funds you can afford to lose.
- Keep your private keys and API secrets secure.
- The bot is intended for experimentation and automation and should be used responsibly.
