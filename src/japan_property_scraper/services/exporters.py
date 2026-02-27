"""Export timestamped site results to JSON and XLSX files."""

import json
from pathlib import Path

import pandas as pd

from japan_property_scraper.config import RAW_DIR
from japan_property_scraper.services.schema import normalize_listings_schema


def export_site_results(
    site_name: str,
    listings: list[dict],
    run_timestamp: str,
) -> None:
    """Save one site's listings as timestamped JSON and XLSX files."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    normalized_listings = normalize_listings_schema(listings)

    json_path = Path(RAW_DIR) / f"{site_name}_{run_timestamp}.json"
    xlsx_path = Path(RAW_DIR) / f"{site_name}_{run_timestamp}.xlsx"

    with json_path.open("w", encoding="utf-8") as file:
        json.dump(normalized_listings, file, ensure_ascii=False, indent=2)

    pd.DataFrame(normalized_listings).to_excel(xlsx_path, index=False)
