"""Main pipeline workflow."""

from __future__ import annotations

import argparse
from datetime import datetime
import logging
from pathlib import Path
from typing import Callable, Sequence

from japan_property_scraper.config import CONSOLIDATED_DIR, TIMESTAMP_FORMAT
from japan_property_scraper.services.consolidation import append_new_or_changed_listings
from japan_property_scraper.services.exporters import export_site_results
from japan_property_scraper.services.map_payload import (
    DEFAULT_GEOCODE_CACHE_PATH,
    DEFAULT_MAP_PAYLOAD_PATH,
    build_listings_map_payload,
)
from japan_property_scraper.services.ryokan_licence_eligibility import (
    DEFAULT_MODEL as DEFAULT_OPENAI_MODEL,
    DEFAULT_PROMPT_PATH as DEFAULT_RYOKAN_PROMPT_PATH,
    update_ryokan_licence_eligibility,
)
from japan_property_scraper.services.ryokan_summary import (
    DEFAULT_SUMMARY_XLS_PATH,
    export_ryokan_summary_xls,
)
from japan_property_scraper.sites import scrape_hachise


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
LOGGER = logging.getLogger(__name__)

SITE_SCRAPERS: dict[str, Callable[[], list[dict]]] = {
    "hachise": scrape_hachise,
}

PIPELINE_TAGS = ("scrape", "openai", "summary", "geocode", "map-export")
DEFAULT_PIPELINE_TAGS = ("scrape",)
DEFAULT_CONSOLIDATED_JSON_PATH = CONSOLIDATED_DIR / "consolidated_changes.json"


def run(
    *,
    tags: Sequence[str] | None = None,
    openai_model: str = DEFAULT_OPENAI_MODEL,
    property_numbers: Sequence[str] | None = None,
    consolidated_json_path: Path = DEFAULT_CONSOLIDATED_JSON_PATH,
    prompt_path: Path = DEFAULT_RYOKAN_PROMPT_PATH,
    summary_xls_path: Path = DEFAULT_SUMMARY_XLS_PATH,
    map_payload_path: Path = DEFAULT_MAP_PAYLOAD_PATH,
    geocode_cache_path: Path = DEFAULT_GEOCODE_CACHE_PATH,
    geocode_api_key: str | None = None,
) -> None:
    """Run selected pipeline stages in order."""
    selected_tags = _normalize_pipeline_tags(tags)
    LOGGER.info("Pipeline tags: %s", ", ".join(selected_tags))

    if "scrape" in selected_tags:
        _run_scrape_stage()

    if "openai" in selected_tags:
        summary = update_ryokan_licence_eligibility(
            consolidated_json_path=consolidated_json_path,
            prompt_path=prompt_path,
            model=openai_model,
            property_numbers=property_numbers,
        )
        LOGGER.info(
            (
                "Ryokan eligibility stage complete. "
                "Processed=%s Updated=%s MissingPropertyNumbers=%s"
            ),
            summary.processed_records,
            summary.updated_records,
            ",".join(summary.missing_property_numbers) or "-",
        )

    if "summary" in selected_tags:
        rows = export_ryokan_summary_xls(
            consolidated_json_path=consolidated_json_path,
            summary_xls_path=summary_xls_path,
        )
        LOGGER.info("Ryokan summary stage complete. Rows=%s", rows)

    map_payload_written = False
    if "geocode" in selected_tags:
        map_summary = build_listings_map_payload(
            consolidated_json_path=consolidated_json_path,
            payload_path=map_payload_path,
            geocode_cache_path=geocode_cache_path,
            geocode_api_key=geocode_api_key,
            geocode_missing=True,
        )
        LOGGER.info(
            (
                "Geocode stage complete. Exported=%s WithCoords=%s CacheHits=%s "
                "Geocoded=%s Failed=%s KeySource=%s Payload=%s"
            ),
            map_summary.rows_exported,
            map_summary.rows_with_coordinates,
            map_summary.cache_hits,
            map_summary.geocoded_count,
            map_summary.failed_geocode_count,
            map_summary.key_source,
            map_summary.payload_path,
        )
        map_payload_written = True

    if "map-export" in selected_tags and not map_payload_written:
        map_summary = build_listings_map_payload(
            consolidated_json_path=consolidated_json_path,
            payload_path=map_payload_path,
            geocode_cache_path=geocode_cache_path,
            geocode_api_key=geocode_api_key,
            geocode_missing=False,
        )
        LOGGER.info(
            (
                "Map-export stage complete. Exported=%s WithCoords=%s CacheHits=%s "
                "Payload=%s"
            ),
            map_summary.rows_exported,
            map_summary.rows_with_coordinates,
            map_summary.cache_hits,
            map_summary.payload_path,
        )


def _run_scrape_stage() -> None:
    """Run all site scrapers and update consolidated snapshot/history."""
    run_timestamp = datetime.now().strftime(TIMESTAMP_FORMAT)
    all_listings: list[dict] = []
    for site_name, scraper in SITE_SCRAPERS.items():
        LOGGER.info("Scraping %s", site_name)
        site_listings = scraper()
        export_site_results(site_name, site_listings, run_timestamp)
        all_listings.extend(site_listings)
        LOGGER.info("%s listings fetched from %s", len(site_listings), site_name)

    changes = append_new_or_changed_listings(all_listings, run_timestamp)
    LOGGER.info("Run complete. %s new/changed listings were consolidated.", changes)


def _normalize_pipeline_tags(tags: Sequence[str] | None) -> list[str]:
    if not tags:
        return list(DEFAULT_PIPELINE_TAGS)

    raw_tokens: list[str] = []
    for raw in tags:
        parts = str(raw).split(",")
        for part in parts:
            token = part.strip().lower()
            if token:
                raw_tokens.append(token)

    if not raw_tokens:
        return list(DEFAULT_PIPELINE_TAGS)

    aliases = {
        "ai": "openai",
        "ryokan": "openai",
        "map": "map-export",
        "geo": "geocode",
    }
    normalized: list[str] = []
    for token in raw_tokens:
        canonical = aliases.get(token, token)
        expanded = PIPELINE_TAGS if canonical == "all" else (canonical,)
        for item in expanded:
            if item not in PIPELINE_TAGS:
                supported = ", ".join(PIPELINE_TAGS + ("all",))
                raise SystemExit(f"Unsupported --tags value '{token}'. Use: {supported}")
            if item not in normalized:
                normalized.append(item)
    return normalized


def cli(argv: Sequence[str] | None = None) -> None:
    """CLI for running selected pipeline stages with tags."""
    parser = argparse.ArgumentParser(
        description=(
            "Run the property pipeline by stage tags. "
            "Supported tags: scrape, openai, summary, geocode, map-export, all."
        ),
    )
    parser.add_argument(
        "--tags",
        action="append",
        default=[],
        help=(
            "Pipeline tags to run (comma-separated or repeated). "
            "Example: --tags scrape,openai or --tags summary. "
            "Default: scrape."
        ),
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_OPENAI_MODEL,
        help=f"OpenAI model for --tags openai (default: {DEFAULT_OPENAI_MODEL}).",
    )
    parser.add_argument(
        "--property-number",
        action="append",
        dest="property_numbers",
        default=[],
        help=(
            "Property number filter for --tags openai. "
            "Repeat to include multiple numbers."
        ),
    )
    parser.add_argument(
        "--json-path",
        default=str(DEFAULT_CONSOLIDATED_JSON_PATH),
        help=(
            "Path to consolidated_changes.json for openai/summary stages "
            f"(default: {DEFAULT_CONSOLIDATED_JSON_PATH})."
        ),
    )
    parser.add_argument(
        "--prompt-path",
        default=str(DEFAULT_RYOKAN_PROMPT_PATH),
        help="Prompt path for --tags openai.",
    )
    parser.add_argument(
        "--summary-xls-path",
        default=str(DEFAULT_SUMMARY_XLS_PATH),
        help="Output path for --tags summary.",
    )
    parser.add_argument(
        "--map-payload-path",
        default=str(DEFAULT_MAP_PAYLOAD_PATH),
        help="Output path for --tags map-export/geocode payload JSON.",
    )
    parser.add_argument(
        "--geocode-cache-path",
        default=str(DEFAULT_GEOCODE_CACHE_PATH),
        help="Cache path for --tags geocode/map-export.",
    )
    parser.add_argument(
        "--geocode-api-key",
        default=None,
        help=(
            "Google Geocoding API key override for --tags geocode. "
            "If omitted, uses GOOGLE_GEOCODING_API_KEY or GOOGLE_MAPS_API_KEY."
        ),
    )
    args = parser.parse_args(argv)

    run(
        tags=args.tags,
        openai_model=args.model,
        property_numbers=args.property_numbers or None,
        consolidated_json_path=Path(args.json_path),
        prompt_path=Path(args.prompt_path),
        summary_xls_path=Path(args.summary_xls_path),
        map_payload_path=Path(args.map_payload_path),
        geocode_cache_path=Path(args.geocode_cache_path),
        geocode_api_key=args.geocode_api_key,
    )


if __name__ == "__main__":
    cli()
