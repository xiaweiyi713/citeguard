"""Data models for claim-free citation verification."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from citeguard.graph import CitationRecord


class Verdict(str, Enum):
    """Outcome of verifying a single citation."""

    VERIFIED = "verified"
    METADATA_MISMATCH = "metadata_mismatch"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


RISK_BY_VERDICT = {
    Verdict.VERIFIED.value: ("low", 0.05, "Keep citation."),
    Verdict.METADATA_MISMATCH.value: ("medium", 0.65, "Review mismatched metadata and apply the suggested correction if appropriate."),
    Verdict.NOT_FOUND.value: ("high", 0.95, "Ask for a DOI/arXiv id or replace the citation; do not call it fabricated without human confirmation."),
    Verdict.AMBIGUOUS.value: ("high", 0.85, "Ask for a DOI/arXiv id to disambiguate."),
}

INPUT_SOURCE_METADATA_KEYS = [
    "input_source_path",
    "input_source_format",
    "input_source_type",
    "input_source_id",
    "input_source_index",
    "input_source_locator",
    "input_source_line_start",
    "input_source_line_end",
]


NEXT_ACTION_DESCRIPTIONS = {
    "continue": "Continue; no immediate remediation is required.",
    "fix_configuration": "Fix CiteGuard configuration before running the check again.",
    "provide_missing_input": "Provide required claim, citation, or file input before retrying.",
    "repair_input": "Repair malformed input, JSON, files, or CLI arguments before retrying.",
    "install_or_configure_dependency": "Install or configure a required optional dependency before retrying.",
    "keep": "Keep a verified citation.",
    "keep_claim": "Keep a claim whose citation evidence supports it.",
    "review_metadata": "Review mismatched citation metadata and the suggested correction.",
    "resolve_identifier_or_replace": "Ask for a DOI/arXiv id or replace an unverified citation.",
    "resolve_citation_identity": "Resolve citation identity before judging claim support.",
    "disambiguate_identifier": "Ask for a DOI/arXiv id or stronger metadata to disambiguate.",
    "inspect_source_health": "Inspect source health because one or more checked sources failed.",
    "retry_or_check_source_health": "Retry later or inspect source health after a source-limited result.",
    "review_counterevidence_leads": "Review counter-evidence candidates before changing the claim or citation.",
    "tighten_claim_or_inspect_full_text": "Tighten the claim or inspect full text for weak support.",
    "inspect_full_text_or_find_stronger_citation": "Inspect full text or find stronger evidence before using the claim.",
    "rewrite_or_replace_evidence": "Rewrite the claim or replace evidence because available evidence contradicts it.",
}

STABLE_NEXT_ACTIONS = frozenset(NEXT_ACTION_DESCRIPTIONS)

REVIEW_ACTION_QUEUE_KEYS = (
    "rewrite_or_replace_indexes",
    "identity_resolution_indexes",
    "metadata_review_indexes",
    "evidence_review_indexes",
    "source_retry_indexes",
    "safe_to_keep_indexes",
    "input_repair_indexes",
)

REVIEW_ACTION_QUEUE_BY_NEXT_ACTION = {
    "continue": "safe_to_keep_indexes",
    "keep": "safe_to_keep_indexes",
    "keep_claim": "safe_to_keep_indexes",
    "rewrite_or_replace_evidence": "rewrite_or_replace_indexes",
    "resolve_identifier_or_replace": "identity_resolution_indexes",
    "resolve_citation_identity": "identity_resolution_indexes",
    "disambiguate_identifier": "identity_resolution_indexes",
    "review_metadata": "metadata_review_indexes",
    "review_counterevidence_leads": "evidence_review_indexes",
    "tighten_claim_or_inspect_full_text": "evidence_review_indexes",
    "inspect_full_text_or_find_stronger_citation": "evidence_review_indexes",
    "inspect_source_health": "source_retry_indexes",
    "retry_or_check_source_health": "source_retry_indexes",
    "fix_configuration": "input_repair_indexes",
    "provide_missing_input": "input_repair_indexes",
    "repair_input": "input_repair_indexes",
    "install_or_configure_dependency": "input_repair_indexes",
}

REVIEW_NEXT_STEP_SPECS = (
    {
        "action": "repair_input",
        "queue": "input_repair_indexes",
        "priority": 1,
    },
    {
        "action": "rewrite_or_replace_evidence",
        "queue": "rewrite_or_replace_indexes",
        "priority": 2,
    },
    {
        "action": "resolve_identity",
        "queue": "identity_resolution_indexes",
        "priority": 3,
    },
    {
        "action": "retry_or_check_source_health",
        "queue": "source_retry_indexes",
        "priority": 4,
    },
    {
        "action": "review_metadata",
        "queue": "metadata_review_indexes",
        "priority": 5,
    },
    {
        "action": "review_evidence",
        "queue": "evidence_review_indexes",
        "priority": 6,
    },
    {
        "action": "keep",
        "queue": "safe_to_keep_indexes",
        "priority": 7,
    },
)


def stable_next_action(action: str) -> str:
    """Validate and return a stable next-action value."""

    if action not in STABLE_NEXT_ACTIONS:
        raise ValueError(f"unknown next_action: {action}")
    return action


NEXT_ACTION_BY_VERDICT = {
    Verdict.VERIFIED.value: stable_next_action("keep"),
    Verdict.METADATA_MISMATCH.value: stable_next_action("review_metadata"),
    Verdict.NOT_FOUND.value: stable_next_action("resolve_identifier_or_replace"),
    Verdict.AMBIGUOUS.value: stable_next_action("disambiguate_identifier"),
}


def verification_next_action(
    verdict: Verdict,
    source_failure_mode: str = "none",
    sources_failed: Optional[List[str]] = None,
) -> str:
    """Return a stable machine action for a single verification result."""

    if source_failure_mode == "all_sources_failed":
        return stable_next_action("retry_or_check_source_health")
    if verdict == Verdict.VERIFIED and sources_failed:
        return stable_next_action("inspect_source_health")
    return NEXT_ACTION_BY_VERDICT[verdict.value]


@dataclass(frozen=True)
class FieldDiff:
    """Per-field comparison between the input citation and the canonical record."""

    field: str
    candidate: Any
    canonical: Any
    matches: bool


@dataclass(frozen=True)
class VerificationResult:
    """Result of verifying one citation."""

    verdict: Verdict
    confidence: float
    input_citation: CitationRecord
    canonical_record: Optional[CitationRecord]
    field_diffs: List[FieldDiff]
    suggested_citation: str
    explanation: str
    sources_checked: List[str]
    sources_responded: List[str]
    sources_failed: List[str] = field(default_factory=list)
    source_failure_details: List[Dict[str, Any]] = field(default_factory=list)
    source_failure_mode: str = "none"
    outage_limited: bool = False
    alternatives: List[CitationRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 4),
            "input": asdict(self.input_citation),
            "canonical_record": asdict(self.canonical_record) if self.canonical_record else None,
            "canonical_metadata_quality": canonical_metadata_quality(self.canonical_record),
            "field_diffs": [asdict(diff) for diff in self.field_diffs],
            "suggested_citation": self.suggested_citation,
            "explanation": self.explanation,
            "sources_checked": list(self.sources_checked),
            "sources_responded": list(self.sources_responded),
            "sources_available": available_sources(self.sources_checked, self.sources_failed),
            "sources_failed": list(self.sources_failed),
            "source_failure_details": [dict(item) for item in self.source_failure_details],
            "source_failure_mode": self.source_failure_mode,
            "outage_limited": self.outage_limited,
            "recovery_code": verification_recovery_code(self.verdict, self.source_failure_details),
            "next_action": verification_next_action(self.verdict, self.source_failure_mode, self.sources_failed),
            "alternatives": [asdict(record) for record in self.alternatives],
        }


@dataclass(frozen=True)
class AuditReport:
    """Result of verifying a batch of citations."""

    results: List[VerificationResult]
    summary: Dict[str, int]
    risk_ranking: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": dict(self.summary),
            "review_summary": review_summary_from_risk_ranking(len(self.results), self.risk_ranking),
            "risk_ranking": [dict(item) for item in self.risk_ranking],
            "results": [result.to_dict() for result in self.results],
        }


def review_summary_from_risk_ranking(total: int, risk_ranking: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize a batch risk ranking for agent triage."""

    risk_counts: Dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    next_actions: Dict[str, int] = {}
    action_queues: Dict[str, List[int]] = {key: [] for key in REVIEW_ACTION_QUEUE_KEYS}
    for item in risk_ranking:
        risk = str(item.get("risk") or "")
        if risk:
            risk_counts[risk] = risk_counts.get(risk, 0) + 1
        next_action = str(item.get("next_action") or "")
        if next_action:
            next_actions[next_action] = next_actions.get(next_action, 0) + 1
        index = item.get("index")
        if isinstance(index, int):
            _append_review_queue_index(action_queues, next_action, index)

    top_risk_indexes = [
        item["index"]
        for item in risk_ranking[:5]
        if isinstance(item.get("index"), int)
    ]
    top_high_risk_indexes = [
        item["index"]
        for item in risk_ranking
        if item.get("risk") == "high" and isinstance(item.get("index"), int)
    ]
    medium_risk_indexes = [
        item["index"]
        for item in risk_ranking
        if item.get("risk") == "medium" and isinstance(item.get("index"), int)
    ]

    recommended_next_steps = _recommended_next_steps(action_queues)
    return {
        "total": total,
        "high_risk_count": risk_counts.get("high", 0),
        "medium_risk_count": risk_counts.get("medium", 0),
        "low_risk_count": risk_counts.get("low", 0),
        "risk_counts": risk_counts,
        "next_actions": next_actions,
        "action_queues": action_queues,
        "recommended_next_steps": recommended_next_steps,
        "suggested_fix_summary": _suggested_fix_summary(risk_ranking),
        "source_traceability": _source_traceability_summary(risk_ranking),
        "top_risk_indexes": top_risk_indexes,
        "top_high_risk_indexes": top_high_risk_indexes[:5],
        "triage_plan": _review_triage_plan(
            total=total,
            risk_counts=risk_counts,
            next_actions=next_actions,
            high_risk_indexes=top_high_risk_indexes,
            medium_risk_indexes=medium_risk_indexes,
            action_queues=action_queues,
            recommended_next_steps=recommended_next_steps,
        ),
    }


def _suggested_fix_summary(risk_ranking: List[Dict[str, Any]]) -> Dict[str, Any]:
    confirmation_required_indexes: List[int] = []
    no_confirmation_required_indexes: List[int] = []
    missing_suggested_fix_indexes: List[int] = []
    fix_kind_counts: Dict[str, int] = {}
    fix_kind_indexes: Dict[str, List[int]] = {}
    for item in risk_ranking:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if not isinstance(index, int):
            continue
        suggested_fix = item.get("suggested_fix")
        if not isinstance(suggested_fix, dict):
            missing_suggested_fix_indexes.append(index)
            continue
        kind = str(suggested_fix.get("kind") or "unknown")
        fix_kind_counts[kind] = fix_kind_counts.get(kind, 0) + 1
        fix_kind_indexes.setdefault(kind, []).append(index)
        if bool(suggested_fix.get("requires_user_confirmation")):
            confirmation_required_indexes.append(index)
        else:
            no_confirmation_required_indexes.append(index)

    confirmation_required_indexes = _unique_ints(confirmation_required_indexes)
    no_confirmation_required_indexes = _unique_ints(no_confirmation_required_indexes)
    missing_suggested_fix_indexes = _unique_ints(missing_suggested_fix_indexes)
    return {
        "schema_version": 1,
        "fix_kind_counts": dict(sorted(fix_kind_counts.items())),
        "fix_kind_indexes": {key: _unique_ints(value) for key, value in sorted(fix_kind_indexes.items())},
        "confirmation_required_count": len(confirmation_required_indexes),
        "confirmation_required_indexes": confirmation_required_indexes,
        "no_confirmation_required_indexes": no_confirmation_required_indexes,
        "missing_suggested_fix_indexes": missing_suggested_fix_indexes,
        "auto_apply_allowed": False,
        "policy": "agents_must_not_silently_apply_suggested_fixes_without_user_confirmation",
    }


def _source_traceability_summary(risk_ranking: List[Dict[str, Any]]) -> Dict[str, Any]:
    source_paths: List[str] = []
    source_formats: List[str] = []
    source_locators: List[str] = []
    source_indexes: List[int] = []
    review_required_locators: List[str] = []
    review_required_indexes: List[int] = []
    high_risk_source_indexes: List[int] = []
    source_backed_count = 0
    for item in risk_ranking:
        if not isinstance(item, dict):
            continue
        item_paths = _source_traceability_values(item, "input_source_path", "input_source_paths")
        item_formats = _source_traceability_values(item, "input_source_format", "input_source_formats")
        item_locators = _source_traceability_values(item, "input_source_locator", "input_source_locators")
        item_indexes = _source_traceability_int_values(item, "input_source_index", "input_source_indexes")
        if not (item_paths or item_formats or item_locators or item_indexes):
            continue
        source_backed_count += 1
        source_paths.extend(item_paths)
        source_formats.extend(item_formats)
        source_locators.extend(item_locators)
        source_indexes.extend(item_indexes)
        risk = str(item.get("risk") or "")
        if risk in {"high", "medium"}:
            review_required_locators.extend(item_locators)
            review_required_indexes.extend(item_indexes)
        if risk == "high":
            high_risk_source_indexes.extend(item_indexes)
    return {
        "schema_version": 1,
        "source_backed_count": source_backed_count,
        "has_source_backed_items": source_backed_count > 0,
        "source_paths": _unique_strings(source_paths),
        "source_formats": _unique_strings(source_formats),
        "source_indexes": sorted(_unique_ints(source_indexes)),
        "source_locators": _unique_strings(source_locators)[:10],
        "review_required_source_indexes": sorted(_unique_ints(review_required_indexes)),
        "review_required_source_locators": _unique_strings(review_required_locators)[:10],
        "high_risk_source_indexes": sorted(_unique_ints(high_risk_source_indexes)),
        "policy": "use_source_locators_to_repair_original_reference_items",
    }


def _source_traceability_values(item: Dict[str, Any], singular_key: str, plural_key: str) -> List[str]:
    values: List[str] = []
    singular = item.get(singular_key)
    if _is_source_traceability_value(singular):
        values.append(str(singular))
    plural = item.get(plural_key)
    if isinstance(plural, list):
        values.extend(str(value) for value in plural if _is_source_traceability_value(value))
    return values


def _is_source_traceability_value(value: Any) -> bool:
    if value in (None, ""):
        return False
    return str(value).strip().lower() != "none"


def _source_traceability_int_values(item: Dict[str, Any], singular_key: str, plural_key: str) -> List[int]:
    values: List[int] = []
    singular = item.get(singular_key)
    if isinstance(singular, int):
        values.append(singular)
    plural = item.get(plural_key)
    if isinstance(plural, list):
        values.extend(value for value in plural if isinstance(value, int))
    return values


def filter_high_risk_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return a batch payload containing only high-risk results with traceability metadata."""

    original_count = len(payload.get("results", []))
    high_risk_indexes = set()
    for item in payload.get("risk_ranking", []):
        if not isinstance(item, dict) or item.get("risk") != "high":
            continue
        index = item.get("index")
        if isinstance(index, int) and 0 <= index < original_count:
            high_risk_indexes.add(index)
    returned_indexes = [index for index in range(original_count) if index in high_risk_indexes]
    omitted_indexes = [index for index in range(original_count) if index not in high_risk_indexes]
    omitted_index_set = set(omitted_indexes)
    filtered = dict(payload)
    filtered["results"] = [
        result for index, result in enumerate(payload.get("results", [])) if index in returned_indexes
    ]
    filtered["risk_ranking"] = [
        item
        for item in payload.get("risk_ranking", [])
        if isinstance(item, dict) and item.get("index") in high_risk_indexes
    ]
    filtered["filtered"] = {
        "high_risk_only": True,
        "returned": len(filtered["results"]),
        "original_results": original_count,
        "returned_indexes": returned_indexes,
        "omitted_indexes": omitted_indexes,
        "omitted_review_summary": review_summary_from_risk_ranking(
            len(omitted_indexes),
            [
                dict(item)
                for item in payload.get("risk_ranking", [])
                if isinstance(item, dict) and item.get("index") in omitted_index_set
            ],
        ),
    }
    return filtered


def _append_review_queue_index(action_queues: Dict[str, List[int]], next_action: str, index: int) -> None:
    queue = REVIEW_ACTION_QUEUE_BY_NEXT_ACTION.get(next_action)
    if queue:
        action_queues[queue].append(index)


def _recommended_next_steps(action_queues: Dict[str, List[int]]) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []
    safe_to_keep_indexes = list(action_queues.get("safe_to_keep_indexes", []))
    for spec in REVIEW_NEXT_STEP_SPECS:
        queue = str(spec["queue"])
        if queue == "safe_to_keep_indexes":
            continue
        indexes = list(action_queues.get(queue, []))
        if not indexes:
            continue
        steps.append(
            {
                "priority": int(spec["priority"]),
                "action": str(spec["action"]),
                "queue": queue,
                "count": len(indexes),
                "indexes": indexes,
            }
        )
    return {
        "first_queue": steps[0]["queue"] if steps else "",
        "first_action": steps[0]["action"] if steps else "",
        "steps": steps,
        "safe_to_keep_count": len(safe_to_keep_indexes),
        "safe_to_keep_indexes": safe_to_keep_indexes,
    }


def _review_triage_plan(
    *,
    total: int,
    risk_counts: Dict[str, int],
    next_actions: Dict[str, int],
    high_risk_indexes: List[int],
    medium_risk_indexes: List[int],
    action_queues: Dict[str, List[int]],
    recommended_next_steps: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a compact, stable batch review plan for agents."""

    steps = [
        dict(step)
        for step in recommended_next_steps.get("steps", [])
        if isinstance(step, dict)
    ]
    review_required_indexes = _unique_ints(
        index
        for step in steps
        for index in step.get("indexes", [])
        if isinstance(step.get("indexes"), list)
    )
    status = "review_required" if review_required_indexes or risk_counts.get("high", 0) or risk_counts.get("medium", 0) else "clear"
    first_queue = str(recommended_next_steps.get("first_queue") or "")
    if status == "clear":
        first_queue = "safe_to_keep_indexes" if total else ""
    next_action = _stable_triage_next_action(
        status=status,
        total=total,
        first_queue=first_queue,
        next_actions=next_actions,
    )

    return {
        "schema_version": 1,
        "status": status,
        "next_action": next_action,
        "first_queue": first_queue,
        "review_required_indexes": review_required_indexes,
        "high_risk_indexes": list(high_risk_indexes),
        "medium_risk_indexes": list(medium_risk_indexes),
        "source_retry_indexes": list(action_queues.get("source_retry_indexes", [])),
        "safe_to_keep_indexes": list(action_queues.get("safe_to_keep_indexes", [])),
        "queue_order": [str(step.get("queue", "")) for step in steps if step.get("queue")],
        "policy": (
            "review_high_and_medium_risk_before_acceptance;"
            " source_retry_is_inconclusive_not_fabrication;"
            " safe_to_keep_only_low_risk"
        ),
    }


def _stable_triage_next_action(
    *,
    status: str,
    total: int,
    first_queue: str,
    next_actions: Dict[str, int],
) -> str:
    if status == "clear":
        return stable_next_action("keep") if total else "continue"
    for action in next_actions:
        if REVIEW_ACTION_QUEUE_BY_NEXT_ACTION.get(action) == first_queue:
            return stable_next_action(action)
    fallback_by_queue = {
        "rewrite_or_replace_indexes": "rewrite_or_replace_evidence",
        "identity_resolution_indexes": "resolve_identifier_or_replace",
        "metadata_review_indexes": "review_metadata",
        "evidence_review_indexes": "inspect_full_text_or_find_stronger_citation",
        "source_retry_indexes": "retry_or_check_source_health",
        "input_repair_indexes": "repair_input",
        "safe_to_keep_indexes": "keep",
    }
    return stable_next_action(fallback_by_queue.get(first_queue, "continue"))


def _unique_ints(indexes: Any) -> List[int]:
    seen = set()
    ordered: List[int] = []
    for index in indexes:
        if not isinstance(index, int) or index in seen:
            continue
        seen.add(index)
        ordered.append(index)
    return ordered


def _unique_strings(values: Any) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for value in values:
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        ordered.append(text)
    return ordered


def verification_risk_item(index: int, result: VerificationResult) -> Dict[str, Any]:
    level, score, recommendation = RISK_BY_VERDICT[result.verdict.value]
    next_action = verification_next_action(result.verdict, result.source_failure_mode, result.sources_failed)
    canonical = result.canonical_record
    if result.sources_failed:
        if level == "low":
            level = "medium"
        score = max(score, 0.55)
        recommendation = (
            recommendation
            + " Re-run later or inspect source health because one or more sources failed."
        )
    item = {
        "index": index,
        "verdict": result.verdict.value,
        "risk": level,
        "risk_score": round(score, 4),
        "risk_reason": verification_risk_reason(result),
        "title": result.input_citation.title,
        "doi": result.input_citation.doi,
        "arxiv_id": result.input_citation.arxiv_id,
        "mismatched_fields": [diff.field for diff in result.field_diffs if not diff.matches],
        "suggested_citation": result.suggested_citation,
        "canonical_title": canonical.title if canonical else "",
        "canonical_year": canonical.year if canonical else None,
        "canonical_venue": canonical.venue if canonical else "",
        "canonical_doi": canonical.doi if canonical else "",
        "canonical_arxiv_id": canonical.arxiv_id if canonical else "",
        "canonical_metadata_quality": canonical_metadata_quality(canonical),
        "source_metadata_missing_fields": source_metadata_missing_fields(canonical),
        "source_metadata_confidence_effect": source_metadata_confidence_effect(canonical),
        "sources_available": available_sources(result.sources_checked, result.sources_failed),
        "sources_failed": list(result.sources_failed),
        "source_failure_details": [dict(item) for item in result.source_failure_details],
        "source_failure_mode": result.source_failure_mode,
        "outage_limited": result.outage_limited,
        "recovery_code": verification_recovery_code(result.verdict, result.source_failure_details),
        "next_action": next_action,
        "suggested_fix": verification_suggested_fix(result, next_action),
        "recommendation": recommendation,
    }
    item.update(input_source_provenance(result.input_citation))
    return item


def verification_risk_reason(result: VerificationResult) -> str:
    """Return a compact stable reason for citation-audit risk tables."""

    if result.source_failure_mode == "all_sources_failed":
        return "all_sources_failed"
    if result.verdict == Verdict.VERIFIED and result.sources_failed:
        return "partial_source_failure"
    if result.verdict == Verdict.VERIFIED:
        return "metadata_verified"
    if result.verdict == Verdict.METADATA_MISMATCH:
        return "metadata_fields_mismatch"
    if result.verdict == Verdict.AMBIGUOUS:
        return "multiple_plausible_matches"
    if result.verdict == Verdict.NOT_FOUND:
        return "no_strong_match"
    return "unknown"


def verification_suggested_fix(result: VerificationResult, next_action: str) -> Dict[str, Any]:
    """Return a compact machine-readable remediation hint for citation audits."""

    if next_action in {"retry_or_check_source_health", "inspect_source_health"}:
        return {
            "kind": "retry_or_check_source_health",
            "action": next_action,
            "sources_failed": list(result.sources_failed),
            "requires_user_confirmation": False,
            "policy": "source_retry_is_inconclusive_not_fabrication",
        }
    if result.verdict == Verdict.METADATA_MISMATCH:
        return {
            "kind": "review_metadata_correction",
            "action": next_action,
            "mismatched_fields": [diff.field for diff in result.field_diffs if not diff.matches],
            "suggested_citation": result.suggested_citation,
            "requires_user_confirmation": True,
        }
    if result.verdict == Verdict.AMBIGUOUS:
        return {
            "kind": "disambiguate_citation",
            "action": next_action,
            "requested_identifiers": ["doi", "arxiv_id"],
            "requires_user_confirmation": True,
        }
    if result.verdict == Verdict.NOT_FOUND:
        return {
            "kind": "add_identifier_or_replace",
            "action": next_action,
            "requested_identifiers": ["doi", "arxiv_id"],
            "requires_user_confirmation": True,
            "policy": "not_found_is_high_risk_not_fabrication_proof",
        }
    return {
        "kind": "keep",
        "action": next_action,
        "requires_user_confirmation": False,
    }


def canonical_metadata_quality(record: Optional[CitationRecord]) -> Dict[str, Any]:
    """Return source-provided metadata completeness diagnostics for a resolved record."""

    if record is None:
        return {}
    quality = record.metadata.get("metadata_quality", {})
    return dict(quality) if isinstance(quality, dict) else {}


def source_metadata_missing_fields(record: Optional[CitationRecord]) -> List[str]:
    """Return missing source metadata fields for compact audit rows."""

    quality = canonical_metadata_quality(record)
    fields = quality.get("missing_fields", [])
    return [str(field) for field in fields] if isinstance(fields, list) else []


def source_metadata_confidence_effect(record: Optional[CitationRecord]) -> str:
    """Return the conservative confidence effect for missing source metadata."""

    quality = canonical_metadata_quality(record)
    return str(quality.get("confidence_effect", "")) if quality else ""


def input_source_provenance(record_or_metadata: Any) -> Dict[str, Any]:
    """Return stable input-source provenance fields from a citation or metadata dict."""

    if isinstance(record_or_metadata, CitationRecord):
        metadata = record_or_metadata.metadata
    elif isinstance(record_or_metadata, dict):
        metadata = record_or_metadata
    else:
        metadata = {}
    provenance = {}
    for key in INPUT_SOURCE_METADATA_KEYS:
        value = metadata.get(key)
        if value not in (None, ""):
            provenance[key] = value
    return provenance


def classify_source_failure_mode(checked: List[str], failed: List[str], responded: Optional[List[str]] = None) -> str:
    """Classify source failures for machine-readable verification output."""

    if not failed:
        return "none"
    if responded:
        return "partial_outage"
    checked_set = set(checked)
    failed_set = set(failed)
    if checked_set and checked_set <= failed_set:
        return "all_sources_failed"
    return "partial_outage"


def available_sources(checked: List[str], failed: List[str]) -> List[str]:
    """Return checked sources that did not report a source-level failure."""

    failed_set = set(failed)
    return [source for source in checked if source not in failed_set]


def source_failure_recovery_code(details: List[Dict[str, Any]]) -> str:
    """Return the most actionable stable error code from source failure details."""

    codes = [str(item.get("code", "")) for item in details if item.get("code")]
    if "timeout" in codes:
        return "timeout"
    if "source_unavailable" in codes:
        return "source_unavailable"
    return ""


def verification_recovery_code(verdict: Verdict, source_failure_details: List[Dict[str, Any]]) -> str:
    """Return a stable recovery code for non-error verification outcomes."""

    if verdict == Verdict.AMBIGUOUS:
        return "ambiguous_citation"
    if verdict == Verdict.NOT_FOUND:
        return source_failure_recovery_code(source_failure_details)
    return ""
