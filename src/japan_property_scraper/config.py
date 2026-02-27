"""Configuration values for the scraper."""

from pathlib import Path


BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "output"
RAW_DIR = OUTPUT_DIR / "raw"
CONSOLIDATED_DIR = OUTPUT_DIR / "consolidated"

TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
