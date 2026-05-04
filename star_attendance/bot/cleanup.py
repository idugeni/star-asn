import asyncio
import logging

from telegram import Message, Update
from telegram.ext import Application

from star_attendance.runtime import get_store

logger = logging.getLogger(__name__)

# Telegram error descriptions that indicate safe-to-ignore conditions
_SAFE_DELETE_ERRORS = {
    "message to delete not found",
    "message can't be deleted",
    "message is too old to delete",
    "bad request",
    "forbidden",
    "not found",
}


def _is_safe_delete_error(exc: Exception) -> bool:
    """Check if a deletion error is safe to ignore (message already gone, no permission, etc.)."""
    exc_msg = str(exc).lower()
    return any(err in exc_msg for err in _SAFE_DELETE_ERRORS)


def _is_private_chat(message: Message) -> bool:
    """Check if a message is from a private (1-on-1) chat."""
    return message.chat.type == "private"


async def auto_delete_message(message: Message, delay: int = 60):
    """
    Schedules a message for deletion after a delay.
    Only records and deletes in private chats. In groups, messages are kept
    for audit trail and because bots often lack delete permissions.
    """
    if not message:
        return

    # Only record for cleanup in private chats
    if _is_private_chat(message):
        await record_message(message)

    async def task():
        await asyncio.sleep(delay)
        try:
            await message.delete()
            logger.debug(f"Auto-deleted message {message.message_id} in chat {message.chat_id}")
        except Exception as exc:
            if _is_safe_delete_error(exc):
                logger.debug(
                    f"Safe-ignore: could not delete message {message.message_id} in chat {message.chat_id}: {exc}"
                )
            else:
                logger.warning(f"Failed to auto-delete message {message.message_id} in chat {message.chat_id}: {exc}")

    asyncio.create_task(task())


async def clean_incoming(update: Update):
    """
    Deletes the user's incoming message immediately to keep the chat history clean.
    Only deletes in private chats — in groups, user messages are preserved
    for context and because the bot may lack delete permissions.
    """
    if not update.message:
        return

    # Only delete in private chats for safety
    if not _is_private_chat(update.message):
        return

    try:
        await update.message.delete()
    except Exception as exc:
        if _is_safe_delete_error(exc):
            logger.debug(f"Safe-ignore: could not delete incoming message: {exc}")
        else:
            logger.warning(f"Failed to delete incoming message: {exc}")


async def delete_after(message: Message, delay: int = 10):
    """Helper for one-shot deletion."""
    await auto_delete_message(message, delay)


async def record_message(message: Message):
    """Records a bot message in the database for future auto-cleanup.
    Only records in private chats to avoid attempting to delete messages
    in groups where the bot may lack permission.
    """
    if not message or not hasattr(message, "from_user") or not message.from_user or not message.from_user.is_bot:
        return

    # Only record in private chats
    if not _is_private_chat(message):
        return

    try:
        store = get_store()
        target_tid = message.chat.id
        store.record_bot_message(telegram_id=target_tid, chat_id=message.chat.id, message_id=message.message_id)
    except Exception as e:
        logger.error(f"Failed to record bot message: {e}")


async def cleanup_old_messages(application: Application):
    """Background task to delete bot messages and screenshots older than 24 hours.
    Only processes messages in private chats. Handles Telegram rate limits
    and safe-to-ignore errors gracefully.
    """
    store = get_store()
    logger.info("Cleaning up old Telegram messages and images/screenshots...")

    # 1. Clean up old bot messages
    old_messages = store.get_old_bot_messages(hours=24)
    deleted_count = 0
    skipped_count = 0

    if old_messages:
        for msg in old_messages:
            try:
                await application.bot.delete_message(chat_id=msg["chat_id"], message_id=msg["message_id"])
                deleted_count += 1
            except Exception as exc:
                if _is_safe_delete_error(exc):
                    logger.debug(f"Could not delete message {msg['message_id']} in chat {msg['chat_id']}: {exc}")
                else:
                    logger.warning(f"Unexpected error deleting message {msg['message_id']} in chat {msg['chat_id']}: {exc}")
                skipped_count += 1

            # Always delete the record from DB to avoid re-processing
            try:
                store.delete_bot_message_record(msg["id"])
            except Exception as e:
                logger.error(f"Failed to delete bot message record {msg.get('id')}: {e}")

            # Delay to avoid hitting Telegram flood limits (30 messages/sec)
            await asyncio.sleep(0.05)

        logger.info(f"Cleanup done: {deleted_count} deleted, {skipped_count} skipped.")

    # 2. Clean up old images/screenshots older than 24 hours
    import glob
    import os
    import time

    # Root directory or current directory screenshots
    for path in glob.glob("*.png"):
        try:
            if os.path.isfile(path) and time.time() - os.path.getmtime(path) > 86400:
                os.remove(path)
                logger.info(f"Auto-deleted old local screenshot: {path}")
        except Exception as e:
            logger.error(f"Failed to delete old local screenshot {path}: {e}")

    # Debug directory screenshots
    debug_dir = r"C:\tmp\star_asn_debug"
    if os.path.isdir(debug_dir):
        for path in glob.glob(os.path.join(debug_dir, "*.png")):
            try:
                if os.path.isfile(path) and time.time() - os.path.getmtime(path) > 86400:
                    os.remove(path)
                    logger.info(f"Auto-deleted old debug screenshot: {path}")
            except Exception as e:
                logger.error(f"Failed to delete old debug screenshot {path}: {e}")

    # 3. Clean up dangling/unused Docker images
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", "image", "prune", "-a", "-f",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await process.wait()
        logger.info("Auto-pruned unused Docker images.")
    except Exception as e:
        logger.error(f"Failed to prune Docker images: {e}")


async def clear_chat_history(chat_id: int, application: Application):
    """Manually clear all recorded bot messages for a specific chat immediately."""
    store = get_store()
    msgs = store.get_all_bot_messages_for_chat(chat_id)
    deleted_count = 0
    skipped_count = 0

    if msgs:
        for msg in msgs:
            try:
                await application.bot.delete_message(chat_id=msg["chat_id"], message_id=msg["message_id"])
                deleted_count += 1
            except Exception as exc:
                if _is_safe_delete_error(exc):
                    logger.debug(f"Could not delete message {msg['message_id']} in chat {msg['chat_id']}: {exc}")
                else:
                    logger.warning(f"Unexpected error deleting message {msg['message_id']} in chat {msg['chat_id']}: {exc}")
                skipped_count += 1

            try:
                store.delete_bot_message_record(msg["id"])
            except Exception as e:
                logger.error(f"Failed to delete bot message record {msg.get('id')}: {e}")

            await asyncio.sleep(0.05)
        logger.info(f"Manual cleanup for chat {chat_id} done: {deleted_count} deleted, {skipped_count} skipped.")


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
