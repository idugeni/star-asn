import asyncio
import json
import time

from telegram import constants
from telegram.ext import ContextTypes

from star_attendance.bot.ui import get_back_button, get_dashboard_text, get_main_menu, get_progress_bar
from star_attendance.notifier import notifier
from star_attendance.runtime import get_store

store = get_store()


async def monitor_mass_progress(context: ContextTypes.DEFAULT_TYPE, chat_id, message_id, action, telegram_id: int):
    """
    Polls the mass status from PostgreSQL and updates the Telegram UI with a cool dashboard.
    Also sends a mass completion summary to the log group when all workers finish.
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

            is_aborted = store.is_mass_stop_requested()
            processed = int(status.get("pos", 0))
            total = int(status.get("total", 0))
            elapsed = time.time() - start_time

            # Update admin UI
            final_msg = notifier.format_mass_completion_msg(
                action=action,
                processed=processed,
                total=total,
                duration=elapsed,
                is_aborted=is_aborted,
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

            # Send mass completion summary to log group
            try:
                notifier.send_message(
                    notifier.format_mass_completion_msg(
                        action=action,
                        processed=processed,
                        total=total,
                        duration=elapsed,
                        is_aborted=is_aborted,
                    ),
                    to_admin=False,
                    to_group=True,
                )
            except Exception:
                pass

            # Auto-refresh to dashboard after 5 seconds
            await asyncio.sleep(5)
            try:
                dashboard_text = await get_dashboard_text(telegram_id)
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=dashboard_text,
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

        log_text = "\n".join([f"<code>{l}</code>" for l in logs]) if logs else "<i>Menunggu worker...</i>"

        label = "PRESENSI MASUK" if action.lower() == "in" else "PRESENSI PULANG"
        msg = (
            f"🚀 <b>MENGORKESTRASI MASS {label}</b>\n"
            f"────────────────\n"
            f"📊 <b>Kemajuan:</b> {progress}\n"
            f"👤 <b>Terbaru:</b> <code>{status.get('last_nip', '---')}</code>\n"
            f"⏱ <b>Berlalu:</b> <code>{time.time() - start_time:.1f}d</code>\n"
            f"────────────────\n"
            f"📝 <b>STATUS LANGSUNG:</b>\n"
            f"{log_text}\n"
            f"────────────────"
        )

        if msg != last_text:
            try:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup

                keyboard = [
                    [InlineKeyboardButton("🛑 BATALKAN PROSES", callback_data="trigger_stop")],
                    [get_back_button()],
                ]
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=msg,
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode=constants.ParseMode.HTML,
                )
                last_text = msg
            except Exception as e:
                # If message is deleted or edited by someone else, stop monitoring
                if "Message is not modified" not in str(e):
                    break

        await asyncio.sleep(1.5)
