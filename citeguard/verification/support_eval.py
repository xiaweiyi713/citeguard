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

SUPPORT_LABEL_ORDER = (
    "supported",
    "weakly_supported",
    "insufficient_evidence",
    "contradicted",
)
SUPPORT_LABEL_RANK = {label: index for index, label in enumerate(SUPPORT_LABEL_ORDER)}

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

ALLOWED_SET_CASE_TYPES = {
    "set_aggregation",
    "weak_set_boundary",
    "contradiction_set",
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

REQUIRED_TEST_CASE_TYPES = {
    "weak_support",
    "hard_negative",
    "contradiction",
    "full_text_required",
}

REQUIRED_TEST_GOLD_LABELS = set(ALLOWED_SUPPORT_LABELS)

REQUIRED_SET_CASE_TYPES = set(ALLOWED_SET_CASE_TYPES)

REQUIRED_SET_TEST_CASE_TYPES = {
    "weak_set_boundary",
    "contradiction_set",
}

REQUIRED_SET_GOLD_LABELS = set(ALLOWED_SUPPORT_LABELS)

HIGH_RISK_SUPPORT_CASE_TYPES = {
    "contradiction",
    "contradiction_set",
    "hard_negative",
    "full_text_required",
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
    languages = set()
    label_sources = set()
    splits = set()
    test_case_types = set()
    test_evidence_scopes = set()
    test_gold_labels = set()
    test_languages = set()
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
        lang = str(case.get("lang", "")).strip()
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
        if lang:
            languages.add(lang)
        if scope:
            evidence_scopes.add(scope)
        if case_type:
            case_types.add(case_type)
        if split:
            splits.add(split)
        if split == "test":
            if gold:
                test_gold_labels.add(gold)
            if lang:
                test_languages.add(lang)
            if scope:
                test_evidence_scopes.add(scope)
            if case_type:
                test_case_types.add(case_type)

        if case_type in {"hard_negative", "full_text_required", "weak_support", "contradiction"} and not notes:
            notes_missing_for_risky_cases.append(case_id or str(index))

    missing_case_types = sorted(REQUIRED_SEED_CASE_TYPES - case_types)
    missing_scopes = sorted(REQUIRED_SEED_EVIDENCE_SCOPES - evidence_scopes)
    missing_labels = sorted(ALLOWED_SUPPORT_LABELS - gold_labels)
    missing_splits = sorted(ALLOWED_SPLITS - splits)
    missing_test_case_types = sorted(REQUIRED_TEST_CASE_TYPES - test_case_types)
    missing_test_labels = sorted(REQUIRED_TEST_GOLD_LABELS - test_gold_labels)
    if missing_case_types:
        errors.append(f"dataset is missing required case_type coverage: {', '.join(missing_case_types)}")
    if missing_scopes:
        errors.append(f"dataset is missing required evidence_scope coverage: {', '.join(missing_scopes)}")
    if missing_labels:
        errors.append(f"dataset is missing required gold label coverage: {', '.join(missing_labels)}")
    if missing_splits:
        errors.append(f"dataset is missing required split coverage: {', '.join(missing_splits)}")
    if missing_test_case_types:
        errors.append(
            "test split is missing required high-risk case_type coverage: "
            + ", ".join(missing_test_case_types)
        )
    if missing_test_labels:
        errors.append(f"test split is missing required gold label coverage: {', '.join(missing_test_labels)}")
    if notes_missing_for_risky_cases:
        warnings.append(
            "risky cases should explain label rationale in label_notes: "
            + ", ".join(notes_missing_for_risky_cases)
        )

    raw_set_cases = data.get("set_cases", [])
    set_case_splits = set()
    set_case_types = set()
    set_gold_labels = set()
    set_test_case_types = set()
    set_test_gold_labels = set()
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
        if case_type and case_type not in ALLOWED_SET_CASE_TYPES:
            errors.append(f"set_case {case_id or index} has unsupported case_type {case_type!r}")
        if case_type:
            set_case_types.add(case_type)
        if split:
            set_case_splits.add(split)
        if gold:
            set_gold_labels.add(gold)
        if split == "test":
            if case_type:
                set_test_case_types.add(case_type)
            if gold:
                set_test_gold_labels.add(gold)
        if label_source:
            label_sources.add(label_source)
        if case_type == "weak_set_boundary" and not notes:
            warnings.append(f"set_case {case_id or index} should explain weak aggregation boundary in label_notes")

    missing_set_case_types = sorted(REQUIRED_SET_CASE_TYPES - set_case_types)
    missing_set_test_case_types = sorted(REQUIRED_SET_TEST_CASE_TYPES - set_test_case_types)
    missing_set_gold_labels = sorted(REQUIRED_SET_GOLD_LABELS - set_gold_labels)
    if missing_set_case_types:
        errors.append(f"set_cases are missing required case_type coverage: {', '.join(missing_set_case_types)}")
    if missing_set_test_case_types:
        errors.append(
            "set_cases test split is missing required case_type coverage: "
            + ", ".join(missing_set_test_case_types)
        )
    if missing_set_gold_labels:
        errors.append(f"set_cases are missing required gold label coverage: {', '.join(missing_set_gold_labels)}")

    summary = {
        "ok": not errors,
        "schema_version": schema_version,
        "n": len(raw_cases),
        "case_types": {case_type: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("case_type") == case_type) for case_type in sorted(case_types)},
        "evidence_scopes": {scope: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("evidence_scope") == scope) for scope in sorted(evidence_scopes)},
        "gold_labels": {label: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("gold") == label) for label in sorted(gold_labels)},
        "languages": {lang: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("lang") == lang) for lang in sorted(languages)},
        "splits": {split: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("split") == split) for split in sorted(splits)},
        "test_split": {
            "case_types": {
                case_type: sum(
                    1
                    for case in raw_cases
                    if isinstance(case, dict)
                    and case.get("split") == "test"
                    and case.get("case_type") == case_type
                )
                for case_type in sorted(test_case_types)
            },
            "evidence_scopes": {
                scope: sum(
                    1
                    for case in raw_cases
                    if isinstance(case, dict)
                    and case.get("split") == "test"
                    and case.get("evidence_scope") == scope
                )
                for scope in sorted(test_evidence_scopes)
            },
            "gold_labels": {
                label: sum(
                    1
                    for case in raw_cases
                    if isinstance(case, dict)
                    and case.get("split") == "test"
                    and case.get("gold") == label
                )
                for label in sorted(test_gold_labels)
            },
            "languages": {
                lang: sum(
                    1
                    for case in raw_cases
                    if isinstance(case, dict)
                    and case.get("split") == "test"
                    and case.get("lang") == lang
                )
                for lang in sorted(test_languages)
            },
            "required_case_types": sorted(REQUIRED_TEST_CASE_TYPES),
            "required_gold_labels": sorted(REQUIRED_TEST_GOLD_LABELS),
        },
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
            "gold_labels": {
                label: sum(1 for case in raw_set_cases if isinstance(case, dict) and case.get("gold") == label)
                for label in sorted(set_gold_labels)
            },
            "test_split": {
                "case_types": {
                    case_type: sum(
                        1
                        for case in raw_set_cases
                        if isinstance(case, dict)
                        and case.get("split") == "test"
                        and case.get("case_type") == case_type
                    )
                    for case_type in sorted(set_test_case_types)
                },
                "gold_labels": {
                    label: sum(
                        1
                        for case in raw_set_cases
                        if isinstance(case, dict)
                        and case.get("split") == "test"
                        and case.get("gold") == label
                    )
                    for label in sorted(set_test_gold_labels)
                },
            },
            "required_case_types": sorted(REQUIRED_SET_CASE_TYPES),
            "required_test_case_types": sorted(REQUIRED_SET_TEST_CASE_TYPES),
            "required_gold_labels": sorted(REQUIRED_SET_GOLD_LABELS),
        },
        "label_sources": sorted(label_sources),
        "label_source_counts": {
            source: sum(
                1
                for case in [*raw_cases, *raw_set_cases]
                if isinstance(case, dict) and case.get("label_source") == source
            )
            for source in sorted(label_sources)
        },
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
        case = case_by_id.get(case_id)
        label_source = (case.label_source.strip() if case else "") or "unknown"
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
            "full_text_required_unreviewed_case_ids": list(
                full_text_required_review.get("unreviewed_case_ids", [])
            ),
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
            "sidecar_provenance_complete_count": _safe_int(
                sidecar_case_provenance.get("complete_count", 0)
            ),
            "sidecar_provenance_complete_fraction": _safe_float(
                sidecar_case_provenance.get("complete_fraction", 0.0)
            ),
            "sidecar_provenance_missing_count": _safe_int(sidecar_case_provenance.get("missing_count", 0)),
            "sidecar_provenance_missing_case_ids": list(
                sidecar_case_provenance.get("missing_case_ids", [])
            ),
            "sidecar_provenance_missing_case_ids_by_field": {
                str(field): list(case_ids or [])
                for field, case_ids in (
                    sidecar_case_provenance.get("missing_case_ids_by_field", {}) or {}
                ).items()
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
    return {
        outer_key: dict(sorted(inner_counts.items()))
        for outer_key, inner_counts in sorted(counts.items())
    }


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
            str(item.get("case_id", ""))
            for item in review_queue[:10]
            if isinstance(item, dict) and item.get("case_id")
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

    quality_ok = quality.get("ok") if isinstance(quality, dict) else None
    label_gate_ok = label_gate.get("ok") if isinstance(label_gate, dict) else None
    review_required_count = int(release_blockers.get("review_required_count", 0) or 0)
    release_blocked = bool(release_blockers.get("release_blocked"))
    supported_acceptance_ok = bool(acceptance_guard.get("ok_to_accept_supported", True))
    supported_acceptance_review = int(acceptance_guard.get("review_before_accepting_count", 0) or 0)

    if quality_ok is False or label_gate_ok is False or release_blocked:
        status = "blocked"
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
        "benchmark_claim_safe": bool(release_blockers.get("benchmark_claim_safe", False)),
        "ok_to_accept_supported": supported_acceptance_ok,
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
        "label_maturity": _support_release_label_maturity_summary(label_sidecar, label_gate),
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
        "sidecar_provenance_complete_fraction": float(
            metrics.get("sidecar_provenance_complete_fraction", 0.0) or 0.0
        ),
    }


def compute_support_report(
    cases: List[SupportCase], predictions: List[str], backend_name: str = ""
) -> Dict[str, Any]:
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
    blocking_items = [
        item
        for item in valid_items
        if str(item.get("severity", "")) in blocking_severities
    ]
    review_required_items = [
        item
        for item in valid_items
        if str(item.get("severity", "")) in {"critical", "high", "medium"}
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
    return [
        str(item.get("case_id", ""))
        for item in items
        if isinstance(item, dict) and item.get("case_id")
    ]


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

    slice_specs = [
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
            "predicate": lambda case: case.case_type == "full_text_required"
            or case.evidence_scope in {"full_text", "mixed_with_full_text"},
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

    rows = []
    for spec in slice_specs:
        pairs = [
            (case, prediction)
            for case, prediction in zip(cases, predictions)
            if spec["predicate"](case)
        ]
        false_case_ids = [
            case.case_id
            for case, prediction in pairs
            if prediction == "supported" and case.gold != "supported"
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

    phases = [
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

    slice_specs = [
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
            "predicate": lambda item: item.get("case_type") == "full_text_required"
            or item.get("evidence_scope") in {"full_text", "mixed_with_full_text"},
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

    slices = []
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
            "incorrect_abstention": sum(
                1 for item in grouped[key] if item.get("bucket") == "incorrect_abstention"
            ),
            "correct_abstention": sum(
                1 for item in grouped[key] if item.get("bucket") == "correct_abstention"
            ),
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
        1 for gold, pred in preds if pred in ("supported", "weakly_supported") and gold not in ("supported", "weakly_supported")
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
