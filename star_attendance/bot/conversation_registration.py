from __future__ import annotations

from typing import Any, cast

from telegram import Message, Update
from telegram.ext import ContextTypes, ConversationHandler

from star_attendance.bot.constants import WAIT_REG_NAME, WAIT_REG_NIP, WAIT_REG_PASS, WAIT_REG_UPT
from star_attendance.runtime import get_internal_api_client

from .conversation_shared import store, validate_nip
from .ui import get_upt_keyboard

internal_api = get_internal_api_client()


async def start_reg(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    message = (
        "📝 <b>REGISTRASI AKUN ANDA</b>\n────────────────\n"
        "Selamat datang di sistem Star-ASN. Silakan masukkan <b>Nomor Induk Pegawai (NIP)</b> Anda sendiri untuk memulai:"
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

    try:
        nip = validate_nip(update.message.text)
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return WAIT_REG_NIP

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
    if not update.message or not update.message.text or not update.effective_user:
        return WAIT_REG_PASS
        
    user_cache = cast(dict[str, Any], context.user_data)
    nip = str(user_cache.get("reg_nip"))
    password = update.message.text
    tid = update.effective_user.id

    status_msg = await update.message.reply_text(
        "⏳ <b>MENAUTKAN AKUN KE SSO PUSAT...</b>\n"
        "────────────────\n"
        "<i>Sedang memverifikasi kredensial dan mengambil profil digital Anda secara otomatis.</i>",
        parse_mode="HTML",
    )

    from star_attendance.sso_handler import SSOHandler
    sso = SSOHandler()
    
    try:
        login_res = await sso.login(nip, password)
        if login_res.get("status") != "success":
            await status_msg.edit_text(
                f"❌ <b>LOGIN SSO GAGAL</b>\n────────────────\n"
                f"{login_res.get('message', 'NIP atau Password salah.')}\n\n"
                "Silakan masukkan kembali <b>PASSWORD</b> Anda yang benar:",
                parse_mode="HTML"
            )
            return WAIT_REG_PASS

        profile_res = await sso.fetch_profile()
        if profile_res.get("status") != "success":
            await status_msg.edit_text(
                "❌ <b>GAGAL MENGAMBIL PROFIL</b>\n────────────────\n"
                "Login berhasil, namun data profil tidak ditemukan di server pusat.\n\n"
                "Silakan hubungi administrator.",
                parse_mode="HTML"
            )
            return ConversationHandler.END

        data = profile_res.get("data", {})
        
        # Automatic Account Creation
        user_data = {
            "nip": nip,
            "password": password,
            "nama": data.get("nama", "ASN User"),
            "upt_id": data.get("nama_upt"), # resolve_upt_id in store will handle name-to-id mapping
            "telegram_id": tid,
            "jabatan": data.get("jabatan"),
            "divisi": data.get("divisi"),
            "pangkat": data.get("pangkat"),
            "email": data.get("email"),
            "birth_date": data.get("birth_date"),
            "birth_place": data.get("birth_place"),
            "sso_sub": data.get("sso_sub"),
        }

        if store.add_user(user_data):
            try:
                await internal_api.restart_scheduler()
            except Exception:
                pass
            
            await status_msg.edit_text(
                "✅ <b>REGISTRASI OTOMATIS BERHASIL</b>\n────────────────\n"
                f"Selamat datang, <b>{user_data['nama']}</b>!\n\n"
                "Sistem telah berhasil:\n"
                "✔ Memverifikasi identitas SSO\n"
                "✔ Mengunduh profil profesional\n"
                "✔ Menghubungkan Telegram ID\n"
                "✔ Menetapkan lokasi UPT otomatis\n\n"
                "Gunakan /start untuk masuk ke Dashboard Utama.",
                parse_mode="HTML"
            )
        else:
            await status_msg.edit_text(
                "❌ <b>DATABASE ERROR</b>\n────────────────\n"
                "Gagal menyimpan data ke database. Silakan hubungi admin.",
                parse_mode="HTML"
            )
            
    except Exception as e:
        await status_msg.edit_text(
            f"❌ <b>SYSTEM ERROR</b>\n────────────────\n<code>{str(e)}</code>",
            parse_mode="HTML"
        )

    return ConversationHandler.END
