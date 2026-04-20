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
        self._lock = asyncio.Lock()
        self._failure_count = 0
        self._opened_until: datetime | None = None
        self._reason: str | None = None

    async def allow_request(self) -> bool:
        async with self._lock:
            if self._opened_until and datetime.now(UTC) < self._opened_until:
                return False
            if self._opened_until and datetime.now(UTC) >= self._opened_until:
                self._opened_until = None
                self._failure_count = 0
                self._reason = None
            return True

    async def record_success(self) -> None:
        async with self._lock:
            self._failure_count = 0
            self._opened_until = None
            self._reason = None

    async def record_failure(self, reason: str) -> None:
        async with self._lock:
            self._failure_count += 1
            self._reason = reason
            if self._failure_count >= settings.PORTAL_CIRCUIT_BREAKER_THRESHOLD:
                self._opened_until = datetime.now(UTC) + timedelta(
                    seconds=settings.PORTAL_CIRCUIT_BREAKER_COOLDOWN_SECONDS
                )

    async def snapshot(self) -> dict[str, object]:
        async with self._lock:
            opened = bool(self._opened_until and datetime.now(UTC) < self._opened_until)
            return {
                "opened": opened,
                "failure_count": self._failure_count,
                "opened_until": isoformat_local(self._opened_until) if self._opened_until else None,
                "reason": self._reason,
            }


portal_circuit_breaker = PortalCircuitBreaker()
browser_bridge_semaphore = asyncio.Semaphore(settings.WAF_BROWSER_MAX_CONCURRENCY)
