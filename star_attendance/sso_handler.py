import re
import logging
from typing import Any, cast
from bs4 import BeautifulSoup
from curl_cffi.requests import AsyncSession
from star_attendance.core.config import MASTER_IDENTITY_HEADERS, MASTER_IDENTITY_UA

logger = logging.getLogger(__name__)

def core_log(level, msg, scope="CORE"):
    logger.log(getattr(logging, level), f"[{scope}] {msg}")

class SSOHandler:
    def __init__(self, proxy: str | None = None):
        self.base_url = "https://demo-sso.kemenimipas.go.id"
        self.proxy = proxy
        self.client: AsyncSession = AsyncSession(
            impersonate="chrome120", 
            timeout=30, 
            proxy=self.proxy
        )
        self.client.headers.update(MASTER_IDENTITY_HEADERS)
        self.client.headers["User-Agent"] = MASTER_IDENTITY_UA

    async def login(self, username, password, on_progress=None) -> dict[str, Any]:
        try:
            # 1. Clear cookies to ensure fresh session
            self.client.cookies.clear()
            
            # --- PHASE 1: INITIAL APP HANDSHAKE ---
            if on_progress: await on_progress("🔍 Inisialisasi Sesi Aplikasi...")
            
            # Update headers for initial request
            self.client.headers.update({
                "Referer": "https://demo-sso.kemenimipas.go.id/",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Dest": "document"
            })
            
            # Apply WAF cookies from master system
            from star_attendance.login_handler import LoginHandler
            if LoginHandler.shared_waf_cookies:
                for c in LoginHandler.shared_waf_cookies:
                    self.client.cookies.set(c["name"], c["value"], domain="demo-sso.kemenimipas.go.id")
            
            # Request login page to get the session and redirect
            resp = await self.client.get(f"{self.base_url}/OAuth/login", allow_redirects=True)
            
            # --- PHASE 2: IDENTITY PROVIDER (KEYCLOAK) ---
            if "sso.kemenimipas.go.id" not in str(resp.url):
                # If not redirected, try me page which usually triggers login
                resp = await self.client.get(f"{self.base_url}/OAuth/me", allow_redirects=True)

            soup = BeautifulSoup(resp.text, "html.parser")
            form = soup.find("form", id="kc-form-login") or soup.find("form", action=re.compile(r"login-actions/authenticate"))
            
            if not form:
                logger.error(f"SSO: Login form not found at {resp.url}. HTML size: {len(resp.text)}")
                return {"status": "failed", "message": "Form login SSO tidak ditemukan. Portal mungkin sedang sibuk atau WAF aktif."}
            
            if on_progress: await on_progress("🔑 Autentikasi Kemenimipas...")
            
            action_url = cast(str, form.get("action"))
            payload = {"username": username, "password": password, "credentialId": ""}
            
            # Update headers for cross-site POST to Keycloak
            self.client.headers.update({
                "Origin": "null",
                "Referer": str(resp.url),
                "Sec-Fetch-Site": "same-origin"
            })
            
            # Apply WAF cookies to identity provider domain too
            if LoginHandler.shared_waf_cookies:
                for c in LoginHandler.shared_waf_cookies:
                    self.client.cookies.set(c["name"], c["value"], domain="sso.kemenimipas.go.id")

            # Submit to Keycloak and follow redirects back to OAuth/callback
            resp_post = await self.client.post(action_url, data=payload, allow_redirects=True)
            
            # --- PHASE 3: VERIFICATION ---
            final_url = str(resp_post.url).lower()
            if "oauth/me" in final_url or "[nip]" in resp_post.text.lower() or "selamat anda berhasil login" in resp_post.text.lower():
                return {"status": "success", "message": "Login successful"}
            
            if "invalid username or password" in resp_post.text.lower():
                return {"status": "failed", "message": "NIP atau password SSO salah."}
            
            if "sso.kemenimipas.go.id" in final_url:
                return {"status": "failed", "message": "Gagal sinkronisasi: Autentikasi terhenti di server pusat."}
                
            return {"status": "failed", "message": "Gagal sinkronisasi: Alur OAuth tidak lengkap."}
            
        except Exception as e:
            core_log("ERROR", f"SSO Login Error: {e}", scope="SSO")
            return {"status": "failed", "message": f"Koneksi terputus: {str(e)}"}

    async def fetch_profile(self) -> dict[str, Any]:
        """
        Optimized profile fetch using targeted regex and key normalization matrix.
        """
        try:
            resp = await self.client.get(f"{self.base_url}/OAuth/me", allow_redirects=True)
            if resp.status_code != 200:
                return {"status": "failed", "message": f"Server SSO merespons HTTP {resp.status_code}"}

            text = resp.text
            raw_data = {}

            # 1. Direct JSON Fallback
            try:
                return {"status": "success", "data": resp.json()}
            except:
                pass

            # 2. Targeted PHP var_dump Extraction
            soup = BeautifulSoup(text, "html.parser")
            
            # Pattern for: ["key"]=> string(X) "value" OR ["key":protected]=> ...
            php_dump_pattern = r'\["([^"]+)"(?::\w+)?\]=>\s*(?:string\(\d+\)\s*)?"([^"]+)"'
            
            # Scan <pre> tags first (cleanest data)
            for pre in soup.find_all("pre"):
                pre_text = pre.get_text()
                if "employee_number" in pre_text.lower() or "nip" in pre_text.lower():
                    matches = re.findall(php_dump_pattern, pre_text)
                    for key, val in matches:
                        raw_data[key.lower()] = val.strip()
                    if raw_data.get("employee_number") or raw_data.get("nip"):
                        break

            # 3. Global extraction if <pre> didn't yield enough
            if not raw_data:
                # Remove noise before global scan
                for noise in soup(["script", "style", "link", "meta"]):
                    noise.decompose()
                matches = re.findall(php_dump_pattern, soup.get_text())
                for key, val in matches:
                    raw_data[key.lower()] = val.strip()

            # 4. Normalisasi Key Matrix ke format STAR-ASN
            profile = {}
            key_matrix = {
                "nip": ["employee_number", "nip", "user_id", "username"],
                "sso_sub": ["sub"],
                "nama": ["name", "display_name", "fullname"],
                "nama_upt": ["organization", "upt", "unit_kerja"],
                "divisi": ["division", "bidang", "seksi"],
                "jabatan": ["position", "jabatan"],
                "pangkat": ["employee_group", "pangkat", "golongan"],
                "birth_place": ["birth_place"],
                "birth_date": ["birth_date"],
                "email": ["email"]
            }

            for std_key, raw_keys in key_matrix.items():
                for raw_key in raw_keys:
                    if raw_key in raw_data:
                        profile[std_key] = raw_data[raw_key]
                        break

            # 5. Output Validation & Sanitization
            if profile.get("nip"):
                clean_nip = re.sub(r"\D", "", str(profile["nip"]))
                if len(clean_nip) >= 8:
                    profile["nip"] = clean_nip
                    return {"status": "success", "data": profile}

            snippet = text[:500].replace("\n", " ")
            logger.error(f"SSO: Final Parsing attempt failed. Response snippet: {snippet}")
            return {"status": "failed", "message": "Format data profil dari SSO Pusat tidak dikenali. Hubungi Admin."}

        except Exception as e:
            logger.error(f"SSO Fetch Error: {e}")
            return {"status": "failed", "message": f"Koneksi terputus: {str(e)}"}

    async def close(self):
        await self.client.close()

async def sync_sso_data(nip: str, password: str, on_progress=None) -> dict[str, Any]:
    handler = SSOHandler()
    try:
        if on_progress: await on_progress("🔍 Menghubungkan ke SSO Pusat...")
        login_res = await handler.login(nip, password, on_progress=on_progress)
        
        if login_res["status"] == "success":
            if on_progress: await on_progress("🛰️ Mengambil data profil...")
            profile_res = await handler.fetch_profile()
            return profile_res
            
        return login_res
    finally:
        await handler.close()
