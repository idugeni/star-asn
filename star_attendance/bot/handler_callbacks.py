from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, cast

import psutil
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, Update, constants
from telegram.ext import ContextTypes

from star_attendance.bot.telemetry import monitor_mass_progress
from star_attendance.bot.ui import get_back_button, get_settings_menu, get_sync_sso_button
from star_attendance.core.config import settings
from star_attendance.core.processor import mass_attendance, process_single_user
from star_attendance.core.timeutils import format_formal_date, format_formal_timestamp, now_local
from star_attendance.core.utils import get_action_label

from .handler_views import (
    build_dashboard_message,
    build_global_settings_message,
    build_manage_user_message,
    build_scheduler_message,
    build_user_manage_keyboard,
    get_global_settings_keyboard,
    get_scheduler_keyboard,
)

EditMessage = Callable[[Message, str, Any], Awaitable[None]]
MainMenuBuilder = Callable[[int], Awaitable[Any]]
UsersKeyboardBuilder = Callable[..., Awaitable[Any]]
AdminChecker = Callable[[int], bool]
OptionsBuilder = Callable[[str], Any]


@dataclass(slots=True)
class CallbackServices:
    store: Any
    internal_api: Any
    edit_message: EditMessage
    get_main_menu: MainMenuBuilder
    get_users_keyboard: UsersKeyboardBuilder
    is_admin: AdminChecker
    build_runtime_options: OptionsBuilder


async def show_history(message: Message, *, services: CallbackServices, tid: int) -> None:
    user = services.store.get_user_by_telegram_id(tid)
    if not user:
        return

    logs = services.store.get_user_history(user["nip"], limit=10)
    response = "<b>📜 RIWAYAT ABSENSI TERAKHIR</b>\n────────────────\n"
    if not logs:
        response += "<i>Belum ada riwayat aktivitas.</i>"
    for log_entry in logs:
        icon = "✅" if log_entry["status"] == "success" else "❌"
        action_name = "PRESENSI MASUK" if log_entry["action"].lower() == "in" else "PRESENSI PULANG"
        response += (
            f"{icon} <b>{action_name}</b>\n"
            f"   └ <code>{format_formal_timestamp(log_entry['timestamp'])}</code>\n"
        )
    await services.edit_message(message, response, InlineKeyboardMarkup([[get_back_button()]]))


async def show_support(message: Message) -> None:
    admin_id = settings.TELEGRAM_ADMIN_ID
    keyboard: list[list[InlineKeyboardButton]] = []
    if admin_id:
        keyboard.append([InlineKeyboardButton("👤 HUBUNGI ADMIN", url=f"tg://user?id={admin_id}")])
    keyboard.append([get_back_button()])
    await message.edit_text(
        "<b>💬 LAYANAN DUKUNGAN</b>\n────────────────\nAda kendala penggunaan? Hubungi administrator untuk bantuan teknis.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode=constants.ParseMode.HTML,
    )


async def show_global_logs(message: Message, *, services: CallbackServices, tid: int) -> None:
    if not services.is_admin(tid):
        return

    logs = services.store.get_global_audit_logs(limit=15)
    response = "<b>📝 LOG SISTEM TERKINI</b>\n────────────────\n"
    if not logs:
        response += "<i>Masih sepi...</i>"
    for log_entry in logs:
        icon = "✅" if log_entry["status"] == "success" else "❌"
        response += (
            f"{icon} <code>{log_entry['nip'][:5]}..</code> | {log_entry['action'].upper()}\n"
            f"   └ <code>{format_formal_timestamp(log_entry['timestamp'])}</code>\n"
        )
    await services.edit_message(message, response, InlineKeyboardMarkup([[get_back_button()]]))


async def show_profile(message: Message, *, services: CallbackServices, tid: int) -> None:
    user = services.store.get_user_by_telegram_id(tid)
    if not user:
        return

    try:
        lat = user.get("latitude")
        lon = user.get("longitude")
        if lat and lon:
            coords = f"{float(lat):.6f}, {float(lon):.6f}"
        else:
            coords = "BELUM DISET"
    except (ValueError, TypeError):
        coords = "FORMAT TIDAK VALID"
    auto_status = "ACTIVE" if user.get("auto_attendance_active") else "INACTIVE"
    in_source = str(user.get("cron_in_source", "-")).upper()
    out_source = str(user.get("cron_out_source", "-")).upper()

    in_label = ""
    out_label = ""

    response = (
        "<b>🆔 PROFIL DIGITAL ASN</b>\n────────────────\n"
        f"👤 <b>NAMA:</b> <code>{user['nama']}</code>\n"
        f"🆔 <b>NIP:</b> <code>{user['nip']}</code>\n"
        f"🎖️ <b>PANGKAT:</b> <code>{user.get('pangkat', '-')}</code>\n"
        f"🛡️ <b>JABATAN:</b> <code>{user.get('jabatan', '-')}</code>\n"
        f"📂 <b>DIVISI:</b> <code>{user.get('divisi', '-')}</code>\n"
        f"📧 <b>EMAIL:</b> <code>{user.get('email', '-')}</code>\n"
        f"🏢 <b>UNIT:</b> <code>{user.get('nama_upt', 'DEFAULT')}</code>\n"
        "────────────────\n"
        f"⏰ <b>OTOMASI IN:</b> <code>{user['cron_in']}</code>{in_label}\n"
        f"⏰ <b>OTOMASI OUT:</b> <code>{user['cron_out']}</code>{out_label}\n"
        f"🗓 <b>HARI KERJA:</b> <code>{user.get('workdays_label', '-')}</code>\n"
        f"🤖 <b>AUTO ABSEN:</b> <code>{auto_status}</code>\n"
        f"ℹ️ <b>INFO:</b> <code>{user.get('auto_attendance_reason', '-')}</code>\n"
        f"📍 <b>LOKASI:</b> <code>{user.get('location_label', '-')}</code>\n"
        f"🧭 <b>KOORDINAT:</b> <code>{coords}</code>\n"
        f"🗂 <b>SUMBER:</b> <code>{str(user.get('location_source', '-')).upper()}</code>\n"
        "────────────────\n"
        f"💎 <b>STATUS:</b> <b>{settings.BOT_EDITION}</b>"
    )
    await services.edit_message(message, response, InlineKeyboardMarkup([[get_sync_sso_button()], [get_back_button()]]))


async def sync_sso_profile(message: Message, *, services: CallbackServices, tid: int) -> None:
    user = services.store.get_user_by_telegram_id(tid)
    if not user:
        return

    await message.edit_text(
        "⏳ <b>SEDANG SINKRONISASI DATA SSO...</b>\n"
        "<i>Menghubungkan ke portal SSO Pusat untuk memverifikasi data Anda.</i>",
        parse_mode=constants.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[get_back_button("view_profile")]]),
    )

    from star_attendance.sso_handler import sync_sso_data

    async def sso_progress(text: str):
        try:
            await message.edit_text(
                f"🔄 <b>SINKRONISASI SSO</b>\n"
                f"────────────────\n"
                f"{text}\n"
                f"────────────────\n"
                f"<i>Mohon tunggu, sedang memproses identitas...</i>",
                parse_mode=constants.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[get_back_button("view_profile")]])
            )
        except: pass

    try:
        # Use existing credentials for SSO with progress reporting
        res = await sync_sso_data(user["nip"], user["password"], on_progress=sso_progress)
        
        if res["status"] == "success":
            await sso_progress("💾 Menyimpan data ke database...")
            data = res["data"]
            # Update user profile in local DB
            update_payload = {}
            if data.get("nama"): update_payload["nama"] = data["nama"]
            if data.get("nama_upt"): update_payload["upt_id"] = data["nama_upt"]
            if data.get("jabatan"): update_payload["jabatan"] = data["jabatan"]
            if data.get("divisi"): update_payload["divisi"] = data["divisi"]
            if data.get("pangkat"): update_payload["pangkat"] = data["pangkat"]
            if data.get("email"): update_payload["email"] = data["email"]
            if data.get("sso_sub"): update_payload["sso_sub"] = data["sso_sub"]
            if data.get("birth_date"): update_payload["birth_date"] = data["birth_date"]
            if data.get("birth_place"): update_payload["birth_place"] = data["birth_place"]

            if update_payload:
                services.store.update_user_settings(user["nip"], update_payload)

            # Formatting Date to Indonesian (e.g., 21 September 1998)
            formatted_birth = data.get('birth_date', '-')
            if formatted_birth and "-" in formatted_birth:
                try:
                    parts = formatted_birth.split("-")
                    months = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]
                    day = int(parts[2])
                    month = months[int(parts[1])]
                    year = parts[0]
                    formatted_birth = f"{day} {month} {year}"
                except: pass

            await message.edit_text(
                "✅ <b>SINKRONISASI BERHASIL</b>\n"
                "Data Anda telah diperbarui dari sistem pusat.\n\n"
                f"👤 <b>Nama:</b> <code>{data.get('nama')}</code>\n"
                f"🔢 <b>NIP:</b> <code>{data.get('nip')}</code>\n"
                f"🆔 <b>SSO UUID:</b> <code>{data.get('sso_sub')}</code>\n\n"
                f"🏢 <b>Unit:</b> <code>{data.get('nama_upt')}</code>\n"
                f"🗂️ <b>Divisi:</b> <code>{data.get('divisi')}</code>\n"
                f"🛡️ <b>Jabatan:</b> <code>{data.get('jabatan')}</code>\n"
                f"🎖️ <b>Golongan:</b> <code>{data.get('pangkat')}</code>\n\n"
                f"🎂 <b>Lahir:</b> <code>{data.get('birth_place')}, {formatted_birth}</code>\n"
                f"📧 <b>Email:</b> <code>{data.get('email')}</code>",
                parse_mode=constants.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[get_back_button("view_profile")]])
            )
        else:
            await message.edit_text(
                f"❌ <b>GAGAL SINKRONISASI</b>\n<code>{res.get('message', 'Unknown Error')}</code>",
                parse_mode=constants.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[get_back_button("view_profile")]])
            )
    except Exception as exc:
        await message.edit_text(
            f"❌ <b>SISTEM ERROR</b>\n<code>{exc}</code>",
            parse_mode=constants.ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup([[get_back_button("view_profile")]])
        )


async def show_scheduler(message: Message, *, services: CallbackServices, restart: bool = False) -> None:
    try:
        payload = await (
            services.internal_api.restart_scheduler() if restart else services.internal_api.get_scheduler_status()
        )
        response = build_scheduler_message(payload)
        if restart:
            response = "♻️ <b>SCHEDULER DIRESTART</b>\n────────────────\n" + response
    except Exception as exc:
        action = "restart scheduler" if restart else "mengambil status scheduler"
        response = f"<b>🕒 SCHEDULER INTERNAL</b>\n────────────────\n❌ Gagal {action}.\n<code>{exc}</code>"
    await services.edit_message(message, response, get_scheduler_keyboard())


async def show_dead_letters(message: Message, *, services: CallbackServices, tid: int) -> None:
    if not services.is_admin(tid):
        return

    dead_letters = services.store.get_recent_dead_letters(limit=10)
    response = "<b>🧨 DAFTAR ANTREAN GAGAL</b>\n────────────────\n"
    if not dead_letters:
        response += "<i>Tidak ada antrean gagal terbaru.</i>"
    for item in dead_letters:
        response += (
            f"• <code>{item['nip']}</code> {str(item['action']).upper()} | attempt={item['attempts']}\n"
            f"  <code>{item['failed_at']}</code>\n"
            f"  <i>{item['reason']}</i>\n"
        )
        if item.get("last_error"):
            response += f"  <code>{item['last_error']}</code>\n"
    await services.edit_message(message, response, InlineKeyboardMarkup([[get_back_button()]]))


async def show_system(message: Message, *, services: CallbackServices, tid: int) -> None:
    if not services.is_admin(tid):
        return

    metrics = services.store.get_metrics_overview(hours=24)
    try:
        health = await services.internal_api.healthz()
        health_text = (
            f"✅ API/DB OK | scheduler=<code>{health.get('scheduler_running')}</code> | "
            f"pgqueuer=<code>{health.get('queue_table_ready')}</code>"
        )
    except Exception as exc:
        health_text = f"❌ Internal API unreachable: <code>{exc}</code>"

    response = (
        "<b>🖥 DIAGNOSTIK SISTEM</b>\n────────────────\n"
        f"⚙️ <b>Beban CPU:</b> <code>{psutil.cpu_percent(interval=0.1)}%</code>\n"
        f"🧠 <b>Penggunaan RAM:</b> <code>{psutil.virtual_memory().percent}%</code>\n"
        f"⏳ <b>Uptime Server:</b> <code>{int(time.time() - psutil.boot_time()) // 3600} jam</code>\n"
        f"🗄 <b>Runtime:</b> {health_text}\n"
        f"📉 <b>Failure Rate 24h:</b> <code>{metrics['failure_rate']:.1%}</code>\n"
        f"🧨 <b>Dead Letters:</b> <code>{metrics['dead_letters']}</code>"
    )
    await services.edit_message(message, response, InlineKeyboardMarkup([[get_back_button()]]))


async def show_stats(message: Message, *, services: CallbackServices, tid: int) -> None:
    if not services.is_admin(tid):
        return

    today = format_formal_date()
    daily = services.store.get_daily_stats()
    metrics = services.store.get_metrics_overview(hours=24)
    mass_status = services.store.get_mass_status()
    response = (
        f"<b>📊 STATISTIK PENGGUNA ({today})</b>\n────────────────\n"
        f"✅ <b>IN OK:</b> <code>{daily.get('in_success', 0)}</code>\n"
        f"❌ <b>IN FAIL:</b> <code>{daily.get('in_failed', 0)}</code>\n"
        f"✅ <b>OUT OK:</b> <code>{daily.get('out_success', 0)}</code>\n"
        f"❌ <b>OUT FAIL:</b> <code>{daily.get('out_failed', 0)}</code>\n\n"
        f"📉 <b>Failure Rate 24h:</b> <code>{metrics['failure_rate']:.1%}</code>\n"
        f"🧨 <b>Dead Letters 24h:</b> <code>{metrics['dead_letters']}</code>\n"
        f"🚀 <b>Mass Active:</b> <code>{mass_status.get('active')}</code>\n"
        f"👤 <b>Last Target:</b> <code>{mass_status.get('last_nip') or '-'}</code>"
    )
    await services.edit_message(message, response, await services.get_main_menu(tid))


async def show_users_page(message: Message, *, services: CallbackServices, tid: int, page: int) -> None:
    if not services.is_admin(tid):
        return
    await services.edit_message(
        message,
        "<b>👥 MANAJEMEN PERSONEL</b>\nPilih personel untuk melihat detail atau melakukan perubahan:",
        await services.get_users_keyboard(page),
    )


async def show_manage_user(message: Message, *, services: CallbackServices, tid: int, target_nip: str) -> None:
    if not services.is_admin(tid):
        return

    user = services.store.get_user_by_nip(target_nip)
    if not user:
        return

    response = build_manage_user_message(user)
    await services.edit_message(message, response, build_user_manage_keyboard(target_nip))


async def trigger_mass_action(
    message: Message,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    services: CallbackServices,
    tid: int,
    action: str,
) -> None:
    if not services.is_admin(tid):
        return

    await message.edit_text(
        f"🚀 <b>MENGEKSEKUSI AKTIVASI {get_action_label(action)}...</b>\n"
        "Menginisialisasi cluster workers untuk seluruh personel.",
        parse_mode=constants.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[get_back_button()]]),
    )
    options = services.build_runtime_options(action)
    services.store.clear_mass_stop()
    asyncio.create_task(mass_attendance(limit=None, options=options))
    asyncio.create_task(monitor_mass_progress(context, message.chat_id, message.message_id, action, tid))


async def trigger_stop(message: Message, *, services: CallbackServices, tid: int) -> None:
    if not services.is_admin(tid):
        return

    services.store.trigger_mass_stop()
    services.store.add_audit_log(
        nip="SYSTEM",
        action="abort",
        status="ok",
        message=f"Admin {tid} issued EMERGENCY STOP signal. Ceasing all cluster operations.",
    )
    await services.edit_message(
        message,
        "🛑 <b>SINYAL PENGHENTIAN DARURAT DIKIRIM</b>\nSemua operasi kluster sedang dihentikan paksa.",
        InlineKeyboardMarkup([[get_back_button()]]),
    )


async def trigger_single_action(
    message: Message,
    *,
    services: CallbackServices,
    tid: int,
    target_nip: str,
    action: str,
) -> None:
    if not services.is_admin(tid):
        return

    user = services.store.get_user_by_nip(target_nip)
    if not user:
        await services.edit_message(
            message, "❌ Personel tidak ditemukan.", InlineKeyboardMarkup([[get_back_button()]])
        )
        return

    action_name = "MASUK" if action.lower() == "in" else "PULANG"
    # 1. Send initial processing message
    sent_msg = await message.edit_text(
        f"⏳ <b>MEMPROSES PRESENSI {action_name}...</b>\n"
        f"👤 <b>Target:</b> <code>{user['nama']}</code>\n"
        "<i>Mohon tunggu, sedang melakukan verifikasi keamanan & memproses data.</i>",
        parse_mode=constants.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[get_back_button(f"manage_user_{target_nip}")]])
    )

    # 2. Prepare options
    class Options:
        def __init__(self, action, store):
            self.action = action
            self.store = store
            self.source = "admin_manual"
            self.request_key = str(uuid.uuid4())

    import uuid

    options = Options(action, services.store)

    # 3. Status Callback for real-time updates
    async def status_callback(status_msg: str):
        try:
            # Reconstruct the processing message with current status
            updated_text = (
                f"⌛ <b>STATUS ABSENSI {get_action_label(action)}...</b>\n"
                f"👤 <b>Target:</b> <code>{user['nama']}</code>\n"
                f"<i>{status_msg}</i>"
            )
            if isinstance(sent_msg, Message):
                await services.edit_message(sent_msg, updated_text, InlineKeyboardMarkup([[get_back_button(f"manage_user_{target_nip}")]]))
        except Exception:
            pass

    # 4. Process in background and update UI on completion
    async def run_and_update():
        try:
            # We use process_single_user directly for immediate result
            success, result_msg = await process_single_user(
                user,
                options,
                1,
                1,
                is_mass=False,
                status_callback=status_callback,
                user_message_id=sent_msg.message_id,
            )

            # The result_msg from process_single_user is already formatted for Telegram
            if result_msg:
                # Add a back button to the result
                keyboard = InlineKeyboardMarkup(
                    [[InlineKeyboardButton("◀️ Kembali ke Menu User", callback_data=f"manage_user_{target_nip}")]]
                )
                await services.edit_message(sent_msg, result_msg, keyboard)
            else:
                status = "BERHASIL" if success else "GAGAL"
                await services.edit_message(
                    sent_msg,
                    f"✅ <b>ABSENSI SELESAI ({status})</b>\nSila cek log untuk detail lengkap.",
                    InlineKeyboardMarkup(
                        [[InlineKeyboardButton("◀️ Kembali", callback_data=f"manage_user_{target_nip}")]]
                    ),
                )
        except Exception as exc:
            await services.edit_message(
                sent_msg, f"❌ <b>SISTEM ERROR</b>\n<code>{exc}</code>", InlineKeyboardMarkup([[get_back_button()]])
            )

    asyncio.create_task(run_and_update())


async def handle_callback(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    services: CallbackServices,
) -> None:
    query = update.callback_query
    if not query or not query.from_user or not query.message or not isinstance(query.message, Message):
        return

    await query.answer()
    tid = query.from_user.id
    data = query.data or ""
    message = query.message
    from star_attendance.core.utils import log as core_log
    core_log("INFO", f"callback-received data={data} user={tid}", scope="BOT")

    try:
        target_nip: str | None = None
        if data == "noop":
            return
        if data == "main_menu":
            user = services.store.get_user_by_telegram_id(tid)
            await services.edit_message(
                message, build_dashboard_message(user, store=services.store), await services.get_main_menu(tid)
            )
            return
        if data == "start_settings_menu":
            await services.edit_message(
                message,
                "<b>⚙️ PENGATURAN</b>\n────────────────\nSilakan pilih konfigurasi yang ingin Anda ubah:",
                get_settings_menu(),
            )
            return
        if data == "view_history":
            await show_history(message, services=services, tid=tid)
            return
        if data == "view_help":
            response = (
                f"<b>📖 PANDUAN PENGGUNA (V{settings.BOT_VERSION})</b>\n"
                "────────────────\n"
                "<b>DASHBOARD:</b> Pantau status & profil Anda secara real-time.\n"
                "<b>RIWAYAT:</b> Cek log keberhasilan absen otomatis.\n"
                "<b>PENGATURAN:</b> Sesuaikan jam, hari kerja, dan lokasi GPS kustom.\n\n"
                "<i>Sistem ini bekerja otomatis sesuai jadwal. Pastikan kredensial Anda tetap valid.</i>"
            )
            await services.edit_message(message, response, InlineKeyboardMarkup([[get_back_button()]]))
            return
        if data == "view_support":
            await show_support(message)
            return
        if data == "view_global_logs":
            await show_global_logs(message, services=services, tid=tid)
            return
        if data == "view_profile":
            await show_profile(message, services=services, tid=tid)
            return
        if data == "sync_sso_profile":
            await sync_sso_profile(message, services=services, tid=tid)
            return
        if data == "view_global_settings":
            if not services.is_admin(tid):
                return
            await services.edit_message(
                message, build_global_settings_message(store=services.store), get_global_settings_keyboard()
            )
            return
        if data == "view_scheduler":
            if not services.is_admin(tid):
                return
            await show_scheduler(message, services=services)
            return
        if data == "restart_scheduler":
            if not services.is_admin(tid):
                return
            await show_scheduler(message, services=services, restart=True)
            return
        if data == "view_dead_letters":
            await show_dead_letters(message, services=services, tid=tid)
            return
        if data == "view_system":
            await show_system(message, services=services, tid=tid)
            return
        if data == "view_stats":
            await show_stats(message, services=services, tid=tid)
            return
        if data.startswith("view_users_list_"):
            await show_users_page(message, services=services, tid=tid, page=int(data.split("_")[-1]))
            return
        if data.startswith("manage_user_"):
            await show_manage_user(message, services=services, tid=tid, target_nip=data.replace("manage_user_", ""))
            return
        if data.startswith("force_in_"):
            await trigger_single_action(
                message, services=services, tid=tid, target_nip=data.replace("force_in_", ""), action="in"
            )
            return
        if data.startswith("force_out_"):
            await trigger_single_action(
                message, services=services, tid=tid, target_nip=data.replace("force_out_", ""), action="out"
            )
            return
        if data in {"trigger_in", "trigger_out"}:
            await trigger_mass_action(message, context, services=services, tid=tid, action=cast(str, data).split("_")[1])
            return
        if data == "trigger_stop":
            await trigger_stop(message, services=services, tid=tid)
            return
        if data == "view_allowance_menu":
            await show_allowance(message, services=services, tid=tid)
            return
        if data.startswith("view_allowance_nip_"):
            target_nip = data.replace("view_allowance_nip_", "")
            await show_allowance(message, services=services, tid=tid, target_nip=target_nip)
            return
        if data.startswith("allowance_periods|"):
            try:
                parts = data.split("|")
                year_text = parts[1]
                target_nip = parts[2] if len(parts) > 2 else None
                await show_allowance_period_selector(
                    message, services=services, tid=tid, year=int(year_text), target_nip=target_nip
                )
            except (ValueError, IndexError):
                await show_allowance_period_selector(message, services=services, tid=tid)
            return
        if data.startswith("allowance_period|"):
            try:
                parts = data.split("|")
                period_code = parts[1]
                year_text = parts[2]
                target_nip = parts[3] if len(parts) > 3 else None
                await show_allowance(
                    message,
                    services=services,
                    tid=tid,
                    period_code=period_code,
                    year=int(year_text),
                    target_nip=target_nip,
                )
            except (ValueError, IndexError):
                await show_allowance(message, services=services, tid=tid)
            return
        if data.startswith("smart_allowance|"):
            try:
                parts = data.split("|")
                period_code = parts[1]
                year_text = parts[2]
                target_nip = parts[3] if len(parts) > 3 else None
                
                # Check if we have data locally
                nip: str | None = target_nip
                if not nip:
                    u = services.store.get_user_by_telegram_id(tid)
                    nip = u["nip"] if u else None
                
                if nip:
                    allowances = get_allowance_rows(services.store, nip, period_code, int(year_text))
                    if allowances:
                        # Data exists, just show it
                        await show_allowance(message, services=services, tid=tid, period_code=period_code, year=int(year_text), target_nip=target_nip)
                    else:
                        # No data, auto-sync
                        await sync_allowance(message, services=services, tid=tid, period_code=period_code, year=int(year_text), target_nip=target_nip)
                else:
                    await show_allowance(message, services=services, tid=tid)
            except Exception:
                await show_allowance(message, services=services, tid=tid)
            return
        if data == "sync_allowance":
            await sync_allowance(message, services=services, tid=tid)
            return
        if data.startswith("sync_allowance|"):
            try:
                parts = data.split("|")
                period_code = parts[1]
                year_text = parts[2]
                target_nip = parts[3] if len(parts) > 3 else None
                await sync_allowance(
                    message,
                    services=services,
                    tid=tid,
                    period_code=period_code,
                    year=int(year_text),
                    target_nip=target_nip,
                )
            except (ValueError, IndexError):
                await sync_allowance(message, services=services, tid=tid)
            return
    except Exception as exc:
        from star_attendance.core.utils import log as core_log
        core_log("ERROR", f"callback-error data={data} user={tid} error={exc}", scope="BOT")
        try:
            await query.edit_message_text(
                f"❌ <b>KESALAHAN SISTEM</b>\nTerjadi kesalahan saat memproses permintaan Anda.\n<code>{exc}</code>",
                parse_mode=constants.ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup([[get_back_button()]]),
            )
        except Exception:
            pass


def get_allowance_rows(store: Any, nip: str, period_code: str, year: int) -> list[dict[str, Any]]:
    get_user_allowance = getattr(store, "get_user_performance_allowance", None)
    if callable(get_user_allowance):
        return cast(list[dict[str, Any]], get_user_allowance(nip, period_code, year))

    get_personal_allowance = getattr(store, "get_personal_allowance", None)
    if callable(get_personal_allowance):
        try:
            return cast(list[dict[str, Any]], get_personal_allowance(nip, period_code, year))
        except TypeError:
            return cast(list[dict[str, Any]], get_personal_allowance(nip, period_code))
    return []


def get_allowance_periods(store: Any, nip: str, year: int) -> list[dict[str, Any]]:
    get_periods = getattr(store, "get_user_performance_allowance_periods", None)
    if callable(get_periods):
        return cast(list[dict[str, Any]], get_periods(nip, year))
    return []


async def show_allowance(
    message: Message,
    *,
    services: CallbackServices,
    tid: int,
    period_code: str | None = None,
    year: int | None = None,
    target_nip: str | None = None,
) -> None:
    if target_nip:
        user = services.store.get_user_by_nip(target_nip)
    else:
        user = services.store.get_user_by_telegram_id(tid)

    if not user:
        return

    from star_attendance.allowance_handler import AllowanceHandler

    target_year = year or now_local().year
    cached_periods = get_allowance_periods(services.store, user["nip"], target_year)

    selected_period = period_code
    if not selected_period and cached_periods:
        selected_period = str(cached_periods[0].get("period_code") or "")

    if not selected_period:
        current_period, current_year = AllowanceHandler.get_current_period_code()
        previous_period, previous_year = AllowanceHandler.get_previous_period_code()
        fallback_candidates: list[str] = []
        if current_year == target_year:
            fallback_candidates.append(current_period)
        if previous_year == target_year and previous_period not in fallback_candidates:
            fallback_candidates.append(previous_period)
        if not fallback_candidates:
            fallback_candidates = [
                option.period_code for option in AllowanceHandler.build_fallback_period_options(target_year)
            ]
        selected_period = fallback_candidates[0]

    allowances = get_allowance_rows(services.store, user["nip"], selected_period, target_year)
    if not allowances and period_code is None:
        current_period, current_year = AllowanceHandler.get_current_period_code()
        previous_period, previous_year = AllowanceHandler.get_previous_period_code()
        fallback_candidates = [
            candidate
            for candidate, candidate_year in [(current_period, current_year), (previous_period, previous_year)]
            if candidate_year == target_year and candidate != selected_period
        ]
        for candidate in fallback_candidates:
            candidate_rows = get_allowance_rows(services.store, user["nip"], candidate, target_year)
            if candidate_rows:
                selected_period = candidate
                allowances = candidate_rows
                break

    readable_period = AllowanceHandler.format_period_code(selected_period)

    response = (
        "<b>💰 TUNJANGAN KINERJA</b>\n"
        f"📅 Periode: <code>{readable_period}</code>\n"
        f"🗓 Tahun: <code>{target_year}</code>\n"
        "────────────────\n"
    )
    if not allowances:
        response += (
            "<i>⚠️ Data untuk periode ini belum tersedia di database bot.</i>\n\n"
            "Klik tombol <b>Update Data</b> di bawah untuk mengambil rincian tunjangan langsung dari portal budget."
        )
    else:
        try:

            def parse_idr(val: str) -> float:
                return float(val.replace(".", "").replace(",", "."))

            total_sum = sum(parse_idr(item["total"]) for item in allowances)
            total_deduction = sum(parse_idr(item["deduction_amount"]) for item in allowances)
            formatted_sum = "{:,.2f}".format(total_sum).replace(",", "X").replace(".", ",").replace("X", ".")
            formatted_deduction = (
                "{:,.2f}".format(total_deduction).replace(",", "X").replace(".", ",").replace("X", ".")
            )
        except Exception:
            formatted_sum = "ERROR"
            formatted_deduction = "ERROR"

        response += (
            f"📊 <b>ESTIMASI TOTAL:</b> <code>Rp {formatted_sum}</code>\n"
            f"🔻 <b>TOTAL POTONGAN:</b> <code>Rp {formatted_deduction}</code>\n"
            f"📅 <b>HARI TERCATAT:</b> <code>{len(allowances)} hari</code>\n\n"
        )

        # Show all recorded days in the period
        for item in allowances:
            response += (
                f"📅 <code>{item['date']}</code> | <b>Rp {item['total']}</b>\n"
                f"   └ Masuk: <code>{item['clock_in']}</code> Keluar: <code>{item['clock_out']}</code>\n"
            )
            if item.get("deduction_reason"):
                response += f"   ⚠️ <i>{item['deduction_reason']} (-{item['deduction_amount']})</i>\n"

    keyboard = [
        [
            InlineKeyboardButton(
                "🔄 UPDATE DATA DARI PORTAL",
                callback_data=f"sync_allowance|{selected_period}|{target_year}"
                + (f"|{target_nip}" if target_nip else ""),
            )
        ],
        [
            InlineKeyboardButton(
                "📅 LIHAT PERIODE LAIN",
                callback_data=f"allowance_periods|{target_year}" + (f"|{target_nip}" if target_nip else "")
            )
        ],
    ]

    if target_nip:
        keyboard.append([InlineKeyboardButton("◀️ KEMBALI KE MANAJEMEN", callback_data=f"manage_user_{target_nip}")])
    else:
        keyboard.append([get_back_button()])

    await services.edit_message(message, response, InlineKeyboardMarkup(keyboard))


async def show_allowance_period_selector(
    message: Message,
    *,
    services: CallbackServices,
    tid: int,
    year: int | None = None,
    target_nip: str | None = None,
) -> None:
    if target_nip:
        user = services.store.get_user_by_nip(target_nip)
    else:
        user = services.store.get_user_by_telegram_id(tid)

    if not user:
        return

    from star_attendance.allowance_handler import AllowanceHandler, list_user_allowance_periods

    target_year = year or now_local().year
    periods: list[dict[str, Any]] = []
    note = "<i>Daftar periode diambil langsung dari portal.</i>"

    try:
        portal_periods = await list_user_allowance_periods(user["nip"], year=target_year)
        if portal_periods.get("status") == "success":
            periods = cast(list[dict[str, Any]], portal_periods.get("periods") or [])
        else:
            note = "<i>Portal belum bisa diakses. Menampilkan periode dari cache lokal/template tahun berjalan.</i>"
    except Exception:
        note = "<i>Portal belum bisa diakses. Menampilkan periode dari cache lokal/template tahun berjalan.</i>"

    if not periods:
        periods = get_allowance_periods(services.store, user["nip"], target_year)

    if not periods:
        periods = [
            AllowanceHandler.serialize_period_option(option)
            for option in AllowanceHandler.build_fallback_period_options(target_year)
        ]

    response = (
        "<b>🗓 PILIH PERIODE TUNJANGAN</b>\n"
        f"🗓 Tahun: <code>{target_year}</code>\n"
        "────────────────\n"
        f"{note}"
    )

    keyboard: list[list[InlineKeyboardButton]] = []
    current_row: list[InlineKeyboardButton] = []
    for period in periods:
        code = str(period.get("period_code") or "")
        label = str(
            period.get("label")
            or period.get("period_label")
            or period.get("readable_period")
            or AllowanceHandler.format_period_code(code)
        )
        current_row.append(
            InlineKeyboardButton(
                label,
                callback_data=f"smart_allowance|{code}|{target_year}" + (f"|{target_nip}" if target_nip else ""),
            )
        )
        if len(current_row) == 2:
            keyboard.append(current_row)
            current_row = []
    if current_row:
        keyboard.append(current_row)
    if target_nip:
        keyboard.append([InlineKeyboardButton("◀️ KEMBALI KE DETAIL", callback_data=f"view_allowance_nip_{target_nip}")])
    else:
        keyboard.append([InlineKeyboardButton("◀️ KEMBALI KE DETAIL", callback_data="view_allowance_menu")])

    await services.edit_message(message, response, InlineKeyboardMarkup(keyboard))


async def sync_allowance(
    message: Message,
    *,
    services: CallbackServices,
    tid: int,
    period_code: str | None = None,
    year: int | None = None,
    target_nip: str | None = None,
) -> None:
    if target_nip:
        user = services.store.get_user_by_nip(target_nip)
    else:
        user = services.store.get_user_by_telegram_id(tid)

    if not user:
        return

    target_year = year or now_local().year
    target_period = period_code

    await message.edit_text(
        "⏳ <b>SEDANG MENGAMBIL DATA TUNJANGAN...</b>\n"
        "<i>Mohon tunggu, sedang login ke portal budget & mengekstraksi data periode yang dipilih.</i>",
        parse_mode=constants.ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup([[get_back_button("view_allowance_menu")]]),
    )

    from star_attendance.allowance_handler import sync_user_allowance

    try:
        result = await sync_user_allowance(user["nip"], period_code=target_period, year=target_year)
        if result.get("status") == "success":
            await show_allowance(
                message,
                services=services,
                tid=tid,
                period_code=cast(str | None, result.get("period")) or target_period,
                year=cast(int | None, result.get("year")) or target_year,
                target_nip=target_nip,
            )
        else:
            msg = result.get("message", "Unknown Error")
            if msg == "session_expired":
                msg = "Sesi portal expired. Silakan lakukan absen manual untuk memperbarui sesi."
            await services.edit_message(
                message,
                f"❌ <b>GAGAL SINKRONISASI</b>\n<code>{msg}</code>",
                InlineKeyboardMarkup([[get_back_button()]]),
            )
    except Exception as exc:
        await services.edit_message(
            message, f"❌ <b>SISTEM ERROR</b>\n<code>{exc}</code>", InlineKeyboardMarkup([[get_back_button()]])
        )
