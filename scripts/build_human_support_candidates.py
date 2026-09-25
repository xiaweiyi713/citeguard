#!/usr/bin/env python3
"""Build an unlabeled real-source support catalog and blinded packet."""

from __future__ import annotations

import argparse
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
    build_blinded_candidate_packet,
    build_human_support_candidate_dataset,
    validate_blinded_candidate_packet,
    validate_candidate_dataset,
)


def _load_json(path: str) -> Dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise HumanSupportCandidateError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HumanSupportCandidateError(f"invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise HumanSupportCandidateError(f"{path} must contain a JSON object")
    return payload


def _write_json(path: str, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _instructions(packet: Dict[str, Any]) -> str:
    labels = ", ".join(f"`{label}`" for label in packet["label_options"])
    return "\n".join(
        [
            "# CiteGuard Real-Source Support Annotation",
            "",
            f"- Packet id: `{packet['packet_id']}`",
            f"- Packet digest: `{packet['packet_digest']}`",
            f"- Candidate digest: `{packet['candidate_digest']}`",
            f"- Cases: `{packet['case_count']}`",
            f"- Review phase: `{packet['review_phase']}`",
            "",
            "Use only the claim and the supplied lawful evidence. Label each row independently before discussion.",
            "The candidate catalog is maintainer-only; do not inspect it while labeling.",
            "",
            f"Allowed labels: {labels}.",
            "",
            "- `supported`: the evidence directly entails the claim.",
            "- `weakly_supported`: the evidence is relevant but narrower or weaker than the claim.",
            "- `insufficient_evidence`: the supplied scope does not establish the claim.",
            "- `contradicted`: the evidence directly conflicts with the claim.",
            "",
            "Fill only `annotation.annotator_id`, `annotation.annotator_label`, `annotation.rationale`, and optional annotation notes.",
            "Keep packet ids, digests, case ids, evidence, and locators unchanged. Do not add or infer a gold label.",
            "Use `insufficient_evidence` when a claim needs unavailable full text; never treat a source outage as contradiction.",
            "",
        ]
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build real-source human support candidates and a blinded packet.")
    parser.add_argument("--candidates", help="Existing candidate dataset; rebuild only its blinded packet.")
    parser.add_argument("--retrieval-dataset", default="data/eval/live_retrieval_benchmark.json")
    parser.add_argument("--claims", help="JSON claim manifest with a claims list.")
    parser.add_argument("--output", help="Unlabeled candidate dataset output path; required with --claims.")
    parser.add_argument("--packet-output", required=True, help="Blinded annotation packet output path.")
    parser.add_argument("--instructions-output", help="Optional Markdown instructions output path.")
    parser.add_argument("--review-phase", default="first_review")
    parser.add_argument("--packet-purpose", default="independent support annotation")
    parser.add_argument("--collected-at", default="")
    parser.add_argument("--case-id", action="append", default=[], help="Only include selected candidate ids.")
    args = parser.parse_args(argv)

    try:
        if args.candidates:
            if args.claims or args.output or args.collected_at:
                raise HumanSupportCandidateError("--candidates cannot be combined with --claims, --output, or --collected-at")
            dataset = _load_json(args.candidates)
        else:
            if not args.claims or not args.output:
                raise HumanSupportCandidateError("--claims and --output are required unless --candidates is supplied")
            retrieval = _load_json(args.retrieval_dataset)
            claims = _load_json(args.claims)
            dataset = build_human_support_candidate_dataset(
                retrieval,
                claims,
                collected_at=args.collected_at or None,
            )
            if args.case_id:
                selected = set(args.case_id)
                dataset["cases"] = [row for row in dataset["cases"] if row["id"] in selected]
                dataset["collection"]["case_count"] = len(dataset["cases"])
        validate_candidate_dataset(dataset)
        packet = build_blinded_candidate_packet(
            dataset,
            review_phase=args.review_phase,
            packet_purpose=args.packet_purpose,
            case_ids=args.case_id if args.candidates else None,
        )
        validate_blinded_candidate_packet(dataset, packet)
        if args.output:
            _write_json(args.output, dataset)
        _write_json(args.packet_output, packet)
        if args.instructions_output:
            Path(args.instructions_output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.instructions_output).write_text(_instructions(packet), encoding="utf-8")
        print(
            json.dumps(
                {
                    "ok": True,
                    "candidate_dataset": args.candidates or args.output,
                    "packet": args.packet_output,
                    "packet_id": packet["packet_id"],
                    "packet_digest": packet["packet_digest"],
                    "candidate_digest": packet["candidate_digest"],
                    "case_count": packet["case_count"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (HumanSupportCandidateError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
