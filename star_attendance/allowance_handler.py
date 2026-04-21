import asyncio
import logging
import time
from datetime import datetime
from typing import Any, cast

from star_attendance.login_handler import LoginHandler, CookieData
from star_attendance.core.config import settings

logger = logging.getLogger("allowance")

class AllowanceHandler:
    def __init__(self, login_handler: LoginHandler):
        self.login_handler = login_handler
        self.base_url = login_handler.base_url
        self.client = login_handler.client

    @staticmethod
    def get_current_period_code() -> tuple[str, int]:
        from star_attendance.core.timeutils import now_local
        now = now_local()
        day = now.day
        if day >= 15:
            start_month = now.month
            end_month = now.month + 1
            year = now.year
            if end_month > 12:
                end_month = 1
        else:
            start_month = now.month - 1
            end_month = now.month
            year = now.year
            if start_month < 1:
                start_month = 12
                year -= 1
        
        period_code = f"15{start_month:02d}_14{end_month:02d}"
        return period_code, year

    @staticmethod
    def format_period_code(period_code: str) -> str:
        """
        Converts 1503_1404 to 15 Mar - 14 Apr
        """
        if "_" not in period_code:
            return period_code
        
        months = [
            "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", 
            "Jul", "Agu", "Sep", "Okt", "Nov", "Des"
        ]
        try:
            start, end = period_code.split("_")
            start_day = int(start[:2])
            start_month = int(start[2:])
            end_day = int(end[:2])
            end_month = int(end[2:])
            
            return f"{start_day} {months[start_month-1]} - {end_day} {months[end_month-1]}"
        except (ValueError, IndexError):
            return period_code

    async def fetch_allowance_data(self, period_code: str | None = None, year: int | None = None) -> dict[str, Any]:
        if period_code is None or year is None:
            period_code, year = self.get_current_period_code()

        logger.info(f"event=fetch_allowance status=start period={period_code} year={year}")
        
        # 1. Access the allowance index page to get TKV and UUID
        allowance_url = f"{self.base_url}/budget/personal_allowance"
        try:
            resp = await self.client.get(allowance_url)
            if resp.status_code != 200:
                return {"status": "failed", "message": f"HTTP {resp.status_code}"}
            
            html = resp.text
            # Extract UUID from data URL in script or HTML
            # Match pattern like /budget/personal_allowance/data/UUID
            import re
            uuid_match = re.search(r'/budget/personal_allowance/data/([a-z0-9-]+)', html)
            if not uuid_match:
                # If not found, maybe it's the dashboard redirect
                if "login" in str(resp.url).lower():
                    return {"status": "failed", "message": "session_expired"}
                return {"status": "failed", "message": "uuid_not_found"}
            
            target_uuid = uuid_match.group(1)
            
            # Extract TKV
            tkv_match = re.search(r'name="tkv" value="([^"]+)"', html)
            if not tkv_match:
                # Some pages use a different way to store TKV or KV-TOKEN
                tkv_match = re.search(r'var tkv = "([^"]+)"', html)
            
            tkv = tkv_match.group(1) if tkv_match else ""
            
            # 2. Extract KV-TOKEN from headers/meta if needed
            kv_token_match = re.search(r'meta name="csrf-token" content="([^"]+)"', html)
            kv_token = kv_token_match.group(1) if kv_token_match else ""

            # 3. Perform POST request with multipart/form-data
            # We use a boundary because the server expects it
            boundary = "----WebKitFormBoundaryStarAsnAllowance"
            body = (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="tkv"\r\n\r\n'
                f"{tkv}\r\n"
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="year"\r\n\r\n'
                f"{year}\r\n"
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="allowance_period_code"\r\n\r\n'
                f"{period_code}\r\n"
                f"--{boundary}--\r\n"
            )

            data_url = f"{self.base_url}/budget/personal_allowance/data/{target_uuid}"
            headers = {
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": allowance_url,
            }
            if kv_token:
                headers["KV-TOKEN"] = kv_token

            logger.info(f"event=fetch_allowance status=requesting url={data_url}")
            resp_data = await self.client.post(data_url, data=body.encode("utf-8"), headers=headers)
            
            if resp_data.status_code != 200:
                return {"status": "failed", "message": f"Data fetch failure: HTTP {resp_data.status_code}"}
            
            return resp_data.json()

        except Exception as e:
            logger.error(f"event=fetch_allowance status=error message='{e}'")
            return {"status": "failed", "message": str(e)}

async def sync_user_allowance(nip: str) -> dict[str, Any]:
    """
    High-level function to sync user allowance data from portal to Supabase.
    Includes automatic session recovery (login) if needed.
    """
    from star_attendance.runtime import get_store
    store = get_store()
    
    user_cred = store.get_user_data(nip)
    if not user_cred:
        return {"status": "failed", "message": "User data not found."}
    
    password = user_cred.get("password")
    proxy = cast(str | None, user_cred.get("proxy"))
    
    # 1. Setup Handler
    handler = LoginHandler(proxy=proxy)
    
    # 2. Try with existing session first
    session_data = store.get_user_session(nip)
    if session_data and "cookies" in session_data:
        for name, value in session_data["cookies"].items():
            handler.client.cookies.set(name, value, domain="star-asn.kemenimipas.go.id")
        
        allowance_handler = AllowanceHandler(handler)
        period_code, year = allowance_handler.get_current_period_code()
        
        result = await allowance_handler.fetch_allowance_data(period_code, year)
        if result.get("status") == "success":
            store.save_personal_allowance(nip, period_code, result["data"])
            return {"status": "success", "period": period_code, "count": len(result["data"])}
        
        # If failed due to something else than session, or session expired, proceed to login
        if result.get("message") != "session_expired":
             return result

    # 3. Perform Full Login (Session missing or expired)
    if not password:
        return {"status": "failed", "message": "Password is required for session recovery."}
    
    login_res = await handler.login(nip, password)
    if login_res.get("status") != "success":
        return {"status": "failed", "message": f"Login failed: {login_res.get('message')}"}
    
    # 4. Retry Fetch with new session
    allowance_handler = AllowanceHandler(handler)
    period_code, year = allowance_handler.get_current_period_code()
    result = await allowance_handler.fetch_allowance_data(period_code, year)
    
    if result.get("status") == "success" and "data" in result:
        store.save_personal_allowance(nip, period_code, result["data"])
        return {"status": "success", "period": period_code, "count": len(result["data"])}
    
    return result
