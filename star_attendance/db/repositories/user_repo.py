"""User repository — all user CRUD, serialization, and search operations."""

from __future__ import annotations

import threading
import uuid
from typing import Any, cast

from sqlalchemy import func
from sqlalchemy.orm import joinedload

from star_attendance.core.config import settings
from star_attendance.core.security import security_manager
from star_attendance.db.manager import db_manager
from star_attendance.db.models import UPT, AuditLog, User
from star_attendance.db.types import UserData


class UserRepository:
    """Handles all user-related database operations."""

    cache_lock = threading.RLock()
    user_cache: dict[str, tuple[float, UserData]] = {}
    users_with_passwords_cache: tuple[float, list[UserData]] | None = None
    user_summaries_cache: tuple[float, list[UserData]] | None = None

    @staticmethod
    def now_monotonic() -> float:
        import time
        return time.monotonic()

    def is_cache_valid(self, timestamp: float, ttl_seconds: int) -> bool:
        return (self.now_monotonic() - timestamp) < ttl_seconds

    def invalidate_user_cache(self, nip: str | None = None) -> None:
        with self.cache_lock:
            if nip:
                self.__class__.user_cache.pop(nip, None)
            else:
                self.__class__.user_cache.clear()
            self.__class__.users_with_passwords_cache = None
            self.__class__.user_summaries_cache = None

    def invalidate_all_caches(self) -> None:
        with self.cache_lock:
            self.__class__.user_cache.clear()
            self.__class__.users_with_passwords_cache = None
            self.__class__.user_summaries_cache = None

    @staticmethod
    def decrypt_password(raw_password: str | None) -> str | None:
        if raw_password and raw_password.startswith("gAAAA"):
            try:
                return security_manager.decrypt_password(raw_password)
            except Exception:
                return raw_password
        return raw_password

    @staticmethod
    def encrypt_password(raw_password: str | None) -> str | None:
        if raw_password is None:
            return None
        password = str(raw_password)
        if not password:
            return password
        return security_manager.encrypt_password(password)

    @staticmethod
    def resolve_upt_id(session: Any, upt_input: Any) -> str | None:
        if not upt_input:
            return None
        try:
            uuid.UUID(str(upt_input))
            return str(upt_input)
        except (ValueError, AttributeError):
            pass
        name = str(upt_input).strip()
        if not name:
            return None
        existing = session.query(UPT).filter(UPT.nama_upt.ilike(name)).first()
        if existing:
            return str(existing.id)
        new_upt = UPT(nama_upt=name)
        session.add(new_upt)
        session.flush()
        return str(new_upt.id)

    def serialize_user(self, user: Any, db_settings: dict[str, Any] | None = None) -> UserData:
        from star_attendance.database_manager import DEFAULT_SETTINGS, coerce_bool, coerce_float, coerce_optional_float, normalize_time_value, normalize_workdays

        effective_settings = db_settings or DEFAULT_SETTINGS
        upt = getattr(user, "upt", None)
        personal_latitude = getattr(user, "personal_latitude", None)
        personal_longitude = getattr(user, "personal_longitude", None)

        effective_latitude = coerce_optional_float(personal_latitude) or coerce_float(
            effective_settings.get("default_latitude", -6.2210973), -6.2210973
        )
        effective_longitude = coerce_optional_float(personal_longitude) or coerce_float(
            effective_settings.get("default_longitude", 106.8314724), 106.8314724
        )

        raw_password = getattr(user, "password", None)
        decrypted = self.decrypt_password(str(raw_password)) if raw_password else None

        is_active = coerce_bool(getattr(user, "is_active", True), True)
        auto_attendance_active = coerce_bool(getattr(user, "auto_attendance_active", False), False)

        cron_in = normalize_time_value(getattr(user, "cron_in", "07:00"), effective_settings.get("cron_in", "07:00"))
        cron_out = normalize_time_value(getattr(user, "cron_out", "18:00"), effective_settings.get("cron_out", "18:00"))
        workdays = normalize_workdays(getattr(user, "default_workdays", None), effective_settings.get("default_workdays", "mon-fri"))

        return cast(UserData, {
            "nip": str(getattr(user, "nip", "")),
            "nama": str(getattr(user, "nama", "")),
            "password": decrypted,
            "telegram_id": getattr(user, "telegram_id", None),
            "is_active": is_active,
            "auto_attendance_active": auto_attendance_active,
            "cron_in": cron_in,
            "cron_out": cron_out,
            "default_workdays": workdays,
            "personal_latitude": effective_latitude,
            "personal_longitude": effective_longitude,
            "upt_id": str(getattr(user, "upt_id", "")) if getattr(user, "upt_id", None) else None,
            "upt_nama": str(getattr(upt, "nama_upt", "")) if upt else None,
        })

    def get_user_data(self, nip: str) -> UserData | None:
        with self.cache_lock:
            cached = self.__class__.user_cache.get(nip)
            if cached and self.is_cache_valid(cached[0], settings.USER_CACHE_TTL_SECONDS):
                return cast(UserData, dict(cached[1]))

        with db_manager.get_session() as session:
            user = session.query(User).filter(User.nip == nip).first()
            if not user:
                return None
            serialized = self.serialize_user(user)

        with self.cache_lock:
            self.__class__.user_cache[nip] = (self.now_monotonic(), serialized)
        return cast(UserData, dict(serialized))

    def get_user_by_nip(self, nip: str) -> UserData | None:
        return self.get_user_data(nip)

    def get_user_summaries(self) -> list[UserData]:
        with self.cache_lock:
            cached = self.__class__.user_summaries_cache
            if cached and self.is_cache_valid(cached[0], settings.USER_CACHE_TTL_SECONDS):
                return [cast(UserData, dict(item)) for item in cached[1]]

        with db_manager.get_session() as session:
            users = session.query(User).options(joinedload(User.upt)).all()
            summaries = [self.serialize_user(u) for u in users]

        with self.cache_lock:
            self.__class__.user_summaries_cache = (self.now_monotonic(), summaries)
        return [cast(UserData, dict(item)) for item in summaries]

    def get_user_by_telegram_id(self, tid: int) -> UserData | None:
        with db_manager.get_session() as session:
            user = session.query(User).filter(User.telegram_id == int(tid)).first()
            if not user:
                return None
            return self.get_user_data(str(user.nip))

    def get_upt_examples(self, limit: int = 2) -> str:
        with db_manager.get_session() as session:
            upts = session.query(UPT).limit(limit).all()
            if upts:
                return ", ".join([str(u.nama_upt) for u in upts])
        return settings.UPT_EXAMPLE_FALLBACK

    def get_all_upts(self) -> list[dict[str, Any]]:
        with db_manager.get_session() as session:
            upts = session.query(UPT).order_by(UPT.nama_upt).all()
            return [{"id": str(u.id), "nama_upt": str(u.nama_upt)} for u in upts]

    def add_user(self, data: dict[str, Any]) -> bool:
        nip = data.get("nip")
        if not nip:
            return False

        with db_manager.get_session() as session:
            existing = session.query(User).filter(User.nip == nip).first()
            if existing:
                return False

            upt_id = self.resolve_upt_id(session, data.get("upt"))
            encrypted_pw = self.encrypt_password(data.get("password"))

            user = User(
                nip=nip,
                nama=data.get("nama", ""),
                password=encrypted_pw,
                telegram_id=data.get("telegram_id"),
                is_active=data.get("is_active", True),
                auto_attendance_active=data.get("auto_attendance_active", False),
                cron_in=data.get("cron_in", "07:00"),
                cron_out=data.get("cron_out", "18:00"),
                default_workdays=data.get("default_workdays", "mon-fri"),
                personal_latitude=data.get("personal_latitude"),
                personal_longitude=data.get("personal_longitude"),
                upt_id=upt_id,
            )
            session.add(user)

        self.invalidate_user_cache(nip)
        return True

    def update_user_settings(self, nip: str, settings_update: dict[str, Any]) -> bool:
        with db_manager.get_session() as session:
            user = session.query(User).filter(User.nip == nip).first()
            if not user:
                return False

            if "nama" in settings_update:
                user.nama = settings_update["nama"]
            if "password" in settings_update:
                user.password = self.encrypt_password(settings_update["password"])
            if "telegram_id" in settings_update:
                user.telegram_id = settings_update["telegram_id"]
            if "is_active" in settings_update:
                user.is_active = settings_update["is_active"]
            if "auto_attendance_active" in settings_update:
                user.auto_attendance_active = settings_update["auto_attendance_active"]
            if "cron_in" in settings_update:
                user.cron_in = settings_update["cron_in"]
            if "cron_out" in settings_update:
                user.cron_out = settings_update["cron_out"]
            if "default_workdays" in settings_update:
                user.default_workdays = settings_update["default_workdays"]
            if "personal_latitude" in settings_update:
                user.personal_latitude = settings_update["personal_latitude"]
            if "personal_longitude" in settings_update:
                user.personal_longitude = settings_update["personal_longitude"]
            if "upt" in settings_update:
                user.upt_id = self.resolve_upt_id(session, settings_update["upt"])

        self.invalidate_user_cache(nip)
        return True

    def rename_user_nip(self, old_nip: str, new_nip: str) -> bool:
        old_nip = str(old_nip).strip()
        new_nip = str(new_nip).strip()
        if not old_nip or not new_nip:
            return False

        with db_manager.get_session() as session:
            user = session.query(User).filter(User.nip == old_nip).first()
            if not user:
                return False

            existing = session.query(User).filter(User.nip == new_nip).first()
            if existing:
                return False

            user.nip = new_nip
            session.query(AuditLog).filter(AuditLog.nip == old_nip).update({"nip": new_nip})

        self.invalidate_user_cache()
        return True

    def get_users_with_passwords(self) -> list[UserData]:
        with self.cache_lock:
            cached = self.__class__.users_with_passwords_cache
            if cached and self.is_cache_valid(cached[0], settings.USER_CACHE_TTL_SECONDS):
                return [cast(UserData, dict(item)) for item in cached[1]]

        with db_manager.get_session() as session:
            users = session.query(User).filter(User.is_active == True, User.password != None).all()  # noqa: E711
            results = [self.serialize_user(u) for u in users]

        with self.cache_lock:
            self.__class__.users_with_passwords_cache = (self.now_monotonic(), results)
        return [cast(UserData, dict(item)) for item in results]

    def delete_user(self, nip: str) -> bool:
        deleted = False
        with db_manager.get_session() as session:
            session.query(AuditLog).filter(AuditLog.nip == nip).delete()
            user = session.query(User).filter(User.nip == nip).first()
            if user:
                session.delete(user)
                deleted = True

        self.invalidate_user_cache(nip)
        return deleted

    def search_users(self, query: str, db_settings: dict[str, Any] | None = None) -> list[UserData]:
        with db_manager.get_session() as session:
            users = (
                session.query(User)
                .options(joinedload(User.upt))
                .filter((User.nama.ilike(f"%{query}%")) | (User.nip.ilike(f"%{query}%")))
                .all()
            )
            return [self.serialize_user(user, db_settings=db_settings) for user in users]

    def get_all_telegram_ids(self) -> list[int]:
        with db_manager.get_session() as session:
            users = session.query(User).filter(User.telegram_id != None).all()  # noqa: E711
            return sorted({int(user.telegram_id) for user in users if user.telegram_id is not None})
