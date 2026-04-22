import asyncio
import logging
from telegram import Message, Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

async def auto_delete_message(message: Message, delay: int = 60):
    """
    Schedules a message for deletion after a delay.
    Used for temporary status messages, errors, and confirmations.
    """
    if not message:
        return
    
    # We use asyncio.create_task to not block the current handler
    async def task():
        await asyncio.sleep(delay)
        try:
            await message.delete()
            logger.debug(f"Auto-deleted message {message.message_id}")
        except Exception as e:
            # Silent failure if already deleted or permissions missing
            pass
            
    asyncio.create_task(task())

async def clean_incoming(update: Update):
    """
    Deletes the user's incoming message immediately to keep the chat history clean.
    """
    if update.message:
        try:
            await update.message.delete()
        except Exception:
            pass

async def delete_after(message: Message, delay: int = 10):
    """Helper for one-shot deletion."""
    await auto_delete_message(message, delay)
