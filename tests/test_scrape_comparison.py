import unittest
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from japan_property_scraper.services.scrape_comparison import build_scrape_comparison


class ScrapeComparisonTests(unittest.TestCase):
    def test_detects_added_removed_price_changes_and_other_changes(self):
        previous = [
            {
                "site": "hachise",
                "listing_id": "100",
                "property_number": "100",
                "property_name": "Old Stable",
                "price_jpy": 10_000_000,
                "url": "https://example.com/100",
                "reno_status": "renovated",
            },
            {
                "site": "hachise",
                "listing_id": "200",
                "property_number": "200",
                "property_name": "Price Drop",
                "price_jpy": "25,000,000",
                "url": "https://example.com/200",
            },
            {
                "site": "hachise",
                "listing_id": "300",
                "property_number": "300",
                "property_name": "Removed House",
                "price_jpy": 30_000_000,
                "url": "https://example.com/300",
                "status": "Apr 10, Price Changed",
            },
            {
                "site": "hachise",
                "listing_id": "400",
                "property_number": "400",
                "property_name": "Status Change",
                "price_jpy": 40_000_000,
                "url": "https://example.com/400",
                "status": "Recently Updated",
                "reno_status": "others",
            },
        ]
        current = [
            {
                "site": "hachise",
                "listing_id": "100",
                "property_number": "100",
                "property_name": "Old Stable",
                "price_jpy": 10_000_000,
                "url": "https://example.com/100",
                "reno_status": "renovated",
            },
            {
                "site": "hachise",
                "listing_id": "200",
                "property_number": "200",
                "property_name": "Price Drop",
                "price_jpy": 22_000_000,
                "url": "https://example.com/200",
                "status": "Apr 25, Price Changed",
            },
            {
                "site": "hachise",
                "listing_id": "400",
                "property_number": "400",
                "property_name": "Status Change",
                "price_jpy": 40_000_000,
                "url": "https://example.com/400",
                "status": "Recently Updated",
                "reno_status": "renovated",
            },
            {
                "site": "hachise",
                "listing_id": "500",
                "property_number": "500",
                "property_name": "New House",
                "price_jpy": 50_000_000,
                "url": "https://example.com/500",
                "status": "New",
            },
        ]

        report = build_scrape_comparison(
            previous_records=previous,
            current_records=current,
            status_history_records=[
                {
                    "site": "hachise",
                    "listing_id": "200",
                    "property_number": "200",
                    "status": "Mar 1, Newly Listed",
                    "price_jpy": 25_000_000,
                    "run_timestamp": "20260301_100000",
                    "time_stamp": "2026-03-01T10:00:00",
                },
                {
                    "site": "hachise",
                    "listing_id": "200",
                    "property_number": "200",
                    "status": "Apr 25, Price Changed",
                    "price_jpy": 22_000_000,
                    "run_timestamp": "20260502_120000",
                    "time_stamp": "2026-05-02T12:00:00",
                },
            ],
            run_timestamp="20260502_120000",
        )

        self.assertEqual(report["summary"]["added"], 1)
        self.assertEqual(report["summary"]["removed"], 1)
        self.assertEqual(report["summary"]["price_changed"], 1)
        self.assertEqual(report["summary"]["other_changed"], 1)

        self.assertEqual(report["added"][0]["property_number"], "500")
        self.assertEqual(report["added"][0]["url"], "https://example.com/500")
        self.assertEqual(report["added"][0]["status"], "New")
        self.assertEqual(report["removed"][0]["property_number"], "300")
        self.assertEqual(report["removed"][0]["url"], "https://example.com/300")
        self.assertEqual(report["removed"][0]["status"], "Apr 10, Price Changed")

        price_change = report["price_changed"][0]
        self.assertEqual(price_change["property_number"], "200")
        self.assertEqual(price_change["url"], "https://example.com/200")
        self.assertEqual(price_change["status"], "Apr 25, Price Changed")
        self.assertEqual(
            price_change["status_history"],
            [
                {
                    "run_timestamp": "20260301_100000",
                    "time_stamp": "2026-03-01T10:00:00",
                    "status": "Mar 1, Newly Listed",
                },
                {
                    "run_timestamp": "20260502_120000",
                    "time_stamp": "2026-05-02T12:00:00",
                    "status": "Apr 25, Price Changed",
                },
            ],
        )
        self.assertEqual(
            price_change["price_history"],
            [
                {
                    "run_timestamp": "20260301_100000",
                    "time_stamp": "2026-03-01T10:00:00",
                    "price_jpy": 25_000_000,
                },
                {
                    "run_timestamp": "20260502_120000",
                    "time_stamp": "2026-05-02T12:00:00",
                    "price_jpy": 22_000_000,
                },
            ],
        )
        self.assertEqual(price_change["old_price_jpy"], 25_000_000)
        self.assertEqual(price_change["new_price_jpy"], 22_000_000)
        self.assertEqual(price_change["delta_jpy"], -3_000_000)
        self.assertEqual(price_change["direction"], "down")

        other_change = report["other_changed"][0]
        self.assertEqual(other_change["property_number"], "400")
        self.assertEqual(other_change["status"], "Recently Updated")
        self.assertEqual(other_change["changed_fields"], ["reno_status"])

    def test_uses_property_number_when_listing_id_is_missing(self):
        previous = [{"site": "hachise", "property_number": "70001", "price_jpy": 1}]
        current = [{"site": "hachise", "property_number": "70001", "price_jpy": 2}]

        report = build_scrape_comparison(
            previous_records=previous,
            current_records=current,
            run_timestamp="20260502_120000",
        )

        self.assertEqual(report["summary"]["price_changed"], 1)
        self.assertEqual(report["price_changed"][0]["property_number"], "70001")


if __name__ == "__main__":
    unittest.main()
