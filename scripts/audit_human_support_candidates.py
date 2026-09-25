#!/usr/bin/env python3
"""Audit the gold-free real-source support candidate staging artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, List, Optional

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.benchmark.human_candidates import (
    HumanSupportCandidateError,
    validate_blinded_candidate_packet,
    validate_candidate_dataset,
)


def _load(path: str) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise HumanSupportCandidateError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HumanSupportCandidateError(f"invalid JSON in {path}: {exc.msg}") from exc


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Check candidate provenance and blinded packet integrity.")
    parser.add_argument("--candidates", default="data/eval/human_support_candidates.json")
    parser.add_argument("--packet", default="experiments/human-support-pilot-packet.json")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when the packet is missing or invalid.")
    args = parser.parse_args(argv)
    try:
        candidates = _load(args.candidates)
        if not isinstance(candidates, dict):
            raise HumanSupportCandidateError("candidate dataset must be a JSON object")
        candidate_summary = validate_candidate_dataset(candidates)
        packet_path = Path(args.packet)
        if packet_path.exists():
            packet = _load(args.packet)
            if not isinstance(packet, dict):
                raise HumanSupportCandidateError("packet must be a JSON object; use JSON rather than JSONL for integrity audit")
            packet_summary = validate_blinded_candidate_packet(candidates, packet)
            packet_status = "valid"
        else:
            packet_summary = None
            packet_status = "missing"
        report = {
            "ok": packet_status == "valid",
            "status": packet_status,
            "candidate_dataset": candidate_summary,
            "packet": packet_summary,
            "policy": {
                "gold_labels_forbidden": True,
                "blinded_packet_required_for_strict_mode": True,
                "lawful_evidence_only": True,
            },
            "next_action": "assign_packet_to_two_independent_reviewers" if packet_status == "valid" else "build_or_repair_blinded_packet",
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if report["ok"] or not args.strict else 1
    except (HumanSupportCandidateError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
