import httpx

from star_attendance.core.config import settings


class InternalAPIClient:
    def __init__(self) -> None:
        self.base_url = settings.INTERNAL_API_URL.rstrip("/")
        self.token = settings.resolved_internal_api_token
        self.timeout = 10.0

    def headers(self) -> dict[str, str]:
        return {"X-Internal-Token": self.token}

    async def healthz(self) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/healthz", headers=self.headers())
            response.raise_for_status()
            return response.json()

    async def get_scheduler_status(self) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/internal/scheduler/status",
                headers=self.headers(),
            )
            response.raise_for_status()
            return response.json()

    async def restart_scheduler(self) -> dict:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/internal/scheduler/restart",
                headers=self.headers(),
            )
            response.raise_for_status()
            return response.json()
