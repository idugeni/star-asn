import json
import threading
import time
import uuid
from datetime import date, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, text
from sqlalchemy.orm import joinedload

from star_attendance.core.config import settings
from star_attendance.core.security import security_manager
from star_attendance.core.timeutils import (
    format_formal_timestamp,
    isoformat_local,
    local_date,
    local_day_bounds,
    now_storage,
    now_utc,
    to_local,
)
from star_attendance.db.enums import AuditAction, AuditStatus
from star_attendance.db.manager import db_manager
from star_attendance.db.models import UPT, AuditLog, GlobalSetting, User, UserPerformanceAllowance, UserSession, PersonalAllowance, BotMessage
from star_attendance.db.types import AuditLogData, UserData

DEFAULT_LOCATION_LATITUDE = -6.2210973
DEFAULT_LOCATION_LONGITUDE = 106.8314724
DEFAULT_WORKDAYS = "mon-fri"

WORKDAY_PRESETS: dict[str, dict[str, str]] = {
    "mon-fri": {"label": "Senin-Jumat", "cron": "mon-fri"},
    "mon-sat": {"label": "Senin-Sabtu", "cron": "mon-sat"},
    "everyday": {"label": "Setiap Hari", "cron": "mon-sun"},
}

WORKDAY_ALIASES = {
    "mon-fri": "mon-fri",
    "monday-friday": "mon-fri",
    "senin-jumat": "mon-fri",
    "seninjumat": "mon-fri",
    "weekdays": "mon-fri",
    "mon-sat": "mon-sat",
    "monday-saturday": "mon-sat",
    "senin-sabtu": "mon-sat",
    "seninsabtu": "mon-sat",
    "everyday": "everyday",
    "daily": "everyday",
    "all-days": "everyday",
    "setiap-hari": "everyday",
    "setiaphari": "everyday",
    "mon-sun": "everyday",
    "*": "everyday",
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "default_location": "Kementerian Imigrasi dan Pemasyarakatan Republik Indonesia",
    "default_latitude": DEFAULT_LOCATION_LATITUDE,
    "default_longitude": DEFAULT_LOCATION_LONGITUDE,
    "timezone": "Asia/Jakarta",
    "ocr_engine": settings.OCR_ENGINE,
    "automation_enabled": True,
    "cron_in": "07:00",
    "cron_out": "18:00",
    "default_workdays": DEFAULT_WORKDAYS,
    "time_storage_version": "timestamptz_v2",
    "mass_active": "0",
    "mass_action": "",
    "mass_pos": "0",
    "mass_total": "0",
    "mass_last_nip": "",
    "mass_start_time": "0",
    "mass_in_success": 0,
    "mass_in_failed": 0,
    "mass_out_success": 0,
    "mass_out_failed": 0,
    "mass_stop": "0",
}


def coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def coerce_float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def coerce_optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def coerce_optional_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return datetime.fromisoformat(str(value)).date()
    except (TypeError, ValueError):
        return None


def infer_allowance_year(period_code: str, data: list[dict[str, Any]]) -> int:
    if data:
        date_str = str(data[0].get("date") or "").strip()
        try:
            allowance_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            if "_" in period_code:
                start_code, end_code = period_code.split("_", maxsplit=1)
                start_month = int(start_code[2:])
                end_month = int(end_code[2:])
                if start_month > end_month and allowance_date.month == end_month:
                    return allowance_date.year - 1
            return allowance_date.year
        except (TypeError, ValueError):
            pass
    return local_date().year


def stringify_setting(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


def coerce_telegram_id(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    if isinstance(value, dict) and "id" in value:
        return coerce_telegram_id(value["id"])
    return None


def normalize_time_value(value: Any, fallback: str) -> str:
    raw = str(value).strip() if value not in (None, "") else ""
    if not raw or raw.lower() in {"none", "null", "default", "-"}:
        return fallback
    return raw if is_valid_time_text(raw) else fallback


def normalize_workdays(value: Any, default: str = DEFAULT_WORKDAYS) -> str:
    if hasattr(value, "value"):
        value = value.value
    if value in (None, ""):
        return default
    normalized = str(value).strip().lower().replace("_", "-").replace(" ", "-")
    return WORKDAY_ALIASES.get(normalized, default)


def get_workday_label(value: Any) -> str:
    key = normalize_workdays(value)
    return WORKDAY_PRESETS.get(key, WORKDAY_PRESETS[DEFAULT_WORKDAYS])["label"]


def get_workday_cron(value: Any) -> str:
    key = normalize_workdays(value)
    return WORKDAY_PRESETS.get(key, WORKDAY_PRESETS[DEFAULT_WORKDAYS])["cron"]


def normalize_audit_action(value: str | AuditAction) -> str:
    raw_value = value.value if isinstance(value, AuditAction) else str(value).strip()
    try:
        return AuditAction(raw_value).value
    except ValueError as exc:
        raise ValueError(f"Unsupported audit action: {value}") from exc


def normalize_audit_status(value: str | AuditStatus) -> str:
    raw_value = value.value if isinstance(value, AuditStatus) else str(value).strip()
    try:
        return AuditStatus(raw_value).value
    except ValueError as exc:
        raise ValueError(f"Unsupported audit status: {value}") from exc


def is_valid_time_text(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 2:
        return False
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError:
        return False
    return 0 <= hour <= 23 and 0 <= minute <= 59


def resolve_auto_attendance_status(
    *,
    automation_enabled: bool,
    is_active: bool,
    has_password: bool,
    cron_in: str,
    cron_out: str,
    latitude: float | None,
    longitude: float | None,
) -> tuple[bool, str]:
    if not automation_enabled:
        return False, "Otomasi global dimatikan."
    if not is_active:
        return False, "User dinonaktifkan."
    if not has_password:
        return False, "Password portal belum tersedia."
    if not is_valid_time_text(cron_in) or not is_valid_time_text(cron_out):
        return False, "Jadwal otomatis belum valid."
    if latitude is None or longitude is None:
        return False, "Koordinat belum lengkap."
    return True, "Auto absen siap dijalankan."


class SupabaseManager:
    """
    Unified Database Manager powered exclusively by Supabase (PostgreSQL).
    Provides relational access, audit feeds, cache-backed reads, and enterprise
    controls such as idempotency locks and dead-letter recording.
    """

    cache_lock = threading.RLock()
    settings_cache: tuple[float, dict[str, Any]] | None = None
    user_cache: dict[str, tuple[float, UserData]] = {}
    users_with_passwords_cache: tuple[float, list[UserData]] | None = None
    user_summaries_cache: tuple[float, list[UserData]] | None = None

    def __init__(self) -> None:
        pass

    @staticmethod
    def now_monotonic() -> float:
        return time.monotonic()

    def is_cache_valid(self, timestamp: float, ttl_seconds: int) -> bool:
        return (self.now_monotonic() - timestamp) < ttl_seconds

    def invalidate_settings_cache(self) -> None:
        with self.cache_lock:
            self.__class__.settings_cache = None

    def invalidate_all_caches(self) -> None:
        """Forcibly clear all internal caches for real-time synchronization."""
        with self.cache_lock:
            self.__class__.settings_cache = None
            self.__class__.user_cache.clear()
            self.__class__.users_with_passwords_cache = None
            self.__class__.user_summaries_cache = None

    def invalidate_user_cache(self, nip: str | None = None) -> None:
        with self.cache_lock:
            if nip:
                self.__class__.user_cache.pop(nip, None)
            else:
                self.__class__.user_cache.clear()
            self.__class__.users_with_passwords_cache = None
            self.__class__.user_summaries_cache = None

    def decrypt_password(self, raw_password: str | None) -> str | None:
        if raw_password and raw_password.startswith("gAAAA"):
            try:
                return security_manager.decrypt_password(raw_password)
            except Exception:
                return raw_password
        return raw_password

    def encrypt_password(self, raw_password: str | None) -> str | None:
        if raw_password is None:
            return None
        password = str(raw_password)
        if not password:
            return ""
        if password.startswith("gAAAA"):
            return password
        return security_manager.encrypt_password(password)

    def resolve_upt_id(self, session: Any, upt_input: Any) -> str | None:
        if not upt_input:
            return None
        try:
            return str(uuid.UUID(str(upt_input)))
        except ValueError:
            name = str(upt_input).strip()
            upt_rec = session.query(UPT).filter(UPT.nama_upt == name).first()
            if upt_rec:
                return str(upt_rec.id)
            
            # Automated Geocoding for New UPTs
            from star_attendance.core.geo import resolve_upt_coordinates_sync
            geo = resolve_upt_coordinates_sync(name)
            
            new_upt = UPT(
                nama_upt=name,
                latitude=geo["latitude"] if geo else None,
                longitude=geo["longitude"] if geo else None,
            )
            session.add(new_upt)
            session.flush()
            return str(new_upt.id)

    def merge_settings(self, raw_values: dict[str, Any]) -> dict[str, Any]:
        merged = dict(DEFAULT_SETTINGS)
        merged.update(raw_values)
        merged["default_location"] = str(merged.get("default_location") or DEFAULT_SETTINGS["default_location"])
        merged["default_latitude"] = coerce_float(
            merged.get("default_latitude"),
            DEFAULT_SETTINGS["default_latitude"],
        )
        merged["default_longitude"] = coerce_float(
            merged.get("default_longitude"),
            DEFAULT_SETTINGS["default_longitude"],
        )
        merged["timezone"] = str(merged.get("timezone") or DEFAULT_SETTINGS["timezone"])
        merged["ocr_engine"] = str(merged.get("ocr_engine") or DEFAULT_SETTINGS["ocr_engine"])
        merged["cron_in"] = str(merged.get("cron_in") or DEFAULT_SETTINGS["cron_in"])
        merged["cron_out"] = str(merged.get("cron_out") or DEFAULT_SETTINGS["cron_out"])
        merged["default_workdays"] = normalize_workdays(
            merged.get("default_workdays"),
            DEFAULT_WORKDAYS,
        )
        merged["automation_enabled"] = coerce_bool(
            merged.get("automation_enabled"),
            bool(DEFAULT_SETTINGS["automation_enabled"]),
        )
        return merged

    def serialize_user(self, user: Any, db_settings: dict[str, Any] | None = None) -> UserData:
        effective_settings = db_settings or self.get_settings()
        upt = getattr(user, "upt", None)
        personal_latitude = getattr(user, "personal_latitude", None)
        personal_longitude = getattr(user, "personal_longitude", None)
        raw_password = cast(str | None, getattr(user, "password", None))
        decrypted_password = self.decrypt_password(raw_password)
        default_latitude = coerce_optional_float(effective_settings.get("default_latitude"))
        default_longitude = coerce_optional_float(effective_settings.get("default_longitude"))

        if personal_latitude is not None and personal_longitude is not None:
            latitude = float(personal_latitude)
            longitude = float(personal_longitude)
            location_source = "personal"
            location_label = str(upt.nama_upt) if upt else "Lokasi Personal"
        else:
            latitude = default_latitude if default_latitude is not None else DEFAULT_LOCATION_LATITUDE
            longitude = default_longitude if default_longitude is not None else DEFAULT_LOCATION_LONGITUDE
            location_source = "default"
            location_label = str(effective_settings.get("default_location") or DEFAULT_SETTINGS["default_location"])

        raw_cron_in = getattr(user, "cron_in", None)
        raw_cron_out = getattr(user, "cron_out", None)
        raw_workdays = getattr(user, "workdays", None)
        cron_in = normalize_time_value(raw_cron_in, str(effective_settings["cron_in"]))
        cron_out = normalize_time_value(raw_cron_out, str(effective_settings["cron_out"]))
        workdays = normalize_workdays(raw_workdays, str(effective_settings["default_workdays"]))
        has_password = bool(decrypted_password)
        is_active = bool(getattr(user, "is_active", True))
        auto_attendance_active, auto_attendance_reason = resolve_auto_attendance_status(
            automation_enabled=bool(effective_settings.get("automation_enabled", True)),
            is_active=is_active,
            has_password=has_password,
            cron_in=cron_in,
            cron_out=cron_out,
            latitude=latitude,
            longitude=longitude,
        )
        return {
            "nip": str(user.nip),
            "nama": str(user.nama),
            "nama_upt": str(upt.nama_upt) if upt else "Unknown",
            "latitude": latitude,
            "longitude": longitude,
            "location_label": location_label,
            "location_source": location_source,
            "telegram_id": coerce_telegram_id(getattr(user, "telegram_id", None)),
            "password": decrypted_password,
            "has_password": has_password,
            "cron_in": cron_in,
            "cron_out": cron_out,
            "cron_in_source": "personal" if is_valid_time_text(str(raw_cron_in).strip()) else "default",
            "cron_out_source": "personal" if is_valid_time_text(str(raw_cron_out).strip()) else "default",
            "workdays": workdays,
            "workdays_label": get_workday_label(workdays),
            "workdays_source": "personal" if raw_workdays not in (None, "") else "default",
            "is_admin": bool(getattr(user, "is_admin", False)),
            "is_active": is_active,
            "auto_attendance_active": auto_attendance_active,
            "auto_attendance_reason": auto_attendance_reason,
            "jabatan": str(user.jabatan) if getattr(user, "jabatan", None) else "-",
            "divisi": str(user.divisi) if getattr(user, "divisi", None) else "-",
            "pangkat": str(user.pangkat) if getattr(user, "pangkat", None) else "-",
            "email": str(user.email) if getattr(user, "email", None) else "-",
        }

    # --- USER OPERATIONS (POSTGRES PRIMARY) ---

    def get_user_by_nip(self, nip: str) -> UserData | None:
        return self.get_user_data(nip)

    def get_user_data(self, nip: str) -> UserData | None:
        with self.cache_lock:
            cached = self.__class__.user_cache.get(nip)
            if cached and self.is_cache_valid(cached[0], settings.USER_CACHE_TTL_SECONDS):
                return cast(UserData, dict(cached[1]))

        db_settings = self.get_settings()
        with db_manager.get_session() as session:
            user = session.query(User).options(joinedload(User.upt)).filter(User.nip == nip).first()
            if not user:
                return None

            serialized = self.serialize_user(user, db_settings=db_settings)
            with self.cache_lock:
                self.__class__.user_cache[nip] = (self.now_monotonic(), serialized)
            return cast(UserData, dict(serialized))

    def get_user_summaries(self) -> list[UserData]:
        with self.cache_lock:
            cached = self.__class__.user_summaries_cache
            if cached and self.is_cache_valid(cached[0], settings.USER_CACHE_TTL_SECONDS):
                return [cast(UserData, dict(item)) for item in cached[1]]

        db_settings = self.get_settings()
        with db_manager.get_session() as session:
            users = session.query(User).options(joinedload(User.upt)).order_by(User.nama.asc()).all()
            summaries = [self.serialize_user(user, db_settings=db_settings) for user in users]

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
        """Returns all UPTs as a list of dicts for keyboard generation."""
        with db_manager.get_session() as session:
            upts = session.query(UPT).order_by(UPT.nama_upt).all()
            return [{"id": str(u.id), "nama_upt": str(u.nama_upt)} for u in upts]

    def add_user(self, data: dict[str, Any]) -> bool:
        nip = data.get("nip")
        if not nip:
            return False

        db_settings = self.get_settings()
        with db_manager.get_session() as session:
            actual_upt_id = self.resolve_upt_id(session, data.get("upt_id"))
            encrypted_password = self.encrypt_password(data.get("password"))

            existing_user = session.query(User).filter(User.nip == nip).first()
            if existing_user:
                # Protection: Don't allow a new telegram_id to overwrite an EXISTING different telegram_id
                # unless the update is coming from an admin (where we might just be updating fields)
                # or the NIP didn't have a telegram_id yet (e.g., added by admin manually).
                new_tid = coerce_telegram_id(data.get("telegram_id"))
                if existing_user.telegram_id and new_tid and existing_user.telegram_id != new_tid:
                    # NIP is already linked to someone else.
                    return False

                existing_user.nama = data.get("nama", existing_user.nama)
                if encrypted_password is not None:
                    existing_user.password = encrypted_password
                if actual_upt_id:
                    existing_user.upt_id = actual_upt_id

                if new_tid is not None:
                    existing_user.telegram_id = new_tid
                existing_user.role = data.get("role", existing_user.role)
                if "cron_in" in data and data.get("cron_in"):
                    existing_user.cron_in = str(data["cron_in"])
                if "cron_out" in data and data.get("cron_out"):
                    existing_user.cron_out = str(data["cron_out"])
                if "is_active" in data:
                    existing_user.is_active = bool(data["is_active"])
                
                # Sync extended fields
                for field in ["jabatan", "divisi", "pangkat", "email", "sso_sub", "birth_date", "birth_place"]:
                    if field in data and data.get(field):
                        setattr(existing_user, field, data[field])

                session.add(existing_user)
            else:
                session.add(
                    User(
                        id=data.get("id") or uuid.uuid4(),
                        nip=nip,
                        nama=data.get("nama", ""),
                        password=encrypted_password or None,
                        upt_id=actual_upt_id,
                        telegram_id=coerce_telegram_id(data.get("telegram_id")),
                        role=data.get("role", "user"),
                        is_admin=bool(data.get("is_admin", False)),
                        is_active=bool(data.get("is_active", True)),
                        cron_in=str(data["cron_in"]).strip() if data.get("cron_in") not in (None, "") else None,
                        cron_out=str(data["cron_out"]).strip() if data.get("cron_out") not in (None, "") else None,
                        workdays=normalize_workdays(data.get("workdays"), str(db_settings["default_workdays"]))
                        if data.get("workdays") not in (None, "")
                        else None,
                        # Sync extended fields
                        jabatan=data.get("jabatan"),
                        divisi=data.get("divisi"),
                        pangkat=data.get("pangkat"),
                        email=data.get("email"),
                        sso_sub=data.get("sso_sub"),
                        birth_date=data.get("birth_date"),
                        birth_place=data.get("birth_place"),
                    )
                )

        self.invalidate_user_cache(str(nip))
        self.add_audit_log(
            nip=str(nip),
            action="registration",
            status="success",
            message=f"Personnel Registered/Updated: {data.get('nama')}",
        )
        return True

    def update_user_settings(self, nip: str, settings_update: dict[str, Any]) -> bool:
        with db_manager.get_session() as session:
            user = session.query(User).filter(User.nip == nip).first()
            if not user:
                return False

            if "cron_in" in settings_update:
                value = settings_update["cron_in"]
                normalized = str(value).strip() if value not in (None, "") else ""
                user.cron_in = normalized if normalized.lower() not in {"none", "null", "default", "-"} else None
            if "cron_out" in settings_update:
                value = settings_update["cron_out"]
                normalized = str(value).strip() if value not in (None, "") else ""
                user.cron_out = normalized if normalized.lower() not in {"none", "null", "default", "-"} else None
            if "personal_latitude" in settings_update:
                user.personal_latitude = coerce_optional_float(settings_update["personal_latitude"])
            if "personal_longitude" in settings_update:
                user.personal_longitude = coerce_optional_float(settings_update["personal_longitude"])
            if "workdays" in settings_update:
                value = settings_update["workdays"]
                user.workdays = normalize_workdays(value) if value not in (None, "") else None
            if "is_active" in settings_update:
                user.is_active = bool(settings_update["is_active"])
            if "nama" in settings_update:
                user.nama = str(settings_update["nama"])
            if "password" in settings_update:
                encrypted_password = self.encrypt_password(settings_update["password"])
                if encrypted_password is not None:
                    user.password = encrypted_password
            
            if "jabatan" in settings_update:
                user.jabatan = str(settings_update["jabatan"])
            if "divisi" in settings_update:
                user.divisi = str(settings_update["divisi"])
            if "pangkat" in settings_update:
                user.pangkat = str(settings_update["pangkat"])
            if "email" in settings_update:
                user.email = str(settings_update["email"])

            if "upt_id" in settings_update:
                user.upt_id = self.resolve_upt_id(session, settings_update["upt_id"])

            session.add(user)

        self.invalidate_user_cache(nip)
        self.add_audit_log(
            nip=nip,
            action="settings_update",
            status="success",
            message=f"Personnel Settings Updated: {settings_update}",
        )
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

            user_id = user.id
            user.nip = new_nip
            session.query(UserSession).filter(UserSession.nip == old_nip).update(
                {"nip": new_nip}, synchronize_session=False
            )
            session.query(AuditLog).filter(AuditLog.nip == old_nip).update(
                {"nip": new_nip}, synchronize_session=False
            )
            session.query(PersonalAllowance).filter(PersonalAllowance.nip == old_nip).update(
                {"nip": new_nip}, synchronize_session=False
            )
            session.query(UserPerformanceAllowance).filter(UserPerformanceAllowance.nip == old_nip).update(
                {"nip": new_nip}, synchronize_session=False
            )
            session.execute(
                text("UPDATE public.attendance_job_locks SET nip = :new_nip WHERE nip = :old_nip"),
                {"old_nip": old_nip, "new_nip": new_nip},
            )
            session.execute(
                text("UPDATE public.attendance_dead_letters SET nip = :new_nip WHERE nip = :old_nip"),
                {"old_nip": old_nip, "new_nip": new_nip},
            )
            self.add_audit_log_entry(
                session,
                nip=new_nip,
                action=AuditAction.rename_nip,
                status=AuditStatus.success,
                message=f"Personnel NIP renamed from {old_nip} to {new_nip}",
                user_id=user_id,
            )

        self.invalidate_user_cache()
        return True

    def get_users_with_passwords(self) -> list[UserData]:
        with self.cache_lock:
            cached = self.__class__.users_with_passwords_cache
            if cached and self.is_cache_valid(cached[0], settings.USER_CACHE_TTL_SECONDS):
                return [cast(UserData, dict(item)) for item in cached[1]]

        db_settings = self.get_settings()
        with db_manager.get_session() as session:
            users = (
                session.query(User)
                .options(joinedload(User.upt))
                .filter(User.password != None, User.password != "", User.is_active == True)  # noqa: E711,E712
                .order_by(User.nama.asc())
                .all()
            )
            results = [self.serialize_user(user, db_settings=db_settings) for user in users]

        with self.cache_lock:
            self.__class__.users_with_passwords_cache = (self.now_monotonic(), results)
        return [cast(UserData, dict(item)) for item in results]

    def delete_user(self, nip: str) -> bool:
        deleted = False
        with db_manager.get_session() as session:
            session.query(AuditLog).filter(AuditLog.nip == nip).delete()
            session.query(UserSession).filter(UserSession.nip == nip).delete()
            deleted = session.query(User).filter(User.nip == nip).delete() > 0

        self.invalidate_user_cache(nip)
        if deleted:
            self.add_audit_log(
                nip=nip,
                action="delete_personnel",
                status="success",
                message="Personnel Data Definitively Deleted from Cluster.",
            )
        return deleted

    # --- SESSION MANAGEMENT (POSTGRES BACKED) ---

    def save_user_session(self, nip: str, session_data: dict[str, Any]) -> None:
        if not session_data or not session_data.get("cookies"):
            print(f"Invalid or empty session data for {nip}. Deleting existing session if any.")
            self.delete_user_session(nip)
            return

        with db_manager.get_session() as session:
            user = session.query(User).filter(User.nip == nip).first()
            if not user:
                print(f"Cannot save session: User {nip} not found in DB.")
                return

            existing = session.query(UserSession).filter(UserSession.user_id == user.id).first()
            if existing:
                existing.data = session_data
                existing.nip = nip
                existing.updated_at = now_storage()
            else:
                session.add(
                    UserSession(
                        user_id=user.id,
                        nip=nip,
                        data=session_data,
                        updated_at=now_storage(),
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

    # --- AUDIT LOGS & TELEMETRY ---

    def add_audit_log(
        self,
        nip: str,
        action: str | AuditAction,
        status: str | AuditStatus,
        message: str,
        response_time: float | None = None,
    ) -> None:
        with db_manager.get_session() as session:
            self.add_audit_log_entry(
                session,
                nip=nip,
                action=action,
                status=status,
                message=message,
                response_time=response_time,
            )

    def add_audit_log_entry(
        self,
        session: Any,
        *,
        nip: str,
        action: str | AuditAction,
        status: str | AuditStatus,
        message: str,
        response_time: float | None = None,
        user_id: Any | None = None,
    ) -> None:
        normalized_nip = str(nip)
        normalized_action = normalize_audit_action(action)
        normalized_status = normalize_audit_status(status)
        resolved_user_id = user_id
        if resolved_user_id is None:
            user = session.query(User).filter(User.nip == normalized_nip).first()
            resolved_user_id = user.id if user else None

        session.add(
            AuditLog(
                user_id=resolved_user_id,
                nip=normalized_nip,
                action=normalized_action,
                status=normalized_status,
                message=message,
                response_time=response_time,
            )
        )

    def get_last_success_action(self, nip: str, action: str) -> tuple[datetime | None, str | None]:
        with db_manager.get_session() as session:
            log = (
                session.query(AuditLog)
                .filter(
                    AuditLog.nip == nip,
                    AuditLog.action == action,
                    AuditLog.status == "success",
                )
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            if log:
                return log.timestamp, log.message
            return None, None

    def get_last_success_actions(self, nip: str) -> dict[str, datetime | None]:
        from sqlalchemy import String, cast

        with db_manager.get_session() as session:
            rows = (
                session.query(
                    cast(AuditLog.action, String).label("action_str"),
                    func.max(AuditLog.timestamp).label("latest_timestamp"),
                )
                .filter(
                    AuditLog.nip == nip,
                    AuditLog.status.in_(["success", "ok"]),
                    cast(AuditLog.action, String).in_(["in", "out", "checkin", "checkout"]),
                )
                .group_by(text("action_str"))
                .all()
            )

            result: dict[str, datetime | None] = {"in": None, "out": None}
            for action_str, latest_timestamp in rows:
                action_str = str(action_str).lower()
                if "." in action_str:
                    action_str = action_str.split(".")[-1]

                if action_str in {"in", "checkin"}:
                    if result["in"] is None or (
                        latest_timestamp and (result["in"] is None or latest_timestamp > result["in"])
                    ):
                        result["in"] = latest_timestamp
                elif action_str in {"out", "checkout"}:
                    if result["out"] is None or (
                        latest_timestamp and (result["out"] is None or latest_timestamp > result["out"])
                    ):
                        result["out"] = latest_timestamp
            return result

    # --- BOT MESSAGE TRACKING (AUTO-CLEAN) ---

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
            return [
                {"id": m.id, "chat_id": m.chat_id, "message_id": m.message_id}
                for m in msgs
            ]

    def delete_bot_message_record(self, record_id: Any) -> None:
        with db_manager.get_session() as session:
            session.query(BotMessage).filter(BotMessage.id == record_id).delete()

    def get_user_history(self, nip: str, limit: int = 10) -> list[AuditLogData]:
        with db_manager.get_session() as session:
            logs = (
                session.query(AuditLog)
                .filter(AuditLog.nip == nip)
                .order_by(AuditLog.timestamp.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "nip": str(log.nip),
                    "action": str(log.action),
                    "status": str(log.status),
                    "message": str(log.message),
                    "response_time": log.response_time,
                    "timestamp": log.timestamp,
                }
                for log in logs
            ]

    def get_system_metrics(self) -> dict[str, Any]:
        """Fetch high-level system metrics for telemetry."""
        from datetime import date

        from sqlalchemy import func

        with db_manager.get_session() as session:
            total_users = session.query(func.count(User.id)).filter(User.is_active == True).scalar()
            total_with_pass = (
                session.query(func.count(User.id)).filter(User.is_active == True, User.password != None).scalar()
            )
            success_today = (
                session.query(func.count(AuditLog.id))
                .filter(AuditLog.status == "success", AuditLog.timestamp >= date.today())
                .scalar()
            )

            return {
                "active_personnel": total_users,
                "managed_personnel": total_with_pass,
                "success_today": success_today,
                "db_provider": "Supabase (PostgreSQL)",
            }

    def get_global_audit_logs(self, limit: int = 20) -> list[AuditLogData]:
        with db_manager.get_session() as session:
            logs = session.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()
            return [
                {
                    "nip": str(log.nip),
                    "action": str(log.action),
                    "status": str(log.status),
                    "message": str(log.message),
                    "response_time": log.response_time,
                    "timestamp": log.timestamp,
                }
                for log in logs
            ]

    def get_recent_audit_feed(
        self,
        limit: int = 200,
        status: str | None = None,
        action: str | None = None,
        nip: str | None = None,
    ) -> list[dict[str, Any]]:
        with db_manager.get_session() as session:
            query = (
                session.query(AuditLog, User.nama)
                .outerjoin(User, User.nip == AuditLog.nip)
                .order_by(AuditLog.timestamp.desc())
            )

            if status:
                query = query.filter(AuditLog.status.ilike(status))
            if action:
                query = query.filter(AuditLog.action == action)
            if nip:
                query = query.filter(AuditLog.nip == nip)

            rows = query.limit(limit).all()

        feed: list[dict[str, Any]] = []
        for log, user_name in rows:
            local_ts = to_local(log.timestamp)
            feed.append(
                {
                    "nip": str(log.nip),
                    "nama": user_name or ("System" if str(log.nip).upper() == "SYSTEM" else "Unknown"),
                    "action": str(log.action),
                    "status": str(log.status).upper(),
                    "message": str(log.message),
                    "response_time": log.response_time,
                    "timestamp": format_formal_timestamp(local_ts),
                    "timestamp_raw": isoformat_local(local_ts),
                }
            )
        return feed

    def clear_audit_logs(self) -> int:
        with db_manager.get_session() as session:
            deleted = session.query(AuditLog).delete()
        return int(deleted or 0)

    def get_daily_stats(self) -> dict[str, int]:
        from sqlalchemy import String, cast

        start_utc, end_utc = local_day_bounds()
        with db_manager.get_session() as session:
            rows = (
                session.query(
                    cast(AuditLog.action, String).label("action_str"),
                    cast(AuditLog.status, String).label("status_str"),
                    func.count(AuditLog.id).label("count"),
                )
                .filter(
                    AuditLog.timestamp >= start_utc,
                    AuditLog.timestamp < end_utc,
                    cast(AuditLog.action, String).in_(["in", "out", "checkin", "checkout"]),
                )
                .group_by(text("action_str"), text("status_str"))
                .all()
            )

        stats = {
            "total_attempts": 0,
            "in_success": 0,
            "in_failed": 0,
            "out_success": 0,
            "out_failed": 0,
        }
        for action_str, status_str, count in rows:
            normalized_action = str(action_str).lower()
            if normalized_action == "checkin":
                normalized_action = "in"
            elif normalized_action == "checkout":
                normalized_action = "out"

            normalized_status = str(status_str).lower()
            if normalized_action not in {"in", "out"}:
                continue
            if normalized_status in {"success", "ok"}:
                stats[f"{normalized_action}_success"] += int(count)
                stats["total_attempts"] += int(count)
            elif normalized_status not in {"skipped"}:
                stats[f"{normalized_action}_failed"] += int(count)
                stats["total_attempts"] += int(count)
        return stats

    def get_metrics_overview(self, hours: int = 24) -> dict[str, Any]:
        from sqlalchemy import String, cast

        window_start = now_utc() - timedelta(hours=hours)
        with db_manager.get_session() as session:
            rows = (
                session.query(
                    cast(AuditLog.action, String).label("action_str"),
                    cast(AuditLog.status, String).label("status_str"),
                    func.count(AuditLog.id).label("count"),
                    func.avg(AuditLog.response_time).label("avg_response_time"),
                )
                .filter(AuditLog.timestamp >= window_start)
                .group_by(text("action_str"), text("status_str"))
                .all()
            )
            try:
                dead_letter_count = (
                    session.execute(
                        text("SELECT COUNT(*) FROM public.attendance_dead_letters WHERE failed_at >= :window_start"),
                        {"window_start": window_start},
                    ).scalar_one_or_none()
                    or 0
                )
            except Exception:
                dead_letter_count = 0

        totals: dict[str, int] = {"total": 0, "success": 0, "failed": 0, "in": 0, "out": 0}
        avg_samples: list[float] = []
        for action_str, status_str, count, avg_response_time in rows:
            normalized_status = str(status_str).lower()
            normalized_action = str(action_str).lower()

            totals["total"] += int(count)
            if normalized_status in {"success", "ok"}:
                totals["success"] += int(count)
            else:
                totals["failed"] += int(count)

            if normalized_action in {"in", "checkin"}:
                totals["in"] += int(count)
            if normalized_action in {"out", "checkout"}:
                totals["out"] += int(count)
            if avg_response_time is not None:
                avg_samples.append(float(avg_response_time))

        failure_rate = (totals["failed"] / totals["total"]) if totals["total"] else 0.0
        alerts: list[dict[str, Any]] = []
        if failure_rate >= settings.ALERT_FAILURE_RATE_THRESHOLD:
            alerts.append(
                {
                    "level": "warning",
                    "code": "high_failure_rate",
                    "message": f"Failure rate {failure_rate:.1%} dalam {hours} jam terakhir melewati ambang.",
                }
            )
        if int(dead_letter_count) > 0:
            alerts.append(
                {
                    "level": "warning",
                    "code": "dead_letters_present",
                    "message": f"Terdapat {dead_letter_count} job di dead-letter queue.",
                }
            )

        return {
            "window_hours": hours,
            "generated_at": isoformat_local(),
            "totals": totals,
            "failure_rate": failure_rate,
            "avg_response_time": (sum(avg_samples) / len(avg_samples)) if avg_samples else None,
            "dead_letters": int(dead_letter_count),
            "alerts": alerts,
        }

    def get_recent_dead_letters(self, limit: int = 10) -> list[dict[str, Any]]:
        with db_manager.get_session() as session:
            rows = (
                session.execute(
                    text(
                        """
                    SELECT request_key, nip, action, reason, attempts, last_error, failed_at
                    FROM public.attendance_dead_letters
                    ORDER BY failed_at DESC
                    LIMIT :limit
                    """
                    ),
                    {"limit": limit},
                )
                .mappings()
                .all()
            )

        results: list[dict[str, Any]] = []
        for row in rows:
            failed_at_local = to_local(row["failed_at"])
            results.append(
                {
                    "request_key": str(row["request_key"]),
                    "nip": str(row["nip"]),
                    "action": str(row["action"]),
                    "reason": str(row["reason"]),
                    "attempts": int(row["attempts"]),
                    "last_error": row["last_error"],
                    "failed_at": format_formal_timestamp(failed_at_local),
                    "failed_at_raw": isoformat_local(failed_at_local),
                }
            )
        return results

    def has_successful_attendance_today(self, nip: str, action: str) -> bool:
        start_utc, end_utc = local_day_bounds()

        # Normalize action to handle both 'in' and 'checkin'
        action_variants = [action]
        if action == "in":
            action_variants.append("checkin")
        elif action == "out":
            action_variants.append("checkout")
        elif action == "checkin":
            action_variants.append("in")
        elif action == "checkout":
            action_variants.append("out")

        with db_manager.get_session() as session:
            from sqlalchemy import String, cast

            row = (
                session.query(AuditLog.id)
                .filter(
                    AuditLog.nip == nip,
                    cast(AuditLog.action, String).in_(action_variants),
                    AuditLog.status.in_(["success", "ok"]),
                    AuditLog.timestamp >= start_utc,
                    AuditLog.timestamp < end_utc,
                )
                .first()
            )
            return row is not None

    def acquire_attendance_lock(self, nip: str, action: str, request_key: str, source: str) -> bool:
        scope = str(local_date())
        lock_key = f"{nip}:{action}:{scope}"
        expires_at = now_utc() + timedelta(seconds=settings.IDEMPOTENCY_LOCK_TTL_SECONDS)
        created_at = now_utc()
        with db_manager.get_session() as session:
            session.execute(text("DELETE FROM public.attendance_job_locks WHERE expires_at <= now()"))
            row = session.execute(
                text(
                    """
                    INSERT INTO public.attendance_job_locks
                        (lock_key, request_key, nip, action, source, scope_date, created_at, expires_at)
                    VALUES
                        (:lock_key, :request_key, :nip, :action, :source, :scope_date, :created_at, :expires_at)
                    ON CONFLICT (lock_key) DO NOTHING
                    RETURNING lock_key
                    """
                ),
                {
                    "lock_key": lock_key,
                    "request_key": request_key,
                    "nip": nip,
                    "action": action,
                    "source": source,
                    "scope_date": scope,
                    "created_at": created_at,
                    "expires_at": expires_at,
                },
            ).first()
            return row is not None

    def release_attendance_lock(self, request_key: str) -> None:
        with db_manager.get_session() as session:
            session.execute(
                text("DELETE FROM public.attendance_job_locks WHERE request_key = :request_key"),
                {"request_key": request_key},
            )

    def record_dead_letter(
        self,
        request_key: str,
        nip: str,
        action: str,
        payload: dict[str, Any],
        reason: str,
        attempts: int,
        last_error: str | None = None,
    ) -> None:
        with db_manager.get_session() as session:
            session.execute(
                text(
                    """
                    INSERT INTO public.attendance_dead_letters
                        (request_key, nip, action, payload, reason, attempts, last_error, failed_at)
                    VALUES
                        (:request_key, :nip, :action, CAST(:payload AS jsonb), :reason, :attempts, :last_error, :failed_at)
                    ON CONFLICT (request_key) DO UPDATE SET
                        payload = EXCLUDED.payload,
                        reason = EXCLUDED.reason,
                        attempts = EXCLUDED.attempts,
                        last_error = EXCLUDED.last_error,
                        failed_at = EXCLUDED.failed_at
                    """
                ),
                {
                    "request_key": request_key,
                    "nip": nip,
                    "action": action,
                    "payload": json.dumps(payload),
                    "reason": reason,
                    "attempts": attempts,
                    "last_error": last_error,
                    "failed_at": now_utc(),
                },
            )

    # --- GLOBAL SETTINGS ---

    def get_settings(self) -> dict[str, Any]:
        with self.cache_lock:
            cached = self.__class__.settings_cache
            if cached and self.is_cache_valid(cached[0], settings.SETTINGS_CACHE_TTL_SECONDS):
                return dict(cached[1])

        with db_manager.get_session() as session:
            rows = session.query(GlobalSetting).all()
            values = {row.key: row.value for row in rows}
            merged = self.merge_settings(values)
            
        with self.cache_lock:
            self.__class__.settings_cache = (self.now_monotonic(), merged)
        return dict(merged)

    def set_setting(self, key: str, value: str) -> None:
        with db_manager.get_session() as session:
            session.merge(GlobalSetting(key=key, value=stringify_setting(value)))
        self.invalidate_settings_cache()

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        allowed_keys = {
            "default_location",
            "default_latitude",
            "default_longitude",
            "timezone",
            "rule_in_before",
            "rule_out_after",
            "rule_mode",
            "rule_work_hours",
            "ocr_engine",
            "automation_enabled",
            "cron_in",
            "cron_out",
            "default_workdays",
            "time_storage_version",
        }
        with db_manager.get_session() as session:
            for key, value in payload.items():
                if key not in allowed_keys:
                    continue
                session.merge(GlobalSetting(key=key, value=stringify_setting(value)))
        self.invalidate_settings_cache()
        self.add_audit_log(
            nip="SYSTEM",
            action="settings_update",
            status="ok",
            message="Global settings updated via control plane.",
        )
        return self.get_settings()

    def get_mass_status(self) -> dict[str, Any]:
        values = self.get_settings()
        return {
            "active": values.get("mass_active", "0"),
            "action": values.get("mass_action", ""),
            "pos": values.get("mass_pos", "0"),
            "total": values.get("mass_total", "0"),
            "last_nip": values.get("mass_last_nip", ""),
            "start_time": values.get("mass_start_time", "0"),
            "in_success": int(values.get("mass_in_success", 0)),
            "in_failed": int(values.get("mass_in_failed", 0)),
            "out_success": int(values.get("mass_out_success", 0)),
            "out_failed": int(values.get("mass_out_failed", 0)),
            "log": values.get("mass_log", "[]"),
        }

    def update_mass_status(self, data: dict[str, Any]) -> None:
        for key, value in data.items():
            self.set_setting(f"mass_{key}", str(value))

    def increment_mass_pos(self) -> int:
        """Atomically increments the mass attendance progress position and handles completion."""
        with db_manager.get_session() as session:
            session.execute(
                text(
                    "INSERT INTO settings (key, value) VALUES ('mass_pos', '1') "
                    "ON CONFLICT (key) DO UPDATE SET value = (settings.value::int + 1)::text"
                )
            )
            session.commit()
            pos = int(session.execute(text("SELECT value FROM settings WHERE key = 'mass_pos'")).scalar() or 0)
            total = int(session.execute(text("SELECT value FROM settings WHERE key = 'mass_total'")).scalar() or 0)
            if pos >= total and total > 0:
                session.execute(text("UPDATE settings SET value = '0' WHERE key = 'mass_active'"))
                session.commit()
            return pos
    def add_mass_log(self, nip: str, name: str, status: str) -> None:
        """Adds a log entry to the rolling mass attendance log (max 5 entries)."""
        import json
        with db_manager.get_session() as session:
            current = session.execute(text("SELECT value FROM settings WHERE key = 'mass_log'")).scalar()
            logs = json.loads(str(current)) if current else []
            
            status_emoji = "✅" if status == "success" else "❌" if status == "failed" else "⚠️"
            entry = f"{status_emoji} {name} ({nip}) - {status.upper()}"
            
            logs.insert(0, entry)
            logs = logs[:5]  # Keep only last 5
            
            session.execute(
                text("INSERT INTO settings (key, value) VALUES ('mass_log', :val) ON CONFLICT (key) DO UPDATE SET value = :val"),
                {"val": json.dumps(logs)}
            )
            session.commit()

    def trigger_mass_stop(self) -> None:
        self.set_setting("mass_stop", "1")
        self.set_setting("mass_active", "0")

    def clear_mass_stop(self) -> None:
        self.set_setting("mass_stop", "0")

    def is_mass_stop_requested(self) -> bool:
        return self.get_settings().get("mass_stop") == "1"

    # --- PERSONAL ALLOWANCE OPERATIONS ---

    def save_user_performance_allowance(
        self,
        nip: str,
        period_code: str,
        year: int,
        data: list[dict[str, Any]],
        *,
        period_label: str | None = None,
        period_start: Any = None,
        period_end: Any = None,
    ) -> None:
        with db_manager.get_session() as session:
            user = session.query(User).filter(User.nip == nip).first()
            user_id = user.id if user else None
            resolved_period_start = coerce_optional_date(period_start)
            resolved_period_end = coerce_optional_date(period_end)

            session.query(UserPerformanceAllowance).filter(
                UserPerformanceAllowance.nip == nip,
                UserPerformanceAllowance.allowance_year == year,
                UserPerformanceAllowance.period_code == period_code,
            ).delete()

            for item in data:
                date_str = item.get("date")
                if not date_str:
                    continue
                try:
                    dt = datetime.strptime(str(date_str), "%Y-%m-%d").date()
                except ValueError:
                    continue

                allowance = UserPerformanceAllowance(
                    user_id=user_id,
                    nip=nip,
                    allowance_year=year,
                    period_code=period_code,
                    period_label=period_label,
                    period_start=resolved_period_start,
                    period_end=resolved_period_end,
                    allowance_date=dt,
                    clock_in=item.get("clock_in"),
                    clock_out=item.get("clock_out"),
                    daily_allowance_amount=item.get("daily_allowance_amount"),
                    deduction_amount=item.get("deduction_amount"),
                    total=item.get("total"),
                    deduction_reason=item.get("deduction_reason"),
                    raw_payload=dict(item),
                    synced_at=now_storage(),
                    updated_at=now_storage(),
                )
                session.add(allowance)
            session.commit()

    def get_user_performance_allowance(self, nip: str, period_code: str, year: int) -> list[dict[str, Any]]:
        with db_manager.get_session() as session:
            rows = (
                session.query(UserPerformanceAllowance)
                .filter(
                    UserPerformanceAllowance.nip == nip,
                    UserPerformanceAllowance.period_code == period_code,
                    UserPerformanceAllowance.allowance_year == year,
                )
                .order_by(UserPerformanceAllowance.allowance_date.asc())
                .all()
            )
            if not rows:
                legacy_rows = (
                    session.query(PersonalAllowance)
                    .filter(PersonalAllowance.nip == nip, PersonalAllowance.period_code == period_code)
                    .order_by(PersonalAllowance.date.asc())
                    .all()
                )
                return [
                    {
                        "date": row.date.strftime("%Y-%m-%d"),
                        "clock_in": row.clock_in,
                        "clock_out": row.clock_out,
                        "daily_allowance_amount": row.daily_allowance_amount,
                        "deduction_amount": row.deduction_amount,
                        "total": row.total,
                        "deduction_reason": row.deduction_reason,
                    }
                    for row in legacy_rows
                ]
            return [
                {
                    "date": row.allowance_date.strftime("%Y-%m-%d"),
                    "clock_in": row.clock_in,
                    "clock_out": row.clock_out,
                    "daily_allowance_amount": row.daily_allowance_amount,
                    "deduction_amount": row.deduction_amount,
                    "total": row.total,
                    "deduction_reason": row.deduction_reason,
                }
                for row in rows
            ]

    def get_user_performance_allowance_periods(self, nip: str, year: int) -> list[dict[str, Any]]:
        with db_manager.get_session() as session:
            rows = (
                session.query(UserPerformanceAllowance)
                .filter(
                    UserPerformanceAllowance.nip == nip,
                    UserPerformanceAllowance.allowance_year == year,
                )
                .order_by(
                    UserPerformanceAllowance.allowance_year.desc(),
                    UserPerformanceAllowance.allowance_date.desc(),
                )
                .all()
            )
            seen: set[tuple[int, str]] = set()
            periods: list[dict[str, Any]] = []
            for row in rows:
                key = (int(row.allowance_year), str(row.period_code))
                if key in seen:
                    continue
                seen.add(key)
                periods.append(
                    {
                        "year": int(row.allowance_year),
                        "period_code": str(row.period_code),
                        "period_label": row.period_label or row.period_code,
                        "period_start": row.period_start.isoformat() if row.period_start else None,
                        "period_end": row.period_end.isoformat() if row.period_end else None,
                        "synced_at": isoformat_local(row.synced_at) if row.synced_at else None,
                    }
                )
            if periods:
                return periods

            legacy_rows = (
                session.query(PersonalAllowance)
                .filter(PersonalAllowance.nip == nip)
                .order_by(PersonalAllowance.date.desc())
                .all()
            )
            legacy_periods: list[dict[str, Any]] = []
            legacy_seen: set[str] = set()
            for row in legacy_rows:
                if not row.period_code or row.period_code in legacy_seen:
                    continue
                legacy_year = row.date.year
                if legacy_year != year:
                    continue
                legacy_seen.add(row.period_code)
                legacy_periods.append(
                    {
                        "year": legacy_year,
                        "period_code": row.period_code,
                        "period_label": row.period_code,
                        "period_start": None,
                        "period_end": None,
                        "synced_at": isoformat_local(row.updated_at) if row.updated_at else None,
                    }
                )
            return legacy_periods

    def save_personal_allowance(
        self,
        nip: str,
        period_code: str,
        data: list[dict[str, Any]],
        *,
        year: int | None = None,
        period_label: str | None = None,
        period_start: Any = None,
        period_end: Any = None,
    ) -> None:
        resolved_year = year if year is not None else infer_allowance_year(period_code, data)
        self.save_user_performance_allowance(
            nip,
            period_code,
            resolved_year,
            data,
            period_label=period_label,
            period_start=period_start,
            period_end=period_end,
        )

    def get_personal_allowance(self, nip: str, period_code: str, year: int | None = None) -> list[dict[str, Any]]:
        if year is not None:
            return self.get_user_performance_allowance(nip, period_code, year)

        with db_manager.get_session() as session:
            rows = (
                session.query(UserPerformanceAllowance)
                .filter(
                    UserPerformanceAllowance.nip == nip,
                    UserPerformanceAllowance.period_code == period_code,
                )
                .order_by(
                    UserPerformanceAllowance.allowance_year.desc(),
                    UserPerformanceAllowance.allowance_date.asc(),
                )
                .all()
            )
            if rows:
                latest_year = int(rows[0].allowance_year)
                return [
                    {
                        "date": row.allowance_date.strftime("%Y-%m-%d"),
                        "clock_in": row.clock_in,
                        "clock_out": row.clock_out,
                        "daily_allowance_amount": row.daily_allowance_amount,
                        "deduction_amount": row.deduction_amount,
                        "total": row.total,
                        "deduction_reason": row.deduction_reason,
                    }
                    for row in rows
                    if int(row.allowance_year) == latest_year
                ]

            legacy_rows = (
                session.query(PersonalAllowance)
                .filter(PersonalAllowance.nip == nip, PersonalAllowance.period_code == period_code)
                .order_by(PersonalAllowance.date.asc())
                .all()
            )
            return [
                {
                    "date": row.date.strftime("%Y-%m-%d"),
                    "clock_in": row.clock_in,
                    "clock_out": row.clock_out,
                    "daily_allowance_amount": row.daily_allowance_amount,
                    "deduction_amount": row.deduction_amount,
                    "total": row.total,
                    "deduction_reason": row.deduction_reason,
                }
                for row in legacy_rows
            ]

    def search_users(self, query: str) -> list[UserData]:
        db_settings = self.get_settings()
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
