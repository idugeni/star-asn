import asyncio
import time

from telegram import constants
from telegram.ext import ContextTypes

from star_attendance.bot.ui import get_main_menu, get_progress_bar
from star_attendance.runtime import get_store

store = get_store()


async def monitor_mass_progress(context: ContextTypes.DEFAULT_TYPE, chat_id, message_id, action, telegram_id: int):
    """
    Polls the mass status from PostgreSQL (Legacy name: RedisStore) and updates the Telegram UI.
    """
    start_time = time.time()
    last_text = ""

    while True:
        # get_mass_status now reads from PostgreSQL GlobalSettings table
        status = store.get_mass_status()

        if status.get("active") != "1":
            # Buffer for slow start
            if time.time() - start_time < 5:
                await asyncio.sleep(1)
                continue

            final_msg = (
                f"✅ <b>MASS {action.upper()} COMPLETED</b>\n────────────────\nStatus: <code>SUCCESSFUL_SHUTDOWN</code>"
            )
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=final_msg,
                    reply_markup=await get_main_menu(telegram_id),
                    parse_mode=constants.ParseMode.HTML,
                )
            except Exception:
                pass
            break

        pos, total = int(status.get("pos", 0)), int(status.get("total", 0))
        # success/fail counters are now incrementally written to AuditLog table
        # For the active UI, we can just show the current position/total
        progress = get_progress_bar(pos, total)

        msg = (
            f"🚀 <b>ORCHESTRATING MASS {action.upper()}</b>\n"
            f"────────────────\n"
            f"📊 <b>Progress:</b> {progress}\n"
            f"👤 <b>Target:</b> <code>{status.get('last_nip', '---')}</code>\n"
            f"⏱ <b>Elapsed:</b> {time.time() - start_time:.1f}s\n"
            f"────────────────"
        )

        if msg != last_text:
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id, message_id=message_id, text=msg, parse_mode=constants.ParseMode.HTML
                )
                last_text = msg
            except Exception:
                pass

        await asyncio.sleep(2)
