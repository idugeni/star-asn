import asyncio
import json
import time
import traceback
from collections import OrderedDict
from collections.abc import Callable, Coroutine, Mapping
from typing import Any, cast

from bs4 import BeautifulSoup
from colorama import Fore, Style
from curl_cffi.requests import AsyncSession  # type: ignore

from star_attendance.core.config import settings
from star_attendance.core.timeutils import isoformat_local
from star_attendance.core.utils import (
    error,
    format_user_info,
    info,
    print_sync,
    set_context,
    start_log_collection,
    step,
    stop_log_collection,
    success,
    warning,
)
from star_attendance.login_handler import CookieData, LoginHandler, MASTER_IDENTITY_HEADERS, MASTER_IDENTITY_UA
from star_attendance.runtime import get_store


class AttendanceEngine:
    def __init__(
        self,
        nip=None,
        action="in",
        location=None,
        store=None,
        proxy=None,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    ):
        self.action = (action or "in").lower()  # "in" or "out"
        self.scope = self.action.upper()
        self.store = store or get_store()
        self.nip = nip
        self.proxy = proxy
        self.status_callback = status_callback
        self.base_url = "https://star-asn.kemenimipas.go.id"

        runtime_settings = self.store.get_settings()
        default_latitude = runtime_settings.get("default_latitude", -7.3995103268718365)
        default_longitude = runtime_settings.get("default_longitude", 109.8895225210264)

        # Default coordinates if user/UPT coordinates are unavailable.
        self.location = f"{default_latitude},{default_longitude}"
        self.timezone = str(runtime_settings.get("timezone", "Asia/Jakarta"))

        self.client: Any = AsyncSession(
            impersonate="chrome120",
            verify=False,
            timeout=20,
            proxies={"http": self.proxy, "https": self.proxy} if self.proxy else None,
        )

        # Master Identity Synchronization
        self.user_agent = MASTER_IDENTITY_UA
        self.headers = MASTER_IDENTITY_HEADERS
        self.client.headers.update(self.headers)

        # Initialize LoginHandler with matching identity and proxy
        self.login_handler = LoginHandler(
            base_url=self.base_url,
            user_agent=self.user_agent,
            proxy=self.proxy
        )

        self.user_info = {"nama": "Unknown", "nip": self.nip, "upt": "Unknown"}
        self.last_response_time = 0.0
        self.active_password = None
        self.csrf_token = None
        self._accumulated_logs: list[str] = []
        self.last_session_source = "NEW"
        self.last_attempts = 0
        self.last_captcha = "N/A"
        self.last_waf_status = "ACTIVE"
        self.last_public_ip = "N/A"
        self.last_user_agent = self.user_agent
        self.last_failure_stage: str | None = None

    def _apply_cookies(self, cookies: Any) -> None:
        if not cookies:
            return
        if isinstance(cookies, Mapping):
            self.client.cookies.update(dict(cookies))
            return
        if isinstance(cookies, list):
            # --- "MASTER OF MASTER" INJECTION ---
            if LoginHandler._waf_cookies and isinstance(LoginHandler._waf_cookies, list):
                for c in LoginHandler._waf_cookies:
                    if not isinstance(c, dict):
                        continue
                    cookie = cast(CookieData, c)
                    try:
                        self.client.cookies.set(
                            cookie["name"],
                            cookie["value"],
                            domain=cookie.get("domain", "star-asn.kemenimipas.go.id"),
                            path=cookie.get("path", "/"),
                        )
                    except Exception:
                        continue
            for cookie in cookies:
                if not isinstance(cookie, Mapping):
                    continue
                name = cookie.get("name")
                value = cookie.get("value")
                if not name or value is None:
                    continue
                domain = cookie.get("domain")
                path = cookie.get("path", "/")
                if domain:
                    self.client.cookies.set(name, value, domain=domain, path=path)
                else:
                    self.client.cookies.set(name, value, path=path)
            return
        raise TypeError(f"Unsupported cookie payload type: {type(cookies).__name__}")

    async def perform_login(self, username, password):
        """Perform login with session fallback and action passing for session continuity"""
        start_log_collection()
        set_context(username)
        if self.status_callback:
            await self.status_callback("🔍 Mencari sesi yang tersedia...")

        try:
            # 1. Try to use saved session from manual login
            saved_session = self.store.get_user_session(username)
            if saved_session and "cookies" in saved_session:
                info(
                    f"Ditemukan sesi tersimpan (captured: {saved_session.get('captured_at', 'unknown')}). Mencoba resume...",
                    scope=self.scope,
                )
                self.client.cookies.update(saved_session["cookies"])
                if saved_session.get("user_agent"):
                    self.user_agent = saved_session["user_agent"]
                    self.client.headers["User-Agent"] = self.user_agent

                # Verify if still valid
                if await self.fetch_user_profile():
                    success(f"Berhasil resume sesi manual for {username}.", scope=self.scope)
                    self._accumulated_logs = stop_log_collection()
                    return True
                else:
                    warning("Sesi tersimpan tidak valid atau expired. Mencoba login otomatis...", scope=self.scope)
                    self.client.cookies.clear()
                    self.store.delete_user_session(username)

            # 2. Automated login fallback (Passing action/location for Browser Session Continuity)
            info(f"Mencoba login otomatis untuk {username}...", scope=self.scope)
            login_result = await self.login_handler.login(
                username, password, action=self.action, location=self.location, status_callback=self.status_callback
            )

            if login_result and "cookies" in login_result:
                self.last_failure_stage = login_result.get("failure_stage")
                self.last_session_source = login_result.get("session_source", "NEW")
                self.last_attempts = login_result.get("attempts", 1)
                self.last_captcha = login_result.get("captcha_code", "N/A")
                self.last_waf_status = login_result.get("waf_status", "ACTIVE")
                self.last_public_ip = login_result.get("public_ip", "N/A")
                self.last_user_agent = login_result.get("user_agent", self.user_agent)
                self._apply_cookies(login_result["cookies"])
                self.last_response_time = login_result.get("response_time", 0.0)

                # Check if attendance was already done via Browser Bridge
                if login_result.get("attendance_result") is True:
                    self.store.save_user_session(
                        username,
                        {
                            "cookies": self.client.cookies.get_dict(),
                            "captured_at": isoformat_local(),
                            "user_agent": self.user_agent,
                        },
                    )
                    self._accumulated_logs = stop_log_collection()
                    return "COMPLETED"

                # Verify after login
                if await self.fetch_user_profile():
                    self.store.save_user_session(
                        username,
                        {
                            "cookies": self.client.cookies.get_dict(),
                            "captured_at": isoformat_local(),
                            "user_agent": self.user_agent,
                        },
                    )
                    success(f"Login otomatis berhasil ({self.last_response_time:.2f}s).", scope=self.scope)
                    self._accumulated_logs = stop_log_collection()
                    return True
                else:
                    self.last_failure_stage = "dashboard_unreachable"
                    if login_result.get("session_source") == "PERSISTENT":
                        warning(
                            f"Deteksi sesi PERSISTENT untuk {username} tidak valid. Membersihkan cookies...",
                            scope=self.scope,
                        )
                        self.client.cookies.clear()
                        self.store.delete_user_session(username)
            elif login_result and login_result.get("status") == "circuit_open":
                self.last_failure_stage = login_result.get("failure_stage")
                warning("Portal circuit breaker sedang aktif. Menunda percobaan login.", scope=self.scope)
                self._accumulated_logs = stop_log_collection()
                return "CIRCUIT_OPEN"

            failure_msg = login_result.get("message") if login_result else "Unknown login failure"
            if login_result and login_result.get("status") == "success":
                failure_msg = "Dashboard tidak bisa diverifikasi setelah login."
            error(f"Gagal login untuk {username}: {failure_msg}", scope=self.scope)
            self._accumulated_logs = stop_log_collection()
            return failure_msg
        except Exception as e:
            self._accumulated_logs = stop_log_collection()
            raise e

    async def switch_user(self, nip, password=None):
        """Switch active user and login immediately with session hardening"""
        start_log_collection()
        self.nip = nip
        self.user_info = {"nama": "Guest", "nip": self.nip, "upt": "Guest Identity"}
        self.client.cookies.clear()

        try:
            user_data = self.store.get_user_data(self.nip) or {}
            active_password = password or user_data.get("password")

            if not active_password:
                msg = f"Password untuk {self.nip} tidak ditemukan (DB/Input)."
                warning(msg, scope=self.scope)
                self._accumulated_logs = stop_log_collection()
                return msg

            if user_data:
                if user_data.get("nama"):
                    self.user_info["nama"] = user_data["nama"]
                if user_data.get("nama_upt"):
                    self.user_info["upt"] = user_data["nama_upt"]
                if user_data.get("latitude") is not None and user_data.get("longitude") is not None:
                    self.location = f"{user_data['latitude']},{user_data['longitude']}"

            self.active_password = active_password

            # 1. Try saved manual session first
            saved_session = self.store.get_user_session(self.nip)
            if saved_session and saved_session.get("cookies"):
                try:
                    self.client.cookies.update(saved_session["cookies"])
                    if saved_session.get("user_agent"):
                        self.user_agent = saved_session["user_agent"]
                        self.client.headers["User-Agent"] = self.user_agent
                    if await self.fetch_user_profile():
                        success(f"Berhasil resume sesi manual untuk {self.nip}.", scope=self.scope)
                        self.last_session_source = "MANUAL-SESSION"
                        self.last_waf_status = "BYPASSED"
                        self._accumulated_logs = stop_log_collection()
                        return True
                    else:
                        warning(
                            f"Sesi tersimpan untuk {self.nip} sudah tidak valid. Membersihkan cookies...",
                            scope=self.scope,
                        )
                        self.client.cookies.clear()
                        self.store.delete_user_session(self.nip)
                except Exception as e:
                    warning(f"Gagal memproses sesi tersimpan: {e}", scope=self.scope)
                    self.client.cookies.clear()

            # 2. Automated login fallback (Passing action and location for full browser session bypass)
            info(f"Mencoba login otomatis untuk {self.nip}...", scope=self.scope)
            login_result = await self.login_handler.login(
                self.nip,
                active_password,
                action=self.action,
                location=self.location,
                status_callback=self.status_callback,
            )

            if login_result:
                if login_result.get("status") == "terminal":
                    msg = login_result.get("message") or "Terminal login failure"
                    error(f"KEGAGALAN TERMINAL: {msg}", scope=self.scope)
                    self._accumulated_logs = stop_log_collection()
                    return f"TERMINAL:{msg}"
                if login_result.get("status") == "circuit_open":
                    warning("Portal circuit breaker sedang aktif. Menunda percobaan login.", scope=self.scope)
                    self._accumulated_logs = stop_log_collection()
                    return "CIRCUIT_OPEN"

                if login_result and "cookies" in login_result:
                    cookies = login_result["cookies"]
                    if cookies and isinstance(cookies, list):
                        self._session_source = "BRIDGE"
                        LoginHandler.cache_shared_waf_cookies(cast(list[CookieData], cookies))
                        for c in LoginHandler._waf_cookies or []:
                            if not isinstance(c, dict):
                                continue
                            cookie = cast(CookieData, c)
                            try:
                                self.client.cookies.set(
                                    cookie["name"],
                                    cookie["value"],
                                    domain=cookie.get("domain", "star-asn.kemenimipas.go.id"),
                                    path=cookie.get("path", "/"),
                                )
                            except Exception:
                                continue
                    self._apply_cookies(login_result["cookies"])
                    self.last_response_time = login_result.get("response_time", 0.0)

                    # MAP TECHNICAL INDICATORS FOR TELEMETRY
                    self.last_session_source = login_result.get("session_source", "NEW")
                    self.last_attempts = login_result.get("attempts", 1)
                    self.last_captcha = login_result.get("captcha_code", "N/A")
                    self.last_waf_status = login_result.get("waf_status", "ACTIVE")
                    self.last_public_ip = login_result.get("public_ip", "N/A")
                    self.last_user_agent = login_result.get("user_agent", self.user_agent)
                    self.last_failure_stage = login_result.get("failure_stage")

                    # THE "SUCCESS TOTAL" SHORTCUT
                    if login_result.get("attendance_result") is True:
                        # Specific source for browser bypass
                        self.last_session_source = "BRIDGE-NATIVE"
                        self.last_waf_status = "BYPASSED"
                        self.last_public_ip = login_result.get("public_ip", "N/A")
                        self.last_user_agent = login_result.get("user_agent", self.user_agent)
                        self.store.save_user_session(
                            self.nip,
                            {
                                "cookies": self.client.cookies.get_dict(),
                                "captured_at": isoformat_local(),
                                "user_agent": self.user_agent,
                            },
                        )
                        success(
                            f"Absensi {self.action.upper()} diselesaikan via Browser Session (Bypass).",
                            scope=self.scope,
                        )
                        self._accumulated_logs = stop_log_collection()
                        return "COMPLETED"

                    if await self.fetch_user_profile():
                        self.store.save_user_session(
                            self.nip,
                            {
                                "cookies": self.client.cookies.get_dict(),
                                "captured_at": isoformat_local(),
                                "user_agent": self.user_agent,
                            },
                        )
                        success(f"Login otomatis berhasil ({self.last_response_time:.2f}s).", scope=self.scope)
                        self._accumulated_logs = stop_log_collection()
                        return True
                    self.last_failure_stage = "dashboard_unreachable"

            failure_msg = login_result.get("message") if login_result else "Unknown login failure"
            if login_result and login_result.get("status") == "success":
                failure_msg = "Dashboard tidak bisa diverifikasi setelah login."
            error(f"Gagal login untuk {self.nip}: {failure_msg}", scope=self.scope)
            self._accumulated_logs = stop_log_collection()
            return failure_msg
        except Exception as e:
            self._accumulated_logs = stop_log_collection()
            raise e

    async def fetch_user_profile(self):
        """Fetch full profile info for dashboard and update DB"""
        try:
            resp = await self.client.get(f"{self.base_url}/home/dashboard")

            if "login" in str(resp.url).lower() or "<title>Login" in resp.text:
                error("Sesi tidak valid (diarahkan ke login).", scope=self.scope)
                self.csrf_token = None
                return False

            soup = BeautifulSoup(resp.text, "html.parser")

            # Extract name
            name_el = soup.find("span", class_="user-name-text")
            if name_el:
                self.user_info["nama"] = name_el.get_text().strip()
                self.store.update_user_settings(self.nip, {"nama": self.user_info["nama"]})

            # Extract UPT (Office)
            upt_el = soup.find("span", class_="user-role-text")
            if upt_el:
                self.user_info["upt"] = upt_el.get_text().strip()

            if not name_el:
                error("Nama user tidak ditemukan di dashboard.", scope=self.scope)
                return False

            # Extract CSRF token (KV-TOKEN)
            csrf_meta = soup.find("meta", {"name": "csrf-token"})
            if csrf_meta:
                self.csrf_token = csrf_meta.get("content")
            else:
                error("CSRF Token tidak ditemukan di dashboard.", scope=self.scope)
                self.csrf_token = None
                return False

            return True
        except Exception as e:
            error(f"Gagal fetch dashboard: {e}", scope=self.scope)
            return False

    async def execute_attendance(self, is_mass=False, show_info=True):
        start_log_collection()
        if not is_mass:
            title = "ABSEN MASUK (Check In)" if self.action == "in" else "ABSEN PULANG (Check Out)"
            print_sync(f"\n{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")
            print_sync(
                f"{Fore.YELLOW}{' ' * ((60 - len(title)) // 2)}{title}{' ' * ((60 - len(title)) // 2)}{Style.RESET_ALL}"
            )
            print_sync(f"{Fore.CYAN}{'=' * 60}{Style.RESET_ALL}")

        # switch_user already logged in, so here we just execute
        if not self.user_info.get("nama") or self.user_info["nama"] == "Unknown":
            if not await self.fetch_user_profile():
                error("Gagal mengambil data profil.", scope=self.scope)
                self._accumulated_logs = stop_log_collection()
                return False

        if self.status_callback:
            await self.status_callback(f"🚀 Memasuki Dashboard {settings.BOT_NAME}...")

        if show_info:
            print_info = format_user_info(
                self.user_info["nama"], self.user_info["nip"], self.user_info["upt"], self.location
            )
            print_sync(print_info)

        result = False
        try:
            # Re-fetch dashboard or use existing soup to check status
            if self.store.is_mass_stop_requested():
                warning(f"Stop signal received. Aborting for {self.nip}", scope=self.scope)
                self._accumulated_logs = stop_log_collection()
                return False

            soup = None
            for attempt in range(2):
                if self.store.is_mass_stop_requested():
                    self._accumulated_logs = stop_log_collection()
                    return False
                resp = await self.client.get(f"{self.base_url}/home/dashboard")
                if resp.status_code == 429:
                    error("Error 429: Too Many Requests. Menunggu 30 detik...", scope=self.scope)
                    await asyncio.sleep(30)
                    continue
                if "login" in str(resp.url).lower() or "<title>Login" in resp.text:
                    if self.active_password and await self.perform_login(self.nip, self.active_password):
                        continue
                    error("Sesi tidak valid (diarahkan ke login).", scope=self.scope)
                    self.store.add_audit_log(self.nip, self.action, "failed", "Sesi tidak valid (login)")
                    self._accumulated_logs = stop_log_collection()
                    return False
                if resp.status_code >= 500:
                    await asyncio.sleep(1.5)
                    continue
                soup = BeautifulSoup(resp.text, "html.parser")
                break
            if soup is None:
                error("Gagal memuat dashboard.", scope=self.scope)
                self.store.add_audit_log(self.nip, self.action, "failed", "Gagal memuat dashboard")
                self._accumulated_logs = stop_log_collection()
                return False

            # Determine button ID based on action
            btn_id = "presence-in" if self.action == "in" else "presence-out"
            btn_presence = soup.find("button", id=btn_id)

            if btn_presence and "disabled" in btn_presence.attrs:
                status_text = btn_presence.find("h5")
                time_text = status_text.get_text(strip=True) if status_text else "Sudah Terdata"
                action_text = "MASUK" if self.action == "in" else "PULANG"
                success(f"STATUS: SUDAH ABSEN {action_text} ({time_text})", scope=self.scope)
                self.store.add_audit_log(self.nip, self.action, "success", f"Sudah absen {self.action}: {time_text}")
                result = True
            else:
                if not self.csrf_token:
                    if not await self.fetch_user_profile():
                        error("CSRF Token tidak ditemukan.", scope=self.scope)
                        self.store.add_audit_log(self.nip, self.action, "failed", "CSRF Token tidak ditemukan")
                        self._accumulated_logs = stop_log_collection()
                        return False

                payload = {
                    "location": self.location,
                    "timezone": self.timezone,
                    "type": self.action,  # "in" or "out"
                }

                ajax_headers = OrderedDict(
                    [
                        ("User-Agent", self.user_agent),
                        ("Accept", "*/*"),
                        ("Accept-Language", "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7"),
                        ("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8"),
                        ("X-Requested-With", "XMLHttpRequest"),
                        ("KV-TOKEN", str(self.csrf_token)),
                        ("Sec-Ch-Ua", '"Google Chrome";v="131", "Chromium";v="131", "Not_A Brand";v="24"'),
                        ("Sec-Ch-Ua-Mobile", "?0"),
                        ("Sec-Ch-Ua-Platform", '"Windows"'),
                        ("Origin", self.base_url),
                        ("Sec-Fetch-Site", "same-origin"),
                        ("Sec-Fetch-Mode", "cors"),
                        ("Sec-Fetch-Dest", "empty"),
                        ("Referer", f"{self.base_url}/home/dashboard"),
                        ("Connection", "keep-alive"),
                    ]
                )

                step(
                    f"Submitting presence ({self.action.upper()}) to {self.base_url}/attendance/presence...",
                    scope=self.scope,
                )

                if self.status_callback:
                    await self.status_callback("📡 Mengirim data kehadiran ke server...")

                submit_attempts = 0
                relogged = False
                last_error = None
                presence_response_time = None
                while submit_attempts < 2:
                    start_pos_time = time.time()
                    try:
                        post_resp = await asyncio.wait_for(
                            self.client.post(
                                f"{self.base_url}/attendance/presence",
                                data=payload,
                                headers=ajax_headers,
                                allow_redirects=False,
                            ),
                            timeout=30.0,
                        )
                    except TimeoutError:
                        last_error = "Timeout submitting attendance (30s)"
                        error(last_error, scope=self.scope)
                        submit_attempts += 1
                        await asyncio.sleep(2)
                        continue
                    presence_response_time = time.time() - start_pos_time

                    if post_resp.status_code == 429:
                        last_error = "Error 429: Too Many Requests"
                        error("Error 429: Too Many Requests. Menunggu 30 detik...", scope=self.scope)
                        await asyncio.sleep(30)
                        submit_attempts += 1
                        continue

                    if post_resp.status_code in [302, 303]:
                        redirect_url = post_resp.headers.get("Location", "")
                        warning(f"Redirected ({post_resp.status_code}) to: {redirect_url}", scope=self.scope)
                        if "login" in redirect_url.lower():
                            if (
                                self.active_password
                                and not relogged
                                and await self.perform_login(self.nip, self.active_password)
                            ):
                                relogged = True
                                submit_attempts += 1
                                continue
                            else:
                                last_error = "Session expired (redirect to login)"
                                break

                    if post_resp.status_code == 200:
                        try:
                            json_resp = post_resp.json()
                            if json_resp and (
                                json_resp.get("status") == "success" or "berhasil" in str(json_resp).lower()
                            ):
                                success(f"ABSEN {self.action.upper()} BERHASIL! Resp: {json_resp}", scope=self.scope)
                                self.store.add_audit_log(
                                    self.nip, self.action, "success", "Berhasil submit absen", presence_response_time
                                )
                                result = True
                                break
                            else:
                                last_error = f"API Error: {json_resp}"
                                error(f"Gagal absen: {json_resp}", scope=self.scope)
                        except json.JSONDecodeError:
                            # Check if HTML response indicates success
                            if "berhasil" in post_resp.text.lower():
                                # 1. Inject Global WAF context if available
                                if LoginHandler._waf_cookies and isinstance(LoginHandler._waf_cookies, list):
                                    for c in LoginHandler._waf_cookies:
                                        if not isinstance(c, dict):
                                            continue
                                        cookie = cast(CookieData, c)
                                        try:
                                            self.client.cookies.set(
                                                cookie["name"],
                                                cookie["value"],
                                                domain=cookie.get("domain", "star-asn.kemenimipas.go.id"),
                                                path=cookie.get("path", "/"),
                                            )
                                        except Exception:
                                            continue
                                success(f"ABSEN {self.action.upper()} BERHASIL (HTML Resp)!", scope=self.scope)
                                self.store.add_audit_log(
                                    self.nip,
                                    self.action,
                                    "success",
                                    "Berhasil submit (HTML detected)",
                                    presence_response_time,
                                )
                                result = True
                                break
                            last_error = f"Invalid JSON response (Code: {post_resp.status_code})"
                            error(f"Response bukan JSON: {post_resp.text[:100]}", scope=self.scope)
                    else:
                        last_error = f"HTTP Error {post_resp.status_code}"
                        error(f"HTTP Error {post_resp.status_code}: {post_resp.text[:100]}", scope=self.scope)

                    submit_attempts += 1
                    await asyncio.sleep(1)

                if not result:
                    self.store.add_audit_log(
                        self.nip, self.action, "failed", last_error or "Unknown error", presence_response_time
                    )

        except Exception as e:
            error(f"Exception during execute_attendance: {e}", scope=self.scope)
            traceback.print_exc()
            self.store.add_audit_log(self.nip, self.action, "failed", f"Exception: {str(e)}")
            self._accumulated_logs = stop_log_collection()
            return False

        self._accumulated_logs = stop_log_collection()
        return result
