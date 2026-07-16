from __future__ import annotations

import asyncio
import logging
import threading

import requests

logger = logging.getLogger(__name__)


class Notifier:
    def __init__(self, token: str | None, chat_id: str | None, timeout_seconds: float = 3.0):
        self.token = token
        self.chat_id = chat_id
        self.timeout_seconds = timeout_seconds
        self._local = threading.local()

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.chat_id)

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            self._local.session = session
        return session

    def send_sync(self, message: str) -> bool:
        if not self.enabled:
            return False
        try:
            response = self._session().post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                json={"chat_id": self.chat_id, "text": message, "disable_web_page_preview": True},
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            return True
        except requests.RequestException as exc:
            # Requests exceptions may embed the bot-token URL.
            logger.error("Telegram notification failed: %s", type(exc).__name__)
            return False

    async def send(self, message: str) -> None:
        await asyncio.to_thread(self.send_sync, message)


def send_telegram_message(message: str) -> bool:
    """Backward-compatible helper using the current environment."""
    import os

    return Notifier(
        os.getenv("NOTIFICATION_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN"),
        os.getenv("NOTIFICATION_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID"),
    ).send_sync(message)
