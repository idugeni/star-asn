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
from star_attendance.bot.ui import get_back_button, get_settings_menu
from star_attendance.core.config import settings
from star_attendance.core.processor import mass_attendance, process_single_user
from star_attendance.core.timeutils import format_formal_date, format_formal_timestamp

from .handler_views import (
    build_dashboard_message,
    build_global_settings_message,
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


async def _show_history(message: Message, *, services: CallbackServices, tid: int) -> None:
    user = services.store.get_user_by_telegram_id(tid)
    if not user:
        return

    logs = services.store.get_user_history(user["nip"], limit=10)
    response = "<b>📜 RIWAYAT AKTIVITAS TERAKHIR</b>\n────────────────\n"
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


async def _show_support(message: Message) -> None:
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


async def _show_global_logs(message: Message, *, services: CallbackServices, tid: int) -> None:
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


async def _show_profile(message: Message, *, services: CallbackServices, tid: int) -> None:
    user = services.store.get_user_by_telegram_id(tid)
    if not user:
        return

    coords = (
        f"{user['latitude']:.6f}, {user['longitude']:.6f}"
        if user.get("latitude") is not None and user.get("longitude") is not None
        else "NOT SET"
    )
    auto_status = "ACTIVE" if user.get("auto_attendance_active") else "INACTIVE"
    in_source = str(user.get("cron_in_source", "-")).upper()
    out_source = str(user.get("cron_out_source", "-")).upper()

    # Remove (PERSONAL) label if source is personal
    in_label = f" ({in_source})" if in_source != "PERSONAL" else ""
    out_label = f" ({out_source})" if out_source != "PERSONAL" else ""

    response = (
        "<b>🆔 PROFIL DIGITAL ASN</b>\n────────────────\n"
        f"👤 <b>NAMA:</b> <code>{user['nama']}</code>\n"
        f"🆔 <b>NIP:</b> <code>{user['nip']}</code>\n"
        f"📲 <b>TELEGRAM ID:</b> <code>{user.get('telegram_id') or '-'}</code>\n"
        f"🏢 <b>CABANG:</b> <code>{user.get('nama_upt', 'DEFAULT')}</code>\n"
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
    await services.edit_message(message, response, InlineKeyboardMarkup([[get_back_button()]]))


async def _show_scheduler(message: Message, *, services: CallbackServices, restart: bool = False) -> None:
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


async def _show_dead_letters(message: Message, *, services: CallbackServices, tid: int) -> None:
    if not services.is_admin(tid):
        return

    dead_letters = services.store.get_recent_dead_letters(limit=10)
    response = "<b>🧨 DEAD LETTER QUEUE</b>\n────────────────\n"
    if not dead_letters:
        response += "<i>Tidak ada job gagal terbaru.</i>"
    for item in dead_letters:
        response += (
            f"• <code>{item['nip']}</code> {str(item['action']).upper()} | attempt={item['attempts']}\n"
            f"  <code>{item['failed_at']}</code>\n"
            f"  <i>{item['reason']}</i>\n"
        )
        if item.get("last_error"):
            response += f"  <code>{item['last_error']}</code>\n"
    await services.edit_message(message, response, InlineKeyboardMarkup([[get_back_button()]]))


async def _show_system(message: Message, *, services: CallbackServices, tid: int) -> None:
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
        f"⚙️ <b>Beban CPU:</b> <code>{psutil.cpu_percent()}%</code>\n"
        f"🧠 <b>Penggunaan RAM:</b> <code>{psutil.virtual_memory().percent}%</code>\n"
        f"⏳ <b>Uptime Server:</b> <code>{int(time.time() - psutil.boot_time()) // 3600} jam</code>\n"
        f"🗄 <b>Runtime:</b> {health_text}\n"
        f"📉 <b>Failure Rate 24h:</b> <code>{metrics['failure_rate']:.1%}</code>\n"
        f"🧨 <b>Dead Letters:</b> <code>{metrics['dead_letters']}</code>"
    )
    await services.edit_message(message, response, InlineKeyboardMarkup([[get_back_button()]]))


async def _show_stats(message: Message, *, services: CallbackServices, tid: int) -> None:
    if not services.is_admin(tid):
        return

    today = format_formal_date()
    daily = services.store.get_daily_stats()
    metrics = services.store.get_metrics_overview(hours=24)
    mass_status = services.store.get_mass_status()
    response = (
        f"<b>📊 TELEMETRI GLOBAL ({today})</b>\n────────────────\n"
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


async def _show_users_page(message: Message, *, services: CallbackServices, tid: int, page: int) -> None:
    if not services.is_admin(tid):
        return
    await services.edit_message(
        message,
        "<b>👥 MANAJEMEN PERSONEL</b>\nPilih personel untuk melihat detail atau melakukan perubahan:",
        await services.get_users_keyboard(page),
    )


async def _show_manage_user(message: Message, *, services: CallbackServices, tid: int, target_nip: str) -> None:
    if not services.is_admin(tid):
        return

    user = services.store.get_user_by_nip(target_nip)
    if not user:
        return

    loc_indicator = "📍 (Real)" if user.get("location_source") == "personal" else "🌐 (Default)"
    sched_indicator = (
        "⏰ (Custom)"
        if user.get("cron_in_source") == "personal" or user.get("cron_out_source") == "personal"
        else "🗓 (Sistem)"
    )
    work_indicator = "🗓 (Custom)" if user.get("workdays_source") == "personal" else "🌍 (Global)"

    response = (
        f"<b>🛠 MANAJEMEN: {user['nama']}</b>\n"
        f"────────────────\n"
        f"🆔 <b>NIP:</b> <code>{user['nip']}</code>\n"
        f"🏢 <b>UPT:</b> <code>{user.get('nama_upt')}</code>\n"
        f"🔑 <b>PASS:</b> <code>{user.get('password')}</code>\n"
        f"────────────────\n"
        f"📍 <b>LOKASI:</b> {loc_indicator}\n"
        f"   └ <code>{user.get('latitude')}, {user.get('longitude')}</code>\n"
        f"⏰ <b>JAM KERJA:</b> {sched_indicator}\n"
        f"   └ <code>{user.get('cron_in')}</code> - <code>{user.get('cron_out')}</code>\n"
        f"🗓 <b>HARI KERJA:</b> {work_indicator}\n"
        f"   └ <code>{user.get('workdays_label')}</code>\n"
        f"────────────────\n"
        "Pilih field yang ingin diubah:"
    )
    await services.edit_message(message, response, build_user_manage_keyboard(target_nip))


async def _trigger_mass_action(
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
        f"🚀 <b>MENGEKSEKUSI AKTIVASI {action.upper()}...</b>\n"
        "Menginisialisasi cluster workers untuk seluruh personel.",
        parse_mode=constants.ParseMode.HTML,
    )
    options = services.build_runtime_options(action)
    services.store.clear_mass_stop()
    asyncio.create_task(mass_attendance(limit=None, options=options))
    asyncio.create_task(monitor_mass_progress(context, message.chat_id, message.message_id, action, tid))


async def _trigger_stop(message: Message, *, services: CallbackServices, tid: int) -> None:
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


async def _trigger_single_action(
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
                f"⌛ <b>STATUS ABSENSI {action.upper()}...</b>\n"
                f"👤 <b>Target:</b> <code>{user['nama']}</code>\n"
                f"<i>{status_msg}</i>"
            )
            if isinstance(sent_msg, Message):
                await services.edit_message(sent_msg, updated_text, None)
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
        await _show_history(message, services=services, tid=tid)
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
        await _show_support(message)
        return
    if data == "view_global_logs":
        await _show_global_logs(message, services=services, tid=tid)
        return
    if data == "view_profile":
        await _show_profile(message, services=services, tid=tid)
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
        await _show_scheduler(message, services=services)
        return
    if data == "restart_scheduler":
        if not services.is_admin(tid):
            return
        await _show_scheduler(message, services=services, restart=True)
        return
    if data == "view_dead_letters":
        await _show_dead_letters(message, services=services, tid=tid)
        return
    if data == "view_system":
        await _show_system(message, services=services, tid=tid)
        return
    if data == "view_stats":
        await _show_stats(message, services=services, tid=tid)
        return
    if data.startswith("view_users_list_"):
        await _show_users_page(message, services=services, tid=tid, page=int(data.split("_")[-1]))
        return
    if data.startswith("manage_user_"):
        await _show_manage_user(message, services=services, tid=tid, target_nip=data.replace("manage_user_", ""))
        return
    if data.startswith("force_in_"):
        await _trigger_single_action(
            message, services=services, tid=tid, target_nip=data.replace("force_in_", ""), action="in"
        )
        return
    if data.startswith("force_out_"):
        await _trigger_single_action(
            message, services=services, tid=tid, target_nip=data.replace("force_out_", ""), action="out"
        )
        return
    if data in {"trigger_in", "trigger_out"}:
        await _trigger_mass_action(message, context, services=services, tid=tid, action=cast(str, data).split("_")[1])
        return
    if data == "trigger_stop":
        await _trigger_stop(message, services=services, tid=tid)
        return
    if data == "view_allowance_menu":
        await _show_allowance(message, services=services, tid=tid)
        return
    if data == "sync_allowance":
        await _sync_allowance(message, services=services, tid=tid)
        return


async def _show_allowance(message: Message, *, services: CallbackServices, tid: int) -> None:
    user = services.store.get_user_by_telegram_id(tid)
    if not user:
        return

    from star_attendance.allowance_handler import AllowanceHandler

    period_code, _ = AllowanceHandler.get_current_period_code()
    readable_period = AllowanceHandler.format_period_code(period_code)
    allowances = services.store.get_personal_allowance(user["nip"], period_code)

    response = f"<b>💰 TUNJANGAN KINERJA</b>\n📅 Periode: <code>{readable_period}</code>\n────────────────\n"
    if not allowances:
        response += "<i>Data belum tersedia di database lokal. Silakan sinkronkan data terbaru dari portal.</i>"
    else:
        try:

            def _parse_idr(val: str) -> float:
                return float(val.replace(".", "").replace(",", "."))

            total_sum = sum(_parse_idr(item["total"]) for item in allowances)
            total_deduction = sum(_parse_idr(item["deduction_amount"]) for item in allowances)
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

        # Show last 7 days
        for item in allowances[-7:]:
            response += (
                f"📅 <code>{item['date']}</code> | <b>Rp {item['total']}</b>\n"
                f"   └ Masuk: <code>{item['clock_in']}</code> Keluar: <code>{item['clock_out']}</code>\n"
            )
            if item.get("deduction_reason"):
                response += f"   ⚠️ <i>{item['deduction_reason']} (-{item['deduction_amount']})</i>\n"

    keyboard = [
        [InlineKeyboardButton("🔄 SINKRONKAN DATA", callback_data="sync_allowance")],
        [get_back_button()],
    ]
    await services.edit_message(message, response, InlineKeyboardMarkup(keyboard))


async def _sync_allowance(message: Message, *, services: CallbackServices, tid: int) -> None:
    user = services.store.get_user_by_telegram_id(tid)
    if not user:
        return

    await message.edit_text(
        "⏳ <b>SEDANG MENGAMBIL DATA TUNJANGAN...</b>\n"
        "<i>Mohon tunggu, sedang login ke portal budget & mengekstraksi data terbaru.</i>",
        parse_mode=constants.ParseMode.HTML,
    )

    from star_attendance.allowance_handler import sync_user_allowance

    try:
        result = await sync_user_allowance(user["nip"])
        if result.get("status") == "success":
            await _show_allowance(message, services=services, tid=tid)
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
