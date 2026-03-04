"""Build Ryokan-eligible listing summary exports from consolidated data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from japan_property_scraper.config import CONSOLIDATED_DIR


DEFAULT_CONSOLIDATED_JSON_PATH = CONSOLIDATED_DIR / "consolidated_changes.json"
DEFAULT_SUMMARY_XLS_PATH = CONSOLIDATED_DIR / "ryokan_summary.xls"
ELIGIBILITY_ALLOWLIST = {"ALREADY A RYOKAN", "LIKELY ELIGIBLE"}
SUMMARY_COLUMNS = [
    "property_number",
    "link",
    "ryokan_licence_eligibility",
    "location",
    "price_jpy",
    "land_use_district",
    "legal_restrictions",
]


def export_ryokan_summary_xls(
    consolidated_json_path: Path = DEFAULT_CONSOLIDATED_JSON_PATH,
    summary_xls_path: Path = DEFAULT_SUMMARY_XLS_PATH,
) -> int:
    """Export Ryokan-eligible records to a summary XLS and return row count."""
    records = _load_json_array(consolidated_json_path)
    rows = [_to_summary_row(record) for record in records if _is_eligible(record)]

    summary_xls_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows, columns=SUMMARY_COLUMNS)
    frame.to_excel(summary_xls_path, index=False)
    return len(rows)


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise ValueError(f"Expected JSON array in {path}")
    return payload


def _is_eligible(record: dict[str, Any]) -> bool:
    value = str(record.get("ryokan_licence_eligibility", "")).strip().upper()
    return value in ELIGIBILITY_ALLOWLIST


def _to_summary_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "property_number": _to_scalar(record.get("property_number")),
        "link": _to_scalar(record.get("url")),
        "ryokan_licence_eligibility": _to_scalar(
            record.get("ryokan_licence_eligibility"),
        ),
        "location": _to_scalar(record.get("location")),
        "price_jpy": _to_scalar(record.get("price_jpy")),
        "land_use_district": _to_scalar(record.get("land_use_district")),
        "legal_restrictions": _to_scalar(record.get("legal_restrictions")),
    }


def _to_scalar(value: Any) -> Any:
    if value in (None, ""):
        return ""
    if isinstance(value, list):
        cleaned = [str(item).strip() for item in value if str(item).strip()]
        return " | ".join(cleaned)
    return value


def cli() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Ryokan summary XLS from consolidated_changes.json for records "
            "with eligibility ALREADY A RYOKAN or LIKELY ELIGIBLE."
        ),
    )
    parser.add_argument(
        "--json-path",
        default=str(DEFAULT_CONSOLIDATED_JSON_PATH),
        help="Path to consolidated_changes.json.",
    )
    parser.add_argument(
        "--output-xls",
        default=str(DEFAULT_SUMMARY_XLS_PATH),
        help="Output XLS path for summary table.",
    )
    args = parser.parse_args()

    row_count = export_ryokan_summary_xls(
        consolidated_json_path=Path(args.json_path),
        summary_xls_path=Path(args.output_xls),
    )
    print(f"Summary rows: {row_count}")
    print(f"Saved: {Path(args.output_xls)}")


if __name__ == "__main__":
    cli()
