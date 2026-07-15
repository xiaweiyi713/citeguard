"""Prediction execution and release-quality summaries for support evaluation."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from citeguard.graph import CitationRecord
from citeguard.verifiers import SupportBackend

from .support import assess_support
from .support_eval import ALLOWED_SPLITS, ALLOWED_SUPPORT_LABELS, SupportCase, SupportSetCase
from .support_eval_metrics import (
    _compute_grouped_metrics,
    compute_support_confusion_matrix,
    compute_support_diagnostics,
    compute_support_error_buckets,
    compute_support_metrics,
    summarize_support_cases,
)
from .support_eval_review import (
    compute_abstention_analysis,
    compute_false_support_analysis,
    compute_release_blocker_summary,
    compute_support_acceptance_slices,
    compute_support_review_queue,
    compute_support_review_queue_summary,
)


def _run_support_predictions(cases: List[SupportCase], backend: SupportBackend) -> List[str]:
    predictions: List[str] = []
    for case in cases:
        paper = citation_record_for_support_case(case)
        result = assess_support(case.claim, paper, backend=backend, lang=case.lang)
        predictions.append(result.verdict.value)
    return predictions


def filter_support_cases_by_split(cases: List[SupportCase], split: str) -> List[SupportCase]:
    """Return only cases assigned to a benchmark split."""

    if split not in ALLOWED_SPLITS:
        raise ValueError(f"unsupported support eval split: {split}")
    return [case for case in cases if case.split == split]


def citation_record_for_support_case(case: SupportCase) -> CitationRecord:
    scope = case.evidence_scope or "abstract"
    if scope == "title":
        return CitationRecord(citation_id=case.case_id, title=case.evidence, source="eval")
    if scope == "abstract":
        return CitationRecord(citation_id=case.case_id, title="", abstract=case.evidence, source="eval")
    if scope in ("metadata", "metadata_snippet", "full_text"):
        return CitationRecord(
            citation_id=case.case_id,
            title="",
            source="eval",
            metadata={"evidence_chunks": [_evidence_chunk_for_case(case)]},
        )
    if scope in ("mixed", "mixed_with_full_text"):
        return CitationRecord(
            citation_id=case.case_id,
            title="",
            abstract=case.evidence,
            source="eval",
            metadata={"evidence_chunks": [_evidence_chunk_for_case(case)]},
        )
    return CitationRecord(citation_id=case.case_id, title="", abstract=case.evidence, source="eval")


def _evidence_chunk_for_case(case: SupportCase) -> Dict[str, str]:
    scope = case.evidence_scope or "metadata"
    if scope == "metadata_snippet":
        return {
            "text": case.evidence,
            "source_field": "eval_metadata_snippet",
            "source_url": "https://example.org/eval-snippet",
            "evidence_scope": "metadata_snippet",
        }
    if scope == "full_text" or scope == "mixed_with_full_text":
        return {
            "text": case.evidence,
            "source_field": "eval_full_text_excerpt",
            "source_url": "",
            "evidence_scope": "full_text",
        }
    return {
        "text": case.evidence,
        "source_field": "eval_metadata_chunk",
        "source_url": "",
        "evidence_scope": "metadata",
    }


def run_support_eval(cases: List[SupportCase], backend: SupportBackend) -> Dict[str, float]:
    predictions = _run_support_predictions(cases, backend)
    return compute_support_metrics([(case.gold, pred) for case, pred in zip(cases, predictions)])


def run_support_eval_report(cases: List[SupportCase], backend: SupportBackend) -> Dict[str, Any]:
    predictions = _run_support_predictions(cases, backend)
    backend_name = str(getattr(backend, "backend_name", backend.__class__.__name__))
    return compute_support_report(cases, predictions, backend_name=backend_name)


def deterministic_support_fixture_predictions(cases: List[SupportCase]) -> List[str]:
    """Return gold labels for deterministic dataset/report plumbing checks.

    This intentionally does not measure model quality. It verifies that the
    support-eval dataset, splits, provenance, grouping, and report schema remain
    reproducible without loading local models or contacting model hubs.
    """

    return [case.gold for case in cases]


def run_support_eval_fixture(cases: List[SupportCase]) -> Dict[str, float]:
    predictions = deterministic_support_fixture_predictions(cases)
    return compute_support_metrics([(case.gold, pred) for case, pred in zip(cases, predictions)])


def run_support_eval_fixture_report(cases: List[SupportCase]) -> Dict[str, Any]:
    predictions = deterministic_support_fixture_predictions(cases)
    return compute_support_report(cases, predictions, backend_name="deterministic_fixture")


def predict_support_set_policy(case: SupportSetCase) -> str:
    """Return the conservative aggregate verdict for a citation-set policy case."""

    verdicts = list(case.citation_verdicts)
    if "contradicted" in verdicts:
        return "contradicted"
    if "supported" in verdicts:
        return "supported"
    if "weakly_supported" in verdicts:
        return "weakly_supported"
    return "insufficient_evidence"


def run_support_set_policy_fixture_report(cases: List[SupportSetCase]) -> Dict[str, Any]:
    """Evaluate model-free claim-level aggregation over per-citation verdicts."""

    predictions = [predict_support_set_policy(case) for case in cases]
    pairs = [(case.gold, prediction) for case, prediction in zip(cases, predictions)]
    metrics = compute_support_metrics(pairs)
    return {
        "backend": "support_set_policy_fixture",
        "dataset": {
            "n": len(cases),
            "case_types": _count_by_attr(cases, "case_type"),
            "languages": _count_by_attr(cases, "lang"),
            "splits": _count_by_attr(cases, "split"),
            "gold_labels": {
                label: sum(1 for case in cases if case.gold == label) for label in sorted(ALLOWED_SUPPORT_LABELS)
            },
        },
        "overall": metrics,
        "confusion_matrix": compute_support_confusion_matrix(pairs),
        "cases": [
            {
                "case_id": case.case_id,
                "claim": case.claim,
                "citation_verdicts": list(case.citation_verdicts),
                "gold": case.gold,
                "predicted": prediction,
                "correct": case.gold == prediction,
                "case_type": case.case_type,
                "lang": case.lang,
                "split": case.split,
                "label_source": case.label_source,
                "label_notes": case.label_notes,
            }
            for case, prediction in zip(cases, predictions)
        ],
        "interpretation": (
            "This fixture evaluates claim-level citation-set aggregation only. "
            "It does not measure retrieval or model quality."
        ),
    }


def _count_by_attr(items: List[Any], attr: str) -> Dict[str, int]:
    values = sorted({str(getattr(item, attr)) for item in items})
    return {value: sum(1 for item in items if str(getattr(item, attr)) == value) for value in values}


def _unique_strings(values: Any) -> List[str]:
    seen = set()
    result: List[str] = []
    for value in values or []:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def compute_support_quality_gate(
    report: Dict[str, Any],
    max_false_support_rate: float = 0.0,
    max_false_support_count: int = 0,
    max_weak_false_support_count: int = 0,
    min_supported_precision: float = 1.0,
    min_contradiction_recall: float = 1.0,
) -> Dict[str, Any]:
    """Evaluate conservative release gates for claim-support reports.

    The defaults are intentionally strict because a false `supported` verdict is
    the most dangerous support-checking failure mode for writing agents.
    """

    metrics = report.get("overall", {}) if isinstance(report, dict) else {}
    dataset = report.get("dataset", {}) if isinstance(report, dict) else {}
    gold_labels = dataset.get("gold_labels", {}) if isinstance(dataset, dict) else {}
    counts = report.get("error_bucket_counts", {}) if isinstance(report, dict) else {}
    buckets = report.get("error_buckets", {}) if isinstance(report, dict) else {}
    raw_review_queue = report.get("review_queue", []) if isinstance(report, dict) else []
    review_queue = (
        list(raw_review_queue)
        if isinstance(raw_review_queue, list)
        else compute_support_review_queue(buckets if isinstance(buckets, dict) else {})
    )
    if not review_queue and isinstance(buckets, dict):
        review_queue = compute_support_review_queue(buckets)
    review_queue_summary = compute_support_review_queue_summary(review_queue)
    thresholds = {
        "max_false_support_rate": max_false_support_rate,
        "max_false_support_count": max_false_support_count,
        "max_weak_false_support_count": max_weak_false_support_count,
        "min_supported_precision": min_supported_precision,
        "min_contradiction_recall": min_contradiction_recall,
    }
    failures: List[Dict[str, Any]] = []
    warnings: List[str] = []

    def case_ids(bucket_name: str) -> List[str]:
        items = buckets.get(bucket_name, []) if isinstance(buckets, dict) else []
        return [str(item.get("case_id")) for item in items if isinstance(item, dict) and item.get("case_id")]

    def add_failure(
        code: str,
        message: str,
        actual: float,
        threshold: float,
        bucket_name: str = "",
    ) -> None:
        failure: Dict[str, Any] = {
            "code": code,
            "message": message,
            "actual": actual,
            "threshold": threshold,
        }
        ids = case_ids(bucket_name) if bucket_name else []
        if ids:
            failure["case_ids"] = ids
        failures.append(failure)

    false_support_count = int(counts.get("false_support", 0))
    weak_false_support_count = int(counts.get("weak_false_support", 0))
    false_support_rate = float(metrics.get("false_support_rate", 0.0))
    support_overcall_count = int(metrics.get("support_overcall_count", false_support_count + weak_false_support_count))
    support_overcall_rate = float(metrics.get("support_overcall_rate", 0.0))
    supported_precision = float(metrics.get("supported_precision", 0.0))
    contradiction_recall = float(metrics.get("contradiction_recall", 0.0))

    if false_support_count > max_false_support_count:
        add_failure(
            "false_support_count",
            "Non-supporting cases were predicted as supported.",
            false_support_count,
            max_false_support_count,
            "false_support",
        )
    if false_support_rate > max_false_support_rate:
        add_failure(
            "false_support_rate",
            "False-support rate exceeds the configured threshold.",
            false_support_rate,
            max_false_support_rate,
            "false_support",
        )
    if weak_false_support_count > max_weak_false_support_count:
        add_failure(
            "weak_false_support_count",
            "Non-supporting cases were predicted as weakly_supported.",
            weak_false_support_count,
            max_weak_false_support_count,
            "weak_false_support",
        )
    if int(gold_labels.get("supported", 0)) > 0 and supported_precision < min_supported_precision:
        add_failure(
            "supported_precision",
            "Supported precision is below the configured threshold.",
            supported_precision,
            min_supported_precision,
        )
    if int(gold_labels.get("contradicted", 0)) > 0 and contradiction_recall < min_contradiction_recall:
        add_failure(
            "contradiction_recall",
            "Contradiction recall is below the configured threshold.",
            contradiction_recall,
            min_contradiction_recall,
            "missed_contradiction",
        )
    if int(gold_labels.get("supported", 0)) == 0:
        warnings.append("No gold supported cases are present; supported precision gate was skipped.")
    if int(gold_labels.get("contradicted", 0)) == 0:
        warnings.append("No gold contradicted cases are present; contradiction recall gate was skipped.")

    return {
        "ok": not failures,
        "thresholds": thresholds,
        "metrics": {
            "false_support_rate": false_support_rate,
            "false_support_count": false_support_count,
            "weak_false_support_count": weak_false_support_count,
            "support_overcall_count": support_overcall_count,
            "support_overcall_rate": support_overcall_rate,
            "supported_precision": supported_precision,
            "contradiction_recall": contradiction_recall,
            "review_queue_count": len(review_queue),
            "critical_review_count": sum(
                1 for item in review_queue if isinstance(item, dict) and item.get("severity") == "critical"
            ),
        },
        "review_queue_case_ids": [
            str(item.get("case_id", "")) for item in review_queue[:10] if isinstance(item, dict) and item.get("case_id")
        ],
        "critical_review_case_ids": [
            str(item.get("case_id", ""))
            for item in review_queue
            if isinstance(item, dict) and item.get("severity") == "critical" and item.get("case_id")
        ],
        "release_blocker_summary": compute_release_blocker_summary(review_queue),
        "review_queue_summary": review_queue_summary,
        "acceptance_slices": report.get("acceptance_slices", []) if isinstance(report, dict) else [],
        "failures": failures,
        "warnings": warnings,
    }


def compute_support_release_summary(
    report: Dict[str, Any],
    quality_gate: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a compact release/agent-facing support-eval summary."""

    metrics = report.get("overall", {}) if isinstance(report, dict) else {}
    dataset = report.get("dataset", {}) if isinstance(report, dict) else {}
    error_counts = report.get("error_bucket_counts", {}) if isinstance(report, dict) else {}
    review_queue_summary = report.get("review_queue_summary", {}) if isinstance(report, dict) else {}
    release_blockers = report.get("release_blocker_summary", {}) if isinstance(report, dict) else {}
    false_support = report.get("false_support_analysis", {}) if isinstance(report, dict) else {}
    acceptance_guard = report.get("acceptance_guard", {}) if isinstance(report, dict) else {}
    abstention = report.get("abstention_analysis", {}) if isinstance(report, dict) else {}
    quality = quality_gate if isinstance(quality_gate, dict) else report.get("quality_gate", {})
    label_gate = report.get("label_sidecar_gate", {}) if isinstance(report, dict) else {}
    label_sidecar = report.get("label_sidecar", {}) if isinstance(report, dict) else {}
    label_maturity = _support_release_label_maturity_summary(label_sidecar, label_gate)

    quality_ok = quality.get("ok") if isinstance(quality, dict) else None
    label_gate_ok = label_gate.get("ok") if isinstance(label_gate, dict) else None
    review_required_count = int(release_blockers.get("review_required_count", 0) or 0)
    release_blocked = bool(release_blockers.get("release_blocked"))
    supported_acceptance_ok = bool(acceptance_guard.get("ok_to_accept_supported", True))
    supported_acceptance_review = int(acceptance_guard.get("review_before_accepting_count", 0) or 0)
    labels_mature = bool(
        label_maturity["human_reviewed"] > 0
        and label_maturity["dual_annotated"] > 0
        and label_maturity["published_benchmark"] > 0
        and label_maturity["high_risk_unreviewed"] == 0
    )
    model_acceptance_ok = supported_acceptance_ok
    supported_acceptance_ok = bool(model_acceptance_ok and labels_mature)

    if quality_ok is False or label_gate_ok is False or release_blocked:
        status = "blocked"
    elif not labels_mature:
        status = "evaluation_passed_but_labels_immature"
    elif not supported_acceptance_ok or supported_acceptance_review or review_required_count:
        status = "review_required"
    else:
        status = "clear"

    next_action = str(release_blockers.get("next_action") or "")
    if status == "blocked" and next_action in {"", "continue"}:
        if label_gate_ok is False:
            next_action = "complete_label_provenance_review"
        elif quality_ok is False:
            next_action = "inspect_support_quality_gate_failures"
        else:
            next_action = "block_release_until_support_eval_reviewed"
    elif status == "evaluation_passed_but_labels_immature":
        next_action = "complete_human_label_review"
    elif status == "review_required" and next_action in {"", "continue"}:
        next_action = "review_support_eval_before_benchmark_claims"
    elif not next_action:
        next_action = "continue"

    top_risk_slice = false_support.get("top_risk_slice") if isinstance(false_support, dict) else None
    if not top_risk_slice:
        top_risk_slice = _first_non_clear_acceptance_slice(report.get("acceptance_slices", []))

    return {
        "schema_version": 1,
        "status": status,
        "next_action": next_action,
        "quality_gate_ok": quality_ok,
        "label_sidecar_gate_ok": label_gate_ok,
        "benchmark_claim_safe": bool(release_blockers.get("benchmark_claim_safe", False) and labels_mature),
        "ok_to_accept_supported": supported_acceptance_ok,
        "model_acceptance_ok": model_acceptance_ok,
        "labels_mature_for_benchmark_claims": labels_mature,
        "policy": (
            "treat_supported_as_release_ready_only_when_status_clear; "
            "false_support_blocks_release; weak_support_overcalls_require_review; "
            "label_sidecar_maturity_controls_benchmark_claims"
        ),
        "metrics": {
            "case_count": int(metrics.get("n", dataset.get("n", 0)) or 0),
            "supported_precision": float(metrics.get("supported_precision", 0.0) or 0.0),
            "supported_recall": float(metrics.get("supported_recall", 0.0) or 0.0),
            "supported_f1": float(metrics.get("supported_f1", 0.0) or 0.0),
            "macro_f1": float(metrics.get("macro_f1", 0.0) or 0.0),
            "weighted_f1": float(metrics.get("weighted_f1", 0.0) or 0.0),
            "false_support_rate": float(metrics.get("false_support_rate", 0.0) or 0.0),
            "support_overcall_count": int(metrics.get("support_overcall_count", 0) or 0),
            "support_overcall_rate": float(metrics.get("support_overcall_rate", 0.0) or 0.0),
            "abstention_rate": float(metrics.get("abstention_rate", 0.0) or 0.0),
            "contradiction_recall": float(metrics.get("contradiction_recall", 0.0) or 0.0),
        },
        "risk_counts": {
            "false_support": int(error_counts.get("false_support", 0) or 0),
            "weak_false_support": int(error_counts.get("weak_false_support", 0) or 0),
            "missed_contradiction": int(error_counts.get("missed_contradiction", 0) or 0),
            "incorrect_abstention": int(error_counts.get("incorrect_abstention", 0) or 0),
            "correct_abstention": int(error_counts.get("correct_abstention", 0) or 0),
        },
        "review_queue": {
            "count": int(review_queue_summary.get("count", review_required_count) or 0),
            "critical_case_ids": list(review_queue_summary.get("critical_case_ids", []) or []),
            "top_case_ids": list(review_queue_summary.get("top_case_ids", []) or []),
            "blocking_case_ids": list(release_blockers.get("blocking_case_ids", []) or []),
            "review_required_case_ids": list(release_blockers.get("review_required_case_ids", []) or []),
        },
        "acceptance": {
            "block_acceptance_case_ids": list(acceptance_guard.get("block_acceptance_case_ids", []) or []),
            "review_before_accepting_case_ids": list(
                acceptance_guard.get("review_before_accepting_case_ids", []) or []
            ),
            "top_risk_slice_id": top_risk_slice.get("id") if isinstance(top_risk_slice, dict) else None,
            "top_risk_slice_case_ids": (
                list(top_risk_slice.get("case_ids", []) or []) if isinstance(top_risk_slice, dict) else []
            ),
        },
        "abstention": {
            "total_count": int(abstention.get("total_abstention_count", 0) or 0),
            "correct_count": int(abstention.get("correct_abstention_count", 0) or 0),
            "incorrect_count": int(abstention.get("incorrect_abstention_count", 0) or 0),
            "review_case_ids": list(abstention.get("review_case_ids", []) or []),
        },
        "label_maturity": label_maturity,
    }


def _first_non_clear_acceptance_slice(rows: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(rows, list):
        return None
    for row in rows:
        if isinstance(row, dict) and row.get("status") != "clear":
            return row
    return None


def _support_release_label_maturity_summary(
    label_sidecar: Dict[str, Any],
    label_gate: Dict[str, Any],
) -> Dict[str, Any]:
    metrics = label_gate.get("metrics", {}) if isinstance(label_gate, dict) else {}
    maturity = label_sidecar.get("label_maturity", {}) if isinstance(label_sidecar, dict) else {}
    return {
        "human_reviewed": int(label_sidecar.get("human_reviewed", metrics.get("human_reviewed", 0)) or 0)
        if isinstance(label_sidecar, dict)
        else 0,
        "dual_annotated": int(metrics.get("dual_annotated", maturity.get("dual_annotated_count", 0)) or 0),
        "published_benchmark": int(maturity.get("published_benchmark_count", 0) or 0)
        if isinstance(maturity, dict)
        else 0,
        "high_risk_reviewed": int(metrics.get("high_risk_reviewed", 0) or 0),
        "high_risk_unreviewed": int(metrics.get("high_risk_unreviewed", 0) or 0),
        "sidecar_provenance_complete_fraction": float(metrics.get("sidecar_provenance_complete_fraction", 0.0) or 0.0),
    }


def compute_support_report(cases: List[SupportCase], predictions: List[str], backend_name: str = "") -> Dict[str, Any]:
    if len(cases) != len(predictions):
        raise ValueError("cases and predictions must have the same length")

    overall_preds = [(case.gold, pred) for case, pred in zip(cases, predictions)]
    error_buckets = compute_support_error_buckets(cases, predictions)
    error_bucket_counts = {key: len(items) for key, items in error_buckets.items()}
    review_queue = compute_support_review_queue(error_buckets)
    false_support_analysis = compute_false_support_analysis(error_buckets)
    acceptance_slices = compute_support_acceptance_slices(cases, predictions)
    report = {
        "dataset": summarize_support_cases(cases),
        "overall": compute_support_metrics(overall_preds),
        "confusion_matrix": compute_support_confusion_matrix(overall_preds),
        "by_case_type": _compute_grouped_metrics(cases, predictions, "case_type"),
        "by_evidence_scope": _compute_grouped_metrics(cases, predictions, "evidence_scope"),
        "by_language": _compute_grouped_metrics(cases, predictions, "lang"),
        "by_split": _compute_grouped_metrics(cases, predictions, "split"),
        "error_bucket_counts": error_bucket_counts,
        "error_buckets": error_buckets,
        "review_queue": review_queue,
        "review_queue_summary": compute_support_review_queue_summary(review_queue),
        "release_blocker_summary": compute_release_blocker_summary(review_queue),
        "false_support_analysis": false_support_analysis,
        "acceptance_guard": false_support_analysis["acceptance_guard"],
        "acceptance_slices": acceptance_slices,
        "abstention_analysis": compute_abstention_analysis(error_buckets),
        "diagnostics": compute_support_diagnostics(cases, predictions, backend_name=backend_name),
        "cases": [
            {
                "case_id": case.case_id,
                "gold": case.gold,
                "predicted": pred,
                "correct": case.gold == pred,
                "case_type": case.case_type,
                "evidence_scope": case.evidence_scope,
                "lang": case.lang,
                "split": case.split,
                "label_source": case.label_source,
            }
            for case, pred in zip(cases, predictions)
        ],
    }
    report["release_summary"] = compute_support_release_summary(report)
    return report
