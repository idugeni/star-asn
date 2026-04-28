"""Allowance repository — performance allowance and personal allowance operations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from star_attendance.core.timeutils import isoformat_local, now_storage
from star_attendance.db.manager import db_manager
from star_attendance.db.models import PersonalAllowance, User, UserPerformanceAllowance


class AllowanceRepository:
    """Handles performance allowance and personal allowance data."""

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
        from star_attendance.database_manager import coerce_optional_date

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
        from star_attendance.database_manager import infer_allowance_year

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
