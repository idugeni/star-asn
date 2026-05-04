import asyncio
import logging
import re
from typing import Any

from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession

from star_attendance.core.config import MASTER_IDENTITY_HEADERS, MASTER_IDENTITY_UA, settings

logger = logging.getLogger("sso")


def log(level, msg, scope="SSO"):
    from star_attendance.core.utils import log as core_log

    core_log(level, msg, scope=scope)


class SSOHandler:
    def __init__(self, mode: str = "star-asn", proxy: str | None = None):
        """
        mode: "star-asn" for attendance login, "demo-sso" for profile sync.
        """
        self.mode = mode
        if mode == "demo-sso":
            self.base_url = "https://demo-sso.kemenimipas.go.id"
            self.proxy = None  # Bypass proxy for Demo-SSO to prevent timeout
        else:
            self.base_url = "https://star-asn.kemenimipas.go.id"
            self.proxy = proxy or settings.resolved_proxy_url

        self.client: AsyncSession = AsyncSession(impersonate="chrome120", timeout=30, proxy=self.proxy, verify=False)
        self.client.headers.update(MASTER_IDENTITY_HEADERS)
        self.client.headers["User-Agent"] = MASTER_IDENTITY_UA

    async def login(
        self, username, password, action: str | None = None, location: str | None = None, on_progress=None
    ) -> dict[str, Any]:
        """
        Main entry point for SSO login.
        """
        if self.mode == "demo-sso":
            return await self._login_demo_sso(username, password, on_progress)
        else:
            return await self._login_star_asn(username, password, action, location, on_progress)

    async def _login_star_asn(self, username, password, action=None, location=None, on_progress=None) -> dict[str, Any]:
        """
        SSO Login flow for Star ASN (Attendance).
        """
        try:
            if on_progress:
                await on_progress("🔍 Memulai alur SSO Star-ASN...")

            # MASTER BYPASS: Pre-inject WAF token
            # MASTER BYPASS: Pre-inject WAF token
            self.client.cookies.set("waf_token", "valid", domain="star-asn.kemenimipas.go.id")

            sso_init_url = f"{self.base_url}/authentication/sso/login"
            resp = await self.client.get(sso_init_url, allow_redirects=True)

            # ONE-WAY FAST DETECTION
            if "waf_token" in resp.text:
                log("WARN", "WAF detected (token bypass ignored). Falling back to browser...")
                return await self.login_via_browser(username, password, action, location, on_progress)

            # Keycloak Form
            return await self._submit_keycloak(resp, username, password, on_progress)

        except Exception as e:
            log("ERROR", f"Star-ASN SSO Exception: {e}")
            return {"status": "failed", "message": f"Error SSO Star-ASN: {str(e)}"}

    async def _login_demo_sso(self, username, password, on_progress=None) -> dict[str, Any]:
        """
        SSO Login flow for Demo-SSO (Profile Sync).
        """
        try:
            if on_progress:
                await on_progress("🔍 Memulai alur SSO Demo-SSO (Data Sync)...")

            # MASTER BYPASS: Pre-inject WAF token
            self.client.cookies.set("waf_token", "valid", domain="demo-sso.kemenimipas.go.id")

            demo_sso_init_url = f"{self.base_url}/OAuth/login"
            resp = await self.client.get(demo_sso_init_url, allow_redirects=True)

            # ONE-WAY FAST DETECTION
            if "waf_token" in resp.text:
                log("WARN", "WAF detected on Demo-SSO. Falling back to browser...")
                return await self.login_via_browser(username, password, on_progress=on_progress)

            if "Selamat anda berhasil login" in resp.text:
                return {
                    "status": "success",
                    "message": "Already logged in to Demo-SSO",
                    "cookies": self.client.cookies.get_dict(),
                }

            # Keycloak Form
            return await self._submit_keycloak(resp, username, password, on_progress)

        except Exception as e:
            log("ERROR", f"Demo-SSO Exception: {e}")
            return {"status": "failed", "message": f"Error Demo-SSO: {str(e)}"}

    async def _submit_keycloak(self, resp, username, password, on_progress=None) -> dict[str, Any]:
        """
        Helper to submit credentials to the central Keycloak form.
        """
        soup = BeautifulSoup(resp.text, "html.parser")
        form = soup.find("form", id="kc-form-login")

        if not form:
            # Fallback for different themes
            form = soup.find("form", action=re.compile(r"login-actions/authenticate"))

        if not form:
            if "dashboard" in str(resp.url).lower() or "Selamat anda berhasil login" in resp.text:
                return {"status": "success", "message": "Sudah login.", "cookies": self.client.cookies.get_dict()}

            log("ERROR", f"Keycloak form not found. URL: {resp.url}")
            return {"status": "failed", "message": "Gagal menemukan form login Keycloak."}

        action_url = form.get("action")
        if not action_url:
            return {"status": "failed", "message": "Gagal menemukan action URL Keycloak."}

        if on_progress:
            await on_progress("🔑 Mengirim kredensial ke SSO Pusat...")

        payload = {"username": username, "password": password, "credentialId": ""}

        self.client.headers.update(
            {
                "Referer": str(resp.url),
                "Origin": "https://sso.kemenimipas.go.id",
                "Content-Type": "application/x-www-form-urlencoded",
            }
        )

        resp_post = await self.client.post(str(action_url), data=payload, allow_redirects=True)

        # Verify success based on mode
        final_url = str(resp_post.url).lower()
        content = resp_post.text

        if self.mode == "star-asn":
            if "star-asn.kemenimipas.go.id" in final_url and "dashboard" in final_url:
                return {
                    "status": "success",
                    "message": "Login SSO Star-ASN berhasil.",
                    "cookies": self.client.cookies.get_dict(),
                    "session_source": "SSO_HTTP",
                }
        else:  # demo-sso
            if "Selamat anda berhasil login" in content or "demo-sso.kemenimipas.go.id" in final_url:
                return {
                    "status": "success",
                    "message": "Login SSO Demo-SSO berhasil.",
                    "cookies": self.client.cookies.get_dict(),
                }

        if "invalid username or password" in content.lower():
            return {"status": "failed", "message": "NIP atau password SSO salah."}

        log("ERROR", f"SSO flow interrupted. Final URL: {resp_post.url}")
        return {"status": "failed", "message": "Alur SSO terhenti. Gunakan browser fallback."}

    async def fetch_profile(self) -> dict[str, Any]:
        """
        Fetches employee profile data from Demo-SSO.
        """
        try:
            if self.mode != "demo-sso":
                # Ensure we are in demo-sso mode for profile sync
                log("WARN", "fetch_profile called in star-asn mode. Switching temporarily...")
                # We'd need to re-login to demo-sso, but usually this is called after _login_demo_sso

            resp = await self.client.get("https://demo-sso.kemenimipas.go.id/OAuth/me")
            if resp.status_code == 200:
                try:
                    # Try JSON first
                    return {"status": "success", "data": resp.json()}
                except:
                    # Fallback parse from PHP dump format
                    text = resp.text
                    data = {}
                    patterns = {
                        "nip": r"\[(?:employee_number|nip)\]\s*=>\s*\"?(\d+)\"?",
                        "nama": r"\[name\]\s*=>\s*\"?([^\"\n\r]+)\"?",
                        "nama_upt": r"\[organization\]\s*=>\s*\"?([^\"\n\r]+)\"?",
                        "jabatan": r"\[position\]\s*=>\s*\"?([^\"\n\r]+)\"?",
                        "divisi": r"\[division\]\s*=>\s*\"?([^\"\n\r]+)\"?",
                        "email": r"\[email\]\s*=>\s*\"?([^\"\n\r]+)\"?",
                        "pangkat": r"\[employee_group\]\s*=>\s*\"?([^\"\n\r]+)\"?",
                        "birth_date": r"\[birth_date\]\s*=>\s*\"?([\d\-]+)\"?",
                    }
                    for key, pattern in patterns.items():
                        match = re.search(pattern, text)
                        if match:
                            data[key] = match.group(1).strip()

                    if data:
                        return {"status": "success", "data": data}
                    
                    log("ERROR", f"/OAuth/me returned HTTP 200 but no data parsed. Content snippet: {text[:500]}")

            return {"status": "failed", "message": f"Gagal mengambil profil (HTTP {resp.status_code})"}
        except Exception as e:
            return {"status": "failed", "message": str(e)}

    async def login_via_browser(
        self, username, password, action=None, location=None, on_progress=None
    ) -> dict[str, Any]:
        """
        Fallback SSO login using Playwright.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return {"status": "failed", "message": "Playwright tidak tersedia."}

        try:
            async with async_playwright() as p:
                from typing import Any
                launch_opts: dict[str, Any] = {
                    "headless": settings.WAF_BROWSER_HEADLESS,
                    "args": ["--no-sandbox", "--disable-blink-features=AutomationControlled"],
                }
                if self.proxy:
                    from urllib.parse import urlparse

                    parsed = urlparse(self.proxy)
                    launch_opts["proxy"] = {
                        "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                        "username": parsed.username,
                        "password": parsed.password,
                    }

                browser = await p.chromium.launch(**launch_opts)  # pyright: ignore[reportArgumentType]
                context = await browser.new_context(user_agent=MASTER_IDENTITY_UA)
                page = await context.new_page()

                if on_progress:
                    await on_progress(f"🌐 Membuka {self.base_url} via Browser...")

                # Start at the initiator
                if self.mode == "star-asn":
                    await page.goto(f"{self.base_url}/authentication/sso/login", wait_until="networkidle")
                else:
                    await page.goto(self.base_url, wait_until="networkidle")

                # Wait for Keycloak form
                try:
                    await page.wait_for_selector('input[name="username"]', timeout=10000)
                except:
                    # Maybe already logged in
                    if "dashboard" in page.url or "Selamat anda berhasil login" in await page.content():
                        pass
                    else:
                        await browser.close()
                        return {"status": "failed", "message": "Timeout menunggu form SSO di browser."}

                if "username" in await page.content():
                    if on_progress:
                        await on_progress("🔐 Mengisi kredensial SSO...")
                    await page.fill('input[name="username"]', username)
                    await page.fill('input[name="password"]', password)

                    # Click login button
                    submit_btn = await page.query_selector('input[name="login"]') or await page.query_selector(
                        "#kc-login"
                    )
                    if submit_btn:
                        await submit_btn.click()
                    else:
                        await page.keyboard.press("Enter")

                    # Wait for redirect
                    if self.mode == "star-asn":
                        await page.wait_for_url(f"**/{self.base_url.split('//')[-1]}/**", timeout=15000)
                    else:
                        await asyncio.sleep(5)  # Wait for demo-sso message

                # Check result
                success_flag = False
                if self.mode == "star-asn":
                    if "dashboard" in page.url:
                        success_flag = True
                        # Perform attendance if requested
                        if action and location:
                            if on_progress:
                                await on_progress(f"🚀 Melakukan absensi {action}...")
                            from star_attendance.login_handler import LoginHandler

                            lh = LoginHandler()
                            # Use page context to perform attendance
                            # (This requires a bridge method or just manual navigation)
                            # For now, we return cookies and let AttendanceEngine handle it
                            pass
                else:
                    if "Selamat anda berhasil login" in await page.content():
                        success_flag = True

                if success_flag:
                    cookies = await context.cookies()
                    await browser.close()
                    return {
                        "status": "success",
                        "message": f"Login SSO {self.mode} Browser berhasil.",
                        "cookies": {str(c.get("name", "")): str(c.get("value", "")) for c in cookies},
                        "session_source": "SSO_BROWSER",
                    }

                await browser.close()
                return {"status": "failed", "message": f"Gagal mencapai target {self.mode} via Browser."}
        except Exception as e:
            log("ERROR", f"SSO Browser Exception: {e}")
            return {"status": "failed", "message": f"Browser Error: {str(e)}"}

    async def close(self):
        await self.client.close()


async def sync_sso_data(nip: str, password: str, on_progress=None) -> dict[str, Any]:
    """
    Profile synchronization wrapper.
    Always uses Demo-SSO as the data source.
    """
    handler = SSOHandler(mode="demo-sso")
    try:
        login_res = await handler.login(nip, password, on_progress=on_progress)
        if login_res["status"] == "success":
            return await handler.fetch_profile()
        return login_res
    finally:
        await handler.close()
