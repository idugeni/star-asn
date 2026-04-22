from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from telegram import Message, Update
from telegram.ext import ContextTypes

from star_attendance.bot.handler_callbacks import CallbackServices
from star_attendance.bot.handler_callbacks import handle_callback as handle_callback_impl
from star_attendance.bot.handler_commands import (
    absen_manual as absen_manual_impl,
)
from star_attendance.bot.handler_commands import (
    help_command as help_command_impl,
)
from star_attendance.bot.handler_commands import (
    manage_hapus as manage_hapus_impl,
)
from star_attendance.bot.handler_commands import (
    manage_name as manage_name_impl,
)
from star_attendance.bot.handler_commands import (
    manage_nip as manage_nip_impl,
)
from star_attendance.bot.handler_commands import (
    manage_pass as manage_pass_impl,
)
from star_attendance.bot.handler_commands import (
    manage_upt as manage_upt_impl,
)
from star_attendance.bot.handler_commands import (
    profil_command as profil_command_impl,
)
from star_attendance.bot.handler_commands import (
    start as start_impl,
)
from star_attendance.bot.handler_views import (
    build_dashboard_message,
    build_global_settings_message,
    build_scheduler_message,
    build_user_manage_keyboard,
    get_global_settings_keyboard,
    get_scheduler_keyboard,
)
from star_attendance.bot.handler_views import (
    edit_smart as edit_smart_impl,
)
from star_attendance.bot.ui import get_main_menu, get_users_keyboard, is_admin
from star_attendance.core.options import RuntimeOptions
from star_attendance.bot.cleanup import clean_incoming, auto_delete_message
from star_attendance.runtime import get_internal_api_client, get_store

store = get_store()
internal_api = get_internal_api_client()


def _build_runtime_options(action: str) -> RuntimeOptions:
    return RuntimeOptions.from_store(action, store=store)


def _build_dashboard_message(user: Mapping[str, Any] | None) -> str:
    return build_dashboard_message(user, store=store)


def _get_global_settings_keyboard():
    return get_global_settings_keyboard()


def _build_global_settings_message() -> str:
    return build_global_settings_message(store=store)


def _get_scheduler_keyboard():
    return get_scheduler_keyboard()


def _build_scheduler_message(status_payload: Mapping[str, Any]) -> str:
    return build_scheduler_message(status_payload)


async def edit_smart(message: Message, text: str, reply_markup: Any = None) -> None:
    await edit_smart_impl(message, text, reply_markup)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await handle_callback_impl(
        update,
        context,
        services=CallbackServices(
            store=store,
            internal_api=internal_api,
            edit_message=edit_smart,
            get_main_menu=get_main_menu,
            get_users_keyboard=get_users_keyboard,
            is_admin=is_admin,
            build_runtime_options=_build_runtime_options,
        ),
    )


def get_user_manage_keyboard(nip: str):
    return build_user_manage_keyboard(nip)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await clean_incoming(update)
    await start_impl(
        update,
        context,
        store=store,
        is_admin_fn=is_admin,
        build_dashboard_message=_build_dashboard_message,
        get_main_menu_fn=get_main_menu,
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await clean_incoming(update)
    await help_command_impl(update, context, is_admin_fn=is_admin)

async def absen_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await clean_incoming(update)
    await absen_manual_impl(update, context, is_admin_fn=is_admin, build_runtime_options=_build_runtime_options)

async def manage_nip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await clean_incoming(update)
    await manage_nip_impl(update, context, store=store, is_admin_fn=is_admin)

async def manage_pass(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await clean_incoming(update)
    await manage_pass_impl(update, context, store=store, is_admin_fn=is_admin)

async def manage_hapus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await clean_incoming(update)
    await manage_hapus_impl(update, context, store=store, is_admin_fn=is_admin)

async def profil_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await clean_incoming(update)
    await profil_command_impl(update, context, store=store)

async def manage_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await clean_incoming(update)
    await manage_name_impl(update, context, store=store, is_admin_fn=is_admin)

async def manage_upt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await clean_incoming(update)
    await manage_upt_impl(update, context, store=store, is_admin_fn=is_admin)


__all__ = [
    "_build_dashboard_message",
    "_build_global_settings_message",
    "_build_runtime_options",
    "_build_scheduler_message",
    "_get_global_settings_keyboard",
    "_get_scheduler_keyboard",
    "absen_manual",
    "edit_smart",
    "get_user_manage_keyboard",
    "handle_callback",
    "help_command",
    "manage_hapus",
    "manage_name",
    "manage_nip",
    "manage_pass",
    "manage_upt",
    "profil_command",
    "start",
]
