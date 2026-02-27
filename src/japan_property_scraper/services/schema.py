"""Shared listing schema normalization utilities."""

from __future__ import annotations

from typing import Any


REQUIRED_ADDITIONAL_FIELDS = [
    "transportations",
    "private_street_area_included",
    "building_structure",
    "building_date",
    "adjoining_street",
    "public_utility",
    "land_use_district",
    "legal_restrictions",
    "handover",
    "current_situation",
    "building_coverage_ratio",
    "floor_area_ratio",
    "land_category",
    "geographical_features",
    "land_tenure",
    "notification_according_to_national_land_utilization_law",
    "elementary_school",
    "junior_high_school",
    "city_planning_act",
    "remarks",
    "transaction_terms",
    "sales_representative",
    "information_updated",
    "information_will_be_updated",
]

LIST_TYPED_FIELDS = {
    "transportations",
    "adjoining_street",
    "remarks",
}


def normalize_listing_schema(listing: dict[str, Any]) -> dict[str, Any]:
    """Ensure required additional fields exist with [] for missing values."""
    normalized = dict(listing)
    for field in REQUIRED_ADDITIONAL_FIELDS:
        value = normalized.get(field)
        if field in LIST_TYPED_FIELDS:
            normalized[field] = _normalize_list_field(value)
        else:
            normalized[field] = _normalize_scalar_field(value)
    return normalized


def normalize_listings_schema(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize schema for all listing dictionaries."""
    return [normalize_listing_schema(listing) for listing in listings]


def _normalize_list_field(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return [item for item in value if item not in (None, "")]
    return [value]


def _normalize_scalar_field(value: Any) -> Any:
    if value in (None, ""):
        return []
    return value
