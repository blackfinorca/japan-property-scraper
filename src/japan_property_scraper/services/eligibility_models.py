"""Shared models and coercion utilities for Ryokan eligibility."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


STATUS_PASS = "pass"
STATUS_NOT_PASS = "not pass"
STATUS_UNKNOWN = "unknown"

CHECKLIST_STATUSES = {STATUS_PASS, STATUS_NOT_PASS, STATUS_UNKNOWN}
MAJOR_BLOCKER_CODES = {"ZONING", "BUILDING_TYPE", "LISTING_DISCLAIMER"}

ELIGIBILITY_LIKELY_ELIGIBLE = "LIKELY ELIGIBLE"
ELIGIBILITY_LIKELY_NOT_ELIGIBLE = "LIKELY NOT ELIGIBLE"
ELIGIBILITY_UNCERTAIN = "UNCERTAIN"
ELIGIBILITY_ALREADY_A_RYOKAN = "ALREADY A RYOKAN"


@dataclass
class UpdateSummary:
    processed_records: int
    updated_records: int
    missing_property_numbers: list[str]


def coerce_checklist(value: Any) -> list[dict[str, Any]]:
    if value in (None, "", []):
        return []

    if isinstance(value, dict):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        return []

    checklist: list[dict[str, Any]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        code = normalize_code(item.get("code")) or f"OTHER_{index}"
        check = to_text(item.get("check")) or "Checklist item"
        status = normalize_check_status(item.get("status"))
        reason = to_text(item.get("reason") or item.get("detail")) or "No reason provided."
        evidence = to_text(item.get("evidence"))
        is_major_blocker = coerce_bool(item.get("is_major_blocker"))
        if is_major_blocker is None:
            is_major_blocker = code in MAJOR_BLOCKER_CODES
        checklist.append(
            {
                "code": code,
                "check": check,
                "status": status,
                "is_major_blocker": is_major_blocker,
                "reason": reason,
                "evidence": evidence,
            },
        )
    return checklist


def coerce_blockers(value: Any) -> list[dict[str, str]]:
    if value in (None, "", []):
        return []

    if isinstance(value, dict):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        return []

    blockers: list[dict[str, str]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        code = normalize_code(item.get("code")) or f"BLOCKER_{index}"
        reason = to_text(item.get("reason") or item.get("detail"))
        evidence = to_text(item.get("evidence"))
        if not reason:
            continue
        blockers.append({"code": code, "reason": reason, "evidence": evidence})
    return blockers


def coerce_risk_notes(value: Any) -> list[dict[str, str]]:
    if value in (None, "", []):
        return []

    if isinstance(value, dict):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        return []

    notes: list[dict[str, str]] = []
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            continue
        code = normalize_code(item.get("code")) or f"RISK_{index}"
        detail = to_text(item.get("detail") or item.get("reason"))
        if not detail:
            continue
        notes.append({"code": code, "detail": detail})
    return notes


def normalize_check_status(value: Any) -> str:
    text = to_text(value).lower()
    if text in CHECKLIST_STATUSES:
        return text
    if text in {"ok", "clear", "passed", "eligible"}:
        return STATUS_PASS
    if text in {"blocker", "fail", "failed", "not_pass", "not-pass", "ineligible"}:
        return STATUS_NOT_PASS
    return STATUS_UNKNOWN


def normalize_code(value: Any) -> str:
    text = to_text(value).upper()
    if not text:
        return ""
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = to_text(value).lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def flatten_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()
