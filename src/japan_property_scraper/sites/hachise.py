"""Hachise property list scraper."""

from __future__ import annotations

from datetime import datetime
import logging
import math
import re
import time
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import requests
from tqdm import tqdm

from japan_property_scraper.sites._hachise_constants import (
    DEFAULT_USD_RATE,
    LIST_URL,
    MAX_FETCH_RETRIES,
    MULTI_VALUE_DETAIL_KEYS,
    RATE_URL,
    REQUEST_HEADERS,
    RETRY_DELAY_SECONDS,
    TIMEOUT_SECONDS,
)
from japan_property_scraper.sites._hachise_detail_parser import parse_detail_fields


LOGGER = logging.getLogger(__name__)

SCALAR_DETAIL_FIELDS = (
    "property_price_text",
    "type_conditions",
    "size",
    "renovations",
    "private_street_area_included",
    "building_structure",
    "building_date",
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
    "transaction_terms",
    "sales_representative",
    "information_updated",
    "information_will_be_updated",
)


def scrape_hachise() -> list[dict]:
    """Scrape Hachise property listings with normalized output fields."""
    with requests.Session() as session:
        list_html = _fetch_page(session, LIST_URL)
        usd_rate = _fetch_usd_rate(session)
        soup = BeautifulSoup(list_html, "lxml")
        cards = soup.select("ul.listings > li.property")
        scrape_timestamp = datetime.now().isoformat(timespec="seconds")
        detail_cache: dict[str, dict[str, Any]] = {}

        listings: list[dict] = []
        for card in tqdm(
            cards,
            desc="Hachise listings",
            unit="listing",
            total=len(cards),
            dynamic_ncols=True,
        ):
            listing = _parse_card(
                card=card,
                usd_rate=usd_rate,
                scrape_timestamp=scrape_timestamp,
                session=session,
                detail_cache=detail_cache,
            )
            if listing is not None:
                listings.append(listing)

    return listings


def _fetch_page(session: requests.Session, url: str) -> str:
    last_error: requests.RequestException | None = None
    for attempt in range(1, MAX_FETCH_RETRIES + 1):
        try:
            response = session.get(
                url,
                headers=REQUEST_HEADERS,
                timeout=TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            if response.encoding is None or response.encoding.lower() == "iso-8859-1":
                response.encoding = "utf-8"
            return response.text
        except requests.RequestException as error:
            last_error = error
            if attempt < MAX_FETCH_RETRIES:
                LOGGER.warning(
                    "Request failed (%s/%s) for %s: %s",
                    attempt,
                    MAX_FETCH_RETRIES,
                    url,
                    error,
                )
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            raise

    raise RuntimeError(f"Unreachable request state for URL: {url}") from last_error


def _fetch_usd_rate(session: requests.Session) -> float:
    try:
        script_text = _fetch_page(session, RATE_URL)
        match = re.search(r"var\s+rate\s*=\s*([0-9.]+)", script_text)
        if match:
            return float(match.group(1))
    except (requests.RequestException, ValueError):
        LOGGER.warning("Falling back to default USD rate %.4f", DEFAULT_USD_RATE)

    return DEFAULT_USD_RATE


def _parse_card(
    card,
    usd_rate: float,
    scrape_timestamp: str,
    session: requests.Session,
    detail_cache: dict[str, dict[str, Any]],
) -> dict | None:
    property_number = _extract_property_number(_safe_text(card.select_one("span.no")))
    if not property_number:
        return None

    heading = card.select_one("div.topbox h3")
    address = _safe_text(heading.select_one("span.address")) if heading else ""
    property_name = _extract_property_name(heading, address)
    location = _extract_location(address)

    info_texts = [
        _safe_text(tag)
        for tag in card.select("div.linkBox li p")
        if _safe_text(tag)
    ]
    land_area_list = _extract_labeled_value(info_texts, "Land")
    floor_area_list = _extract_labeled_value(info_texts, "Floor")
    reno_source = info_texts[2] if len(info_texts) > 2 else ""
    type_source = info_texts[3] if len(info_texts) > 3 else ""

    price_jpy_text = _safe_text(card.select_one("li.price span.jpy"))
    price_jpy = _extract_number(price_jpy_text)
    price_usd = math.ceil(price_jpy * usd_rate) if price_jpy else None

    status_values = [
        _safe_text(tag)
        for tag in card.select("div.category p")
        if _safe_text(tag)
    ]
    status = " | ".join(status_values)

    href = card.select_one("p.mainImage a")
    detail_url = urljoin(LIST_URL, href["href"]) if href and href.get("href") else ""
    details = _get_detail_fields(session, detail_url, detail_cache)

    detail_location = _first_or_empty_list(details.get("detail_location"))
    detail_land_area = _first_or_empty_list(details.get("detail_land_area"))
    detail_floor_area = _first_or_empty_list(details.get("detail_floor_area"))
    type_conditions = _first_or_empty_list(details.get("type_conditions"))
    detail_price_text = _first_or_empty_list(details.get("property_price_text"))
    if type_conditions != []:
        type_source = str(type_conditions)

    if price_jpy is None and detail_price_text != []:
        price_jpy = _extract_number(str(detail_price_text))
        detail_price_usd = _extract_approx_usd(str(detail_price_text))
        if detail_price_usd is not None:
            price_usd = detail_price_usd
        elif price_jpy:
            price_usd = math.ceil(price_jpy * usd_rate)

    resolved_location = (
        detail_location if detail_location != [] else _empty_list_or_value(location)
    )
    resolved_address = (
        detail_location if detail_location != [] else _empty_list_or_value(address)
    )
    resolved_land_area = (
        detail_land_area if detail_land_area != [] else _empty_list_or_value(land_area_list)
    )
    resolved_floor_area = (
        detail_floor_area
        if detail_floor_area != []
        else _empty_list_or_value(floor_area_list)
    )

    listing = {
        "property_number": property_number,
        "property_name": property_name,
        "location": resolved_location,
        "address": resolved_address,
        "land_area": resolved_land_area,
        "floor_area": resolved_floor_area,
        "reno_status": _normalize_reno_status(reno_source),
        "type": _normalize_type(type_source),
        "price_jpy": price_jpy,
        "price_usd": price_usd,
        "status": _empty_list_or_value(status),
        "time_stamp": scrape_timestamp,
        "summary": "",
        "site": "hachise",
        "listing_id": property_number,
        "title": property_name,
        "url": _empty_list_or_value(detail_url),
    }
    detail_fields = _build_detail_fields(details)
    detail_fields["property_price_text"] = _resolve_property_price_text(
        detail_price_text=detail_price_text,
        price_jpy=price_jpy,
        price_usd=price_usd,
        usd_rate=usd_rate,
    )
    listing.update(detail_fields)
    return listing


def _build_detail_fields(details: dict[str, Any]) -> dict[str, Any]:
    detail_fields: dict[str, Any] = {}
    for key in MULTI_VALUE_DETAIL_KEYS:
        detail_fields[key] = _multi_or_empty_list(details.get(key))
    for key in SCALAR_DETAIL_FIELDS:
        detail_fields[key] = _first_or_empty_list(details.get(key))
    return detail_fields


def _extract_property_number(text: str) -> str:
    match = re.search(r"No\.\s*([^\]]+)", text)
    if match:
        return match.group(1).strip()
    return text.replace("[", "").replace("]", "").strip()


def _extract_property_name(heading, address: str) -> str:
    if heading is None:
        return ""

    text = " ".join(heading.stripped_strings)
    if address and text.endswith(address):
        text = text[: -len(address)].strip()
    return re.sub(r"\s+", " ", text)


def _extract_location(address: str) -> str:
    if not address:
        return ""
    parts = [part.strip() for part in address.split(",") if part.strip()]
    if len(parts) > 1:
        return parts[-1]
    return address


def _extract_labeled_value(texts: list[str], label: str) -> str:
    label_prefix = f"{label.lower()}:"
    for text in texts:
        if text.lower().startswith(label_prefix):
            return text.split(":", 1)[1].strip()
    return ""


def _normalize_reno_status(text: str) -> str:
    lowered = text.lower().replace("-", "").replace(" ", "")
    if "non" in lowered and "renovated" in lowered:
        return "nonrenovated"
    if "renovated" in lowered:
        return "renovated"
    return "others"


def _normalize_type(text: str) -> str:
    lowered = text.lower().strip()
    if not lowered or lowered == "--":
        return "others"
    compact = lowered.replace("-", "").replace(" ", "")
    if "machiya" in compact:
        return "kyo_machiya"
    return _to_snake_case(lowered)


def _extract_number(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text)
    if not digits:
        return None
    return int(digits)


def _extract_approx_usd(text: str) -> int | None:
    match = re.search(r"approx\.\s*([\d,]+)\s*usd", text, flags=re.IGNORECASE)
    if not match:
        return None
    digits = re.sub(r"[^\d]", "", match.group(1))
    if not digits:
        return None
    return int(digits)


def _resolve_property_price_text(
    *,
    detail_price_text: Any,
    price_jpy: int | None,
    price_usd: Any,
    usd_rate: float,
) -> Any:
    raw = str(detail_price_text).strip() if detail_price_text not in (None, []) else ""
    if raw and not _looks_like_price_placeholder(raw):
        return raw

    if price_jpy is None:
        return _empty_list_or_value(raw)

    usd_value: int
    if isinstance(price_usd, int):
        usd_value = price_usd
    else:
        usd_value = math.ceil(price_jpy * usd_rate)

    return (
        f"{price_jpy:,} JPY "
        f"(Approx. {usd_value:,} USD *1JPY={usd_rate:.4f} USD)"
    )


def _looks_like_price_placeholder(text: str) -> bool:
    lowered = text.lower()
    if not lowered:
        return True
    # Hachise injects USD and FX-rate via JS into empty spans on the client.
    if re.search(r"approx\.\s*usd", lowered):
        return True
    if re.search(r"1jpy\s*=\s*usd", lowered):
        return True
    return False


def _to_snake_case(text: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return normalized or "others"


def _safe_text(tag) -> str:
    if tag is None:
        return ""
    return tag.get_text(" ", strip=True)


def _get_detail_fields(
    session: requests.Session,
    detail_url: str,
    detail_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not detail_url:
        return {}
    if detail_url in detail_cache:
        return detail_cache[detail_url]

    try:
        detail_html = _fetch_page(session, detail_url)
        details = parse_detail_fields(detail_html)
    except (requests.RequestException, RuntimeError, ValueError) as error:
        LOGGER.warning("Failed to parse detail page %s: %s", detail_url, error)
        details = {}

    detail_cache[detail_url] = details
    return details


def _first_or_empty_list(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else []
    return value if value else []


def _multi_or_empty_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return value if value else []
    return [value] if value else []


def _empty_list_or_value(value: str) -> Any:
    return value if value else []
