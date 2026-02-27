"""Main scraper workflow."""

from datetime import datetime
import logging
from typing import Callable

from japan_property_scraper.config import TIMESTAMP_FORMAT
from japan_property_scraper.services.consolidation import (
    append_new_or_changed_listings,
)
from japan_property_scraper.services.exporters import export_site_results
from japan_property_scraper.sites import scrape_hachise


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
LOGGER = logging.getLogger(__name__)

SITE_SCRAPERS: dict[str, Callable[[], list[dict]]] = {
    "hachise": scrape_hachise,
}


def run() -> None:
    """Run all site scrapers and update output files."""
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


if __name__ == "__main__":
    run()
