from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Message, constants

from star_attendance.bot.ui import get_back_button
from star_attendance.core.config import settings
from star_attendance.core.timeutils import format_formal_timestamp
from star_attendance.database_manager import get_workday_label

UserPayload = Mapping[str, Any]


def _format_coords(user: UserPayload) -> str:
    latitude = user.get("latitude")
    longitude = user.get("longitude")
    if latitude is None or longitude is None:
        return "BELUM TERSEDIA"
    return f"{float(latitude):.6f}, {float(longitude):.6f}"


def _format_source(source: str | None) -> str:
    mapping = {
        "personal": "PERSONAL",
        "upt": "UPT",
        "default": "DEFAULT",
    }
    return mapping.get(str(source or "").lower(), "UNKNOWN")


def build_dashboard_message(user: UserPayload | None, *, store: Any) -> str:
    header = f"<b>🛡️ {settings.BOT_NAME} DASHBOARD UTAMA</b>"
    if user:
        last_actions = store.get_last_success_actions(str(user["nip"]))
        last_in_str = format_formal_timestamp(last_actions.get("in")) if last_actions.get("in") else "BELUM ADA"
        last_out_str = format_formal_timestamp(last_actions.get("out")) if last_actions.get("out") else "BELUM ADA"
        telegram_id = user.get("telegram_id") or "-"
        auto_status = "AKTIF" if user.get("auto_attendance_active") else "NONAKTIF"
        in_source = str(user.get("cron_in_source", "-")).upper()
        out_source = str(user.get("cron_out_source", "-")).upper()
        
        in_label = ""
        out_label = ""

        body = (
            "👤 <b>DATA PERSONEL</b>\n"
            f"  ├ NAMA: <code>{user['nama']}</code>\n"
            f"  ├ NIP: <code>{user['nip']}</code>\n"
            f"  ├ TELEGRAM ID: <code>{telegram_id}</code>\n"
            f"  └ UNIT: <code>{user.get('nama_upt', 'CLUSTER DEFAULT')}</code>\n\n"
            "⏰ <b>JADWAL OPERASIONAL</b>\n"
            f"  ├ AUTO-MASUK: <code>{user['cron_in']}</code>{in_label}\n"
            f"  ├ AUTO-PULANG: <code>{user['cron_out']}</code>{out_label}\n"
            f"  ├ HARI KERJA: <code>{user.get('workdays_label', '-')}</code>\n"
            f"  ├ STATUS USER: <code>{'AKTIF' if user.get('is_active', True) else 'NONAKTIF'}</code>\n"
            f"  ├ STATUS AUTO ABSEN: <code>{auto_status}</code>\n"
            f"  └ INFO: <code>{user.get('auto_attendance_reason', '-')}</code>\n\n"
            "📍 <b>LOKASI ABSENSI</b>\n"
            f"  ├ SUMBER: <code>{_format_source(str(user.get('location_source')))}</code>\n"
            f"  ├ NAMA LOKASI: <code>{user.get('location_label', user.get('nama_upt', '-'))}</code>\n"
            f"  └ KOORDINAT: <code>{_format_coords(user)}</code>\n\n"
            "📊 <b>RINGKASAN AKTIVITAS</b>\n"
            f"  ├ PRESENSI MASUK: <code>{last_in_str}</code>\n"
            f"  └ PRESENSI PULANG: <code>{last_out_str}</code>"
        )
    else:
        body = "<i>⚠️ Administrator Mode: Session Active</i>"

    footer = (
        "────────────────\n"
        f"⚡ <b>STATUS:</b> <code>READY</code> ({format_formal_timestamp()})\n"
        f"💎 <b>EDITION:</b> <b>{settings.BOT_EDITION}</b>"
    )
    return f"{header}\n────────────────\n{body}\n{footer}"


@lru_cache(maxsize=1)
def get_global_settings_keyboard() -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("📍 Nama Lokasi", callback_data="global_edit_default_location"),
            InlineKeyboardButton("🧭 Latitude", callback_data="global_edit_default_latitude"),
        ],
        [
            InlineKeyboardButton("🗺 Longitude", callback_data="global_edit_default_longitude"),
            InlineKeyboardButton("🌍 Timezone", callback_data="global_edit_timezone"),
        ],
        [
            InlineKeyboardButton("🕗 Rule IN", callback_data="global_edit_rule_in_before"),
            InlineKeyboardButton("🕔 Rule OUT", callback_data="global_edit_rule_out_after"),
        ],
        [
            InlineKeyboardButton("🧠 Mode", callback_data="global_edit_rule_mode"),
            InlineKeyboardButton("⏱ Jam Kerja", callback_data="global_edit_rule_work_hours"),
        ],
        [
            InlineKeyboardButton("🚀 Cron IN", callback_data="global_edit_cron_in"),
            InlineKeyboardButton("🏁 Cron OUT", callback_data="global_edit_cron_out"),
        ],
        [
            InlineKeyboardButton("🗓 Hari Kerja", callback_data="global_edit_default_workdays"),
            InlineKeyboardButton("🤖 Automation", callback_data="global_edit_automation_enabled"),
        ],
        [
            InlineKeyboardButton("🔎 OCR", callback_data="global_edit_ocr_engine"),
        ],
        [get_back_button()],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_global_settings_message(*, store: Any) -> str:
    current = store.get_settings()
    return (
        "<b>🌐 GLOBAL SETTINGS</b>\n────────────────\n"
        f"📍 <b>Default Location:</b> <code>{current.get('default_location')}</code>\n"
        f"🧭 <b>Default Latitude:</b> <code>{current.get('default_latitude')}</code>\n"
        f"🗺 <b>Default Longitude:</b> <code>{current.get('default_longitude')}</code>\n"
        f"🌍 <b>Timezone:</b> <code>{current.get('timezone')}</code>\n"
        f"🕗 <b>Rule IN:</b> <code>{current.get('rule_in_before')}</code>\n"
        f"🕔 <b>Rule OUT:</b> <code>{current.get('rule_out_after')}</code>\n"
        f"🧠 <b>Rule Mode:</b> <code>{current.get('rule_mode')}</code>\n"
        f"⏱ <b>Work Hours:</b> <code>{current.get('rule_work_hours')}</code>\n"
        f"🚀 <b>Default Cron IN:</b> <code>{current.get('cron_in')}</code>\n"
        f"🏁 <b>Default Cron OUT:</b> <code>{current.get('cron_out')}</code>\n"
        f"🗓 <b>Default Workdays:</b> <code>{get_workday_label(current.get('default_workdays'))}</code>\n"
        f"🤖 <b>Automation:</b> <code>{current.get('automation_enabled')}</code>\n"
        f"🔎 <b>OCR Engine:</b> <code>{current.get('ocr_engine')}</code>"
    )


@lru_cache(maxsize=1)
def get_scheduler_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("♻️ RESTART SCHEDULER", callback_data="restart_scheduler")],
            [get_back_button()],
        ]
    )


def build_scheduler_message(status_payload: Mapping[str, Any]) -> str:
    jobs = list(status_payload.get("jobs", []))
    preview = [
        f"• <code>{job['nip']}</code> {str(job['action']).upper()} @ <code>{job['next_run']}</code> | <code>{job.get('workdays', '-')}</code>"
        for job in jobs[:5]
    ]
    jobs_text = "\n".join(preview) if preview else "<i>Tidak ada job aktif.</i>"
    return (
        "<b>🕒 SCHEDULER INTERNAL</b>\n────────────────\n"
        f"⚙️ <b>Running:</b> <code>{status_payload.get('running')}</code>\n"
        f"🌍 <b>Timezone:</b> <code>{status_payload.get('timezone')}</code>\n"
        f"🧩 <b>Job Count:</b> <code>{status_payload.get('job_count')}</code>\n\n"
        f"{jobs_text}"
    )


def build_user_manage_keyboard(nip: str) -> InlineKeyboardMarkup:
    keyboard = [
        [
            InlineKeyboardButton("✏️ Nama", callback_data=f"edit_name_{nip}"),
            InlineKeyboardButton("🔑 Pass", callback_data=f"edit_pass_{nip}"),
        ],
        [
            InlineKeyboardButton("🆔 NIP", callback_data=f"edit_nip_{nip}"),
            InlineKeyboardButton("🏢 UPT", callback_data=f"edit_upt_{nip}"),
        ],
        [
            InlineKeyboardButton("📍 Atur Lokasi", callback_data=f"edit_loc_{nip}"),
            InlineKeyboardButton("⏰ Atur Jam", callback_data=f"edit_schedule_{nip}"),
            InlineKeyboardButton("🗓 Hari Kerja", callback_data=f"edit_workdays_{nip}"),
        ],
        [
            InlineKeyboardButton("📥 Presensi Masuk", callback_data=f"force_in_{nip}"),
            InlineKeyboardButton("📤 Presensi Pulang", callback_data=f"force_out_{nip}"),
        ],
        [InlineKeyboardButton("🗑️ Hapus Personel", callback_data=f"edit_del_{nip}")],
        [InlineKeyboardButton("◀️ Kembali ke Daftar", callback_data="view_users_list_0")],
    ]
    return InlineKeyboardMarkup(keyboard)


def build_manage_user_message(user: UserPayload) -> str:
    loc_indicator = "MANDIRI" if user.get("location_source") == "personal" else "SISTEM"
    sched_indicator = (
        "KHUSUS"
        if user.get("cron_in_source") == "personal" or user.get("cron_out_source") == "personal"
        else "STANDAR"
    )
    work_indicator = "KHUSUS" if user.get("workdays_source") == "personal" else "GLOBAL"
    
    coords = (
        f"{float(user['latitude']):.6f}, {float(user['longitude']):.6f}"
        if user.get("latitude") is not None and user.get("longitude") is not None
        else "BELUM DISET"
    )

    response = (
        f"<b>🛠 MANAJEMEN: {user['nama']}</b>\n"
        f"────────────────\n"
        f"🆔 <b>NIP:</b> <code>{user['nip']}</code>\n"
        f"🏢 <b>UPT:</b> <code>{user.get('nama_upt', 'DEFAULT')}</code>\n"
        f"🔑 <b>PASS:</b> <code>{user.get('password')}</code>\n"
        f"────────────────\n"
        f"📍 <b>LOKASI:</b> {loc_indicator}\n"
        f"   └ <code>{coords}</code>\n"
        f"⏰ <b>JAM KERJA:</b> {sched_indicator}\n"
        f"   └ <code>{user.get('cron_in')}</code> - <code>{user.get('cron_out')}</code>\n"
        f"🗓 <b>HARI KERJA:</b> {work_indicator}\n"
        f"   └ <code>{user.get('workdays_label', '-')}</code>"
    )
    return response


async def edit_smart(message: Message, text: str, reply_markup: Any = None) -> None:
    try:
        if message.photo or message.caption:
            await message.edit_caption(
                caption=text,
                reply_markup=reply_markup,
                parse_mode=constants.ParseMode.HTML,
            )
        else:
            await message.edit_text(
                text=text,
                reply_markup=reply_markup,
                parse_mode=constants.ParseMode.HTML,
            )
    except Exception as exc:
        if "Message is not modified" not in str(exc):
            raise
