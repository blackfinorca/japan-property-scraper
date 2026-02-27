"""Constants and label mappings for Hachise scraping."""

from __future__ import annotations


LIST_URL = "https://www.hachise.com/buy/list.html"
RATE_URL = "https://www.hachise.com/common/js/rate.js"
DEFAULT_USD_RATE = 0.0065
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}
TIMEOUT_SECONDS = 30
MAX_FETCH_RETRIES = 3
RETRY_DELAY_SECONDS = 0.6

DETAIL_LABEL_TO_KEY = {
    "location": "detail_location",
    "transportations": "transportations",
    "land area": "detail_land_area",
    "private street area included": "private_street_area_included",
    "floor area": "detail_floor_area",
    "building structure": "building_structure",
    "building date": "building_date",
    "size": "size",
    "adjoining street": "adjoining_street",
    "public utility": "public_utility",
    "land use district": "land_use_district",
    "legal restrictions": "legal_restrictions",
    "handover": "handover",
    "current situation": "current_situation",
    "building coverage ratio": "building_coverage_ratio",
    "floor area ratio": "floor_area_ratio",
    "land category": "land_category",
    "geographical features": "geographical_features",
    "land tenure": "land_tenure",
    "notification according to national land utilization law": (
        "notification_according_to_national_land_utilization_law"
    ),
    "elementary school": "elementary_school",
    "junior high school": "junior_high_school",
    "city planning act": "city_planning_act",
    "remarks": "remarks",
    "transaction terms": "transaction_terms",
    "sales representative": "sales_representative",
    "information updated": "information_updated",
    "information will be updated": "information_will_be_updated",
    "type & conditions": "type_conditions",
}

MULTI_VALUE_DETAIL_KEYS = {"transportations", "adjoining_street", "remarks"}

LABEL_ALIASES = {
    "transportation": "transportations",
    "transportation(s)": "transportations",
    "tranportations": "transportations",
    "private road area included": "private street area included",
    "legal restriction": "legal restrictions",
    "locations": "location",
    "sales represetative": "sales representative",
    "sales representatives": "sales representative",
    "coordinated by": "sales representative",
    "dealer (real estate agent)": "transaction terms",
    "conditions": "type & conditions",
    "property": "type & conditions",
    "notification according to national land use law": (
        "notification according to national land utilization law"
    ),
}

COMBINED_LABEL_TO_KEYS = {
    "handover/current situation": ["handover", "current_situation"],
    "building coverage ratio/floor area ratio": [
        "building_coverage_ratio",
        "floor_area_ratio",
    ],
    "land category/geographical features": [
        "land_category",
        "geographical_features",
    ],
    "land tenure/notification according to national land utilization law": [
        "land_tenure",
        "notification_according_to_national_land_utilization_law",
    ],
    "elementary school/junior high school": [
        "elementary_school",
        "junior_high_school",
    ],
    "elementary & junior high school": [
        "elementary_school",
        "junior_high_school",
    ],
    "land category/land tenure": ["land_category", "land_tenure"],
    "land area/land category": ["detail_land_area", "land_category"],
    "floor area/building structure": ["detail_floor_area", "building_structure"],
}


def build_detail_regex_label_patterns() -> dict[str, list[str]]:
    """Return regex fallback label map keyed by normalized output field."""
    patterns: dict[str, list[str]] = {}
    for label, key in DETAIL_LABEL_TO_KEY.items():
        patterns.setdefault(key, []).append(label)
    patterns["transportations"].extend(["transportation", "transportation(s)"])
    return patterns
