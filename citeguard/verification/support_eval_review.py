"""Human review queues and high-risk error analysis for support evaluation."""

from __future__ import annotations

from typing import Any, Dict, List

from .support_eval import HIGH_RISK_SUPPORT_CASE_TYPES, SupportCase


def _unique_strings(values: Any) -> List[str]:
    unique: List[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in unique:
            unique.append(text)
    return unique


def compute_support_review_queue_summary(review_queue: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize a support review queue for machine routing."""

    valid_items = [item for item in review_queue if isinstance(item, dict)]
    by_severity: Dict[str, int] = {}
    by_recommended_action: Dict[str, int] = {}
    by_bucket: Dict[str, int] = {}
    critical_case_ids: List[str] = []
    top_case_ids: List[str] = []

    for item in valid_items:
        case_id = str(item.get("case_id", "")).strip()
        if case_id and len(top_case_ids) < 10:
            top_case_ids.append(case_id)
        severity = str(item.get("severity", "") or "unknown")
        by_severity[severity] = by_severity.get(severity, 0) + 1
        if severity == "critical" and case_id:
            critical_case_ids.append(case_id)
        action = str(item.get("recommended_action", "") or "inspect_case")
        by_recommended_action[action] = by_recommended_action.get(action, 0) + 1
        buckets = item.get("buckets", [])
        if not isinstance(buckets, list):
            buckets = []
        for bucket in buckets:
            bucket_name = str(bucket)
            by_bucket[bucket_name] = by_bucket.get(bucket_name, 0) + 1

    return {
        "count": len(valid_items),
        "by_severity": dict(sorted(by_severity.items())),
        "by_recommended_action": dict(sorted(by_recommended_action.items())),
        "by_bucket": dict(sorted(by_bucket.items())),
        "top_case_ids": top_case_ids,
        "critical_case_ids": critical_case_ids,
    }


def compute_release_blocker_summary(review_queue: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize support-eval review rows as release/readiness blockers."""

    valid_items = [item for item in review_queue if isinstance(item, dict)]
    blocking_severities = {"critical", "high"}
    blocking_items = [item for item in valid_items if str(item.get("severity", "")) in blocking_severities]
    review_required_items = [
        item for item in valid_items if str(item.get("severity", "")) in {"critical", "high", "medium"}
    ]
    blocking_case_ids = _queue_case_ids(blocking_items)
    review_required_case_ids = _queue_case_ids(review_required_items)
    blocking_buckets = _queue_bucket_counts(blocking_items)
    blocking_actions = _queue_action_counts(blocking_items)

    if any(str(item.get("severity", "")) == "critical" for item in blocking_items):
        next_action = "block_release_until_false_support_reviewed"
    elif blocking_items:
        next_action = "block_release_until_high_risk_reviewed"
    elif review_required_items:
        next_action = "review_medium_risk_before_benchmark_claims"
    else:
        next_action = "continue"

    return {
        "release_blocked": bool(blocking_items),
        "benchmark_claim_safe": not review_required_items,
        "blocking_count": len(blocking_items),
        "blocking_case_ids": blocking_case_ids,
        "blocking_buckets": blocking_buckets,
        "blocking_recommended_actions": blocking_actions,
        "review_required_count": len(review_required_items),
        "review_required_case_ids": review_required_case_ids,
        "next_action": next_action,
        "policy": "critical_or_high_support_eval_rows_block_release_claims",
        "interpretation": (
            "Critical/high support-eval rows block release-readiness claims. "
            "Medium rows still require review before making unqualified benchmark claims."
        ),
    }


def _queue_case_ids(items: List[Dict[str, Any]]) -> List[str]:
    return [str(item.get("case_id", "")) for item in items if isinstance(item, dict) and item.get("case_id")]


def _queue_bucket_counts(items: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        buckets = item.get("buckets", []) if isinstance(item, dict) else []
        if not isinstance(buckets, list):
            continue
        for bucket in buckets:
            name = str(bucket)
            counts[name] = counts.get(name, 0) + 1
    return dict(sorted(counts.items()))


def _queue_action_counts(items: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for item in items:
        action = str(item.get("recommended_action", "") or "inspect_case")
        counts[action] = counts.get(action, 0) + 1
    return dict(sorted(counts.items()))


def compute_support_review_queue(error_buckets: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, Any]]:
    """Return a risk-ordered review queue for support-eval failures."""

    by_case_id: Dict[str, Dict[str, Any]] = {}
    bucket_order = (
        "false_support",
        "missed_contradiction",
        "weak_false_support",
        "supported_rejected",
        "incorrect_abstention",
    )
    for bucket in bucket_order:
        for item in error_buckets.get(bucket, []):
            case_id = str(item.get("case_id", "")).strip()
            if not case_id:
                continue
            row = by_case_id.setdefault(case_id, dict(item, buckets=[]))
            row["buckets"].append(bucket)

    queue = []
    for row in by_case_id.values():
        metadata = _support_review_queue_metadata(row)
        queue.append(
            {
                "case_id": row["case_id"],
                "severity": metadata["severity"],
                "risk_score": metadata["risk_score"],
                "buckets": sorted(set(row["buckets"]), key=_support_review_bucket_rank),
                "gold": row.get("gold", ""),
                "predicted": row.get("predicted", ""),
                "case_type": row.get("case_type", ""),
                "evidence_scope": row.get("evidence_scope", ""),
                "lang": row.get("lang", ""),
                "split": row.get("split", ""),
                "recommended_action": metadata["recommended_action"],
                "reason": metadata["reason"],
            }
        )

    return sorted(
        queue,
        key=lambda item: (
            -int(item["risk_score"]),
            item.get("split") != "test",
            str(item.get("case_type", "")),
            str(item.get("case_id", "")),
        ),
    )


def _support_review_bucket_rank(bucket: str) -> int:
    ranks = {
        "false_support": 0,
        "missed_contradiction": 1,
        "weak_false_support": 2,
        "supported_rejected": 3,
        "incorrect_abstention": 4,
    }
    return ranks.get(bucket, 99)


def _support_review_queue_metadata(row: Dict[str, Any]) -> Dict[str, Any]:
    buckets = set(row.get("buckets", []))
    gold = str(row.get("gold", ""))
    predicted = str(row.get("predicted", ""))
    case_type = str(row.get("case_type", ""))

    if "false_support" in buckets and gold == "contradicted":
        return {
            "severity": "critical",
            "risk_score": 100,
            "recommended_action": "inspect_contradiction_before_accepting_support",
            "reason": "The backend predicted supported for a contradicted case.",
        }
    if "false_support" in buckets and case_type in HIGH_RISK_SUPPORT_CASE_TYPES:
        return {
            "severity": "critical",
            "risk_score": 95,
            "recommended_action": "rewrite_or_replace_evidence",
            "reason": "A high-risk non-supporting case was predicted as supported.",
        }
    if "false_support" in buckets:
        return {
            "severity": "critical",
            "risk_score": 90,
            "recommended_action": "rewrite_or_replace_evidence",
            "reason": "A non-supporting case was predicted as supported.",
        }
    if "missed_contradiction" in buckets:
        return {
            "severity": "high",
            "risk_score": 80,
            "recommended_action": "run_nli_or_human_contradiction_review",
            "reason": "A contradicted case was not predicted as contradicted.",
        }
    if "weak_false_support" in buckets:
        return {
            "severity": "high",
            "risk_score": 70,
            "recommended_action": "downgrade_or_find_stronger_evidence",
            "reason": "A non-supporting case was predicted as weakly_supported.",
        }
    if "supported_rejected" in buckets:
        return {
            "severity": "medium",
            "risk_score": 50,
            "recommended_action": "inspect_recall_loss",
            "reason": "A supported case was rejected or contradicted.",
        }
    if "incorrect_abstention" in buckets:
        return {
            "severity": "medium",
            "risk_score": 40,
            "recommended_action": "inspect_abstention_threshold",
            "reason": "The backend abstained on a case with a stronger gold label.",
        }
    return {
        "severity": "low",
        "risk_score": 10,
        "recommended_action": "inspect_case",
        "reason": f"Review case with gold={gold!r} and predicted={predicted!r}.",
    }


def compute_false_support_analysis(error_buckets: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    """Summarize the highest-risk support overcalls for release triage."""

    false_items = list(error_buckets.get("false_support", []))
    weak_items = list(error_buckets.get("weak_false_support", []))
    items = [dict(item, bucket="false_support") for item in false_items]
    items.extend(dict(item, bucket="weak_false_support") for item in weak_items)
    risk_slices = _false_support_risk_slices(items)
    acceptance_guard = compute_false_support_acceptance_guard(error_buckets)
    false_case_ids = [item["case_id"] for item in false_items]
    weak_case_ids = [item["case_id"] for item in weak_items]
    high_risk_overcall_case_ids = [
        item["case_id"]
        for item in items
        if item.get("case_type") in HIGH_RISK_SUPPORT_CASE_TYPES
        or item.get("gold") == "contradicted"
        or item.get("split") == "test"
        or item.get("lang") not in {"", "en", None}
    ]
    return {
        "false_support_count": len(false_items),
        "weak_false_support_count": len(weak_items),
        "total_overcall_count": len(items),
        "case_ids": [item["case_id"] for item in items],
        "false_support_case_ids": false_case_ids,
        "weak_false_support_case_ids": weak_case_ids,
        "high_risk_overcall_case_ids": high_risk_overcall_case_ids,
        "high_risk_case_ids": false_case_ids,
        "acceptance_guard": acceptance_guard,
        "review_plan": compute_false_support_review_plan(acceptance_guard, risk_slices),
        "risk_slices": risk_slices,
        "top_risk_slice": risk_slices[0] if risk_slices else None,
        "by_case_type": _false_support_group_summary(items, "case_type"),
        "by_evidence_scope": _false_support_group_summary(items, "evidence_scope"),
        "by_language": _false_support_group_summary(items, "lang"),
        "by_split": _false_support_group_summary(items, "split"),
        "interpretation": (
            "False-support overcalls are the highest-risk support failures. "
            "Review these cases before relaxing support thresholds or shipping a support backend."
        ),
    }


def compute_support_acceptance_slices(cases: List[SupportCase], predictions: List[str]) -> List[Dict[str, Any]]:
    """Return fixed support-risk slices that should stay visible even when clear."""

    if len(cases) != len(predictions):
        raise ValueError("cases and predictions must have the same length")

    slice_specs: List[Dict[str, Any]] = [
        {
            "id": "contradiction",
            "severity": "critical",
            "predicate": lambda case: case.gold == "contradicted",
            "policy": "contradicted_cases_must_not_be_called_supported",
            "recommended_action": "inspect_contradiction_before_accepting_support",
        },
        {
            "id": "hard_negative",
            "severity": "critical",
            "predicate": lambda case: case.case_type == "hard_negative",
            "policy": "real_or_related_papers_without_claim_support_must_not_be_called_supported",
            "recommended_action": "rewrite_or_replace_evidence",
        },
        {
            "id": "full_text_boundary",
            "severity": "high",
            "predicate": lambda case: (
                case.case_type == "full_text_required" or case.evidence_scope in {"full_text", "mixed_with_full_text"}
            ),
            "policy": "abstract_or_metadata_evidence_must_not_be_upgraded_to_full_text_support",
            "recommended_action": "inspect_full_text_or_find_stronger_citation",
        },
        {
            "id": "test_split",
            "severity": "high",
            "predicate": lambda case: case.split == "test",
            "policy": "heldout_test_overcalls_require_release_review",
            "recommended_action": "block_release_until_reviewed",
        },
        {
            "id": "non_english",
            "severity": "high",
            "predicate": lambda case: case.lang not in {"", "en"},
            "policy": "non_english_overcalls_require_language_specific_review",
            "recommended_action": "review_language_specific_failure",
        },
    ]

    rows: List[Dict[str, Any]] = []
    for spec in slice_specs:
        pairs = [(case, prediction) for case, prediction in zip(cases, predictions) if spec["predicate"](case)]
        false_case_ids = [
            case.case_id for case, prediction in pairs if prediction == "supported" and case.gold != "supported"
        ]
        weak_case_ids = [
            case.case_id
            for case, prediction in pairs
            if prediction == "weakly_supported" and case.gold not in {"supported", "weakly_supported"}
        ]
        status = "blocked" if false_case_ids else "review_required" if weak_case_ids else "clear"
        rows.append(
            {
                "id": spec["id"],
                "severity": spec["severity"],
                "status": status,
                "case_count": len(pairs),
                "case_ids": [case.case_id for case, _prediction in pairs],
                "false_support_count": len(false_case_ids),
                "false_support_case_ids": false_case_ids,
                "weak_false_support_count": len(weak_case_ids),
                "weak_false_support_case_ids": weak_case_ids,
                "recommended_action": spec["recommended_action"] if status != "clear" else "continue",
                "policy": spec["policy"],
            }
        )
    return rows


def compute_false_support_review_plan(
    acceptance_guard: Dict[str, Any],
    risk_slices: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Return an action-first review plan for support overcalls."""

    block_case_ids = list(acceptance_guard.get("block_acceptance_case_ids", []) or [])
    review_case_ids = list(acceptance_guard.get("review_before_accepting_case_ids", []) or [])
    top_slice = risk_slices[0] if risk_slices else {}
    if block_case_ids:
        status = "blocked"
        next_action = "review_supported_overcalls_before_release"
    elif review_case_ids:
        status = "review_required"
        next_action = "review_weak_support_overcalls_before_acceptance"
    else:
        status = "clear"
        next_action = "continue"

    phases: List[Dict[str, Any]] = [
        {
            "id": "supported_overcall_blockers",
            "priority": 1,
            "status": "blocked" if block_case_ids else "clear",
            "recommended_action": "rewrite_or_replace_evidence",
            "case_ids": block_case_ids,
            "count": len(block_case_ids),
        },
        {
            "id": "weak_support_overcall_review",
            "priority": 2,
            "status": "review_required" if review_case_ids else "clear",
            "recommended_action": "downgrade_or_find_stronger_evidence",
            "case_ids": review_case_ids,
            "count": len(review_case_ids),
        },
        {
            "id": "highest_risk_slice_review",
            "priority": 3,
            "status": "review_required" if top_slice else "clear",
            "recommended_action": top_slice.get("recommended_action", "continue") if top_slice else "continue",
            "risk_slice_id": top_slice.get("id") if top_slice else None,
            "case_ids": list(top_slice.get("case_ids", []) or []) if top_slice else [],
            "count": int(top_slice.get("count", 0) or 0) if top_slice else 0,
        },
    ]
    for phase in phases:
        phase["annotation_packet"] = _false_support_annotation_packet_for_phase(phase)
        phase["command_template"] = list(phase["annotation_packet"].get("command_template", []))
        phase["packet_id"] = phase["annotation_packet"].get("packet_id")
        phase["output"] = phase["annotation_packet"].get("output")
        phase["instructions_output"] = phase["annotation_packet"].get("instructions_output")
    recommended_packets = [
        phase["annotation_packet"]
        for phase in phases
        if phase.get("status") != "clear" and phase.get("annotation_packet", {}).get("case_ids")
    ]
    return {
        "schema_version": 1,
        "status": status,
        "next_action": next_action,
        "block_acceptance_case_ids": block_case_ids,
        "review_before_accepting_case_ids": review_case_ids,
        "top_risk_slice_id": top_slice.get("id") if top_slice else None,
        "top_risk_slice_case_ids": list(top_slice.get("case_ids", []) or []) if top_slice else [],
        "phases": phases,
        "recommended_annotation_packets": recommended_packets,
        "recommended_annotation_packet_count": len(recommended_packets),
        "recommended_annotation_case_ids": _unique_strings(
            case_id
            for packet in recommended_packets
            for case_id in packet.get("case_ids", [])
            if isinstance(packet, dict)
        ),
        "policy": (
            "supported_overcalls_block_release; weak_overcalls_require_review; "
            "top_risk_slice_sets_triage_order; annotation_packets_are_review_assignments_not_label_changes"
        ),
    }


def _false_support_annotation_packet_for_phase(phase: Dict[str, Any]) -> Dict[str, Any]:
    phase_id = str(phase.get("id") or "false_support_review")
    case_ids = _unique_strings(str(case_id) for case_id in phase.get("case_ids", []) or [] if case_id)
    packet_id = f"support-label-packet-{phase_id.replace('_', '-')}"
    purpose = _false_support_phase_packet_purpose(phase)
    command = [
        "python",
        "scripts/prepare_support_label_sidecar.py",
        "--dataset",
        "data/eval/support_eval.json",
        "--existing-sidecar",
        "data/eval/support_eval_label_sidecar.json",
        "--annotation-packet",
        "--review-phase",
        phase_id,
        "--packet-purpose",
        purpose,
    ]
    for case_id in case_ids:
        command.extend(["--case-id", case_id])
    command.extend(
        [
            "--output",
            f"experiments/{packet_id}.json",
            "--instructions-output",
            f"experiments/{packet_id}-instructions.md",
        ]
    )
    return {
        "schema_version": 1,
        "packet_id": packet_id,
        "review_phase": phase_id,
        "packet_purpose": purpose,
        "status": phase.get("status", "clear"),
        "priority": phase.get("priority"),
        "case_ids": case_ids,
        "count": len(case_ids),
        "command_template": command,
        "output": f"experiments/{packet_id}.json",
        "instructions_output": f"experiments/{packet_id}-instructions.md",
        "policy": "create_blinded_annotation_packet_before_changing_labels_or_accepting_support_overcalls",
    }


def _false_support_phase_packet_purpose(phase: Dict[str, Any]) -> str:
    phase_id = str(phase.get("id") or "")
    if phase_id == "supported_overcall_blockers":
        return "Review false supported overcalls that block release acceptance."
    if phase_id == "weak_support_overcall_review":
        return "Review weak-support overcalls before accepting weak support behavior."
    if phase_id == "highest_risk_slice_review":
        risk_slice_id = str(phase.get("risk_slice_id") or "highest_risk_slice")
        return f"Review the highest-risk false-support slice: {risk_slice_id}."
    return "Review support-eval overcalls before changing labels or thresholds."


def compute_false_support_acceptance_guard(error_buckets: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    """Return a compact policy decision for accepting support overcalls."""

    false_items = list(error_buckets.get("false_support", []))
    weak_items = list(error_buckets.get("weak_false_support", []))
    block_case_ids = [str(item["case_id"]) for item in false_items if item.get("case_id")]
    review_case_ids = [str(item["case_id"]) for item in weak_items if item.get("case_id")]
    if block_case_ids:
        next_action = "block_release_until_reviewed"
    elif review_case_ids:
        next_action = "review_before_accepting_weak_support"
    else:
        next_action = "accept_supported_predictions"
    return {
        "ok_to_accept_supported": not block_case_ids,
        "block_acceptance_count": len(block_case_ids),
        "block_acceptance_case_ids": block_case_ids,
        "review_before_accepting_count": len(review_case_ids),
        "review_before_accepting_case_ids": review_case_ids,
        "next_action": next_action,
        "policy": "supported_overcalls_block_acceptance; weak_overcalls_require_review",
        "interpretation": (
            "A supported prediction for a non-supporting gold case blocks acceptance. "
            "A weakly_supported prediction for a non-supporting gold case must be reviewed before it is treated as support."
        ),
    }


def compute_abstention_analysis(error_buckets: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    """Summarize abstentions so agents can separate conservative refusals from recall loss."""

    incorrect_items = list(error_buckets.get("incorrect_abstention", []))
    correct_items = list(error_buckets.get("correct_abstention", []))
    items = [dict(item, bucket="incorrect_abstention") for item in incorrect_items]
    items.extend(dict(item, bucket="correct_abstention") for item in correct_items)
    return {
        "incorrect_abstention_count": len(incorrect_items),
        "correct_abstention_count": len(correct_items),
        "total_abstention_count": len(items),
        "case_ids": [item["case_id"] for item in items],
        "incorrect_case_ids": [item["case_id"] for item in incorrect_items],
        "correct_case_ids": [item["case_id"] for item in correct_items],
        "review_case_ids": [item["case_id"] for item in incorrect_items],
        "by_case_type": _abstention_group_summary(items, "case_type"),
        "by_evidence_scope": _abstention_group_summary(items, "evidence_scope"),
        "by_language": _abstention_group_summary(items, "lang"),
        "by_split": _abstention_group_summary(items, "split"),
        "interpretation": (
            "Correct abstentions are conservative behavior on insufficient-evidence cases; "
            "incorrect abstentions are recall-loss cases to inspect before tightening abstention thresholds."
        ),
    }


def _false_support_risk_slices(items: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    """Return prioritized false-support overcall slices for agent triage."""

    slice_specs: List[Dict[str, Any]] = [
        {
            "id": "contradicted_overcalled",
            "severity": "critical",
            "risk_score": 100,
            "recommended_action": "inspect_contradiction_before_accepting_support",
            "description": "Cases whose gold label is contradicted but the backend overcalled support.",
            "predicate": lambda item: item.get("gold") == "contradicted",
        },
        {
            "id": "hard_negative_overcalled",
            "severity": "critical",
            "risk_score": 95,
            "recommended_action": "rewrite_or_replace_evidence",
            "description": "Hard-negative cases where a real or related source still does not support the claim.",
            "predicate": lambda item: item.get("case_type") == "hard_negative",
        },
        {
            "id": "full_text_boundary_overcalled",
            "severity": "high",
            "risk_score": 90,
            "recommended_action": "inspect_full_text_or_find_stronger_citation",
            "description": "Cases crossing a full-text boundary where abstract or metadata evidence is not enough.",
            "predicate": lambda item: (
                item.get("case_type") == "full_text_required"
                or item.get("evidence_scope") in {"full_text", "mixed_with_full_text"}
            ),
        },
        {
            "id": "test_split_overcalled",
            "severity": "high",
            "risk_score": 85,
            "recommended_action": "block_release_until_reviewed",
            "description": "Held-out test split overcalls that should be reviewed before release reporting.",
            "predicate": lambda item: item.get("split") == "test",
        },
        {
            "id": "non_english_overcalled",
            "severity": "high",
            "risk_score": 80,
            "recommended_action": "review_language_specific_failure",
            "description": "Non-English overcalls that may indicate language-specific support failures.",
            "predicate": lambda item: item.get("lang") not in {"", "en", None},
        },
    ]

    slices: List[Dict[str, Any]] = []
    for spec in slice_specs:
        matches = [item for item in items if spec["predicate"](item)]
        if not matches:
            continue
        slices.append(
            {
                "id": spec["id"],
                "severity": spec["severity"],
                "risk_score": spec["risk_score"],
                "recommended_action": spec["recommended_action"],
                "description": spec["description"],
                "count": len(matches),
                "false_support": sum(1 for item in matches if item.get("bucket") == "false_support"),
                "weak_false_support": sum(1 for item in matches if item.get("bucket") == "weak_false_support"),
                "case_ids": [item["case_id"] for item in matches],
                "false_support_case_ids": [
                    item["case_id"] for item in matches if item.get("bucket") == "false_support"
                ],
                "weak_false_support_case_ids": [
                    item["case_id"] for item in matches if item.get("bucket") == "weak_false_support"
                ],
            }
        )
    return slices


def _false_support_group_summary(items: List[Dict[str, str]], field_name: str) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for item in items:
        key = str(item.get(field_name, "unknown") or "unknown")
        grouped.setdefault(key, []).append(item)
    return {
        key: {
            "false_support": sum(1 for item in grouped[key] if item.get("bucket") == "false_support"),
            "weak_false_support": sum(1 for item in grouped[key] if item.get("bucket") == "weak_false_support"),
            "total": len(grouped[key]),
            "case_ids": [item["case_id"] for item in grouped[key]],
            "false_support_case_ids": [
                item["case_id"] for item in grouped[key] if item.get("bucket") == "false_support"
            ],
            "weak_false_support_case_ids": [
                item["case_id"] for item in grouped[key] if item.get("bucket") == "weak_false_support"
            ],
        }
        for key in sorted(grouped)
    }


def _abstention_group_summary(items: List[Dict[str, str]], field_name: str) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, str]]] = {}
    for item in items:
        key = str(item.get(field_name, "unknown") or "unknown")
        grouped.setdefault(key, []).append(item)
    return {
        key: {
            "incorrect_abstention": sum(1 for item in grouped[key] if item.get("bucket") == "incorrect_abstention"),
            "correct_abstention": sum(1 for item in grouped[key] if item.get("bucket") == "correct_abstention"),
            "total": len(grouped[key]),
            "case_ids": [item["case_id"] for item in grouped[key]],
            "incorrect_case_ids": [
                item["case_id"] for item in grouped[key] if item.get("bucket") == "incorrect_abstention"
            ],
            "correct_case_ids": [
                item["case_id"] for item in grouped[key] if item.get("bucket") == "correct_abstention"
            ],
        }
        for key in sorted(grouped)
    }
