from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from star_attendance.core.config import settings


@dataclass(slots=True)
class RuntimeOptions:
    action: str
    explain: bool = True
    dry_run: bool = False
    store: Any | None = None
    source: str | None = None
    request_key: str | None = None
    round_retry_max: int | None = settings.MASS_RETRY_MAX

    @classmethod
    def from_store(
        cls,
        action: str,
        *,
        store: Any,
        explain: bool = True,
        dry_run: bool = False,
        source: str | None = None,
        request_key: str | None = None,
        round_retry_max: int | None = None,
    ) -> RuntimeOptions:
        return cls(
            action=action,
            explain=explain,
            dry_run=dry_run,
            store=store,
            source=source,
            request_key=request_key,
            round_retry_max=round_retry_max if round_retry_max is not None else settings.MASS_RETRY_MAX,
        )
