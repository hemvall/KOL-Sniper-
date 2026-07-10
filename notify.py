import os
import requests
import logging

logger = logging.getLogger(__name__)


def send_telegram_notification(text: str) -> bool:
    """Send a simple Telegram message using a bot token + chat id from env.

    Expects `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to be set.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        logger.debug("Telegram notify not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing)")
        return False

    token = token.strip()
    if (token.startswith('"') and token.endswith('"')) or (token.startswith("'") and token.endswith("'")):
        token = token[1:-1]

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        r = requests.post(url, json=payload, timeout=10)
        if r.status_code != 200:
            logger.error("Telegram send failed %s: %s", r.status_code, r.text[:200])
            return False
        return True
    except Exception:
        logger.exception("Telegram send failed")
        return False
