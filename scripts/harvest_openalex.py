"""Fetch paper metadata from OpenAlex without third-party dependencies."""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

from _bootstrap import ensure_project_root

ensure_project_root()


def fetch_openalex(query: str, per_page: int = 10) -> dict:
    params = urllib.parse.urlencode({"search": query, "per-page": per_page})
    url = f"https://api.openalex.org/works?{params}"
    with urllib.request.urlopen(url) as response:  # nosec B310 - trusted public API endpoint
        return json.load(response)


def main() -> None:
    parser = argparse.ArgumentParser(description="Harvest OpenAlex metadata for a query.")
    parser.add_argument("--query", required=True, help="Topic or keyword query.")
    parser.add_argument("--output", required=True, help="Output JSON path.")
    parser.add_argument("--per-page", type=int, default=10, help="Number of results to request.")
    args = parser.parse_args()

    payload = fetch_openalex(args.query, per_page=args.per_page)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved OpenAlex response to {output_path}")


if __name__ == "__main__":
    main()
