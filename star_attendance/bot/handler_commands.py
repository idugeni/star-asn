from __future__ import annotations

import os
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from telegram import Update, constants
from telegram.ext import ContextTypes

from star_attendance.core.config import settings
from star_attendance.core.processor import process_single_user

MenuBuilder = Callable[[int], Awaitable[Any]]
AdminChecker = Callable[[int], bool]
OptionsBuilder = Callable[[str], Any]
DashboardBuilder = Callable[[Mapping[str, Any] | None], str]


async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    store: Any,
    is_admin_fn: AdminChecker,
    build_dashboard_message: DashboardBuilder,
    get_main_menu_fn: MenuBuilder,
) -> None:
    if not update.message or not update.effective_user:
        return

    tid = update.effective_user.id
    user = store.get_user_by_telegram_id(tid)
    is_adm = is_admin_fn(tid)

    if not user and not is_adm:
        welcome_text = (
            f"<b>✨ SELAMAT DATANG DI {settings.BOT_NAME} ENTERPRISE</b>\n"
            "────────────────\n\n"
            "      <b>SISTEM OTOMASI KEHADIRAN CERDAS</b>\n\n"
            "────────────────\n"
            "Silakan daftarkan NIP Anda melalui tombol di bawah untuk memulai revolusi efisiensi kerja Anda."
        )
        await update.message.reply_text(
            welcome_text,
            parse_mode=constants.ParseMode.HTML,
            reply_markup=await get_main_menu_fn(tid),
        )
        return

    caption = build_dashboard_message(user)
    reply_markup = await get_main_menu_fn(tid)
    try:
        banner_path = settings.BOT_BANNER_PATH
        if banner_path and os.path.exists(banner_path):
            with open(banner_path, "rb") as photo:
                await update.message.reply_photo(
                    photo=photo,
                    caption=caption,
                    reply_markup=reply_markup,
                    parse_mode=constants.ParseMode.HTML,
                )
        else:
            await update.message.reply_text(
                caption,
                reply_markup=reply_markup,
                parse_mode=constants.ParseMode.HTML,
            )
    except Exception:
        await update.message.reply_text(
            caption,
            reply_markup=reply_markup,
            parse_mode=constants.ParseMode.HTML,
        )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    is_admin_fn: AdminChecker,
) -> None:
    if not update.message or not update.effective_user:
        return

    tid = update.effective_user.id
    if is_admin_fn(tid):
        message = (
            "<b>📖 DOKUMENTASI ADMINISTRATOR</b>\n────────────────\n"
            "<b>PERINTAH MANAJEMEN:</b>\n"
            "• /start - Dashboard Utama\n"
            "• /absen - Override Absensi Instan\n"
            "• /tambah - Registrasi Manual\n"
            "• /adduser - Tambah Personel Baru (Admin)\n\n"
            "<b>MODUL TELEGRAM CONTROL PLANE:</b>\n"
            "🚀 <b>Aktivasi Masal:</b> Eksekusi absensi seluruh kluster.\n"
            "🌐 <b>Global Settings:</b> Ubah rule global dan default runtime.\n"
            "🕒 <b>Scheduler:</b> Pantau dan restart scheduler internal.\n"
            "🧨 <b>Dead Letter:</b> Audit job gagal dari worker."
        )
    else:
        message = (
            "<b>📖 PANDUAN PENGGUNA</b>\n────────────────\n"
            "<b>PERINTAH UTAMA:</b>\n"
            "• /start - Dashboard Personal\n"
            "• /schedule - Atur jam absen otomatis\n"
            "• /workdays - Atur hari auto absen\n"
            "• /location - Atur lokasi GPS\n\n"
            "<b>CATATAN KEAMANAN:</b>\n"
            "<i>Data kredensial Anda dienkripsi dalam database untuk menjamin privasi dan keamanan akun.</i>"
        )
    await update.message.reply_text(message, parse_mode=constants.ParseMode.HTML)


async def absen_manual(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    is_admin_fn: AdminChecker,
    build_runtime_options: OptionsBuilder,
) -> None:
    if not update.message or not update.effective_user or not is_admin_fn(update.effective_user.id):
        return

    if update.effective_chat:
        try:
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=update.message.message_id,
            )
        except Exception:
            pass

    args = context.args or []
    if len(args) < 3:
        await update.message.reply_text(
            "❌ <b>Sintaks Perintah Salah</b>\nContoh: <code>/absen &lt;NIP&gt; &lt;PASSWORD&gt; &lt;IN/OUT&gt;</code>",
            parse_mode=constants.ParseMode.HTML,
        )
        return

    nip, password, action = args[0], args[1], args[2].lower()
    if action not in {"in", "out"}:
        await update.message.reply_text("❌ Aksi harus <b>in</b> atau <b>out</b>.", parse_mode=constants.ParseMode.HTML)
        return

    status_message = await update.message.reply_text(
        f"⏳ <b>MENGEKSEKUSI GUEST {action.upper()}...</b>\nTarget: <code>{nip}</code>",
        parse_mode=constants.ParseMode.HTML,
    )
    msg_id_container = {"id": status_message.message_id}

    result, _ = await process_single_user(
        {"nip": nip, "password": password},
        build_runtime_options(action),
        1,
        1,
        is_mass=False,
        user_message_id=msg_id_container,
    )

    if update.effective_chat:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=status_message.message_id,
            text=(
                f"{'✅' if result else '❌'} <b>EKSEKUSI {action.upper()} {'BERHASIL' if result else 'GAGAL'}</b>\n"
                f"Target: <code>{nip}</code>"
            ),
            parse_mode=constants.ParseMode.HTML,
        )


async def manage_nip(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    store: Any,
    is_admin_fn: AdminChecker,
) -> None:
    if not update.message or not update.effective_user or not is_admin_fn(update.effective_user.id):
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "💡 <b>Update NIP</b>\n<code>/nip [LAMA] [BARU]</code>", parse_mode=constants.ParseMode.HTML
        )
        return

    if store.rename_user_nip(args[0], args[1]):
        await update.message.reply_text(
            f"✅ NIP diperbarui: <code>{args[0]}</code> -> <code>{args[1]}</code>",
            parse_mode=constants.ParseMode.HTML,
        )
    else:
        await update.message.reply_text("❌ User tidak ditemukan.")


async def manage_pass(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    store: Any,
    is_admin_fn: AdminChecker,
) -> None:
    if not update.message or not update.effective_user or not is_admin_fn(update.effective_user.id):
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "💡 <b>Update Password</b>\n<code>/pass [NIP] [PWD]</code>", parse_mode=constants.ParseMode.HTML
        )
        return

    if store.update_user_settings(args[0], {"password": args[1]}):
        await update.message.reply_text(
            f"✅ Password <code>{args[0]}</code> diperbarui.", parse_mode=constants.ParseMode.HTML
        )
    else:
        await update.message.reply_text("❌ Gagal update password.")


async def manage_hapus(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    store: Any,
    is_admin_fn: AdminChecker,
) -> None:
    if not update.message or not update.effective_user or not is_admin_fn(update.effective_user.id):
        return

    args = context.args or []
    if not args:
        await update.message.reply_text(
            "💡 <b>Hapus User</b>\n<code>/hapus [NIP]</code>", parse_mode=constants.ParseMode.HTML
        )
        return

    if store.delete_user(args[0]):
        await update.message.reply_text(f"✅ User <code>{args[0]}</code> dihapus.", parse_mode=constants.ParseMode.HTML)
    else:
        await update.message.reply_text("❌ Gagal menghapus user.")


async def profil_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    store: Any,
) -> None:
    if not update.effective_user or not update.message:
        return

    tid = update.effective_user.id
    user = store.get_user_by_telegram_id(tid)
    if not user:
        await update.message.reply_text("Anda belum terdaftar. Gunakan /start untuk mendaftar.")
        return

    coords = (
        f"{user['latitude']:.6f}, {user['longitude']:.6f}"
        if user.get("latitude") is not None and user.get("longitude") is not None
        else "DEFAULT UPT"
    )
    auto_status = "ACTIVE" if user.get("auto_attendance_active") else "INACTIVE"
    in_source = str(user.get("cron_in_source", "-")).upper()
    out_source = str(user.get("cron_out_source", "-")).upper()
    in_label = ""
    out_label = ""

    message = (
        "<b>👤 PROFIL PERSONEL</b>\n────────────────\n"
        f"📛 <b>NAMA:</b> <code>{user['nama']}</code>\n"
        f"🆔 <b>NIP:</b> <code>{user['nip']}</code>\n"
        f"📲 <b>TELEGRAM ID:</b> <code>{user.get('telegram_id') or '-'}</code>\n"
        f"🏢 <b>UNIT:</b> <code>{user['nama_upt']}</code>\n"
        "────────────────\n"
        f"⏰ <b>JADWAL AUTO-IN:</b> <code>{user['cron_in']}</code>{in_label}\n"
        f"⏰ <b>JADWAL AUTO-OUT:</b> <code>{user['cron_out']}</code>{out_label}\n"
        f"🗓 <b>HARI KERJA:</b> <code>{user.get('workdays_label', '-')}</code>\n"
        f"🤖 <b>AUTO ABSEN:</b> <code>{auto_status}</code>\n"
        f"ℹ️ <b>INFO:</b> <code>{user.get('auto_attendance_reason', '-')}</code>\n"
        f"📍 <b>LOKASI:</b> <code>{user.get('location_label', user['nama_upt'])}</code>\n"
        f"🧭 <b>KOORDINAT:</b> <code>{coords}</code>\n"
        f"🗂 <b>SUMBER:</b> <code>{str(user.get('location_source', '-')).upper()}</code>\n"
        "────────────────\n"
        "💎 <b>STATUS:</b> <b>ENTERPRISE ACTIVE</b>"
    )
    await update.message.reply_text(message, parse_mode=constants.ParseMode.HTML)


async def manage_name(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    store: Any,
    is_admin_fn: AdminChecker,
) -> None:
    if not update.message or not update.effective_user or not is_admin_fn(update.effective_user.id):
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "💡 <b>Update Nama</b>\n<code>/nama [NIP] [NAMA BARU]</code>", parse_mode=constants.ParseMode.HTML
        )
        return

    new_name = " ".join(args[1:])
    if store.update_user_settings(args[0], {"nama": new_name}):
        await update.message.reply_text(
            f"✅ Nama <code>{args[0]}</code> diperbarui menjadi: <b>{new_name}</b>",
            parse_mode=constants.ParseMode.HTML,
        )
    else:
        await update.message.reply_text("❌ Gagal update nama.")


async def manage_upt(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    store: Any,
    is_admin_fn: AdminChecker,
) -> None:
    if not update.message or not update.effective_user or not is_admin_fn(update.effective_user.id):
        return

    args = context.args or []
    if len(args) < 2:
        await update.message.reply_text(
            "💡 <b>Update UPT</b>\n<code>/upt [NIP] [ID/NAMA UPT]</code>", parse_mode=constants.ParseMode.HTML
        )
        return

    new_upt = " ".join(args[1:])
    if store.update_user_settings(args[0], {"upt_id": new_upt}):
        await update.message.reply_text(
            f"✅ UPT <code>{args[0]}</code> diperbarui menjadi: <b>{new_upt}</b>",
            parse_mode=constants.ParseMode.HTML,
        )
    else:
        await update.message.reply_text("❌ Gagal update UPT.")
