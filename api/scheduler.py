import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore
from apscheduler.triggers.cron import CronTrigger  # type: ignore

from star_attendance.core.config import settings

# Import core worker logic
from star_attendance.core.processor import process_single_user
from star_attendance.core.timeutils import format_formal_timestamp
from star_attendance.database_manager import SupabaseManager, get_workday_cron

logger = logging.getLogger("scheduler")
logger.setLevel(getattr(logging, settings.LOG_LEVEL))


class AttendanceScheduler:
    def __init__(self, store: SupabaseManager):
        self.scheduler = AsyncIOScheduler()
        self.store = store
        self.is_running = False

    def _resolve_timezone(self, timezone_name: str | None):
        candidate = timezone_name or "Asia/Jakarta"
        try:
            return ZoneInfo(candidate)
        except ZoneInfoNotFoundError:
            logger.warning(f"Unknown timezone '{candidate}', falling back to Asia/Jakarta")
            return ZoneInfo("Asia/Jakarta")

    async def start(self):
        if not self.scheduler.running:
            self.scheduler.start()

        # Initial sync
        await self.sync_user_schedules()

        self.is_running = True
        logger.info("Star ASN Enterprise Scheduler Started")

    async def sync_user_schedules(self):
        """
        Iterates through all database users and registers their personal cron jobs.
        """
        db_settings = self.store.get_settings()
        scheduler_tz = self._resolve_timezone(db_settings.get("timezone"))
        automation_enabled = bool(db_settings.get("automation_enabled", True))
        users = self.store.get_users_with_passwords() if automation_enabled else []
        logger.info(f"Syncing schedules for {len(users)} users in timezone {scheduler_tz}...")

        # Track current jobs to remove stale ones
        current_job_ids = set()

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
            job_id_in = f"user_{pin}_in"
            try:
                h, m = map(int, cron_in.split(":"))
                self.scheduler.add_job(
                    self.dispatch_user_task,
                    CronTrigger(hour=h, minute=m, day_of_week=day_of_week, timezone=scheduler_tz),
                    args=[u, "in"],
                    id=job_id_in,
                    replace_existing=True,
                )
                current_job_ids.add(job_id_in)
            except Exception as e:
                logger.error(f"Failed to schedule IN for {pin}: {e}")

            # Setup Personal OUT
            job_id_out = f"user_{pin}_out"
            try:
                h, m = map(int, cron_out.split(":"))
                self.scheduler.add_job(
                    self.dispatch_user_task,
                    CronTrigger(hour=h, minute=m, day_of_week=day_of_week, timezone=scheduler_tz),
                    args=[u, "out"],
                    id=job_id_out,
                    replace_existing=True,
                )
                current_job_ids.add(job_id_out)
            except Exception as e:
                logger.error(f"Failed to schedule OUT for {pin}: {e}")

        for job in list(self.scheduler.get_jobs()):
            if job.id.startswith("user_") and job.id not in current_job_ids:
                self.scheduler.remove_job(job.id)

        logger.info(f"Schedules synchronized. Total Active Jobs: {len(current_job_ids)}")

        # Log Heartbeat to group log
        self.store.add_audit_log(
            nip="SYSTEM",
            action="scheduler_sync",
            status="ok",
            message=(
                "Scheduler automation disabled."
                if not automation_enabled
                else f"Sync Complete. Active personal schedules: {len(current_job_ids) // 2} personnel."
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

        class Options:
            def __init__(self, d):
                for k, v in d.items():
                    setattr(self, k, v)

        options = Options(
            {
                "action": action,
                "explain": True,  # Enable process detail tracking
                "dry_run": False,
                "source": "scheduler_auto",
                "store": self.store,
            }
        )

        # Create a worker task
        logger.info(f"Triggering personal {action.upper()} for {fresh_user['nip']}")

        # Define a status callback to send live updates to Telegram
        msg_id_container = {"id": None}
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
        scheduler_tz = self._resolve_timezone(self.store.get_settings().get("timezone"))
        jobs = []
        # In APScheduler 3.x, job.next_run_time is the correct attribute.
        # However, it might be None if the job is not yet scheduled or the scheduler is stopped.
        for job in self.scheduler.get_jobs():
            if not job.id.startswith("user_"):
                continue
            parts = job.id.split("_")
            nip = parts[1] if len(parts) >= 3 else None
            action = parts[2] if len(parts) >= 3 else None

            next_run_str = "N/A"
            try:
                if hasattr(job, "next_run_time") and job.next_run_time:
                    next_run_str = format_formal_timestamp(job.next_run_time.astimezone(scheduler_tz))
            except Exception:
                pass

            jobs.append(
                {
                    "id": job.id,
                    "nip": nip,
                    "action": action,
                    "next_run": next_run_str,
                    "source": "user_cron",
                    "workdays": job.args[0].get("workdays_label", "-") if getattr(job, "args", None) else "-",
                }
            )
        return jobs

    async def restart(self):
        if not self.scheduler.running:
            self.scheduler.start()
        await self.sync_user_schedules()
        return self.get_status()

    def get_status(self):
        jobs = self.get_jobs()
        return {
            "running": self.scheduler.running,
            "timezone": str(self._resolve_timezone(self.store.get_settings().get("timezone"))),
            "job_count": len(jobs),
            "jobs": jobs,
        }
