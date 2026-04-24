import asyncio
import logging
import warnings

from telegram.warnings import PTBUserWarning

warnings.filterwarnings("ignore", category=PTBUserWarning)

from telegram import BotCommand, MenuButtonWebApp, WebAppInfo
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ExtBot,
)

# Import our modular components
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
    WAIT_BROADCAST_MSG,
    WAIT_MAN_ACTION,
    WAIT_REG_NAME,
    WAIT_REG_NIP,
    WAIT_REG_PASS,
    WAIT_REG_UPT,
    WAIT_SEARCH_QUERY,
    WAIT_SET_DAYS,
    WAIT_SET_IN,
    WAIT_SET_LOC,
    WAIT_SET_OUT,
)
from star_attendance.bot.conversations import (
    admin_add_loc,
    admin_add_name,
    admin_add_nip,
    admin_add_pass,
    admin_add_schedule,
    admin_add_start,
    admin_add_upt,
    admin_add_workdays,
    admin_confirm_del,
    admin_edit_input,
    admin_edit_start,
    cancel_convo,
    exec_broadcast,
    exec_search,
    man_execute,
    reg_name,
    reg_nip,
    reg_pass,
    reg_upt,
    set_days,
    set_in,
    set_loc,
    set_out,
    start_broadcast,
    start_location,
    start_manual,
    start_reg,
    start_schedule,
    start_search,
    start_settings,
    start_workdays,
)
from star_attendance.bot.handlers import (
    absen_manual,
    handle_callback,
    help_command,
    manage_hapus,
    manage_name,
    manage_nip,
    manage_pass,
    manage_upt,
    profil_command,
    start,
)
from star_attendance.core.config import settings
from star_attendance.db.bootstrap import verify_runtime_schema

# Logging Setup
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=getattr(logging, settings.LOG_LEVEL)
)
logger = logging.getLogger(__name__)

import time

import psutil

from star_attendance.notifier import notifier
from star_attendance.runtime import get_store

store = get_store()


async def post_init(application):
    logger.info("Starting post-init...")

    # 1. SET BOT IDENTITY & DESCRIPTION (Welcome Splash before Start)
    description = (
        "🚀 STAR-ASN ENTERPRISE: SOLUSI OTOMASI KEHADIRAN CERDAS\n\n"
        "Platform pengelolaan kehadiran personel berbasis AI yang dirancang untuk efisiensi, "
        "keamanan, dan akurasi tinggi.\n\n"
        "✅ Otomasi Absen In/Out\n"
        "✅ Bypass WAF & Keamanan Tinggi\n"
        "✅ Notifikasi Real-time\n\n"
        "Klik tombol MULAI di bawah untuk mengaktifkan asisten cerdas Anda."
    )
    short_description = "Otomasi Kehadiran Cerdas Star-ASN Edition."

    try:
        await application.bot.set_my_description(description)
        await application.bot.set_my_short_description(short_description)
        logger.info("Bot descriptions set successfully")
    except Exception as e:
        logger.warning(f"Failed to set bot descriptions: {e}")

    try:
        await application.bot.set_my_commands(
            [
                BotCommand("start", "🏠 Beranda Utama"),
                BotCommand("profil", "👤 Profil Digital"),
                BotCommand("schedule", "⏰ Jadwal Absen"),
                BotCommand("workdays", "🗓 Hari Auto Absen"),
                BotCommand("location", "📍 Lokasi GPS"),
                BotCommand("manual", "🕹 Absensi Instan"),
                BotCommand("help", "📖 Bantuan"),
            ]
        )
        logger.info("Bot commands set successfully")
    except Exception as e:
        logger.warning(f"Failed to set bot commands: {e}")

    # 3. SET MINI APP MENU BUTTON (The "Buka" button)
    if settings.MINI_APP_URL:
        try:
            await application.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="Buka", web_app=WebAppInfo(url=settings.MINI_APP_URL))
            )
            logger.info(f"Mini App menu button activated for: {settings.MINI_APP_URL}")
        except Exception as e:
            logger.warning(f"Failed to activate Mini App menu button: {e}")
    else:
        logger.info("MINI_APP_URL is empty. Skipping Mini App menu button setup.")

    # SYSTEM READINESS TELEMETRY
    logger.info("Starting system telemetry collection...")
    try:
        import platform

        import httpx

        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent
        boot_time = psutil.boot_time()

        logger.info(f"System stats - CPU: {cpu}%, RAM: {ram}%")

        # Get Public IP
        public_ip = "UNKNOWN"
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get("https://api.ipify.org")
                if resp.status_code == 200:
                    public_ip = resp.text.strip()
                    logger.info(f"Public IP obtained: {public_ip}")
        except Exception as e:
            logger.warning(f"Failed to fetch public IP: {e}")

        # Get DB Metrics with fallback
        metrics = {"db_provider": "PostgreSQL", "active_personnel": 0, "managed_personnel": 0, "success_today": 0}
        try:
            logger.info("Attempting to fetch system metrics...")
            metrics = store.get_system_metrics()
            logger.info(f"Metrics retrieved: {metrics}")
        except Exception as e:
            logger.error(f"Failed to get system metrics: {e}", exc_info=True)
            logger.info("Using default metrics fallback")

        msg = (
            "<b>🚀 STAR-ASN ENTERPRISE: SYSTEM READY</b>\n"
            "────────────────\n"
            f"💻 <b>NODE:</b> <code>{platform.node()}</code>\n"
            f"📡 <b>IP:</b> <code>{public_ip}</code>\n"
            f"⚙️ <b>CPU:</b> <code>{cpu}%</code>\n"
            f"🧠 <b>RAM:</b> <code>{ram}%</code>\n"
            f"🕒 <b>UPTIME:</b> <code>{int(time.time() - boot_time) // 3600} jam</code>\n"
            f"🗄 <b>DB:</b> <code>CONNECTED ({metrics.get('db_provider', 'Unknown')})</code>\n"
            "────────────────\n"
            f"👥 <b>PERSONNEL:</b> <code>{metrics.get('active_personnel', 0)} Active</code>\n"
            f"🤖 <b>MANAGED:</b> <code>{metrics.get('managed_personnel', 0)} Scheduled</code>\n"
            f"✅ <b>TODAY:</b> <code>{metrics.get('success_today', 0)} Successes</code>\n"
            "────────────────\n"
            "<i>Pusat komando kluster operasional aktif.</i>"
        )

        logger.info("Scheduling startup telemetry message (async)...")

        # Schedule as background task - don't block event loop
        async def send_startup_notify():
            await asyncio.sleep(1)  # Give app time to start
            try:
                notifier.send_message_sync(msg, to_admin=False, to_group=True)
                logger.info("Startup telemetry dispatched to log group successfully.")
            except Exception as e:
                logger.error(f"Failed to send startup telemetry: {e}", exc_info=True)

        asyncio.create_task(send_startup_notify())  # Non-blocking schedule
    except Exception as e:
        logger.error(f"Failed in post_init telemetry: {e}", exc_info=True)

    from star_attendance.bot.cleanup import start_global_cleanup_task
    asyncio.create_task(start_global_cleanup_task(application))
    
    logger.info("post-init completed")


class RecordedBot(ExtBot):
    """Custom Bot class that automatically records sent messages for auto-cleanup."""
    async def send_message(self, *args, **kwargs):
        msg = await super().send_message(*args, **kwargs)
        from star_attendance.bot.cleanup import record_message
        asyncio.create_task(record_message(msg))
        return msg

    async def send_photo(self, *args, **kwargs):
        msg = await super().send_photo(*args, **kwargs)
        from star_attendance.bot.cleanup import record_message
        asyncio.create_task(record_message(msg))
        return msg


def main():
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not found in environment.")
        return

    verify_runtime_schema(require_pgqueuer=True)

    app = ApplicationBuilder().token(token).bot_class(RecordedBot).post_init(post_init).build()

    # Registration Conversation
    reg_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_reg, pattern="^start_reg$"), CommandHandler("tambah", start_reg)],
        states={
            WAIT_REG_NIP: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_nip)],
            WAIT_REG_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_pass)],
            WAIT_REG_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, reg_name)],
            WAIT_REG_UPT: [
                CallbackQueryHandler(reg_upt, pattern="^reg_upt_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, reg_upt),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_convo)],
    )

    # Manual Trigger Conversation
    man_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_manual, pattern="^start_manual$"),
            CommandHandler("manual", start_manual),
        ],
        states={
            WAIT_MAN_ACTION: [CallbackQueryHandler(man_execute, pattern="^man_do_|^man_cancel$")],
        },
        fallbacks=[CommandHandler("cancel", cancel_convo)],
    )

    # Personal Settings Conversation
    set_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(start_settings, pattern="^start_settings$"),
            CallbackQueryHandler(start_schedule, pattern="^start_schedule$"),
            CallbackQueryHandler(start_workdays, pattern="^start_workdays$"),
            CallbackQueryHandler(start_location, pattern="^start_location$"),
            CommandHandler("settings", start_settings),
            CommandHandler("schedule", start_schedule),
            CommandHandler("workdays", start_workdays),
            CommandHandler("location", start_location),
        ],
        states={
            WAIT_SET_IN: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_in)],
            WAIT_SET_OUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_out)],
            WAIT_SET_DAYS: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_days)],
            WAIT_SET_LOC: [
                MessageHandler(filters.LOCATION, set_loc),
                MessageHandler(filters.TEXT & ~filters.COMMAND, set_loc),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_convo)],
    )

    # Unified Admin Override Handler
    admin_edit_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(admin_edit_start, pattern="^(edit_|global_edit_)")],
        states={
            WAIT_ADMIN_INPUT_VAL: [
                CallbackQueryHandler(admin_edit_input, pattern="^val_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_input),
            ],
            WAIT_ADMIN_CONFIRM_DEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_confirm_del)],
        },
        fallbacks=[CommandHandler("cancel", cancel_convo)],
    )

    # Admin Add User Conversation
    admin_add_handler = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(admin_add_start, pattern="^start_admin_add$"),
            CommandHandler("adduser", admin_add_start),
        ],
        states={
            WAIT_ADMIN_ADD_NIP: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_nip)],
            WAIT_ADMIN_ADD_PASS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_pass)],
            WAIT_ADMIN_ADD_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_name)],
            WAIT_ADMIN_ADD_UPT: [
                CallbackQueryHandler(admin_add_upt, pattern="^add_upt_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_upt),
            ],
            WAIT_ADMIN_ADD_SCHEDULE: [
                CallbackQueryHandler(admin_add_schedule, pattern="^preset_sch_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_schedule),
            ],
            WAIT_ADMIN_ADD_WORKDAYS: [
                CallbackQueryHandler(admin_add_workdays, pattern="^preset_wd_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_workdays),
            ],
            WAIT_ADMIN_ADD_LOC: [
                CallbackQueryHandler(admin_add_loc, pattern="^preset_loc_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, admin_add_loc),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_convo)],
    )

    # Search Conversation
    search_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_search, pattern="^start_search$")],
        states={
            WAIT_SEARCH_QUERY: [MessageHandler(filters.TEXT & ~filters.COMMAND, exec_search)],
        },
        fallbacks=[CommandHandler("cancel", cancel_convo)],
    )

    # Broadcast Conversation
    broadcast_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(start_broadcast, pattern="^start_broadcast$")],
        states={
            WAIT_BROADCAST_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, exec_broadcast)],
        },
        fallbacks=[CommandHandler("cancel", cancel_convo)],
    )

    app.add_handler(reg_handler)
    app.add_handler(man_handler)
    app.add_handler(set_handler)
    app.add_handler(admin_edit_handler)
    app.add_handler(admin_add_handler)
    app.add_handler(search_handler)
    app.add_handler(broadcast_handler)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("profil", profil_command))
    app.add_handler(CommandHandler("help", help_command))

    # Hidden / Legacy CMDs (Admin only, not in menu)
    app.add_handler(CommandHandler("absen", absen_manual))
    app.add_handler(CommandHandler("nip", manage_nip))
    app.add_handler(CommandHandler("pass", manage_pass))
    app.add_handler(CommandHandler("nama", manage_name))
    app.add_handler(CommandHandler("upt", manage_upt))
    app.add_handler(CommandHandler("hapus", manage_hapus))

    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Star ASN Multi-User Bot is listening...")
    app.run_polling()


if __name__ == "__main__":
    main()
