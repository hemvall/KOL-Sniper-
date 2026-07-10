@echo off
cd /d %~dp0
start "sniper" python sniper.py
start "telegram_bot" python telegram_bot.py
echo Started sniper.py and telegram_bot.py
