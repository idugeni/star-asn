from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

APP_TIMEZONE_NAME = "Asia/Jakarta"
APP_TIMEZONE_LABEL = "WIB"
APP_TIMEZONE = ZoneInfo(APP_TIMEZONE_NAME)

DAY_NAMES = (
    "Senin",
    "Selasa",
    "Rabu",
    "Kamis",
    "Jumat",
    "Sabtu",
    "Minggu",
)

MONTH_NAMES = (
    "",
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
)


def now_local() -> datetime:
    return datetime.now(APP_TIMEZONE)


def now_utc() -> datetime:
    return datetime.now(UTC)


def now_storage() -> datetime:
    """Return UTC-aware datetime for timestamptz storage."""
    return now_utc()


def assume_local(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=APP_TIMEZONE)
    return value.astimezone(APP_TIMEZONE)


def to_local(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return assume_local(value)


def legacy_utc_naive_to_local_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).astimezone(APP_TIMEZONE).replace(tzinfo=None)
    return value.astimezone(APP_TIMEZONE).replace(tzinfo=None)


def legacy_local_naive_to_utc_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    local = assume_local(value)
    return local.astimezone(UTC)


def format_formal_date(value: datetime | None = None) -> str:
    local = to_local(value) or now_local()
    return f"{DAY_NAMES[local.weekday()]}, {local.day:02d} {MONTH_NAMES[local.month]} {local.year}"


def format_precise_time(value: datetime | None = None) -> str:
    local = to_local(value) or now_local()
    return f"{local:%H:%M:%S} {APP_TIMEZONE_LABEL}"


def format_formal_timestamp(value: datetime | None = None) -> str:
    local = to_local(value) or now_local()
    return f"{format_formal_date(local)} {format_precise_time(local)}"


def format_log_timestamp(value: datetime | None = None) -> str:
    local = to_local(value) or now_local()
    return f"{local:%Y-%m-%d %H:%M:%S}.{local.microsecond // 1000:03d} {APP_TIMEZONE_LABEL}"


def isoformat_local(value: datetime | None = None) -> str:
    local = to_local(value) or now_local()
    return local.isoformat(timespec="milliseconds")


def isoformat_utc(value: datetime | None = None) -> str:
    aware = value or now_utc()
    if aware.tzinfo is None:
        aware = legacy_local_naive_to_utc_aware(aware) or now_utc()
    return aware.astimezone(UTC).isoformat(timespec="milliseconds")


def local_day_bounds(value: datetime | None = None) -> tuple[datetime, datetime]:
    local = to_local(value) or now_local()
    start_local = datetime.combine(local.date(), time.min, tzinfo=APP_TIMEZONE)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def local_date(value: datetime | None = None) -> date:
    local = to_local(value) or now_local()
    return local.date()
