from __future__ import annotations

from typing import Any, cast

from telegram import Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from star_attendance.bot.constants import WAIT_REG_NAME, WAIT_REG_NIP, WAIT_REG_PASS, WAIT_REG_UPT
from star_attendance.runtime import get_internal_api_client

from .conversation_shared import store
from .ui import get_upt_keyboard

internal_api = get_internal_api_client()


async def start_reg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    message = (
        "📝 <b>REGISTRASI PERSONEL BARU</b>\n────────────────\n"
        "Selamat datang di sistem Star-ASN. Silakan masukkan <b>Nomor Induk Pegawai (NIP)</b> Anda untuk memulai:"
    )
    if query and query.message and isinstance(query.message, Message):
        await query.answer()
        await query.message.reply_text(message, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(message, parse_mode="HTML")
    return WAIT_REG_NIP


async def reg_nip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text or not update.effective_user:
        return WAIT_REG_NIP

    nip = update.message.text.strip()
    existing = store.get_user_by_nip(nip)
    tid = update.effective_user.id

    if existing:
        if existing.get("telegram_id") and existing.get("telegram_id") != tid:
            await update.message.reply_text(
                "❌ <b>NIP SUDAH TERTAUT</b>\n────────────────\n"
                f"Maaf, NIP <code>{nip}</code> sudah terdaftar dengan akun Telegram lain.\n\n"
                "Silakan hubungi administrator jika Anda merasa ini adalah kesalahan.",
                parse_mode="HTML",
            )
            return ConversationHandler.END

        if not existing.get("telegram_id"):
            await update.message.reply_text(
                "📢 <b>DATA DITEMUKAN</b>\n────────────────\n"
                f"NIP <code>{nip}</code> sudah didaftarkan sebelumnya oleh Administrator.\n\n"
                "Silakan masukkan <b>PASSWORD</b> Anda untuk memverifikasi dan menautkan akun ini ke Telegram Anda:",
                parse_mode="HTML",
            )
            user_cache = cast(dict[str, Any], context.user_data)
            user_cache["reg_nip"] = nip
            return WAIT_REG_PASS

    user_cache = cast(dict[str, Any], context.user_data)
    user_cache["reg_nip"] = nip
    await update.message.reply_text(
        "🔐 <b>LANGKAH 2/4: KEAMANAN</b>\n────────────────\n"
        "NIP diterima. Sekarang masukkan <b>PASSWORD</b> portal absensi Anda.\n\n"
        "<i>💡 Password ini digunakan untuk masuk ke sistem Star-ASN dan akan dienkripsi secara aman.</i>",
        parse_mode="HTML",
    )
    return WAIT_REG_PASS


async def reg_pass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return WAIT_REG_PASS
    user_cache = cast(dict[str, Any], context.user_data)
    user_cache["reg_pass"] = update.message.text
    await update.message.reply_text(
        "👤 <b>LANGKAH 3/4: PROFIL</b>\n────────────────\n"
        "Password tersimpan. Silakan masukkan <b>NAMA LENGKAP</b> Anda sesuai data kepegawaian:",
        parse_mode="HTML",
    )
    return WAIT_REG_NAME


async def reg_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return WAIT_REG_NAME
    user_cache = cast(dict[str, Any], context.user_data)
    user_cache["reg_name"] = update.message.text

    upt_list = store.get_all_upts()
    keyboard = get_upt_keyboard(upt_list, callback_prefix="reg_upt_")

    await update.message.reply_text(
        "🏢 <b>LANGKAH 4/4: UNIT KERJA (UPT)</b>\n────────────────\n"
        "Silakan pilih <b>Unit Kerja</b> tempat Anda bertugas dari daftar di bawah:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return WAIT_REG_UPT


async def reg_upt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    user_cache = cast(dict[str, Any], context.user_data)

    if query:
        await query.answer()
        data = query.data or ""
        user_cache["reg_upt"] = data.replace("reg_upt_", "")
    else:
        if not update.message or not update.message.text:
            return WAIT_REG_UPT
        user_cache["reg_upt"] = update.message.text

    if not update.effective_user:
        return ConversationHandler.END

    user_data = {
        "nip": user_cache.get("reg_nip"),
        "password": user_cache.get("reg_pass"),
        "nama": user_cache.get("reg_name"),
        "upt_id": user_cache.get("reg_upt"),
        "telegram_id": update.effective_user.id,
    }

    if store.add_user(user_data):
        sync_note = ""
        try:
            await internal_api.restart_scheduler()
        except Exception as exc:
            sync_note = f"\n⚠️ Sinkronisasi scheduler belum berhasil: <code>{exc}</code>"
        if update.message:
            await update.message.reply_text(
                "✅ Registrasi Berhasil!\n"
                f"Selamat bergabung, {user_data['nama']}. Data Anda telah terhubung dengan Telegram ID: {user_data['telegram_id']}\n\n"
                f"Ketik /start untuk membuka dashboard.{sync_note}",
                parse_mode="HTML",
            )
    elif update.message:
        await update.message.reply_text("❌ Terjadi kesalahan saat menyimpan data. Silakan hubungi admin.")

    return ConversationHandler.END
