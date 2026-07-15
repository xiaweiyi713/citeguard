"""Acceptance gate computation for human support-label sidecars."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def compute_support_label_sidecar_gate(
    summary: Dict[str, Any],
    min_coverage: float = 1.0,
    min_human_reviewed: int = 0,
    min_high_risk_reviewed: int = 0,
    min_high_risk_reviewed_by_language: Optional[Dict[str, int]] = None,
    min_dual_annotated: int = 0,
    max_unresolved_disagreements: int = 0,
    min_raw_dual_agreement_rate: Optional[float] = None,
    max_supported_disagreements: Optional[int] = None,
) -> Dict[str, Any]:
    """Evaluate provenance sidecar coverage gates from a validation summary."""

    coverage = _safe_float(summary.get("coverage", 0.0))
    human_reviewed = _safe_int(summary.get("human_reviewed", 0))
    maturity = summary.get("label_maturity", {})
    if not isinstance(maturity, dict):
        maturity = {}
    high_risk_review = summary.get("high_risk_review", {})
    if not isinstance(high_risk_review, dict):
        high_risk_review = {}
    full_text_required_review = summary.get("full_text_required_review", {})
    if not isinstance(full_text_required_review, dict):
        full_text_required_review = {}
    policy_boundary_review = summary.get("policy_boundary_review", {})
    if not isinstance(policy_boundary_review, dict):
        policy_boundary_review = {}
    label_provenance = summary.get("label_provenance", {})
    if not isinstance(label_provenance, dict):
        label_provenance = {}
    sidecar_case_provenance = summary.get("sidecar_case_provenance", {})
    if not isinstance(sidecar_case_provenance, dict):
        sidecar_case_provenance = {}
    high_risk_reviewed = _safe_int(high_risk_review.get("reviewed_count", 0))
    high_risk_unreviewed = _safe_int(high_risk_review.get("unreviewed_count", 0))
    high_risk_case_count = _safe_int(high_risk_review.get("case_count", 0))
    case_count_by_language = _int_mapping(high_risk_review.get("case_count_by_language", {}))
    reviewed_by_language = _int_mapping(high_risk_review.get("reviewed_by_language", {}))
    unreviewed_by_language = _int_mapping(high_risk_review.get("unreviewed_by_language", {}))
    dual_annotated = _safe_int(maturity.get("dual_annotated_count", 0))
    unresolved_disagreements = _safe_int(maturity.get("unresolved_disagreement_count", 0))
    supported_disagreements = _safe_int(maturity.get("supported_disagreement_count", 0))
    raw_dual_agreement_rate = maturity.get("raw_dual_agreement_rate")
    failures: List[Dict[str, Any]] = []
    if coverage < min_coverage:
        failures.append(
            {
                "code": "sidecar_coverage",
                "message": "Support label sidecar coverage is below the configured threshold.",
                "actual": coverage,
                "threshold": min_coverage,
            }
        )
    if human_reviewed < min_human_reviewed:
        failures.append(
            {
                "code": "sidecar_human_reviewed",
                "message": "Human-reviewed support label count is below the configured threshold.",
                "actual": human_reviewed,
                "threshold": min_human_reviewed,
            }
        )
    if high_risk_reviewed < min_high_risk_reviewed:
        failures.append(
            {
                "code": "sidecar_high_risk_reviewed",
                "message": "Human-reviewed high-risk support label count is below the configured threshold.",
                "actual": high_risk_reviewed,
                "threshold": min_high_risk_reviewed,
                "unreviewed_case_ids": list(high_risk_review.get("unreviewed_case_ids", [])),
            }
        )
    for language, threshold in sorted((min_high_risk_reviewed_by_language or {}).items()):
        actual = reviewed_by_language.get(language, 0)
        if actual < threshold:
            unreviewed_case_ids_by_language = high_risk_review.get("unreviewed_case_ids_by_language", {})
            if not isinstance(unreviewed_case_ids_by_language, dict):
                unreviewed_case_ids_by_language = {}
            failures.append(
                {
                    "code": "sidecar_high_risk_reviewed_by_language",
                    "message": "Human-reviewed high-risk support label count for a language is below the configured threshold.",
                    "language": language,
                    "actual": actual,
                    "threshold": threshold,
                    "unreviewed_case_ids": list(unreviewed_case_ids_by_language.get(language, [])),
                }
            )
    if dual_annotated < min_dual_annotated:
        failures.append(
            {
                "code": "sidecar_dual_annotated",
                "message": "Dual-annotated support label count is below the configured threshold.",
                "actual": dual_annotated,
                "threshold": min_dual_annotated,
            }
        )
    if unresolved_disagreements > max_unresolved_disagreements:
        failures.append(
            {
                "code": "sidecar_unresolved_disagreements",
                "message": "Unresolved support label disagreements exceed the configured threshold.",
                "actual": unresolved_disagreements,
                "threshold": max_unresolved_disagreements,
                "case_ids": list(maturity.get("unresolved_disagreement_case_ids", [])),
            }
        )
    if min_raw_dual_agreement_rate is not None:
        if raw_dual_agreement_rate is None:
            failures.append(
                {
                    "code": "sidecar_raw_dual_agreement_rate",
                    "message": "Raw dual-annotation agreement rate is unavailable.",
                    "actual": None,
                    "threshold": min_raw_dual_agreement_rate,
                }
            )
        elif float(raw_dual_agreement_rate) < min_raw_dual_agreement_rate:
            failures.append(
                {
                    "code": "sidecar_raw_dual_agreement_rate",
                    "message": "Raw dual-annotation agreement rate is below the configured threshold.",
                    "actual": float(raw_dual_agreement_rate),
                    "threshold": min_raw_dual_agreement_rate,
                }
            )
    if max_supported_disagreements is not None and supported_disagreements > max_supported_disagreements:
        failures.append(
            {
                "code": "sidecar_supported_disagreements",
                "message": "Supported-label disagreements exceed the configured threshold.",
                "actual": supported_disagreements,
                "threshold": max_supported_disagreements,
                "case_ids": list(maturity.get("supported_disagreement_case_ids", [])),
            }
        )
    return {
        "ok": not failures,
        "thresholds": {
            "min_coverage": min_coverage,
            "min_human_reviewed": min_human_reviewed,
            "min_high_risk_reviewed": min_high_risk_reviewed,
            "min_high_risk_reviewed_by_language": dict(sorted((min_high_risk_reviewed_by_language or {}).items())),
            "min_dual_annotated": min_dual_annotated,
            "max_unresolved_disagreements": max_unresolved_disagreements,
            "min_raw_dual_agreement_rate": min_raw_dual_agreement_rate,
            "max_supported_disagreements": max_supported_disagreements,
        },
        "metrics": {
            "coverage": coverage,
            "human_reviewed": human_reviewed,
            "high_risk_case_count": high_risk_case_count,
            "high_risk_reviewed": high_risk_reviewed,
            "high_risk_unreviewed": high_risk_unreviewed,
            "high_risk_case_count_by_language": case_count_by_language,
            "high_risk_reviewed_by_language": reviewed_by_language,
            "high_risk_unreviewed_by_language": unreviewed_by_language,
            "high_risk_case_count_by_language_case_type": _nested_int_mapping(
                high_risk_review.get("case_count_by_language_case_type", {})
            ),
            "high_risk_reviewed_by_language_case_type": _nested_int_mapping(
                high_risk_review.get("reviewed_by_language_case_type", {})
            ),
            "high_risk_unreviewed_by_language_case_type": _nested_int_mapping(
                high_risk_review.get("unreviewed_by_language_case_type", {})
            ),
            "full_text_required_case_count": _safe_int(full_text_required_review.get("case_count", 0)),
            "full_text_required_reviewed": _safe_int(full_text_required_review.get("reviewed_count", 0)),
            "full_text_required_unreviewed": _safe_int(full_text_required_review.get("unreviewed_count", 0)),
            "full_text_required_case_count_by_language": _int_mapping(
                full_text_required_review.get("case_count_by_language", {})
            ),
            "full_text_required_reviewed_by_language": _int_mapping(
                full_text_required_review.get("reviewed_by_language", {})
            ),
            "full_text_required_unreviewed_by_language": _int_mapping(
                full_text_required_review.get("unreviewed_by_language", {})
            ),
            "full_text_required_unreviewed_case_ids": list(full_text_required_review.get("unreviewed_case_ids", [])),
            "policy_boundary_case_count": _safe_int(policy_boundary_review.get("case_count", 0)),
            "policy_boundary_reviewed": _safe_int(policy_boundary_review.get("reviewed_count", 0)),
            "policy_boundary_unreviewed": _safe_int(policy_boundary_review.get("unreviewed_count", 0)),
            "policy_boundary_case_count_by_language": _int_mapping(
                policy_boundary_review.get("case_count_by_language", {})
            ),
            "policy_boundary_reviewed_by_language": _int_mapping(
                policy_boundary_review.get("reviewed_by_language", {})
            ),
            "policy_boundary_unreviewed_by_language": _int_mapping(
                policy_boundary_review.get("unreviewed_by_language", {})
            ),
            "policy_boundary_unreviewed_case_ids": list(policy_boundary_review.get("unreviewed_case_ids", [])),
            "dual_annotated": dual_annotated,
            "unresolved_disagreements": unresolved_disagreements,
            "supported_disagreements": supported_disagreements,
            "raw_dual_agreement_rate": raw_dual_agreement_rate,
            "unresolved_disagreement_case_ids": list(maturity.get("unresolved_disagreement_case_ids", [])),
            "supported_disagreement_case_ids": list(maturity.get("supported_disagreement_case_ids", [])),
            "label_source_counts": _int_mapping(label_provenance.get("label_source_counts", {})),
            "reviewed_by_label_source": _int_mapping(label_provenance.get("reviewed_by_label_source", {})),
            "unreviewed_by_label_source": _int_mapping(label_provenance.get("unreviewed_by_label_source", {})),
            "reviewed_source_locator_count": _safe_int(label_provenance.get("reviewed_source_locator_count", 0)),
            "reviewed_missing_source_locator_count": _safe_int(
                label_provenance.get("reviewed_missing_source_locator_count", 0)
            ),
            "published_benchmark_source_locator_count": _safe_int(
                label_provenance.get("published_benchmark_source_locator_count", 0)
            ),
            "sidecar_provenance_complete_count": _safe_int(sidecar_case_provenance.get("complete_count", 0)),
            "sidecar_provenance_complete_fraction": _safe_float(sidecar_case_provenance.get("complete_fraction", 0.0)),
            "sidecar_provenance_missing_count": _safe_int(sidecar_case_provenance.get("missing_count", 0)),
            "sidecar_provenance_missing_case_ids": list(sidecar_case_provenance.get("missing_case_ids", [])),
            "sidecar_provenance_missing_case_ids_by_field": {
                str(field): list(case_ids or [])
                for field, case_ids in (sidecar_case_provenance.get("missing_case_ids_by_field", {}) or {}).items()
                if isinstance(case_ids, list)
            }
            if isinstance(sidecar_case_provenance.get("missing_case_ids_by_field"), dict)
            else {},
            "sidecar_provenance_field_present_counts": _int_mapping(
                sidecar_case_provenance.get("field_present_counts", {})
            ),
            "dataset_cases": int(summary.get("dataset_cases", 0)),
            "sidecar_cases": int(summary.get("n", 0)),
        },
        "failures": failures,
    }


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _int_mapping(value: Any) -> Dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _safe_int(raw_value) for key, raw_value in sorted(value.items(), key=lambda item: str(item[0]))}


def _nested_int_mapping(value: Any) -> Dict[str, Dict[str, int]]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): _int_mapping(raw_value)
        for key, raw_value in sorted(value.items(), key=lambda item: str(item[0]))
        if isinstance(raw_value, dict)
    }


def _increment_nested_count(counts: Dict[str, Dict[str, int]], outer_key: str, inner_key: str) -> None:
    inner_counts = counts.setdefault(outer_key, {})
    inner_counts[inner_key] = inner_counts.get(inner_key, 0) + 1


def _sorted_nested_counts(counts: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    return {outer_key: dict(sorted(inner_counts.items())) for outer_key, inner_counts in sorted(counts.items())}
