"""Rule engine for Ryokan eligibility decisions."""

from __future__ import annotations

import re
from typing import Any

from japan_property_scraper.services.eligibility_models import (
    ELIGIBILITY_ALREADY_A_RYOKAN,
    ELIGIBILITY_LIKELY_ELIGIBLE,
    ELIGIBILITY_LIKELY_NOT_ELIGIBLE,
    ELIGIBILITY_UNCERTAIN,
    STATUS_NOT_PASS,
    STATUS_PASS,
    STATUS_UNKNOWN,
    flatten_value,
)


def build_assessment_from_model(
    *,
    record: dict[str, Any],
    model_checklist: list[dict[str, Any]],
    model_blockers: list[dict[str, str]],
    model_risk_notes: list[dict[str, str]],
) -> dict[str, Any]:
    checklist = merge_checklists(record, model_checklist)
    blockers = derive_blockers(checklist)
    risk_notes = derive_risk_notes(
        checklist=checklist,
        blockers=blockers,
        model_risk_notes=model_risk_notes,
        model_blockers=model_blockers,
    )
    eligibility = decide_eligibility(checklist, blockers)
    dealbreaker = blockers[0]["reason"] if blockers else None

    return {
        "ryokan_licence_eligibility": eligibility,
        "ryokan_licence_blockers": blockers,
        "ryokan_licence_dealbreaker": dealbreaker,
        "ryokan_licence_dealbreaker_checklist": checklist,
        "ryokan_licence_risk_notes": risk_notes,
    }


def detect_already_ryokan_fast_pass(record: dict[str, Any]) -> str | None:
    current_situation_text = flatten_value(record.get("current_situation"))
    remarks_text = flatten_value(record.get("remarks"))
    current_situation_lower = current_situation_text.lower()
    remarks_lower = remarks_text.lower()

    operation_markers = [
        "in operation as an inn",
        "currently in operation as an inn",
        "operating as an inn",
    ]
    has_inn_operation = any(
        marker in current_situation_lower or marker in remarks_lower
        for marker in operation_markers
    )
    if not has_inn_operation:
        return None

    has_reapply_or_succession = any(
        token in remarks_lower
        for token in [
            "reapply",
            "re-apply",
            "reapplication",
            "re-application",
            "succession",
            "successor",
            "business transfer",
            "transfer procedures",
        ]
    )
    has_licence_context = any(
        token in remarks_lower
        for token in [
            "license",
            "licence",
            "permit",
            "registration",
            "inn",
            "ryokan",
            "short-term rental",
            "minpaku",
        ]
    )
    if not (has_reapply_or_succession and has_licence_context):
        return None

    return (
        f"current_situation: {current_situation_text or 'N/A'} | "
        f"remarks: {remarks_text or 'N/A'}"
    )


def build_already_ryokan_assessment(
    *,
    record: dict[str, Any],
    evidence: str,
) -> dict[str, Any]:
    _, area_reason, area_evidence = evaluate_floor_area(record)
    checklist = [
        {
            "code": "ALREADY_RYOKAN_OPERATION",
            "check": "Already operating as an inn with succession/reapply signal",
            "status": STATUS_PASS,
            "is_major_blocker": False,
            "reason": (
                "Listing indicates active inn operation and mentions licence "
                "reapplication/succession."
            ),
            "evidence": evidence,
        },
        {
            "code": "ZONING",
            "check": "Zoning allows Ryokan route",
            "status": STATUS_PASS,
            "is_major_blocker": True,
            "reason": (
                "Existing inn operation is a strong positive signal that zoning "
                "constraints were previously cleared."
            ),
            "evidence": evidence,
        },
        {
            "code": "BUILDING_TYPE",
            "check": "Building type is suitable",
            "status": STATUS_PASS,
            "is_major_blocker": True,
            "reason": (
                "Existing inn operation is a strong positive signal that building "
                "type constraints were previously cleared."
            ),
            "evidence": evidence,
        },
        {
            "code": "LISTING_DISCLAIMER",
            "check": "No listing-level inn prohibition",
            "status": STATUS_PASS,
            "is_major_blocker": True,
            "reason": (
                "Listing includes operational inn/succession language rather than "
                "an inn prohibition."
            ),
            "evidence": evidence,
        },
        {
            "code": "FLOOR_AREA",
            "check": "Minimum floor area baseline (>=33 sqm)",
            "status": STATUS_UNKNOWN,
            "is_major_blocker": False,
            "reason": (
                "Already-operating inn fast-pass applied. Area should still be "
                "verified for current licensing requirements."
            ),
            "evidence": area_evidence or area_reason,
        },
    ]
    risk_notes = [
        {
            "code": "LICENSE_SUCCESSION",
            "detail": (
                "Verify exact Kyoto City licence succession/reapplication steps "
                "before transfer."
            ),
        },
    ]
    return {
        "ryokan_licence_eligibility": ELIGIBILITY_ALREADY_A_RYOKAN,
        "ryokan_licence_blockers": [],
        "ryokan_licence_dealbreaker": None,
        "ryokan_licence_dealbreaker_checklist": checklist,
        "ryokan_licence_risk_notes": risk_notes,
    }


def merge_checklists(
    record: dict[str, Any],
    model_checklist: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    default_checklist = build_default_checklist(record)
    mandatory_codes = {item["code"] for item in default_checklist}
    if not model_checklist:
        return default_checklist

    merged = list(default_checklist)
    existing_codes = set(mandatory_codes)
    for item in model_checklist:
        if item["code"] in existing_codes:
            continue
        merged.append(item)
        existing_codes.add(item["code"])
    return merged


def build_default_checklist(record: dict[str, Any]) -> list[dict[str, Any]]:
    zoning_status, zoning_reason, zoning_evidence = evaluate_zoning(record)
    building_status, building_reason, building_evidence = evaluate_building_type(record)
    disclaimer_status, disclaimer_reason, disclaimer_evidence = evaluate_disclaimer(record)
    area_status, area_reason, area_evidence = evaluate_floor_area(record)

    return [
        {
            "code": "ZONING",
            "check": "Zoning allows Ryokan route",
            "status": zoning_status,
            "is_major_blocker": True,
            "reason": zoning_reason,
            "evidence": zoning_evidence,
        },
        {
            "code": "BUILDING_TYPE",
            "check": "Building type is suitable",
            "status": building_status,
            "is_major_blocker": True,
            "reason": building_reason,
            "evidence": building_evidence,
        },
        {
            "code": "LISTING_DISCLAIMER",
            "check": "No listing-level inn prohibition",
            "status": disclaimer_status,
            "is_major_blocker": True,
            "reason": disclaimer_reason,
            "evidence": disclaimer_evidence,
        },
        {
            "code": "FLOOR_AREA",
            "check": "Minimum floor area baseline (>=33 sqm)",
            "status": area_status,
            "is_major_blocker": False,
            "reason": area_reason,
            "evidence": area_evidence,
        },
    ]


def evaluate_zoning(record: dict[str, Any]) -> tuple[str, str, str]:
    zoning = flatten_value(record.get("land_use_district"))
    zoning_lower = zoning.lower()
    if _contains_low_rise_zone(zoning_lower):
        return (
            STATUS_NOT_PASS,
            "Land use district indicates low-rise exclusive residential zoning.",
            zoning or "land_use_district",
        )
    if _contains_industrial_zone(zoning_lower):
        return (
            STATUS_NOT_PASS,
            "Land use district appears industrial-only/heavy industrial.",
            zoning or "land_use_district",
        )
    if not zoning:
        return (
            STATUS_UNKNOWN,
            "Land use district is missing or unclear.",
            "land_use_district is empty.",
        )
    return (
        STATUS_PASS,
        "No prohibited zoning keyword detected.",
        zoning,
    )


def evaluate_building_type(record: dict[str, Any]) -> tuple[str, str, str]:
    type_text = flatten_value(record.get("type"))
    structure_text = flatten_value(record.get("building_structure"))
    remarks_text = flatten_value(record.get("remarks"))
    combined = " ".join([type_text, structure_text, remarks_text]).lower()

    evidence = " / ".join(text for text in [type_text, structure_text] if text)
    if _contains_apartment_keywords(combined):
        return (
            STATUS_NOT_PASS,
            "Apartment/condominium style building is high-risk for Ryokan route.",
            evidence or combined,
        )
    if _contains_detached_keywords(combined):
        return (
            STATUS_PASS,
            "Detached/machiya/old-house keywords detected.",
            evidence or combined,
        )
    return (
        STATUS_UNKNOWN,
        "Building type is not explicit enough to confirm.",
        evidence or "type/building_structure data is unclear.",
    )


def evaluate_disclaimer(record: dict[str, Any]) -> tuple[str, str, str]:
    remarks = flatten_value(record.get("remarks"))
    remarks_lower = remarks.lower()
    if _has_guesthouse_prohibition(remarks_lower):
        return (
            STATUS_NOT_PASS,
            "Remarks include guesthouse/inn prohibition wording.",
            remarks,
        )
    if not remarks:
        return (
            STATUS_UNKNOWN,
            "Remarks are missing, listing-level restrictions cannot be confirmed.",
            "remarks is empty.",
        )
    return (
        STATUS_PASS,
        "No explicit guesthouse/inn prohibition phrase detected.",
        remarks,
    )


def evaluate_floor_area(record: dict[str, Any]) -> tuple[str, str, str]:
    floor_area_raw = flatten_value(record.get("floor_area"))
    sqm = extract_floor_area_sqm(floor_area_raw)
    if sqm is None:
        return (
            STATUS_UNKNOWN,
            "Floor area could not be parsed.",
            floor_area_raw or "floor_area is empty.",
        )
    if sqm < 33:
        return (
            STATUS_NOT_PASS,
            "Floor area is below 33 sqm baseline.",
            f"{sqm:.2f} sqm",
        )
    return (
        STATUS_PASS,
        "Floor area meets 33 sqm baseline.",
        f"{sqm:.2f} sqm",
    )


def extract_floor_area_sqm(text: str) -> float | None:
    if not text:
        return None

    total_match = re.search(
        r"total[^0-9]*([0-9]+(?:\.[0-9]+)?)",
        text,
        flags=re.IGNORECASE,
    )
    if total_match:
        return float(total_match.group(1))

    sqm_matches = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*sqm", text, flags=re.IGNORECASE)
    if sqm_matches:
        values = [float(value) for value in sqm_matches]
        if len(values) == 1:
            return values[0]
        return sum(values)

    return None


def derive_blockers(checklist: list[dict[str, Any]]) -> list[dict[str, str]]:
    blockers: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for item in checklist:
        if item["status"] != STATUS_NOT_PASS:
            continue
        if not item["is_major_blocker"]:
            continue
        blocker = {
            "code": item["code"],
            "reason": item["reason"],
            "evidence": item["evidence"],
        }
        key = (blocker["code"], blocker["reason"])
        if key in seen:
            continue
        seen.add(key)
        blockers.append(blocker)

    return blockers


def derive_risk_notes(
    checklist: list[dict[str, Any]],
    blockers: list[dict[str, str]],
    model_risk_notes: list[dict[str, str]],
    model_blockers: list[dict[str, str]],
) -> list[dict[str, str]]:
    notes: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    for note in model_risk_notes:
        key = (note["code"], note["detail"])
        if key in seen:
            continue
        seen.add(key)
        notes.append(note)

    for blocker in model_blockers:
        detail = f"Potential blocker from model output: {blocker['reason']}"
        note = {"code": blocker["code"], "detail": detail}
        key = (note["code"], note["detail"])
        if key in seen:
            continue
        seen.add(key)
        notes.append(note)

    for item in checklist:
        status = item["status"]
        if status not in {STATUS_NOT_PASS, STATUS_UNKNOWN}:
            continue

        if status == STATUS_NOT_PASS:
            detail = f"Potential blocker: {item['reason']}"
        else:
            detail = f"Insufficient information: {item['reason']}"

        note = {"code": item["code"], "detail": detail}
        key = (note["code"], note["detail"])
        if key in seen:
            continue
        seen.add(key)
        notes.append(note)

    return notes


def decide_eligibility(
    checklist: list[dict[str, Any]],
    blockers: list[dict[str, str]],
) -> str:
    if blockers:
        return ELIGIBILITY_LIKELY_NOT_ELIGIBLE
    if checklist and all(item["status"] == STATUS_PASS for item in checklist):
        return ELIGIBILITY_LIKELY_ELIGIBLE
    return ELIGIBILITY_UNCERTAIN


def _contains_low_rise_zone(text: str) -> bool:
    keywords = [
        "low-rise exclusive residential",
        "category 1 low-rise",
        "first-class low-rise",
        "第1種低層",
        "1st class low-rise",
    ]
    return any(keyword in text for keyword in keywords)


def _contains_industrial_zone(text: str) -> bool:
    keywords = ["industrial-only", "heavy industrial", "industrial district"]
    return any(keyword in text for keyword in keywords)


def _contains_apartment_keywords(text: str) -> bool:
    keywords = ["apartment", "condominium", "mansion", "マンション"]
    return any(keyword in text for keyword in keywords)


def _contains_detached_keywords(text: str) -> bool:
    keywords = [
        "detached",
        "machiya",
        "kyo_machiya",
        "kyo machiya",
        "old_house",
        "old house",
        "wooden house",
    ]
    return any(keyword in text for keyword in keywords)


def _has_guesthouse_prohibition(text: str) -> bool:
    phrases = [
        "not available for guest house and inn",
        "not available for guesthouse and inn",
        "guest house and inn is not available",
        "cannot be used as guest house",
    ]
    return any(phrase in text for phrase in phrases)
