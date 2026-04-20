from typing import TypedDict, Optional
from datetime import datetime

class UPTData(TypedDict):
    id: str
    nama_upt: str
    latitude: Optional[float]
    longitude: Optional[float]
    address: Optional[str]
    timezone: str

class UserData(TypedDict):
    nip: str
    nama: str
    nama_upt: str
    latitude: Optional[float]
    longitude: Optional[float]
    location_label: str
    location_source: str
    telegram_id: Optional[int]
    password: Optional[str]
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
    response_time: Optional[float]
    timestamp: datetime
