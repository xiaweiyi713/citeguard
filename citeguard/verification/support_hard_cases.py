"""First real-source hard-case support slice (maintainer-reviewed, not dual-annotated)."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List, Sequence

from .support_eval import ALLOWED_CASE_TYPES, ALLOWED_SET_CASE_TYPES, ALLOWED_SPLITS, ALLOWED_SUPPORT_LABELS


HARD_CASE_DATASET_TYPE = "real_source_hard_cases"
ALLOWED_ORIGINS = {"natural_excerpt", "maintainer_perturbation"}
ALLOWED_ERROR_FAMILIES = {
    "direct_support",
    "related_not_support",
    "causal_overclaim",
    "scope_overclaim",
    "condition_omission",
    "contradiction",
    "full_text_required",
    "multi_citation_aggregation",
}
REQUIRED_ERROR_FAMILIES = set(ALLOWED_ERROR_FAMILIES)


class SupportHardCaseValidationError(ValueError):
    """Raised when the real-source hard-case slice violates its contract."""


def load_support_hard_cases(path: str) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    validate_support_hard_cases(data)
    return data


def validate_support_hard_cases(data: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    if not isinstance(data, dict):
        raise SupportHardCaseValidationError("hard-case dataset must be a JSON object")
    if data.get("dataset_type") != HARD_CASE_DATASET_TYPE:
        errors.append("dataset_type must be real_source_hard_cases")
    if int(data.get("schema_version") or 0) != 1:
        errors.append("schema_version must be 1")
    policy = data.get("label_policy")
    if not isinstance(policy, dict) or not str(policy.get("label_source") or "").strip():
        errors.append("label_policy.label_source is required")
    elif str(policy.get("label_source")) != "maintainer_reviewed":
        errors.append("this slice must be labeled maintainer_reviewed")

    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        errors.append("cases must be a non-empty list")
        cases = []
    set_cases = data.get("set_cases") if isinstance(data.get("set_cases"), list) else []

    seen_ids = set()
    paper_splits: Dict[str, set] = defaultdict(set)
    origins = set()
    families = set()
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            errors.append(f"case {index} must be an object")
            continue
        case_id = str(case.get("id") or "").strip()
        if not case_id:
            errors.append(f"case {index} id is required")
        elif case_id in seen_ids:
            errors.append(f"duplicate case id {case_id!r}")
        seen_ids.add(case_id)
        paper_id = str(case.get("paper_id") or "").strip()
        split = str(case.get("split") or "").strip()
        origin = str(case.get("origin") or "").strip()
        family = str(case.get("error_family") or "").strip()
        gold = str(case.get("gold") or "").strip()
        case_type = str(case.get("case_type") or "").strip()
        for field in (
            "claim",
            "evidence",
            "gold",
            "lang",
            "evidence_scope",
            "evidence_locator",
            "source_locator",
            "label_source",
            "case_type",
            "error_family",
            "origin",
            "split",
            "paper_id",
            "rights_basis",
            "benchmark_origin",
        ):
            if not str(case.get(field) or "").strip():
                errors.append(f"case {case_id or index} field {field!r} is required")
        if gold and gold not in ALLOWED_SUPPORT_LABELS:
            errors.append(f"case {case_id} has unsupported gold {gold!r}")
        if case_type and case_type not in ALLOWED_CASE_TYPES:
            errors.append(f"case {case_id} has unsupported case_type {case_type!r}")
        if split and split not in ALLOWED_SPLITS:
            errors.append(f"case {case_id} has unsupported split {split!r}")
        if origin and origin not in ALLOWED_ORIGINS:
            errors.append(f"case {case_id} has unsupported origin {origin!r}")
        if family and family not in ALLOWED_ERROR_FAMILIES:
            errors.append(f"case {case_id} has unsupported error_family {family!r}")
        if str(case.get("benchmark_origin") or "") != "real_source":
            errors.append(f"case {case_id} must have benchmark_origin=real_source")
        if paper_id and split:
            paper_splits[paper_id].add(split)
        if origin:
            origins.add(origin)
        if family:
            families.add(family)
        if family in {"related_not_support", "causal_overclaim", "scope_overclaim", "condition_omission"} and not str(
            case.get("label_notes") or ""
        ).strip():
            errors.append(f"case {case_id} needs label_notes explaining the perturbation")

    for case in set_cases:
        if not isinstance(case, dict):
            errors.append("set_case must be an object")
            continue
        case_id = str(case.get("id") or "").strip()
        if case_id in seen_ids:
            errors.append(f"duplicate set_case id {case_id!r}")
        seen_ids.add(case_id)
        family = str(case.get("error_family") or "multi_citation_aggregation")
        families.add(family)
        if str(case.get("case_type") or "") not in ALLOWED_SET_CASE_TYPES:
            errors.append(f"set_case {case_id} has unsupported case_type")
        papers = case.get("paper_ids")
        if not isinstance(papers, list):
            papers = []
        splits = set()
        for paper_id in papers:
            paper_split = paper_splits.get(str(paper_id), set())
            if paper_split:
                splits.update(paper_split)
        if len(splits) > 1:
            errors.append(f"set_case {case_id} mixes papers from multiple splits")

    crossed = sorted(paper_id for paper_id, splits in paper_splits.items() if len(splits) > 1)
    if crossed:
        errors.append("paper-grouped split violated for: " + ", ".join(crossed))
    missing_origin = sorted(ALLOWED_ORIGINS - origins)
    if missing_origin:
        errors.append("missing origin coverage: " + ", ".join(missing_origin))
    missing_families = sorted(REQUIRED_ERROR_FAMILIES - families)
    if missing_families:
        errors.append("missing error_family coverage: " + ", ".join(missing_families))
    if errors:
        raise SupportHardCaseValidationError("; ".join(errors))
    return data


def hard_case_split_integrity(cases: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for case in cases:
        mapping[str(case["paper_id"])] = str(case["split"])
    return mapping
