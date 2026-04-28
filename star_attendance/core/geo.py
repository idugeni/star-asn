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


async def _google_maps_search(client: httpx.AsyncClient, query: str) -> Optional[Dict[str, Any]]:
    """Search Google Places API (New) Text Search — finds places by name.

    Requires GOOGLE_MAPS_API_KEY with Places API (New) enabled.
    Uses the v1 Text Search endpoint which is better for institution names
    than the legacy Geocoding API.
    """
    api_key = getattr(settings, "GOOGLE_MAPS_API_KEY", None)
    if not api_key:
        return None

    # Places API (New) — Text Search
    headers = {
        "X-Goog-Api-Key": api_key,
        "Content-Type": "application/json",
    }
    body = {
        "textQuery": f"{query}, Indonesia",
    }
    # Request only the fields we need (FieldMask controls billing)
    params = {"fields": "places.location,places.formattedAddress"}

    response = await client.post(
        "https://places.googleapis.com/v1/places:searchText",
        headers=headers,
        params=params,
        json=body,
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()

    places = data.get("places", [])
    if places:
        place = places[0]
        loc = place.get("location", {})
        lat = loc.get("latitude")
        lng = loc.get("longitude")
        addr = place.get("formattedAddress", "")
        if lat is not None and lng is not None:
            return _make_result("", float(lat), float(lng), addr)
    return None


async def resolve_upt_coordinates(upt_name: str) -> Optional[Dict[str, Any]]:
    """
    Resolve coordinates for a UPT name using multi-strategy geocoding.

    Strategy order:
    1. OpenStreetMap Nominatim with progressively simplified queries
    2. Google Places API (New) Text Search (if GOOGLE_MAPS_API_KEY is configured)
    3. City-name-only fallback via Nominatim

    Returns a dict with latitude, longitude, and address or None if not found.
    """
    if not upt_name:
        return None

    variants = _build_search_variants(upt_name)

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Strategy 1: Nominatim with all variants
            for query in variants:
                try:
                    result = await _nominatim_search(client, query)
                    if result:
                        result["nama_upt"] = upt_name
                        logger.info(f"Geocoded '{upt_name}' via Nominatim query '{query}' → {result['latitude']}, {result['longitude']}")
                        return result
                except Exception:
                    continue

            # Strategy 2: Google Places API (New) Text Search
            for query in variants:
                try:
                    result = await _google_maps_search(client, query)
                    if result:
                        result["nama_upt"] = upt_name
                        logger.info(f"Geocoded '{upt_name}' via Google Places query '{query}' → {result['latitude']}, {result['longitude']}")
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
    headers = {"User-Agent": "Star-ASN-Enterprise/2.0 (Contact: admin@star-asn.local)"}

    try:
        with httpx.Client(timeout=10) as client:
            # Strategy 1: Nominatim with all variants
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

            # Strategy 2: Google Places API (New) Text Search
            api_key = getattr(settings, "GOOGLE_MAPS_API_KEY", None)
            if api_key:
                gheaders = {
                    "X-Goog-Api-Key": api_key,
                    "Content-Type": "application/json",
                }
                for query in variants:
                    try:
                        body = {"textQuery": f"{query}, Indonesia"}
                        gparams = {"fields": "places.location,places.formattedAddress"}
                        response = client.post(
                            "https://places.googleapis.com/v1/places:searchText",
                            headers=gheaders,
                            params=gparams,
                            json=body,
                            timeout=10,
                        )
                        data = response.json()
                        places = data.get("places", [])
                        if places:
                            place = places[0]
                            loc = place.get("location", {})
                            lat = loc.get("latitude")
                            lng = loc.get("longitude")
                            addr = place.get("formattedAddress", "")
                            if lat is not None and lng is not None:
                                result = _make_result(upt_name, float(lat), float(lng), addr)
                                logger.info(f"Geocoded '{upt_name}' via Google Places query '{query}' → {result['latitude']}, {result['longitude']}")
                                return result
                    except Exception:
                        continue

    except Exception as e:
        logger.error(f"Sync Geocoding Error for {upt_name}: {e}")

    logger.warning(f"Could not geocode '{upt_name}' with any strategy")
    return None
