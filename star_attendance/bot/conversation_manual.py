from __future__ import annotations

from typing import cast

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from star_attendance.bot.constants import WAIT_MAN_ACTION
from star_attendance.core.options import RuntimeOptions
from star_attendance.core.processor import process_single_user
from star_attendance.core.utils import get_action_label

from .conversation_shared import get_user_id, store


async def start_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not query.message:
        return ConversationHandler.END
    await query.answer()

    tid = get_user_id(update)
    user = store.get_user_by_telegram_id(tid)
    if not user:
        if isinstance(query.message, Message):
            await query.message.reply_text("Anda belum terdaftar. Silakan daftar terlebih dahulu.")
        return ConversationHandler.END

    keyboard = [
        [InlineKeyboardButton("✅ ABSEN MASUK SEKARANG", callback_data="man_do_in")],
        [InlineKeyboardButton("🏠 ABSEN PULANG SEKARANG", callback_data="man_do_out")],
        [InlineKeyboardButton("❌ BATAL", callback_data="man_cancel")],
    ]
    if isinstance(query.message, Message):
        await query.message.reply_text(
            f"<b>KONFIRMASI ABSENSI INSTAN</b>\nTarget: {user['nama']}\n\nApakah Anda yakin ingin melakukan absensi sekarang?",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML",
        )
    return WAIT_MAN_ACTION


async def man_execute(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not query.message:
        return ConversationHandler.END
    await query.answer()

    data = cast(str, query.data)
    if data == "man_cancel":
        if isinstance(query.message, Message):
            await query.message.edit_text("Operasi dibatalkan.")
        return ConversationHandler.END

    action = data.split("_")[-1]
    tid = get_user_id(update)
    user = store.get_user_by_telegram_id(tid)
    if not user or not isinstance(query.message, Message):
        return ConversationHandler.END

    await query.message.edit_text(
        f"<b>🤖 OTOMASI {get_action_label(action)}</b>\n────────────────\n⏳ Mengeksekusi manual {get_action_label(action)}...",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ KEMBALI", callback_data="main_menu")]])
    )
    status_message = query.message
    msg_id_container = {"id": status_message.message_id}
    last_status = [f"⏳ Mengeksekusi manual {get_action_label(action)}..."]

    async def progress_callback(text: str) -> None:
        if text == last_status[0]:
            return
        last_status[0] = text
        try:
            await status_message.edit_text(
                f"<b>🤖 OTOMASI {get_action_label(action)}</b>\n────────────────\n🔄 {text}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("◀️ KEMBALI", callback_data="main_menu")]])
            )
        except Exception:
            pass

    options = RuntimeOptions.from_store(action, store=store)
    try:
        result, full_message = await process_single_user(
            user,
            options,
            1,
            1,
            is_mass=False,
            status_callback=progress_callback,
            user_message_id=msg_id_container,
        )
    except Exception as exc:
        await status_message.edit_text(
            f"❌ <b>EKSEKUSI MANUAL GAGAL</b>\n────────────────\n<code>{exc}</code>",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    if full_message:
        await status_message.edit_text(full_message, parse_mode="HTML")
    else:
        await status_message.edit_text("✅ Manual Berhasil!" if result else "❌ Manual Gagal.")

    return ConversationHandler.END
