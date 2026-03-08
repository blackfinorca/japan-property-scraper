"""Analyze latest vs previous scrape history changes via OpenAI and print a table."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

from openai import APIError, OpenAI, RateLimitError


PROJECT_ROOT = Path(__file__).resolve().parent
RAW_DIR = PROJECT_ROOT / "output" / "raw"
DEFAULT_PROMPT_PATH = PROJECT_ROOT / "src" / "japan_property_scraper" / "prompts" / "history-analysis.txt"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "output" / "consolidated" / "history_analysis_changes.json"
DEFAULT_MODEL = "gpt-4o-mini"
MAX_RETRIES = 4


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    latest_path, previous_path = resolve_input_files(
        raw_dir=Path(args.raw_dir),
        site_prefix=args.site_prefix,
        latest_file=Path(args.latest_file) if args.latest_file else None,
        previous_file=Path(args.previous_file) if args.previous_file else None,
    )

    latest_records = load_json_array(latest_path)
    previous_records = load_json_array(previous_path)
    latest_reduced = reduce_records(latest_records)
    previous_reduced = reduce_records(previous_records)

    prompt_template = Path(args.prompt_path).read_text(encoding="utf-8")
    prompt_text = (
        prompt_template
        .replace("{{latest_scrape_json}}", json.dumps(latest_reduced, ensure_ascii=False))
        .replace("{{previous_scrape_json}}", json.dumps(previous_reduced, ensure_ascii=False))
    )

    client = build_client()
    payload = request_json(
        client=client,
        model=args.model,
        prompt_text=prompt_text,
    )
    payload = normalize_output_payload(payload)

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Latest file:   {latest_path}")
    print(f"Previous file: {previous_path}")
    print(f"Output JSON:   {output_path}")
    print()
    print_table(payload)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare latest and previous raw scrape files via OpenAI and "
            "output per-property changes."
        ),
    )
    parser.add_argument(
        "--raw-dir",
        default=str(RAW_DIR),
        help=f"Directory with timestamped raw JSON files (default: {RAW_DIR}).",
    )
    parser.add_argument(
        "--site-prefix",
        default="hachise",
        help="File prefix used in raw files (default: hachise).",
    )
    parser.add_argument(
        "--latest-file",
        default=None,
        help="Explicit latest scrape JSON file path.",
    )
    parser.add_argument(
        "--previous-file",
        default=None,
        help="Explicit previous scrape JSON file path.",
    )
    parser.add_argument(
        "--prompt-path",
        default=str(DEFAULT_PROMPT_PATH),
        help=f"Prompt template path (default: {DEFAULT_PROMPT_PATH}).",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"OpenAI model (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--output-path",
        default=str(DEFAULT_OUTPUT_PATH),
        help=f"Output JSON path (default: {DEFAULT_OUTPUT_PATH}).",
    )
    return parser.parse_args(argv)


def resolve_input_files(
    *,
    raw_dir: Path,
    site_prefix: str,
    latest_file: Path | None,
    previous_file: Path | None,
) -> tuple[Path, Path]:
    if latest_file and previous_file:
        return latest_file, previous_file

    pattern = f"{site_prefix}_*.json"
    candidates = sorted(raw_dir.glob(pattern))
    if len(candidates) < 2:
        raise RuntimeError(f"Need at least 2 raw JSON files in {raw_dir} matching {pattern}.")

    latest = candidates[-1]
    previous = candidates[-2]
    if latest_file:
        latest = latest_file
    if previous_file:
        previous = previous_file
    return latest, previous


def load_json_array(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected JSON array in {path}")
    return [item for item in payload if isinstance(item, dict)]


def reduce_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reduced: list[dict[str, Any]] = []
    for record in records:
        property_number = to_text(record.get("property_number"))
        if not property_number:
            continue
        reduced.append(
            {
                "property_number": property_number,
                "price_jpy": to_number(record.get("price_jpy")),
                "price_usd": to_number(record.get("price_usd")),
                "information_updated": to_text_or_none(record.get("information_updated")),
                "status": to_text_or_none(record.get("status")),
            },
        )
    reduced.sort(key=lambda item: item["property_number"])
    return reduced


def to_text(value: Any) -> str:
    if value in (None, []):
        return ""
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def to_text_or_none(value: Any) -> str | None:
    text = to_text(value)
    return text or None


def to_number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    text = to_text(value)
    if not text:
        return None
    cleaned = text.replace(",", "")
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    token = match.group(0)
    if "." in token:
        try:
            return float(token)
        except ValueError:
            return None
    try:
        return int(token)
    except ValueError:
        return None


def build_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set.")
    return OpenAI(api_key=api_key)


def request_json(*, client: OpenAI, model: str, prompt_text: str) -> dict[str, Any]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": "Return JSON only. Follow the prompt exactly.",
                    },
                    {"role": "user", "content": prompt_text},
                ],
            )
            content = response.choices[0].message.content or ""
            return parse_json_response(content)
        except RateLimitError:
            if attempt >= MAX_RETRIES:
                raise
            time.sleep(2**attempt)
        except APIError:
            if attempt >= MAX_RETRIES:
                raise
            time.sleep(2 ** (attempt - 1))

    raise RuntimeError("Unreachable: OpenAI retry loop exhausted.")


def parse_json_response(content: str) -> dict[str, Any]:
    if not content:
        raise ValueError("OpenAI returned empty content.")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("OpenAI output is not valid JSON.") from None
        payload = json.loads(content[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("OpenAI output must be a JSON object.")
    return payload


def normalize_output_payload(payload: dict[str, Any]) -> dict[str, Any]:
    changes = payload.get("changes")
    if not isinstance(changes, list):
        return {"changes": []}

    normalized_changes: list[dict[str, Any]] = []
    for item in changes:
        if not isinstance(item, dict):
            continue
        property_number = to_text(item.get("property_number"))
        if not property_number:
            continue
        fields = item.get("changed_fields")
        if not isinstance(fields, list):
            continue
        normalized_fields: list[dict[str, Any]] = []
        for field in fields:
            if not isinstance(field, dict):
                continue
            key = to_text(field.get("key"))
            if key not in {"price_jpy", "price_usd", "information_updated", "status"}:
                continue
            normalized_fields.append(
                {
                    "key": key,
                    "previous": field.get("previous"),
                    "latest": field.get("latest"),
                },
            )
        if normalized_fields:
            normalized_changes.append(
                {
                    "property_number": property_number,
                    "changed_fields": normalized_fields,
                },
            )

    normalized_changes.sort(key=lambda item: item["property_number"])
    return {"changes": normalized_changes}


def print_table(payload: dict[str, Any]) -> None:
    rows: list[list[str]] = []
    for item in payload.get("changes", []):
        property_number = to_text(item.get("property_number"))
        for field in item.get("changed_fields", []):
            rows.append(
                [
                    property_number,
                    to_text(field.get("key")),
                    format_cell(field.get("previous")),
                    format_cell(field.get("latest")),
                ],
            )

    if not rows:
        print("No changes found.")
        return

    headers = ["property_number", "field", "previous", "latest"]
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, value in enumerate(row):
            widths[idx] = max(widths[idx], len(value))

    def line(char: str = "-") -> str:
        return "+" + "+".join(char * (width + 2) for width in widths) + "+"

    print(line("-"))
    print(
        "| "
        + " | ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers)))
        + " |",
    )
    print(line("="))
    for row in rows:
        print(
            "| " + " | ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))) + " |",
        )
    print(line("-"))
    print(f"Total changed fields: {len(rows)}")
    print(f"Total changed properties: {len(payload.get('changes', []))}")


def format_cell(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, (int, float)):
        return f"{value:,}"
    text = to_text(value)
    return text if text else "null"


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # pragma: no cover
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
