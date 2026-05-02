"""Build latest scrape comparison reports from previous and current snapshots."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from japan_property_scraper.config import CONSOLIDATED_DIR, RAW_DIR


DEFAULT_COMPARISON_REPORT_PATH = CONSOLIDATED_DIR / "latest_scrape_comparison.json"

IGNORED_COMPARISON_FIELDS = {
    "change_type",
    "fingerprint",
    "price_jpy",
    "price_per_m2",
    "price_per_m2_benchmark",
    "price_usd",
    "run_timestamp",
    "summary",
    "time_stamp",
}


def build_scrape_comparison(
    *,
    previous_records: list[dict[str, Any]],
    current_records: list[dict[str, Any]],
    status_history_records: list[dict[str, Any]] | None = None,
    run_timestamp: str,
) -> dict[str, Any]:
    """Compare previous consolidated records with a fresh scrape snapshot."""
    previous_by_key = _records_by_key(previous_records)
    current_by_key = _records_by_key(current_records)
    status_history_by_key = _status_history_by_key(
        status_history_records or [*previous_records, *current_records],
    )
    price_history_by_key = _price_history_by_key(
        status_history_records or [*previous_records, *current_records],
    )

    previous_keys = set(previous_by_key)
    current_keys = set(current_by_key)

    added = [
        _with_status_history(
            _listing_summary(current_by_key[key], prefix="new"),
            status_history_by_key,
            price_history_by_key,
        )
        for key in sorted(current_keys - previous_keys)
    ]
    removed = [
        _with_status_history(
            _listing_summary(previous_by_key[key], prefix="old"),
            status_history_by_key,
            price_history_by_key,
        )
        for key in sorted(previous_keys - current_keys)
    ]

    price_changed: list[dict[str, Any]] = []
    other_changed: list[dict[str, Any]] = []

    for key in sorted(previous_keys & current_keys):
        previous = previous_by_key[key]
        current = current_by_key[key]
        old_price = _parse_price(previous.get("price_jpy"))
        new_price = _parse_price(current.get("price_jpy"))
        changed_fields = _changed_fields(previous, current)

        if old_price != new_price:
            price_changed.append(
                _with_status_history(
                    {
                        **_listing_summary(current),
                        "old_price_jpy": old_price,
                        "new_price_jpy": new_price,
                        "delta_jpy": _price_delta(old_price, new_price),
                        "delta_percent": _price_delta_percent(old_price, new_price),
                        "direction": _price_direction(old_price, new_price),
                        "changed_fields": changed_fields,
                        "old_url": _to_text(previous.get("url")),
                        "new_url": _to_text(current.get("url")),
                    },
                    status_history_by_key,
                    price_history_by_key,
                ),
            )
            continue

        if changed_fields:
            other_changed.append(
                _with_status_history(
                    {
                        **_listing_summary(current),
                        "changed_fields": changed_fields,
                        "old_values": {
                            field: previous.get(field)
                            for field in changed_fields
                        },
                        "new_values": {
                            field: current.get(field)
                            for field in changed_fields
                        },
                    },
                    status_history_by_key,
                    price_history_by_key,
                ),
            )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_timestamp": run_timestamp,
        "summary": {
            "previous_total": len(previous_by_key),
            "current_total": len(current_by_key),
            "added": len(added),
            "removed": len(removed),
            "price_changed": len(price_changed),
            "other_changed": len(other_changed),
        },
        "added": added,
        "removed": removed,
        "price_changed": price_changed,
        "other_changed": other_changed,
    }


def write_scrape_comparison_report(
    *,
    previous_records: list[dict[str, Any]],
    current_records: list[dict[str, Any]],
    status_history_records: list[dict[str, Any]] | None = None,
    run_timestamp: str,
    report_path: Path = DEFAULT_COMPARISON_REPORT_PATH,
) -> dict[str, Any]:
    """Build and write the latest scrape comparison report."""
    report = build_scrape_comparison(
        previous_records=previous_records,
        current_records=current_records,
        status_history_records=status_history_records,
        run_timestamp=run_timestamp,
    )
    _write_json_atomic(report_path, report)
    return report


def load_raw_status_history_records(raw_dir: Path = RAW_DIR) -> list[dict[str, Any]]:
    """Load status-bearing records from timestamped raw scrape JSON files."""
    if not raw_dir.exists():
        return []

    records: list[dict[str, Any]] = []
    for path in sorted(raw_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, list):
            continue
        run_timestamp = _run_timestamp_from_raw_path(path)
        for item in payload:
            if not isinstance(item, dict):
                continue
            if not _to_text(item.get("status")):
                continue
            enriched = dict(item)
            if not _to_text(enriched.get("run_timestamp")) and run_timestamp:
                enriched["run_timestamp"] = run_timestamp
            records.append(enriched)
    return records


def _records_by_key(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    keyed: dict[str, dict[str, Any]] = {}
    for record in records:
        key = _record_key(record)
        if key:
            keyed[key] = record
    return keyed


def _run_timestamp_from_raw_path(path: Path) -> str:
    stem = path.stem
    parts = stem.split("_")
    if len(parts) < 3:
        return ""
    return "_".join(parts[-2:])


def _status_history_by_key(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, str]]]:
    history: dict[str, list[dict[str, str]]] = {}
    seen: set[tuple[str, str, str, str]] = set()
    for record in records:
        key = _record_key(record)
        status = _to_text(record.get("status"))
        if not key or not status:
            continue
        entry = {
            "run_timestamp": _to_text(record.get("run_timestamp")),
            "time_stamp": _to_text(record.get("time_stamp")),
            "status": status,
        }
        dedupe_key = (
            key,
            entry["run_timestamp"],
            entry["time_stamp"],
            entry["status"],
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        history.setdefault(key, []).append(entry)

    for entries in history.values():
        entries.sort(key=lambda item: (item["run_timestamp"], item["time_stamp"]))
    return history


def _price_history_by_key(
    records: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    history: dict[str, list[dict[str, Any]]] = {}
    seen: set[tuple[str, str, str, int]] = set()
    for record in records:
        key = _record_key(record)
        price = _parse_price(record.get("price_jpy"))
        if not key or price is None:
            continue
        entry = {
            "run_timestamp": _to_text(record.get("run_timestamp")),
            "time_stamp": _to_text(record.get("time_stamp")),
            "price_jpy": price,
        }
        dedupe_key = (
            key,
            entry["run_timestamp"],
            entry["time_stamp"],
            entry["price_jpy"],
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        history.setdefault(key, []).append(entry)

    for entries in history.values():
        entries.sort(key=lambda item: (item["run_timestamp"], item["time_stamp"]))
    return history


def _with_status_history(
    row: dict[str, Any],
    status_history_by_key: dict[str, list[dict[str, str]]],
    price_history_by_key: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    key = _record_key(row)
    row["status_history"] = status_history_by_key.get(key, [])
    row["price_history"] = price_history_by_key.get(key, [])
    return row


def _record_key(record: dict[str, Any]) -> str:
    site = _to_text(record.get("site"))
    listing_id = _to_text(record.get("listing_id") or record.get("property_number"))
    if not listing_id:
        return ""
    return f"{site}:{listing_id}"


def _listing_summary(
    record: dict[str, Any],
    *,
    prefix: str = "",
) -> dict[str, Any]:
    price_key = f"{prefix}_price_jpy" if prefix else "price_jpy"
    return {
        "site": _to_text(record.get("site")),
        "listing_id": _to_text(record.get("listing_id") or record.get("property_number")),
        "property_number": _to_text(record.get("property_number")),
        "property_name": _to_text(record.get("property_name") or record.get("title")),
        price_key: _parse_price(record.get("price_jpy")),
        "status": _to_text(record.get("status")),
        "url": _to_text(record.get("url")),
    }


def _changed_fields(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> list[str]:
    fields = set(previous) | set(current)
    changed: list[str] = []
    for field in sorted(fields):
        if field in IGNORED_COMPARISON_FIELDS or field.startswith("ryokan_"):
            continue
        if _normalize_for_compare(previous.get(field)) != _normalize_for_compare(current.get(field)):
            changed.append(field)
    return changed


def _normalize_for_compare(value: Any) -> Any:
    if value in (None, "", []):
        return ""
    if isinstance(value, list):
        return [
            _normalize_for_compare(item)
            for item in value
            if _normalize_for_compare(item) != ""
        ]
    if isinstance(value, str):
        return " ".join(value.strip().split())
    return value


def _parse_price(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(round(value))
    text = _to_text(value)
    digits = "".join(char for char in text if char.isdigit())
    return int(digits) if digits else None


def _price_delta(old_price: int | None, new_price: int | None) -> int | None:
    if old_price is None or new_price is None:
        return None
    return new_price - old_price


def _price_delta_percent(old_price: int | None, new_price: int | None) -> float | None:
    if old_price in (None, 0) or new_price is None:
        return None
    return round(((new_price - old_price) / old_price) * 100, 2)


def _price_direction(old_price: int | None, new_price: int | None) -> str:
    if old_price is None and new_price is not None:
        return "added-price"
    if old_price is not None and new_price is None:
        return "removed-price"
    if old_price is None or new_price is None or old_price == new_price:
        return "unchanged"
    return "up" if new_price > old_price else "down"


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=path.stem + "_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
