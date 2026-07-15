"""Offline evaluation of claim-support assessment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List


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
            "test split is missing required high-risk case_type coverage: " + ", ".join(missing_test_case_types)
        )
    if missing_test_labels:
        errors.append(f"test split is missing required gold label coverage: {', '.join(missing_test_labels)}")
    if notes_missing_for_risky_cases:
        warnings.append(
            "risky cases should explain label rationale in label_notes: " + ", ".join(notes_missing_for_risky_cases)
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
            "set_cases test split is missing required case_type coverage: " + ", ".join(missing_set_test_case_types)
        )
    if missing_set_gold_labels:
        errors.append(f"set_cases are missing required gold label coverage: {', '.join(missing_set_gold_labels)}")

    summary = {
        "ok": not errors,
        "schema_version": schema_version,
        "n": len(raw_cases),
        "case_types": {
            case_type: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("case_type") == case_type)
            for case_type in sorted(case_types)
        },
        "evidence_scopes": {
            scope: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("evidence_scope") == scope)
            for scope in sorted(evidence_scopes)
        },
        "gold_labels": {
            label: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("gold") == label)
            for label in sorted(gold_labels)
        },
        "languages": {
            lang: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("lang") == lang)
            for lang in sorted(languages)
        },
        "splits": {
            split: sum(1 for case in raw_cases if isinstance(case, dict) and case.get("split") == split)
            for split in sorted(splits)
        },
        "test_split": {
            "case_types": {
                case_type: sum(
                    1
                    for case in raw_cases
                    if isinstance(case, dict) and case.get("split") == "test" and case.get("case_type") == case_type
                )
                for case_type in sorted(test_case_types)
            },
            "evidence_scopes": {
                scope: sum(
                    1
                    for case in raw_cases
                    if isinstance(case, dict) and case.get("split") == "test" and case.get("evidence_scope") == scope
                )
                for scope in sorted(test_evidence_scopes)
            },
            "gold_labels": {
                label: sum(
                    1
                    for case in raw_cases
                    if isinstance(case, dict) and case.get("split") == "test" and case.get("gold") == label
                )
                for label in sorted(test_gold_labels)
            },
            "languages": {
                lang: sum(
                    1
                    for case in raw_cases
                    if isinstance(case, dict) and case.get("split") == "test" and case.get("lang") == lang
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
                        if isinstance(case, dict) and case.get("split") == "test" and case.get("case_type") == case_type
                    )
                    for case_type in sorted(set_test_case_types)
                },
                "gold_labels": {
                    label: sum(
                        1
                        for case in raw_set_cases
                        if isinstance(case, dict) and case.get("split") == "test" and case.get("gold") == label
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


# Compatibility facade: implementations live in focused modules, while this
# module preserves the established import surface.
from .support_eval_labels import *  # noqa: E402,F401,F403
from .support_eval_label_gate import *  # noqa: E402,F401,F403
from .support_eval_review import *  # noqa: E402,F401,F403
from .support_eval_metrics import *  # noqa: E402,F401,F403
from .support_eval_execution import *  # noqa: E402,F401,F403
