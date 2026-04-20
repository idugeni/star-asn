import os
from typing import Optional, Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update

from star_attendance.core.config import settings
from star_attendance.runtime import get_store

# Global Admin ID from settings
ADMIN_ID: Optional[int] = settings.TELEGRAM_ADMIN_ID

store = get_store()


def is_authorized(update: Update) -> bool:
    if not update.effective_user:
        return False

    tid = update.effective_user.id
    if ADMIN_ID is not None and tid == ADMIN_ID:
        return True

    user = store.get_user_by_telegram_id(tid)
    return user is not None


def is_admin(telegram_id: int) -> bool:
    if ADMIN_ID is not None and telegram_id == ADMIN_ID:
        return True
    user = store.get_user_by_telegram_id(telegram_id)
    return bool(user.get("is_admin", False)) if user else False


def get_progress_bar(current: int, total: int, length: int = 10) -> str:
    if total <= 0:
        return "░░░░░░░░░░"
    filled = int(length * current // total)
    bar = "█" * filled + "░" * (length - filled)
    percent = (current / total) * 100
    return f"<code>{bar}</code> {percent:.0f}%"


def get_back_button(target: str = "main_menu") -> InlineKeyboardButton:
    return InlineKeyboardButton("🔙 KEMBALI KE BERANDA", callback_data=target)


async def get_main_menu(telegram_id: int) -> InlineKeyboardMarkup:
    is_adm = is_admin(telegram_id)
    keyboard = [
        [
            InlineKeyboardButton("👤 PROFIL SAYA", callback_data="view_profile"),
            InlineKeyboardButton("🔄 REFRESH", callback_data="main_menu"),
        ],
        [
            InlineKeyboardButton("📜 RIWAYAT", callback_data="view_history"),
            InlineKeyboardButton("⚙️ PENGATURAN", callback_data="start_settings_menu"),
        ],
        [InlineKeyboardButton("🕹️ ABSEN MANUAL", callback_data="start_manual")],
        [
            InlineKeyboardButton("📖 PANDUAN", callback_data="view_help"),
            InlineKeyboardButton("💬 SUPPORT", callback_data="view_support"),
        ],
    ]

    if is_adm:
        keyboard.extend(
            [
                [InlineKeyboardButton("─── 🛡️ ADMIN PANEL ───", callback_data="noop")],
                [
                    InlineKeyboardButton("🚀 MASSAL IN", callback_data="trigger_in"),
                    InlineKeyboardButton("🏠 MASSAL OUT", callback_data="trigger_out"),
                ],
                [
                    InlineKeyboardButton("📊 TELEMETRI", callback_data="view_stats"),
                    InlineKeyboardButton("📝 LOG SISTEM", callback_data="view_global_logs"),
                ],
                [
                    InlineKeyboardButton("👥 MANAJEMEN", callback_data="view_users_list_0"),
                    InlineKeyboardButton("🔍 CARI USER", callback_data="start_search"),
                ],
                [
                    InlineKeyboardButton("🌐 GLOBAL SET", callback_data="view_global_settings"),
                    InlineKeyboardButton("🕒 SCHEDULER", callback_data="view_scheduler"),
                ],
                [
                    InlineKeyboardButton("🧨 DEAD LETTER", callback_data="view_dead_letters"),
                    InlineKeyboardButton("🖥️ DIAGNOSTIK", callback_data="view_system"),
                ],
                [
                    InlineKeyboardButton("📢 BROADCAST", callback_data="start_broadcast"),
                    InlineKeyboardButton("🛑 EMERGENCY STOP", callback_data="trigger_stop"),
                ],
            ]
        )
    else:
        user = store.get_user_by_telegram_id(telegram_id)
        if not user:
            keyboard = [[InlineKeyboardButton("➕ DAFTAR PERSONEL BARU", callback_data="start_reg")]]

    return InlineKeyboardMarkup(keyboard)


def get_settings_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("⏰ ATUR JADWAL", callback_data="start_schedule")],
        [InlineKeyboardButton("🗓 ATUR HARI KERJA", callback_data="start_workdays")],
        [InlineKeyboardButton("📍 ATUR LOKASI", callback_data="start_location")],
        [get_back_button()],
    ]
    return InlineKeyboardMarkup(keyboard)


async def get_users_keyboard(page: int = 0, limit: int = 6, search_query: Optional[str] = None) -> InlineKeyboardMarkup:
    if search_query:
        users = store.search_users(search_query)
    else:
        users = store.get_user_summaries()

    total = len(users)
    start_idx = page * limit
    end_idx = start_idx + limit
    page_users = users[start_idx:end_idx]

    keyboard = [
        [InlineKeyboardButton("➕ TAMBAH PERSONEL BARU", callback_data="start_admin_add")],
        *[
            [InlineKeyboardButton(f"👤 {u['nama'][:20]} ({u['nip']})", callback_data=f"manage_user_{u['nip']}")]
            for u in page_users
        ]
    ]

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ Prev", callback_data=f"view_users_list_{page-1}"))
    if end_idx < total:
        nav_row.append(InlineKeyboardButton("Next ▶️", callback_data=f"view_users_list_{page+1}"))

    if nav_row:
        keyboard.append(nav_row)
    keyboard.append([get_back_button()])

    return InlineKeyboardMarkup(keyboard)


def get_upt_keyboard(upt_list: list[dict[str, Any]], callback_prefix: str = "upt_") -> InlineKeyboardMarkup:
    """Generates an inline keyboard with 2 columns of UPT buttons."""
    keyboard = []
    for i in range(0, len(upt_list), 2):
        row = [
            InlineKeyboardButton(upt_list[i]["nama_upt"], callback_data=f"{callback_prefix}{upt_list[i]['id'] or upt_list[i]['nama_upt']}")
        ]
        if i + 1 < len(upt_list):
            row.append(
                InlineKeyboardButton(upt_list[i+1]["nama_upt"], callback_data=f"{callback_prefix}{upt_list[i+1]['id'] or upt_list[i+1]['nama_upt']}")
            )
        keyboard.append(row)
    return InlineKeyboardMarkup(keyboard)
