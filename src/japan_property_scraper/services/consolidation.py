"""Track unique consolidated listings and write historical changes separately."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

from japan_property_scraper.config import CONSOLIDATED_DIR, HISTORY_DATA_DIR
from japan_property_scraper.services.ryokan_summary import export_ryokan_summary_xls
from japan_property_scraper.services.schema import normalize_listings_schema


CENTRAL_JSON_PATH = Path(CONSOLIDATED_DIR) / "consolidated_changes.json"
HISTORY_JSON_PATH = Path(HISTORY_DATA_DIR) / "consolidated_changes_history.json"


def append_new_or_changed_listings(
    listings: list[dict],
    run_timestamp: str,
) -> int:
    """Append new/changed records to history and refresh unique consolidated snapshot."""
    unique_records, history_records = _load_or_migrate_storage_state(CENTRAL_JSON_PATH)
    listings = normalize_listings_schema(listings)
    latest_by_key = _latest_snapshot(unique_records)

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

    unique_snapshot = list(latest_by_key.values())
    history_snapshot = history_records + new_change_records
    _write_unique_and_history(
        unique_records=unique_snapshot,
        history_records=history_snapshot,
        consolidated_json_path=CENTRAL_JSON_PATH,
    )
    return len(new_change_records)


def load_consolidated_unique_records(
    consolidated_json_path: Path = CENTRAL_JSON_PATH,
) -> list[dict[str, Any]]:
    """Load unique consolidated records, migrating old history-in-place files if needed."""
    unique_records, _ = _load_or_migrate_storage_state(consolidated_json_path)
    return unique_records


def export_consolidated_tabular_files(
    records: list[dict],
    consolidated_json_path: Path = CENTRAL_JSON_PATH,
) -> None:
    """Export unique consolidated records to CSV and XLS next to the JSON file."""
    csv_path = consolidated_json_path.with_suffix(".csv")
    xls_path = consolidated_json_path.with_suffix(".xls")
    frame = pd.DataFrame(records)
    frame.to_csv(csv_path, index=False, encoding="utf-8")
    frame.to_excel(xls_path, index=False)


def _load_or_migrate_storage_state(
    consolidated_json_path: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    consolidated_json_path.parent.mkdir(parents=True, exist_ok=True)
    history_json_path = _resolve_history_json_path(consolidated_json_path)
    history_json_path.parent.mkdir(parents=True, exist_ok=True)

    raw_unique_records = _load_json_array(consolidated_json_path)
    raw_history_records = _load_json_array(history_json_path)
    unique_records = normalize_listings_schema(raw_unique_records)
    history_records = normalize_listings_schema(raw_history_records)

    if unique_records != raw_unique_records:
        _write_json_array(consolidated_json_path, unique_records)
        export_consolidated_tabular_files(unique_records, consolidated_json_path)
    if history_records != raw_history_records:
        _write_json_array(history_json_path, history_records)

    if history_records and not unique_records:
        unique_records = _dedupe_to_latest(history_records)
        _write_json_array(consolidated_json_path, unique_records)
        export_consolidated_tabular_files(unique_records, consolidated_json_path)
        return unique_records, history_records

    if not history_records and unique_records:
        # Legacy migration: consolidated file used to store full history.
        history_records = list(unique_records)
        unique_records = _dedupe_to_latest(history_records)
        _write_json_array(history_json_path, history_records)
        _write_json_array(consolidated_json_path, unique_records)
        export_consolidated_tabular_files(unique_records, consolidated_json_path)
        return unique_records, history_records

    deduped_unique = _dedupe_to_latest(unique_records)
    if len(deduped_unique) != len(unique_records):
        unique_records = deduped_unique
        _write_json_array(consolidated_json_path, unique_records)
        export_consolidated_tabular_files(unique_records, consolidated_json_path)

    return unique_records, history_records


def _write_unique_and_history(
    *,
    unique_records: list[dict[str, Any]],
    history_records: list[dict[str, Any]],
    consolidated_json_path: Path,
) -> None:
    history_json_path = _resolve_history_json_path(consolidated_json_path)
    history_json_path.parent.mkdir(parents=True, exist_ok=True)

    _write_json_array(consolidated_json_path, unique_records)
    export_consolidated_tabular_files(unique_records, consolidated_json_path)
    export_ryokan_summary_xls(consolidated_json_path)
    _write_json_array(history_json_path, history_records)


def _resolve_history_json_path(consolidated_json_path: Path) -> Path:
    if consolidated_json_path.resolve() == CENTRAL_JSON_PATH.resolve():
        return HISTORY_JSON_PATH

    if consolidated_json_path.parent.name == "consolidated":
        output_dir = consolidated_json_path.parent.parent
    else:
        output_dir = consolidated_json_path.parent
    history_dir = output_dir / "history_data"
    return history_dir / f"{consolidated_json_path.stem}_history.json"


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise ValueError(f"Expected JSON array in {path}")
    return payload


def write_json_atomic(path: Path, records: list[dict[str, Any]]) -> None:
    """Write JSON array to path atomically (via temp file + os.replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=path.stem + "_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as file:
            json.dump(records, file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def _write_json_array(path: Path, records: list[dict[str, Any]]) -> None:
    write_json_atomic(path, records)


def _dedupe_to_latest(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in records:
        key = _listing_key(item)
        if key in latest:
            latest.pop(key)
        latest[key] = item
    return list(latest.values())


def _listing_key(listing: dict[str, Any]) -> str:
    listing_id = listing.get("listing_id") or listing.get("property_number", "")
    return f"{listing.get('site', '')}:{listing_id}"


def _fingerprint(listing: dict[str, Any]) -> str:
    excluded_fields = {
        "change_type",
        "fingerprint",
        "run_timestamp",
        "time_stamp",
    }
    fingerprint_payload = {
        key: value
        for key, value in listing.items()
        if key not in excluded_fields and not key.startswith("ryokan_")
    }
    raw = json.dumps(
        fingerprint_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _latest_snapshot(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for item in records:
        latest[_listing_key(item)] = item
    return latest
