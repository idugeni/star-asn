import asyncio
import threading
import time
import warnings
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from datetime import datetime
from typing import Any, TypedDict, cast

import cv2

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


def log(level: str, msg: str) -> None:
    colors = {"INFO": Fore.BLUE, "WARN": Fore.YELLOW, "ERROR": Fore.RED, "SUCCESS": Fore.GREEN}
    color = colors.get(level, Fore.WHITE)
    with print_lock:
        print(
            f"{Fore.CYAN}[{get_timestamp()}] {color}[{level}] {Fore.MAGENTA}[{LOG_SCOPE}] {Style.RESET_ALL}{get_context_prefix()}{msg}",
            flush=True,
        )


class LoginHandler:
    _dddd: Any = None  # ddddocr singleton
    _waf_cookies: list[CookieData] | None = None  # Shared WAF cookies
    _waf_lock = asyncio.Lock()

    def __init__(
        self,
        base_url: str = "https://star-asn.kemenimipas.go.id",
        user_agent: str | None = None,
        proxy: str | None = None,
    ) -> None:
        self.base_url = base_url
        # Default Master Identity (Chrome 147)
        self.user_agent = (
            user_agent
            or "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        )
        self.proxy = proxy

        self.client: Any = AsyncSession(impersonate="chrome120", verify=False, timeout=30, proxy=self.proxy)
        self.client.headers.update(
            {
                "User-Agent": self.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Accept-Language": "en-US,en;q=0.9",
                "Cache-Control": "no-cache",
                "DNT": "1",
                "Pragma": "no-cache",
                "Priority": "u=0, i",
                "Sec-Ch-Ua": '"Google Chrome";v="147", "Not.A/Brand";v="8", "Chromium";v="147"',
                "Sec-Ch-Ua-Mobile": "?0",
                "Sec-Ch-Ua-Platform": '"Windows"',
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }
        )

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

        # Initialize OCR Engines (Singleton pattern - LAZY LOAD)
        # Moved from __init__ to first-use to avoid blocking event loop on startup
        if LoginHandler._dddd is None:
            pass  # Will be loaded on first captcha solve

        self.captcha_mode = settings.CAPTCHA_MODE.lower()
        self.captcha_require_alpha = True  # Hardcoded or add to settings if needed
        self.captcha_max_digits = 3  # Hardcoded or add to settings if needed

    @property
    def ocr(self) -> Any:
        if LoginHandler._dddd is None:
            log("INFO", "event=ocr_init status=start message='Initializing ddddocr engine (Lazy Load)'")
            LoginHandler._dddd = ddddocr.DdddOcr(show_ad=False)
        return LoginHandler._dddd

    @classmethod
    async def prime_waf_globally(cls, base_url: str = "https://star-asn.kemenimipas.go.id"):
        """
        [PROACTIVE BYPASS] - The "Master Identity" solves the challenge once
        to open the gate for all 1000 workers simultaneously.
        """
        async with cls._waf_lock:
            # Skip if already primed recently
            if cls._waf_cookies:
                log("INFO", "event=waf_priming status=skipped reason=already_primed")
                return True

            log("INFO", "event=waf_priming status=start action=launching_master_identity")
            # Create a temporary handler just for priming
            temp_handler = LoginHandler(base_url)
            cookies = await temp_handler._solve_waf_challenge_via_browser()
            if cookies:
                cls._waf_cookies = cast(list[CookieData], cookies)
                log("SUCCESS", "event=waf_priming status=complete action=master_gate_opened")
                return True
            log("ERROR", "event=waf_priming status=failed message='Master Identity could not open the gate'")
            return False

    def _black_ratio(self, img):
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

    def _enhance_gray(self, gray):
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(gray)
        return cv2.convertScaleAbs(enhanced, alpha=1.2, beta=0)

    def _filter_variants(self, variants):
        filtered = []
        seen = set()
        for variant in variants:
            ratio = self._black_ratio(variant)
            if 0.002 <= ratio <= 0.6:
                key = (variant.shape[0], variant.shape[1], int(variant.sum()))
                if key not in seen:
                    seen.add(key)
                    filtered.append(variant)
        return filtered

    def _gray_variants(self, img):
        if img is None:
            return []
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray = self._enhance_gray(gray)
        denoised = cv2.fastNlMeansDenoising(gray, None, 20, 7, 21)
        line_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1))
        lines = cv2.morphologyEx(denoised, cv2.MORPH_OPEN, line_kernel, iterations=1)
        line_removed = cv2.subtract(denoised, lines)
        variants = []
        _, otsu = cv2.threshold(denoised, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(otsu)
        variants.append(255 - otsu)
        adaptive_11 = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        adaptive_15 = cv2.adaptiveThreshold(denoised, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 15, 2)
        variants.append(adaptive_11)
        variants.append(255 - adaptive_11)
        variants.append(adaptive_15)
        variants.append(255 - adaptive_15)
        _, line_otsu = cv2.threshold(line_removed, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        variants.append(line_otsu)
        variants.append(255 - line_otsu)
        return variants

    def _color_variants(self, img):
        if img is None:
            return []
        b, g, r = cv2.split(img)
        diff_gr = cv2.subtract(g, r)
        diff_gb = cv2.subtract(g, b)
        variants = []
        for diff in (diff_gr, diff_gb):
            diff = self._enhance_gray(diff)
            _, otsu = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            variants.append(otsu)
            variants.append(255 - otsu)
        return variants

    def _get_mode_order(self):
        return ["baseline", "variants", "adaptive", "color", "raw"]

    async def _get_two_best_candidates(self, image_bytes, min_conf):
        # ddddocr only returns one best prediction
        res = await self.solve_captcha_bytes(image_bytes)
        pred = res.get("prediction")
        if pred:
            return [(1.0, pred, "ddddocr")]
        return []

    async def _fetch_captcha_bytes(self):
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

    def _is_valid_code(self, code):
        """Strictly enforce 6-digit captcha as per enterprise requirements"""
        if not code or len(code) != 6:
            return False
        return True

    # EasyOCR methods removed to save weight and simplify logic

    def preprocess_image(self, image_bytes):
        """
        Preprocessing tunggal yang sangat cepat dan presisi untuk Captcha Kemenkumham.
        Target: Teks Hijau.
        """
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return None
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            ranges = [
                (np.array([28, 35, 35]), np.array([100, 255, 255])),
                (np.array([35, 50, 50]), np.array([95, 255, 255])),
                (np.array([40, 60, 50]), np.array([85, 255, 255])),
            ]
            masks = [cv2.inRange(hsv, lower, upper) for lower, upper in ranges]
            mask = cv2.bitwise_or(masks[0], masks[1])
            mask = cv2.bitwise_or(mask, masks[2])
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            cleaned_mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
            cleaned_mask = cv2.morphologyEx(cleaned_mask, cv2.MORPH_CLOSE, kernel, iterations=1)
            contours, _ = cv2.findContours(cleaned_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            final_img = np.ones_like(mask) * 255
            valid_contours = []
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                area = cv2.contourArea(cnt)
                aspect_ratio = float(w) / h
                if area > 18 and aspect_ratio < 10 and h > 6:
                    valid_contours.append(cnt)
            if not valid_contours:
                green = img[:, :, 1]
                green = self._enhance_gray(green)
                blurred = cv2.GaussianBlur(green, (3, 3), 0)
                thresh = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 13, 2)
                thresh = 255 - thresh
                thresh = cv2.copyMakeBorder(thresh, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
                small_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                dilated = cv2.dilate(thresh, small_kernel, iterations=1)
                if self._black_ratio(dilated) >= 0.002:
                    return dilated
                return thresh
            cv2.drawContours(final_img, valid_contours, -1, (0), thickness=cv2.FILLED)
            final_img = cv2.copyMakeBorder(final_img, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
            return final_img

        except Exception as e:
            log("ERROR", f"Gagal memproses gambar: {e}")
            return None

    def preprocess_variants(self, image_bytes):
        try:
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is None:
                return []
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            ranges = [
                (np.array([28, 35, 35]), np.array([100, 255, 255])),
                (np.array([35, 50, 50]), np.array([95, 255, 255])),
                (np.array([40, 60, 50]), np.array([85, 255, 255])),
                (np.array([45, 70, 50]), np.array([80, 255, 255])),
            ]
            variants = []
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            for lower, upper in ranges:
                mask = cv2.inRange(hsv, lower, upper)
                cleaned_mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
                cleaned_mask = cv2.morphologyEx(cleaned_mask, cv2.MORPH_CLOSE, kernel, iterations=1)
                if cv2.countNonZero(cleaned_mask) < 10:
                    green = img[:, :, 1]
                    green = self._enhance_gray(green)
                    blurred = cv2.GaussianBlur(green, (3, 3), 0)
                    thresh = cv2.adaptiveThreshold(
                        blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 13, 2
                    )
                    thresh = 255 - thresh
                    thresh = cv2.copyMakeBorder(thresh, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
                    variants.append(thresh)
                    small_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                    variants.append(cv2.dilate(thresh, small_kernel, iterations=1))
                    variants.append(cv2.erode(thresh, small_kernel, iterations=1))
                    continue
                line_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 1))
                cleaned_mask_line = cv2.morphologyEx(cleaned_mask, cv2.MORPH_OPEN, line_kernel, iterations=1)
                contours, _ = cv2.findContours(cleaned_mask_line, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                final_img = np.ones_like(mask) * 255
                valid_contours = []
                for cnt in contours:
                    x, y, w, h = cv2.boundingRect(cnt)
                    area = cv2.contourArea(cnt)
                    aspect_ratio = float(w) / h
                    if area > 18 and aspect_ratio < 10 and h > 6:
                        valid_contours.append(cnt)
                if len(valid_contours) < 4:
                    contours, _ = cv2.findContours(cleaned_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    valid_contours = []
                    for cnt in contours:
                        x, y, w, h = cv2.boundingRect(cnt)
                        area = cv2.contourArea(cnt)
                        aspect_ratio = float(w) / h
                        if area > 18 and aspect_ratio < 10 and h > 6:
                            valid_contours.append(cnt)
                cv2.drawContours(final_img, valid_contours, -1, (0), thickness=cv2.FILLED)
                final_img = cv2.copyMakeBorder(final_img, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
                variants.append(final_img)
                masked = cv2.bitwise_and(img, img, mask=cleaned_mask)
                gray = cv2.cvtColor(masked, cv2.COLOR_BGR2GRAY)
                gray = self._enhance_gray(gray)
                blurred = cv2.GaussianBlur(gray, (3, 3), 0)
                _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                thresh = 255 - thresh
                thresh = cv2.copyMakeBorder(thresh, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)
                variants.append(thresh)
                small_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
                variants.append(cv2.dilate(thresh, small_kernel, iterations=1))
                variants.append(cv2.erode(thresh, small_kernel, iterations=1))
            return variants
        except Exception as e:
            log("ERROR", f"Gagal memproses variasi gambar: {e}")
            return []

    async def solve_captcha(self):
        try:
            image_bytes = await self._fetch_captcha_bytes()
            if image_bytes is None:
                return None

            res = await self.solve_captcha_bytes(image_bytes)
            return res.get("prediction")

        except Exception as e:
            log("WARN", f"event=captcha_fetch error={e}")
            await asyncio.sleep(0.5)

        return None

    async def solve_captcha_bytes(self, image_bytes, mode="baseline"):
        try:
            res = self.ocr.classification(image_bytes)
            res = str(res).upper()
            if self._is_valid_code(res):
                return {"prediction": res, "confidence": 1.0, "error": None}
            else:
                # Fallback: Try minimal preprocessing
                variant = self.preprocess_image(image_bytes)
                if variant is not None:
                    _, encoded_img = cv2.imencode(".png", variant)
                    res2 = self.ocr.classification(encoded_img.tobytes())
                    res2 = str(res2).upper()
                    if self._is_valid_code(res2):
                        return {"prediction": res2, "confidence": 0.9, "error": None}
                return {"prediction": res, "confidence": 0.5, "error": "invalid_code_format"}
        except Exception as e:
            return {"prediction": None, "confidence": None, "error": str(e)}
        except Exception as e:
            return {"prediction": None, "confidence": None, "error": f"exception:{e}"}

    _public_ip_cache: str | None = None
    _public_ip_expiry: float = 0.0

    async def get_public_ip(self) -> str:
        """Fetch current public IP address with 5-minute caching"""
        now = time.time()
        if LoginHandler._public_ip_cache and now < LoginHandler._public_ip_expiry:
            return LoginHandler._public_ip_cache

        try:
            # Try multiple services for redundancy
            for url in ["https://api.ipify.org", "https://ifconfig.me/ip", "https://checkip.amazonaws.com"]:
                try:
                    resp = await self.client.get(url, timeout=3)
                    if resp.status_code == 200:
                        LoginHandler._public_ip_cache = resp.text.strip()
                        LoginHandler._public_ip_expiry = now + 300  # 5 minutes cache
                        return LoginHandler._public_ip_cache
                except Exception:
                    continue
            return LoginHandler._public_ip_cache or "UNKNOWN"
        except Exception:
            return LoginHandler._public_ip_cache or "ERROR"

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
        consecutive_solve_failures = 0

        if status_callback:
            await status_callback("🛡️ Menyiapkan koneksi aman (WAF)...")

        if not await portal_circuit_breaker.allow_request():
            log("WARN", "event=portal_circuit status=open action=skip_login")
            if status_callback:
                await status_callback("🚧 Portal sedang cooldown karena kegagalan berulang. Coba lagi sesaat lagi.")
            clear_context()
            return {"status": "circuit_open", "message": "Portal circuit breaker is open"}

        for attempt in range(1, max_attempts + 1):
            try:
                # 0. WAF Slow Handshake: Optimized for discovered 6.5s door opening time
                if attempt == 1 and not LoginHandler._waf_cookies:
                    log("INFO", "event=waf_priming status=stage1 action=warmup jitter=3.5s")
                    await self.client.get(f"{self.base_url}/", headers={"Sec-Fetch-Site": "none"})
                    await asyncio.sleep(3.5)

                    log("INFO", "event=waf_priming status=stage2 action=warmup jitter=3.0s")
                    await self.client.get(
                        f"{self.base_url}/authentication/login",
                        headers={"Sec-Fetch-Site": "same-origin", "Referer": self.base_url},
                    )
                    await asyncio.sleep(3.0)

                start_time = datetime.now()

                # --- TELEMETRY STATE TRACKING ---
                # Track session source for debug logs
                if not hasattr(self, "_session_source"):
                    self._session_source = "NEW"

                waf_status = "ACTIVE"
                # 1. Initiating Login Page
                r_init = await self.client.get(
                    login_url,
                    headers={
                        "Sec-Fetch-Dest": "document",
                        "Sec-Fetch-Mode": "navigate",
                        "Sec-Fetch-Site": "same-origin",
                        "Sec-Fetch-User": "?1",
                    },
                )

                # --- INTELLIGENT DETECTION: ARE WE ALREADY IN? ---
                # Some WAFs or session managers redirect to dashboard if cookies are already good.
                # We check for vertical layout and user name text specifically in a way that suggests a dashboard
                has_dashboard_layout = 'data-layout="vertical"' in r_init.text
                has_user_profile = 'class="user-name-text"' in r_init.text or 'class="user-role-text"' in r_init.text

                if has_dashboard_layout and has_user_profile:
                    log(
                        "SUCCESS",
                        "event=session_id status=pre_authenticated message='Detected application layout. Cookies already valid.'",
                    )
                    await portal_circuit_breaker.record_success()
                    return {
                        "status": "success",
                        "cookies": self.client.cookies.get_dict(),
                        "response_time": (datetime.now() - start_time).total_seconds(),
                        "session_source": "PERSISTENT",
                    }

                if 'name="tkv"' not in r_init.text:
                    if "Security Check" in r_init.text or "WAF" in r_init.text or "Checking on progress" in r_init.text:
                        failure_reason = "waf_blocked"
                        log("WARN", f"event=tkv status=blocked_by_waf code={r_init.status_code}")

                        # 0. Check if we already have shared WAF context if available
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
                            # If we just applied cookies, retry this attempt immediately
                            await asyncio.sleep(1.0)

                        # 1. If still blocked, attempt WAF Bridge for the first time
                        else:
                            async with LoginHandler._waf_lock:
                                # Double check after lock
                                if not LoginHandler._waf_cookies:
                                    log("INFO", "event=waf_bridge status=start action=launch_browser")
                                    cookies = await self._solve_waf_challenge_via_browser(status_callback=status_callback)
                                    if cookies and isinstance(cookies, list):
                                        self._session_source = "BRIDGE"
                                        waf_status = "BYPASSED"
                                        LoginHandler._waf_cookies = cast(list[CookieData], cookies)
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
                                        log("SUCCESS", "event=waf_bridge status=success action=cookies_synced")
                                    else:
                                        failure_reason = "browser_bridge_failed"
                                        log("ERROR", "event=waf_bridge status=failed")

                        # 2. Emergency Fallback for this specific user on the last attempt
                        if attempt == max_attempts:
                            browser_result = await self._run_browser_login_fallback(
                                username=username,
                                password=password,
                                action=action,
                                location=location,
                                status_callback=status_callback,
                                start_time=start_time,
                            )
                            if browser_result:
                                return browser_result
                            failure_reason = "browser_bridge_failed"
                            return {"status": "failed", "message": "browser_bridge_failed"}

                        await asyncio.sleep(1.0)
                    else:
                        log_snippet = r_init.text[:150].replace("\n", " ")
                        log("WARN", f"event=tkv status=missing code={r_init.status_code} snippet='{log_snippet}...'")
                    continue

                # Parsing TKV manual (lebih cepat dari BeautifulSoup)
                try:
                    tkv = r_init.text.split('name="tkv" value="')[1].split('"')[0]
                except Exception:
                    log("WARN", f"event=tkv status=parse_failed code={r_init.status_code}")
                    continue

                # 2. Solve Captcha
                min_conf = settings.CAPTCHA_MIN_CONF
                image_bytes = await self._fetch_captcha_bytes()
                if image_bytes is None:
                    consecutive_solve_failures += 1
                    log("WARN", "event=captcha_fetch status=failed action=retry_image")
                    if consecutive_solve_failures >= 2:
                        await asyncio.sleep(0.4)
                    continue
                if consecutive_solve_failures > 0:
                    await asyncio.sleep(min(0.2 * consecutive_solve_failures, 0.6))
                consecutive_solve_failures = 0
                candidates = await self._get_two_best_candidates(image_bytes, min_conf)
                if not candidates:
                    consecutive_solve_failures += 1
                    log("WARN", "event=captcha_solve status=failed action=retry_image")
                    if consecutive_solve_failures >= 2:
                        await asyncio.sleep(0.4)
                    continue
                for index, (conf, code, mode) in enumerate(candidates, start=1):
                    log(
                        "INFO", f"event=login_attempt attempt={attempt}.{index} mode={mode} captcha={Fore.YELLOW}{code}"
                    )

                    if status_callback:
                        await status_callback(f"🧩 Memecahkan kode captcha (Percobaan {attempt}.{index})...")

                    data = {"tkv": tkv, "username": username, "password": password, "kv-captcha": code}

                    request_start_time = time.time()
                    r_post = await self.client.post(
                        login_url,
                        data=data,
                        headers={"X-Requested-With": "XMLHttpRequest", "Origin": self.base_url, "Referer": login_url},
                    )
                    response_time = time.time() - request_start_time

                    try:
                        res = r_post.json()
                        if res.get("status") == "success":
                            log("SUCCESS", "event=login status=success")
                            await portal_circuit_breaker.record_success()
                            return {
                                "status": "success",
                                "cookies": self.client.cookies.get_dict(),
                                "response_time": response_time,
                                "attempts": attempt,
                                "captcha_code": code,
                                "session_source": getattr(self, "_session_source", "NEW"),
                                "waf_status": waf_status,
                                "public_ip": await self.get_public_ip(),
                                "user_agent": self.user_agent,
                            }
                        else:
                            msg = res.get("message", "").lower()
                            if "captcha" in msg:
                                log("WARN", "event=captcha status=invalid action=retry_code")
                                continue
                            else:
                                log("ERROR", f"event=login status=failed message={res.get('message')}")
                                clear_context()
                                # Terminal failure if account not found or password explicitly wrong
                                fatal_keywords = [
                                    "belum terdaftar",
                                    "salah nip",
                                    "salah password",
                                    "tidak aktif",
                                    "login gagal",
                                    "tidak ditemukan",
                                ]
                                if any(k in msg for k in fatal_keywords):
                                    return {"status": "terminal", "message": res.get("message")}
                                failure_reason = res.get("message") or "login_failed"
                                return {"status": "failed", "message": failure_reason}
                    except:
                        if "dashboard" in str(r_post.url):
                            log("SUCCESS", "event=login status=success redirect=true")
                            clear_context()
                            await portal_circuit_breaker.record_success()
                            return {
                                "status": "success",
                                "cookies": self.client.cookies.get_dict(),
                                "response_time": response_time,
                            }

            except Exception as e:
                failure_reason = f"exception:{e}"
                log("ERROR", f"event=login exception={e}")
                await asyncio.sleep(1)
        browser_result = await self._run_browser_login_fallback(
            username=username,
            password=password,
            action=action,
            location=location,
            status_callback=status_callback,
        )
        if browser_result:
            return browser_result
        if failure_reason:
            await portal_circuit_breaker.record_failure(failure_reason)
        clear_context()
        return {"status": "failed", "message": failure_reason or "Login failed after multiple attempts"}

    async def _run_browser_login_fallback(
        self,
        username: str,
        password: str,
        action: str | None = None,
        location: str | None = None,
        status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
        start_time: datetime | None = None,
    ) -> dict[str, Any] | None:
        log("STEP", "event=emergency_bridge status=launching message='Escalating to full browser login fallback.'")
        if status_callback:
            await status_callback("🌐 Menjalankan fallback login browser penuh...")

        bridge_started_at = start_time or datetime.now()
        res_browser = await self._solve_waf_challenge_via_browser(
            username=username,
            password=password,
            action=action,
            location=location,
        )
        if res_browser and isinstance(res_browser, dict) and res_browser.get("status") == "success":
            await portal_circuit_breaker.record_success()
            return {
                "status": "success",
                "cookies": res_browser.get("cookies"),
                "response_time": (datetime.now() - bridge_started_at).total_seconds(),
                "attendance_result": res_browser.get("attendance_result"),
                "session_source": "BRIDGE",
                "waf_status": "BYPASSED",
                "public_ip": await self.get_public_ip(),
                "user_agent": self.user_agent,
            }
        if res_browser:
            await portal_circuit_breaker.record_success()
            return {
                "status": "success",
                "cookies": res_browser,
                "response_time": (datetime.now() - bridge_started_at).total_seconds(),
                "session_source": "BRIDGE",
                "waf_status": "BYPASSED",
                "public_ip": await self.get_public_ip(),
                "user_agent": self.user_agent,
            }
        return {"status": "failed", "message": "Browser bridge login failed"}

    async def _solve_waf_challenge_via_browser(
        self, username=None, password=None, action=None, location=None, status_callback=None
    ):
        """
        Launches a real Chromium browser to solve the WAF challenge,
        perform full login if credentials provided, and optionally execute attendance.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            log("ERROR", "Playwright not installed. Run 'pip install playwright'")
            return None

        try:
            if status_callback:
                await status_callback("🌐 Meluncurkan browser untuk verifikasi WAF...")

            headless = settings.WAF_BROWSER_HEADLESS
            async with browser_bridge_semaphore:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(
                        headless=headless, args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                    )
                    context = await browser.new_context(user_agent=self.user_agent, viewport={"width": 1280, "height": 720})
                    page = await context.new_page()

                    login_url = f"{self.base_url}/authentication/login"
                    log("INFO", f"event=waf_browser status=opened url={login_url}")
                    if status_callback:
                        await status_callback("⏳ Menunggu verifikasi WAF (Cloudflare/Citrix)...")

                    # --- HUMAN-LIKE HANDSHAKE: Loading full assets for correct fingerprinting ---
                    # We no longer block CSS or Images during WAF bypass to ensure Cloudflare/Citrix 
                    # integrity checks pass (fingerprinting depends on CSS/Asset rendering).
                    # We use 'commit' for faster initiation followed by targeted waiting.
                    await page.goto(login_url, wait_until="commit", timeout=60000)

                    # 1. Wait for WAF to clear and Login Page to appear
                    log("INFO", "event=waf_browser status=waiting action=clearing_waf")
                    try:
                        # Detection: Look for the 'tkv' input which signals the login form is ready.
                        # Increased timeout to 60s for slow WAF handshakes.
                        await page.wait_for_selector('input[name="tkv"]', timeout=60000)
                        log("SUCCESS", "event=waf_browser status=ready message='WAF cleared, login form detected'")
                    except Exception as e:
                        log("ERROR", f"event=waf_browser status=timeout message='WAF did not clear or login form not found: {e}'")
                        await portal_circuit_breaker.record_failure("browser_bridge_timeout")
                        await browser.close()
                        return None


                    # 2. Fast-Wait: Continue as soon as form is interactive
                    await page.wait_for_selector('input[name="username"]', state="attached", timeout=45000)
                    await page.wait_for_selector('input[name="password"]', state="attached", timeout=10000)

                    # 2. If Username/Password provided, perform FULL LOGIN
                    if username and password:
                        log("INFO", f"event=waf_browser status=authenticating user={username}")

                        # Use DOM-level setters so headless/container runs don't depend on field visibility timing.
                        await page.locator('input[name="username"]').evaluate(
                            "(el, value) => { el.value = value; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }",
                            username,
                        )
                        await page.locator('input[name="password"]').evaluate(
                            "(el, value) => { el.value = value; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }",
                            password,
                        )

                        # Solve Captcha natively
                        captcha_img = await page.query_selector('img[src*="captcha"]')
                        if captcha_img:
                            img_bytes = await captcha_img.screenshot()
                            # Use our internal OCR solver
                            ocr_res = await self._get_two_best_candidates(img_bytes, min_conf=0.2)
                            if ocr_res:
                                code = ocr_res[0][1]
                                log("INFO", f"event=waf_browser status=solving_captcha code={code}")
                                if status_callback:
                                    await status_callback("🧩 Memecahkan Captcha...")
                                await page.locator('input[name="kv-captcha"]').evaluate(
                                    "(el, value) => { el.value = value; el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); }",
                                    code,
                                )
                                await page.locator('button[type="submit"]').click(force=True)

                                # Wait for navigation or error
                                await asyncio.sleep(3)

                                if "dashboard" in page.url or "user-name-text" in await page.content():
                                    log("SUCCESS", "event=waf_browser status=login_success")
                                    await portal_circuit_breaker.record_success()

                                    # 2.1 IF ACTION PROVIDED: Perform Attendance in Browser Session
                                    if action:
                                        log("INFO", f"event=waf_browser status=executing_attendance action={action}")
                                        attendance_res = await self._perform_attendance_in_browser(
                                            page, action, location
                                        )
                                        # Return a combined result
                                        cookies_list = await context.cookies()
                                        formatted_cookies = [
                                            {
                                                "name": c["name"],
                                                "value": c["value"],
                                                "domain": c["domain"],
                                                "path": c["path"],
                                            }
                                            for c in cookies_list
                                        ]
                                        await browser.close()
                                        return {
                                            "status": "success",
                                            "cookies": formatted_cookies,
                                            "attendance_result": attendance_res,
                                        }
                                    else:
                                        # When no action is passed, return ONLY the formatted cookies list
                                        cookies_list = await context.cookies()
                                        formatted_cookies = [
                                            {"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c["path"]}
                                            for c in cookies_list
                                        ]
                                        await browser.close()
                                        return formatted_cookies
                                else:
                                    log(
                                        "WARN",
                                        "event=waf_browser status=login_pending message='Manual intervention might be needed'",
                                    )
                                    # We wait a bit more just in case
                                    await page.wait_for_timeout(5000)

                    # 3. Extract final cookies
                    log("SUCCESS", "event=waf_browser status=extracting_cookies")
                    cookies_list = await context.cookies()

                    # Convert to our TypedDict format
                    formatted_cookies = []
                    for c in cookies_list:
                        formatted_cookies.append(
                            {"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c["path"]}
                        )

                    await browser.close()
                    return formatted_cookies

        except Exception as e:
            await portal_circuit_breaker.record_failure(f"browser_bridge_exception:{e}")
            log("ERROR", f"event=waf_browser exception={e}")
            return None

    async def _perform_attendance_in_browser(self, page, action, location=None):
        """
        Executes the final attendance submission directly within an active Playwright page.
        Guarantees session continuity for WAF-protected environments.
        """
        try:
            # 1. Navigate to Dashboard explicitly
            await page.goto(f"{self.base_url}/home/dashboard")
            await page.wait_for_load_state("networkidle")

            # 2. Extract CSRF token from page
            csrf_token = await page.eval_on_selector('meta[name="csrf-token"]', "el => el.content")
            if not csrf_token:
                log("ERROR", "event=browser_attendance status=failed message='CSRF Token not found'")
                return False

            # 3. Perform the AJAX POST via page.evaluate to stay in the same session
            # This is the most reliable way as it uses the browser's own fetch mechanism
            log("INFO", f"event=browser_attendance status=submitting action={action}")

            # Prepare payload
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
            log("INFO", f"event=browser_attendance status=result data={result}")

            if result.get("status") == "success" or "berhasil" in str(result).lower():
                return True
            return False

        except Exception as e:
            log("ERROR", f"event=browser_attendance exception={e}")
            return False
