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
        self.client: AsyncSession = AsyncSession(impersonate="chrome120", verify=False, timeout=30, proxy=self.proxy)
        self.client.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        })

    async def login(self, username, password) -> dict[str, Any]:
        try:
            # 1. Initial request to demo-sso to get redirect to Keycloak
            resp = await self.client.get(self.base_url, allow_redirects=True)
            if "login" not in str(resp.url).lower():
                 # Maybe already logged in?
                 if "Selamat anda berhasil login" in resp.text:
                     return {"status": "success", "message": "Already logged in"}
            
            # 2. Extract login form action from Keycloak page
            soup = BeautifulSoup(resp.text, "html.parser")
            form = soup.find("form", id="kc-form-login")
            if not form:
                return {"status": "failed", "message": "Keycloak login form not found"}
            
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
