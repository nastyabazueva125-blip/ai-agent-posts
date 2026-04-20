import asyncio
import logging
from telegram import Bot
from telegram.constants import ParseMode
import config

logger = logging.getLogger(__name__)


async def _send_message(text: str) -> bool:
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    async with bot:
        await bot.send_message(
            chat_id=config.TELEGRAM_CHANNEL_ID,
            text=text,
            parse_mode=ParseMode.HTML,
        )
    return True


def publish_to_channel(text: str) -> bool:
    try:
        return asyncio.run(_send_message(text))
    except Exception as e:
        logger.error("Telegram send failed: %s", e)
        return False
