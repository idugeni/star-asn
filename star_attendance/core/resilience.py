from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from star_attendance.core.config import settings
from star_attendance.core.timeutils import isoformat_local


@dataclass
class CircuitSnapshot:
    opened: bool
    failure_count: int
    opened_until: datetime | None
    reason: str | None


class PortalCircuitBreaker:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.failure_count = 0
        self.opened_until: datetime | None = None
        self.reason: str | None = None

    async def allow_request(self) -> bool:
        async with self.lock:
            if self.opened_until and datetime.now(UTC) < self.opened_until:
                return False
            if self.opened_until and datetime.now(UTC) >= self.opened_until:
                self.opened_until = None
                self.failure_count = 0
                self.reason = None
            return True

    async def record_success(self) -> None:
        async with self.lock:
            self.failure_count = 0
            self.opened_until = None
            self.reason = None

    async def record_failure(self, reason: str) -> None:
        async with self.lock:
            self.failure_count += 1
            self.reason = reason
            if self.failure_count >= settings.PORTAL_CIRCUIT_BREAKER_THRESHOLD:
                self.opened_until = datetime.now(UTC) + timedelta(
                    seconds=settings.PORTAL_CIRCUIT_BREAKER_COOLDOWN_SECONDS
                )

    async def snapshot(self) -> dict[str, object]:
        async with self.lock:
            opened = bool(self.opened_until and datetime.now(UTC) < self.opened_until)
            return {
                "opened": opened,
                "failure_count": self.failure_count,
                "opened_until": isoformat_local(self.opened_until) if self.opened_until else None,
                "reason": self.reason,
            }


portal_circuit_breaker = PortalCircuitBreaker()
browser_bridge_semaphore = asyncio.Semaphore(settings.WAF_BROWSER_MAX_CONCURRENCY)
