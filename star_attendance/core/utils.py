import json
import queue
import threading
import time
from contextvars import ContextVar

from colorama import Fore, Style
from sqlalchemy import text

from star_attendance.core.config import settings
from star_attendance.core.timeutils import format_log_timestamp

# --- Global Helpers & Logging ---
# Some logging helpers call other helpers that also acquire this lock.
# RLock keeps those nested calls from deadlocking.
print_lock = threading.RLock()
# Use ContextVar instead of threading.local for asyncio compatibility
_worker_context: ContextVar[str] = ContextVar("worker_context", default="")
_log_collector: ContextVar[list[str] | None] = ContextVar("log_collector", default=None)
TELEGRAM_LOG_SCOPE_BLOCKLIST = frozenset({"AUTH"})


# --- Async Broadcast Manager ---
class LogBroadcastManager:
    """
    Manages non-blocking log broadcasts to PostgreSQL.
    Uses a background thread to process a queue.
    """

    def __init__(self):
        self.queue = queue.Queue(maxsize=1000)
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def _worker(self):
        try:
            # Lazy import to avoid circular dependency
            from star_attendance.db.manager import db_manager
            from star_attendance.notifier import notifier
        except Exception as e:
            print(f"FATAL: LogBroadcastManager worker failed to start: {e}")
            return

        while True:
            try:
                # Wait for log items
                item = self.queue.get()
                print(f"DEBUG: Processing log item: {item.get('level')} - {item.get('message')[:30]}...")
                if item is None:
                    break

                # Broadast to DB via pg_notify
                if settings.LOG_BROADCAST_ENABLED:
                    try:
                        with db_manager.get_session() as session:
                            session.execute(text("SELECT pg_notify('live_logs', :val)"), {"val": json.dumps(item)})
                    except Exception:
                        pass  # Silently fail if DB is busy or down

                # Broadcast to Telegram Log Group
                if should_broadcast_to_telegram(
                    level=str(item.get("level") or ""),
                    scope=str(item.get("scope") or ""),
                    skip_telegram=bool(item.get("skip_telegram")),
                ):
                    try:
                        log_msg = f"<b>[{item['level']}]</b> [{item['scope']}]\n{item['message']}"
                        notifier.send_message(log_msg, to_admin=False, to_group=True)
                    except Exception as e:
                        print(f"DEBUG: Telegram Broadcast Error: {e}")

                self.queue.task_done()
            except Exception:
                time.sleep(1)  # Safety backoff

    def broadcast(self, level, message, scope, timestamp):
        # If a collector is active, collect the log
        collector = _log_collector.get()
        if collector is not None and level in {"ERROR", "WARN", "SUCCESS"}:
            collector.append(f"[{timestamp}] {level}: {message}")
            # We still want to broadcast to DB, but skip Telegram individual messages
            # So we set a flag in the item
            skip_telegram = True
        else:
            skip_telegram = False

        try:
            # Non-blocking put
            self.queue.put_nowait(
                {
                    "timestamp": timestamp,
                    "level": level,
                    "scope": scope,
                    "message": message,
                    "skip_telegram": skip_telegram,
                }
            )
        except queue.Full:
            # If queue is full, we drop the broadcast to preserve app performance
            pass


# Initialize singleton
broadcast_manager = LogBroadcastManager()


def get_timestamp():
    return format_log_timestamp()


def should_broadcast_to_telegram(*, level: str, scope: str, skip_telegram: bool = False) -> bool:
    if skip_telegram or not settings.LOG_TELEGRAM_ENABLED:
        return False
    if level not in {"ERROR", "WARN", "SUCCESS"}:
        return False
    if str(scope).upper() in TELEGRAM_LOG_SCOPE_BLOCKLIST:
        return False
    return True


def set_context(context):
    _worker_context.set(str(context))


def clear_context():
    _worker_context.set("")


def start_log_collection():
    _log_collector.set([])


def stop_log_collection() -> list[str]:
    logs = _log_collector.get() or []
    _log_collector.set(None)
    return logs


def get_context_prefix():
    ctx = _worker_context.get()
    return f"ctx={ctx} " if ctx else ""


def print_sync(msg):
    with print_lock:
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:
            # Fallback for non-UTF8 consoles (e.g. Windows cmd/powershell with CP1252)
            try:
                print(str(msg).encode("ascii", "replace").decode("ascii"), flush=True)
            except Exception:
                pass


def format_info_line(level, msg, scope="CORE"):
    colors = {"INFO": Fore.BLUE, "WARN": Fore.YELLOW, "ERROR": Fore.RED, "SUCCESS": Fore.GREEN, "STEP": Fore.MAGENTA}
    color = colors.get(level, Fore.WHITE)
    return f"{Fore.CYAN}[{get_timestamp()}] {color}[{level}] {Fore.MAGENTA}[{scope}] {Style.RESET_ALL}{get_context_prefix()}{msg}"


def log(level, message, scope="SYSTEM"):
    timestamp = get_timestamp()
    log_line = f"[{timestamp}] [{level:7}] [{scope:10}] {message}"

    # Console output remains synchronous to preserve terminal order
    color = Fore.WHITE
    if level == "SUCCESS":
        color = Fore.GREEN
    elif level == "WARN":
        color = Fore.YELLOW
    elif level == "ERROR":
        color = Fore.RED
    elif level == "INFO":
        color = Fore.CYAN

    print_sync(f"{color}{log_line}{Style.RESET_ALL}")

    # Asynchronous broadcast to DB
    broadcast_manager.broadcast(level, message, scope, timestamp)


def info(msg, scope="CORE"):
    log("INFO", msg, scope)


def warning(msg, scope="CORE"):
    log("WARN", msg, scope)


def error(msg, scope="CORE"):
    log("ERROR", msg, scope)


def success(msg, scope="CORE"):
    log("SUCCESS", msg, scope)


def step(msg, scope="CORE"):
    log("STEP", msg, scope)


def info_with_header(header, msg, scope="CORE"):
    with print_lock:
        print_sync(f"{Fore.CYAN}{'-' * 60}{Style.RESET_ALL}")
        print_sync(header)
        print_sync(format_info_line("INFO", msg, scope))


def format_user_info(name, nip, upt, location):
    return (
        f" {Fore.WHITE} +------------------------------------------------------------+{Style.RESET_ALL}\n"
        f" {Fore.WHITE} | {Fore.WHITE}Nama      : {Fore.GREEN}{name:<46}{Fore.WHITE} |{Style.RESET_ALL}\n"
        f" {Fore.WHITE} | {Fore.WHITE}NIP       : {Fore.GREEN}{nip:<46}{Fore.WHITE} |{Style.RESET_ALL}\n"
        f" {Fore.WHITE} | {Fore.WHITE}Kantor    : {Fore.MAGENTA}{upt:<46}{Fore.WHITE} |{Style.RESET_ALL}\n"
        f" {Fore.WHITE} | {Fore.WHITE}GPS       : {Fore.BLUE}{location:<46}{Fore.WHITE} |{Style.RESET_ALL}\n"
        f" {Fore.WHITE} +------------------------------------------------------------+{Style.RESET_ALL}"
    )
