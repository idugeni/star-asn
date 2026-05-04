import html
import queue
import threading
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import psutil
import requests

from star_attendance.core.config import settings
from star_attendance.core.timeutils import format_formal_timestamp, format_precise_time


def as_datetime(value: Any) -> datetime | None:
    return value if isinstance(value, datetime) else None


def escape_text(value: Any, default: str = "-") -> str:
    raw = default if value in (None, "") else str(value)
    return html.escape(raw, quote=False)


def code(value: Any, default: str = "-") -> str:
    return f"<code>{escape_text(value, default)}</code>"


def action_label(action: str, *, automated: bool = False) -> str:
    normalized = str(action).lower()
    if normalized == "in":
        return "MASUK"
    if normalized == "out":
        return "KELUAR" if automated else "PULANG"
    return str(action).upper()


def status_meta(status: str) -> tuple[str, str]:
    normalized = str(status).lower()
    if normalized in {"success", "ok"}:
        return "✅", "BERHASIL"
    if normalized in {"skipped", "already_recorded", "already-success"}:
        return "ℹ️", "SUDAH TERCATAT"
    if normalized in {"duplicate", "deduplicated"}:
        return "⚠️", "PERMINTAAN DUPLIKAT"
    return "❌", "GAGAL"


def follow_up_message(status: str) -> str:
    normalized = str(status).lower()
    if normalized in {"success", "ok"}:
        return "Presensi berhasil diproses via Smart SSO (Tanpa Captcha)."
    if normalized in {"skipped", "already_recorded", "already-success"}:
        return "Absensi sudah pernah tercatat sebelumnya, jadi sistem tidak mengirim duplikasi."
    if normalized in {"duplicate", "deduplicated"}:
        return "Permintaan yang sama sedang diproses atau baru saja selesai."
    return "Silakan cek bot dan lakukan verifikasi manual bila diperlukan."


class TelegramNotifier:
    def __init__(self) -> None:
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.admin_id = str(settings.TELEGRAM_ADMIN_ID) if settings.TELEGRAM_ADMIN_ID else None
        self.log_group_id = settings.TELEGRAM_LOG_GROUP_ID
        self.is_active = bool(self.token)
        self.session = requests.Session()
        self.msg_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1000)
        self.worker_thread = threading.Thread(target=self.dispatch_worker, daemon=True)
        self.worker_thread.start()
        # Track last notification message per chat to avoid spam (keep only 1 latest)
        self._last_msg_ids: dict[int, int] = {}  # chat_id -> message_id

    def dispatch_worker(self) -> None:
        while True:
            item = self.msg_queue.get()
            if item is None:
                break
            try:
                msg = item["message"]
                chats = item["chat_ids"]
                is_silent = item.get("silent", False)
                self.send_now(msg, chats, silent=is_silent)
            finally:
                self.msg_queue.task_done()

    def send_now(self, message: str, chat_ids: Sequence[str | int], silent: bool = False) -> dict[int, int]:
        """Sends message immediately and returns {chat_id: message_id}"""
        if not self.is_active or not chat_ids:
            return {}

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        results: dict[int, int] = {}
        for chat_id in chat_ids:
            payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML", "disable_notification": silent}
            try:
                response = self.session.post(url, json=payload, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        msg_id = data["result"]["message_id"]
                        results[int(chat_id)] = msg_id
                        try:
                            if int(chat_id) > 0:
                                from star_attendance.runtime import get_store
                                store = get_store()
                                store.record_bot_message(telegram_id=int(chat_id), chat_id=int(chat_id), message_id=msg_id)
                        except Exception as e:
                            print(f"Failed to record notification message in DB: {e}")
                else:
                    print(f"Notification Error for {chat_id}: {response.status_code} - {response.text}")
            except Exception as exc:
                print(f"Notification Error for {chat_id}: {exc}")
        return results

    def edit_message(self, chat_id: int | str, message_id: int, new_text: str) -> bool:
        """Edits an existing message."""
        if not self.is_active:
            return False
        url = f"https://api.telegram.org/bot{self.token}/editMessageText"
        payload = {"chat_id": str(chat_id), "message_id": message_id, "text": new_text, "parse_mode": "HTML"}
        try:
            response = self.session.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as exc:
            print(f"Edit Message Error: {exc}")
            return False

    def delete_message(self, chat_id: int | str, message_id: int) -> bool:
        """Deletes an existing message."""
        if not self.is_active:
            return False
        url = f"https://api.telegram.org/bot{self.token}/deleteMessage"
        payload = {"chat_id": str(chat_id), "message_id": int(message_id)}
        try:
            response = self.session.post(url, json=payload, timeout=10)
            return response.status_code == 200
        except Exception as exc:
            print(f"Delete Message Error: {exc}")
            return False

    def send_message_sync_get_id(self, message: str, to_admin: bool = True, to_group: bool = True) -> dict[int, int]:
        """Sends message immediately and returns mapping of chat_id to message_id."""
        return self.send_now(message, self.resolve_targets(to_admin, to_group))

    def resolve_targets(self, to_admin: bool, to_group: bool) -> list[str]:
        targets: list[str] = []
        if to_admin and self.admin_id:
            targets.append(self.admin_id)
        if to_group and self.log_group_id:
            targets.append(self.log_group_id)
        return targets

    def enqueue_message(self, message: str, chat_ids: Sequence[str | int], silent: bool = False) -> bool:
        if not self.is_active:
            return False
        try:
            self.msg_queue.put_nowait({"message": message, "chat_ids": list(chat_ids), "silent": silent})
            return True
        except queue.Full:
            return bool(self.send_now(message, chat_ids, silent=silent))

    def send_message(self, message: str, to_admin: bool = True, to_group: bool = True, silent: bool = False) -> bool:
        return self.enqueue_message(message, self.resolve_targets(to_admin, to_group), silent=silent)

    def send_message_sync(
        self, message: str, to_admin: bool = True, to_group: bool = True, silent: bool = False
    ) -> bool:
        """Sends message immediately without queueing (blocking)."""
        return bool(self.send_now(message, self.resolve_targets(to_admin, to_group), silent=silent))

    def send_direct_message(self, chat_id: int | str | None, message: str, delete_after: int | None = None) -> bool:
        if chat_id in (None, ""):
            return False

        # If delete_after is provided, we send it sync to get the ID, then schedule deletion
        if delete_after and self.is_active:
            chat_id_str = str(chat_id)
            res = self.send_now(message, [chat_id_str])
            chat_id_int = int(chat_id_str)
            if res and chat_id_int in res:
                msg_id = res[chat_id_int]

                # Schedule deletion via a thread with proper error handling
                def del_task():
                    import logging
                    import time

                    _logger = logging.getLogger(__name__)
                    time.sleep(delete_after)
                    url = f"https://api.telegram.org/bot{self.token}/deleteMessage"
                    try:
                        resp = self.session.post(url, json={"chat_id": str(chat_id), "message_id": msg_id}, timeout=5)
                        if resp.status_code != 200:
                            _logger.debug(
                                f"Auto-delete failed for msg {msg_id} in chat {chat_id}: "
                                f"{resp.status_code} - {resp.text[:100]}"
                            )
                    except Exception as exc:
                        _logger.debug(f"Auto-delete error for msg {msg_id} in chat {chat_id}: {exc}")

                threading.Thread(target=del_task, daemon=True).start()
            return bool(res)

        return self.enqueue_message(message, [str(chat_id)])

    def format_attendance_msg(
        self,
        nip: str,
        name: str,
        action: str,
        status: str,
        duration: float = 0,
        *,
        recorded_at: datetime | None = None,
        telegram_id: int | str | None = None,
        detail: str | None = None,
        trace_id: str | None = None,
        event_time: datetime | None = None,
    ) -> str:
        timestamp = format_formal_timestamp(event_time)
        icon, status_text = status_meta(status)
        action_text = action_label(action, automated=False)

        # Determine Header Color Based on Status
        header_color = "🟢" if status.lower() in {"success", "ok"} else "🔴"
        if status.lower() in {"skipped", "duplicate"}:
            header_color = "🟡"

        lines = [
            f"<b>{header_color} STAR-ASN NOTIFIKASI TELEMETRI</b>",
            "────────────────",
            f"👤 <b>PERSONEL:</b> {escape_text(name, 'Tidak Diketahui')}",
            f"🆔 <b>NIP:</b> {code(nip)}",
            f"⚙️ <b>AKSI:</b> {action_text}",
            f"{icon} <b>STATUS:</b> {status_text}",
            "────────────────",
        ]

        if recorded_at is not None:
            from star_attendance.core.timeutils import format_formal_date

            lines.append(f"📅 <b>TANGGAL:</b> <code>{format_formal_date(recorded_at)}</code>")
            lines.append(f"⏰ <b>JAM ABSENSI:</b> <code>{format_precise_time(recorded_at)}</code>")

        lines.append(f"⏱ <b>DURASI:</b> <code>{duration:.2f}d</code>")

        if detail:
            lines.append(f"💬 <b>INFO:</b> {escape_text(detail)}")

        # System Telemetry Section
        try:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            lines.append(f"📊 <b>SISTEM:</b> <code>CPU {cpu}% | RAM {ram}%</code>")
        except Exception:
            pass

        if trace_id:
            lines.append(f"🧾 <b>ID PERMINTAAN:</b> {code(trace_id)}")

        lines.append("────────────────")
        return "\n".join(lines)

    def format_user_attendance_msg(
        self,
        nip: str,
        name: str,
        action: str,
        status: str,
        duration: float = 0,
        *,
        recorded_at: datetime | None = None,
        detail: str | None = None,
        event_time: datetime | None = None,
    ) -> str:
        timestamp = format_formal_timestamp(event_time)
        icon, status_text = status_meta(status)
        action_text = action_label(action, automated=True)

        # Friendly Tone for User Notif
        greeting = "Halo"
        from star_attendance.core.timeutils import now_local

        hour = now_local().hour
        if 0 <= hour < 5:
            greeting = "Selamat Dini Hari"
        elif 5 <= hour < 11:
            greeting = "Selamat Pagi"
        elif 11 <= hour < 15:
            greeting = "Selamat Siang"
        elif 15 <= hour < 18:
            greeting = "Selamat Sore"
        else:
            greeting = "Selamat Malam"

        label_text = action_label(action, automated=True)
        lines = [
            f"<b>{icon} STATUS PRESENSI {label_text}</b>",
            "────────────────",
            f"👤 {greeting}, <b>{escape_text(name, 'Tidak Diketahui')}</b>",
            "Laporan kehadiran Anda telah diproses via <b>Smart SSO</b>:",
            "",
            f"⚙️ <b>Aksi:</b> {action_text}",
            f"{icon} <b>Status:</b> {status_text}",
        ]

        if recorded_at is not None:
            from star_attendance.core.timeutils import format_formal_date

            lines.append(f"📅 <b>Tanggal:</b> <code>{format_formal_date(recorded_at)}</code>")
            lines.append(f"⏰ <b>Waktu:</b> <code>{format_precise_time(recorded_at)}</code>")

        lines.append(f"⏱ <b>Proses:</b> <code>{duration:.2f} detik</code>")

        # Detail with a cleaner approach
        info_text = detail or follow_up_message(status)
        lines.append(f"📝 <b>Keterangan:</b> <i>{escape_text(info_text)}</i>")

        lines.extend(
            [
                "────────────────",
            ]
        )

        # Optional: Add technical micro-telemetry for a premium feel
        try:
            cpu = psutil.cpu_percent(interval=None)
            ram = psutil.virtual_memory().percent
            lines.append(f"<b>📊 SISTEM:</b> <code>CPU {cpu}% | RAM {ram}% | ⚡ LIGHTNING FAST</code>")
        except:
            pass

        lines.append("<i>Asisten Digital Star-ASN Enterprise</i>")
        return "\n".join(lines)

    def format_debug_log(self, data: dict[str, Any]) -> str:
        status = data.get("status", "unknown")
        icon, status_text = status_meta(str(status))
        recorded_at = as_datetime(data.get("recorded_at"))
        event_time = as_datetime(data.get("event_time"))
        action_text = data.get("action_text") or action_label(str(data.get("action", "")), automated=False)
        detail = data.get("detail")
        lines = [
            f"<b>{icon} STAR-ASN KLUSTER LOGISTIK</b>",
            "────────────────",
            f"👤 <b>PENGGUNA:</b> {escape_text(data.get('name'), 'Tidak Diketahui')}",
            f"🆔 <b>NIP:</b> {code(data.get('nip'))}",
            f"🪪 <b>TELEGRAM ID:</b> {code(data.get('telegram_id'))}",
            f"⚙️ <b>AKSI:</b> {escape_text(action_text, '-')}",
            f"{icon} <b>STATUS:</b> {status_text}",
        ]
        if recorded_at is not None:
            from star_attendance.core.timeutils import format_formal_date

            lines.append(f"📅 <b>TANGGAL:</b> <code>{format_formal_date(recorded_at)}</code>")
            lines.append(f"⏰ <b>TERCATAT PADA:</b> <code>{format_precise_time(recorded_at)}</code>")
        if detail:
            lines.append(f"💬 <b>DETAIL:</b> {escape_text(detail)}")

        # Include accumulated logs if available
        logs = data.get("logs")
        if logs and isinstance(logs, list):
            lines.append("")
            for log_entry in logs:
                lines.append(f"<blockquote>{escape_text(log_entry)}</blockquote>")
        # Compact Metrics
        perf_metrics = (
            f"<code>📡 {data.get('public_ip', 'N/A')} | "
            f"🔐 {data.get('waf_status', 'AKTIF')} | "
            f"⚡ {float(data.get('duration', 0) or 0):.2f}s</code>"
        )
        lines.append("")
        lines.append(f"📊 <b>METRICS:</b> {perf_metrics}")
        lines.extend(
            [
                "",
                "📱 <b>IDENTITAS AGEN:</b>",
                f"  └ UA: <code>{escape_text(data.get('user_agent', 'N/A')[:50])}...</code>",
                "",
                f"🕒 <b>PENANDA WAKTU:</b> <code>{format_formal_timestamp(event_time)}</code>",
                "────────────────",
            ]
        )
        return "\n".join(lines)

    def send_mass_user_progress(
        self,
        nip: str,
        name: str,
        action: str,
        status: str,
        position: int,
        total: int,
    ) -> None:
        """Send per-user progress notification to the log group during mass attendance."""
        if not self.is_active or not self.log_group_id:
            return
        icon, status_text = status_meta(status)
        action_text = action_label(action, automated=False)
        label = "PRESENSI MASUK" if action.lower() == "in" else "PRESENSI PULANG"
        msg = (
            f"{icon} <b>MASS {label} [{position}/{total}]</b>\n"
            f"────────────────\n"
            f"👤 <b>PERSONEL:</b> {escape_text(name, 'Tidak Diketahui')}\n"
            f"🆔 <b>NIP:</b> {code(nip)}\n"
            f"⚙️ <b>AKSI:</b> {action_text}\n"
            f"{icon} <b>STATUS:</b> {status_text}\n"
            f"────────────────"
        )
        self.enqueue_message(msg, [self.log_group_id])

    def send_replace_message(self, chat_id: int | str, message: str) -> bool:
        """Send a message to a chat, replacing the previous one if it exists.
        Deletes the last notification message in this chat before sending a new one,
        so only the latest message is kept (no spam). Returns True if sent."""
        if not self.is_active:
            return False
        chat_id_int = int(chat_id)

        # Try to delete the previous message if it exists
        last_msg_id = self._last_msg_ids.get(chat_id_int)
        if last_msg_id:
            self.delete_message(chat_id_int, last_msg_id)
            del self._last_msg_ids[chat_id_int]

        # Send the new message synchronously to get the message_id
        res = self.send_now(message, [str(chat_id_int)])
        if chat_id_int in res:
            self._last_msg_ids[chat_id_int] = res[chat_id_int]
            return True
        return False

    def format_mass_completion_msg(
        self,
        action: str,
        processed: int,
        total: int,
        duration: float,
        is_aborted: bool = False,
    ) -> str:
        """Format mass attendance completion summary for the log group."""
        label = "PRESENSI MASUK" if action.lower() == "in" else "PRESENSI PULANG"
        status_icon = "🛑" if is_aborted else "✅"
        status_title = "DIBATALKAN" if is_aborted else "SELESAI"
        status_code = "EMERGENCY_STOP" if is_aborted else "SUCCESSFUL_SHUTDOWN"

        return (
            f"{status_icon} <b>MASS {label} {status_title}</b>\n"
            f"────────────────\n"
            f"📊 <b>Total Diproses:</b> <code>{processed} / {total}</code>\n"
            f"⏱ <b>Total Durasi:</b> <code>{duration:.1f}d</code>\n"
            f"────────────────\n"
            f"Status: <code>{status_code}</code>"
        )

    async def debug(self, title: str, message: str, debug_data: dict[Any, Any] | None = None) -> None:
        self.send_message(f"<b>{title}</b>\n{html.escape(message, quote=False)}", to_admin=True, to_group=True)

    def notify_attendance(
        self,
        nip: str,
        name: str,
        action: str,
        status: str,
        duration: float = 0,
        to_admin: bool = True,
        to_group: bool = True,
        to_user: bool = False,
        user_chat_id: int | str | None = None,
        user_message_id: int | None = None,
        debug_data: dict[Any, Any] | None = None,
        delete_after_user_msg: int | None = 60,
    ) -> None:
        payload = dict(debug_data or {})
        payload.update(
            {
                "nip": nip,
                "name": name,
                "duration": duration,
                "status": status,
                "telegram_id": payload.get("telegram_id") or user_chat_id,
            }
        )
        if "action_text" not in payload:
            payload["action_text"] = action_label(action)

        recorded_at = as_datetime(payload.get("recorded_at"))
        event_time = as_datetime(payload.get("event_time"))
        detail = payload.get("detail")
        trace_id = str(payload["request_key"]) if payload.get("request_key") not in (None, "") else None

        user_message = self.format_user_attendance_msg(
            nip,
            name,
            action,
            status,
            duration,
            recorded_at=recorded_at,
            detail=str(detail) if detail else None,
            event_time=event_time,
        )
        admin_message = self.format_attendance_msg(
            nip,
            name,
            action,
            status,
            duration,
            recorded_at=recorded_at,
            telegram_id=payload.get("telegram_id"),
            detail=str(detail) if detail else None,
            trace_id=trace_id,
            event_time=event_time,
        )

        # CONSOLIDATED: Send ONLY the detailed debug log to telemetry group
        # Smart Cleaner removed — deleting previous group messages is unsafe because:
        # 1. A stale/wrong message_id could delete unrelated messages
        # 2. In groups, deleted messages disappear for all members losing audit trail
        # 3. The bot may not have delete permissions in the group
        # Group messages are now kept as a persistent audit log.
        if to_group and self.log_group_id:
            try:
                # Debug logs to group are ALWAYS SILENT to prevent spam noise
                self.send_message(self.format_debug_log(payload), to_admin=False, to_group=True, silent=True)
            except Exception as e:
                print(f"Group notification error: {e}")

        if to_user and user_chat_id:
            if user_message_id:
                # If editing an existing message (Interactive), use the informative user message
                self.edit_message(user_chat_id, user_message_id, user_message)
            else:
                # Keep only the latest notification per user chat (delete previous, send new)
                self.send_replace_message(user_chat_id, user_message)

        # Convert both IDs to strings and strip whitespace to prevent any string/int mismatch
        user_id_str = str(user_chat_id).strip() if user_chat_id else ""
        admin_id_str = str(self.admin_id).strip() if self.admin_id else ""

        if to_admin and admin_id_str:
            # Skip if the target user is the admin themselves and they are already getting the user message
            if to_user and user_id_str == admin_id_str:
                pass
            else:
                self.send_replace_message(self.admin_id, admin_message)


notifier = TelegramNotifier()
