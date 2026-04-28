import httpx
import logging
import re
from typing import Any, Dict, Optional

from star_attendance.core.config import settings

logger = logging.getLogger(__name__)

# Indonesian government institution prefixes that confuse geocoding
_STRIP_PREFIXES = [
    "KANTOR ", "RUMAH ", "LEMBAGA ", "BADAN ", "DINAS ",
    "INSPEKTORAT ", "SEKRETARIAT ", "BIRO ", "DIREKTORAT ",
]
# Known abbreviation → common name mapping for better geocoding hits
_ALIAS_MAP: dict[str, str] = {
    "RUTAN": "RUMAH TAHANAN",
    "LAPAS": "LEMBAGA PEMASYARAKATAN",
    "IMIGRASI": "KANTOR IMIGRASI",
    "KEMENKUMHAM": "KEMENTERIAN HUKUM DAN HAK ASASI MANUSIA",
}


def _extract_city_name(upt_name: str) -> str | None:
    """Extract likely city/kabupaten name from a UPT name.

    Strategy: the last proper-noun token(s) after the classification
    (e.g. "KELAS IIB WONOSOBO" → "WONOSOBO").
    """
    # Remove known classification patterns like "KELAS I", "KELAS II", "KELAS IIB", etc.
    cleaned = re.sub(r"\bKELAS\s+[IVX]+\b", "", upt_name, flags=re.IGNORECASE).strip()
    # Remove common institutional suffixes
    for prefix in _STRIP_PREFIXES:
        cleaned = cleaned.replace(prefix, "")
    # The last word(s) are typically the city name
    parts = cleaned.split()
    if not parts:
        return None
    # Take last 1-2 words as city name (handles "JAKARTA BARAT", "WONOSOBO", etc.)
    if len(parts) >= 2:
        candidate = f"{parts[-2]} {parts[-1]}"
        # Check if it looks like a two-word city (e.g. "JAKARTA BARAT")
        if parts[-1].upper() in ("BARAT", "TIMUR", "UTARA", "SELATAN", "TENGAH", "KULON", "WETAN"):
            return candidate
    return parts[-1]


def _build_search_variants(upt_name: str) -> list[str]:
    """Build a list of progressively simplified search queries for geocoding."""
    variants: list[str] = []
    name = upt_name.strip()

    # 1. Original name
    variants.append(name)

    # 2. Strip institutional prefixes first (RUMAH, KANTOR, etc.)
    stripped = name
    for prefix in _STRIP_PREFIXES:
        stripped = stripped.replace(prefix, "")
    stripped = stripped.strip()
    if stripped and stripped != name:
        variants.append(stripped)

    # 3. Expand abbreviations (RUTAN → RUMAH TAHANAN, LAPAS → LEMBAGA PEMASYARAKATAN)
    expanded = name
    for abbr, full in _ALIAS_MAP.items():
        if abbr in expanded.upper():
            expanded = expanded.replace(abbr, full)
    if expanded != name:
        variants.append(expanded)

    # 4. Strip prefixes + remove classification (KELAS IIB, etc.)
    no_class = re.sub(r"\bKELAS\s+[IVX]+\b", "", stripped, flags=re.IGNORECASE).strip()
    if no_class and no_class != stripped:
        variants.append(no_class)

    # 5. Strip prefixes + expand abbreviations + remove classification
    expanded_no_class = re.sub(r"\bKELAS\s+[IVX]+\b", "", expanded, flags=re.IGNORECASE).strip()
    if expanded_no_class and expanded_no_class != expanded:
        variants.append(expanded_no_class)

    # 6. Extract city name only (last resort)
    city = _extract_city_name(name)
    if city:
        variants.append(city)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for v in variants:
        vl = v.upper()
        if vl not in seen:
            seen.add(vl)
            unique.append(v)
    return unique


def _make_result(upt_name: str, lat: float, lon: float, address: str) -> Dict[str, Any]:
    return {
        "nama_upt": upt_name,
        "latitude": lat,
        "longitude": lon,
        "address": address,
    }


async def _nominatim_search(client: httpx.AsyncClient, query: str) -> Optional[Dict[str, Any]]:
    """Search Nominatim for a single query string."""
    params: dict[str, str | int] = {
        "q": f"{query}, Indonesia",
        "format": "json",
        "limit": 1,
    }
    headers = {"User-Agent": "Star-ASN-Enterprise/2.0 (Contact: admin@star-asn.local)"}
    response = await client.get(
        "https://nominatim.openstreetmap.org/search",
        params=params,
        headers=headers,
    )
    response.raise_for_status()
    results = response.json()
    if results:
        res = results[0]
        return _make_result(
            "", float(res["lat"]), float(res["lon"]), res["display_name"]
        )
    return None


async def _goapi_search(client: httpx.AsyncClient, query: str) -> Optional[Dict[str, Any]]:
    """Search GoAPI Places — free, Indonesia-optimized place search.

    Returns the first matching place with coordinates.
    Requires GOAPI_KEY in settings.
    """
    api_key = getattr(settings, "GOAPI_KEY", None)
    if not api_key:
        return None
    params = {"search": query, "api_key": api_key}
    response = await client.get(
        "https://api.goapi.io/places",
        params=params,
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    if data.get("status") == "success":
        results = data.get("data", {}).get("results", [])
        if results:
            place = results[0]
            lat = float(place["lat"])
            lng = float(place["lng"])
            addr = place.get("displayName", "")
            return _make_result("", lat, lng, addr)
    return None


async def resolve_upt_coordinates(upt_name: str) -> Optional[Dict[str, Any]]:
    """
    Resolve coordinates for a UPT name using multi-strategy geocoding.

    Strategy order:
    1. GoAPI Places (free, Indonesia-optimized) with all variants
    2. OpenStreetMap Nominatim with progressively simplified queries

    Returns a dict with latitude, longitude, and address or None if not found.
    """
    if not upt_name:
        return None

    variants = _build_search_variants(upt_name)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Strategy 1: GoAPI Places (Indonesia-optimized, free)
            for query in variants:
                try:
                    result = await _goapi_search(client, query)
                    if result:
                        result["nama_upt"] = upt_name
                        logger.info(f"Geocoded '{upt_name}' via GoAPI query '{query}' → {result['latitude']}, {result['longitude']}")
                        return result
                except Exception:
                    continue

            # Strategy 2: Nominatim fallback
            for query in variants:
                try:
                    result = await _nominatim_search(client, query)
                    if result:
                        result["nama_upt"] = upt_name
                        logger.info(f"Geocoded '{upt_name}' via Nominatim query '{query}' → {result['latitude']}, {result['longitude']}")
                        return result
                except Exception:
                    continue

    except Exception as e:
        logger.error(f"Geocoding Error for {upt_name}: {e}")

    logger.warning(f"Could not geocode '{upt_name}' with any strategy")
    return None


def resolve_upt_coordinates_sync(upt_name: str) -> Optional[Dict[str, Any]]:
    """Synchronous version of resolve_upt_coordinates."""
    if not upt_name:
        return None

    variants = _build_search_variants(upt_name)

    try:
        with httpx.Client(timeout=10) as client:
            # Strategy 1: GoAPI Places (Indonesia-optimized, free)
            api_key = getattr(settings, "GOAPI_KEY", None)
            if api_key:
                for query in variants:
                    try:
                        params = {"search": query, "api_key": api_key}
                        response = client.get(
                            "https://api.goapi.io/places",
                            params=params,
                            timeout=10,
                        )
                        data = response.json()
                        if data.get("status") == "success":
                            results = data.get("data", {}).get("results", [])
                            if results:
                                place = results[0]
                                lat = float(place["lat"])
                                lng = float(place["lng"])
                                addr = place.get("displayName", "")
                                result = _make_result(upt_name, lat, lng, addr)
                                logger.info(f"Geocoded '{upt_name}' via GoAPI query '{query}' → {result['latitude']}, {result['longitude']}")
                                return result
                    except Exception:
                        continue

            # Strategy 2: Nominatim fallback
            headers = {"User-Agent": "Star-ASN-Enterprise/2.0 (Contact: admin@star-asn.local)"}
            for query in variants:
                try:
                    params: dict[str, str | int] = {
                        "q": f"{query}, Indonesia",
                        "format": "json",
                        "limit": 1,
                    }
                    response = client.get(
                        "https://nominatim.openstreetmap.org/search",
                        params=params,
                        headers=headers,
                    )
                    results = response.json()
                    if results:
                        res = results[0]
                        result = _make_result(
                            upt_name,
                            float(res["lat"]),
                            float(res["lon"]),
                            res["display_name"],
                        )
                        logger.info(f"Geocoded '{upt_name}' via Nominatim query '{query}' → {result['latitude']}, {result['longitude']}")
                        return result
                except Exception:
                    continue

    except Exception as e:
        logger.error(f"Sync Geocoding Error for {upt_name}: {e}")

    logger.warning(f"Could not geocode '{upt_name}' with any strategy")
    return None
