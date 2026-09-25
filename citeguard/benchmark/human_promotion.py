"""Promote independently labeled real-source candidates into support evaluation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

from citeguard.benchmark.human_candidates import (
    HumanSupportCandidateError,
    _blinded_case_id,
    merge_candidate_annotation_packets,
    validate_candidate_dataset,
)
from citeguard.benchmark.human_adjudication import validate_candidate_adjudication_packet
from citeguard.verification.support_eval import (
    SupportCase,
    SupportSetCase,
    support_set_case_to_label_case,
    validate_support_eval_dataset,
)
from citeguard.verification.support_eval_labels import validate_support_label_sidecar


def promote_human_support_candidates(
    candidates: Mapping[str, Any],
    packets: Sequence[Mapping[str, Any]],
    dataset: Mapping[str, Any],
    sidecar: Mapping[str, Any],
    *,
    curator_id: str,
    adjudications: Optional[Mapping[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Re-verify packets and stage agreed or independently adjudicated cases.

    Packet annotations are the sole source of labels. A previously merged
    candidate status is never trusted as evidence of human review.
    """

    validate_candidate_dataset(candidates)
    validate_support_eval_dataset(dict(dataset))
    validate_support_label_sidecar(dict(sidecar), _label_cases(dataset))
    curator = curator_id.strip()
    if not curator:
        raise HumanSupportCandidateError("curator_id is required for dataset review")
    if len(packets) < 2:
        raise HumanSupportCandidateError("at least two independent completed packets are required")
    if any(row.get("annotations") or row.get("annotation_status") != "not_human_reviewed" for row in candidates["cases"]):
        raise HumanSupportCandidateError("use the original unlabeled candidate catalog, not a merged review file")

    merged, merge_report = merge_candidate_annotation_packets(candidates, packets)
    if merge_report["skipped_count"]:
        raise HumanSupportCandidateError("one or more packet rows were rejected; inspect the merge report first")
    adjudication_report = (
        validate_candidate_adjudication_packet(candidates, packets, adjudications)
        if adjudications is not None else None
    )
    decisions = adjudication_report["decisions"] if adjudication_report else {}

    output_dataset = deepcopy(dict(dataset))
    output_sidecar = deepcopy(dict(sidecar))
    existing_ids = {
        str(row["id"])
        for key in ("cases", "set_cases")
        for row in output_dataset.get(key, [])
    }
    source_splits: Dict[str, str] = {}
    for row in output_dataset["cases"]:
        locator = str(row.get("source_locator", "")).strip()
        source_case_id = str(row.get("source_case_id", "")).strip()
        split = str(row.get("split", "")).strip()
        for source_key in (f"locator:{locator}" if locator else "", f"case:{source_case_id}" if source_case_id else ""):
            if source_key and split:
                if source_key in source_splits and source_splits[source_key] != split:
                    raise HumanSupportCandidateError(f"existing source {source_key!r} spans multiple splits")
                source_splits[source_key] = split

    promoted = []
    adjudicated = []
    skipped = []
    for row in merged["cases"]:
        case_id = str(row["id"])
        annotations = row["annotations"]
        if case_id in existing_ids:
            skipped.append({"case_id": case_id, "code": "already_in_dataset"})
            continue
        decision = decisions.get(_blinded_case_id(candidates, row))
        agreed = row["annotation_status"] == "dual_annotator_agreed" and len(annotations) == 2
        resolved = row["annotation_status"] == "dual_annotator_disagreement" and len(annotations) == 2 and decision is not None
        if not agreed and not resolved:
            code = (
                "requires_independent_adjudication"
                if row["annotation_status"] == "dual_annotator_disagreement"
                else "requires_exactly_two_agreeing_annotations"
            )
            skipped.append({"case_id": case_id, "code": code})
            continue
        reviewer_ids = [str(item["annotator_id"]) for item in annotations]
        if len(set(reviewer_ids)) != 2 or curator in reviewer_ids:
            skipped.append({"case_id": case_id, "code": "reviewers_must_be_distinct_from_curator"})
            continue
        if resolved:
            assert decision is not None
            adjudicator_id = str(decision["adjudicator_id"])
            label = str(decision["adjudicated_label"])
        else:
            adjudicator_id = ""
            label = str(annotations[0]["annotator_label"])
        if resolved and adjudicator_id == curator:
            skipped.append({"case_id": case_id, "code": "curator_must_be_distinct_from_adjudicator"})
            continue
        if any(not str(item.get("rationale", "")).strip() for item in annotations):
            skipped.append({"case_id": case_id, "code": "both_rationales_required"})
            continue
        if any(item.get("packet_verified") is not True for item in annotations):
            skipped.append({"case_id": case_id, "code": "unverified_packet"})
            continue
        locator = str(row["source_locator"]).strip()
        source_keys = (f"locator:{locator}", f"case:{row['source_case_id']}")
        split = str(row["split"]).strip()
        if any(key in source_splits and source_splits[key] != split for key in source_keys):
            skipped.append({"case_id": case_id, "code": "source_crosses_splits"})
            continue

        label_notes = (
            "Two independent reviewers disagreed; a third reviewer adjudicated. Rationales remain in archived packets."
            if resolved else
            "Two independent reviewers agreed; rationales remain in the archived completed packets."
        )
        output_dataset["cases"].append({
            "id": case_id,
            "benchmark_origin": "real_source",
            "claim": row["claim"],
            "evidence": row["evidence"],
            "gold": label,
            "lang": row["lang"],
            "domain": row["domain"],
            "writing_context": row["writing_context"],
            "evidence_scope": row["evidence_scope"],
            "case_type": row["case_type"],
            "split": split,
            "label_source": "human_benchmark",
            "label_notes": label_notes,
            "source_case_id": row["source_case_id"],
            "source_locator": locator,
            "evidence_locator": row["evidence_locator"],
            "rights_basis": row["rights_basis"],
            "candidate_provenance": {
                key: row["candidate_provenance"][key]
                for key in ("source_case_id", "metadata_snapshot_sha256", "collected_at", "public_metadata_only")
            },
        })
        output_sidecar["cases"].append({
            "case_id": case_id,
            "adjudication_status": "dual_annotator_adjudicated" if resolved else "dual_annotator_agreed",
            "annotator_count": 2,
            "annotator_labels": [str(item["annotator_label"]) for item in annotations],
            "annotator_ids": reviewer_ids,
            "adjudicated_label": label,
            "disagreement": "resolved" if resolved else "none",
            "adjudicator": adjudicator_id,
            "source_locator": locator,
            "notes": "Promoted after separate dataset review.",
            "curator_id": curator,
            "review_provenance": [
                {
                    key: item[key]
                    for key in (
                        "annotator_id", "annotator_label", "packet_id", "packet_digest",
                        "completed_packet_digest", "packet_verified",
                    )
                }
                for item in annotations
            ],
            "adjudication_provenance": (
                {
                    "packet_digest": adjudication_report["packet_digest"],
                    "completed_packet_digest": adjudication_report["completed_packet_digest"],
                }
                if resolved and adjudication_report else {}
            ),
            "candidate_campaign_id": candidates["campaign_id"],
            "label_source": "human_benchmark",
            "case_type": row["case_type"],
            "evidence_scope": row["evidence_scope"],
            "split": split,
            "lang": row["lang"],
        })
        promoted.append(case_id)
        if resolved:
            adjudicated.append(case_id)
        existing_ids.add(case_id)
        for key in source_keys:
            source_splits[key] = split

    validate_support_eval_dataset(output_dataset)
    validate_support_label_sidecar(output_sidecar, _label_cases(output_dataset))
    unresolved = [item["case_id"] for item in skipped if item["code"] == "requires_independent_adjudication"]
    awaiting_second = [
        item["case_id"] for item in skipped if item["code"] == "requires_exactly_two_agreeing_annotations"
    ]
    report = {
        "ok": True,
        "candidate_count": len(merged["cases"]),
        "promoted_count": len(promoted),
        "promoted_case_ids": promoted,
        "adjudicated_count": len(adjudicated),
        "adjudicated_case_ids": adjudicated,
        "unresolved_disagreement_case_ids": unresolved,
        "awaiting_second_review_case_ids": awaiting_second,
        "skipped": skipped,
        "merge_conflicts": merge_report["conflicts"],
        "curator_id": curator,
        "benchmark_ready": False,
        "next_action": (
            "obtain_independent_adjudication"
            if unresolved else "obtain_second_independent_review"
            if awaiting_second else "run_human_benchmark_audit_and_freeze_test_split_when_quotas_are_met"
        ),
    }
    return output_dataset, output_sidecar, report


def _label_cases(dataset: Mapping[str, Any]) -> list[SupportCase]:
    cases = [
        SupportCase(
            row["id"], row["claim"], row["evidence"], row["gold"],
            lang=row["lang"], evidence_scope=row["evidence_scope"],
            label_source=row["label_source"], label_notes=row.get("label_notes", ""),
            case_type=row["case_type"], split=row["split"],
            source_locator=row.get("source_locator", ""),
        )
        for row in dataset["cases"]
    ]
    cases.extend(
        support_set_case_to_label_case(SupportSetCase(
            row["id"], row["claim"], row["citation_verdicts"], row["gold"],
            lang=row["lang"], label_source=row["label_source"],
            label_notes=row.get("label_notes", ""), case_type=row["case_type"], split=row["split"],
        ))
        for row in dataset.get("set_cases", [])
    )
    return cases
