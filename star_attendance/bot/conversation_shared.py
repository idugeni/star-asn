from __future__ import annotations

import re
from typing import Any

from telegram import Update

from star_attendance.database_manager import WORKDAY_ALIASES, WORKDAY_PRESETS, normalize_workdays
from star_attendance.runtime import get_store

store = get_store()


def validate_nip(nip: Any) -> str:
    """Validates NIP format (must be 18 digits)."""
    raw = str(nip).strip()
    if not re.fullmatch(r"\d{18}", raw):
        raise ValueError("NIP harus terdiri dari 18 digit angka.")
    return raw


TIME_RE = re.compile(r"^\d{2}:\d{2}$")
GLOBAL_SETTING_LABELS = {
    "default_location": "LOKASI DEFAULT",
    "default_latitude": "LATITUDE DEFAULT",
    "default_longitude": "LONGITUDE DEFAULT",
    "timezone": "TIMEZONE",
    "rule_in_before": "BATAS IN",
    "rule_out_after": "BATAS OUT",
    "rule_mode": "RULE MODE",
    "rule_work_hours": "JAM KERJA",
    "ocr_engine": "OCR ENGINE",
    "automation_enabled": "AUTOMATION ENABLED",
    "cron_in": "CRON IN DEFAULT",
    "cron_out": "CRON OUT DEFAULT",
    "default_workdays": "HARI KERJA DEFAULT",
}


def get_user_id(update: Update) -> int:
    if not update.effective_user:
        raise ValueError("No user found in update")
    return update.effective_user.id


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "on"}:
        return True
    if normalized in {"false", "0", "no", "off"}:
        return False
    raise ValueError("Gunakan salah satu nilai: true/false, yes/no, on/off.")


def validate_time_text(value: str) -> str:
    raw = value.strip()
    if not TIME_RE.match(raw):
        raise ValueError("Format waktu harus HH:MM, contoh 07:00.")
    hour, minute = map(int, raw.split(":"))
    if hour > 23 or minute > 59:
        raise ValueError("Jam atau menit tidak valid.")
    return raw


def parse_workdays(value: str) -> str:
    raw = value.strip().lower().replace("_", "-").replace(" ", "-")
    if raw not in WORKDAY_ALIASES and raw not in WORKDAY_PRESETS:
        raise ValueError("Pilihan hari kerja tidak dikenali.")
    return normalize_workdays(raw)


def parse_coordinates(value: str) -> tuple[float, float]:
    parts = [p.strip() for p in value.replace(",", " ").split() if p.strip()]
    if len(parts) != 2:
        raise ValueError("Gunakan format 'latitude longitude' atau 'latitude, longitude'.")
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        raise ValueError("Koordinat harus berupa angka desimal.")


def parse_schedule_range(value: str) -> tuple[str, str]:
    parts = [p.strip() for p in value.replace("-", " ").replace("–", " ").split() if p.strip()]
    if len(parts) != 2:
        raise ValueError("Gunakan format '07:00 - 16:00'.")
    start = validate_time_text(parts[0])
    end = validate_time_text(parts[1])
    return start, end


def validate_global_setting(key: str, value: str) -> Any:
    raw = value.strip()
    if key in {"rule_in_before", "rule_out_after", "cron_in", "cron_out"}:
        return validate_time_text(raw)
    if key == "rule_mode":
        allowed = {"smart", "combined", "time", "work", "none"}
        normalized = raw.lower()
        if normalized not in allowed:
            raise ValueError("rule_mode harus salah satu: smart, combined, time, work, none.")
        return normalized
    if key in {"default_latitude", "default_longitude"}:
        return float(raw)
    if key == "rule_work_hours":
        hours = float(raw)
        if hours <= 0:
            raise ValueError("rule_work_hours harus lebih dari 0.")
        return hours
    if key == "automation_enabled":
        return parse_bool(raw)
    if key == "default_workdays":
        return parse_workdays(raw)
    if not raw:
        raise ValueError("Nilai tidak boleh kosong.")
    return raw
