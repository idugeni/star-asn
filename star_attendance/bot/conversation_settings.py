from __future__ import annotations

from typing import Any, cast, TYPE_CHECKING

if TYPE_CHECKING:
    from star_attendance.db.types import UserData

from telegram import (
    KeyboardButton, Message, ReplyKeyboardMarkup, ReplyKeyboardRemove, Update, constants
)
from telegram.ext import ContextTypes, ConversationHandler

from star_attendance.bot.constants import WAIT_SET_DAYS, WAIT_SET_IN, WAIT_SET_LOC, WAIT_SET_OUT
from star_attendance.bot.handler_views import build_dashboard_message
from star_attendance.bot.ui import get_main_menu
from star_attendance.runtime import get_internal_api_client

from .conversation_shared import parse_workdays, store, validate_time_text


internal_api = get_internal_api_client()
WORKDAY_OPTIONS = [["Senin-Jumat"], ["Senin-Sabtu"], ["Setiap Hari"], ["❌ Batal"]]
IN_TIME_OPTIONS = [["07:00", "07:30", "08:00"], ["08:30", "09:00", "❌ Batal"]]
OUT_TIME_OPTIONS = [["16:00", "16:30", "17:00"], ["17:30", "18:00", "❌ Batal"]]
SKIP_LOCATION_CHOICES = {"Lewati", "⏩ Lewati", "LEWATI", "⏩ LEWATI", "❌ Batal"}


def _clear_settings_cache(user_cache: dict[str, Any]) -> None:
    for key in ("set_in", "set_out", "set_workdays"):
        user_cache.pop(key, None)


async def _sync_scheduler() -> tuple[bool, str | None]:
    try:
        await internal_api.restart_scheduler()
        return True, None
    except Exception as exc:
        return False, str(exc)


async def _show_dashboard(message: Message, user: UserData, sync_error: str | None = None) -> None:
    header = "✅ Pengaturan berhasil diperbarui."
    if sync_error:
        header += f"\n⚠️ Sinkronisasi scheduler belum berhasil: <code>{sync_error}</code>"
    await message.reply_text(header, parse_mode=constants.ParseMode.HTML, reply_markup=ReplyKeyboardRemove())
    await message.reply_text(
        build_dashboard_message(user, store=store),
        parse_mode=constants.ParseMode.HTML,
        reply_markup=await get_main_menu(user["telegram_id"] or 0),
    )


async def start_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_settings_cache(cast(dict[str, Any], context.user_data))
    query = update.callback_query
    message: Message | None = None
    if query:
        await query.answer()
        if isinstance(query.message, Message):
            message = query.message
    else:
        message = update.message

    if not message:
        return ConversationHandler.END

    await message.reply_text(
        "🛠 <b>KONFIGURASI JADWAL</b>\n────────────────\n"
        "Pilih atau ketik jam <b>AUTO-IN</b> Anda (Format HH:mm):",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(IN_TIME_OPTIONS, one_time_keyboard=True, resize_keyboard=True),
    )
    return WAIT_SET_IN


async def start_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_settings_cache(cast(dict[str, Any], context.user_data))
    query = update.callback_query
    message = query.message if query and isinstance(query.message, Message) else update.message
    if query:
        await query.answer()
    if not message:
        return ConversationHandler.END

    await message.reply_text(
        "⏰ <b>PENGATURAN JADWAL CEPAT</b>\n────────────────\n"
        "Pilih atau ketik jam <b>AUTO-IN</b> baru Anda:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(IN_TIME_OPTIONS, one_time_keyboard=True, resize_keyboard=True),
    )
    return WAIT_SET_IN


async def start_workdays(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    _clear_settings_cache(cast(dict[str, Any], context.user_data))
    query = update.callback_query
    message = query.message if query and isinstance(query.message, Message) else update.message
    if query:
        await query.answer()
    if not message:
        return ConversationHandler.END

    await message.reply_text(
        "🗓 <b>PILIH POLA HARI AUTO ABSEN</b>\n────────────────\n"
        "Pilih hari kerja yang akan dipakai untuk auto absen:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(WORKDAY_OPTIONS, one_time_keyboard=True, resize_keyboard=True),
    )
    return WAIT_SET_DAYS


async def start_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()

    keyboard = ReplyKeyboardMarkup([
        [KeyboardButton("📍 Ambil Lokasi Saya Sekarang", request_location=True)],
        [KeyboardButton("❌ Batal")]
    ], resize_keyboard=True, one_time_keyboard=True)

    message = (
        "📍 <b>PENGATURAN LOKASI GPS</b>\n────────────────\n"
        "Silakan kirimkan lokasi Anda untuk akurasi absensi.\n\n"
        "💡 <b>Pilihan:</b>\n"
        "1. Klik tombol <b>📍 Ambil Lokasi</b> di bawah (Paling Akurat).\n"
        "2. Kirimkan pesan teks dengan format <code>lat, lon</code>.\n"
        "   Contoh: <code>-6.123, 106.456</code>"
    )

    if query and isinstance(query.message, Message):
        await query.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)
    elif update.message:
        await update.message.reply_text(message, parse_mode="HTML", reply_markup=keyboard)

    return WAIT_SET_LOC


async def set_in(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return WAIT_SET_IN
        
    text = update.message.text.strip()
    if text == "❌ Batal":
        return await cancel_convo(update, context)
        
    try:
        normalized = validate_time_text(text)
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return WAIT_SET_IN

    user_cache = cast(dict[str, Any], context.user_data)
    user_cache["set_in"] = normalized
    await update.message.reply_text(
        "✅ Jam <b>IN</b> tersimpan.\n\n"
        "Sekarang pilih atau ketik jam <b>AUTO-OUT (Pulang)</b> Anda:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(OUT_TIME_OPTIONS, one_time_keyboard=True, resize_keyboard=True),
    )
    return WAIT_SET_OUT


async def set_out(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return WAIT_SET_OUT
        
    text = update.message.text.strip()
    if text == "❌ Batal":
        return await cancel_convo(update, context)
        
    try:
        normalized = validate_time_text(text)
    except ValueError as exc:
        await update.message.reply_text(f"❌ {exc}")
        return WAIT_SET_OUT

    user_cache = cast(dict[str, Any], context.user_data)
    user_cache["set_out"] = normalized

    await update.message.reply_text(
        "🗓 <b>PILIH HARI AUTO ABSEN</b>\n────────────────\n"
        "Pilih pola hari kerja untuk auto absen Anda:",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(WORKDAY_OPTIONS, one_time_keyboard=True, resize_keyboard=True),
    )
    return WAIT_SET_DAYS


async def set_days(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return WAIT_SET_DAYS
        
    text = update.message.text.strip()
    if text == "❌ Batal":
        return await cancel_convo(update, context)

    try:
        workdays = parse_workdays(text)
    except ValueError as exc:
        await update.message.reply_text(
            f"❌ {exc}\nPilih salah satu: <code>Senin-Jumat</code>, <code>Senin-Sabtu</code>, atau <code>Setiap Hari</code>.",
            parse_mode="HTML",
        )
        return WAIT_SET_DAYS

    user_cache = cast(dict[str, Any], context.user_data)
    user_cache["set_workdays"] = workdays

    keyboard = [[KeyboardButton("📍 BAGIKAN LOKASI GPS", request_location=True)], [KeyboardButton("⏩ LEWATI")]]
    await update.message.reply_text(
        "📍 <b>PENGATURAN LOKASI</b>\n────────────────\n"
        "Bot dapat melakukan absen menggunakan titik koordinat khusus jika diperlukan.\n\n"
        "1. Klik tombol di bawah untuk kirim lokasi GPS,\n"
        "2. Ketik koordinat manual (contoh: <code>-6.2146, 106.8451</code>),\n"
        "3. Klik <b>Lewati</b> jika ingin menggunakan lokasi default kantor/UPT.",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardMarkup(keyboard, one_time_keyboard=True, resize_keyboard=True),
    )
    return WAIT_SET_LOC


async def set_loc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.effective_user:
        return ConversationHandler.END

    user = store.get_user_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Error: User tidak ditemukan.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    user_cache = cast(dict[str, Any], context.user_data)
    settings_update: dict[str, Any] = {}

    if user_cache.get("set_in") not in (None, ""):
        settings_update["cron_in"] = user_cache.get("set_in")
    if user_cache.get("set_out") not in (None, ""):
        settings_update["cron_out"] = user_cache.get("set_out")
    if user_cache.get("set_workdays") not in (None, ""):
        settings_update["workdays"] = user_cache.get("set_workdays")

    if update.message.location:
        settings_update["personal_latitude"] = update.message.location.latitude
        settings_update["personal_longitude"] = update.message.location.longitude
    elif update.message.text:
        raw_text = update.message.text.strip()
        if raw_text in SKIP_LOCATION_CHOICES:
            settings_update["personal_latitude"] = None
            settings_update["personal_longitude"] = None
        else:
            try:
                latitude, longitude = [float(part.strip()) for part in raw_text.split(",", maxsplit=1)]
                if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                    raise ValueError("Koordinat di luar jangkauan valid.")
                settings_update["personal_latitude"] = latitude
                settings_update["personal_longitude"] = longitude
            except Exception:
                await update.message.reply_text(
                    "❌ Format koordinat tidak valid. Gunakan format <code>latitude, longitude</code>.",
                    parse_mode="HTML",
                )
                return WAIT_SET_LOC

    success = store.update_user_settings(user["nip"], settings_update)
    _clear_settings_cache(user_cache)

    if not success:
        await update.message.reply_text("❌ Gagal memperbarui pengaturan.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    sync_ok, sync_error = await _sync_scheduler()
    refreshed_user = store.get_user_by_telegram_id(update.effective_user.id)
    if not refreshed_user:
        await update.message.reply_text("✅ Pengaturan berhasil diperbarui!", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    await _show_dashboard(
        update.message,
        refreshed_user,
        sync_error=None if sync_ok else sync_error,
    )
    return ConversationHandler.END


async def cancel_convo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.message:
        user_cache = cast(dict[str, Any], context.user_data)
        _clear_settings_cache(user_cache)
        await update.message.reply_text("Operasi dibatalkan.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END
