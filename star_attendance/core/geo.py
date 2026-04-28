import httpx
import logging
import asyncio
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

async def resolve_upt_coordinates(upt_name: str) -> Optional[Dict[str, Any]]:
    """
    Automatically resolve coordinates for a UPT name using OpenStreetMap Nominatim.
    Returns a dict with latitude, longitude, and address or None if not found.
    """
    if not upt_name:
        return None
        
    # Clean up common prefixes that might confuse geocoding
    search_query = upt_name.strip()
    
    # We add "Indonesia" to the query to ensure we get results in the right region
    params: dict[str, str | int] = {
        "q": f"{search_query}, Indonesia",
        "format": "json",
        "limit": 1
    }
    
    headers = {
        "User-Agent": "Star-ASN-Enterprise/2.0 (Contact: admin@star-asn.local)"
    }
    
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers)
            response.raise_for_status()
            results = response.json()
            
            if results:
                res = results[0]
                return {
                    "nama_upt": upt_name,
                    "latitude": float(res["lat"]),
                    "longitude": float(res["lon"]),
                    "address": res["display_name"]
                }
            
            # Fallback: remove specific terms if initial search fails
            if "KANTOR" in search_query or "RUMAH" in search_query:
                simplified = search_query.replace("KANTOR ", "").replace("RUMAH ", "")
                params["q"] = f"{simplified}, Indonesia"
                response = await client.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers)
                results = response.json()
                if results:
                    res = results[0]
                    return {
                        "nama_upt": upt_name,
                        "latitude": float(res["lat"]),
                        "longitude": float(res["lon"]),
                        "address": res["display_name"]
                    }
                    
    except Exception as e:
        logger.error(f"Geocoding Error for {upt_name}: {e}")
        
    return None

def resolve_upt_coordinates_sync(upt_name: str) -> Optional[Dict[str, Any]]:
    """Synchronous version of resolve_upt_coordinates."""
    if not upt_name:
        return None
        
    search_query = upt_name.strip()
    params: dict[str, str | int] = {
        "q": f"{search_query}, Indonesia",
        "format": "json",
        "limit": 1
    }
    headers = {"User-Agent": "Star-ASN-Enterprise/2.0 (Contact: admin@star-asn.local)"}
    
    try:
        with httpx.Client(timeout=10) as client:
            response = client.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers)
            results = response.json()
            if results:
                res = results[0]
                return {
                    "nama_upt": upt_name,
                    "latitude": float(res["lat"]),
                    "longitude": float(res["lon"]),
                    "address": res["display_name"]
                }
            
            if "KANTOR" in search_query or "RUMAH" in search_query:
                simplified = search_query.replace("KANTOR ", "").replace("RUMAH ", "")
                params["q"] = f"{simplified}, Indonesia"
                response = client.get("https://nominatim.openstreetmap.org/search", params=params, headers=headers)
                results = response.json()
                if results:
                    res = results[0]
                    return {
                        "nama_upt": upt_name,
                        "latitude": float(res["lat"]),
                        "longitude": float(res["lon"]),
                        "address": res["display_name"]
                    }
    except Exception as e:
        logger.error(f"Sync Geocoding Error for {upt_name}: {e}")
    return None
