from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
from dataclasses import replace

from kol_sniper.config import Settings
from kol_sniper.health import HealthServer
from kol_sniper.runtime import create_runtime
from notify import Notifier


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


async def dry_run_signal(settings: Settings, text: str) -> int:
    safe = replace(settings, dry_run=True)
    runtime = create_runtime(safe)
    try:
        result = await runtime.service.handle_signal(
            source="cli",
            message_id=f"manual-{__import__('time').time_ns()}",
            text=text,
        )
        print(json.dumps(result.__dict__ if result else {"matched": False}, default=str, indent=2))
        return 0 if result else 2
    finally:
        await runtime.close()


async def run_listener(settings: Settings) -> None:
    from telethon import TelegramClient, events  # type: ignore[import-untyped]

    missing = []
    if not settings.telegram_api_id:
        missing.append("TELEGRAM_API_ID")
    if not settings.telegram_api_hash:
        missing.append("TELEGRAM_API_HASH")
    if not settings.telegram_channels:
        missing.append("TELEGRAM_CHANNELS")
    if missing:
        raise ValueError("listener configuration missing: " + ", ".join(missing))

    notifier = Notifier(settings.notification_bot_token, settings.notification_chat_id)
    runtime = create_runtime(settings, notifier.send if notifier.enabled else None)
    health = HealthServer(settings.health_host, settings.health_port, runtime.store)
    client = TelegramClient(
        settings.telegram_session,
        settings.telegram_api_id,
        settings.telegram_api_hash,
        sequential_updates=False,
    )

    @client.on(events.NewMessage(chats=list(settings.telegram_channels)))
    async def on_message(event) -> None:
        message = event.message
        await runtime.service.handle_signal(
            source=str(event.chat_id),
            message_id=str(message.id),
            text=message.raw_text or "",
            message_at=message.date,
        )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        await runtime.service.start()
        await client.start()
        health.start()
        logging.getLogger(__name__).info(
            "listener started (%s) for %d channel(s)",
            "DRY RUN" if settings.dry_run else "LIVE",
            len(settings.telegram_channels),
        )
        disconnected = asyncio.ensure_future(client.disconnected)
        stopped = asyncio.create_task(stop.wait())
        await asyncio.wait({disconnected, stopped}, return_when=asyncio.FIRST_COMPLETED)
        disconnected.cancel()
        stopped.cancel()
    finally:
        health.stop()
        await client.disconnect()
        await runtime.close()


def main() -> int:
    os.umask(0o077)
    parser = argparse.ArgumentParser(description="Low-latency, fail-closed Pump.fun signal executor")
    parser.add_argument("--check", action="store_true", help="validate static configuration")
    parser.add_argument(
        "--dry-run-signal", metavar="TEXT", help="parse and persist one signal without trading"
    )
    args = parser.parse_args()
    settings = Settings.from_env()
    configure_logging(settings.log_level)
    if args.check:
        errors = settings.errors(live=not settings.dry_run)
        print(json.dumps({"ok": not errors, "dry_run": settings.dry_run, "errors": errors}, indent=2))
        return 0 if not errors else 1
    if args.dry_run_signal:
        return asyncio.run(dry_run_signal(settings, args.dry_run_signal))
    settings.require_valid(live=not settings.dry_run)
    asyncio.run(run_listener(settings))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130) from None
