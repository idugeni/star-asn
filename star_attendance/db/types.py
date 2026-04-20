from datetime import datetime
from typing import TypedDict


class UPTData(TypedDict):
    id: str
    nama_upt: str
    latitude: float | None
    longitude: float | None
    address: str | None
    timezone: str


class UserData(TypedDict):
    nip: str
    nama: str
    nama_upt: str
    latitude: float | None
    longitude: float | None
    location_label: str
    location_source: str
    telegram_id: int | None
    password: str | None
    has_password: bool
    cron_in: str
    cron_out: str
    cron_in_source: str
    cron_out_source: str
    workdays: str
    workdays_label: str
    workdays_source: str
    is_admin: bool
    is_active: bool
    auto_attendance_active: bool
    auto_attendance_reason: str


class SessionData(TypedDict):
    nip: str
    data: dict
    updated_at: datetime


class AuditLogData(TypedDict):
    nip: str
    action: str
    status: str
    message: str
    response_time: float | None
    timestamp: datetime
