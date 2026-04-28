"""Audit log repository — all audit, telemetry, and metrics operations."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import String, func, text, cast as sa_cast

from star_attendance.core.config import settings
from star_attendance.core.timeutils import (
    format_formal_timestamp,
    isoformat_local,
    local_day_bounds,
    now_storage,
    now_utc,
    to_local,
)
from star_attendance.db.enums import AuditAction, AuditStatus
from star_attendance.db.manager import db_manager
from star_attendance.db.models import AuditLog, User
from star_attendance.db.types import AuditLogData


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


class AuditRepository:
    """Handles all audit log, metrics, and telemetry operations."""

    def add_audit_log(
        self,
        nip: str,
        action: str | AuditAction,
        status: str | AuditStatus,
        message: str = "",
        *,
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
        message: str = "",
        response_time: float | None = None,
    ) -> None:
        session.add(
            AuditLog(
                nip=nip,
                action=normalize_audit_action(action),
                status=normalize_audit_status(status),
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
                    AuditLog.status.in_(["success", "ok"]),
                )
                .order_by(AuditLog.timestamp.desc())
                .first()
            )
            if log:
                return log.timestamp, log.message
            return None, None

    def get_last_success_actions(self, nip: str) -> dict[str, datetime | None]:
        with db_manager.get_session() as session:
            rows = (
                session.query(
                    sa_cast(AuditLog.action, String).label("action_str"),
                    func.max(AuditLog.timestamp).label("latest_timestamp"),
                )
                .filter(
                    AuditLog.nip == nip,
                    AuditLog.status.in_(["success", "ok"]),
                    sa_cast(AuditLog.action, String).in_(["in", "out", "checkin", "checkout"]),
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
        with db_manager.get_session() as session:
            total_users = session.query(func.count(User.id)).filter(User.is_active == True).scalar()  # noqa: E711
            total_with_pass = (
                session.query(func.count(User.id)).filter(User.is_active == True, User.password != None).scalar()  # noqa: E711
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
        start_utc, end_utc = local_day_bounds()
        with db_manager.get_session() as session:
            rows = (
                session.query(
                    sa_cast(AuditLog.action, String).label("action_str"),
                    sa_cast(AuditLog.status, String).label("status_str"),
                    func.count(AuditLog.id).label("count"),
                )
                .filter(
                    AuditLog.timestamp >= start_utc,
                    AuditLog.timestamp < end_utc,
                    sa_cast(AuditLog.action, String).in_(["in", "out", "checkin", "checkout"]),
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
        window_start = now_utc() - timedelta(hours=hours)
        with db_manager.get_session() as session:
            rows = (
                session.query(
                    sa_cast(AuditLog.action, String).label("action_str"),
                    sa_cast(AuditLog.status, String).label("status_str"),
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

    def has_successful_attendance_today(self, nip: str, action: str) -> bool:
        start_utc, end_utc = local_day_bounds()

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
            row = (
                session.query(AuditLog.id)
                .filter(
                    AuditLog.nip == nip,
                    sa_cast(AuditLog.action, String).in_(action_variants),
                    AuditLog.status.in_(["success", "ok"]),
                    AuditLog.timestamp >= start_utc,
                    AuditLog.timestamp < end_utc,
                )
                .first()
            )
            return row is not None
