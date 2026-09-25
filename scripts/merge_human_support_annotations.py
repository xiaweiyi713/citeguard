#!/usr/bin/env python3
"""Merge completed blinded support packets into an unlabeled candidate catalog."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.benchmark.human_candidates import (
    HumanSupportCandidateError,
    merge_candidate_annotation_packets,
    validate_candidate_dataset,
)


def _load_packet(path: str) -> Dict[str, Any]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise HumanSupportCandidateError(f"could not read {path}: {exc}") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise HumanSupportCandidateError(
            f"{path} must be a complete JSON packet; JSONL cannot preserve the blinded packet integrity contract"
        ) from exc
    if isinstance(payload, dict):
        return payload
    raise HumanSupportCandidateError(f"{path} must contain a complete packet JSON object")


def _write_json(path: str, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Merge intact blinded packet labels without inventing gold or hiding disagreement.")
    parser.add_argument("--candidates", required=True, help="Unlabeled candidate dataset.")
    parser.add_argument("--packet", action="append", required=True, help="Completed intact JSON packet; repeat per annotator.")
    parser.add_argument("--output", required=True, help="Updated candidate dataset output path.")
    parser.add_argument("--report", help="Optional merge report output path.")
    args = parser.parse_args(argv)
    try:
        dataset = json.loads(Path(args.candidates).read_text(encoding="utf-8"))
        if not isinstance(dataset, dict):
            raise HumanSupportCandidateError("candidate dataset must be a JSON object")
        validate_candidate_dataset(dataset)
        packets = [_load_packet(path) for path in args.packet]
        merged, report = merge_candidate_annotation_packets(dataset, packets)
        merged = deepcopy(merged)
        history = merged.setdefault("annotation_merge_history", [])
        if not isinstance(history, list):
            history = []
            merged["annotation_merge_history"] = history
        history.append({"packet_paths": list(args.packet), "report": report})
        _write_json(args.output, merged)
        if args.report:
            _write_json(args.report, report)
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["ok"] else 1
    except (OSError, json.JSONDecodeError, HumanSupportCandidateError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
