"""Estimate Ryokan licence eligibility and write results into consolidated JSON."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable

from openai import OpenAI
from tqdm import tqdm

from japan_property_scraper.config import CONSOLIDATED_DIR
from japan_property_scraper.services.consolidation import (
    export_consolidated_tabular_files,
    load_consolidated_unique_records,
    write_json_atomic,
)
from japan_property_scraper.services.eligibility_models import (
    UpdateSummary,
    coerce_blockers,
    coerce_checklist,
    coerce_risk_notes,
)
from japan_property_scraper.services.eligibility_openai import (
    build_openai_client,
    load_prompt,
    request_model_json,
)
from japan_property_scraper.services.eligibility_rules import (
    build_already_ryokan_assessment,
    build_assessment_from_model,
    detect_already_ryokan_fast_pass,
)
from japan_property_scraper.services.ryokan_summary import export_ryokan_summary_xls


DEFAULT_CONSOLIDATED_JSON_PATH = CONSOLIDATED_DIR / "consolidated_changes.json"
DEFAULT_PROMPT_PATH = (
    Path(__file__).resolve().parents[1]
    / "prompts"
    / "ryokan-licence-eligibility.txt"
)
DEFAULT_MODEL = "gpt-4o-mini"


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
    _CHECKPOINT_EVERY = 10

    for index in tqdm(selected_indices, desc="Ryokan eligibility", unit="record"):
        record = records[index]
        fast_pass_evidence = detect_already_ryokan_fast_pass(record)
        if fast_pass_evidence is not None:
            assessment = build_already_ryokan_assessment(
                record=record,
                evidence=fast_pass_evidence,
            )
        else:
            if prompt_text is None:
                prompt_text = load_prompt(prompt_path)
            if client is None:
                client = build_openai_client()
            assessment = _build_model_assessment(
                client=client,
                model=model,
                prompt_text=prompt_text,
                record=record,
            )

        record["ryokan_licence_eligibility"] = assessment["ryokan_licence_eligibility"]
        record["ryokan_licence_blockers"] = assessment["ryokan_licence_blockers"]
        record["ryokan_licence_dealbreaker"] = assessment["ryokan_licence_dealbreaker"]
        record["ryokan_licence_dealbreaker_checklist"] = assessment[
            "ryokan_licence_dealbreaker_checklist"
        ]
        record["ryokan_licence_risk_notes"] = assessment["ryokan_licence_risk_notes"]
        updated_records += 1

        if updated_records % _CHECKPOINT_EVERY == 0:
            write_json_atomic(consolidated_json_path, records)

    write_json_atomic(consolidated_json_path, records)
    export_consolidated_tabular_files(records, consolidated_json_path)
    export_ryokan_summary_xls(consolidated_json_path)

    return UpdateSummary(
        processed_records=len(selected_indices),
        updated_records=updated_records,
        missing_property_numbers=missing_numbers,
    )


def _build_model_assessment(
    *,
    client: OpenAI,
    model: str,
    prompt_text: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    parsed = request_model_json(
        client=client,
        model=model,
        prompt_text=prompt_text,
        record=record,
    )

    model_checklist = coerce_checklist(parsed.get("checklist"))
    model_blockers = coerce_blockers(parsed.get("blockers"))
    model_risk_notes = coerce_risk_notes(parsed.get("risk_notes"))

    return build_assessment_from_model(
        record=record,
        model_checklist=model_checklist,
        model_blockers=model_blockers,
        model_risk_notes=model_risk_notes,
    )


def _normalize_property_numbers(
    property_numbers: Iterable[str] | None,
) -> set[str]:
    if property_numbers is None:
        return set()
    return {str(value).strip() for value in property_numbers if str(value).strip()}


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
        print("Property numbers not found: " + ", ".join(summary.missing_property_numbers))


if __name__ == "__main__":
    cli()
