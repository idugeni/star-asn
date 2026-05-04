import logging
from typing import Any

logger = logging.getLogger(__name__)


async def resolve_upt_coordinates(upt_name: str) -> dict[str, Any] | None:
    """
    Resolve coordinates for a UPT name.

    Geocoding API has been removed. Location coordinates must be provided
    via Telegram's native location sharing button or manual input.
    Always returns None — UPTs are created without coordinates by default.
    """
    logger.info(
        f"Geocoding disabled for '{upt_name}'. Use Telegram location button or manual input to set coordinates."
    )
    return None


def resolve_upt_coordinates_sync(upt_name: str) -> dict[str, Any] | None:
    """Synchronous version of resolve_upt_coordinates. Always returns None."""
    logger.info(
        f"Geocoding disabled for '{upt_name}'. Use Telegram location button or manual input to set coordinates."
    )
    return None
