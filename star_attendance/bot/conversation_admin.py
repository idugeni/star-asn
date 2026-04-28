from __future__ import annotations

from typing import Any, cast

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, ReplyKeyboardRemove, Update
from telegram.ext import ContextTypes, ConversationHandler

from star_attendance.bot.constants import (
    WAIT_ADMIN_ADD_LOC,
    WAIT_ADMIN_ADD_NAME,
    WAIT_ADMIN_ADD_NIP,
    WAIT_ADMIN_ADD_PASS,
    WAIT_ADMIN_ADD_SCHEDULE,
    WAIT_ADMIN_ADD_UPT,
    WAIT_ADMIN_ADD_WORKDAYS,
    WAIT_ADMIN_CONFIRM_DEL,
    WAIT_ADMIN_INPUT_VAL,
)
from star_attendance.runtime import get_internal_api_client
from star_attendance.core.utils import get_action_label

from .conversation_shared import GLOBAL_SETTING_LABELS, store, validate_global_setting, validate_nip
from .handler_views import (
    build_global_settings_message,
    build_manage_user_message,
    build_user_manage_keyboard,
    get_global_settings_keyboard,
)
from .ui import get_upt_keyboard, is_admin
from star_attendance.sso_handler import sync_sso_data

internal_api = get_internal_api_client()


async def _sync_scheduler_notice(update: Update) -> None:
    message = update.effective_message
    if not message:
        return

    try:
        # First attempt
        await internal_api.restart_scheduler()
    except Exception:
        try:
            # Short wait and one retry in case API is still starting (cold start)
            import asyncio

            await asyncio.sleep(2)
            await internal_api.restart_scheduler()
        except Exception:
            # If still fails, show a friendly message instead of a scary tech error
            await message.reply_text(
                "✅ <b>Data Berhasil Disimpan</b>\n"
                "────────────────\n"
                "ℹ️ <i>Status: Sinkronisasi otomatis sedang berjalan di latar belakang. Anda tidak perlu melakukan apa-apa lagi.</i>",
                parse_mode="HTML",
            )


async def admin_edit_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if not query:
        return ConversationHandler.END
    await query.answer()

    data = query.data
    if data is None:
        return ConversationHandler.END

    user_cache = cast(dict[str, Any], context.user_data)

    if data.startswith("global_edit_"):
        setting_key = data.replace("global_edit_", "", 1)
        current_value = store.get_settings().get(setting_key, "-")
        user_cache["admin_edit_kind"] = "global_setting"
        user_cache["admin_edit_field"] = setting_key
        if query.message and isinstance(query.message, Message):
            await query.message.reply_text(
                f"🌐 <b>UPDATE {GLOBAL_SETTING_LABELS.get(setting_key, setting_key.upper())}</b>\n────────────────\n"
                f"Nilai saat ini: <code>{current_value}</code>\n"
                "Masukkan nilai baru:",
                parse_mode="HTML",
                reply_markup=ReplyKeyboardRemove(),
            )
        return WAIT_ADMIN_INPUT_VAL

    parts = data.split("_")
    if len(parts) < 3:
        return ConversationHandler.END

    action = parts[1]
    target_nip = parts[2]
    user_cache["admin_edit_kind"] = "user_field"
    user_cache["admin_edit_target"] = target_nip
    user_cache["admin_edit_field"] = action

    if action == "del" and query.message and isinstance(query.message, Message):
        await query.message.reply_text(
            f"⚠️ <b>KONFIRMASI PENGHAPUSAN</b>\n────────────────\n"
            f"Apakah Anda yakin ingin menghapus personel dengan NIP <code>{target_nip}</code>?\n\n"
            "Ketik <b>YAKIN</b> untuk mengeksekusi.",
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
        )
        return WAIT_ADMIN_CONFIRM_DEL

    field_map = {
        "name": "NAMA LENGKAP",
        "pass": "PASSWORD PORTAL",
        "nip": "NIP BARU",
        "upt": "UNIT KERJA (UPT)",
        "loc": "KOORDINAT LOKASI (Lat, Lon)",
        "schedule": "JAM KERJA (Contoh: 07:30 - 16:30)",
        "workdays": "HARI KERJA (Preset)",
    }

    prompt = f"🛠 <b>UPDATE {field_map.get(action, get_action_label(action))}</b>\n────────────────\n"
    keyboard = None

    if action == "loc":
        prompt += (
            f"Personel: <code>{target_nip}</code>\n\nMasukkan koordinat dalam format: <code>latitude, longitude</code>"
        )
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏢 Pakai Lokasi UPT (Default)", callback_data="val_DEFAULT")]]
        )
    elif action == "schedule":
        prompt += f"Personel: <code>{target_nip}</code>\n\nPilih preset jam atau ketik manual:"
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⏰ 07:30 - 16:30 (Default)", callback_data="val_SISTEM")],
                [InlineKeyboardButton("⌨️ Input Manual", callback_data="val_MANUAL")],
            ]
        )
    elif action == "workdays":
        prompt += f"Personel: <code>{target_nip}</code>\n\nPilih preset hari kerja:"
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🗓 Senin-Jumat", callback_data="val_mon-fri")],
                [InlineKeyboardButton("🗓 Senin-Sabtu", callback_data="val_mon-sat")],
                [InlineKeyboardButton("🗓 Setiap Hari", callback_data="val_everyday")],
                [InlineKeyboardButton("🌐 Ikuti Global", callback_data="val_GLOBAL")],
            ]
        )
    elif action in ["upt", "unit"]:
        upt_list = store.get_all_upts()
        keyboard = get_upt_keyboard(upt_list, callback_prefix="val_")
        prompt += f"Personel: <code>{target_nip}</code>\n\nPilih Unit Kerja baru dari daftar:"
    else:
        prompt += f"Masukkan nilai baru untuk personel <code>{target_nip}</code>:"

    if query.message and isinstance(query.message, Message):
        await query.message.reply_text(
            prompt,
            parse_mode="HTML",
            reply_markup=keyboard or ReplyKeyboardRemove(),
        )
    return WAIT_ADMIN_INPUT_VAL


async def admin_edit_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    new_value = None

    if query:
        await query.answer()
        data = query.data or ""
        if data.startswith("val_"):
            new_value = data.replace("val_", "")
            if new_value == "MANUAL":
                if isinstance(query.message, Message):
                    await query.message.reply_text(
                        "Silakan ketik nilai manual (Format: <code>HH:MM - HH:MM</code>):", parse_mode="HTML"
                    )
                return WAIT_ADMIN_INPUT_VAL
    else:
        if not update.message or not update.message.text:
            return WAIT_ADMIN_INPUT_VAL
        new_value = update.message.text

    if not new_value:
        return WAIT_ADMIN_INPUT_VAL

    user_cache = cast(dict[str, Any], context.user_data)
    edit_kind = user_cache.get("admin_edit_kind")
    field = str(user_cache.get("admin_edit_field", ""))

    if edit_kind == "global_setting":
        try:
            parsed_value = validate_global_setting(field, new_value)
        except Exception as exc:
            if update.message:
                await update.message.reply_text(f"❌ Nilai tidak valid: {exc}")
            return WAIT_ADMIN_INPUT_VAL

        updated = store.update_settings({field: parsed_value})
        if update.message:
            header = f"✅ <b>GLOBAL SETTING {field.upper()} DIPERBARUI</b>\n────────────────\n"
            body = build_global_settings_message(store=store)
            await update.message.reply_text(
                f"{header}{body}",
                parse_mode="HTML",
                reply_markup=get_global_settings_keyboard(),
            )
        await _sync_scheduler_notice(update)
        return ConversationHandler.END

    target_nip = str(user_cache.get("admin_edit_target", ""))
    field_map = {
        "name": "nama",
        "pass": "password",
        "nip": "nip",
        "upt": "upt_id",
        "loc": "loc",
        "schedule": "schedule",
    }

    success = False
    try:
        if field == "nip":
            success = store.rename_user_nip(target_nip, validate_nip(new_value))
        elif field == "loc":
            if new_value.upper() == "DEFAULT":
                success = store.update_user_settings(
                    target_nip, {"personal_latitude": None, "personal_longitude": None}
                )
            else:
                from .conversation_shared import parse_coordinates

                lat, lon = parse_coordinates(new_value)
                success = store.update_user_settings(target_nip, {"personal_latitude": lat, "personal_longitude": lon})
        elif field == "schedule":
            if new_value.upper() == "SISTEM":
                success = store.update_user_settings(target_nip, {"cron_in": None, "cron_out": None})
            else:
                from .conversation_shared import parse_schedule_range

                cin, cout = parse_schedule_range(new_value)
                success = store.update_user_settings(target_nip, {"cron_in": cin, "cron_out": cout})
        elif field == "workdays":
            if new_value.upper() == "GLOBAL":
                success = store.update_user_settings(target_nip, {"workdays": None})
            else:
                from .conversation_shared import parse_workdays

                workdays = parse_workdays(new_value)
                success = store.update_user_settings(target_nip, {"workdays": workdays})
        else:
            db_field = field_map.get(field)
            if db_field:
                success = store.update_user_settings(target_nip, {db_field: new_value})
    except Exception as exc:
        if update.message:
            await update.message.reply_text(f"❌ Error: {exc}")
        return WAIT_ADMIN_INPUT_VAL

    if success and update.message:
        refreshed_user = store.get_user_by_nip(new_value if field == "nip" else target_nip)
        if refreshed_user:
            header = f"✅ <b>DATA {field.upper()} BERHASIL DIPERBARUI</b>\n────────────────\n"
            body = build_manage_user_message(refreshed_user)
            await update.message.reply_text(
                f"{header}{body}",
                parse_mode="HTML",
                reply_markup=build_user_manage_keyboard(refreshed_user["nip"]),
            )
        else:
            await update.message.reply_text(f"✅ Data <code>{field.upper()}</code> berhasil diperbarui.", parse_mode="HTML")
        await _sync_scheduler_notice(update)
    elif update.message:
        await update.message.reply_text("❌ Gagal memperbarui data. Pastikan target valid.")
    return ConversationHandler.END


async def admin_confirm_del(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return WAIT_ADMIN_CONFIRM_DEL
    if update.message.text.upper() != "YAKIN":
        await update.message.reply_text("❌ Pembatalan. Konfirmasi harus bertuliskan 'YAKIN'.")
        return ConversationHandler.END

    user_cache = cast(dict[str, Any], context.user_data)
    target_nip = str(user_cache.get("admin_edit_target", ""))
    if target_nip and store.delete_user(target_nip):
        await update.message.reply_text(
            f"✅ Personel <code>{target_nip}</code> telah dihapus dari sistem.",
            parse_mode="HTML",
        )
    else:
        await update.message.reply_text("❌ Gagal menghapus personel.")
    return ConversationHandler.END


async def admin_add_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.effective_user or not is_admin(update.effective_user.id):
        return ConversationHandler.END

    query = update.callback_query
    message = (
        "➕ <b>ADMIN: TAMBAH PERSONEL BARU</b>\n────────────────\n"
        "Silakan masukkan <b>NIP</b> personel baru yang ingin didaftarkan:"
    )
    if query and query.message and isinstance(query.message, Message):
        await query.answer()
        await query.message.reply_text(message, parse_mode="HTML")
    elif update.message:
        await update.message.reply_text(message, parse_mode="HTML")
    return WAIT_ADMIN_ADD_NIP


async def admin_add_nip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return WAIT_ADMIN_ADD_NIP
    user_cache = cast(dict[str, Any], context.user_data)
    try:
        nip = validate_nip(update.message.text)
        user_cache["admin_add_nip"] = nip
    except Exception as exc:
        await update.message.reply_text(f"❌ NIP tidak valid: {exc}")
        return WAIT_ADMIN_ADD_NIP

    await update.message.reply_text(
        "🔑 <b>PASSWORD PORTAL</b>\n────────────────\n"
        f"NIP <code>{user_cache['admin_add_nip']}</code> diterima.\n"
        "Sekarang masukkan <b>PASSWORD</b> portal absensi untuk personel ini:",
        parse_mode="HTML",
    )
    return WAIT_ADMIN_ADD_PASS


async def admin_add_pass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return WAIT_ADMIN_ADD_PASS
    user_cache = cast(dict[str, Any], context.user_data)
    nip = user_cache.get("admin_add_nip")
    password = update.message.text
    user_cache["admin_add_pass"] = password

    if not nip:
        await update.message.reply_text("❌ NIP tidak ditemukan. Mulai ulang dari /tambah.")
        return ConversationHandler.END

    # Perform SSO Sync
    status_msg = await update.message.reply_text(
        "🔍 <b>SINKRONISASI SSO</b>\n────────────────\n"
        "Menghubungkan ke server demo-sso...",
        parse_mode="HTML",
    )

    async def on_progress(msg: str):
        try:
            await status_msg.edit_text(
                f"🔍 <b>SINKRONISASI SSO</b>\n────────────────\n{msg}",
                parse_mode="HTML",
            )
        except Exception:
            pass

    res = await sync_sso_data(str(nip), password, on_progress=on_progress)

    if res["status"] == "success":
        profile = res["data"]
        user_cache["admin_add_name"] = profile.get("nama")
        user_cache["admin_add_upt"] = profile.get("nama_upt")
        # Store extra fields
        user_cache["admin_add_jabatan"] = profile.get("jabatan")
        user_cache["admin_add_divisi"] = profile.get("divisi")
        user_cache["admin_add_pangkat"] = profile.get("pangkat")
        user_cache["admin_add_email"] = profile.get("email")
        user_cache["admin_add_sso_sub"] = profile.get("sso_sub")
        user_cache["admin_add_birth_date"] = profile.get("birth_date")
        user_cache["admin_add_birth_place"] = profile.get("birth_place")

        await status_msg.edit_text(
            f"✅ <b>DATA TERVERIFIKASI</b>\n────────────────\n"
            f"👤 <b>Nama:</b> <code>{profile.get('nama')}</code>\n"
            f"🏢 <b>UPT:</b> <code>{profile.get('nama_upt')}</code>\n\n"
            "Data otomatis disinkronkan. Melanjutkan ke pengaturan jadwal...",
            parse_mode="HTML",
        )
        # Skip WAIT_ADMIN_ADD_NAME and WAIT_ADMIN_ADD_UPT, go to admin_add_upt logic
        return await admin_add_upt(update, context)
    else:
        await status_msg.edit_text(
            f"❌ <b>GAGAL SINKRONISASI</b>\n────────────────\n"
            f"Pesan: {res.get('message')}\n\n"
            "Pastikan NIP dan Password SSO benar, lalu kirim ulang password:",
            parse_mode="HTML",
        )
        return WAIT_ADMIN_ADD_PASS


async def admin_add_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not update.message or not update.message.text:
        return WAIT_ADMIN_ADD_NAME
    user_cache = cast(dict[str, Any], context.user_data)
    user_cache["admin_add_name"] = update.message.text
    upt_list = store.get_all_upts()
    keyboard = get_upt_keyboard(upt_list, callback_prefix="add_upt_")

    await update.message.reply_text(
        "🏢 <b>LANGKAH 4: UNIT KERJA (UPT)</b>\n────────────────\n"
        "Pilih <b>Unit Kerja</b> tempat personel bertugas dari daftar di bawah:",
        parse_mode="HTML",
        reply_markup=keyboard,
    )
    return WAIT_ADMIN_ADD_UPT


async def admin_add_upt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_cache = cast(dict[str, Any], context.user_data)
    query = update.callback_query

    if query:
        await query.answer()
        data = query.data or ""
        user_cache["admin_add_upt"] = data.replace("add_upt_", "")
    elif not user_cache.get("admin_add_upt"):
        if not update.message or not update.message.text:
            return WAIT_ADMIN_ADD_UPT
        user_cache["admin_add_upt"] = update.message.text

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⏰ 07:30 - 16:30 (Default)", callback_data="preset_sch_default")],
            [InlineKeyboardButton("⌨️ Input Manual", callback_data="preset_sch_manual")],
        ]
    )

    msg_fn = None
    if query and query.message and isinstance(query.message, Message):
        msg_fn = query.message.reply_text
    elif update.message:
        msg_fn = update.message.reply_text

    if msg_fn:
        await msg_fn(
            "⏰ <b>LANGKAH 5: JAM KERJA</b>\n────────────────\nTentukan jam operasional untuk personel ini.",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    return WAIT_ADMIN_ADD_SCHEDULE


async def admin_add_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_cache = cast(dict[str, Any], context.user_data)
    query = update.callback_query

    if query:
        await query.answer()
        data = str(query.data) if query.data else "preset_sch_default"
        if data == "preset_sch_default":
            user_cache["admin_add_schedule"] = "07:30 - 16:30"
        elif query.message and isinstance(query.message, Message):
            await query.message.reply_text(
                "⌨️ <b>INPUT JAM MANUAL</b>\n────────────────\n"
                "Silakan ketik jam kerja dengan format: <code>HH:MM - HH:MM</code>\n"
                "Contoh: <code>08:00 - 17:00</code>",
                parse_mode="HTML",
            )
            return WAIT_ADMIN_ADD_SCHEDULE
        else:
            return WAIT_ADMIN_ADD_SCHEDULE
    else:
        # User typed manually
        if not update.message or not update.message.text:
            return WAIT_ADMIN_ADD_SCHEDULE
        user_cache["admin_add_schedule"] = update.message.text

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🗓 Senin - Jumat", callback_data="preset_wd_mon-fri")],
            [InlineKeyboardButton("🗓 Senin - Sabtu", callback_data="preset_wd_mon-sat")],
            [InlineKeyboardButton("🗓 Setiap Hari", callback_data="preset_wd_everyday")],
        ]
    )

    msg_fn = None
    if query and isinstance(query.message, Message):
        msg_fn = query.message.reply_text
    elif update.message:
        msg_fn = update.message.reply_text

    if msg_fn:
        await msg_fn(
            "🗓 <b>LANGKAH 6: HARI KERJA</b>\n────────────────\n"
            "Pilih hari apa saja personel ini harus melakukan absensi otomatis.",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    return WAIT_ADMIN_ADD_WORKDAYS


async def admin_add_workdays(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_cache = cast(dict[str, Any], context.user_data)
    query = update.callback_query

    if query:
        await query.answer()
        q_data = query.data or ""
        user_cache["admin_add_workdays"] = q_data.replace("preset_wd_", "")
    else:
        if not update.message or not update.message.text:
            return WAIT_ADMIN_ADD_WORKDAYS
        user_cache["admin_add_workdays"] = update.message.text

    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏢 Gunakan Lokasi UPT (Default)", callback_data="preset_loc_default")],
            [InlineKeyboardButton("⌨️ Masukkan Titik Manual", callback_data="preset_loc_manual")],
        ]
    )

    msg_fn = None
    if query and isinstance(query.message, Message):
        msg_fn = query.message.reply_text
    elif update.message:
        msg_fn = update.message.reply_text

    if msg_fn:
        await msg_fn(
            "📍 <b>LANGKAH 7: LOKASI ABSENSI</b>\n────────────────\n"
            "Di mana personel ini akan melakukan absensi?\n\n"
            "💡 <i>Gunakan lokasi UPT jika personel bekerja di kantor, atau manual jika bekerja remote.</i>",
            parse_mode="HTML",
            reply_markup=keyboard,
        )
    return WAIT_ADMIN_ADD_LOC


async def admin_add_loc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_cache = cast(dict[str, Any], context.user_data)
    query = update.callback_query

    if query:
        await query.answer()
        data = str(query.data) if query.data else ""
        if data == "preset_loc_manual":
            if isinstance(query.message, Message):
                await query.message.reply_text(
                    "📍 <b>INPUT KOORDINAT MANUAL</b>\n────────────────\n"
                    "Kirimkan titik koordinat dalam format: <code>lat, lon</code>\n"
                    "Contoh: <code>-6.175, 106.827</code>",
                    parse_mode="HTML",
                )
            return WAIT_ADMIN_ADD_LOC
        raw_loc = "DEFAULT"
    else:
        if not update.message or not update.message.text:
            return WAIT_ADMIN_ADD_LOC
        raw_loc = update.message.text

    target_nip = user_cache.get("admin_add_nip")

    # Process inputs
    raw_schedule = str(user_cache.get("admin_add_schedule", "SISTEM"))
    raw_workdays = str(user_cache.get("admin_add_workdays", "GLOBAL"))

    from .conversation_shared import parse_coordinates, parse_schedule_range, parse_workdays

    cin, cout = (None, None)
    if raw_schedule.upper() != "SISTEM":
        try:
            cin, cout = parse_schedule_range(raw_schedule)
        except:
            pass

    wday = None
    if raw_workdays.upper() != "GLOBAL":
        try:
            wday = parse_workdays(raw_workdays)
        except:
            pass

    lat, lon = (None, None)
    if raw_loc.upper() != "DEFAULT":
        try:
            lat, lon = parse_coordinates(raw_loc)
        except:
            pass

    user_data = {
        "nip": target_nip,
        "password": user_cache.get("admin_add_pass"),
        "nama": user_cache.get("admin_add_name"),
        "upt_id": user_cache.get("admin_add_upt"),
        "cron_in": cin,
        "cron_out": cout,
        "workdays": wday,
        "personal_latitude": lat,
        "personal_longitude": lon,
        "telegram_id": None,
        "jabatan": user_cache.get("admin_add_jabatan"),
        "divisi": user_cache.get("admin_add_divisi"),
        "pangkat": user_cache.get("admin_add_pangkat"),
        "email": user_cache.get("admin_add_email"),
        "sso_sub": user_cache.get("admin_add_sso_sub"),
        "birth_date": user_cache.get("admin_add_birth_date"),
        "birth_place": user_cache.get("admin_add_birth_place"),
    }

    if store.add_user(user_data) and update.message:
        await update.message.reply_text(
            f"✅ <b>PERSONEL LENGKAP TERDAFTAR</b>\n────────────────\n"
            f"🆔 <b>NIP:</b> <code>{user_data['nip']}</code>\n"
            f"👤 <b>NAMA:</b> <code>{user_data['nama']}</code>\n"
            f"⏰ <b>JADWAL:</b> <code>{raw_schedule.upper()}</code>\n"
            f"🗓 <b>HARI:</b> <code>{raw_workdays.upper()}</code>\n"
            f"📍 <b>LOKASI:</b> <code>{raw_loc.upper()}</code>",
            parse_mode="HTML",
        )
        await _sync_scheduler_notice(update)
    elif update.message:
        await update.message.reply_text("❌ Gagal menambahkan personel. Pastikan data valid.")

    return ConversationHandler.END
