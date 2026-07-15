"""Human-label sidecars, provenance summaries, and maturity gates."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .support_eval import (
    ALLOWED_ADJUDICATION_STATUSES,
    ALLOWED_SUPPORT_LABELS,
    HIGH_RISK_SUPPORT_CASE_TYPES,
    SUPPORT_LABEL_RANK,
    SupportCase,
    SupportLabelProvenance,
    SupportLabelSidecarValidationError,
)
from .support_eval_label_gate import _increment_nested_count, _sorted_nested_counts


def load_support_label_sidecar(path: str, cases: List[SupportCase]) -> List[SupportLabelProvenance]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    validate_support_label_sidecar(data, cases)
    return [
        SupportLabelProvenance(
            case_id=str(item["case_id"]),
            adjudication_status=str(item["adjudication_status"]),
            annotator_count=int(item.get("annotator_count", 0)),
            annotator_labels=[str(label) for label in item.get("annotator_labels", [])],
            adjudicated_label=str(item.get("adjudicated_label", "")),
            disagreement=str(item.get("disagreement", "none")),
            adjudicator=str(item.get("adjudicator", "")),
            source_locator=str(item.get("source_locator", "")),
            notes=str(item.get("notes", "")),
        )
        for item in data.get("cases", [])
    ]


def build_support_label_sidecar_template(
    cases: List[SupportCase],
    existing_sidecar: Optional[Dict[str, Any]] = None,
    dataset_name: str = "support_eval.json",
    include_context: bool = False,
) -> Dict[str, Any]:
    """Build a complete sidecar draft for human label provenance tracking.

    Existing valid entries are preserved. Missing cases receive a conservative
    `not_human_reviewed` placeholder whose adjudicated label mirrors the current
    dataset gold label, so the generated sidecar validates immediately while
    making the absence of human review explicit.
    """

    existing_by_id: Dict[str, Dict[str, Any]] = {}
    if existing_sidecar is not None:
        validate_support_label_sidecar(existing_sidecar, cases)
        existing_by_id = {
            str(item.get("case_id")): dict(item)
            for item in existing_sidecar.get("cases", [])
            if isinstance(item, dict) and item.get("case_id")
        }

    template_cases = []
    for case in cases:
        item = dict(existing_by_id.get(case.case_id, _sidecar_placeholder_for_case(case)))
        item.update(_sidecar_case_provenance_fields(case))
        if include_context:
            item.update(
                {
                    "claim": case.claim,
                    "evidence": case.evidence,
                    "evidence_scope": case.evidence_scope,
                    "case_type": case.case_type,
                    "split": case.split,
                    "dataset_gold": case.gold,
                }
            )
        template_cases.append(item)

    return {
        "schema_version": 1,
        "dataset": dataset_name,
        "notes": (
            "Generated support label provenance sidecar template. Preserve annotator labels, "
            "disagreement status, adjudicator, source locator, and notes for every reviewed case."
        ),
        "cases": template_cases,
    }


def _sidecar_placeholder_for_case(case: SupportCase) -> Dict[str, Any]:
    item = {
        "case_id": case.case_id,
        "adjudication_status": "not_human_reviewed",
        "annotator_count": 0,
        "annotator_labels": [],
        "adjudicated_label": case.gold,
        "disagreement": "not_applicable",
        "adjudicator": "",
        "source_locator": "",
        "notes": (
            "Unreviewed seed label. When reviewed, record evidence source, "
            "annotator rationale, disagreement resolution, and adjudication notes."
        ),
    }
    item.update(_sidecar_case_provenance_fields(case))
    return item


def _sidecar_case_provenance_fields(case: SupportCase) -> Dict[str, Any]:
    return {
        "label_source": case.label_source,
        "case_type": case.case_type,
        "evidence_scope": case.evidence_scope,
        "split": case.split,
        "lang": case.lang,
    }


def validate_support_label_sidecar(data: Dict[str, Any], cases: List[SupportCase]) -> Dict[str, Any]:
    """Validate optional sidecar metadata for human review and adjudication."""

    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(data, dict):
        raise SupportLabelSidecarValidationError("support label sidecar must be a JSON object")
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    case_ids = {case.case_id for case in cases}
    case_by_id = {case.case_id: case for case in cases}
    gold_by_case = {case.case_id: case.gold for case in cases}
    raw_items = data.get("cases")
    if not isinstance(raw_items, list):
        errors.append("cases must be a list")
        raw_items = []

    seen_ids = set()
    statuses = set()
    human_reviewed = 0
    for index, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            errors.append(f"sidecar item {index} must be an object")
            continue
        case_id = str(item.get("case_id", "")).strip()
        status = str(item.get("adjudication_status", "")).strip()
        annotator_labels = item.get("annotator_labels", [])
        adjudicated_label = str(item.get("adjudicated_label", "")).strip()
        disagreement = str(item.get("disagreement", "none")).strip()
        annotator_count = item.get("annotator_count", 0)

        if not case_id:
            errors.append(f"sidecar item {index} case_id is required")
        elif case_id in seen_ids:
            errors.append(f"sidecar case_id {case_id!r} is duplicated")
        elif case_id not in case_ids:
            errors.append(f"sidecar case_id {case_id!r} does not exist in dataset")
        seen_ids.add(case_id)

        if case_id in case_by_id:
            expected_provenance = _sidecar_case_provenance_fields(case_by_id[case_id])
            for field, expected in expected_provenance.items():
                if field in item and str(item.get(field, "")).strip() != str(expected).strip():
                    errors.append(
                        f"sidecar case {case_id or index} {field} {item.get(field)!r} does not match dataset {expected!r}"
                    )

        if status not in ALLOWED_ADJUDICATION_STATUSES:
            errors.append(f"sidecar case {case_id or index} has unsupported adjudication_status {status!r}")
        else:
            statuses.add(status)
            if status != "not_human_reviewed":
                human_reviewed += 1

        if not isinstance(annotator_count, int) or annotator_count < 0:
            errors.append(f"sidecar case {case_id or index} annotator_count must be a non-negative integer")
        if not isinstance(annotator_labels, list):
            errors.append(f"sidecar case {case_id or index} annotator_labels must be a list")
            annotator_labels = []
        if annotator_count and len(annotator_labels) != annotator_count:
            errors.append(f"sidecar case {case_id or index} annotator_labels length must match annotator_count")
        for label in annotator_labels:
            if label not in ALLOWED_SUPPORT_LABELS:
                errors.append(f"sidecar case {case_id or index} has unsupported annotator label {label!r}")
        if adjudicated_label not in ALLOWED_SUPPORT_LABELS:
            errors.append(f"sidecar case {case_id or index} has unsupported adjudicated_label {adjudicated_label!r}")
        if case_id in gold_by_case and adjudicated_label and adjudicated_label != gold_by_case[case_id]:
            errors.append(
                f"sidecar case {case_id} adjudicated_label {adjudicated_label!r} does not match dataset gold {gold_by_case[case_id]!r}"
            )
        if status == "single_annotator" and annotator_count != 1:
            errors.append(f"sidecar case {case_id or index} single_annotator requires annotator_count 1")
        if status.startswith("dual_annotator") and annotator_count < 2:
            errors.append(f"sidecar case {case_id or index} dual annotation requires annotator_count >= 2")
        if status == "dual_annotator_adjudicated" and not str(item.get("adjudicator", "")).strip():
            errors.append(f"sidecar case {case_id or index} adjudicated disagreements require adjudicator")
        if disagreement not in {"none", "resolved", "unresolved", "not_applicable"}:
            errors.append(f"sidecar case {case_id or index} has unsupported disagreement value {disagreement!r}")
        errors.extend(
            _sidecar_status_consistency_errors(
                case_id or str(index),
                status=status,
                annotator_count=annotator_count if isinstance(annotator_count, int) else 0,
                annotator_labels=annotator_labels,
                adjudicated_label=adjudicated_label,
                disagreement=disagreement,
                source_locator=str(item.get("source_locator", "")).strip(),
            )
        )
        if disagreement == "unresolved":
            warnings.append(f"sidecar case {case_id or index} has unresolved label disagreement")

    coverage = round(len(seen_ids & case_ids) / len(case_ids), 4) if case_ids else 0.0
    label_maturity = summarize_support_label_maturity(raw_items, dataset_case_count=len(case_ids))
    high_risk_review = summarize_support_high_risk_review(raw_items, cases)
    full_text_required_review = summarize_support_full_text_required_review(raw_items, cases)
    policy_boundary_review = summarize_support_policy_boundary_review(raw_items, cases)
    label_provenance = summarize_support_label_provenance(raw_items, cases)
    sidecar_case_provenance = summarize_support_sidecar_case_provenance(raw_items, cases)
    summary = {
        "ok": not errors,
        "schema_version": data.get("schema_version"),
        "n": len(raw_items),
        "dataset_cases": len(case_ids),
        "coverage": coverage,
        "human_reviewed": human_reviewed,
        "adjudication_statuses": {
            status: sum(1 for item in raw_items if isinstance(item, dict) and item.get("adjudication_status") == status)
            for status in sorted(statuses)
        },
        "label_maturity": label_maturity,
        "high_risk_review": high_risk_review,
        "full_text_required_review": full_text_required_review,
        "policy_boundary_review": policy_boundary_review,
        "label_provenance": label_provenance,
        "sidecar_case_provenance": sidecar_case_provenance,
        "warnings": warnings,
    }
    if errors:
        raise SupportLabelSidecarValidationError("; ".join(errors))
    return summary


def summarize_support_high_risk_review(raw_items: List[Any], cases: List[SupportCase]) -> Dict[str, Any]:
    """Summarize human-review coverage for the highest-risk support cases."""

    sidecar_by_id = {
        str(item.get("case_id", "")).strip(): item
        for item in raw_items
        if isinstance(item, dict) and str(item.get("case_id", "")).strip()
    }
    reviewed_case_ids: List[str] = []
    unreviewed_case_ids: List[str] = []
    case_count_by_language: Dict[str, int] = {}
    reviewed_by_language: Dict[str, int] = {}
    unreviewed_by_language: Dict[str, int] = {}
    reviewed_case_ids_by_language: Dict[str, List[str]] = {}
    unreviewed_case_ids_by_language: Dict[str, List[str]] = {}
    unreviewed_by_case_type: Dict[str, int] = {}
    case_count_by_language_case_type: Dict[str, Dict[str, int]] = {}
    reviewed_by_language_case_type: Dict[str, Dict[str, int]] = {}
    unreviewed_by_language_case_type: Dict[str, Dict[str, int]] = {}
    high_risk_cases = [case for case in cases if case.case_type in HIGH_RISK_SUPPORT_CASE_TYPES]
    for case in high_risk_cases:
        language = case.lang.strip() or "unknown"
        case_type = case.case_type.strip() or "unknown"
        case_count_by_language[language] = case_count_by_language.get(language, 0) + 1
        _increment_nested_count(case_count_by_language_case_type, language, case_type)
        item = sidecar_by_id.get(case.case_id, {})
        if item.get("adjudication_status") != "not_human_reviewed" and item:
            reviewed_case_ids.append(case.case_id)
            reviewed_by_language[language] = reviewed_by_language.get(language, 0) + 1
            _increment_nested_count(reviewed_by_language_case_type, language, case_type)
            reviewed_case_ids_by_language.setdefault(language, []).append(case.case_id)
            continue
        unreviewed_case_ids.append(case.case_id)
        unreviewed_by_language[language] = unreviewed_by_language.get(language, 0) + 1
        _increment_nested_count(unreviewed_by_language_case_type, language, case_type)
        unreviewed_case_ids_by_language.setdefault(language, []).append(case.case_id)
        unreviewed_by_case_type[case_type] = unreviewed_by_case_type.get(case_type, 0) + 1

    return {
        "case_types": sorted(HIGH_RISK_SUPPORT_CASE_TYPES),
        "case_count": len(high_risk_cases),
        "reviewed_count": len(reviewed_case_ids),
        "unreviewed_count": len(unreviewed_case_ids),
        "case_count_by_language": dict(sorted(case_count_by_language.items())),
        "reviewed_by_language": dict(sorted(reviewed_by_language.items())),
        "unreviewed_by_language": dict(sorted(unreviewed_by_language.items())),
        "reviewed_case_ids": reviewed_case_ids,
        "unreviewed_case_ids": unreviewed_case_ids,
        "reviewed_case_ids_by_language": dict(sorted(reviewed_case_ids_by_language.items())),
        "unreviewed_case_ids_by_language": dict(sorted(unreviewed_case_ids_by_language.items())),
        "unreviewed_by_case_type": dict(sorted(unreviewed_by_case_type.items())),
        "case_count_by_language_case_type": _sorted_nested_counts(case_count_by_language_case_type),
        "reviewed_by_language_case_type": _sorted_nested_counts(reviewed_by_language_case_type),
        "unreviewed_by_language_case_type": _sorted_nested_counts(unreviewed_by_language_case_type),
    }


def summarize_support_full_text_required_review(raw_items: List[Any], cases: List[SupportCase]) -> Dict[str, Any]:
    """Summarize human-review coverage for abstract/full-text boundary cases."""

    sidecar_by_id = {
        str(item.get("case_id", "")).strip(): item
        for item in raw_items
        if isinstance(item, dict) and str(item.get("case_id", "")).strip()
    }
    reviewed_case_ids: List[str] = []
    unreviewed_case_ids: List[str] = []
    case_count_by_language: Dict[str, int] = {}
    reviewed_by_language: Dict[str, int] = {}
    unreviewed_by_language: Dict[str, int] = {}
    reviewed_case_ids_by_language: Dict[str, List[str]] = {}
    unreviewed_case_ids_by_language: Dict[str, List[str]] = {}
    boundary_cases = [case for case in cases if case.case_type == "full_text_required"]
    for case in boundary_cases:
        language = case.lang.strip() or "unknown"
        case_count_by_language[language] = case_count_by_language.get(language, 0) + 1
        item = sidecar_by_id.get(case.case_id, {})
        if item.get("adjudication_status") != "not_human_reviewed" and item:
            reviewed_case_ids.append(case.case_id)
            reviewed_by_language[language] = reviewed_by_language.get(language, 0) + 1
            reviewed_case_ids_by_language.setdefault(language, []).append(case.case_id)
            continue
        unreviewed_case_ids.append(case.case_id)
        unreviewed_by_language[language] = unreviewed_by_language.get(language, 0) + 1
        unreviewed_case_ids_by_language.setdefault(language, []).append(case.case_id)

    return {
        "case_types": ["full_text_required"],
        "case_count": len(boundary_cases),
        "reviewed_count": len(reviewed_case_ids),
        "unreviewed_count": len(unreviewed_case_ids),
        "case_count_by_language": dict(sorted(case_count_by_language.items())),
        "reviewed_by_language": dict(sorted(reviewed_by_language.items())),
        "unreviewed_by_language": dict(sorted(unreviewed_by_language.items())),
        "reviewed_case_ids": reviewed_case_ids,
        "unreviewed_case_ids": unreviewed_case_ids,
        "reviewed_case_ids_by_language": dict(sorted(reviewed_case_ids_by_language.items())),
        "unreviewed_case_ids_by_language": dict(sorted(unreviewed_case_ids_by_language.items())),
    }


def summarize_support_policy_boundary_review(raw_items: List[Any], cases: List[SupportCase]) -> Dict[str, Any]:
    """Summarize human-review coverage for weak citation-set aggregation cases."""

    sidecar_by_id = {
        str(item.get("case_id", "")).strip(): item
        for item in raw_items
        if isinstance(item, dict) and str(item.get("case_id", "")).strip()
    }
    reviewed_case_ids: List[str] = []
    unreviewed_case_ids: List[str] = []
    case_count_by_language: Dict[str, int] = {}
    reviewed_by_language: Dict[str, int] = {}
    unreviewed_by_language: Dict[str, int] = {}
    reviewed_case_ids_by_language: Dict[str, List[str]] = {}
    unreviewed_case_ids_by_language: Dict[str, List[str]] = {}
    boundary_cases = [case for case in cases if case.case_type == "weak_set_boundary"]
    for case in boundary_cases:
        language = case.lang.strip() or "unknown"
        case_count_by_language[language] = case_count_by_language.get(language, 0) + 1
        item = sidecar_by_id.get(case.case_id, {})
        if item.get("adjudication_status") != "not_human_reviewed" and item:
            reviewed_case_ids.append(case.case_id)
            reviewed_by_language[language] = reviewed_by_language.get(language, 0) + 1
            reviewed_case_ids_by_language.setdefault(language, []).append(case.case_id)
            continue
        unreviewed_case_ids.append(case.case_id)
        unreviewed_by_language[language] = unreviewed_by_language.get(language, 0) + 1
        unreviewed_case_ids_by_language.setdefault(language, []).append(case.case_id)

    return {
        "case_types": ["weak_set_boundary"],
        "case_count": len(boundary_cases),
        "reviewed_count": len(reviewed_case_ids),
        "unreviewed_count": len(unreviewed_case_ids),
        "case_count_by_language": dict(sorted(case_count_by_language.items())),
        "reviewed_by_language": dict(sorted(reviewed_by_language.items())),
        "unreviewed_by_language": dict(sorted(unreviewed_by_language.items())),
        "reviewed_case_ids": reviewed_case_ids,
        "unreviewed_case_ids": unreviewed_case_ids,
        "reviewed_case_ids_by_language": dict(sorted(reviewed_case_ids_by_language.items())),
        "unreviewed_case_ids_by_language": dict(sorted(unreviewed_case_ids_by_language.items())),
    }


def summarize_support_label_provenance(raw_items: List[Any], cases: List[SupportCase]) -> Dict[str, Any]:
    """Summarize label-source and review-provenance coverage for benchmark claims."""

    case_by_id = {case.case_id: case for case in cases}
    label_source_counts: Dict[str, int] = {}
    status_by_label_source: Dict[str, Dict[str, int]] = {}
    reviewed_by_label_source: Dict[str, int] = {}
    unreviewed_by_label_source: Dict[str, int] = {}
    unreviewed_case_ids_by_label_source: Dict[str, List[str]] = {}
    reviewed_source_locator_count = 0
    reviewed_missing_source_locator_case_ids: List[str] = []
    published_benchmark_count = 0
    published_benchmark_source_locator_count = 0
    published_benchmark_case_ids: List[str] = []

    for case in cases:
        label_source = case.label_source.strip() or "unknown"
        label_source_counts[label_source] = label_source_counts.get(label_source, 0) + 1

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("case_id", "")).strip()
        resolved_case = case_by_id.get(case_id)
        label_source = (resolved_case.label_source.strip() if resolved_case else "") or "unknown"
        status = str(item.get("adjudication_status", "")).strip() or "unknown"
        source_locator = str(item.get("source_locator", "")).strip()
        status_counts = status_by_label_source.setdefault(label_source, {})
        status_counts[status] = status_counts.get(status, 0) + 1
        if status == "not_human_reviewed":
            unreviewed_by_label_source[label_source] = unreviewed_by_label_source.get(label_source, 0) + 1
            if case_id:
                unreviewed_case_ids_by_label_source.setdefault(label_source, []).append(case_id)
            continue

        reviewed_by_label_source[label_source] = reviewed_by_label_source.get(label_source, 0) + 1
        if source_locator:
            reviewed_source_locator_count += 1
        elif case_id:
            reviewed_missing_source_locator_case_ids.append(case_id)

        if status == "published_benchmark":
            published_benchmark_count += 1
            if case_id:
                published_benchmark_case_ids.append(case_id)
            if source_locator:
                published_benchmark_source_locator_count += 1

    return {
        "label_source_counts": dict(sorted(label_source_counts.items())),
        "status_by_label_source": {
            label_source: dict(sorted(status_counts.items()))
            for label_source, status_counts in sorted(status_by_label_source.items())
        },
        "reviewed_by_label_source": dict(sorted(reviewed_by_label_source.items())),
        "unreviewed_by_label_source": dict(sorted(unreviewed_by_label_source.items())),
        "unreviewed_case_ids_by_label_source": dict(sorted(unreviewed_case_ids_by_label_source.items())),
        "reviewed_source_locator_count": reviewed_source_locator_count,
        "reviewed_missing_source_locator_count": len(reviewed_missing_source_locator_case_ids),
        "reviewed_missing_source_locator_case_ids": reviewed_missing_source_locator_case_ids,
        "published_benchmark_count": published_benchmark_count,
        "published_benchmark_source_locator_count": published_benchmark_source_locator_count,
        "published_benchmark_case_ids": published_benchmark_case_ids,
    }


def summarize_support_sidecar_case_provenance(raw_items: List[Any], cases: List[SupportCase]) -> Dict[str, Any]:
    """Summarize dataset-context fields copied into the sidecar for review packets."""

    case_by_id = {case.case_id: case for case in cases}
    fields = ["label_source", "case_type", "evidence_scope", "split", "lang"]
    present_counts = {field: 0 for field in fields}
    complete_case_ids: List[str] = []
    missing_case_ids_by_field: Dict[str, List[str]] = {field: [] for field in fields}
    sidecar_case_ids = set()

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("case_id", "")).strip()
        if case_id not in case_by_id:
            continue
        sidecar_case_ids.add(case_id)
        complete = True
        for field in fields:
            if field in item:
                present_counts[field] += 1
                continue
            complete = False
            missing_case_ids_by_field[field].append(case_id)
        if complete:
            complete_case_ids.append(case_id)

    total = len(case_by_id)
    complete_count = len(complete_case_ids)
    missing_case_ids = [case.case_id for case in cases if case.case_id not in sidecar_case_ids]
    return {
        "fields": fields,
        "field_present_counts": present_counts,
        "complete_count": complete_count,
        "complete_fraction": round(complete_count / total, 4) if total else 0.0,
        "complete_case_ids": complete_case_ids,
        "missing_count": len(missing_case_ids),
        "missing_case_ids": missing_case_ids,
        "missing_case_ids_by_field": {
            field: case_ids for field, case_ids in missing_case_ids_by_field.items() if case_ids
        },
    }


def _sidecar_status_consistency_errors(
    case_id: str,
    *,
    status: str,
    annotator_count: int,
    annotator_labels: List[Any],
    adjudicated_label: str,
    disagreement: str,
    source_locator: str,
) -> List[str]:
    errors: List[str] = []
    normalized_labels = [str(label) for label in annotator_labels]
    unique_labels = {label for label in normalized_labels}

    if status == "not_human_reviewed":
        if annotator_count != 0:
            errors.append(f"sidecar case {case_id} not_human_reviewed requires annotator_count 0")
        if normalized_labels:
            errors.append(f"sidecar case {case_id} not_human_reviewed requires empty annotator_labels")
        if disagreement != "not_applicable":
            errors.append(f"sidecar case {case_id} not_human_reviewed requires disagreement 'not_applicable'")
    elif status == "single_annotator":
        if disagreement != "none":
            errors.append(f"sidecar case {case_id} single_annotator requires disagreement 'none'")
        if normalized_labels and adjudicated_label != normalized_labels[0]:
            errors.append(f"sidecar case {case_id} single_annotator adjudicated_label must match annotator label")
    elif status == "dual_annotator_agreed":
        if len(unique_labels) != 1:
            errors.append(f"sidecar case {case_id} dual_annotator_agreed requires all annotator labels to match")
        if disagreement != "none":
            errors.append(f"sidecar case {case_id} dual_annotator_agreed requires disagreement 'none'")
        if normalized_labels and adjudicated_label != normalized_labels[0]:
            errors.append(f"sidecar case {case_id} dual_annotator_agreed adjudicated_label must match annotator labels")
    elif status == "dual_annotator_adjudicated":
        if len(unique_labels) < 2:
            errors.append(
                f"sidecar case {case_id} dual_annotator_adjudicated requires at least two distinct annotator labels"
            )
        if disagreement != "resolved":
            errors.append(f"sidecar case {case_id} dual_annotator_adjudicated requires disagreement 'resolved'")
    elif status == "published_benchmark":
        if not source_locator:
            errors.append(f"sidecar case {case_id} published_benchmark requires source_locator")
        if disagreement == "unresolved":
            errors.append(f"sidecar case {case_id} published_benchmark cannot have unresolved disagreement")

    if disagreement in {"resolved", "unresolved"} and annotator_count < 2:
        errors.append(f"sidecar case {case_id} disagreement {disagreement!r} requires annotator_count >= 2")
    if disagreement == "none" and annotator_count >= 2 and len(unique_labels) > 1:
        errors.append(f"sidecar case {case_id} disagreement 'none' requires matching annotator labels")
    if disagreement == "not_applicable" and status != "not_human_reviewed":
        errors.append(f"sidecar case {case_id} disagreement 'not_applicable' is only for not_human_reviewed")
    return errors


def summarize_support_label_maturity(raw_items: List[Any], dataset_case_count: int = 0) -> Dict[str, Any]:
    """Summarize human-review and disagreement maturity for support labels."""

    reviewed_count = 0
    single_annotator_count = 0
    dual_annotated_count = 0
    dual_agreed_count = 0
    dual_disagreed_count = 0
    adjudicated_count = 0
    published_benchmark_count = 0
    resolved_disagreement_count = 0
    unresolved_disagreement_count = 0
    disagreement_case_ids: List[str] = []
    unresolved_disagreement_case_ids: List[str] = []
    supported_disagreement_case_ids: List[str] = []
    dual_label_pair_counts: Dict[str, int] = {}
    dual_disagreement_label_pair_counts: Dict[str, int] = {}

    for item in raw_items:
        if not isinstance(item, dict):
            continue
        case_id = str(item.get("case_id", "")).strip()
        status = str(item.get("adjudication_status", "")).strip()
        disagreement = str(item.get("disagreement", "none")).strip()
        annotator_count = item.get("annotator_count", 0)
        annotator_labels = item.get("annotator_labels", [])
        if not isinstance(annotator_count, int) or annotator_count < 0:
            annotator_count = 0
        if not isinstance(annotator_labels, list):
            annotator_labels = []

        if status != "not_human_reviewed":
            reviewed_count += 1
        if status == "single_annotator":
            single_annotator_count += 1
        if status == "dual_annotator_adjudicated":
            adjudicated_count += 1
        if status == "published_benchmark":
            published_benchmark_count += 1

        if annotator_count >= 2 and len(annotator_labels) >= 2:
            normalized_labels = [str(label) for label in annotator_labels]
            for left_index in range(len(normalized_labels)):
                for right_index in range(left_index + 1, len(normalized_labels)):
                    pair_key = _label_pair_key(normalized_labels[left_index], normalized_labels[right_index])
                    dual_label_pair_counts[pair_key] = dual_label_pair_counts.get(pair_key, 0) + 1
                    if normalized_labels[left_index] != normalized_labels[right_index]:
                        dual_disagreement_label_pair_counts[pair_key] = (
                            dual_disagreement_label_pair_counts.get(pair_key, 0) + 1
                        )

            dual_annotated_count += 1
            if len(set(normalized_labels)) == 1:
                dual_agreed_count += 1
            else:
                dual_disagreed_count += 1
                if case_id:
                    disagreement_case_ids.append(case_id)
                    if "supported" in normalized_labels:
                        supported_disagreement_case_ids.append(case_id)

        if disagreement == "resolved":
            resolved_disagreement_count += 1
        elif disagreement == "unresolved":
            unresolved_disagreement_count += 1
            if case_id:
                unresolved_disagreement_case_ids.append(case_id)

    return {
        "reviewed_count": reviewed_count,
        "reviewed_fraction": round(reviewed_count / dataset_case_count, 4) if dataset_case_count else 0.0,
        "single_annotator_count": single_annotator_count,
        "dual_annotated_count": dual_annotated_count,
        "dual_agreed_count": dual_agreed_count,
        "dual_disagreed_count": dual_disagreed_count,
        "raw_dual_agreement_rate": (
            round(dual_agreed_count / dual_annotated_count, 4) if dual_annotated_count else None
        ),
        "adjudicated_count": adjudicated_count,
        "published_benchmark_count": published_benchmark_count,
        "resolved_disagreement_count": resolved_disagreement_count,
        "unresolved_disagreement_count": unresolved_disagreement_count,
        "disagreement_case_ids": disagreement_case_ids,
        "unresolved_disagreement_case_ids": unresolved_disagreement_case_ids,
        "dual_label_pair_counts": dict(sorted(dual_label_pair_counts.items())),
        "dual_disagreement_label_pair_counts": dict(sorted(dual_disagreement_label_pair_counts.items())),
        "supported_disagreement_count": len(supported_disagreement_case_ids),
        "supported_disagreement_case_ids": supported_disagreement_case_ids,
    }


def _label_pair_key(left: str, right: str) -> str:
    labels = sorted(
        [left, right],
        key=lambda label: (SUPPORT_LABEL_RANK.get(label, len(SUPPORT_LABEL_RANK)), label),
    )
    return f"{labels[0]}|{labels[1]}"
