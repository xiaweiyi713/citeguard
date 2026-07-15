"""Confusion matrices, grouped diagnostics, and aggregate support metrics."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .support_eval import SUPPORT_LABEL_ORDER, SupportCase


def summarize_support_cases(cases: List[SupportCase]) -> Dict[str, Any]:
    """Return provenance and coverage counts for a support benchmark case list."""

    return {
        "n": len(cases),
        "case_types": _count_cases_by(cases, "case_type"),
        "evidence_scopes": _count_cases_by(cases, "evidence_scope"),
        "gold_labels": _count_cases_by(cases, "gold"),
        "languages": _count_cases_by(cases, "lang"),
        "splits": _count_cases_by(cases, "split"),
        "label_sources": sorted({case.label_source for case in cases if case.label_source}),
    }


def compute_support_diagnostics(
    cases: List[SupportCase], predictions: List[str], backend_name: str = ""
) -> Dict[str, Any]:
    if len(cases) != len(predictions):
        raise ValueError("cases and predictions must have the same length")

    preds = [(case.gold, pred) for case, pred in zip(cases, predictions)]
    metrics = compute_support_metrics(preds)
    buckets = compute_support_error_buckets(cases, predictions)
    missed_contradictions = buckets["missed_contradiction"]
    false_support = buckets["false_support"]
    weak_false_support = buckets["weak_false_support"]
    backend_label = backend_name or "unknown"
    backend_lower = backend_label.lower()
    heuristic_limited = "heuristic" in backend_lower

    warnings: List[str] = []
    recommendations: List[str] = []
    if heuristic_limited:
        warnings.append(
            "Heuristic support mode cannot reliably clear contradictions; do not treat absent contradicted verdicts as proof that no contradiction exists."
        )
        recommendations.append("Run the deep NLI support backend for contradiction-sensitive evaluation.")
    if missed_contradictions:
        warnings.append(
            "Contradiction recall is below target; inspect missed_contradiction cases before relying on support verdicts."
        )
        recommendations.append("Prioritize contradiction examples when calibrating or selecting the support backend.")
    if false_support or weak_false_support:
        warnings.append("At least one non-supporting case was predicted as supported or weakly_supported.")
        recommendations.append("Review false_support and weak_false_support buckets before relaxing thresholds.")

    return {
        "backend": backend_label,
        "heuristic_limited": heuristic_limited,
        "needs_nli_contradiction_review": bool(missed_contradictions),
        "missed_contradiction_case_ids": [item["case_id"] for item in missed_contradictions],
        "false_support_case_ids": [item["case_id"] for item in false_support],
        "weak_false_support_case_ids": [item["case_id"] for item in weak_false_support],
        "contradiction_recall": metrics["contradiction_recall"],
        "false_support_rate": metrics["false_support_rate"],
        "warnings": warnings,
        "recommendations": recommendations,
    }


def _compute_grouped_metrics(
    cases: List[SupportCase], predictions: List[str], field_name: str
) -> Dict[str, Dict[str, float]]:
    grouped: Dict[str, List[Tuple[str, str]]] = {}
    for case, pred in zip(cases, predictions):
        key = str(getattr(case, field_name) or "unknown")
        grouped.setdefault(key, []).append((case.gold, pred))
    return {key: compute_support_metrics(grouped[key]) for key in sorted(grouped)}


def _count_cases_by(cases: List[SupportCase], field_name: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for case in cases:
        key = str(getattr(case, field_name) or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def compute_support_confusion_matrix(preds: List[Tuple[str, str]]) -> Dict[str, Dict[str, int]]:
    labels = sorted({label for pair in preds for label in pair})
    matrix: Dict[str, Dict[str, int]] = {gold: {pred: 0 for pred in labels} for gold in labels}
    for gold, pred in preds:
        matrix.setdefault(gold, {label: 0 for label in labels})
        if pred not in matrix[gold]:
            matrix[gold][pred] = 0
        matrix[gold][pred] += 1
    return matrix


def compute_support_error_bucket_counts(cases: List[SupportCase], predictions: List[str]) -> Dict[str, int]:
    return {key: len(items) for key, items in compute_support_error_buckets(cases, predictions).items()}


def compute_support_error_buckets(cases: List[SupportCase], predictions: List[str]) -> Dict[str, List[Dict[str, str]]]:
    if len(cases) != len(predictions):
        raise ValueError("cases and predictions must have the same length")

    buckets: Dict[str, List[Dict[str, str]]] = {
        "false_support": [],
        "weak_false_support": [],
        "missed_contradiction": [],
        "supported_rejected": [],
        "incorrect_abstention": [],
        "correct_abstention": [],
    }
    for case, pred in zip(cases, predictions):
        row = _error_bucket_row(case, pred)
        if pred == "supported" and case.gold != "supported":
            buckets["false_support"].append(row)
        if pred == "weakly_supported" and case.gold not in ("supported", "weakly_supported"):
            buckets["weak_false_support"].append(row)
        if case.gold == "contradicted" and pred != "contradicted":
            buckets["missed_contradiction"].append(row)
        if case.gold == "supported" and pred in ("contradicted", "insufficient_evidence"):
            buckets["supported_rejected"].append(row)
        if pred == "insufficient_evidence" and case.gold != "insufficient_evidence":
            buckets["incorrect_abstention"].append(row)
        if pred == "insufficient_evidence" and case.gold == "insufficient_evidence":
            buckets["correct_abstention"].append(row)
    return buckets


def _error_bucket_row(case: SupportCase, prediction: str) -> Dict[str, str]:
    return {
        "case_id": case.case_id,
        "gold": case.gold,
        "predicted": prediction,
        "case_type": case.case_type,
        "evidence_scope": case.evidence_scope,
        "lang": case.lang,
        "split": case.split,
        "label_source": case.label_source,
    }


def compute_support_metrics(preds: List[Tuple[str, str]]) -> Dict[str, Any]:
    n = len(preds)
    correct = sum(1 for gold, pred in preds if gold == pred)
    per_label = _compute_per_label_metrics(preds)
    aggregate_metrics = _compute_aggregate_label_metrics(per_label)
    supported_tp = sum(1 for gold, pred in preds if gold == "supported" and pred == "supported")
    supported_pred = sum(1 for _, pred in preds if pred == "supported")
    supported_total = sum(1 for gold, _ in preds if gold == "supported")
    supported_precision = supported_tp / supported_pred if supported_pred else 0.0
    supported_recall = supported_tp / supported_total if supported_total else 0.0
    supported_f1 = (
        2 * supported_precision * supported_recall / (supported_precision + supported_recall)
        if supported_precision + supported_recall
        else 0.0
    )
    misjudged_support = sum(
        1 for gold, pred in preds if gold == "supported" and pred in ("contradicted", "insufficient_evidence")
    )
    false_support = sum(1 for gold, pred in preds if pred == "supported" and gold != "supported")
    support_overcall = sum(
        1
        for gold, pred in preds
        if pred in ("supported", "weakly_supported") and gold not in ("supported", "weakly_supported")
    )
    non_supported_total = sum(1 for gold, _ in preds if gold != "supported")
    non_supporting_total = sum(1 for gold, _ in preds if gold not in ("supported", "weakly_supported"))
    abstentions = sum(1 for _, pred in preds if pred == "insufficient_evidence")
    contra_total = sum(1 for gold, _ in preds if gold == "contradicted")
    contra_hit = sum(1 for gold, pred in preds if gold == "contradicted" and pred == "contradicted")
    return {
        "n": n,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "supported_precision": round(supported_precision, 4),
        "supported_recall": round(supported_recall, 4),
        "supported_f1": round(supported_f1, 4),
        "false_support_rate": round(false_support / non_supported_total, 4) if non_supported_total else 0.0,
        "support_overcall_count": support_overcall,
        "support_overcall_rate": round(support_overcall / non_supporting_total, 4) if non_supporting_total else 0.0,
        "abstention_rate": round(abstentions / n, 4) if n else 0.0,
        "misjudged_support_rate": round(misjudged_support / supported_total, 4) if supported_total else 0.0,
        "contradiction_recall": round(contra_hit / contra_total, 4) if contra_total else 0.0,
        "macro_precision": aggregate_metrics["macro_precision"],
        "macro_recall": aggregate_metrics["macro_recall"],
        "macro_f1": aggregate_metrics["macro_f1"],
        "weighted_precision": aggregate_metrics["weighted_precision"],
        "weighted_recall": aggregate_metrics["weighted_recall"],
        "weighted_f1": aggregate_metrics["weighted_f1"],
        "per_label": per_label,
    }


def _compute_per_label_metrics(preds: List[Tuple[str, str]]) -> Dict[str, Dict[str, float]]:
    metrics: Dict[str, Dict[str, float]] = {}
    for label in SUPPORT_LABEL_ORDER:
        tp = sum(1 for gold, pred in preds if gold == label and pred == label)
        predicted = sum(1 for _, pred in preds if pred == label)
        gold_total = sum(1 for gold, _ in preds if gold == label)
        precision = tp / predicted if predicted else 0.0
        recall = tp / gold_total if gold_total else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        metrics[label] = {
            "tp": tp,
            "predicted": predicted,
            "gold": gold_total,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }
    return metrics


def _compute_aggregate_label_metrics(per_label: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    labels = [label for label in SUPPORT_LABEL_ORDER if label in per_label]
    if not labels:
        return {
            "macro_precision": 0.0,
            "macro_recall": 0.0,
            "macro_f1": 0.0,
            "weighted_precision": 0.0,
            "weighted_recall": 0.0,
            "weighted_f1": 0.0,
        }

    total_gold = sum(int(per_label[label].get("gold", 0)) for label in labels)

    def average(field: str) -> float:
        return round(sum(float(per_label[label].get(field, 0.0)) for label in labels) / len(labels), 4)

    def weighted_average(field: str) -> float:
        if not total_gold:
            return 0.0
        value = sum(float(per_label[label].get(field, 0.0)) * int(per_label[label].get("gold", 0)) for label in labels)
        return round(value / total_gold, 4)

    return {
        "macro_precision": average("precision"),
        "macro_recall": average("recall"),
        "macro_f1": average("f1"),
        "weighted_precision": weighted_average("precision"),
        "weighted_recall": weighted_average("recall"),
        "weighted_f1": weighted_average("f1"),
    }
