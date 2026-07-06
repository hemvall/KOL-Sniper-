import os
import re
import logging
import asyncio
from typing import Optional

import requests
from telegram import __version__ as ptb_version
from telegram import InputMediaPhoto
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes
from telegram import Update

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN_REGEX = re.compile(r"0x[a-fA-F0-9]{40}")
COINGECKO_CONTRACT_URL = "https://api.coingecko.com/api/v3/coins/ethereum/contract/{}"


def fetch_token_info(address: str) -> Optional[dict]:
    """Fetch token info from CoinGecko by contract address."""
    url = COINGECKO_CONTRACT_URL.format(address.lower())
    try:
        r = requests.get(url, timeout=10)
        if r.status_code != 200:
            logger.info("CoinGecko returned %s for %s", r.status_code, address)
            return None
        data = r.json()
        return data
    except Exception as e:
        logger.exception("Error fetching token info: %s", e)
        return None


def format_token_message(data: dict, contract: str, deep_link_base: str) -> str:
    name = data.get("name") or "Unknown"
    symbol = data.get("symbol") or ""
    market = data.get("market_data", {})
    price = market.get("current_price", {}).get("usd")
    mcap = market.get("market_cap", {}).get("usd")
    change24 = market.get("price_change_percentage_24h")
    homepage = data.get("links", {}).get("homepage", [None])[0]

    lines = [f"*{name}* ({symbol})", f"Contract: `{contract}`"]
    if price is not None:
        lines.append(f"Price (USD): ${price:,.6g}")
    if mcap is not None:
        lines.append(f"Market Cap (USD): ${mcap:,.0f}")
    if change24 is not None:
        lines.append(f"24h change: {change24:.2f}%")
    if homepage:
        lines.append(f"Website: {homepage}")

    deep_link = deep_link_base.rstrip("/") + "/" + contract
    lines.append(f"GMGN: {deep_link}")

    return "\n".join(lines)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = update.message.text or ""
    found = TOKEN_REGEX.findall(text)
    if not found:
        return

    deep_link_base = os.getenv("GMGN_DEEP_LINK", "https://gmgn.app/token")

    for contract in set(found):
        await update.message.reply_text(f"Looking up {contract}...")
        data = await asyncio.to_thread(fetch_token_info, contract)
        if not data:
            await update.message.reply_text(f"No data found for {contract}.\nGMGN link: {deep_link_base.rstrip('/')}/{contract}")
            continue

        msg = format_token_message(data, contract, deep_link_base)
        # Send image preview if available
        image = data.get("image", {}).get("large")
        try:
            if image:
                await update.message.reply_photo(photo=image, caption=msg, parse_mode='Markdown')
            else:
                await update.message.reply_text(msg, parse_mode='Markdown')
        except Exception:
            # Fallback to plain text
            await update.message.reply_text(msg)


def main() -> None:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("Please set TELEGRAM_BOT_TOKEN environment variable.")
        return

    logger.info("python-telegram-bot version: %s", ptb_version)

    app = ApplicationBuilder().token(token).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Starting bot, listening for messages containing contract addresses...")
    app.run_polling()


if __name__ == "__main__":
    main()
