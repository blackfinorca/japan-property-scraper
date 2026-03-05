"""OpenAI transport helpers for Ryokan eligibility inference."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from openai import APIError, OpenAI, RateLimitError

LOGGER = logging.getLogger(__name__)
_MAX_RETRIES = 4


def build_openai_client() -> OpenAI:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY environment variable is not set.")
    return OpenAI(api_key=api_key)


def load_prompt(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def request_model_json(
    *,
    client: OpenAI,
    model: str,
    prompt_text: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": prompt_text},
                    {"role": "user", "content": build_record_prompt(record)},
                ],
            )
            content = response.choices[0].message.content or ""
            return parse_model_output(content)
        except RateLimitError as error:
            if attempt >= _MAX_RETRIES:
                raise
            wait = 2**attempt  # 2, 4, 8 seconds
            LOGGER.warning("OpenAI rate limit (attempt %d/%d); retrying in %ds.", attempt, _MAX_RETRIES, wait)
            time.sleep(wait)
        except APIError as error:
            if attempt >= _MAX_RETRIES:
                raise
            wait = 2 ** (attempt - 1)  # 1, 2, 4 seconds
            LOGGER.warning("OpenAI API error (attempt %d/%d): %s; retrying in %ds.", attempt, _MAX_RETRIES, error, wait)
            time.sleep(wait)
    raise RuntimeError("Unreachable: OpenAI retry loop exhausted without returning or raising.")


def build_record_prompt(record: dict[str, Any]) -> str:
    record_json = json.dumps(record, ensure_ascii=False, indent=2)
    return (
        "Analyze this single property record and return JSON only.\n"
        "Required keys: checklist, blockers, risk_notes.\n"
        "Checklist status values must be exactly: pass, not pass, unknown.\n"
        "Include checks for ZONING, BUILDING_TYPE, LISTING_DISCLAIMER.\n\n"
        f"Property record:\n{record_json}\n"
    )


def parse_model_output(content: str) -> dict[str, Any]:
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
