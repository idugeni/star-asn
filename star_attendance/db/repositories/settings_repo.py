"""Settings repository — global settings, mass attendance state, and idempotency locks."""

from __future__ import annotations

import json
import threading
import time
from datetime import timedelta
from typing import Any

from sqlalchemy import text

from star_attendance.core.config import settings
from star_attendance.core.timeutils import local_date, now_utc
from star_attendance.db.manager import db_manager
from star_attendance.db.models import GlobalSetting

DEFAULT_LOCATION_LATITUDE = -6.2210973
DEFAULT_LOCATION_LONGITUDE = 106.8314724
DEFAULT_WORKDAYS = "mon-fri"

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


def stringify_setting(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return ""
    return str(value)


class SettingsRepository:
    """Handles global settings, mass attendance state, and idempotency locks."""

    cache_lock = threading.RLock()
    settings_cache: tuple[float, dict[str, Any]] | None = None

    @staticmethod
    def now_monotonic() -> float:
        return time.monotonic()

    def is_cache_valid(self, timestamp: float, ttl_seconds: int) -> bool:
        return (self.now_monotonic() - timestamp) < ttl_seconds

    def invalidate_settings_cache(self) -> None:
        with self.cache_lock:
            self.__class__.settings_cache = None

    def invalidate_all_caches(self) -> None:
        self.invalidate_settings_cache()

    def merge_settings(self, raw_values: dict[str, Any]) -> dict[str, Any]:
        from star_attendance.database_manager import coerce_bool, coerce_float

        merged = dict(DEFAULT_SETTINGS)
        merged.update(raw_values)
        merged["default_location"] = str(merged.get("default_location") or DEFAULT_SETTINGS["default_location"])
        merged["default_latitude"] = coerce_float(merged.get("default_latitude"), DEFAULT_LOCATION_LATITUDE)
        merged["default_longitude"] = coerce_float(merged.get("default_longitude"), DEFAULT_LOCATION_LONGITUDE)
        merged["automation_enabled"] = coerce_bool(merged.get("automation_enabled"), True)
        return merged

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

    def update_settings(self, payload: dict[str, Any], audit_callback: Any = None) -> dict[str, Any]:
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
        if audit_callback:
            audit_callback(
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
        with db_manager.get_session() as session:
            current = session.execute(text("SELECT value FROM settings WHERE key = 'mass_log'")).scalar()
            logs = json.loads(str(current)) if current else []

            status_emoji = "✅" if status == "success" else "❌" if status == "failed" else "⚠️"
            entry = f"{status_emoji} {name} ({nip}) - {status.upper()}"

            logs.insert(0, entry)
            logs = logs[:5]

            session.execute(
                text(
                    "INSERT INTO settings (key, value) VALUES ('mass_log', :val) ON CONFLICT (key) DO UPDATE SET value = :val"
                ),
                {"val": json.dumps(logs)},
            )
            session.commit()

    def trigger_mass_stop(self) -> None:
        self.set_setting("mass_stop", "1")
        self.set_setting("mass_active", "0")

    def clear_mass_stop(self) -> None:
        self.set_setting("mass_stop", "0")

    def is_mass_stop_requested(self) -> bool:
        return self.get_settings().get("mass_stop") == "1"

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
        from star_attendance.core.timeutils import now_utc as _now_utc

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
                    "failed_at": _now_utc(),
                },
            )

    def get_recent_dead_letters(self, limit: int = 10) -> list[dict[str, Any]]:
        from star_attendance.core.timeutils import format_formal_timestamp, isoformat_local, to_local

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
