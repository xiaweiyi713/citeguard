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
    ][:5]

    return {
        "total": total,
        "high_risk_count": risk_counts.get("high", 0),
        "medium_risk_count": risk_counts.get("medium", 0),
        "low_risk_count": risk_counts.get("low", 0),
        "risk_counts": risk_counts,
        "next_actions": next_actions,
        "action_queues": action_queues,
        "top_risk_indexes": top_risk_indexes,
        "top_high_risk_indexes": top_high_risk_indexes,
    }


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
    return {
        "index": index,
        "verdict": result.verdict.value,
        "risk": level,
        "risk_score": round(score, 4),
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
        "sources_available": available_sources(result.sources_checked, result.sources_failed),
        "sources_failed": list(result.sources_failed),
        "source_failure_details": [dict(item) for item in result.source_failure_details],
        "source_failure_mode": result.source_failure_mode,
        "outage_limited": result.outage_limited,
        "recovery_code": verification_recovery_code(result.verdict, result.source_failure_details),
        "next_action": next_action,
        "recommendation": recommendation,
    }


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
