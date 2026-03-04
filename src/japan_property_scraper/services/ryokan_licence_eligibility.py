"""Estimate Ryokan licence eligibility and write results into consolidated JSON."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from openai import OpenAI
from tqdm import tqdm

from japan_property_scraper.config import CONSOLIDATED_DIR
from japan_property_scraper.services.consolidation import (
    export_consolidated_tabular_files,
    load_consolidated_unique_records,
)
from japan_property_scraper.services.ryokan_summary import export_ryokan_summary_xls


DEFAULT_CONSOLIDATED_JSON_PATH = CONSOLIDATED_DIR / "consolidated_changes.json"
DEFAULT_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "ryokan-licence-eligibility.txt"
)
DEFAULT_MODEL = "gpt-4o-mini"

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


def update_ryokan_licence_eligibility(
    *,
    consolidated_json_path: Path = DEFAULT_CONSOLIDATED_JSON_PATH,
    prompt_path: Path = DEFAULT_PROMPT_PATH,
    model: str = DEFAULT_MODEL,
    property_numbers: Iterable[str] | None = None,
) -> UpdateSummary:
    """Update consolidated JSON with Ryokan licence eligibility assessment."""
    records = load_consolidated_unique_records(consolidated_json_path)
    target_numbers = _normalize_property_numbers(property_numbers)
    selected_indices, missing_numbers = _select_indices(records, target_numbers)

    if not selected_indices:
        export_consolidated_tabular_files(records, consolidated_json_path)
        export_ryokan_summary_xls(consolidated_json_path)
        return UpdateSummary(
            processed_records=0,
            updated_records=0,
            missing_property_numbers=missing_numbers,
        )

    prompt_text: str | None = None
    client: OpenAI | None = None

    updated_records = 0
    for index in tqdm(selected_indices, desc="Ryokan eligibility", unit="record"):
        record = records[index]
        fast_pass_evidence = _detect_already_ryokan_fast_pass(record)
        if fast_pass_evidence is not None:
            assessment = _build_already_ryokan_assessment(
                record=record,
                evidence=fast_pass_evidence,
            )
        else:
            if prompt_text is None:
                prompt_text = _load_prompt(prompt_path)
            if client is None:
                client = _build_openai_client()
            assessment = _estimate_record(
                client=client,
                model=model,
                prompt_text=prompt_text,
                record=record,
            )
        record["ryokan_licence_eligibility"] = assessment["ryokan_licence_eligibility"]
        record["ryokan_eligibility"] = assessment["ryokan_licence_eligibility"]
        record["ryokan_licence_blockers"] = assessment["ryokan_licence_blockers"]
        record["ryokan_licence_dealbreaker"] = assessment["ryokan_licence_dealbreaker"]
        record["ryokan_licence_dealbreaker_checklist"] = assessment[
            "ryokan_licence_dealbreaker_checklist"
        ]
        record["ryokan_licence_risk_notes"] = assessment["ryokan_licence_risk_notes"]
        updated_records += 1

    with consolidated_json_path.open("w", encoding="utf-8") as file:
        json.dump(records, file, ensure_ascii=False, indent=2)
    export_consolidated_tabular_files(records, consolidated_json_path)
    export_ryokan_summary_xls(consolidated_json_path)

    return UpdateSummary(
        processed_records=len(selected_indices),
        updated_records=updated_records,
        missing_property_numbers=missing_numbers,
    )


def _build_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set.")
    return OpenAI(api_key=api_key)


def _load_prompt(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def _normalize_property_numbers(
    property_numbers: Iterable[str] | None,
) -> set[str]:
    if property_numbers is None:
        return set()
    return {
        str(value).strip()
        for value in property_numbers
        if str(value).strip()
    }


def _select_indices(
    records: list[dict[str, Any]],
    target_numbers: set[str],
) -> tuple[list[int], list[str]]:
    if not target_numbers:
        return list(range(len(records))), []

    selected_indices: list[int] = []
    for index, record in enumerate(records):
        record_number = str(record.get("property_number", "")).strip()
        if record_number in target_numbers:
            selected_indices.append(index)

    found_numbers = {
        str(records[index].get("property_number", "")).strip()
        for index in selected_indices
    }
    missing_numbers = sorted(target_numbers - found_numbers)
    return selected_indices, missing_numbers


def _estimate_record(
    *,
    client: OpenAI,
    model: str,
    prompt_text: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    response = client.chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": prompt_text},
            {"role": "user", "content": _build_record_prompt(record)},
        ],
    )
    content = response.choices[0].message.content or ""
    parsed = _parse_model_output(content)

    model_checklist = _coerce_checklist(parsed.get("checklist"))
    checklist = _merge_checklists(record, model_checklist)
    model_blockers = _coerce_blockers(parsed.get("blockers"))
    blockers = _derive_blockers(checklist)
    model_risk_notes = _coerce_risk_notes(parsed.get("risk_notes"))
    risk_notes = _derive_risk_notes(
        checklist=checklist,
        blockers=blockers,
        model_risk_notes=model_risk_notes,
        model_blockers=model_blockers,
    )

    eligibility = _decide_eligibility(checklist, blockers)
    dealbreaker = blockers[0]["reason"] if blockers else None

    return {
        "ryokan_licence_eligibility": eligibility,
        "ryokan_licence_blockers": blockers,
        "ryokan_licence_dealbreaker": dealbreaker,
        "ryokan_licence_dealbreaker_checklist": checklist,
        "ryokan_licence_risk_notes": risk_notes,
    }


def _detect_already_ryokan_fast_pass(record: dict[str, Any]) -> str | None:
    current_situation_text = _flatten_value(record.get("current_situation"))
    remarks_text = _flatten_value(record.get("remarks"))
    current_situation_lower = current_situation_text.lower()
    remarks_lower = remarks_text.lower()

    operation_markers = [
        "in operation as an inn",
        "in operation as in inn",
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


def _build_already_ryokan_assessment(
    *,
    record: dict[str, Any],
    evidence: str,
) -> dict[str, Any]:
    _, area_reason, area_evidence = _evaluate_floor_area(record)
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


def _build_record_prompt(record: dict[str, Any]) -> str:
    record_json = json.dumps(record, ensure_ascii=False, indent=2)
    return (
        "Analyze this single property record and return JSON only.\n"
        "Required keys: checklist, blockers, risk_notes.\n"
        "Checklist status values must be exactly: pass, not pass, unknown.\n"
        "Include checks for ZONING, BUILDING_TYPE, LISTING_DISCLAIMER.\n\n"
        f"Property record:\n{record_json}\n"
    )


def _parse_model_output(content: str) -> dict[str, Any]:
    if not content:
        raise ValueError("OpenAI response content is empty.")

    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError(f"Model output is not valid JSON: {content!r}") from None
        payload = json.loads(content[start : end + 1])

    if not isinstance(payload, dict):
        raise ValueError("Model output must be a JSON object.")
    return payload


def _coerce_checklist(value: Any) -> list[dict[str, Any]]:
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
        code = _normalize_code(item.get("code")) or f"OTHER_{index}"
        check = _to_text(item.get("check")) or "Checklist item"
        status = _normalize_check_status(item.get("status"))
        reason = _to_text(item.get("reason") or item.get("detail")) or "No reason provided."
        evidence = _to_text(item.get("evidence"))
        is_major_blocker = _coerce_bool(item.get("is_major_blocker"))
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


def _coerce_blockers(value: Any) -> list[dict[str, str]]:
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
        code = _normalize_code(item.get("code")) or f"BLOCKER_{index}"
        reason = _to_text(item.get("reason") or item.get("detail"))
        evidence = _to_text(item.get("evidence"))
        if not reason:
            continue
        blockers.append({"code": code, "reason": reason, "evidence": evidence})
    return blockers


def _coerce_risk_notes(value: Any) -> list[dict[str, str]]:
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
        code = _normalize_code(item.get("code")) or f"RISK_{index}"
        detail = _to_text(item.get("detail") or item.get("reason"))
        if not detail:
            continue
        notes.append({"code": code, "detail": detail})
    return notes


def _merge_checklists(
    record: dict[str, Any],
    model_checklist: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    default_checklist = _build_default_checklist(record)
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


def _build_default_checklist(record: dict[str, Any]) -> list[dict[str, Any]]:
    zoning_status, zoning_reason, zoning_evidence = _evaluate_zoning(record)
    building_status, building_reason, building_evidence = _evaluate_building_type(record)
    disclaimer_status, disclaimer_reason, disclaimer_evidence = _evaluate_disclaimer(record)
    area_status, area_reason, area_evidence = _evaluate_floor_area(record)

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


def _evaluate_zoning(record: dict[str, Any]) -> tuple[str, str, str]:
    zoning = _flatten_value(record.get("land_use_district"))
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


def _evaluate_building_type(record: dict[str, Any]) -> tuple[str, str, str]:
    type_text = _flatten_value(record.get("type"))
    structure_text = _flatten_value(record.get("building_structure"))
    remarks_text = _flatten_value(record.get("remarks"))
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


def _evaluate_disclaimer(record: dict[str, Any]) -> tuple[str, str, str]:
    remarks = _flatten_value(record.get("remarks"))
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


def _evaluate_floor_area(record: dict[str, Any]) -> tuple[str, str, str]:
    floor_area_raw = _flatten_value(record.get("floor_area"))
    sqm = _extract_floor_area_sqm(floor_area_raw)
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


def _extract_floor_area_sqm(text: str) -> float | None:
    if not text:
        return None

    total_match = re.search(r"total[^0-9]*([0-9]+(?:\.[0-9]+)?)", text, flags=re.IGNORECASE)
    if total_match:
        return float(total_match.group(1))

    sqm_matches = re.findall(r"([0-9]+(?:\.[0-9]+)?)\s*sqm", text, flags=re.IGNORECASE)
    if sqm_matches:
        values = [float(value) for value in sqm_matches]
        if len(values) == 1:
            return values[0]
        return sum(values)

    return None


def _derive_blockers(checklist: list[dict[str, Any]]) -> list[dict[str, str]]:
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


def _derive_risk_notes(
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

    blocker_keys = {(blocker["code"], blocker["reason"]) for blocker in blockers}
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

        blocker_key = (item["code"], item["reason"])
        if status == STATUS_NOT_PASS and item["is_major_blocker"] and blocker_key not in blocker_keys:
            blocker_keys.add(blocker_key)

    return notes


def _decide_eligibility(
    checklist: list[dict[str, Any]],
    blockers: list[dict[str, str]],
) -> str:
    if blockers:
        return ELIGIBILITY_LIKELY_NOT_ELIGIBLE
    if checklist and all(item["status"] == STATUS_PASS for item in checklist):
        return ELIGIBILITY_LIKELY_ELIGIBLE
    return ELIGIBILITY_UNCERTAIN


def _normalize_check_status(value: Any) -> str:
    text = _to_text(value).lower()
    if text in CHECKLIST_STATUSES:
        return text
    if text in {"ok", "clear", "passed", "eligible"}:
        return STATUS_PASS
    if text in {"blocker", "fail", "failed", "not_pass", "not-pass", "ineligible"}:
        return STATUS_NOT_PASS
    return STATUS_UNKNOWN


def _normalize_code(value: Any) -> str:
    text = _to_text(value).upper()
    if not text:
        return ""
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _to_text(value).lower()
    if text in {"true", "yes", "1"}:
        return True
    if text in {"false", "no", "0"}:
        return False
    return None


def _to_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _flatten_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


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


def cli() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Estimate Ryokan licence eligibility via OpenAI and write fields into "
            "consolidated_changes.json."
        ),
    )
    parser.add_argument(
        "--json-path",
        default=str(DEFAULT_CONSOLIDATED_JSON_PATH),
        help=(
            "Path to consolidated_changes.json "
            "(default: output/consolidated/consolidated_changes.json)."
        ),
    )
    parser.add_argument(
        "--prompt-path",
        default=str(DEFAULT_PROMPT_PATH),
        help=(
            "Path to ryokan prompt "
            "(default: src/japan_property_scraper/prompts/ryokan-licence-eligibility.txt)."
        ),
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI model to use (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--property-number",
        action="append",
        dest="property_numbers",
        default=[],
        help=(
            "Property number to process. Repeat this flag to target multiple values. "
            "When omitted, all records are processed."
        ),
    )
    args = parser.parse_args()

    summary = update_ryokan_licence_eligibility(
        consolidated_json_path=Path(args.json_path),
        prompt_path=Path(args.prompt_path),
        model=args.model,
        property_numbers=args.property_numbers,
    )

    print(f"Processed records: {summary.processed_records}")
    print(f"Updated records: {summary.updated_records}")
    if summary.missing_property_numbers:
        print(
            "Property numbers not found: "
            + ", ".join(summary.missing_property_numbers),
        )


if __name__ == "__main__":
    cli()
