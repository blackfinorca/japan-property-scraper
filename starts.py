"""Print key statistics for a JSON array of listing records."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_JSON_PATH = Path("output/consolidated/consolidated_changes.json")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print keys and entry counts for a JSON file."
    )
    parser.add_argument(
        "json_path",
        nargs="?",
        default=str(DEFAULT_JSON_PATH),
        help="Path to JSON file (default: output/consolidated/consolidated_changes.json).",
    )
    args = parser.parse_args()

    json_path = Path(args.json_path)
    if not json_path.exists():
        raise SystemExit(f"File not found: {json_path}")

    with json_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    if not isinstance(payload, list):
        raise SystemExit("Expected a JSON array of objects.")

    total_entries = len(payload)
    key_stats: dict[str, dict[str, int]] = {}

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
