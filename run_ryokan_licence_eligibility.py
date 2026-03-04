"""Entry point for Ryokan licence eligibility estimation."""

from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from japan_property_scraper.services.ryokan_licence_eligibility import cli  # noqa: E402


if __name__ == "__main__":
    cli()
