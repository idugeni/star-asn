"""Session repository — user session management (cookies, auth state)."""

from __future__ import annotations

from typing import Any

from star_attendance.db.manager import db_manager
from star_attendance.db.models import UserSession


class SessionRepository:
    """Handles user session persistence and retrieval."""

    def save_user_session(self, nip: str, session_data: dict[str, Any]) -> None:
        if not session_data or not session_data.get("cookies"):
            print(f"Invalid or empty session data for {nip}. Deleting existing session if any.")
            self.delete_user_session(nip)
            return

        with db_manager.get_session() as session:
            existing = session.query(UserSession).filter(UserSession.nip == nip).first()
            if existing:
                existing.data = session_data
            else:
                session.add(
                    UserSession(
                        nip=nip,
                        data=session_data,
                    )
                )
            print(f"Session persisted to Supabase for {nip}.")

    def get_user_session(self, nip: str) -> dict[str, Any] | None:
        with db_manager.get_session() as session:
            sess = session.query(UserSession).filter(UserSession.nip == nip).first()
            if sess and sess.data is not None:
                return dict(sess.data)
            return None

    def delete_user_session(self, nip: str) -> None:
        with db_manager.get_session() as session:
            session.query(UserSession).filter(UserSession.nip == nip).delete()
