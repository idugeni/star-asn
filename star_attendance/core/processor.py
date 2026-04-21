import asyncio
import time
import uuid
from collections.abc import Callable, Coroutine, Mapping
from typing import Any

from colorama import Fore, Style

from star_attendance.core.config import settings
from star_attendance.core.engine import AttendanceEngine
from star_attendance.core.utils import (
    clear_context,
    format_user_info,
    info_with_header,
    log,
    print_sync,
    set_context,
    warning,
)
from star_attendance.notifier import notifier
from star_attendance.queueing import create_queue_pool, encode_queue_payload, require_queue_schema
from star_attendance.runtime import get_store


def _safe_last_success_record(store: Any, nip: str, action: str) -> tuple[Any | None, str | None]:
    record = store.get_last_success_action(nip, action)
    if isinstance(record, tuple):
        if len(record) >= 2:
            return record[0], record[1]
        if len(record) == 1:
            return record[0], None
    return None, None


async def process_single_user(
    user,
    options,
    position,
    total,
    is_mass=True,
    status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    user_message_id: int | dict[str, Any] | None = None,
):
    nip = user["nip"]
    action = options.action.lower()
    scope = action.upper()
    store = options.store if getattr(options, "store", None) else get_store()
    source = str(getattr(options, "source", None) or ("mass_worker" if is_mass else "api_manual"))
    request_key = str(getattr(options, "request_key", None) or uuid.uuid4())
    header: str | None = None
    full_msg: str | None = None
    raw_user_data = store.get_user_data(nip)
    user_data = raw_user_data if isinstance(raw_user_data, Mapping) else {}
    actual_name = str(user_data.get("nama") or user.get("nama") or "Unknown")
    user_chat_id = user.get("telegram_id") or user_data.get("telegram_id")

    if is_mass:
        name = actual_name
        upt = user_data.get("nama_upt") or "Unknown"
        latitude = user_data.get("latitude")
        longitude = user_data.get("longitude")
        location = f"{latitude},{longitude}" if latitude is not None and longitude is not None else "-"
        header = format_user_info(name, nip, upt, location)
        set_context(nip)
        info_with_header(
            header, f"event=start action={action} position={position} total={total} nip={nip}", scope=scope
        )
    else:
        log("INFO", f"event=start action={action} position={position} total={total} nip={nip}", scope=scope)

    # Execute Attendance with Retries
    start_time = time.perf_counter()
    retry_max = int(getattr(options, "round_retry_max", None) or settings.MASS_RETRY_MAX)
    retry_delay = float(settings.MASS_RETRY_DELAY)
    attempt = 0
    result = False
    last_error: str | None = None
    acquired_lock = False

    engine = AttendanceEngine(action=action, nip=nip, status_callback=status_callback)
    try:
        if store.has_successful_attendance_today(nip, action):
            recorded_at, _ = _safe_last_success_record(store, nip, action)
            store.add_audit_log(nip, action, "skipped", "Attendance already recorded successfully today.")

            # Formatted message for Admin/Logs
            full_msg = notifier.format_attendance_msg(
                nip,
                actual_name,
                action,
                "skipped",
                recorded_at=recorded_at,
                telegram_id=user_chat_id,
                detail=f"Absensi {action.upper()} untuk NIP {nip} sudah tercatat pada hari ini.",
                trace_id=request_key,
            )

            # Send notification to User if they have a Telegram ID
            if user_chat_id:
                notifier.notify_attendance(
                    nip,
                    actual_name,
                    action,
                    "skipped",
                    duration=0,
                    to_group=False,
                    to_admin=False,
                    to_user=True,
                    user_chat_id=user_chat_id,
                    debug_data={
                        "recorded_at": recorded_at,
                        "event_time": recorded_at,
                        "action": action,
                        "detail": f"Anda sudah melakukan {action.upper()} hari ini pada pukul {recorded_at.strftime('%H:%M:%S')}."
                        if recorded_at
                        else "Sudah tercatat.",
                    },
                )

            return False, full_msg

        acquired_lock = store.acquire_attendance_lock(nip, action, request_key, source)
        if not acquired_lock:
            store.add_audit_log(nip, action, "skipped", "Duplicate attendance request skipped by idempotency guard.")
            if not is_mass:
                full_msg = notifier.format_attendance_msg(
                    nip,
                    actual_name,
                    action,
                    "duplicate",
                    telegram_id=user_chat_id,
                    detail="Permintaan yang sama sedang diproses atau baru saja selesai. Silakan tunggu sebentar.",
                    trace_id=request_key,
                )
            return False, full_msg

        while attempt < retry_max and result is not True:
            attempt += 1
            try:
                password = user.get("password")
                login_res = await engine.switch_user(nip, password=str(password) if password else "")
                if login_res == "COMPLETED":
                    # Action already done in browser during WAF bridge
                    result = True
                    last_error = None
                elif login_res == "CIRCUIT_OPEN":
                    last_error = "Portal circuit breaker is open"
                    store.add_audit_log(nip, action, "failed", last_error)
                    result = False
                    break
                elif isinstance(login_res, str) and login_res.startswith("TERMINAL:"):
                    # Halt retries immediately for this user (Functional error)
                    last_error = login_res.split(":", 1)[1]
                    store.add_audit_log(nip, action, "failed", last_error)
                    result = False
                    break
                elif login_res is True:
                    result = await engine.execute_attendance(is_mass=is_mass, show_info=False)
                    if result:
                        last_error = ""
                    else:
                        last_error = str(last_error) if last_error else "Attendance submission failed"
                else:
                    if isinstance(login_res, dict):
                        last_error = login_res.get("message") or login_res.get("status") or str(login_res)
                    else:
                        last_error = str(login_res) if login_res else "Login gagal atau password tidak ditemukan"

                    store.add_audit_log(nip, action, "failed", last_error)
                    result = False
            except Exception as e:
                log("INFO", f"Attempt {attempt} failed: {e}", scope=scope)
                last_error = str(e)
                result = False

            if result is not True and attempt < retry_max:
                # Use INFO for retry messages
                log("INFO", f"event=retry action={action} attempt={attempt} max={retry_max}", scope=scope)
                await asyncio.sleep(retry_delay)
    finally:
        if acquired_lock:
            store.release_attendance_lock(request_key)
        await engine.client.close()
        if is_mass:
            print_sync(f"{Fore.CYAN}{'-' * 60}{Style.RESET_ALL}")
            clear_context()

    elapsed = time.perf_counter() - start_time
    log("INFO", f"event=end action={action} status={'OK' if result else 'FAIL'} duration={elapsed:.2f}s", scope=scope)

    should_notify = result or not is_mass or source == "scheduler_auto"
    if should_notify:
        actual_name = str(engine.user_info.get("nama") or actual_name)
        recorded_at = None
        if result:
            recorded_at, _ = _safe_last_success_record(store, nip, action)

        debug_data = {
            "action": action,
            "session_source": getattr(engine, "last_session_source", "NEW"),
            "attempts": getattr(engine, "last_attempts", 1),
            "captcha_code": getattr(engine, "last_captcha", "N/A"),
            "waf_status": getattr(engine, "last_waf_status", "ACTIVE"),
            "failure_stage": getattr(engine, "last_failure_stage", None),
            "public_ip": getattr(engine, "last_public_ip", "N/A"),
            "user_agent": getattr(engine, "last_user_agent", "N/A"),
            "source": source,
            "request_key": request_key,
            "recorded_at": recorded_at,
            "event_time": recorded_at,
            "detail": str(last_error) if not result else None,
            "telegram_id": user_chat_id,
            "logs": getattr(engine, "_accumulated_logs", []),
        }

        full_msg = notifier.format_attendance_msg(
            nip,
            actual_name,
            action,
            "success" if result else "failed",
            elapsed,
            recorded_at=recorded_at,
            telegram_id=user_chat_id,
            detail=str(last_error) if not result else None,
            trace_id=request_key,
            event_time=recorded_at,
        )

        # Resolve message ID if passed as container
        final_msg_id = user_message_id.get("id") if isinstance(user_message_id, dict) else user_message_id

        notifier.notify_attendance(
            nip,
            actual_name,
            action,
            "success" if result else "failed",
            duration=elapsed,
            to_group=True,
            to_admin=False,
            to_user=bool(user_chat_id),  # Always notify user if they are registered in bot
            user_chat_id=user_chat_id,
            user_message_id=final_msg_id,
            debug_data=debug_data,
        )

    if not result and last_error:
        store.record_dead_letter(
            request_key=request_key,
            nip=nip,
            action=action,
            payload={"nip": nip, "action": action, "source": source},
            reason="attendance_processing_failed",
            attempts=attempt,
            last_error=last_error,
        )
        if not full_msg and not is_mass:
            full_msg = notifier.format_attendance_msg(
                nip,
                actual_name,
                action,
                "failed",
                elapsed,
                telegram_id=user_chat_id,
                detail=last_error,
                trace_id=request_key,
            )

    return result, full_msg


async def mass_attendance(limit=None, options=None):
    store = options.store if getattr(options, "store", None) else get_store()
    options.store = store
    users = store.get_users_with_passwords()

    if limit:
        users = users[:limit]

    if not users:
        warning("Tidak ada personil terdaftar untuk absen masal.", scope=options.action.upper())
        return

    action = options.action
    scope = action.upper()

    print_sync(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    print_sync(f"{Fore.YELLOW}{' ' * 10}SUPABASE CLUSTER: DISPATCHING {scope} JOBS{' ' * 10}{Style.RESET_ALL}")
    print_sync(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
    mass_start = time.perf_counter()

    # --- "MASTER OF MASTER" PRIMING ---
    from star_attendance.login_handler import LoginHandler

    await LoginHandler.prime_waf_globally()

    pool = await create_queue_pool()
    queries = await require_queue_schema(pool)

    count = 0
    batch_size = 100
    try:
        for start in range(0, len(users), batch_size):
            if store.is_mass_stop_requested():
                warning(f"event=mass_abort action={action} message='Dispatch halted by stop signal'", scope=scope)
                break

            batch = users[start : start + batch_size]
            entrypoints = ["attendance.process"] * len(batch)
            payloads = [
                encode_queue_payload(
                    {
                        "nip": user["nip"],
                        "action": action,
                        "request_key": str(uuid.uuid4()),
                        "source": "mass_dispatch",
                    }
                )
                for user in batch
            ]
            priorities = [0] * len(batch)
            await queries.enqueue(entrypoints, payloads, priorities)
            count += len(batch)

            # Update live status after each batch dispatch.
            status_data = {
                "active": "1",
                "action": action,
                "pos": str(count),
                "total": str(len(users)),
                "last_nip": batch[-1]["nip"],
                "start_time": str(mass_start),
            }
            store.update_mass_status(status_data)
    finally:
        store.update_mass_status(
            {
                "active": "0",
                "action": action,
                "pos": str(count),
                "total": str(len(users)),
            }
        )
        await pool.close()

    # Log mass orchestration summary to audit log
    store.add_audit_log(
        nip="SYSTEM",
        action=f"mass_{action}",
        status="ok",
        message=f"Mass {action.upper()} Dispatched. Total Personnel: {count} workers enqueued.",
    )

    print_sync(
        f"\n{Fore.GREEN}[SUCCESS] Postgres dispatch complete. Workers are processing independently.{Style.RESET_ALL}\n"
    )
    return {"queued": count}
