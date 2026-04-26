import asyncio
import time
import json

from telegram import constants
from telegram.ext import ContextTypes

from star_attendance.bot.ui import get_back_button, get_main_menu, get_progress_bar
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
            is_aborted = store.is_mass_stop_requested()
            status_icon = "🛑" if is_aborted else "✅"
            status_title = "ABORTED" if is_aborted else "COMPLETED"
            status_code = "EMERGENCY_STOP" if is_aborted else "SUCCESSFUL_SHUTDOWN"

            final_msg = (
                f"{status_icon} <b>MASS {label} {status_title}</b>\n────────────────\n"
                f"📊 <b>Total Processed:</b> <code>{status.get('pos', '0')} / {status.get('total', '0')}</code>\n"
                f"⏱ <b>Total Duration:</b> <code>{time.time() - start_time:.1f}s</code>\n"
                f"────────────────\n"
                f"Status: <code>{status_code}</code>"
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
                from telegram import InlineKeyboardMarkup, InlineKeyboardButton
                keyboard = [
                    [InlineKeyboardButton("🛑 BATALKAN PROSES", callback_data="trigger_stop")],
                    [get_back_button()]
                ]
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=msg,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=constants.ParseMode.HTML
                )
                last_text = msg
            except Exception as e:
                # If message is deleted or edited by someone else, stop monitoring
                if "Message is not modified" not in str(e):
                    break
        
        await asyncio.sleep(1.5)
