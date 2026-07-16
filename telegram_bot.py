from __future__ import annotations

import json
import logging
import os

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from kol_sniper.analytics import performance_snapshot
from kol_sniper.config import Settings
from kol_sniper.storage import Store

logger = logging.getLogger(__name__)
os.umask(0o077)
settings = Settings.from_env()
store = Store(settings.database_path)


def authorized(update: Update) -> bool:
    user = update.effective_user
    return bool(user and str(user.id) in settings.admin_user_ids)


async def reply(update: Update, text: str) -> None:
    if update.effective_message:
        await update.effective_message.reply_text(text[:4_000])


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await reply(
        update,
        json.dumps(
            {
                "risk": store.risk_snapshot(),
                "performance": performance_snapshot(store),
                "metrics": store.metrics(),
            },
            indent=2,
        ),
    )


async def positions(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await reply(update, json.dumps(store.open_positions(), indent=2, default=str) or "No open positions")


async def orders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not authorized(update):
        return
    await reply(update, json.dumps(store.recent_orders(10), indent=2, default=str))


async def post_init(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("status", "Health and risk limits"),
            BotCommand("positions", "Open positions"),
            BotCommand("orders", "Recent orders"),
        ]
    )


def main() -> None:
    if not settings.notification_bot_token:
        raise ValueError("NOTIFICATION_BOT_TOKEN is required")
    if not settings.admin_user_ids:
        raise ValueError("ADMIN_USER_IDS is required")
    app = Application.builder().token(settings.notification_bot_token).post_init(post_init).build()
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("positions", positions))
    app.add_handler(CommandHandler("orders", orders))
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
