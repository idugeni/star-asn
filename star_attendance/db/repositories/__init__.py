"""Repository package — provides focused data access layers.

The SupabaseManager facade delegates to these repositories internally.
Import individual repositories for fine-grained data access, or use
SupabaseManager for backward-compatible full access.
"""

from star_attendance.db.repositories.allowance_repo import AllowanceRepository
from star_attendance.db.repositories.audit_repo import AuditRepository
from star_attendance.db.repositories.bot_message_repo import BotMessageRepository
from star_attendance.db.repositories.session_repo import SessionRepository
from star_attendance.db.repositories.settings_repo import SettingsRepository
from star_attendance.db.repositories.user_repo import UserRepository

__all__ = [
    "AllowanceRepository",
    "AuditRepository",
    "BotMessageRepository",
    "SessionRepository",
    "SettingsRepository",
    "UserRepository",
]
