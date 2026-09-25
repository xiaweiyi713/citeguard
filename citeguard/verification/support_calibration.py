"""Uncalibrated threshold sweeps on the real-source hard-case slice."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence, Tuple

from citeguard.graph import CitationRecord
from citeguard.verifiers.support_backends import HeuristicSupportBackend
from citeguard.verification.support import assess_support
from citeguard.verification.support_eval_metrics import compute_support_metrics
from citeguard.verification.support_hard_cases import load_support_hard_cases


MIN_CALIBRATION_GROUP_N = 20
THRESHOLD_GRID = tuple(round(index / 10, 1) for index in range(10))
ACCEPTING_VERDICTS = {"supported", "weakly_supported"}


def evaluate_hard_case_thresholds(path: Path | str) -> Dict[str, Any]:
    """Sweep acceptance thresholds without promoting any value to a calibrated probability."""

    data = load_support_hard_cases(str(path))
    backend = HeuristicSupportBackend()
    rows = [_predict_case(case, backend) for case in data.get("cases") or []]
    thresholds = [_metrics_for_threshold(rows, minimum) for minimum in THRESHOLD_GRID]
    groups = _group_reports(rows)
    return {
        "schema_version": 1,
        "dataset": str(path),
        "case_count": len(rows),
        "calibration_status": "uncalibrated",
        "note": (
            "Scores remain uncalibrated. This sweep reports false-support vs recall "
            "tradeoffs on a maintainer-reviewed slice; it does not change production thresholds."
        ),
        "min_group_n": MIN_CALIBRATION_GROUP_N,
        "thresholds": thresholds,
        "groups": groups,
    }


def _predict_case(case: Mapping[str, Any], backend: HeuristicSupportBackend) -> Dict[str, Any]:
    record = CitationRecord(
        citation_id=str(case.get("id") or "hard-case"),
        title="",
        abstract=str(case.get("evidence") or ""),
        source="eval",
    )
    result = assess_support(str(case.get("claim") or ""), record, backend=backend, lang=str(case.get("lang") or ""))
    return {
        "id": str(case.get("id") or ""),
        "gold": str(case.get("gold") or ""),
        "pred": result.verdict.value,
        "confidence": float(result.confidence),
        "lang": str(case.get("lang") or ""),
        "error_family": str(case.get("error_family") or ""),
        "split": str(case.get("split") or ""),
    }


def _apply_threshold(pred: str, confidence: float, minimum: float) -> str:
    if pred in ACCEPTING_VERDICTS and confidence < minimum:
        return "insufficient_evidence"
    return pred


def _metrics_for_threshold(rows: Sequence[Mapping[str, Any]], minimum: float) -> Dict[str, Any]:
    pairs: List[Tuple[str, str]] = []
    accepted = 0
    for row in rows:
        pred = _apply_threshold(str(row["pred"]), float(row["confidence"]), minimum)
        if pred in ACCEPTING_VERDICTS:
            accepted += 1
        pairs.append((str(row["gold"]), pred))
    metrics = compute_support_metrics(pairs)
    return {
        "min_confidence": minimum,
        "false_support_rate": metrics["false_support_rate"],
        "supported_recall": metrics["supported_recall"],
        "abstention_rate": metrics["abstention_rate"],
        "accepted_support_rate": round(accepted / len(rows), 4) if rows else 0.0,
        "accuracy": metrics["accuracy"],
    }


def _group_reports(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    reports: List[Dict[str, Any]] = []
    for by in ("lang", "error_family", "split"):
        buckets: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            buckets[str(row.get(by) or "")].append(row)
        for value, items in sorted(buckets.items()):
            pairs = [(str(item["gold"]), str(item["pred"])) for item in items]
            metrics = compute_support_metrics(pairs)
            reports.append(
                {
                    "by": by,
                    "value": value,
                    "case_count": len(items),
                    "calibration_status": "uncalibrated",
                    "false_support_rate": metrics["false_support_rate"],
                    "supported_recall": metrics["supported_recall"],
                    "abstention_rate": metrics["abstention_rate"],
                }
            )
    return reports
