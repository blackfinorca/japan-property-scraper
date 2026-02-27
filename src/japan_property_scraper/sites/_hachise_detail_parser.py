"""Detail-page parsing utilities for Hachise listings."""

from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from japan_property_scraper.sites._hachise_constants import (
    COMBINED_LABEL_TO_KEYS,
    DETAIL_LABEL_TO_KEY,
    LABEL_ALIASES,
    MULTI_VALUE_DETAIL_KEYS,
    build_detail_regex_label_patterns,
)


DETAIL_REGEX_LABEL_PATTERNS = build_detail_regex_label_patterns()


def parse_detail_fields(detail_html: str) -> dict[str, Any]:
    """Extract normalized detail fields from a listing detail page HTML."""
    soup = BeautifulSoup(detail_html, "lxml")
    parsed: dict[str, Any] = {}

    details_table = _select_best_details_table(soup)
    if details_table is not None:
        _merge_parsed_details(parsed, _parse_details_table(details_table))

    details_dl = _select_best_details_dl(soup)
    if details_dl is not None:
        _merge_parsed_details(parsed, _parse_details_dl(details_dl))

    _apply_regex_fallback(detail_html, parsed)
    _apply_detail_value_fixes(parsed)
    return parsed


def _normalize_label(label: str) -> str:
    normalized = label.replace("\u3000", " ")
    normalized = normalized.replace("：", ":")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip().lower().rstrip(":")


def _resolve_detail_key(normalized_label: str) -> str | None:
    aliased_label = LABEL_ALIASES.get(normalized_label, normalized_label)
    return DETAIL_LABEL_TO_KEY.get(aliased_label)


def _resolve_detail_keys(normalized_label: str) -> list[str]:
    canonical_label = _canonicalize_label(normalized_label)
    if canonical_label in COMBINED_LABEL_TO_KEYS:
        return COMBINED_LABEL_TO_KEYS[canonical_label]

    single_key = _resolve_detail_key(canonical_label)
    if single_key:
        return [single_key]

    if "/" not in canonical_label:
        return []

    keys: list[str] = []
    for part in [segment.strip() for segment in canonical_label.split("/") if segment.strip()]:
        key = _resolve_detail_key(part)
        if key and key not in keys:
            keys.append(key)
    return keys


def _canonicalize_label(normalized_label: str) -> str:
    canonical = normalized_label.replace("／", "/")
    canonical = canonical.replace(" &amp; ", " & ")
    canonical = re.sub(r"\s*/\s*", "/", canonical)
    canonical = re.sub(r"\s*&\s*", " & ", canonical)
    canonical = re.sub(r"\s+", " ", canonical)
    return canonical.strip()


def _select_best_details_table(soup: BeautifulSoup):
    candidates = soup.select("section#details table, section#wrap_details table, table")
    return _select_best_details_block(candidates, heading_selector="th")


def _select_best_details_dl(soup: BeautifulSoup):
    candidates = soup.select("section#details dl, section#wrap_details dl, dl")
    return _select_best_details_block(candidates, heading_selector="dt")


def _select_best_details_block(candidates, heading_selector: str):
    best_table = None
    best_score = 0
    seen_ids: set[int] = set()

    for table in candidates:
        table_id = id(table)
        if table_id in seen_ids:
            continue
        seen_ids.add(table_id)

        matched_keys: set[str] = set()
        for heading in table.select(heading_selector):
            label = _normalize_label(_safe_text(heading))
            detail_keys = _resolve_detail_keys(label)
            for detail_key in detail_keys:
                matched_keys.add(detail_key)

        score = len(matched_keys)
        if score > best_score:
            best_score = score
            best_table = table

    return best_table if best_score >= 3 else None


def _parse_details_table(details_table) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    active_keys: list[str] = []
    remaining_rowspan_rows = 0

    for row in details_table.select("tr"):
        heading = row.find("th")
        if heading is not None:
            normalized_label = _normalize_label(_safe_text(heading))
            active_keys = _resolve_detail_keys(normalized_label)
            remaining_rowspan_rows = _parse_rowspan(heading) - 1
        elif remaining_rowspan_rows <= 0:
            active_keys = []

        value_cell = row.find("td")
        if active_keys and value_cell is not None:
            values = _extract_values_from_cell(
                value_cell=value_cell,
                split_lines=any(key in MULTI_VALUE_DETAIL_KEYS for key in active_keys),
            )
            _assign_values_to_keys(parsed, active_keys, values)

        if heading is None and remaining_rowspan_rows > 0:
            remaining_rowspan_rows -= 1

    return parsed


def _parse_details_dl(details_dl) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    headings = details_dl.find_all("dt")
    values = details_dl.find_all("dd")

    for heading, value_cell in zip(headings, values):
        normalized_label = _normalize_label(_safe_text(heading))
        detail_keys = _resolve_detail_keys(normalized_label)
        if not detail_keys:
            continue

        extracted_values = _extract_values_from_cell(
            value_cell=value_cell,
            split_lines=any(key in MULTI_VALUE_DETAIL_KEYS for key in detail_keys),
        )
        _assign_values_to_keys(parsed, detail_keys, extracted_values)

    return parsed


def _assign_values_to_keys(
    parsed: dict[str, Any],
    detail_keys: list[str],
    values: list[str],
) -> None:
    if not detail_keys or not values:
        return

    if len(detail_keys) == 1:
        parsed.setdefault(detail_keys[0], []).extend(values)
        return

    split_pairs = _split_values_on_combined_separator(values)
    if split_pairs:
        left_values = [left for left, _ in split_pairs if left]
        right_values = [right for _, right in split_pairs if right]
        if left_values:
            parsed.setdefault(detail_keys[0], []).extend(left_values)
        if right_values:
            parsed.setdefault(detail_keys[1], []).extend(right_values)

    if not split_pairs:
        merged_value = " ".join(values).strip()
        if not merged_value:
            return
        parsed.setdefault(detail_keys[0], []).append(merged_value)
        parsed.setdefault(detail_keys[1], []).append(merged_value)


def _split_values_on_combined_separator(values: list[str]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for value in values:
        pair = _split_first_combined_pair(value)
        if pair is not None:
            pairs.append(pair)
    return pairs


def _split_first_combined_pair(value: str) -> tuple[str, str] | None:
    if "／" in value:
        left, right = value.split("／", 1)
        return left.strip(), right.strip()

    slash_match = re.search(r"\s/\s", value)
    if slash_match:
        left, right = value.split("/", 1)
        return left.strip(), right.strip()

    return None


def _parse_rowspan(heading_tag) -> int:
    raw_value = heading_tag.get("rowspan")
    if raw_value is None:
        return 1
    try:
        parsed = int(str(raw_value))
        return parsed if parsed > 0 else 1
    except ValueError:
        return 1


def _apply_regex_fallback(detail_html: str, parsed: dict[str, Any]) -> None:
    for key, labels in DETAIL_REGEX_LABEL_PATTERNS.items():
        existing = parsed.get(key)
        if existing:
            continue

        extracted_values: list[str] = []
        for label in labels:
            extracted_values = _extract_values_by_label_regex(detail_html, label)
            if extracted_values:
                break

        if not extracted_values:
            continue
        if key in MULTI_VALUE_DETAIL_KEYS:
            parsed[key] = extracted_values
        else:
            parsed[key] = [" ".join(extracted_values).strip()]


def _extract_values_by_label_regex(detail_html: str, label: str) -> list[str]:
    label_pattern = re.escape(label)
    label_pattern = label_pattern.replace(r"\ ", r"\s*")
    label_pattern = label_pattern.replace(r"\&", r"(?:&|&amp;)")
    label_pattern = label_pattern.replace(r"\　", r"\s*")

    row_pattern = re.compile(
        rf"<th[^>]*?(?:rowspan=['\"]?(?P<rowspan>\d+)['\"]?)?[^>]*>"
        rf"\s*{label_pattern}\s*</th>\s*<td[^>]*>(?P<first>.*?)</td>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    continuation_pattern = re.compile(
        r"<tr[^>]*>\s*<td[^>]*>(.*?)</td>\s*</tr>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    dl_pattern = re.compile(
        rf"<dt[^>]*>\s*{label_pattern}\s*</dt>\s*<dd[^>]*>(?P<value>.*?)</dd>",
        flags=re.IGNORECASE | re.DOTALL,
    )

    values: list[str] = []
    for match in row_pattern.finditer(detail_html):
        first_values = _split_html_lines(match.group("first"))
        if first_values:
            values.extend(first_values)

        rowspan_value = match.group("rowspan")
        if not rowspan_value:
            continue

        try:
            extra_rows = max(int(rowspan_value) - 1, 0)
        except ValueError:
            extra_rows = 0
        if extra_rows == 0:
            continue

        tail = detail_html[match.end() :]
        continuation_matches = continuation_pattern.finditer(tail)
        for _ in range(extra_rows):
            continuation_match = next(continuation_matches, None)
            if continuation_match is None:
                break
            continuation_values = _split_html_lines(continuation_match.group(1))
            if continuation_values:
                values.extend(continuation_values)

    for match in dl_pattern.finditer(detail_html):
        extracted_values = _split_html_lines(match.group("value"))
        if extracted_values:
            values.extend(extracted_values)

    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            deduped.append(value)
            seen.add(value)
    return deduped


def _extract_values_from_cell(value_cell, split_lines: bool) -> list[str]:
    if split_lines:
        values = _split_html_lines(value_cell.decode_contents())
        if values:
            return values
    value = _safe_text(value_cell)
    return [value] if value else []


def _split_html_lines(html_fragment: str) -> list[str]:
    parts = re.split(r"<br\s*/?>", html_fragment, flags=re.IGNORECASE)
    values = [_clean_html_fragment(part) for part in parts]
    return [value for value in values if value]


def _clean_html_fragment(html_fragment: str) -> str:
    text = BeautifulSoup(html_fragment, "lxml").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _merge_parsed_details(base: dict[str, Any], incoming: dict[str, Any]) -> None:
    for key, raw_values in incoming.items():
        values = [value for value in raw_values if value]
        if not values:
            continue
        existing = base.get(key)
        if not existing:
            base[key] = values
            continue
        if key in MULTI_VALUE_DETAIL_KEYS:
            for value in values:
                if value not in existing:
                    existing.append(value)


def _apply_detail_value_fixes(parsed: dict[str, Any]) -> None:
    building_coverage_values = parsed.get("building_coverage_ratio", [])
    if not building_coverage_values:
        return

    ratio_values = [
        value for value in building_coverage_values if "%" in value or "％" in value
    ]
    possible_land_category_values = [
        value for value in building_coverage_values if value not in ratio_values
    ]
    if ratio_values:
        parsed["building_coverage_ratio"] = ratio_values
    if possible_land_category_values and not parsed.get("land_category"):
        parsed["land_category"] = possible_land_category_values

    # Some pages incorrectly pair Land Category/Land Tenure and place
    # Geographical Features under the second value (e.g., "Flatland").
    land_tenure_values = parsed.get("land_tenure", [])
    if land_tenure_values:
        likely_tenure = []
        likely_geo = []
        for value in land_tenure_values:
            lowered = value.lower()
            if any(token in lowered for token in ("title", "leasehold", "freehold")):
                likely_tenure.append(value)
            else:
                likely_geo.append(value)

        if likely_tenure:
            parsed["land_tenure"] = likely_tenure
        else:
            parsed["land_tenure"] = []

        if likely_geo and not parsed.get("geographical_features"):
            parsed["geographical_features"] = likely_geo


def _safe_text(tag) -> str:
    if tag is None:
        return ""
    return tag.get_text(" ", strip=True)
