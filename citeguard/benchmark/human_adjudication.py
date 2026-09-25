"""Content-bound third-party adjudication for real-source support candidates."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any, Dict, Mapping, Sequence

from citeguard.benchmark.human_candidates import (
    HumanSupportCandidateError,
    _blinded_case_id,
    build_blinded_candidate_packet,
    merge_candidate_annotation_packets,
    validate_candidate_dataset,
)
from citeguard.verification.support_eval import ALLOWED_SUPPORT_LABELS


ADJUDICATION_SCHEMA_VERSION = 1
ADJUDICATION_PACKET_TYPE = "human_support_candidate_adjudication"
DECISION_FIELDS = {"adjudicator_id", "adjudicated_label", "rationale"}


def build_candidate_adjudication_packet(
    candidates: Mapping[str, Any],
    packets: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Prepare a blinded disagreement-only packet from intact reviewer returns."""

    validate_candidate_dataset(candidates)
    if any(row.get("annotations") or row.get("annotation_status") != "not_human_reviewed" for row in candidates["cases"]):
        raise HumanSupportCandidateError("adjudication requires the original unlabeled candidate catalog")
    merged, report = merge_candidate_annotation_packets(candidates, packets)
    if report["skipped_count"]:
        raise HumanSupportCandidateError("one or more reviewer packet rows were rejected")
    case_rows = []
    for row in merged["cases"]:
        annotations = row["annotations"]
        if row["annotation_status"] != "dual_annotator_disagreement":
            continue
        if len(annotations) != 2 or len({item["annotator_id"] for item in annotations}) != 2:
            raise HumanSupportCandidateError(f"case {row['id']} needs exactly two distinct original annotators")
        if any(not str(item.get("rationale", "")).strip() for item in annotations):
            raise HumanSupportCandidateError(f"case {row['id']} needs both original rationales")
        case_rows.append({
            "case_id": _blinded_case_id(candidates, row),
            "claim": row["claim"],
            "evidence": row["evidence"],
            "evidence_scope": row["evidence_scope"],
            "evidence_locator": row["evidence_locator"],
            "source_locator": row["source_locator"],
            "lang": row["lang"],
            "annotations": [
                {
                    key: annotation[key]
                    for key in (
                        "annotator_id", "annotator_label", "rationale", "packet_id",
                        "packet_digest", "completed_packet_digest",
                    )
                }
                for annotation in sorted(annotations, key=lambda item: item["annotator_id"])
            ],
            "decision": _empty_decision(),
        })
    if not case_rows:
        raise HumanSupportCandidateError("there are no exactly dual-annotated disagreements to adjudicate")
    case_rows.sort(key=lambda item: item["case_id"])
    packet = {
        "schema_version": ADJUDICATION_SCHEMA_VERSION,
        "packet_type": ADJUDICATION_PACKET_TYPE,
        "candidate_campaign_id": candidates["campaign_id"],
        "candidate_digest": build_blinded_candidate_packet(candidates)["candidate_digest"],
        "case_count": len(case_rows),
        "cases": case_rows,
    }
    packet["packet_digest"] = _digest(_without_decisions(packet))
    return packet


def validate_candidate_adjudication_packet(
    candidates: Mapping[str, Any],
    packets: Sequence[Mapping[str, Any]],
    adjudications: Mapping[str, Any],
) -> Dict[str, Any]:
    """Return completed decisions only after verifying all immutable review content."""

    expected = build_candidate_adjudication_packet(candidates, packets)
    if _without_decisions(adjudications) != _without_decisions(expected):
        raise HumanSupportCandidateError("adjudication packet differs from the reviewed candidate evidence or labels")
    decisions: Dict[str, Dict[str, str]] = {}
    for index, row in enumerate(adjudications["cases"], start=1):
        decision = row.get("decision")
        if not isinstance(decision, Mapping) or set(decision) != DECISION_FIELDS:
            raise HumanSupportCandidateError(f"adjudication cases[{index}] decision fields are invalid")
        normalized = {field: str(decision[field]).strip() for field in DECISION_FIELDS}
        if not any(normalized.values()):
            continue
        case_id = str(row["case_id"])
        if not all(normalized.values()):
            raise HumanSupportCandidateError(f"adjudication case {case_id} has a partial decision")
        if normalized["adjudicated_label"] not in ALLOWED_SUPPORT_LABELS:
            raise HumanSupportCandidateError(f"adjudication case {case_id} has an unsupported label")
        reviewer_ids = {str(item["annotator_id"]) for item in row["annotations"]}
        if normalized["adjudicator_id"] in reviewer_ids:
            raise HumanSupportCandidateError(f"adjudication case {case_id} must use a third reviewer")
        decisions[case_id] = normalized
    return {
        "case_count": expected["case_count"],
        "completed_count": len(decisions),
        "packet_digest": expected["packet_digest"],
        "completed_packet_digest": _digest(adjudications),
        "decisions": decisions,
    }


def _empty_decision() -> Dict[str, str]:
    return {"adjudicator_id": "", "adjudicated_label": "", "rationale": ""}


def _without_decisions(packet: Mapping[str, Any]) -> Dict[str, Any]:
    content = deepcopy(dict(packet))
    for row in content.get("cases", []) if isinstance(content.get("cases"), list) else []:
        if isinstance(row, dict):
            row["decision"] = _empty_decision()
    return content


def _digest(value: Any) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()
