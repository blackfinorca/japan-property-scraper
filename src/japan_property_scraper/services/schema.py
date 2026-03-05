"""Shared listing schema normalization utilities."""

from __future__ import annotations

import re
from typing import Any


REQUIRED_ADDITIONAL_FIELDS = [
    "property_price_text",
    "type_conditions",
    "size",
    "renovations",
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
    "price_per_m2",
    "price_per_m2_benchmark",
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
    _normalize_floor_area_and_price(normalized)
    return normalized


def normalize_listings_schema(listings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize schema for all listing dictionaries."""
    normalized_listings = [normalize_listing_schema(listing) for listing in listings]
    _apply_price_per_m2_benchmark(normalized_listings)
    return normalized_listings


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


def _normalize_floor_area_and_price(normalized: dict[str, Any]) -> None:
    floor_area_sqm = _extract_floor_area_total_sqm(normalized.get("floor_area"))
    if floor_area_sqm is not None:
        normalized["floor_area"] = _format_sqm(floor_area_sqm)
    elif normalized.get("floor_area") in (None, ""):
        normalized["floor_area"] = []

    price_jpy = _extract_number(normalized.get("price_jpy"))
    if price_jpy is None or floor_area_sqm is None or floor_area_sqm <= 0:
        normalized["price_per_m2"] = []
        return

    normalized["price_per_m2"] = int(round(price_jpy / floor_area_sqm))


def _apply_price_per_m2_benchmark(normalized_listings: list[dict[str, Any]]) -> None:
    values: list[float] = []
    for listing in normalized_listings:
        value = _extract_number(listing.get("price_per_m2"))
        if value is None or value <= 0:
            continue
        values.append(value)

    benchmark: int | list[Any]
    if values:
        benchmark = int(round(sum(values) / len(values)))
    else:
        benchmark = []

    for listing in normalized_listings:
        listing["price_per_m2_benchmark"] = benchmark


def _extract_floor_area_total_sqm(value: Any) -> float | None:
    text = _to_text(value)
    if not text:
        return None

    normalized_text = _normalize_area_text(text)

    total_matches = re.findall(
        r"(?:total|合計)[^0-9]*([0-9]+(?:\.[0-9]+)?)",
        normalized_text,
        flags=re.IGNORECASE,
    )
    if total_matches:
        return max(float(match) for match in total_matches)

    floor_matches = re.findall(
        r"(?:\bb?\d+f\b|\d+\s*階)[^0-9]*([0-9]+(?:\.[0-9]+)?)",
        normalized_text,
        flags=re.IGNORECASE,
    )
    if len(floor_matches) >= 2:
        return sum(float(match) for match in floor_matches)

    sqm_matches = re.findall(
        r"([0-9]+(?:\.[0-9]+)?)\s*(?:sqm|sq\.?\s*m|m2)",
        normalized_text,
        flags=re.IGNORECASE,
    )
    if sqm_matches:
        values = [float(match) for match in sqm_matches]
        if len(values) == 1:
            return values[0]
        return max(values)

    bare_matches = re.findall(r"([0-9]+(?:\.[0-9]+)?)", normalized_text)
    if len(bare_matches) == 1:
        return float(bare_matches[0])
    return None


def _normalize_area_text(text: str) -> str:
    normalized = text
    normalized = normalized.replace("\u3000", " ")
    normalized = normalized.replace("：", ":")
    normalized = normalized.replace("㎡", " sqm ")
    normalized = normalized.replace("m²", " m2 ")
    normalized = normalized.replace("sq.m", " sqm")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _format_sqm(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text} sqm"


def _extract_number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = _to_text(value)
    if not text:
        return None

    digits = re.sub(r"[^\d.]", "", text)
    if not digits:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def _to_text(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()
