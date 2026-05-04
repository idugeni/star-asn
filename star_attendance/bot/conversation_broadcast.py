from __future__ import annotations

import asyncio

from telegram import Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from star_attendance.bot.constants import WAIT_BROADCAST_MSG, WAIT_SEARCH_QUERY
from star_attendance.bot.ui import get_users_keyboard, is_admin
from star_attendance.core.config import settings

from .conversation_shared import store


async def start_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not query.from_user or not is_admin(query.from_user.id):
        return ConversationHandler.END
    await query.answer()
    if query.message and isinstance(query.message, Message):
        await query.message.reply_text(
            "📢 <b>PENGIRIMAN BROADCAST</b>\n────────────────\n"
            "Masukkan pesan yang ingin dikirimkan ke SELURUH personel terdaftar:",
            parse_mode="HTML",
        )
    return WAIT_BROADCAST_MSG


async def exec_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return WAIT_BROADCAST_MSG
    message_text = update.message.text
    telegram_ids = store.get_all_telegram_ids()

    success_count = 0
    await update.message.reply_text(f"⏳ Sedang mengirim pesan ke {len(telegram_ids)} user...")

    for telegram_id in telegram_ids:
        try:
            await context.bot.send_message(
                chat_id=telegram_id,
                text=f"📢 <b>PENGUMUMAN SISTEM</b>\n────────────────\n{message_text}",
                parse_mode="HTML",
            )
            success_count += 1
            await asyncio.sleep(settings.BOT_BROADCAST_DELAY)
        except Exception:
            pass

    from telegram import InlineKeyboardMarkup

    from star_attendance.bot.ui import get_back_button

    await update.message.reply_text(
        f"✅ Broadcast selesai: {success_count} terkirim, {len(telegram_ids) - success_count} gagal.",
        reply_markup=InlineKeyboardMarkup([[get_back_button()]]),
    )
    return ConversationHandler.END


async def start_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query or not query.from_user or not is_admin(query.from_user.id):
        return ConversationHandler.END
    await query.answer()
    if query.message and isinstance(query.message, Message):
        await query.message.reply_text(
            "🔍 <b>PENCARIAN PERSONEL</b>\n────────────────\nMasukkan Nama atau NIP yang ingin dicari:",
            parse_mode="HTML",
        )
    return WAIT_SEARCH_QUERY


async def exec_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return WAIT_SEARCH_QUERY
    query_text = update.message.text
    keyboard = await get_users_keyboard(page=0, search_query=query_text)
    await update.message.reply_text(
        f"🔍 Hasil pencarian untuk: <code>{query_text}</code>",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return ConversationHandler.END
