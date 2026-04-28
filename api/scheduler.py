"""Attendance Scheduler — APScheduler 4.x async-native implementation.

Uses AsyncScheduler as an async context manager with CronTrigger
for per-user attendance scheduling.
"""

import logging
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler import AsyncScheduler  # type: ignore
from apscheduler.triggers.cron import CronTrigger  # type: ignore

from star_attendance.core.config import settings
from star_attendance.core.logging_config import configure_structlog
from star_attendance.core.options import RuntimeOptions
from star_attendance.core.processor import process_single_user
from star_attendance.core.timeutils import format_formal_timestamp
from star_attendance.database_manager import SupabaseManager, get_workday_cron

configure_structlog(settings.LOG_LEVEL)
logger = logging.getLogger("scheduler")


class AttendanceScheduler:
    def __init__(self, store: SupabaseManager):
        db_settings = store.get_settings()
        self.tz = self._resolve_timezone(db_settings.get("timezone"))
        self.store = store
        self.is_running = False
        self._scheduler: AsyncScheduler | None = None

    def _resolve_timezone(self, timezone_name: str | None) -> ZoneInfo:
        candidate = timezone_name or "Asia/Jakarta"
        try:
            return ZoneInfo(candidate)
        except ZoneInfoNotFoundError:
            logger.warning(f"Unknown timezone '{candidate}', falling back to Asia/Jakarta")
            return ZoneInfo("Asia/Jakarta")

    async def start(self):
        """Start the scheduler as an async context manager."""
        self._scheduler = AsyncScheduler()
        await self._scheduler.__aenter__()

        # Initial sync
        await self.sync_user_schedules()

        self.is_running = True
        logger.info("Star ASN Enterprise Scheduler Started (APScheduler 4.x)")

    async def stop(self):
        """Gracefully stop the scheduler."""
        if self._scheduler is not None:
            await self._scheduler.__aexit__(None, None, None)
            self._scheduler = None
            self.is_running = False

    async def sync_user_schedules(self):
        """
        Iterates through all database users and registers their personal cron schedules.
        """
        if self._scheduler is None:
            logger.error("Cannot sync schedules: scheduler not started.")
            return

        db_settings = self.store.get_settings()
        automation_enabled = bool(db_settings.get("automation_enabled", True))
        users = self.store.get_users_with_passwords() if automation_enabled else []
        logger.info(f"Syncing schedules for {len(users)} users in timezone {self.tz}...")

        # Track current schedule IDs to remove stale ones
        current_schedule_ids = set()

        for u in users:
            if not u.get("auto_attendance_active", False):
                logger.info(
                    "Skipping schedule for %s: %s",
                    u["nip"],
                    u.get("auto_attendance_reason", "auto attendance inactive"),
                )
                continue

            pin = u["nip"]
            cron_in = u.get("cron_in", "07:00")
            cron_out = u.get("cron_out", "18:00")
            day_of_week = get_workday_cron(u.get("workdays"))

            # Setup Personal IN
            schedule_id_in = f"user_{pin}_in"
            try:
                h, m = map(int, cron_in.split(":"))
                await self._scheduler.add_schedule(
                    self.dispatch_user_task,
                    CronTrigger(hour=h, minute=m, day_of_week=day_of_week),
                    args=[u, "in"],
                    id=schedule_id_in,
                    replace_existing=True,
                    misfire_grace_time=3600,
                    coalesce=True,
                )
                current_schedule_ids.add(schedule_id_in)
            except Exception as e:
                logger.error(f"Failed to schedule IN for {pin}: {e}")

            # Setup Personal OUT
            schedule_id_out = f"user_{pin}_out"
            try:
                h, m = map(int, cron_out.split(":"))
                await self._scheduler.add_schedule(
                    self.dispatch_user_task,
                    CronTrigger(hour=h, minute=m, day_of_week=day_of_week),
                    args=[u, "out"],
                    id=schedule_id_out,
                    replace_existing=True,
                    misfire_grace_time=3600,
                    coalesce=True,
                )
                current_schedule_ids.add(schedule_id_out)
            except Exception as e:
                logger.error(f"Failed to schedule OUT for {pin}: {e}")

        # Remove stale schedules
        for schedule in await self._scheduler.get_schedules():
            if schedule.id.startswith("user_") and schedule.id not in current_schedule_ids:
                await self._scheduler.remove_schedule(schedule.id)

        logger.info(f"Schedules synchronized. Total Active Schedules: {len(current_schedule_ids)}")

        # Log Heartbeat
        self.store.add_audit_log(
            nip="SYSTEM",
            action="scheduler_sync",
            status="ok",
            message=(
                "Scheduler automation disabled."
                if not automation_enabled
                else f"Sync Complete. Active personal schedules: {len(current_schedule_ids) // 2} personnel."
            ),
        )

    async def dispatch_user_task(self, user_data: dict, action: str):
        """
        Dispatches a single attendance task for a specific user.
        """
        db_settings = self.store.get_settings()
        if not db_settings.get("automation_enabled", True):
            logger.info("Skipping scheduler dispatch because automation is disabled.")
            return

        # Fresh user data from DB to ensure latest settings/password
        fresh_user = self.store.get_user_data(user_data["nip"])
        if not fresh_user:
            logger.error(f"Cannot dispatch task: User {user_data['nip']} not found in DB.")
            return

        options = RuntimeOptions.from_store(
            action=action,
            store=self.store,
            explain=True,
            dry_run=False,
            source="scheduler_auto",
        )

        # Create a worker task
        logger.info(f"Triggering personal {action.upper()} for {fresh_user['nip']}")

        # Define a status callback to send live updates to Telegram
        msg_id_container: dict[str, int | None] = {"id": None}
        tid = fresh_user.get("telegram_id")

        async def status_callback(status_msg: str):
            if tid:
                try:
                    from star_attendance.notifier import notifier

                    text = f"🤖 <b>OTOMASI {action.upper()}</b>\n────────────────\n🔄 {status_msg}"
                    if msg_id_container["id"] is None:
                        res = notifier.send_message_sync_get_id(text, to_admin=False, to_group=False)
                        if tid in res:
                            msg_id_container["id"] = res[tid]
                    else:
                        notifier.edit_message(tid, msg_id_container["id"], text)
                except Exception as e:
                    logger.warning(f"Failed to send status update to {tid}: {e}")

        await process_single_user(
            fresh_user,
            options,
            1,
            1,
            is_mass=False,
            status_callback=status_callback,
            user_message_id=msg_id_container["id"],
        )

    def get_jobs(self):
        """Synchronous job list (may be stale — use get_jobs_async for live data)."""
        return []

    async def get_jobs_async(self) -> list[dict[str, Any]]:
        """Get scheduled jobs asynchronously (APScheduler 4.x native)."""
        scheduler_tz = self._resolve_timezone(self.store.get_settings().get("timezone"))
        jobs: list[dict[str, Any]] = []

        if self._scheduler is None:
            return jobs

        for schedule in await self._scheduler.get_schedules():
            if not schedule.id.startswith("user_"):
                continue
            parts = schedule.id.split("_")
            nip = parts[1] if len(parts) >= 3 else None
            action = parts[2] if len(parts) >= 3 else None

            next_run_str = "N/A"
            try:
                if schedule.next_fire_time:
                    next_run_str = format_formal_timestamp(schedule.next_fire_time.astimezone(scheduler_tz))
            except Exception:
                pass

            jobs.append(
                {
                    "id": schedule.id,
                    "nip": nip,
                    "action": action,
                    "next_run": next_run_str,
                    "source": "user_cron",
                }
            )
        return jobs

    async def restart(self):
        await self.stop()
        await self.start()
        return await self.get_status_async()

    def get_status(self):
        """Synchronous status (may have stale job list)."""
        return {
            "running": self.is_running,
            "timezone": str(self._resolve_timezone(self.store.get_settings().get("timezone"))),
            "job_count": 0,
            "jobs": [],
        }

    async def get_status_async(self):
        """Async status with live job data."""
        jobs = await self.get_jobs_async()
        return {
            "running": self.is_running,
            "timezone": str(self._resolve_timezone(self.store.get_settings().get("timezone"))),
            "job_count": len(jobs),
            "jobs": jobs,
        }
