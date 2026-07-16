@echo off
if not exist .venv\Scripts\python.exe (
  echo Create the virtual environment and install requirements first.
  exit /b 1
)
start "KOL Sniper" .venv\Scripts\python.exe sniper.py
start "KOL Sniper Admin" .venv\Scripts\python.exe telegram_bot.py
