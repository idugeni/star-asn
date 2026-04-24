import asyncio
import logging
from telegram import Message, Update
from telegram.ext import Application
from star_attendance.runtime import get_store

logger = logging.getLogger(__name__)

async def auto_delete_message(message: Message, delay: int = 60):
    """
    Schedules a message for deletion after a delay.
    Used for temporary status messages, errors, and confirmations.
    """
    if not message:
        return
    
    # Record for 24h cleanup as well
    await record_message(message)
    
    # We use asyncio.create_task to not block the current handler
    async def task():
        await asyncio.sleep(delay)
        try:
            await message.delete()
            logger.debug(f"Auto-deleted message {message.message_id}")
        except Exception:
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

async def record_message(message: Message):
    """Records a bot message in the database for future auto-cleanup."""
    if not message or not hasattr(message, "from_user") or not message.from_user or not message.from_user.is_bot:
        return
    
    try:
        store = get_store()
        target_tid = message.chat.id
        store.record_bot_message(
            telegram_id=target_tid,
            chat_id=message.chat.id,
            message_id=message.message_id
        )
    except Exception as e:
        logger.error(f"Failed to record bot message: {e}")

async def cleanup_old_messages(application: Application):
    """Background task to delete bot messages older than 24 hours."""
    store = get_store()
    logger.info("Cleaning up old Telegram messages...")
    
    # Get messages older than 24 hours
    old_messages = store.get_old_bot_messages(hours=24)
    if not old_messages:
        return

    deleted_count = 0
    for msg in old_messages:
        try:
            await application.bot.delete_message(
                chat_id=msg["chat_id"],
                message_id=msg["message_id"]
            )
            deleted_count += 1
        except Exception as e:
            # Message might already be deleted or too old to delete (> 48h)
            logger.debug(f"Could not delete message {msg['message_id']} in chat {msg['chat_id']}: {e}")
        
        # Always delete the record from DB to avoid re-processing
        store.delete_bot_message_record(msg["id"])
        
        # Small delay to avoid hitting Telegram flood limits
        await asyncio.sleep(0.05)

    if deleted_count > 0:
        logger.info(f"Successfully cleaned up {deleted_count} old messages.")

async def start_global_cleanup_task(application: Application):
    """
    Infinite loop to run the cleaner task every hour.
    Following best practices for Telegram SPA experience.
    """
    logger.info("Global message auto-cleaner (24h) service starting...")
    while True:
        try:
            await cleanup_old_messages(application)
        except Exception as e:
            logger.error(f"Error in global cleanup loop: {e}")
        
        # Sleep for 1 hour
        await asyncio.sleep(3600)
