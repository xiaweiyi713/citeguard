"""Validate and freeze a corpus file into an indexed JSON artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import ensure_project_root

ensure_project_root()


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a lightweight citation index artifact.")
    parser.add_argument("--input", required=True, help="Input corpus JSON file.")
    parser.add_argument("--output", required=True, help="Output index JSON file.")
    args = parser.parse_args()

    input_path = Path(args.input)
    rows = json.loads(input_path.read_text(encoding="utf-8"))
    rows = sorted(rows, key=lambda row: row.get("citation_id", ""))
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"records": rows}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Built index with {len(rows)} records at {output_path}")


if __name__ == "__main__":
    main()
