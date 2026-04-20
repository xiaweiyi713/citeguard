"""Build a local citation corpus from JSONL metadata."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List

from _bootstrap import ensure_project_root

ensure_project_root()


REQUIRED_KEYS = {"citation_id", "title"}


def load_jsonl(path: Path) -> List[dict]:
    records: List[dict] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            missing = REQUIRED_KEYS - row.keys()
            if missing:
                raise ValueError(f"Line {line_number} is missing required keys: {sorted(missing)}")
            records.append(row)
    return records


def write_json(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(list(rows), handle, ensure_ascii=False, indent=2)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a normalized local citation corpus.")
    parser.add_argument("--input", required=True, help="Input JSONL metadata file.")
    parser.add_argument("--output", required=True, help="Output JSON file.")
    args = parser.parse_args()

    rows = load_jsonl(Path(args.input))
    write_json(Path(args.output), rows)
    print(f"Wrote {len(rows)} records to {args.output}")


if __name__ == "__main__":
    main()
