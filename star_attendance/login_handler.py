import asyncio
import threading
import time
import warnings
import uuid
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
    _last_browser_tkv: str | None = None # Captured from browser during bypass

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
        if LoginHandler._dddd is None:
            pass  # Will be loaded on first captcha solve

        self.captcha_mode = settings.CAPTCHA_MODE.lower()
        self.captcha_require_alpha = True  
        self.captcha_max_digits = 3  

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

    async def _get_two_best_candidates(self, image_bytes, min_conf):
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
        if not code or len(code) != 6:
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
            image_bytes = await self._fetch_captcha_bytes()
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
            res = str(res).upper()
            if self._is_valid_code(res):
                return {"prediction": res, "confidence": 1.0, "error": None}
            else:
                variant = self.preprocess_image(image_bytes)
                if variant is not None:
                    _, encoded_img = cv2.imencode(".png", variant)
                    res2 = self.ocr.classification(encoded_img.tobytes())
                    res2 = str(res2).upper()
                    if self._is_valid_code(res2):
                        return {"prediction": res2, "confidence": 0.9, "error": None}
                return {"prediction": res, "confidence": 0.5, "error": "invalid_code_format"}
        except Exception as e:
            return {"prediction": None, "confidence": None, "error": f"exception:{e}"}

    _public_ip_cache: str | None = None
    _public_ip_expiry: float = 0.0

    async def get_public_ip(self) -> str:
        now = time.time()
        if LoginHandler._public_ip_cache and now < LoginHandler._public_ip_expiry:
            return LoginHandler._public_ip_cache
        try:
            for url in ["https://api.ipify.org", "https://ifconfig.me/ip", "https://checkip.amazonaws.com"]:
                try:
                    resp = await self.client.get(url, timeout=3)
                    if resp.status_code == 200:
                        LoginHandler._public_ip_cache = resp.text.strip()
                        LoginHandler._public_ip_expiry = now + 300  
                        return LoginHandler._public_ip_cache
                except Exception: continue
            return LoginHandler._public_ip_cache or "UNKNOWN"
        except Exception: return "ERROR"

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
                start_time = datetime.now()
                r_init = await self.client.get(login_url)

                if 'data-layout="vertical"' in r_init.text and 'class="user-name-text"' in r_init.text:
                    log("SUCCESS", "event=session_id status=pre_authenticated")
                    await portal_circuit_breaker.record_success()
                    return {
                        "status": "success",
                        "cookies": self.client.cookies.get_dict(),
                        "response_time": (datetime.now() - start_time).total_seconds(),
                        "session_source": "PERSISTENT",
                    }

                if 'name="tkv"' not in r_init.text:
                    log("WARN", "event=tkv status=missing action=escalating_to_browser")
                    return await self._run_browser_login_fallback(username, password, action, location, status_callback, start_time)

                # --- TKV extraction ---
                try:
                    tkv = r_init.text.split('name="tkv" value="')[1].split('"')[0]
                except Exception:
                    continue

                # 2. Solve Captcha
                image_bytes = await self._fetch_captcha_bytes()
                if image_bytes is None: continue
                
                candidates = await self._get_two_best_candidates(image_bytes, settings.CAPTCHA_MIN_CONF)
                if not candidates: continue
                
                for index, (conf, code, mode) in enumerate(candidates, start=1):
                    log("INFO", f"event=login_attempt attempt={attempt}.{index} captcha={Fore.YELLOW}{code}")
                    if status_callback:
                        await status_callback(f"🧩 Memecahkan Captcha: <b>{code}</b>")

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
                            }
                        else:
                            msg = res.get("message", "").lower()
                            if "captcha" in msg: continue
                            if any(k in msg for k in ["belum terdaftar", "salah nip", "salah password", "login gagal"]):
                                return {"status": "terminal", "message": res.get("message")}
                            failure_reason = res.get("message") or "login_failed"
                            return {"status": "failed", "message": failure_reason}
                    except:
                        if "dashboard" in str(r_post.url):
                            log("SUCCESS", "event=login status=success redirect=true")
                            return {"status": "success", "cookies": self.client.cookies.get_dict(), "response_time": response_time}

            except Exception as e:
                log("ERROR", f"event=login exception={e}")
                await asyncio.sleep(1)

        return await self._run_browser_login_fallback(username, password, action, location, status_callback)

    async def _run_browser_login_fallback(self, username, password, action, location, status_callback, start_time=None):
        log("STEP", "event=emergency_bridge status=launching")
        if status_callback:
            await status_callback("🌐 Menjalankan fallback login browser penuh...")

        res_browser = await self._solve_waf_challenge_via_browser(
            username=username, password=password, action=action, location=location
        )
        if isinstance(res_browser, dict) and res_browser.get("status") == "success":
            await portal_circuit_breaker.record_success()
            return {
                "status": "success",
                "cookies": res_browser.get("cookies"),
                "attendance_result": res_browser.get("attendance_result"),
                "session_source": "BRIDGE",
            }
        return {"status": "failed", "message": "Browser bridge login failed"}

    async def _solve_waf_challenge_via_browser(self, username=None, password=None, action=None, location=None, status_callback=None):
        try:
            from playwright.async_api import async_playwright
        except ImportError: return None

        async with browser_bridge_semaphore:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=settings.WAF_BROWSER_HEADLESS, 
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
                )
                context = await browser.new_context(user_agent=self.user_agent, viewport={"width": 1280, "height": 720})
                page = await context.new_page()
                
                await page.goto(f"{self.base_url}/authentication/login", wait_until="commit", timeout=60000)
                
                try:
                    await page.wait_for_selector('input[name="tkv"]', state="attached", timeout=45000)
                    tkv_value = await page.eval_on_selector('input[name="tkv"]', "el => el.value")
                    LoginHandler._last_browser_tkv = tkv_value
                    log("SUCCESS", "event=waf_browser status=ready")
                except Exception as e:
                    log("ERROR", f"event=waf_browser status=timeout error={e}")
                    await browser.close()
                    return None

                if not username or not password:
                    cookies_list = await context.cookies()
                    formatted = [{"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c["path"]} for c in cookies_list]
                    await browser.close()
                    return {"status": "success", "cookies": formatted}

                attendance_res = None
                for login_attempt in range(1, 6):
                    try:
                        await page.locator('input[name="username"]').fill(username)
                        await page.locator('input[name="password"]').fill(password)
                        
                        await page.wait_for_load_state("networkidle")
                        captcha_img = await page.wait_for_selector('img[src*="captcha"]', state="visible", timeout=15000)
                        await captcha_img.scroll_into_view_if_needed()
                        await asyncio.sleep(1)
                        img_bytes = await captcha_img.screenshot()
                        
                        ocr_candidates = await self._get_two_best_candidates(img_bytes, 0.2)
                        if not ocr_candidates:
                            await page.click('img[src*="captcha"]')
                            await asyncio.sleep(2)
                            continue
                        
                        code = ocr_candidates[0][1]
                        await page.locator('input[name="kv-captcha"]').fill(code)
                        await page.locator('button[type="submit"]').click(force=True)

                        await page.wait_for_function(
                            "() => window.location.href.includes('dashboard') || document.body.innerText.includes('Dashboard') || document.body.innerText.includes('Statistik')",
                            timeout=15000
                        )
                        log("SUCCESS", "event=waf_browser status=dashboard_reached")
                        if action:
                            attendance_res = await self._perform_attendance_in_browser(page, action, location)
                        break
                    except Exception:
                        if login_attempt == 5:
                            await page.screenshot(path=f"/tmp/failed_{username}.png")
                        try:
                            await page.click('img[src*="captcha"]', timeout=3000)
                            await asyncio.sleep(2)
                        except: pass

                cookies_list = await context.cookies()
                formatted = [{"name": c["name"], "value": c["value"], "domain": c["domain"], "path": c["path"]} for c in cookies_list]
                
                if username:
                    try:
                        from star_attendance.runtime import get_store
                        store = get_store()
                        db_user = store.get_user_data(username)
                        if db_user:
                            store.save_user_session(db_user["id"], {c["name"]: c["value"] for c in cookies_list}, nip=username)
                    except: pass
                
                await browser.close()
                return {"status": "success", "cookies": formatted, "attendance_result": attendance_res}

    async def _perform_attendance_in_browser(self, page, action, location=None):
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
            log("INFO", f"event=browser_attendance status=result data={result}")
            return result.get("status") == "success" or "berhasil" in str(result).lower()
        except Exception: return False
