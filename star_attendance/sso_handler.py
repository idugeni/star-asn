import asyncio
import logging
import re
from typing import Any, cast

from curl_cffi.requests import AsyncSession
from bs4 import BeautifulSoup

from star_attendance.core.config import settings
from star_attendance.core.utils import log as core_log

logger = logging.getLogger("sso")

class SSOHandler:
    def __init__(self, proxy: str | None = None):
        self.base_url = "https://demo-sso.kemenimipas.go.id"
        self.sso_url = "https://sso.kemenimipas.go.id"
        self.proxy = proxy
        
        # EXACT ALIGNMENT WITH STAR-ASN LOGIN SYSTEM
        from star_attendance.login_handler import MASTER_IDENTITY_HEADERS, MASTER_IDENTITY_UA
        self.client: AsyncSession = AsyncSession(
            impersonate="chrome120", 
            verify=False, 
            timeout=30, 
            proxy=self.proxy
        )
        self.client.headers.update(MASTER_IDENTITY_HEADERS)
        self.client.headers["User-Agent"] = MASTER_IDENTITY_UA

    async def login(self, username, password) -> dict[str, Any]:
        try:
            # 1. Clear cookies to ensure fresh session (Same as Attendance Engine)
            self.client.cookies.clear()
            
            # 2. Initial request to trigger login flow
            resp = await self.client.get(self.base_url, allow_redirects=True)
            
            # 3. WAF DETECTION (Same logic as LoginHandler.is_waf_interstitial)
            if any(marker in resp.text.lower() for marker in ["security check", "checking your browser", "waf", "document.cookie='waf_token"]):
                logger.info("SSO: Star-ASN Style WAF Challenge detected. Applying Master Bypass...")
                # Apply global WAF cookies if available (shared with attendance system)
                from star_attendance.login_handler import LoginHandler
                if LoginHandler.shared_waf_cookies:
                    for c in LoginHandler.shared_waf_cookies:
                        self.client.cookies.set(c["name"], c["value"], domain="demo-sso.kemenimipas.go.id")
                
                # Manual injection for this specific portal
                self.client.cookies.set("waf_token", "valid", domain="demo-sso.kemenimipas.go.id")
                
                # Retry with hardened headers
                resp = await self.client.get(self.base_url, allow_redirects=True)

            # 4. Handle Redirection to Keycloak
            if "login" not in str(resp.url).lower() and "kc-form-login" not in resp.text:
                logger.info("SSO: Triggering explicit OAuth bridge...")
                resp = await self.client.get(f"{self.base_url}/OAuth/me", allow_redirects=True)

            # 4. Final verification of login form
            if "login" not in str(resp.url).lower() and "kc-form-login" not in resp.text:
                # One last attempt: visit sso center directly if we can't get redirected
                if "sso.kemenimipas.go.id" not in str(resp.url):
                    logger.warning("SSO: Redirect to Keycloak failed. Is the server reachable?")
                    return {"status": "failed", "message": "Server SSO Pusat (Keycloak) tidak merespons atau sedang Maintenance."}

            # Extract login form action from Keycloak page
            soup = BeautifulSoup(resp.text, "html.parser")
            form = soup.find("form", id="kc-form-login")
            if not form:
                # Try finding by action name as fallback
                form = soup.find("form", action=re.compile(r"login-actions/authenticate"))
            
            if not form:
                snippet = resp.text[:200].replace("\n", " ")
                logger.error(f"SSO: Form not found. URL: {resp.url} Snippet: {snippet}")
                return {"status": "failed", "message": "Form login Keycloak tidak ditemukan. Silakan cek koneksi ke server pusat."}
            
            action_url = cast(str, form.get("action"))
            
            # 3. Perform login
            payload = {
                "username": username,
                "password": password,
                "credentialId": ""
            }
            
            resp_post = await self.client.post(action_url, data=payload, allow_redirects=True)
            
            if "Selamat anda berhasil login" in resp_post.text:
                return {"status": "success", "message": "Login successful"}
            
            if "Invalid username or password" in resp_post.text:
                return {"status": "failed", "message": "Username atau password SSO salah."}
            
            return {"status": "failed", "message": "Gagal login ke SSO (Unknown error)"}
            
        except Exception as e:
            core_log("ERROR", f"SSO Login Error: {e}", scope="SSO")
            return {"status": "failed", "message": str(e)}

    async def fetch_profile(self) -> dict[str, Any]:
        try:
            # The 'Me' page displays data in a pre tag or similar
            resp = await self.client.get(f"{self.base_url}/OAuth/me")
            if resp.status_code == 200:
                # Based on subagent, it might be JSON or HTML with data
                try:
                    return {"status": "success", "data": resp.json()}
                except Exception:
                    # Fallback parse from HTML if it's just a dump
                    text = resp.text
                    data = {}
                    
                    # Comprehensive regex matching for PHP array dump format
                    patterns = {
                        "nip": r"\[(?:employee_number|nip)\]\s*=>\s*\"?(\d+)\"?",
                        "nama": r"\[name\]\s*=>\s*\"?([^\"\n\r]+)\"?",
                        "nama_upt": r"\[organization\]\s*=>\s*\"?([^\"\n\r]+)\"?",
                        "jabatan": r"\[position\]\s*=>\s*\"?([^\"\n\r]+)\"?",
                        "divisi": r"\[division\]\s*=>\s*\"?([^\"\n\r]+)\"?",
                        "email": r"\[email\]\s*=>\s*\"?([^\"\n\r]+)\"?",
                        "pangkat": r"\[employee_group\]\s*=>\s*\"?([^\"\n\r]+)\"?",
                        "tgl_lahir": r"\[birth_date\]\s*=>\s*\"?([\d\-]+)\"?",
                    }
                    
                    for key, pattern in patterns.items():
                        match = re.search(pattern, text)
                        if match:
                            data[key] = match.group(1).strip()
                    
                    if data:
                        return {"status": "success", "data": data}
                    
                    return {"status": "failed", "message": "Could not parse profile data"}
            return {"status": "failed", "message": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"status": "failed", "message": str(e)}

    async def close(self):
        await self.client.close()

async def sync_sso_data(nip: str, password: str) -> dict[str, Any]:
    handler = SSOHandler()
    try:
        login_res = await handler.login(nip, password)
        if login_res["status"] == "success":
            profile_res = await handler.fetch_profile()
            return profile_res
        return login_res
    finally:
        await handler.close()
