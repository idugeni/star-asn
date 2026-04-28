import asyncio
import threading
import time
import warnings
import uuid
import os
import re
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from datetime import datetime
from typing import Any, TypedDict, cast

import cv2
import PIL.Image
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS # type: ignore

# DDDDOCR is our primary engine
import ddddocr  # type: ignore
import numpy as np
from colorama import Fore, Style, init
from curl_cffi.requests import AsyncSession  # type: ignore

from star_attendance.core.config import settings
from star_attendance.core.resilience import browser_bridge_semaphore, portal_circuit_breaker
from star_attendance.core.timeutils import format_log_timestamp

HAS_DDDDOCR = True

# Setup awal
init(autoreset=True)
warnings.filterwarnings("ignore", message=".*pin_memory.*", category=UserWarning)
print_lock = threading.Lock()
# Use ContextVar instead of threading.local for asyncio compatibility
_auth_context: ContextVar[str] = ContextVar("auth_context", default="")
LOG_SCOPE = "AUTH"


class CookieData(TypedDict):
    name: str
    value: str
    domain: str
    path: str


# --- HELPER FUNCTIONS ---


def get_timestamp() -> str:
    return format_log_timestamp()


def set_context(context: Any) -> None:
    _auth_context.set(str(context))


def clear_context() -> None:
    _auth_context.set("")


def get_context_prefix() -> str:
    ctx = _auth_context.get()
    return f"ctx={ctx} " if ctx else ""


TKV_REGEX = re.compile(r'name="tkv" value="([^"]+)"')
CSRF_REGEX = re.compile(r'name="csrf-token" content="([^"]+)"')
USER_NAME_REGEX = re.compile(r'class="user-name-text">([^<]+)<')


MASTER_IDENTITY_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
MASTER_IDENTITY_HEADERS = {
    "User-Agent": MASTER_IDENTITY_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "DNT": "1",
    "Sec-Ch-Ua": '"Google Chrome";v="147", "Chromium";v="147", "Not.A/Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Connection": "keep-alive",
}


from star_attendance.core.utils import log as core_log, set_context as core_set_context

def log(level: str, msg: str) -> None:
    # Bridge to the unified logging system in core.utils
    core_log(level, msg, scope="AUTH")


class LoginHandler:
    dddd_ocr: Any = None  # ddddocr singleton
    shared_waf_cookies: list[CookieData] | None = None  # Shared WAF cookies
    waf_global_lock = asyncio.Lock()
    last_browser_tkv: str | None = None  # Captured from browser during bypass
    ocr_init_lock = threading.Lock()
    cached_public_ip: str = "N/A"

    def __init__(
        self,
        base_url: str = "https://star-asn.kemenimipas.go.id",
        user_agent: str | None = None,
        proxy: str | None = None,
    ) -> None:
        self.base_url = base_url
        self.user_agent = user_agent or MASTER_IDENTITY_UA
        self.proxy = proxy

        self.client: Any = AsyncSession(impersonate="chrome120", verify=False, timeout=30, proxy=self.proxy)
        self.client.headers.update(MASTER_IDENTITY_HEADERS)
        if user_agent:
            self.client.headers["User-Agent"] = user_agent

        # --- "MASTER OF MASTER" INJECTION ---
        if LoginHandler.shared_waf_cookies and isinstance(LoginHandler.shared_waf_cookies, list):
            for c in LoginHandler.shared_waf_cookies:
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

        # Initialize OCR Engines (Singleton pattern - Ensure it exists)
        if LoginHandler.dddd_ocr is None:
            pass
        
        self.captcha_mode = settings.CAPTCHA_MODE.lower()
        self.captcha_require_alpha = True  
        self.captcha_max_digits = 3  

    @property
    def ocr(self) -> Any:
        if LoginHandler.dddd_ocr is None:
            with LoginHandler.ocr_init_lock:
                if LoginHandler.dddd_ocr is None:
                    log("INFO", "event=ocr-init status=start message='Initializing ddddocr engine (Singleton)'")
                    LoginHandler.dddd_ocr = ddddocr.DdddOcr()
                    log("SUCCESS", "event=ocr-init status=complete")
        return LoginHandler.dddd_ocr

    def build_result(
        self,
        status: str,
        *,
        message: str,
        session_source: str | None = None,
        failure_stage: str | None = None,
        cookies: Any = None,
        response_time: float | None = None,
        attempts: int | None = None,
        captcha_code: str | None = None,
        attendance_result: bool | None = None,
        public_ip: str | None = None,
    ) -> dict[str, Any]:
        waf_status = "ACTIVE"
        if cookies:
            waf_cookies = self.extract_shared_waf_cookies(cookies if isinstance(cookies, list) else [])
            if waf_cookies:
                waf_status = "BYPASSED"

        result: dict[str, Any] = {
            "status": status,
            "message": message,
            "session_source": session_source,
            "failure_stage": failure_stage,
            "waf_status": waf_status,
            "public_ip": public_ip or self.__class__.cached_public_ip,
            "user_agent": self.user_agent,
        }
        if cookies is not None:
            result["cookies"] = cookies
        if response_time is not None:
            result["response_time"] = response_time
        if attempts is not None:
            result["attempts"] = attempts
        if captcha_code is not None:
            result["captcha_code"] = captcha_code
        if attendance_result is not None:
            result["attendance_result"] = attendance_result
        return result

    @staticmethod
    def format_cookie_payload(cookies_list: list[dict[str, Any]]) -> list[CookieData]:
        payload: list[CookieData] = []
        for cookie in cookies_list:
            name = str(cookie.get("name") or "").strip()
            if not name:
                continue
            payload.append(
                {
                    "name": name,
                    "value": str(cookie.get("value") or ""),
                    "domain": str(cookie.get("domain") or "star-asn.kemenimipas.go.id"),
                    "path": str(cookie.get("path") or "/"),
                }
            )
        return payload

    @classmethod
    def extract_shared_waf_cookies(cls, cookies: list[CookieData] | None) -> list[CookieData]:
        if not cookies:
            return []
        # Strictly only share WAF related cookies, exclude anything else
        return [cookie for cookie in cookies if str(cookie.get("name", "")).lower().startswith("waf")]

    @classmethod
    def cache_shared_waf_cookies(cls, cookies: list[CookieData] | None) -> None:
        cls.shared_waf_cookies = cls.extract_shared_waf_cookies(cookies)

    def apply_cookie_payload(self, cookies: list[CookieData] | None) -> None:
        for cookie in cookies or []:
            try:
                name = cookie.get("name")
                value = cookie.get("value")
                if not name or value is None:
                    continue
                    
                # Use provided domain, or fallback to the base domain
                domain = cookie.get("domain") or "star-asn.kemenimipas.go.id"
                path = cookie.get("path") or "/"
                
                self.client.cookies.set(
                    name,
                    value,
                    domain=domain,
                    path=path,
                )
            except Exception:
                continue

    def is_waf_interstitial(self, html: str, title: str = "") -> bool:
        normalized = f"{title}\n{html}".lower()
        return any(
            marker in normalized
            for marker in (
                "security check",
                "waf",
                "document.cookie='waf_token",
                "just a moment",
                "cf-browser-verification",
                "checking your browser",
                "attention required",
                "cloudflare",
            )
        )

    def is_login_form_ready_html(self, html: str) -> bool:
        return all(marker in html for marker in ('name="tkv"', 'name="username"', 'name="password"'))

    def is_dashboard_html(self, html: str) -> bool:
        # Modern markers
        if 'class="user-name-text"' in html and 'name="csrf-token"' in html:
            return True
        # Title markers (Fallback)
        if '<title>Statistik | STAR ASN</title>' in html or '<title>Dashboard | STAR ASN</title>' in html:
            return True
        # Identity markers
        if 'href="https://star-asn.kemenimipas.go.id/authentication/logout"' in html:
            return True
        return False

    def message_is_invalid_credentials(self, message: str | None) -> bool:
        normalized = str(message or "").lower()
        return any(
            token in normalized
            for token in ("belum terdaftar", "salah nip", "salah password", "login gagal", "password tidak ditemukan")
        )

    def message_is_captcha_failure(self, message: str | None) -> bool:
        normalized = str(message or "").lower()
        return "captcha" in normalized and any(token in normalized for token in ("salah", "invalid", "gagal"))

    @classmethod
    async def prime_waf_globally(cls, base_url: str = "https://star-asn.kemenimipas.go.id"):
        async with cls.waf_global_lock:
            if cls.shared_waf_cookies:
                log("INFO", "event=waf-priming status=skipped reason=already-primed")
                return True

            log("INFO", "event=waf-priming status=start action=launching-master-identity")
            temp_handler = LoginHandler(base_url)
            bootstrap_result = await temp_handler.solve_waf_challenge_via_browser()
            cookies = cast(list[CookieData] | None, bootstrap_result.get("cookies") if bootstrap_result else None)
            if cookies:
                cls.cache_shared_waf_cookies(cookies)
                log("SUCCESS", "event=waf-priming status=complete action=master-gate-opened")
                return True
            log("ERROR", "event=waf-priming status=failed message='Master Identity could not open the gate'")
            return False

    def black_ratio(self, img):
        if img is None:
            return 0.0
        if len(img.shape) == 3:
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            gray = img
        total = gray.size
        if total == 0:
            return 0.0
        black = np.count_nonzero(gray < 200)
        return black / float(total)

    def enhance_gray(self, gray):
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        return cv2.convertScaleAbs(enhanced, alpha=1.2, beta=0)

    async def get_best_candidates(self, image_bytes, min_conf=0.1):
        candidates = []
        
        # 1. Baseline raw
        res1 = self.ocr.classification(image_bytes)
        code1 = str(res1).strip().upper()
        if self.is_valid_code(code1):
            candidates.append((1.0, code1, "raw"))
        else:
            log("DEBUG", f"OCR raw prediction invalid: '{code1}'")
            
        # 2. Enhanced (Greyscale/Contrast)
        variant = self.preprocess_image(image_bytes)
        if variant is not None:
            _, enc = cv2.imencode(".png", variant)
            res2 = self.ocr.classification(enc.tobytes())
            code2 = str(res2).strip().upper()
            if self.is_valid_code(code2) and code2 not in [c[1] for c in candidates]:
                candidates.append((0.9, code2, "enhanced"))
            elif code2 != code1:
                log("DEBUG", f"OCR enhanced prediction invalid or duplicate: '{code2}'")
        
        if not candidates:
            log("WARN", "No valid captcha candidates found after dual-pass OCR.")
            
        return candidates[:3]

    async def fetch_captcha_bytes(self):
        url = f"{self.base_url}/authentication/captcha"
        ts = int(time.time() * 1000)
        try:
            resp = await self.client.get(f"{url}?t={ts}")
            if resp.status_code != 200:
                return None
            return resp.content
        except Exception as e:
            log("ERROR", f"fetch_captcha_bytes error: {e}")
            return None

    def is_valid_code(self, code):
        clean_code = str(code or "").strip()
        if not clean_code or len(clean_code) != 6:
            return False
        return True

    def preprocess_image(self, image_bytes):
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return None
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            ranges = [
                (np.array([28, 35, 35]), np.array([100, 255, 255])),
                (np.array([35, 50, 50]), np.array([95, 255, 255])),
            ]
            masks = [cv2.inRange(hsv, lower, upper) for lower, upper in ranges]
            mask = cv2.bitwise_or(masks[0], masks[1])
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            cleaned_mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
            contours, _ = cv2.findContours(cleaned_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            final_img = np.ones_like(mask) * 255
            valid_contours = []
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                area = cv2.contourArea(cnt)
                if area > 18 and h > 6:
                    valid_contours.append(cnt)
            if not valid_contours:
                return None
            cv2.drawContours(final_img, valid_contours, -1, (0), thickness=cv2.FILLED)
            final_img = cv2.copyMakeBorder(final_img, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
            return final_img
        except Exception:
            return None

    async def solve_captcha(self):
        try:
            image_bytes = await self.fetch_captcha_bytes()
            if image_bytes is None:
                return None
            res = await self.solve_captcha_bytes(image_bytes)
            return res.get("prediction")
        except Exception:
            await asyncio.sleep(0.5)
        return None

    async def solve_captcha_bytes(self, image_bytes, mode="baseline"):
        try:
            res = self.ocr.classification(image_bytes)
            res = str(res).strip().upper()
            if self.is_valid_code(res):
                return {"prediction": res, "confidence": 1.0, "error": None}
            else:
                variant = self.preprocess_image(image_bytes)
                if variant is not None:
                    _, encoded_img = cv2.imencode(".png", variant)
                    res2 = self.ocr.classification(encoded_img.tobytes())
                    res2 = str(res2).strip().upper()
                    if self.is_valid_code(res2):
                        return {"prediction": res2, "confidence": 0.9, "error": None}
                log("WARN", f"Captcha prediction invalid format: {res}")
                return {"prediction": res, "confidence": 0.5, "error": "invalid_code_format"}
        except Exception as e:
            log("ERROR", f"solve_captcha_bytes exception: {e}")
            return {"prediction": None, "confidence": None, "error": f"exception:{e}"}

    async def verify_dashboard_session(self) -> tuple[bool, str]:
        """Confirm session is valid by reaching the dashboard."""
        try:
            resp = await self.client.get(f"{self.base_url}/home/dashboard", timeout=30.0)
            
            # Check for redirect or login page
            if "login" in str(resp.url).lower() or "<title>login" in resp.text.lower():
                log("WARN", f"event=session-verify status=invalid reason=redirected-to-login url={resp.url}")
                return False, "Portal mengarahkan kembali ke halaman login."
            
            if self.is_dashboard_html(resp.text):
                return True, "Dashboard tervalidasi."
                
            log("WARN", f"event=session-verify status=invalid reason=marker-missing title='{resp.text[:50]}...'")
            return False, "Marker dashboard tidak ditemukan setelah login."
        except Exception as e:
            log("ERROR", f"event=session-verify status=error message={e}")
            return False, f"Gagal verifikasi dashboard: {e}"

    async def ensure_portal_ready(
        self,
        page: Any,
        *,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        timeout_ms: int = 90000,
        diagnostic_label: str = "anonymous",
    ) -> dict[str, Any]:
        login_url = f"{self.base_url}/authentication/login"
        try:
            await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            log("ERROR", f"event=portal-ready status=navigation-failed error={e}")
            return self.build_result(
                "failed",
                message=f"Gagal membuka halaman login portal: {e}",
                session_source="BROWSER",
                failure_stage="login_form_unavailable",
            )

        title = ""
        html = ""
        try:
            title = await page.title()
            html = await page.content()
        except Exception:
            pass

        waf_detected = self.is_waf_interstitial(html, title)
        if status_callback:
            await status_callback(
                "🛡️ Menunggu security check portal..." if waf_detected else "🌐 Menyiapkan form login portal..."
            )

        try:
            await page.wait_for_function(
                """() => {
                    const tkv = document.querySelector('input[name="tkv"]');
                    const username = document.querySelector('input[name="username"]');
                    const password = document.querySelector('input[name="password"]');
                    return Boolean(tkv && username && password);
                }""",
                timeout=timeout_ms,
            )
            await page.wait_for_load_state("domcontentloaded")
        except Exception as e:
            shot_path = f"failed_waf_{diagnostic_label}.png"
            try:
                await page.screenshot(path=shot_path)
            except Exception:
                shot_path = ""
            failure_stage = "waf_timeout" if waf_detected else "login_form_unavailable"
            message = "WAF timeout sebelum form login tersedia." if waf_detected else "Form login portal tidak tersedia."
            diagnostic = f" diagnostic={shot_path}" if shot_path else ""
            log("ERROR", f"event=portal-ready status=timeout stage={failure_stage} error={e}{diagnostic}")
            return self.build_result(
                "failed",
                message=message,
                session_source="BROWSER",
                failure_stage=failure_stage,
            )

        log("SUCCESS", "event=portal-ready status=login-form-ready")
        if status_callback:
            await status_callback("🔐 Form login portal siap.")
        return self.build_result("success", message="Form login portal siap.", session_source="BROWSER")

    async def bootstrap_portal_session_via_browser(
        self,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    ) -> dict[str, Any]:
        bootstrap = await self.solve_waf_challenge_via_browser(status_callback=status_callback)
        if bootstrap and bootstrap.get("status") == "success":
            cookies = cast(list[CookieData], bootstrap.get("cookies") or [])
            self.apply_cookie_payload(cookies)
            LoginHandler.cache_shared_waf_cookies(cookies)
            return self.build_result(
                "success",
                message="Portal login siap.",
                session_source="BROWSER",
                cookies=cookies,
            )
        if bootstrap:
            return self.build_result(
                str(bootstrap.get("status") or "failed"),
                message=str(bootstrap.get("message") or "Form login portal tidak tersedia."),
                session_source=str(bootstrap.get("session_source") or "BROWSER"),
                failure_stage=cast(str | None, bootstrap.get("failure_stage")),
            )
        return self.build_result(
            "failed",
            message="Form login portal tidak tersedia.",
            session_source="BROWSER",
            failure_stage="login_form_unavailable",
        )

    async def open_dashboard_in_browser(self, page: Any) -> tuple[bool, str, str]:
        try:
            await page.goto(f"{self.base_url}/home/dashboard", wait_until="domcontentloaded", timeout=25000)
        except Exception:
            pass

        try:
            await page.wait_for_function(
                """() => {
                    const userName = document.querySelector('span.user-name-text');
                    const csrf = document.querySelector('meta[name="csrf-token"]');
                    return Boolean(userName && csrf);
                }""",
                timeout=10000,
            )
        except Exception:
            pass

        content = await page.content()
        if "login" not in page.url.lower() and self.is_dashboard_html(content):
            return True, "Dashboard tervalidasi.", ""
        if self.message_is_invalid_credentials(content):
            return False, "NIP atau password portal tidak valid.", "invalid_credentials"
        if self.message_is_captcha_failure(content):
            return False, "Captcha portal tidak valid.", "captcha_failed"
        return False, "Dashboard tidak dapat diakses setelah login.", "dashboard_unreachable"

    async def login(
        self,
        username,
        password,
        action: str | None = None,
        location: str | None = None,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    ):
        login_url = f"{self.base_url}/authentication/login"
        set_context(username)
        max_attempts = settings.CAPTCHA_ATTEMPTS
        failure_reason: str | None = None

        if status_callback:
            await status_callback("🛡️ Menyiapkan koneksi aman (WAF)...")

        if not await portal_circuit_breaker.allow_request():
            log("WARN", "event=portal-circuit status=open action=skip-login")
            if status_callback:
                await status_callback("🚧 Portal sedang cooldown karena kegagalan berulang. Coba lagi sesaat lagi.")
            clear_context()
            return self.build_result("circuit_open", message="Portal circuit breaker is open", session_source="HTTP")

        for attempt in range(1, max_attempts + 1):
            try:
                if LoginHandler.cached_public_ip == "N/A":
                    try:
                        # Try ipify first
                        ip_resp = await self.client.get("https://api.ipify.org", timeout=5)
                        LoginHandler.cached_public_ip = ip_resp.text.strip()
                    except Exception:
                        try:
                            # Fallback if ipify is blocked or down
                            ip_resp = await self.client.get("https://ifconfig.me", timeout=5)
                            LoginHandler.cached_public_ip = ip_resp.text.strip()
                        except Exception:
                            pass

                perf_start = time.perf_counter()
                r_init = await self.client.get(login_url)

                if self.is_dashboard_html(r_init.text):
                    dashboard_ok, dashboard_message = await self.verify_dashboard_session()
                    if dashboard_ok:
                        log("SUCCESS", "event=session-id status=pre-authenticated")
                        await portal_circuit_breaker.record_success()
                        return self.build_result(
                            "success",
                            message="Sesi dashboard aktif.",
                            cookies=self.client.cookies.get_dict(),
                            response_time=time.perf_counter() - perf_start,
                            session_source="PERSISTENT",
                            captcha_code="BYPASSED",
                        )

                if self.is_waf_interstitial(r_init.text):
                    log("WARN", "event=portal status=waf-interstitial action=browser-bootstrap")
                    bootstrap_result = await self.bootstrap_portal_session_via_browser(status_callback)
                    if bootstrap_result.get("status") != "success":
                        clear_context()
                        return bootstrap_result
                    
                    # Sync cookies back to client
                    if "cookies" in bootstrap_result:
                        for c in bootstrap_result["cookies"]:
                             self.client.cookies.set(c["name"], c["value"], domain="star-asn.kemenimipas.go.id")

                    r_init = await self.client.get(login_url)

                if not self.is_login_form_ready_html(r_init.text):
                    log("WARN", "event=login-form status=missing action=emergency-bootstrap")
                    bootstrap_result = await self.bootstrap_portal_session_via_browser(status_callback)
                    if bootstrap_result.get("status") != "success":
                        clear_context()
                        return bootstrap_result
                    
                    # Sync cookies back to client
                    if "cookies" in bootstrap_result:
                        for c in bootstrap_result["cookies"]:
                             self.client.cookies.set(c["name"], c["value"], domain="star-asn.kemenimipas.go.id")

                    continue

                match = TKV_REGEX.search(r_init.text)
                if not match:
                    continue
                tkv = match.group(1)

                image_bytes = await self.fetch_captcha_bytes()
                if image_bytes is None: continue
                
                candidates = await self.get_best_candidates(image_bytes)
                if not candidates: continue
                
                for index, (conf, code, mode) in enumerate(candidates, start=1):
                    log("INFO", f"event=login-attempt attempt={attempt}.{index} captcha={Fore.YELLOW}{code}")
                    if status_callback:
                        await status_callback(f"🧩 Memecahkan Captcha: <b>{code}</b>")

                    payload = {
                        "tkv": tkv,
                        "username": username,
                        "password": password,
                        "kv-captcha": code,
                    }
                    request_start_time = time.time()
                    r_post = await self.client.post(
                        login_url,
                        data=payload,
                        headers={
                            "X-Requested-With": "XMLHttpRequest", 
                            "Origin": self.base_url, 
                            "Referer": login_url,
                            "Accept": "application/json, text/javascript, */*; q=0.01",
                            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8"
                        },
                        timeout=30.0,
                    )
                    response_time = time.time()
                    try:
                        res = r_post.json()
                        response_message = res.get("message")
                        
                        if res.get("status") == "success":
                            if status_callback:
                                await status_callback("🏠 Memverifikasi akses dashboard...")
                            dashboard_ok, dashboard_message = await self.verify_dashboard_session()
                            if dashboard_ok:
                                log("SUCCESS", "event=login status=success dashboard=verified")
                                await portal_circuit_breaker.record_success()
                                return self.build_result(
                                    "success",
                                    message="Login berhasil.",
                                    cookies=self.client.cookies.get_dict(),
                                    response_time=time.time() - perf_start,
                                    attempts=attempt,
                                    captcha_code=code,
                                    session_source="HTTP",
                                )
                            failure_reason = dashboard_message
                        elif self.message_is_invalid_credentials(response_message):
                            return self.build_result(
                                "failed",
                                message=response_message or "Kredensial salah.",
                                session_source="HTTP",
                                failure_stage="invalid_credentials",
                                captcha_code=code,
                                attempts=attempt,
                            )
                        else:
                            failure_reason = response_message or "Login gagal (Response JSON status != success)"
                    except Exception:
                        response_body = r_post.text
                        # 1. Check for WAF challenge
                        if self.is_waf_interstitial(response_body):
                            log("WARN", "event=login status=waf-detected-on-post action=emergency-bootstrap")
                            if status_callback: await status_callback("🛡️ WAF terdeteksi pada POST, memicu bypass...")
                            await self.bootstrap_portal_session_via_browser(status_callback)
                            continue 
                        
                        # 2. Check if we were redirected to dashboard (Fallback for non-JSON 302)
                        dashboard_ok, dashboard_message = await self.verify_dashboard_session()
                        if dashboard_ok:
                            log("SUCCESS", "event=login status=success redirect=true dashboard=verified")
                            await portal_circuit_breaker.record_success()
                            return self.build_result(
                                "success",
                                message="Login berhasil (Redirect).",
                                cookies=self.client.cookies.get_dict(),
                                response_time=time.time() - perf_start,
                                attempts=attempt,
                                captcha_code=code,
                                session_source="HTTP",
                            )
                            
                        # 3. Check for specific text-based errors
                        if self.message_is_captcha_failure(response_body):
                            failure_reason = "Captcha portal tidak valid."
                            continue
                        if self.message_is_invalid_credentials(response_body):
                            return self.build_result(
                                "failed",
                                message="NIP atau password portal tidak valid.",
                                session_source="HTTP",
                                failure_stage="invalid_credentials",
                                captcha_code=code,
                                attempts=attempt,
                            )
                        failure_reason = dashboard_message or "Response portal tidak valid (Bukan JSON)."

            except Exception as e:
                err_str = str(e).lower()
                failure_stage = "network_error"
                
                # Smart Technical Error Mapping
                if "curl: (7)" in err_str:
                    failure_stage = "network_refused"
                    failure_reason = "❌ Portal Down atau koneksi ditolak (Curl 7)."
                elif "curl: (28)" in err_str or "timed out" in err_str:
                    failure_stage = "network_timeout"
                    failure_reason = "⏳ Koneksi timeout (Portal lambat/Down)."
                elif "ssl" in err_str or "curl: (35)" in err_str:
                    failure_stage = "ssl_error"
                    failure_reason = "🔒 Kesalahan Sertifikat SSL Portal."
                else:
                    failure_reason = f"Network Exception: {e}"
                
                log("ERROR", f"event=login status=failed stage={failure_stage} error={e}")
                await portal_circuit_breaker.record_failure(failure_reason)
                await asyncio.sleep(1)

        return self.build_result(
            "failed",
            message=failure_reason or "Gagal login setelah beberapa percobaan.",
            session_source="HTTP",
            failure_stage=failure_stage if 'failure_stage' in locals() else "unknown_failure"
        )

    async def run_browser_login_fallback(self, username, password, action, location, status_callback, start_time=None):
        log("STEP", "event=emergency-bridge status=launching")
        if status_callback:
            await status_callback("🌐 Menjalankan fallback login browser penuh...")

        res_browser = await self.solve_waf_challenge_via_browser(
            username=username, password=password, action=action, location=location
        )
        if isinstance(res_browser, dict) and res_browser.get("status") == "success":
            cookies = res_browser.get("cookies")
            if cookies:
                for c in cookies:
                     self.client.cookies.set(c["name"], c["value"], domain="star-asn.kemenimipas.go.id")

            LoginHandler.cache_shared_waf_cookies(cast(list[CookieData] | None, cookies))
            await portal_circuit_breaker.record_success()
            return self.build_result(
                "success",
                message="Login browser berhasil dan dashboard tervalidasi.",
                cookies=cookies,
                attendance_result=res_browser.get("attendance_result"),
                session_source="BRIDGE",
            )

        if isinstance(res_browser, dict):
            return self.build_result(
                str(res_browser.get("status") or "failed"),
                message=str(res_browser.get("message") or "Browser bridge login failed"),
                session_source="BRIDGE",
                failure_stage=cast(str | None, res_browser.get("failure_stage")),
            )
        return self.build_result(
            "failed",
            message="Browser bridge login failed",
            session_source="BRIDGE",
            failure_stage="dashboard_unreachable",
        )

    async def solve_waf_challenge_via_browser(self, username=None, password=None, action=None, location=None, status_callback=None):
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return self.build_result(
                "failed",
                message="Playwright tidak tersedia di runtime.",
                session_source="BROWSER",
                failure_stage="login_form_unavailable",
            )

        async with browser_bridge_semaphore:
            async with async_playwright() as p:
                launch_opts: dict = {
                    "headless": settings.WAF_BROWSER_HEADLESS,
                    "args": [
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                }
                # Pass proxy to Chromium if configured (Bright Data / custom)
                # Playwright requires separate server/username/password fields
                if self.proxy:
                    from urllib.parse import urlparse
                    parsed = urlparse(self.proxy)
                    proxy_config: dict[str, str] = {
                        "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
                    }
                    if parsed.username:
                        proxy_config["username"] = parsed.username
                    if parsed.password:
                        proxy_config["password"] = parsed.password
                    launch_opts["proxy"] = proxy_config

                browser = await p.chromium.launch(**launch_opts)
                context = await browser.new_context(
                    user_agent=self.user_agent,
                    viewport={"width": 1280, "height": 720},
                    ignore_https_errors=True
                )
                page = await context.new_page()
                ready_result = await self.ensure_portal_ready(
                    page,
                    status_callback=status_callback,
                    diagnostic_label=username or "anonymous",
                )
                if ready_result.get("status") != "success":
                    await browser.close()
                    return ready_result

                if not username or not password:
                    cookies_list = await context.cookies()
                    formatted = self.format_cookie_payload(cookies_list)
                    await browser.close()
                    return self.build_result(
                        "success",
                        message="Form login portal siap.",
                        session_source="BROWSER",
                        cookies=formatted,
                    )

                attendance_res = None
                debug_dir = r"C:\tmp\star_asn_debug"
                if not os.path.exists(debug_dir):
                    try: os.makedirs(debug_dir)
                    except: pass
                last_failure_stage = "dashboard_unreachable"
                last_message = "Dashboard tidak dapat diakses setelah login."
                reached_dashboard = False

                for login_attempt in range(1, 6):
                    try:
                        log("INFO", f"event=waf-browser status=attempt attempt={login_attempt} user={username}")
                        if status_callback:
                            await status_callback(f"🧩 Menyiapkan captcha percobaan {login_attempt}/5...")
                        await page.locator('input[name="username"]').fill(username)
                        await page.locator('input[name="password"]').fill(password)
                        
                        captcha_img = await page.wait_for_selector('img[src*="captcha"]', state="visible", timeout=15000)
                        await captcha_img.scroll_into_view_if_needed()
                        await asyncio.sleep(1)
                        img_bytes = await captcha_img.screenshot()
                        
                        ocr_candidates = await self.get_best_candidates(img_bytes)
                        if not ocr_candidates:
                            log("WARN", f"event=waf-browser status=ocr-failed attempt={login_attempt}")
                            last_failure_stage = "captcha_failed"
                            last_message = "Captcha portal tidak dapat dibaca."
                            await page.click('img[src*="captcha"]')
                            await asyncio.sleep(2)
                            continue
                        
                        code = ocr_candidates[0][1]
                        log("INFO", f"event=waf-browser status=captcha-solved code={code} attempt={login_attempt}")
                        
                        await page.locator('input[name="kv-captcha"]').fill("")
                        await page.locator('input[name="kv-captcha"]').fill(code)
                        await page.locator('button[type="submit"]').click(force=True)

                        log("INFO", f"event=waf-browser status=submitted-wait user={username}")
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=5000)
                        except Exception:
                            pass
                        if status_callback:
                            await status_callback("🏠 Memverifikasi akses dashboard...")

                        dashboard_ok, dashboard_message, failure_stage = await self.open_dashboard_in_browser(page)
                        if dashboard_ok:
                            reached_dashboard = True
                            log("SUCCESS", "event=waf-browser status=dashboard-reached user={username}")
                            if action:
                                attendance_res = await self.perform_attendance_in_browser(page, action, location)
                            break
                        last_failure_stage = failure_stage
                        last_message = dashboard_message
                        shot_name = f"failed_{username}_att{login_attempt}_{int(time.time())}.png"
                        await page.screenshot(path=os.path.join(debug_dir, shot_name))

                        if failure_stage == "invalid_credentials":
                            await browser.close()
                            return self.build_result(
                                "terminal",
                                message=dashboard_message,
                                session_source="BRIDGE",
                                failure_stage=failure_stage,
                            )
                        if failure_stage == "captcha_failed":
                            await page.click('img[src*="captcha"]', timeout=3000)
                            await asyncio.sleep(2)
                        else:
                            await asyncio.sleep(3)
                    except Exception as e:
                        last_failure_stage = "dashboard_unreachable"
                        last_message = f"Kesalahan saat login browser: {e}"
                        log("ERROR", f"event=waf-browser status=attempt-error error={e}")
                        await asyncio.sleep(2)

                cookies_list = await context.cookies()
                formatted = self.format_cookie_payload(cookies_list)
                
                if username and reached_dashboard:
                    try:
                        from star_attendance.runtime import get_store
                        from star_attendance.core.timeutils import now_local
                        store = get_store()
                        store.save_user_session(
                            username,
                            {
                                "cookies": {c["name"]: c["value"] for c in formatted},
                                "captured_at": now_local().isoformat(),
                                "user_agent": self.user_agent,
                            },
                        )
                    except Exception as e:
                        log("WARN", f"event=waf-browser status=session-persist-failed error={e}")
                
                await browser.close()
                if reached_dashboard:
                    return self.build_result(
                        "success",
                        message="Login browser berhasil dan dashboard tervalidasi.",
                        session_source="BRIDGE",
                        cookies=formatted,
                        attendance_result=attendance_res,
                    )
                return self.build_result(
                    "failed",
                    message=last_message,
                    session_source="BRIDGE",
                    failure_stage=last_failure_stage,
                )

    async def perform_attendance_in_browser(self, page, action, location=None):
        try:
            await page.goto(f"{self.base_url}/home/dashboard")
            await page.wait_for_load_state("networkidle")
            csrf_token = await page.eval_on_selector('meta[name="csrf-token"]', "el => el.content")
            location = location or "-7.3995,109.8895"
            script = f"""
            fetch('/attendance/presence', {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'KV-TOKEN': '{csrf_token}',
                    'X-Requested-With': 'XMLHttpRequest'
                }},
                body: 'location={location}&timezone=Asia/Jakarta&type={action}'
            }}).then(res => res.json())
            """
            result = await page.evaluate(script)
            log("INFO", f"event=browser-attendance status=result data={result}")
            return result.get("status") == "success" or "berhasil" in str(result).lower()
        except Exception: return False
