"""Offline evaluation of claim-support assessment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from citeguard.graph import CitationRecord
from citeguard.verifiers import SupportBackend

from .support import assess_support


ALLOWED_ADJUDICATION_STATUSES = {
    "not_human_reviewed",
    "single_annotator",
    "dual_annotator_agreed",
    "dual_annotator_adjudicated",
    "published_benchmark",
}

ALLOWED_SUPPORT_LABELS = {
    "supported",
    "weakly_supported",
    "insufficient_evidence",
    "contradicted",
}

ALLOWED_EVIDENCE_SCOPES = {
    "title",
    "abstract",
    "metadata",
    "metadata_snippet",
    "full_text",
    "mixed",
    "mixed_with_full_text",
    "none",
}

ALLOWED_CASE_TYPES = {
    "direct_support",
    "weak_support",
    "hard_negative",
    "unrelated_negative",
    "contradiction",
    "metadata_only",
    "full_text_required",
    "standard",
}

ALLOWED_SPLITS = {
    "train",
    "dev",
    "test",
}

REQUIRED_SEED_CASE_TYPES = {
    "direct_support",
    "weak_support",
    "hard_negative",
    "unrelated_negative",
    "contradiction",
    "full_text_required",
}

REQUIRED_SEED_EVIDENCE_SCOPES = {
    "title",
    "abstract",
    "metadata_snippet",
    "full_text",
}


class SupportEvalValidationError(ValueError):
    """Raised when a support eval dataset violates the benchmark contract."""


class SupportLabelSidecarValidationError(ValueError):
    """Raised when support label provenance sidecar metadata is invalid."""


@dataclass(frozen=True)
class SupportCase:
    case_id: str
    claim: str
    evidence: str
    gold: str
    lang: str = ""
    evidence_scope: str = "abstract"
    label_source: str = "synthetic"
    label_notes: str = ""
    case_type: str = "standard"
    split: str = "test"


@dataclass(frozen=True)
class SupportSetCase:
    case_id: str
    claim: str
    citation_verdicts: List[str]
    gold: str
    lang: str = ""
    label_source: str = "synthetic"
    label_notes: str = ""
    case_type: str = "set_aggregation"
    split: str = "test"


@dataclass(frozen=True)
class SupportLabelProvenance:
    case_id: str
    adjudication_status: str
    annotator_count: int
    annotator_labels: List[str]
    adjudicated_label: str
    disagreement: str = "none"
    adjudicator: str = ""
    source_locator: str = ""
    notes: str = ""


def load_support_eval(path: str) -> List[SupportCase]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    validate_support_eval_dataset(data)
    return [
        SupportCase(
            c["id"],
            c["claim"],
            c["evidence"],
            c["gold"],
            c.get("lang", ""),
            c.get("evidence_scope", "abstract"),
            c.get("label_source", "synthetic"),
            c.get("label_notes", ""),
            c.get("case_type", "standard"),
            c.get("split", "test"),
        )
        for c in data["cases"]
    ]


def load_support_set_eval(path: str) -> List[SupportSetCase]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    validate_support_eval_dataset(data)
    return [
        SupportSetCase(
            c["id"],
            c["claim"],
            [str(verdict) for verdict in c["citation_verdicts"]],
            c["gold"],
            c.get("lang", ""),
            c.get("label_source", "synthetic"),
            c.get("label_notes", ""),
            c.get("case_type", "set_aggregation"),
            c.get("split", "test"),
        )
        for c in data.get("set_cases", [])
    ]


def load_support_label_cases(path: str) -> List[SupportCase]:
    """Return all dataset cases that need label provenance sidecar coverage."""

    cases = load_support_eval(path)
    cases.extend(support_set_case_to_label_case(case) for case in load_support_set_eval(path))
    return cases


def support_set_case_to_label_case(case: SupportSetCase) -> SupportCase:
    return SupportCase(
        case.case_id,
        case.claim,
        "citation_verdicts: " + ", ".join(case.citation_verdicts),
        case.gold,
        lang=case.lang,
        evidence_scope="mixed",
        label_source=case.label_source,
        label_notes=case.label_notes,
        case_type=case.case_type,
        split=case.split,
    )


def validate_support_eval_dataset(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate benchmark schema, provenance, and minimum coverage."""

    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(data, dict):
        raise SupportEvalValidationError("support eval dataset must be a JSON object")
    schema_version = data.get("schema_version")
    if schema_version != 2:
        errors.append("schema_version must be 2")
    label_policy = data.get("label_policy")
    if not isinstance(label_policy, dict):
        errors.append("label_policy must be an object")
    else:
        if not str(label_policy.get("label_source", "")).strip():
            errors.append("label_policy.label_source is required")
        if not str(label_policy.get("notes", "")).strip():
            errors.append("label_policy.notes is required")

    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        errors.append("cases must be a non-empty list")
        raw_cases = []

    seen_ids = set()
    case_types = set()
    evidence_scopes = set()
    gold_labels = set()
    label_sources = set()
    splits = set()
    notes_missing_for_risky_cases: List[str] = []
    for index, case in enumerate(raw_cases, start=1):
        if not isinstance(case, dict):
            errors.append(f"case {index} must be an object")
            continue

        case_id = str(case.get("id", "")).strip()
        if not case_id:
            errors.append(f"case {index} id is required")
        elif case_id in seen_ids:
            errors.append(f"case id {case_id!r} is duplicated")
        seen_ids.add(case_id)

        for field in ("claim", "evidence", "gold", "lang", "evidence_scope", "label_source", "case_type", "split"):
            if not str(case.get(field, "")).strip():
                errors.append(f"case {case_id or index} field {field!r} is required")

        gold = str(case.get("gold", "")).strip()
        scope = str(case.get("evidence_scope", "")).strip()
        case_type = str(case.get("case_type", "")).strip()
        label_source = str(case.get("label_source", "")).strip()
        split = str(case.get("split", "")).strip()
        notes = str(case.get("label_notes", "")).strip()

        if gold and gold not in ALLOWED_SUPPORT_LABELS:
            errors.append(f"case {case_id or index} has unsupported gold label {gold!r}")
        if scope and scope not in ALLOWED_EVIDENCE_SCOPES:
            errors.append(f"case {case_id or index} has unsupported evidence_scope {scope!r}")
        if case_type and case_type not in ALLOWED_CASE_TYPES:
            errors.append(f"case {case_id or index} has unsupported case_type {case_type!r}")
        if split and split not in ALLOWED_SPLITS:
            errors.append(f"case {case_id or index} has unsupported split {split!r}")
        if label_source:
            label_sources.add(label_source)
        if gold:
            gold_labels.add(gold)
        if scope:
            evidence_scopes.add(scope)
        if case_type:
            case_types.add(case_type)
        if split:
            splits.add(split)

        if case_type in {"hard_negative", "full_text_required", "weak_support", "contradiction"} and not notes:
            notes_missing_for_risky_cases.append(case_id or str(index))

    missing_case_types = sorted(REQUIRED_SEED_CASE_TYPES - case_types)
    missing_scopes = sorted(REQUIRED_SEED_EVIDENCE_SCOPES - evidence_scopes)
    missing_labels = sorted(ALLOWED_SUPPORT_LABELS - gold_labels)
    missing_splits = sorted(ALLOWED_SPLITS - splits)
    if missing_case_types:
        errors.append(f"dataset is missing required case_type coverage: {', '.join(missing_case_types)}")
    if missing_scopes:
        errors.append(f"dataset is missing required evidence_scope coverage: {', '.join(missing_scopes)}")
    if missing_labels:
        errors.append(f"dataset is missing required gold label coverage: {', '.join(missing_labels)}")
    if missing_splits:
        errors.append(f"dataset is missing required split coverage: {', '.join(missing_splits)}")
    if notes_missing_for_risky_cases:
        warnings.append(
            "risky cases should explain label rationale in label_notes: "
            + ", ".join(notes_missing_for_risky_cases)
        )

    raw_set_cases = data.get("set_cases", [])
    set_case_splits = set()
    set_case_types = set()
    if raw_set_cases is None:
        raw_set_cases = []
    if not isinstance(raw_set_cases, list):
        errors.append("set_cases must be a list when provided")
        raw_set_cases = []
    for index, case in enumerate(raw_set_cases, start=1):
        if not isinstance(case, dict):
            errors.append(f"set_case {index} must be an object")
            continue
        case_id = str(case.get("id", "")).strip()
        if not case_id:
            errors.append(f"set_case {index} id is required")
        elif case_id in seen_ids:
            errors.append(f"case id {case_id!r} is duplicated")
        seen_ids.add(case_id)

        for field in ("claim", "gold", "lang", "label_source", "case_type", "split"):
            if not str(case.get(field, "")).strip():
                errors.append(f"set_case {case_id or index} field {field!r} is required")

        citation_verdicts = case.get("citation_verdicts")
        if not isinstance(citation_verdicts, list) or not citation_verdicts:
            errors.append(f"set_case {case_id or index} citation_verdicts must be a non-empty list")
            citation_verdicts = []
        for verdict in citation_verdicts:
            if verdict not in ALLOWED_SUPPORT_LABELS:
                errors.append(f"set_case {case_id or index} has unsupported citation verdict {verdict!r}")

        gold = str(case.get("gold", "")).strip()
        split = str(case.get("split", "")).strip()
        case_type = str(case.get("case_type", "")).strip()
        label_source = str(case.get("label_source", "")).strip()
        notes = str(case.get("label_notes", "")).strip()
        if gold and gold not in ALLOWED_SUPPORT_LABELS:
            errors.append(f"set_case {case_id or index} has unsupported gold label {gold!r}")
        if split and split not in ALLOWED_SPLITS:
            errors.append(f"set_case {case_id or index} has unsupported split {split!r}")
        if case_type:
            set_case_types.add(case_type)
        if split:
            set_case_splits.add(split)
        if label_source:
            label_sources.add(label_source)
        if case_type == "weak_set_boundary" and not notes:
            warnings.append(f"set_case {case_id or index} should explain weak aggregation boundary in label_notes")

    summary = {
        "ok": not errors,
        "schema_version": schema_version,
        "n": len(raw_cases),
        "case_types": {case_type: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("case_type") == case_type) for case_type in sorted(case_types)},
        "evidence_scopes": {scope: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("evidence_scope") == scope) for scope in sorted(evidence_scopes)},
        "gold_labels": {label: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("gold") == label) for label in sorted(gold_labels)},
        "splits": {split: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("split") == split) for split in sorted(splits)},
        "set_cases": {
            "n": len(raw_set_cases),
            "case_types": {
                case_type: sum(
                    1 for case in raw_set_cases if isinstance(case, dict) and case.get("case_type") == case_type
                )
                for case_type in sorted(set_case_types)
            },
            "splits": {
                split: sum(1 for case in raw_set_cases if isinstance(case, dict) and case.get("split") == split)
                for split in sorted(set_case_splits)
            },
        },
        "label_sources": sorted(label_sources),
        "warnings": warnings,
    }
    if errors:
        raise SupportEvalValidationError("; ".join(errors))
    return summary


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
    return {
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


def validate_support_label_sidecar(data: Dict[str, Any], cases: List[SupportCase]) -> Dict[str, Any]:
    """Validate optional sidecar metadata for human review and adjudication."""

    errors: List[str] = []
    warnings: List[str] = []
    if not isinstance(data, dict):
        raise SupportLabelSidecarValidationError("support label sidecar must be a JSON object")
    if data.get("schema_version") != 1:
        errors.append("schema_version must be 1")

    case_ids = {case.case_id for case in cases}
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
        "warnings": warnings,
    }
    if errors:
        raise SupportLabelSidecarValidationError("; ".join(errors))
    return summary


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
            errors.append(f"sidecar case {case_id} dual_annotator_adjudicated requires at least two distinct annotator labels")
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
            dual_annotated_count += 1
            if len({str(label) for label in annotator_labels}) == 1:
                dual_agreed_count += 1
            else:
                dual_disagreed_count += 1
                if case_id:
                    disagreement_case_ids.append(case_id)

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
            round(dual_agreed_count / dual_annotated_count, 4)
            if dual_annotated_count
            else None
        ),
        "adjudicated_count": adjudicated_count,
        "published_benchmark_count": published_benchmark_count,
        "resolved_disagreement_count": resolved_disagreement_count,
        "unresolved_disagreement_count": unresolved_disagreement_count,
        "disagreement_case_ids": disagreement_case_ids,
        "unresolved_disagreement_case_ids": unresolved_disagreement_case_ids,
    }


def compute_support_label_sidecar_gate(
    summary: Dict[str, Any],
    min_coverage: float = 1.0,
    min_human_reviewed: int = 0,
    min_dual_annotated: int = 0,
    max_unresolved_disagreements: int = 0,
    min_raw_dual_agreement_rate: Optional[float] = None,
) -> Dict[str, Any]:
    """Evaluate provenance sidecar coverage gates from a validation summary."""

    coverage = _safe_float(summary.get("coverage", 0.0))
    human_reviewed = _safe_int(summary.get("human_reviewed", 0))
    maturity = summary.get("label_maturity", {})
    if not isinstance(maturity, dict):
        maturity = {}
    dual_annotated = _safe_int(maturity.get("dual_annotated_count", 0))
    unresolved_disagreements = _safe_int(maturity.get("unresolved_disagreement_count", 0))
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
    return {
        "ok": not failures,
        "thresholds": {
            "min_coverage": min_coverage,
            "min_human_reviewed": min_human_reviewed,
            "min_dual_annotated": min_dual_annotated,
            "max_unresolved_disagreements": max_unresolved_disagreements,
            "min_raw_dual_agreement_rate": min_raw_dual_agreement_rate,
        },
        "metrics": {
            "coverage": coverage,
            "human_reviewed": human_reviewed,
            "dual_annotated": dual_annotated,
            "unresolved_disagreements": unresolved_disagreements,
            "raw_dual_agreement_rate": raw_dual_agreement_rate,
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
            "splits": _count_by_attr(cases, "split"),
            "gold_labels": {label: sum(1 for case in cases if case.gold == label) for label in sorted(ALLOWED_SUPPORT_LABELS)},
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
            "supported_precision": supported_precision,
            "contradiction_recall": contradiction_recall,
        },
        "failures": failures,
        "warnings": warnings,
    }


def compute_support_report(
    cases: List[SupportCase], predictions: List[str], backend_name: str = ""
) -> Dict[str, Any]:
    if len(cases) != len(predictions):
        raise ValueError("cases and predictions must have the same length")

    overall_preds = [(case.gold, pred) for case, pred in zip(cases, predictions)]
    error_buckets = compute_support_error_buckets(cases, predictions)
    error_bucket_counts = {key: len(items) for key, items in error_buckets.items()}
    return {
        "dataset": summarize_support_cases(cases),
        "overall": compute_support_metrics(overall_preds),
        "confusion_matrix": compute_support_confusion_matrix(overall_preds),
        "by_case_type": _compute_grouped_metrics(cases, predictions, "case_type"),
        "by_evidence_scope": _compute_grouped_metrics(cases, predictions, "evidence_scope"),
        "by_split": _compute_grouped_metrics(cases, predictions, "split"),
        "error_bucket_counts": error_bucket_counts,
        "error_buckets": error_buckets,
        "false_support_analysis": compute_false_support_analysis(error_buckets),
        "diagnostics": compute_support_diagnostics(cases, predictions, backend_name=backend_name),
        "cases": [
            {
                "case_id": case.case_id,
                "gold": case.gold,
                "predicted": pred,
                "correct": case.gold == pred,
                "case_type": case.case_type,
                "evidence_scope": case.evidence_scope,
                "split": case.split,
                "label_source": case.label_source,
            }
            for case, pred in zip(cases, predictions)
        ],
    }


def compute_false_support_analysis(error_buckets: Dict[str, List[Dict[str, str]]]) -> Dict[str, Any]:
    """Summarize the highest-risk support overcalls for release triage."""

    false_items = list(error_buckets.get("false_support", []))
    weak_items = list(error_buckets.get("weak_false_support", []))
    items = [dict(item, bucket="false_support") for item in false_items]
    items.extend(dict(item, bucket="weak_false_support") for item in weak_items)
    return {
        "false_support_count": len(false_items),
        "weak_false_support_count": len(weak_items),
        "total_overcall_count": len(items),
        "case_ids": [item["case_id"] for item in items],
        "high_risk_case_ids": [item["case_id"] for item in false_items],
        "by_case_type": _false_support_group_summary(items, "case_type"),
        "by_evidence_scope": _false_support_group_summary(items, "evidence_scope"),
        "by_split": _false_support_group_summary(items, "split"),
        "interpretation": (
            "False-support overcalls are the highest-risk support failures. "
            "Review these cases before relaxing support thresholds or shipping a support backend."
        ),
    }


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
        }
        for key in sorted(grouped)
    }


def summarize_support_cases(cases: List[SupportCase]) -> Dict[str, Any]:
    """Return provenance and coverage counts for a support benchmark case list."""

    return {
        "n": len(cases),
        "case_types": _count_cases_by(cases, "case_type"),
        "evidence_scopes": _count_cases_by(cases, "evidence_scope"),
        "gold_labels": _count_cases_by(cases, "gold"),
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
        warnings.append(
            "At least one non-supporting case was predicted as supported or weakly_supported."
        )
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
        "split": case.split,
        "label_source": case.label_source,
    }


def compute_support_metrics(preds: List[Tuple[str, str]]) -> Dict[str, float]:
    n = len(preds)
    correct = sum(1 for gold, pred in preds if gold == pred)
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
    non_supported_total = sum(1 for gold, _ in preds if gold != "supported")
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
        "abstention_rate": round(abstentions / n, 4) if n else 0.0,
        "misjudged_support_rate": round(misjudged_support / supported_total, 4) if supported_total else 0.0,
        "contradiction_recall": round(contra_hit / contra_total, 4) if contra_total else 0.0,
    }
