"""Utility helpers for consolidated_changes.json analysis."""

from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import re
from statistics import mean
from typing import Any

from bs4 import BeautifulSoup
import requests
import tiktoken


DEFAULT_JSON_PATH = Path("output/consolidated/consolidated_changes.json")
DEFAULT_PROMPT_PATH = Path(
    "src/japan_property_scraper/prompts/ryokan-licence-eligibility.txt",
)
DEFAULT_MODEL = "gpt-4o-mini"
MODEL_DOC_URL_TEMPLATE = "https://developers.openai.com/api/docs/models/{model_slug}"

CHAT_TOKENS_PER_MESSAGE = 3
CHAT_REPLY_PRIMING_TOKENS = 3

OUTPUT_FIELDS = [
    "ryokan_licence_eligibility",
    "ryokan_licence_blockers",
    "ryokan_licence_dealbreaker",
    "ryokan_licence_dealbreaker_checklist",
    "ryokan_licence_risk_notes",
]

# USD per 1M tokens (fallback map if live fetch fails)
# Source date: 2026-03-04 (from official OpenAI model pages)
FALLBACK_MODEL_PRICING_USD_PER_1M: dict[str, dict[str, float]] = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Utilities for consolidated_changes.json: key stats and Ryokan token/cost "
            "estimation."
        ),
    )
    subparsers = parser.add_subparsers(dest="command")

    stats_parser = subparsers.add_parser(
        "stats",
        help="Print key and non-empty counts for consolidated JSON records.",
    )
    stats_parser.add_argument(
        "json_path",
        nargs="?",
        default=str(DEFAULT_JSON_PATH),
        help=(
            "Path to JSON file (default: "
            "output/consolidated/consolidated_changes.json)."
        ),
    )

    estimate_parser = subparsers.add_parser(
        "estimate-cost",
        help=(
            "Estimate full-run input/output tokens and USD cost for Ryokan "
            "eligibility inference."
        ),
    )
    estimate_parser.add_argument(
        "--json-path",
        default=str(DEFAULT_JSON_PATH),
        help="Path to consolidated_changes.json.",
    )
    estimate_parser.add_argument(
        "--prompt-path",
        default=str(DEFAULT_PROMPT_PATH),
        help="Path to ryokan system prompt file.",
    )
    estimate_parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model name (default: {DEFAULT_MODEL}).",
    )
    estimate_parser.add_argument(
        "--avg-output-tokens-per-record",
        type=float,
        default=None,
        help=(
            "Manual override for average output tokens per record. "
            "If omitted, estimates from existing ryokan output fields in JSON."
        ),
    )
    estimate_parser.add_argument(
        "--fallback-output-tokens-per-record",
        type=float,
        default=220.0,
        help=(
            "Used only when output fields are missing and no manual output override "
            "is provided."
        ),
    )
    estimate_parser.add_argument(
        "--offline-pricing",
        action="store_true",
        help="Skip live pricing fetch and use built-in fallback pricing table.",
    )

    args = parser.parse_args()

    if args.command in (None, "stats"):
        _run_stats(Path(getattr(args, "json_path", DEFAULT_JSON_PATH)))
        return

    if args.command == "estimate-cost":
        _run_cost_estimate(
            json_path=Path(args.json_path),
            prompt_path=Path(args.prompt_path),
            model=args.model,
            avg_output_tokens_per_record=args.avg_output_tokens_per_record,
            fallback_output_tokens_per_record=args.fallback_output_tokens_per_record,
            offline_pricing=args.offline_pricing,
        )
        return

    raise SystemExit(f"Unknown command: {args.command}")


def _run_stats(json_path: Path) -> None:
    payload = _load_json_array(json_path)
    total_entries = len(payload)
    key_stats: dict[str, dict[str, int]] = {}
    eligibility_summary = _build_eligibility_summary(payload)

    for entry in payload:
        if not isinstance(entry, dict):
            continue
        for key, value in entry.items():
            stats = key_stats.setdefault(key, {"present": 0, "non_empty": 0})
            stats["present"] += 1
            if not _is_empty(value):
                stats["non_empty"] += 1

    print(f"File: {json_path}")
    print(f"Total entries: {total_entries}")
    print()
    print("Key | Present In Entries | Non-Empty Entries")
    print("-" * 58)
    for key in sorted(key_stats):
        stats = key_stats[key]
        print(f"{key} | {stats['present']} | {stats['non_empty']}")

    print()
    print("Ryokan Eligibility Summary")
    print("-" * 58)
    for label, count in eligibility_summary.items():
        print(f"{label} | {count}")


def _run_cost_estimate(
    *,
    json_path: Path,
    prompt_path: Path,
    model: str,
    avg_output_tokens_per_record: float | None,
    fallback_output_tokens_per_record: float,
    offline_pricing: bool,
) -> None:
    records = _load_json_array(json_path)
    prompt_text = _load_text(prompt_path)
    encoder = _get_encoder(model)
    input_total_tokens, input_per_record_avg = _estimate_input_tokens(
        records=records,
        prompt_text=prompt_text,
        encoder=encoder,
    )

    (
        output_total_tokens,
        output_per_record_avg,
        output_source,
    ) = _estimate_output_tokens(
        records=records,
        encoder=encoder,
        avg_output_tokens_per_record=avg_output_tokens_per_record,
        fallback_output_tokens_per_record=fallback_output_tokens_per_record,
    )

    pricing = _get_model_pricing(model=model, offline_pricing=offline_pricing)
    input_cost = (input_total_tokens / 1_000_000) * pricing["input_per_1m_usd"]
    output_cost = (output_total_tokens / 1_000_000) * pricing["output_per_1m_usd"]
    total_cost = input_cost + output_cost

    print(f"Model: {model}")
    print(f"Records (full run): {len(records)}")
    print(f"Pricing source: {pricing['source']}")
    print(
        "Rates (USD per 1M tokens): "
        f"input={pricing['input_per_1m_usd']:.4f}, "
        f"output={pricing['output_per_1m_usd']:.4f}",
    )
    print()
    print("Token estimate:")
    print(
        f"- Input tokens total: {input_total_tokens:,} "
        f"(avg/record: {input_per_record_avg:.2f})",
    )
    print(
        f"- Output tokens total: {output_total_tokens:,} "
        f"(avg/record: {output_per_record_avg:.2f}; source: {output_source})",
    )
    print(
        f"- Total tokens: {input_total_tokens + output_total_tokens:,}",
    )
    print()
    print("Estimated cost (USD):")
    print(f"- Input cost: ${input_cost:.6f}")
    print(f"- Output cost: ${output_cost:.6f}")
    print(f"- Total cost: ${total_cost:.6f}")


def _estimate_input_tokens(
    *,
    records: list[dict[str, Any]],
    prompt_text: str,
    encoder: tiktoken.Encoding,
) -> tuple[int, float]:
    prompt_tokens = len(encoder.encode(prompt_text))
    per_record: list[int] = []
    for record in records:
        user_prompt = _build_ryokan_user_prompt(record)
        user_tokens = len(encoder.encode(user_prompt))
        total = (
            prompt_tokens
            + user_tokens
            + (CHAT_TOKENS_PER_MESSAGE * 2)
            + CHAT_REPLY_PRIMING_TOKENS
        )
        per_record.append(total)

    total_tokens = sum(per_record)
    avg_tokens = mean(per_record) if per_record else 0.0
    return total_tokens, avg_tokens


def _estimate_output_tokens(
    *,
    records: list[dict[str, Any]],
    encoder: tiktoken.Encoding,
    avg_output_tokens_per_record: float | None,
    fallback_output_tokens_per_record: float,
) -> tuple[int, float, str]:
    if avg_output_tokens_per_record is not None:
        total = int(round(avg_output_tokens_per_record * len(records)))
        return total, avg_output_tokens_per_record, "manual override"

    samples: list[int] = []
    for record in records:
        payload = {field: record.get(field) for field in OUTPUT_FIELDS}
        if not _has_any_non_empty(payload):
            continue
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        samples.append(len(encoder.encode(raw)))

    if samples:
        average = mean(samples)
        total = int(round(average * len(records)))
        return total, average, "existing ryokan output fields"

    total = int(round(fallback_output_tokens_per_record * len(records)))
    return total, fallback_output_tokens_per_record, "fallback default"


def _build_eligibility_summary(
    records: list[dict[str, Any]],
) -> dict[str, int]:
    canonical_order = [
        "ALREADY A RYOKAN",
        "LIKELY ELIGIBLE",
        "LIKELY NOT ELIGIBLE",
        "UNCERTAIN",
    ]
    summary: dict[str, int] = {label: 0 for label in canonical_order}
    summary["MISSING_OR_EMPTY"] = 0
    summary["OTHER"] = 0

    for record in records:
        value = record.get("ryokan_licence_eligibility")
        if _is_empty(value):
            summary["MISSING_OR_EMPTY"] += 1
            continue

        normalized = str(value).strip().upper()
        if normalized in summary:
            summary[normalized] += 1
        else:
            summary["OTHER"] += 1

    return summary


def _get_model_pricing(model: str, offline_pricing: bool) -> dict[str, Any]:
    if not offline_pricing:
        live = _fetch_live_model_pricing(model)
        if live is not None:
            return live

    fallback = FALLBACK_MODEL_PRICING_USD_PER_1M.get(model)
    if fallback is None:
        known = ", ".join(sorted(FALLBACK_MODEL_PRICING_USD_PER_1M))
        raise SystemExit(
            "Unable to fetch live pricing and model is not in fallback table. "
            f"Model: {model}. Known fallback models: {known}",
        )
    return {
        "input_per_1m_usd": fallback["input"],
        "output_per_1m_usd": fallback["output"],
        "source": (
            "fallback table (official OpenAI model page rates captured on "
            f"{date(2026, 3, 4).isoformat()})"
        ),
    }


def _fetch_live_model_pricing(model: str) -> dict[str, Any] | None:
    model_slug = _normalize_model_slug(model)
    url = MODEL_DOC_URL_TEMPLATE.format(model_slug=model_slug)
    try:
        response = requests.get(url, timeout=20)
        response.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    lines = [line.strip() for line in soup.stripped_strings if line.strip()]
    input_price = _extract_price_for_label(lines=lines, label="Input")
    output_price = _extract_price_for_label(lines=lines, label="Output")
    if input_price is None or output_price is None:
        return None

    return {
        "input_per_1m_usd": input_price,
        "output_per_1m_usd": output_price,
        "source": f"live model page: {url}",
    }


def _extract_price_for_label(lines: list[str], label: str) -> float | None:
    # Prefer the "Text tokens" section when present.
    section_starts = [
        index for index, value in enumerate(lines) if value.lower() == "text tokens"
    ]
    for start_index in section_starts:
        end_index = min(start_index + 120, len(lines))
        section_value = _extract_price_in_slice(lines, label, start_index, end_index)
        if section_value is not None:
            return section_value

    # Fallback: search entire page.
    return _extract_price_in_slice(lines, label, 0, len(lines))


def _extract_price_in_slice(
    lines: list[str],
    label: str,
    start_index: int,
    end_index: int,
) -> float | None:
    for index in range(start_index, end_index):
        if lines[index] != label:
            continue
        for next_index in range(index + 1, min(index + 10, end_index)):
            value = _parse_usd_price(lines[next_index])
            if value is not None:
                return value
    return None


def _parse_usd_price(text: str) -> float | None:
    compact = text.replace(",", "").strip()
    match = re.fullmatch(r"\$([0-9]+(?:\.[0-9]+)?)", compact)
    if not match:
        return None
    return float(match.group(1))


def _normalize_model_slug(model: str) -> str:
    base = model.split("@")[0]
    date_suffix = re.fullmatch(r"(.+)-20\d{2}-\d{2}-\d{2}", base)
    if date_suffix:
        return date_suffix.group(1)
    return base


def _get_encoder(model: str) -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(model)
    except KeyError:
        return tiktoken.get_encoding("o200k_base")


def _build_ryokan_user_prompt(record: dict[str, Any]) -> str:
    record_json = json.dumps(record, ensure_ascii=False, indent=2)
    return (
        "Analyze this single property record and return JSON only.\n"
        "Required keys: checklist, blockers, risk_notes.\n"
        "Checklist status values must be exactly: pass, not pass, unknown.\n"
        "Include checks for ZONING, BUILDING_TYPE, LISTING_DISCLAIMER.\n\n"
        f"Property record:\n{record_json}\n"
    )


def _load_json_array(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise SystemExit(f"File not found: {path}")
    with path.open("r", encoding="utf-8") as file:
        payload = json.load(file)
    if not isinstance(payload, list):
        raise SystemExit(f"Expected a JSON array in: {path}")
    return payload


def _load_text(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"File not found: {path}")
    return path.read_text(encoding="utf-8")


def _has_any_non_empty(payload: dict[str, Any]) -> bool:
    return any(not _is_empty(value) for value in payload.values())


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if value == "":
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    return False


if __name__ == "__main__":
    main()
