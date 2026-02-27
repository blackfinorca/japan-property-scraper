"""Track and export changed/new listings in central JSON and CSV files."""

import hashlib
import json
from pathlib import Path

import pandas as pd

from japan_property_scraper.config import CONSOLIDATED_DIR
from japan_property_scraper.services.schema import normalize_listings_schema


CENTRAL_JSON_PATH = Path(CONSOLIDATED_DIR) / "consolidated_changes.json"
CENTRAL_CSV_PATH = Path(CONSOLIDATED_DIR) / "consolidated_changes.csv"


def _load_existing_changes() -> list[dict]:
    if not CENTRAL_JSON_PATH.exists():
        return []

    with CENTRAL_JSON_PATH.open("r", encoding="utf-8") as file:
        return json.load(file)


def _listing_key(listing: dict) -> str:
    listing_id = listing.get("listing_id") or listing.get("property_number", "")
    return f"{listing.get('site', '')}:{listing_id}"


def _fingerprint(listing: dict) -> str:
    excluded_fields = {
        "change_type",
        "fingerprint",
        "run_timestamp",
        "time_stamp",
    }
    fingerprint_payload = {
        key: value
        for key, value in listing.items()
        if key not in excluded_fields
    }
    raw = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _latest_snapshot(existing_changes: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for item in existing_changes:
        latest[_listing_key(item)] = item
    return latest


def append_new_or_changed_listings(
    listings: list[dict],
    run_timestamp: str,
) -> int:
    """Append only new or changed listings to the central JSON and CSV files."""
    CONSOLIDATED_DIR.mkdir(parents=True, exist_ok=True)

    existing_changes = normalize_listings_schema(_load_existing_changes())
    listings = normalize_listings_schema(listings)
    latest_by_key = _latest_snapshot(existing_changes)

    new_change_records: list[dict] = []
    for listing in listings:
        key = _listing_key(listing)
        current_fp = _fingerprint(listing)
        previous_record = latest_by_key.get(key)

        if previous_record is None:
            change_type = "new"
        elif previous_record.get("fingerprint") != current_fp:
            change_type = "changed"
        else:
            continue

        change_record = {
            **listing,
            "change_type": change_type,
            "run_timestamp": run_timestamp,
            "fingerprint": current_fp,
        }
        new_change_records.append(change_record)
        latest_by_key[key] = change_record

    all_changes = existing_changes + new_change_records
    with CENTRAL_JSON_PATH.open("w", encoding="utf-8") as file:
        json.dump(all_changes, file, ensure_ascii=False, indent=2)

    pd.DataFrame(all_changes).to_csv(CENTRAL_CSV_PATH, index=False, encoding="utf-8")
    return len(new_change_records)
