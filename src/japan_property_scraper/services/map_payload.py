"""Build map-ready listing payloads with optional backend geocoding."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any

import requests

from japan_property_scraper.config import BASE_DIR, CONSOLIDATED_DIR
from japan_property_scraper.services.consolidation import load_consolidated_unique_records


DEFAULT_CONSOLIDATED_JSON_PATH = CONSOLIDATED_DIR / "consolidated_changes.json"
DEFAULT_MAP_PAYLOAD_PATH = CONSOLIDATED_DIR / "listings_map_payload.json"
DEFAULT_GEOCODE_CACHE_PATH = CONSOLIDATED_DIR / "geocode_cache.json"
DEFAULT_LOCAL_MAP_CONFIG_PATH = BASE_DIR / "frontend" / "listings_map" / "config.local.json"

GEOCODE_API_URL = "https://maps.googleapis.com/maps/api/geocode/json"
RETRYABLE_GEOCODE_STATUSES = {"OVER_QUERY_LIMIT", "UNKNOWN_ERROR"}


@dataclass
class MapPayloadSummary:
    total_records: int
    rows_exported: int
    rows_with_coordinates: int
    cache_hits: int
    geocoded_count: int
    failed_geocode_count: int
    payload_path: Path
    cache_path: Path
    key_source: str


def build_listings_map_payload(
    *,
    consolidated_json_path: Path = DEFAULT_CONSOLIDATED_JSON_PATH,
    payload_path: Path = DEFAULT_MAP_PAYLOAD_PATH,
    geocode_cache_path: Path = DEFAULT_GEOCODE_CACHE_PATH,
    geocode_api_key: str | None = None,
    geocode_missing: bool = True,
    geocode_delay_seconds: float = 0.08,
) -> MapPayloadSummary:
    """Build map payload JSON and optional geocode cache updates."""
    records = load_consolidated_unique_records(consolidated_json_path)
    cache = _load_cache(geocode_cache_path)
    key, key_source = _resolve_geocode_api_key(geocode_api_key)
    can_geocode = geocode_missing and bool(key)

    rows: list[dict[str, Any]] = []
    cache_hits = 0
    geocoded_count = 0
    failed_geocode_count = 0

    for record in records:
        address = _to_text(record.get("address"))
        cache_key = _normalize_address_key(address)
        geocode_entry: dict[str, Any] | None = None

        if cache_key:
            cached = cache.get(cache_key)
            if _has_coordinates(cached):
                geocode_entry = cached
                cache_hits += 1

        if geocode_entry is None and can_geocode and cache_key:
            geocode_entry = _geocode_address(
                address=address,
                api_key=key or "",
            )
            if _has_coordinates(geocode_entry):
                geocoded_count += 1
            else:
                failed_geocode_count += 1
            cache[cache_key] = {
                **(geocode_entry or {}),
                "address": address,
                "updated_at": _utc_now_iso(),
            }
            if geocode_delay_seconds > 0:
                time.sleep(geocode_delay_seconds)

        lat = None
        lng = None
        place_id = ""
        geocode_status = "MISSING"
        if geocode_entry:
            lat = _to_float(geocode_entry.get("lat"))
            lng = _to_float(geocode_entry.get("lng"))
            place_id = _to_text(geocode_entry.get("place_id"))
            geocode_status = _to_text(geocode_entry.get("status")) or geocode_status

        rows.append(
            {
                "property_number": _to_text(record.get("property_number")),
                "property_name": _to_text(record.get("property_name")),
                "price_jpy": record.get("price_jpy"),
                "url": _to_text(record.get("url")),
                "address": address,
                "ryokan_licence_eligibility": _to_text(
                    record.get("ryokan_licence_eligibility"),
                ),
                "lat": lat,
                "lng": lng,
                "place_id": place_id,
                "geocode_status": geocode_status,
            },
        )

    payload_path.parent.mkdir(parents=True, exist_ok=True)
    with payload_path.open("w", encoding="utf-8") as file:
        json.dump(rows, file, ensure_ascii=False, indent=2)

    geocode_cache_path.parent.mkdir(parents=True, exist_ok=True)
    with geocode_cache_path.open("w", encoding="utf-8") as file:
        json.dump(cache, file, ensure_ascii=False, indent=2)

    rows_with_coordinates = sum(
        1 for row in rows if _to_float(row.get("lat")) is not None and _to_float(row.get("lng")) is not None
    )
    return MapPayloadSummary(
        total_records=len(records),
        rows_exported=len(rows),
        rows_with_coordinates=rows_with_coordinates,
        cache_hits=cache_hits,
        geocoded_count=geocoded_count,
        failed_geocode_count=failed_geocode_count,
        payload_path=payload_path,
        cache_path=geocode_cache_path,
        key_source=key_source,
    )


def _resolve_geocode_api_key(explicit_key: str | None) -> tuple[str | None, str]:
    if explicit_key and _to_text(explicit_key):
        return _to_text(explicit_key), "cli"

    env = os.getenv("GOOGLE_GEOCODING_API_KEY")
    if env and _to_text(env):
        return _to_text(env), "GOOGLE_GEOCODING_API_KEY"

    env_maps = os.getenv("GOOGLE_MAPS_API_KEY")
    if env_maps and _to_text(env_maps):
        return _to_text(env_maps), "GOOGLE_MAPS_API_KEY"

    local_config_key = _load_local_maps_key(DEFAULT_LOCAL_MAP_CONFIG_PATH)
    if local_config_key:
        return local_config_key, str(DEFAULT_LOCAL_MAP_CONFIG_PATH)

    return None, "none"


def _load_local_maps_key(path: Path) -> str | None:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as file:
            payload = json.load(file)
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(payload, dict):
        return None
    key = _to_text(payload.get("mapsApiKey") or payload.get("googleMapsApiKey"))
    return key or None


def _geocode_address(address: str, api_key: str) -> dict[str, Any]:
    if not address:
        return {"status": "EMPTY_ADDRESS"}

    query_address = _address_for_geocode(address)
    last_status = "UNKNOWN_ERROR"
    for attempt in range(1, 4):
        try:
            response = requests.get(
                GEOCODE_API_URL,
                params={"address": query_address, "key": api_key},
                timeout=20,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            last_status = "REQUEST_FAILED"
            if attempt < 3:
                time.sleep(0.6 * attempt)
                continue
            return {"status": last_status}

        status = _to_text(payload.get("status")) or "UNKNOWN_ERROR"
        last_status = status
        if status == "OK":
            results = payload.get("results") or []
            if not results:
                return {"status": "ZERO_RESULTS"}
            first = results[0]
            location = (((first.get("geometry") or {}).get("location")) or {})
            lat = _to_float(location.get("lat"))
            lng = _to_float(location.get("lng"))
            if lat is None or lng is None:
                return {"status": "MALFORMED_GEOMETRY"}
            return {
                "status": "OK",
                "lat": lat,
                "lng": lng,
                "place_id": _to_text(first.get("place_id")),
                "formatted_address": _to_text(first.get("formatted_address")),
            }

        if status in RETRYABLE_GEOCODE_STATUSES and attempt < 3:
            time.sleep(0.6 * attempt)
            continue

        return {"status": status}

    return {"status": last_status}


def _address_for_geocode(address: str) -> str:
    base = address.strip()
    lowered = base.lower()
    if "kyoto" in lowered or "japan" in lowered:
        return base
    return f"{base}, Kyoto, Japan"


def _normalize_address_key(address: str) -> str:
    return " ".join(address.strip().lower().split())


def _load_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            normalized[str(key)] = value
    return normalized


def _has_coordinates(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    return _to_float(value.get("lat")) is not None and _to_float(value.get("lng")) is not None


def _to_float(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = _to_text(value)
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def cli() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Build map-ready listings payload JSON with optional backend geocoding."
        ),
    )
    parser.add_argument(
        "--json-path",
        default=str(DEFAULT_CONSOLIDATED_JSON_PATH),
        help="Path to consolidated_changes.json.",
    )
    parser.add_argument(
        "--output-path",
        default=str(DEFAULT_MAP_PAYLOAD_PATH),
        help="Output path for map payload JSON.",
    )
    parser.add_argument(
        "--cache-path",
        default=str(DEFAULT_GEOCODE_CACHE_PATH),
        help="Geocode cache JSON path.",
    )
    parser.add_argument(
        "--geocode-api-key",
        default=None,
        help=(
            "Google Geocoding API key override. "
            "If omitted, uses GOOGLE_GEOCODING_API_KEY or GOOGLE_MAPS_API_KEY."
        ),
    )
    parser.add_argument(
        "--no-geocode",
        action="store_true",
        help="Do not call Geocoding API; use cache only.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0.08,
        help="Delay between geocode API calls (default: 0.08).",
    )
    args = parser.parse_args()

    summary = build_listings_map_payload(
        consolidated_json_path=Path(args.json_path),
        payload_path=Path(args.output_path),
        geocode_cache_path=Path(args.cache_path),
        geocode_api_key=args.geocode_api_key,
        geocode_missing=not args.no_geocode,
        geocode_delay_seconds=args.delay_seconds,
    )

    print(f"Total records: {summary.total_records}")
    print(f"Rows exported: {summary.rows_exported}")
    print(f"Rows with coordinates: {summary.rows_with_coordinates}")
    print(f"Cache hits: {summary.cache_hits}")
    print(f"Geocoded this run: {summary.geocoded_count}")
    print(f"Failed geocode this run: {summary.failed_geocode_count}")
    print(f"Geocode key source: {summary.key_source}")
    print(f"Payload path: {summary.payload_path}")
    print(f"Cache path: {summary.cache_path}")


if __name__ == "__main__":
    cli()
