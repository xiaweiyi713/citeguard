#!/usr/bin/env python3
"""Report whether the real-source retrieval collection is ready for observation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.benchmark.live_retrieval import (
    LiveRetrievalBenchmarkError,
    audit_live_retrieval_collection,
)


def _load_json(path: str) -> Dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise LiveRetrievalBenchmarkError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LiveRetrievalBenchmarkError(f"invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise LiveRetrievalBenchmarkError(f"{path} must contain a JSON object")
    return payload


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit CiteGuard's real-source retrieval benchmark collection.")
    parser.add_argument("--dataset", default="data/eval/live_retrieval_benchmark.json")
    parser.add_argument("--campaign", default="data/eval/live_retrieval_benchmark_campaign.json")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero until collection quotas are ready.")
    args = parser.parse_args(argv)
    try:
        report = audit_live_retrieval_collection(_load_json(args.dataset), _load_json(args.campaign))
    except LiveRetrievalBenchmarkError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ready" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
