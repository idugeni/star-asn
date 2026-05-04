"""Bot message repository — tracking and auto-cleanup of bot messages."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from star_attendance.core.timeutils import now_storage
from star_attendance.db.manager import db_manager
from star_attendance.db.models import BotMessage


class BotMessageRepository:
    """Handles bot message tracking for auto-cleanup."""

    def record_bot_message(self, telegram_id: int, chat_id: int, message_id: int) -> None:
        with db_manager.get_session() as session:
            session.add(
                BotMessage(
                    telegram_id=telegram_id,
                    chat_id=chat_id,
                    message_id=message_id,
                )
            )

    def get_old_bot_messages(self, hours: int = 24) -> list[dict[str, Any]]:
        threshold = now_storage() - timedelta(hours=hours)
        with db_manager.get_session() as session:
            msgs = session.query(BotMessage).filter(BotMessage.created_at < threshold).limit(100).all()
            return [{"id": m.id, "chat_id": m.chat_id, "message_id": m.message_id} for m in msgs]

    def get_all_bot_messages_for_chat(self, chat_id: int) -> list[dict[str, Any]]:
        with db_manager.get_session() as session:
            msgs = session.query(BotMessage).filter(BotMessage.chat_id == chat_id).all()
            return [{"id": m.id, "chat_id": m.chat_id, "message_id": m.message_id} for m in msgs]

    def delete_bot_message_record(self, record_id: Any) -> None:
        with db_manager.get_session() as session:
            session.query(BotMessage).filter(BotMessage.id == record_id).delete()

