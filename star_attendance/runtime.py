from functools import lru_cache

from star_attendance.database_manager import SupabaseManager
from star_attendance.internal_api import InternalAPIClient


@lru_cache(maxsize=1)
def get_store() -> SupabaseManager:
    return SupabaseManager()


@lru_cache(maxsize=1)
def get_internal_api_client() -> InternalAPIClient:
    return InternalAPIClient()
