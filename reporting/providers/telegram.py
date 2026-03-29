from telegram import Bot
import asyncio
import logging

logger = logging.getLogger(__name__)

async def send_telegram_message(bot_token, chat_id, message):
    """
    Sends a message to a Telegram chat using the bot token.
    """
    try:
        bot = Bot(token=bot_token)
        async with bot:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
            logger.info(f"Telegram message sent to {chat_id}")
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        raise
