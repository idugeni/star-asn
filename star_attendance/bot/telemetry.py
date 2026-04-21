import asyncio
import time
import json

from telegram import constants
from telegram.ext import ContextTypes

from star_attendance.bot.ui import get_main_menu, get_progress_bar
from star_attendance.runtime import get_store

store = get_store()


async def monitor_mass_progress(context: ContextTypes.DEFAULT_TYPE, chat_id, message_id, action, telegram_id: int):
    """
    Polls the mass status from PostgreSQL and updates the Telegram UI with a cool dashboard.
    """
    start_time = time.time()
    last_text = ""

    while True:
        status = store.get_mass_status()

        if status.get("active") != "1":
            # Buffer for slow start
            if time.time() - start_time < 5:
                await asyncio.sleep(1)
                continue

            label = "PRESENSI MASUK" if action.lower() == "in" else "PRESENSI PULANG"
            final_msg = (
                f"✅ <b>MASS {label} COMPLETED</b>\n────────────────\n"
                f"📊 <b>Total Processed:</b> <code>{status.get('pos', '0')} / {status.get('total', '0')}</code>\n"
                f"⏱ <b>Total Duration:</b> <code>{time.time() - start_time:.1f}s</code>\n"
                f"────────────────\n"
                f"Status: <code>SUCCESSFUL_SHUTDOWN</code>"
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
        progress = get_progress_bar(pos, total)
        
        # Parse live logs
        logs_raw = status.get("log", "[]")
        try:
            logs = json.loads(logs_raw)
        except Exception:
            logs = []
            
        log_text = "\n".join([f"<code>{l}</code>" for l in logs]) if logs else "<i>Waiting for workers...</i>"

        label = "PRESENSI MASUK" if action.lower() == "in" else "PRESENSI PULANG"
        msg = (
            f"🚀 <b>ORCHESTRATING MASS {label}</b>\n"
            f"────────────────\n"
            f"📊 <b>Progress:</b> {progress}\n"
            f"👤 <b>Latest:</b> <code>{status.get('last_nip', '---')}</code>\n"
            f"⏱ <b>Elapsed:</b> <code>{time.time() - start_time:.1f}s</code>\n"
            f"────────────────\n"
            f"📝 <b>LIVE STATUS:</b>\n"
            f"{log_text}\n"
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

        await asyncio.sleep(1.5) # Faster updates for "cool" effect
