"""Claim-support verification: does a paper support a claim? (abstract-level)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, Union
from urllib.parse import urlparse

from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients.base import MetadataSource
from citeguard.verifiers import SupportBackend
from citeguard.verifiers.support_backends import split_evidence_text

from .models import (
    available_sources,
    batch_execution_summary,
    canonical_metadata_quality,
    classify_source_failure_mode,
    input_source_provenance,
    review_summary_from_risk_ranking,
    source_failure_recovery_code,
    source_metadata_confidence_effect,
    source_metadata_missing_fields,
)
from .resolve import STRONG_MATCH, resolve_citation


class SupportVerdict(str, Enum):
    """Outcome of judging whether a paper supports a claim."""

    SUPPORTED = "supported"
    WEAKLY_SUPPORTED = "weakly_supported"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CONTRADICTED = "contradicted"


@dataclass(frozen=True)
class SupportDecisionPolicy:
    """Thresholds controlling the 4-way support verdict mapping."""

    entail_strong: float = 0.55
    entail_weak: float = 0.30
    contra_strong: float = 0.55
    margin: float = 0.05
    relatedness_floor: float = 0.30
    weak_relatedness: float = 0.40


DEFAULT_SUPPORT_POLICY = SupportDecisionPolicy()


@dataclass(frozen=True)
class SupportResult:
    """Result of a claim-support check."""

    verdict: SupportVerdict
    confidence: float
    claim: str
    evidence: Dict[str, str]
    nli_scores: Optional[Dict[str, float]]
    engine: str
    resolution: Dict[str, Any]
    explanation: str
    lang: str = ""
    evidence_scope: str = "abstract"
    model_failure_details: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        evidence = dict(self.evidence)
        evidence.setdefault(
            "source_name",
            infer_evidence_source_name(evidence.get("source_field", ""), evidence.get("source_url", "")),
        )
        data = {
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 4),
            "claim": self.claim,
            "evidence": evidence,
            "evidence_scope": self.evidence_scope,
            "nli_scores": dict(self.nli_scores) if self.nli_scores else None,
            "engine": self.engine,
            "resolution": dict(self.resolution),
            "canonical_metadata_quality": _resolution_metadata_quality(self.resolution),
            "source_metadata_missing_fields": _resolution_metadata_missing_fields(self.resolution),
            "source_metadata_confidence_effect": _resolution_metadata_confidence_effect(self.resolution),
            "explanation": self.explanation,
            "lang": self.lang,
            "model_failure_details": [dict(item) for item in self.model_failure_details],
            "next_action": _support_next_action(self.verdict, self.resolution),
        }
        data.update(_counterevidence_review_for_result(self))
        return data


@dataclass(frozen=True)
class ClaimSupportRequest:
    """One claim-citation pair to assess."""

    claim: str
    citation: CitationRecord
    lang: str = ""


@dataclass(frozen=True)
class ClaimSupportAuditItem:
    """One claim with either a single citation or a citation set to assess."""

    claim: str
    citations: List[CitationRecord]
    lang: str = ""
    input_mode: str = "citation"


@dataclass(frozen=True)
class SupportAuditReport:
    """Batch result for many claim-citation support checks."""

    results: List[Union[SupportResult, ClaimSupportSetResult]]
    summary: Dict[str, int]
    risk_ranking: List[Dict[str, Any]] = field(default_factory=list)
    input_modes: List[str] = field(default_factory=list)
    batch_execution: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        results = []
        for index, result in enumerate(self.results):
            item = result.to_dict()
            if self.input_modes:
                item["input_mode"] = self.input_modes[index]
            results.append(item)
        return {
            "summary": dict(self.summary),
            "review_summary": review_summary_from_risk_ranking(len(self.results), self.risk_ranking),
            "risk_ranking": [dict(item) for item in self.risk_ranking],
            "results": results,
            "batch_execution": dict(self.batch_execution),
        }


@dataclass(frozen=True)
class CounterEvidenceSearchReport:
    """Potential counter-evidence candidates for a claim.

    This is a retrieval aid only: candidates are not treated as proof of
    contradiction until a support/contradiction check evaluates their evidence.
    """

    claim: str
    queries: List[str]
    candidates: List[Dict[str, Any]]
    sources_checked: List[str]
    sources_responded: List[str]
    sources_failed: List[str] = field(default_factory=list)
    source_failure_details: List[Dict[str, Any]] = field(default_factory=list)
    source_failure_mode: str = "none"
    query_plan: List[Dict[str, str]] = field(default_factory=list)
    query_results: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        next_action = _counterevidence_next_action(
            candidate_count=len(self.candidates),
            source_failure_mode=self.source_failure_mode,
            sources_failed=self.sources_failed,
        )
        return {
            "claim": self.claim,
            "queries": list(self.queries),
            "query_plan": [dict(item) for item in self.query_plan],
            "query_results": [dict(item) for item in self.query_results],
            "candidate_count": len(self.candidates),
            "candidates": [dict(item) for item in self.candidates],
            "review_summary": _counterevidence_review_summary(
                self.candidates,
                source_failure_mode=self.source_failure_mode,
                sources_failed=self.sources_failed,
                next_action=next_action,
            ),
            "sources_checked": list(self.sources_checked),
            "sources_responded": list(self.sources_responded),
            "sources_available": available_sources(self.sources_checked, self.sources_failed),
            "sources_failed": list(self.sources_failed),
            "source_failure_details": [dict(item) for item in self.source_failure_details],
            "source_failure_mode": self.source_failure_mode,
            "outage_limited": self.source_failure_mode == "all_sources_failed",
            "recovery_code": source_failure_recovery_code(self.source_failure_details),
            "next_action": next_action,
            "interpretation": (
                "Retrieved candidates are review leads, not a contradiction verdict. "
                "Run support checks before rewriting or removing citations."
            ),
        }


@dataclass(frozen=True)
class ClaimSupportSetResult:
    """Claim-level support result aggregated across multiple cited papers."""

    verdict: SupportVerdict
    confidence: float
    claim: str
    summary: Dict[str, int]
    results: List[SupportResult]
    evidence: List[Dict[str, str]]
    explanation: str
    risk: str
    recommendation: str
    support_mode: str = ""
    supporting_citation_count: int = 0
    contradicting_citation_count: int = 0
    lang: str = ""
    evidence_scope: str = "abstract"

    def to_dict(self) -> Dict[str, Any]:
        evidence_provenance = _support_set_evidence_provenance(self)
        input_provenance = _support_set_input_source_provenance(self)
        data = {
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 4),
            "claim": self.claim,
            "summary": dict(self.summary),
            "results": [result.to_dict() for result in self.results],
            "evidence": [dict(item) for item in self.evidence],
            "explanation": self.explanation,
            "risk": self.risk,
            "recommendation": self.recommendation,
            "support_mode": self.support_mode,
            "supporting_citation_count": self.supporting_citation_count,
            "contradicting_citation_count": self.contradicting_citation_count,
            "lang": self.lang,
            "evidence_scope": self.evidence_scope,
            "evidence_scopes": evidence_provenance["evidence_scopes"],
            "evidence_source_names": evidence_provenance["evidence_source_names"],
            "evidence_source_fields": evidence_provenance["evidence_source_fields"],
            "source_metadata_missing_fields": _support_set_metadata_missing_fields(self),
            "source_metadata_confidence_effects": _support_set_metadata_confidence_effects(self),
            "support_mode_details": _support_set_mode_details(self),
            "input_source_paths": input_provenance["input_source_paths"],
            "input_source_formats": input_provenance["input_source_formats"],
            "input_source_types": input_provenance["input_source_types"],
            "input_source_ids": input_provenance["input_source_ids"],
            "input_source_indexes": input_provenance["input_source_indexes"],
            "input_source_locators": input_provenance["input_source_locators"],
            "input_source_line_starts": input_provenance["input_source_line_starts"],
            "input_source_line_ends": input_provenance["input_source_line_ends"],
            "next_action": _support_set_next_action(self.verdict),
        }
        data.update(_counterevidence_review_for_set(self.verdict, self.summary))
        return data


def build_evidence_spans(citation: CitationRecord) -> List[Dict[str, str]]:
    """Candidate evidence spans: title + abstract sentences + metadata chunks."""

    spans: List[Dict[str, str]] = []
    seen = set()

    def add(
        text: str,
        source_field: str,
        source_url: str = "",
        evidence_scope: str = "",
        source_name: str = "",
    ) -> None:
        cleaned = " ".join(str(text).split())
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        scope = evidence_scope or infer_evidence_scope(source_field, source_url)
        source = source_name or infer_evidence_source_name(source_field, source_url)
        spans.append(
            {
                "text": cleaned,
                "source_field": source_field,
                "source_url": source_url,
                "evidence_scope": scope,
                "source_name": source,
            }
        )

    citation_source_name = _citation_record_source_name(citation.source)
    if citation.title:
        add(citation.title, "title", evidence_scope="title", source_name=citation_source_name)
    if citation.abstract:
        for index, sentence in enumerate(split_evidence_text(citation.abstract), start=1):
            add(
                sentence,
                f"abstract_sentence_{index}",
                evidence_scope="abstract",
                source_name=citation_source_name,
            )
    for index, chunk in enumerate(citation.metadata.get("evidence_chunks", []), start=1):
        if isinstance(chunk, dict):
            add(
                chunk.get("text", ""),
                str(chunk.get("source_field", f"metadata_chunk_{index}")),
                str(chunk.get("source_url", "")),
                str(chunk.get("evidence_scope", "")),
                str(chunk.get("source_name", "")),
            )
        else:
            add(str(chunk), f"metadata_chunk_{index}")
    return spans


def _citation_record_source_name(source: str) -> str:
    source_name = str(source or "").strip()
    if not source_name or source_name == "unknown":
        return "citation_metadata"
    return source_name


def infer_evidence_scope(source_field: str, source_url: str = "") -> str:
    """Return a conservative machine-readable scope for a support evidence span."""

    field = str(source_field).lower()
    if source_field == "none":
        return "none"
    if field == "title":
        return "title"
    if field.startswith("abstract"):
        return "abstract"
    if "full_text" in field or "fulltext" in field or "full-text" in field:
        return "full_text"
    if source_url:
        return "metadata_snippet"
    if field.startswith("metadata") or "chunk" in field:
        return "metadata"
    return "unknown"


def infer_evidence_source_name(source_field: str, source_url: str = "") -> str:
    """Return a stable source label for an evidence span without parsing prose."""

    field = str(source_field or "").strip()
    lowered = field.lower()
    if not field or lowered == "none":
        return "none"
    if lowered == "title" or lowered.startswith("abstract"):
        return "citation_metadata"
    if "user_full_text" in lowered or lowered.startswith("user_provided"):
        return "user_provided"
    if lowered.startswith("eval_"):
        return "eval_fixture"

    aliases = {
        "openalex": "openalex",
        "crossref": "crossref",
        "arxiv": "arxiv",
        "semantic": "semantic_scholar",
        "semanticscholar": "semantic_scholar",
        "s2": "semantic_scholar",
        "fixture": "fixture",
    }
    first_token = lowered.split("_", 1)[0].replace("-", "")
    if first_token in aliases:
        return aliases[first_token]

    parsed = urlparse(str(source_url or ""))
    hostname = (parsed.hostname or "").lower()
    for token, canonical in aliases.items():
        if token and token in hostname.replace("-", ""):
            return canonical
    if source_url:
        return "remote_metadata"
    if lowered.startswith("metadata") or "chunk" in lowered:
        return "metadata"
    return "unknown"


def check_claim_support(
    claim: str,
    candidate: CitationRecord,
    source: MetadataSource,
    backend: Optional[SupportBackend] = None,
    policy: SupportDecisionPolicy = DEFAULT_SUPPORT_POLICY,
    lang: str = "",
    oa_fulltext_fetcher: Optional[Any] = None,
) -> SupportResult:
    """Resolve the cited paper, then judge whether it supports the claim."""

    outcome = resolve_citation(candidate, source)
    checked = outcome.sources_checked
    failure_status = _resolution_source_status(outcome)
    if outcome.best is None or outcome.score < STRONG_MATCH:
        explanation = (
            f"Could not locate the paper in {', '.join(checked)}; cannot judge support. Provide a DOI/arXiv id."
        )
        if failure_status["source_failure_mode"] == "all_sources_failed":
            explanation = (
                f"Could not reach any checked source ({', '.join(outcome.sources_failed)}); "
                "support is inconclusive. Retry later or provide a DOI/arXiv id."
            )
        elif failure_status["source_failure_mode"] == "partial_outage":
            explanation = (
                f"Could not locate the paper in {', '.join(checked)}; one or more sources failed, "
                "so support is inconclusive. Retry later or provide a DOI/arXiv id."
            )
        return SupportResult(
            verdict=SupportVerdict.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
            claim=claim,
            evidence={
                "text": "",
                "source_field": "none",
                "source_url": "",
                "evidence_scope": "none",
                "source_name": "none",
            },
            nli_scores=None,
            engine="none",
            resolution={"verdict": "not_found", **failure_status, **input_source_provenance(candidate)},
            explanation=explanation,
            lang=lang,
            evidence_scope="none",
        )
    if outcome.ambiguous:
        return SupportResult(
            verdict=SupportVerdict.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
            claim=claim,
            evidence={
                "text": "",
                "source_field": "none",
                "source_url": "",
                "evidence_scope": "none",
                "source_name": "none",
            },
            nli_scores=None,
            engine="none",
            resolution={
                "verdict": "ambiguous",
                **failure_status,
                "recovery_code": "ambiguous_citation",
                **input_source_provenance(candidate),
            },
            explanation="The citation is ambiguous; provide a DOI/arXiv id before judging support.",
            lang=lang,
            evidence_scope="none",
        )
    resolution = {
        "verdict": "matched",
        "title": outcome.best.title,
        "year": outcome.best.year,
        "canonical_metadata_quality": canonical_metadata_quality(outcome.best),
        "source_metadata_missing_fields": source_metadata_missing_fields(outcome.best),
        "source_metadata_confidence_effect": source_metadata_confidence_effect(outcome.best),
        **failure_status,
        **input_source_provenance(candidate),
    }
    resolved = _merge_candidate_evidence(outcome.best, candidate)
    if oa_fulltext_fetcher is not None:
        resolved = oa_fulltext_fetcher.attach(resolved)
        oa_report = resolved.metadata.get("oa_fulltext")
        if isinstance(oa_report, dict):
            resolution["oa_fulltext"] = {key: value for key, value in oa_report.items() if key != "chunks"}
    return assess_support(claim, resolved, backend=backend, policy=policy, lang=lang, resolution=resolution)


def _resolution_source_status(outcome) -> Dict[str, Any]:
    failure_mode = classify_source_failure_mode(
        outcome.sources_checked,
        outcome.sources_failed,
        outcome.sources_responded,
    )
    return {
        "sources_checked": list(outcome.sources_checked),
        "sources_responded": list(outcome.sources_responded),
        "sources_available": available_sources(outcome.sources_checked, outcome.sources_failed),
        "sources_failed": list(outcome.sources_failed),
        "source_failure_details": [dict(item) for item in outcome.source_failure_details],
        "source_failure_mode": failure_mode,
        "outage_limited": failure_mode != "none" and outcome.best is None,
        "recovery_code": _resolution_recovery_code(
            verdict="",
            source_failure_details=outcome.source_failure_details,
            failure_mode=failure_mode,
        ),
    }


def _resolution_recovery_code(verdict: str, source_failure_details: List[Dict[str, Any]], failure_mode: str) -> str:
    if verdict == "ambiguous":
        return "ambiguous_citation"
    if failure_mode != "none":
        return source_failure_recovery_code(source_failure_details)
    return ""


def audit_claim_support(
    requests: Sequence[Union[ClaimSupportRequest, ClaimSupportAuditItem]],
    source: MetadataSource,
    backend: Optional[SupportBackend] = None,
    policy: SupportDecisionPolicy = DEFAULT_SUPPORT_POLICY,
    lang: str = "",
    oa_fulltext_fetcher: Optional[Any] = None,
    max_workers: int = 4,
) -> SupportAuditReport:
    """Resolve and assess many claim-citation pairs."""

    def assess(
        request: Union[ClaimSupportRequest, ClaimSupportAuditItem],
    ) -> tuple[Union[SupportResult, ClaimSupportSetResult], str]:
        if isinstance(request, ClaimSupportAuditItem):
            mode = request.input_mode or ("citation_set" if len(request.citations) != 1 else "citation")
            if mode == "citation_set":
                return (
                    check_claim_support_set(
                        request.claim,
                        request.citations,
                        source,
                        backend=backend,
                        policy=policy,
                        lang=request.lang or lang,
                        oa_fulltext_fetcher=oa_fulltext_fetcher,
                    ),
                    mode,
                )
            return (
                check_claim_support(
                    request.claim,
                    request.citations[0],
                    source,
                    backend=backend,
                    policy=policy,
                    lang=request.lang or lang,
                    oa_fulltext_fetcher=oa_fulltext_fetcher,
                ),
                mode,
            )
        return (
            check_claim_support(
                request.claim,
                request.citation,
                source,
                backend=backend,
                policy=policy,
                oa_fulltext_fetcher=oa_fulltext_fetcher,
                lang=request.lang or lang,
            ),
            "citation",
        )

    worker_count = max(1, min(int(max_workers), 16, len(requests) or 1))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="citeguard-support") as executor:
        assessed = list(executor.map(assess, requests))
    results = [result for result, _ in assessed]
    input_modes = [mode for _, mode in assessed]
    summary = {verdict.value: 0 for verdict in SupportVerdict}
    for result in results:
        summary[result.verdict.value] += 1
    risk_ranking = sorted(
        [_support_audit_risk_item(index, result, input_modes[index]) for index, result in enumerate(results)],
        key=lambda item: item["risk_score"],
        reverse=True,
    )
    return SupportAuditReport(
        results=results,
        summary=summary,
        risk_ranking=risk_ranking,
        input_modes=input_modes,
        batch_execution=batch_execution_summary(len(requests), worker_count),
    )


def check_claim_support_set(
    claim: str,
    candidates: List[CitationRecord],
    source: MetadataSource,
    backend: Optional[SupportBackend] = None,
    policy: SupportDecisionPolicy = DEFAULT_SUPPORT_POLICY,
    lang: str = "",
    oa_fulltext_fetcher: Optional[Any] = None,
) -> ClaimSupportSetResult:
    """Assess whether one claim is supported by a set of cited papers.

    This aggregates individual citation checks at their recorded evidence
    scopes. It does not infer unstated multi-hop or unavailable full-text support.
    """

    results = [
        check_claim_support(
            claim,
            candidate,
            source,
            backend=backend,
            policy=policy,
            lang=lang,
            oa_fulltext_fetcher=oa_fulltext_fetcher,
        )
        for candidate in candidates
    ]
    summary = {verdict.value: 0 for verdict in SupportVerdict}
    for result in results:
        summary[result.verdict.value] += 1

    contradicted = [result for result in results if result.verdict == SupportVerdict.CONTRADICTED]
    supported = [result for result in results if result.verdict == SupportVerdict.SUPPORTED]
    weak = [result for result in results if result.verdict == SupportVerdict.WEAKLY_SUPPORTED]

    if contradicted:
        best = max(contradicted, key=lambda item: item.confidence)
        verdict = SupportVerdict.CONTRADICTED
        confidence = best.confidence
        risk = "high"
        support_mode = "contradiction_dominates"
        explanation = "At least one resolved citation contradicts the claim."
        recommendation = (
            "Do not present this claim with the current citation set without rewriting or replacing evidence."
        )
        evidence_results = contradicted
    elif supported:
        best = max(supported, key=lambda item: item.confidence)
        verdict = SupportVerdict.SUPPORTED
        confidence = best.confidence
        risk = "low"
        support_mode = "single_strong_support" if len(supported) == 1 else "multiple_strong_support"
        explanation = (
            "At least one resolved citation supports the claim with full-text evidence."
            if any(result.evidence_scope == "full_text" for result in supported)
            else "At least one resolved citation supports the claim with available evidence."
        )
        recommendation = "Keep the claim, preserving citation-level evidence and confidence."
        evidence_results = supported
    elif len(weak) >= 2:
        verdict = SupportVerdict.WEAKLY_SUPPORTED
        confidence = round(sum(result.confidence for result in weak) / len(weak), 4)
        risk = "medium"
        support_mode = "multiple_weak_support"
        explanation = "Multiple citations provide related or partial evidence, but none strongly supports the claim."
        recommendation = "Tighten the claim or inspect full text before treating the citation set as support."
        evidence_results = weak
    elif weak:
        verdict = SupportVerdict.WEAKLY_SUPPORTED
        confidence = weak[0].confidence
        risk = "medium"
        support_mode = "single_weak_support"
        explanation = "One citation provides related or partial evidence, but the set is not strong enough."
        recommendation = "Add stronger evidence, inspect full text, or weaken the claim."
        evidence_results = weak
    else:
        verdict = SupportVerdict.INSUFFICIENT_EVIDENCE
        confidence = 0.0
        risk = "medium"
        support_mode = "insufficient_evidence"
        explanation = "No citation in the set confirms the claim with the available evidence."
        recommendation = "Find a stronger citation or inspect full text before using the claim."
        evidence_results = []

    evidence = []
    result_indexes = {id(result): index for index, result in enumerate(results)}
    for result in evidence_results:
        item: Dict[str, Any] = dict(result.evidence)
        item["index"] = result_indexes.get(id(result), -1)
        item["verdict"] = result.verdict.value
        item["confidence"] = round(result.confidence, 4)
        item["resolution"] = dict(result.resolution)
        item["evidence_scope"] = result.evidence_scope
        evidence.append(item)
    aggregate_scope = _aggregate_evidence_scope([result.evidence_scope for result in evidence_results])

    return ClaimSupportSetResult(
        verdict=verdict,
        confidence=confidence,
        claim=claim,
        summary=summary,
        results=results,
        evidence=evidence,
        explanation=explanation,
        risk=risk,
        recommendation=recommendation,
        support_mode=support_mode,
        supporting_citation_count=len(supported) + len(weak),
        contradicting_citation_count=len(contradicted),
        lang=lang,
        evidence_scope=aggregate_scope,
    )


from .support_reporting import (  # noqa: E402  # Imported after core types to avoid a cycle.
    _aggregate_evidence_scope,
    _counterevidence_next_action,
    _counterevidence_review_for_result,
    _counterevidence_review_for_set,
    _counterevidence_review_summary,
    _merge_candidate_evidence,
    _resolution_metadata_confidence_effect,
    _resolution_metadata_missing_fields,
    _resolution_metadata_quality,
    _support_audit_risk_item,
    _support_next_action,
    _support_set_evidence_provenance,
    _support_set_input_source_provenance,
    _support_set_metadata_confidence_effects,
    _support_set_metadata_missing_fields,
    _support_set_mode_details,
    _support_set_next_action,
)
from .support_scoring import _extract_nli, assess_support  # noqa: E402
from .support_counterevidence import (  # noqa: E402
    enrich_support_payload_with_counterevidence,
    search_counterevidence_candidates,
)

__all__ = [
    "_extract_nli",
    "assess_support",
    "enrich_support_payload_with_counterevidence",
    "search_counterevidence_candidates",
]
