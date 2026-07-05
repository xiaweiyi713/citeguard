"""Claim-support verification: does a paper support a claim? (abstract-level)."""

from __future__ import annotations

import re
import socket
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from citeguard.citation import normalize_text, tokenize_text
from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients.base import MetadataSource
from citeguard.verifiers import SupportAssessment, SupportBackend, build_default_support_backend
from citeguard.verifiers.support_backends import split_evidence_text

from .models import (
    available_sources,
    classify_source_failure_mode,
    review_summary_from_risk_ranking,
    source_failure_recovery_code,
    stable_next_action,
)
from .resolve import STRONG_MATCH, resolve_citation, source_names


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


_ZH_SOURCE_OUTAGE_TERMS = (
    "源不可达",
    "来源不可达",
    "数据源不可达",
    "源失败",
    "来源失败",
    "源故障",
    "来源故障",
    "检索失败",
    "查询失败",
    "超时",
    "限流",
    "未找到",
    "找不到",
)
_ZH_FABRICATION_TERMS = ("伪造", "虚假", "编造", "幻觉", "捏造")
_ZH_CONFIDENCE_TERMS = ("提高", "增加", "提升", "证明", "证据", "置信", "确信")
_ZH_CONFIDENCE_REDUCTION_TERMS = ("降低", "下调", "减少")
_ZH_CERTAINTY_TERMS = ("置信", "可信", "确定")
_ZH_PROOF_DENIAL_TERMS = ("不能证明", "无法证明", "不可证明")
_ZH_EVIDENCE_DENIAL_TERMS = ("不是证据", "并非证据", "不构成证据", "不能作为证据")
_ZH_CLASSIFICATION_DENIAL_TERMS = ("不应", "不能", "不可")
_ZH_CLASSIFICATION_TERMS = ("指控", "判定", "标记", "归类")
_ZH_RETRY_OR_HEALTH_TERMS = ("来源健康", "源健康", "稍后重试", "人工复核")


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
        data = {
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 4),
            "claim": self.claim,
            "evidence": dict(self.evidence),
            "evidence_scope": self.evidence_scope,
            "nli_scores": dict(self.nli_scores) if self.nli_scores else None,
            "engine": self.engine,
            "resolution": dict(self.resolution),
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
        return {
            "claim": self.claim,
            "queries": list(self.queries),
            "query_plan": [dict(item) for item in self.query_plan],
            "query_results": [dict(item) for item in self.query_results],
            "candidate_count": len(self.candidates),
            "candidates": [dict(item) for item in self.candidates],
            "sources_checked": list(self.sources_checked),
            "sources_responded": list(self.sources_responded),
            "sources_available": available_sources(self.sources_checked, self.sources_failed),
            "sources_failed": list(self.sources_failed),
            "source_failure_details": [dict(item) for item in self.source_failure_details],
            "source_failure_mode": self.source_failure_mode,
            "outage_limited": self.source_failure_mode == "all_sources_failed",
            "recovery_code": source_failure_recovery_code(self.source_failure_details),
            "next_action": _counterevidence_next_action(
                candidate_count=len(self.candidates),
                source_failure_mode=self.source_failure_mode,
                sources_failed=self.sources_failed,
            ),
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
            "next_action": _support_set_next_action(self.verdict),
        }
        data.update(_counterevidence_review_for_set(self.verdict, self.summary))
        return data


def build_evidence_spans(citation: CitationRecord) -> List[Dict[str, str]]:
    """Candidate evidence spans: title + abstract sentences + metadata chunks."""

    spans: List[Dict[str, str]] = []
    seen = set()

    def add(text: str, source_field: str, source_url: str = "", evidence_scope: str = "") -> None:
        cleaned = " ".join(str(text).split())
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        scope = evidence_scope or infer_evidence_scope(source_field, source_url)
        spans.append(
            {
                "text": cleaned,
                "source_field": source_field,
                "source_url": source_url,
                "evidence_scope": scope,
            }
        )

    if citation.title:
        add(citation.title, "title", evidence_scope="title")
    if citation.abstract:
        for index, sentence in enumerate(split_evidence_text(citation.abstract), start=1):
            add(sentence, f"abstract_sentence_{index}", evidence_scope="abstract")
    for index, chunk in enumerate(citation.metadata.get("evidence_chunks", []), start=1):
        if isinstance(chunk, dict):
            add(
                chunk.get("text", ""),
                str(chunk.get("source_field", f"metadata_chunk_{index}")),
                str(chunk.get("source_url", "")),
                str(chunk.get("evidence_scope", "")),
            )
        else:
            add(str(chunk), f"metadata_chunk_{index}")
    return spans


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


def _extract_nli(assessment: SupportAssessment) -> Optional[Dict[str, float]]:
    """Pull NLI probabilities out of an ensemble or NLI assessment, if present."""

    if assessment.backend_name == "transformers_nli":
        probs = assessment.details.get("probabilities")
        return dict(probs) if probs else None
    if assessment.backend_name == "ensemble_support":
        for component in assessment.details.get("components", []):
            if component.get("backend") == "transformers_nli":
                probs = component.get("details", {}).get("probabilities")
                return dict(probs) if probs else None
    return None


def _component_score(assessment: SupportAssessment, backend_name: str) -> float:
    if assessment.backend_name == backend_name:
        return float(assessment.score)
    for component in assessment.details.get("components", []):
        if component.get("backend") == backend_name:
            return float(component.get("score", 0.0))
    return 0.0


def _component_passed(assessment: SupportAssessment, backend_name: str) -> bool:
    if assessment.backend_name == backend_name:
        return bool(assessment.passed)
    for component in assessment.details.get("components", []):
        if component.get("backend") == backend_name:
            return bool(component.get("passed", False))
    return False


def _prob(nli: Optional[Dict[str, float]], key: str) -> float:
    return float(nli.get(key, 0.0)) if nli else 0.0


def _explicit_contradiction_confidence(claim: str, evidence: str, score: float = 0.0) -> float:
    """Return a conservative confidence for explicit claim/evidence contradiction cues."""

    if not claim or not evidence:
        return 0.0
    if not _is_related_enough(claim, evidence):
        return 0.0
    if not (_english_contradiction_pattern(claim, evidence) or _chinese_contradiction_pattern(claim, evidence)):
        return 0.0

    claim_tokens = set(tokenize_text(claim))
    evidence_tokens = set(tokenize_text(evidence))
    overlap = claim_tokens & evidence_tokens
    coverage = len(overlap) / max(len(claim_tokens), 1)
    precision = len(overlap) / max(len(evidence_tokens), 1)
    confidence = 0.50 + 0.40 * coverage + 0.20 * precision + 0.10 * min(max(score, 0.0), 1.0)
    return round(min(0.85, max(0.58, confidence)), 4)


def _is_related_enough(claim: str, evidence: str) -> bool:
    claim_tokens = set(tokenize_text(claim))
    evidence_tokens = set(tokenize_text(evidence))
    overlap = claim_tokens & evidence_tokens
    if not overlap:
        return False
    coverage = len(overlap) / max(len(claim_tokens), 1)
    precision = len(overlap) / max(len(evidence_tokens), 1)
    return (len(overlap) >= 2 and coverage >= 0.25) or (len(overlap) >= 3 and precision >= 0.15)


def _span_evidence_scope(span: Dict[str, str]) -> str:
    return span.get("evidence_scope") or infer_evidence_scope(span.get("source_field", ""), span.get("source_url", ""))


def _support_anchor_score(claim: str, span: Dict[str, str], assessment: SupportAssessment) -> float:
    heuristic_score = _component_score(assessment, "heuristic_support")
    if heuristic_score > 0.0:
        return heuristic_score
    if _component_passed(assessment, "heuristic_support"):
        return max(heuristic_score, 0.18)
    if _is_related_enough(claim, span["text"]):
        return max(heuristic_score, 0.18)
    return 0.0


def _direct_metadata_support_candidate(
    claim: str,
    span: Dict[str, str],
    assessment: SupportAssessment,
    entailment: float,
    contradiction: float,
    policy: SupportDecisionPolicy,
) -> bool:
    scope = _span_evidence_scope(span)
    if scope not in ("metadata_snippet", "full_text"):
        return False
    if entailment < max(0.40, policy.entail_weak):
        return False
    if entailment < contradiction + policy.margin:
        return False
    return _support_anchor_score(claim, span, assessment) >= 0.18


def _weak_support_candidate(
    claim: str,
    span: Dict[str, str],
    assessment: SupportAssessment,
    nli: Optional[Dict[str, float]],
    policy: SupportDecisionPolicy,
) -> bool:
    anchor = _support_anchor_score(claim, span, assessment)
    if anchor <= 0.0:
        return False

    scope = _span_evidence_scope(span)
    if scope == "title" and anchor >= 0.25:
        return True

    entailment = _prob(nli, "entailment")
    contradiction = _prob(nli, "contradiction")
    if nli and entailment >= policy.entail_weak and entailment >= contradiction + policy.margin:
        return True

    return assessment.score >= policy.weak_relatedness and anchor >= 0.12


def _english_contradiction_pattern(claim: str, evidence: str) -> bool:
    claim_text = normalize_text(claim)
    evidence_text = normalize_text(evidence)
    improvement_claim = re.search(
        r"\b(improves?|improved|increase[sd]?|increasing|boosts?|boosted|raises?|raised|gains?)\b",
        claim_text,
    )
    negative_result = re.search(
        r"\b(?:does|do|did)\s+not\s+(?:improve|increase|boost|raise|gain)\b"
        r"|\bnot\s+(?:improve|increase|boost|raise|gain)\b"
        r"|\b(reduces?|reduced|decreases?|decreased|lowers?|lowered|worse|harms?|harmed)\b",
        evidence_text,
    )
    if improvement_claim and negative_result:
        return True

    necessity_claim = re.search(r"\b(always|must|required|requires|necessary|only|all|every)\b", claim_text)
    optional_evidence = re.search(
        r"\b(optional|not\s+required|not\s+necessary|need\s+not|does\s+not\s+require|do\s+not\s+require|by\s+default)\b",
        evidence_text,
    )
    if necessity_claim and optional_evidence:
        return True

    support_claim = re.search(r"\b(supports?|supported|proves?|proved|demonstrates?|shows?)\b", claim_text)
    negative_support_claim = re.search(
        r"\b(?:not|fail(?:s|ed|ing)?|without|cannot|does\s+not|do\s+not|did\s+not)\s+(?:to\s+)?support\b",
        claim_text,
    )
    support_denial = re.search(
        r"\b(?:does|do|did)\s+not\s+support\b|\bnot\s+support\b|\bfails?\s+to\s+support\b",
        evidence_text,
    )
    if support_claim and not negative_support_claim and support_denial:
        return True

    fabrication_claim = re.search(r"\b(?:treats?|marks?|labels?|flags?|classifies?)\b.*\bfabricated\b", claim_text)
    fabrication_denial = re.search(
        r"\b(?:does|do|did)\s+not\s+(?:treat|mark|label|flag|classify)\b.*\bfabricated\b"
        r"|\bnot\s+(?:treat|mark|label|flag|classify)(?:ed)?\b.*\bfabricated\b",
        evidence_text,
    )
    return bool(fabrication_claim and fabrication_denial)


def _source_outage_safety_pattern(claim: str, evidence: str) -> bool:
    claim_text = normalize_text(claim)
    evidence_text = normalize_text(evidence)
    outage_claim = re.search(
        r"\b(?:source|sources|outage|outages|unavailable|timeout|timeouts|not_found|not\s+found|missing)\b",
        claim_text,
    )
    zh_outage_claim = any(term in claim_text for term in _ZH_SOURCE_OUTAGE_TERMS)
    fabrication_claim = re.search(r"\b(?:fabricated|fake|false|hallucinated|forged)\b", claim_text)
    zh_fabrication_claim = any(term in claim_text for term in _ZH_FABRICATION_TERMS)
    confidence_claim = re.search(r"\b(?:increase|raises?|boosts?|proves?|evidence|confidence)\b", claim_text)
    zh_confidence_claim = any(term in claim_text for term in _ZH_CONFIDENCE_TERMS)
    if not (outage_claim or zh_outage_claim) or not (
        fabrication_claim or zh_fabrication_claim or confidence_claim or zh_confidence_claim
    ):
        return False

    outage_evidence = re.search(
        r"\b(?:source|sources|outage|outages|unavailable|timeout|timeouts|not_found|not\s+found|missing)\b",
        evidence_text,
    )
    zh_outage_evidence = any(term in evidence_text for term in _ZH_SOURCE_OUTAGE_TERMS)
    safety_evidence = re.search(
        r"\b(?:lower|lowers|reduced?|decrease[sd]?|inconclusive|retry|source[-\s]?health)\b.*"
        r"\b(?:confidence|certainty|inspection|check)\b"
        r"|\bnot\s+(?:evidence|proof)\b.*\b(?:fabricated|fake|false|hallucinated|forged)\b"
        r"|\bmust\s+not\b.*\b(?:fabricated|fake|false|hallucinated|forged)\b",
        evidence_text,
    )
    zh_safety_evidence = (
        (
            any(term in evidence_text for term in _ZH_CONFIDENCE_REDUCTION_TERMS)
            and any(term in evidence_text for term in _ZH_CERTAINTY_TERMS)
        )
        or (
            any(term in evidence_text for term in _ZH_PROOF_DENIAL_TERMS)
            and any(term in evidence_text for term in _ZH_FABRICATION_TERMS)
        )
        or (
            any(term in evidence_text for term in _ZH_EVIDENCE_DENIAL_TERMS)
            and any(term in evidence_text for term in _ZH_FABRICATION_TERMS)
        )
        or (
            any(term in evidence_text for term in _ZH_CLASSIFICATION_DENIAL_TERMS)
            and any(term in evidence_text for term in _ZH_CLASSIFICATION_TERMS)
            and any(term in evidence_text for term in _ZH_FABRICATION_TERMS)
        )
        or any(term in evidence_text for term in _ZH_RETRY_OR_HEALTH_TERMS)
    )
    return bool((outage_evidence or zh_outage_evidence) and (safety_evidence or zh_safety_evidence))


def _chinese_contradiction_pattern(claim: str, evidence: str) -> bool:
    claim_text = normalize_text(claim)
    evidence_text = normalize_text(evidence)

    universal_claim = any(term in claim_text for term in ("一定", "总是", "所有", "全部", "必然", "必须"))
    universal_denial = any(term in evidence_text for term in ("未必", "不一定", "并非", "不总是", "不必", "可选"))
    if universal_claim and universal_denial:
        return True

    improvement_claim = any(term in claim_text for term in ("提升", "提高", "增加", "改善"))
    negative_result = any(term in evidence_text for term in ("降低", "减少", "未提升", "没有提升", "不提升", "下降"))
    if improvement_claim and negative_result:
        return True

    support_claim = "支持" in claim_text
    support_denial = any(term in evidence_text for term in ("不支持", "未支持", "未必支持", "不能支持"))
    return support_claim and support_denial


def assess_support(
    claim: str,
    citation: CitationRecord,
    backend: Optional[SupportBackend] = None,
    policy: SupportDecisionPolicy = DEFAULT_SUPPORT_POLICY,
    lang: str = "",
    resolution: Optional[Dict[str, Any]] = None,
) -> SupportResult:
    """Judge whether `citation` supports `claim`, over abstract-level evidence."""

    backend = backend or build_default_support_backend()
    resolution = resolution if resolution is not None else {"verdict": "matched", "title": citation.title}

    spans = build_evidence_spans(citation)
    if not spans:
        return SupportResult(
            verdict=SupportVerdict.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
            claim=claim,
            evidence={"text": "", "source_field": "none", "source_url": "", "evidence_scope": "none"},
            nli_scores=None,
            engine="heuristic",
            resolution=resolution,
            explanation="No abstract or evidence text was available to judge support.",
            lang=lang,
            evidence_scope="none",
        )

    assessed = []
    for span in spans:
        assessment = backend.assess(claim, span["text"])
        assessed.append((span, assessment, _extract_nli(assessment)))
    model_failures = _model_failure_details_from_assessed(assessed)

    def emit(result: SupportResult) -> SupportResult:
        if not model_failures:
            return result
        return replace(result, model_failure_details=model_failures)

    engine = "ensemble" if any(nli for _, _, nli in assessed) else "heuristic"
    best_score_span, best_score_assessment, _ = max(
        assessed,
        key=lambda item: (item[1].score, _span_scope_priority(item[0])),
    )
    best_score = best_score_assessment.score

    if engine == "ensemble":
        ent_span, ent_assessment, ent_nli = max(
            assessed,
            key=lambda item: (_prob(item[2], "entailment"), _span_scope_priority(item[0])),
        )
        entailment = _prob(ent_nli, "entailment")
        ent_contra = _prob(ent_nli, "contradiction")
        related = [item for item in assessed if item[1].score >= policy.relatedness_floor]
        con_span, _, con_nli = max(
            related or assessed,
            key=lambda item: (_prob(item[2], "contradiction"), _span_scope_priority(item[0])),
        )
        contradiction = _prob(con_nli, "contradiction") if related else 0.0
        explicit_contradiction = max(
            (
                (_explicit_contradiction_confidence(claim, span["text"], assessment.score), span, nli)
                for span, assessment, nli in assessed
            ),
            key=lambda item: (item[0], _span_scope_priority(item[1])),
        )

        if explicit_contradiction[0] >= policy.contra_strong:
            return emit(_result(
                SupportVerdict.CONTRADICTED,
                explicit_contradiction[0],
                claim,
                explicit_contradiction[1],
                explicit_contradiction[2],
                engine,
                resolution,
                "The evidence contains an explicit contradiction cue for the claim.",
                lang,
            ))
        if entailment >= policy.entail_strong and entailment >= ent_contra + policy.margin:
            return emit(_result(
                SupportVerdict.SUPPORTED,
                entailment,
                claim,
                ent_span,
                ent_nli,
                engine,
                resolution,
                "The abstract entails the claim.",
                lang,
            ))
        if contradiction >= policy.contra_strong:
            return emit(_result(
                SupportVerdict.CONTRADICTED,
                contradiction,
                claim,
                con_span,
                con_nli,
                engine,
                resolution,
                "The abstract contradicts the claim.",
                lang,
            ))
        if _direct_metadata_support_candidate(
            claim,
            ent_span,
            ent_assessment,
            entailment,
            ent_contra,
            policy,
        ):
            return emit(_result(
                SupportVerdict.SUPPORTED,
                entailment,
                claim,
                ent_span,
                ent_nli,
                engine,
                resolution,
                "A source metadata or full-text evidence snippet directly supports the claim.",
                lang,
            ))
        weak_candidates = []
        if _weak_support_candidate(claim, ent_span, ent_assessment, ent_nli, policy):
            weak_candidates.append(
                (
                    max(entailment, ent_assessment.score, _support_anchor_score(claim, ent_span, ent_assessment)),
                    ent_span,
                    ent_nli,
                )
            )
        if _weak_support_candidate(claim, best_score_span, best_score_assessment, None, policy):
            weak_candidates.append(
                (
                    max(best_score, _support_anchor_score(claim, best_score_span, best_score_assessment)),
                    best_score_span,
                    None,
                )
            )
        if weak_candidates:
            confidence, span, nli = max(weak_candidates, key=lambda item: (item[0], _span_scope_priority(item[1])))
            return emit(_result(
                SupportVerdict.WEAKLY_SUPPORTED,
                confidence,
                claim,
                span,
                nli,
                engine,
                resolution,
                "Partial or related evidence, but not strong enough.",
                lang,
            ))
        return emit(_result(
            SupportVerdict.INSUFFICIENT_EVIDENCE,
            round(1.0 - best_score, 4),
            claim,
            best_score_span,
            ent_nli,
            engine,
            resolution,
            "The abstract does not address the claim (cannot confirm).",
            lang,
        ))

    if _weak_support_candidate(claim, best_score_span, best_score_assessment, None, policy):
        return emit(_result(
            SupportVerdict.WEAKLY_SUPPORTED,
            best_score,
            claim,
            best_score_span,
            None,
            engine,
            resolution,
            "Lexical overlap suggests relatedness; deep models not loaded.",
            lang,
        ))
    return emit(_result(
        SupportVerdict.INSUFFICIENT_EVIDENCE,
        round(1.0 - best_score, 4),
        claim,
        best_score_span,
        None,
        engine,
        resolution,
        "Insufficient lexical overlap; deep models not loaded.",
        lang,
    ))


def _result(verdict, confidence, claim, span, nli, engine, resolution, explanation, lang) -> SupportResult:
    evidence_scope = span.get("evidence_scope") or infer_evidence_scope(span["source_field"], span.get("source_url", ""))
    adjusted_confidence = _support_confidence_with_source_failures(float(confidence), resolution)
    adjusted_explanation = explanation + _support_source_failure_note(resolution)
    return SupportResult(
        verdict=verdict,
        confidence=adjusted_confidence,
        claim=claim,
        evidence={
            "text": span["text"],
            "source_field": span["source_field"],
            "source_url": span.get("source_url", ""),
            "evidence_scope": evidence_scope,
        },
        nli_scores=nli,
        engine=engine,
        resolution=resolution,
        explanation=adjusted_explanation,
        lang=lang,
        evidence_scope=evidence_scope,
    )


def _support_confidence_with_source_failures(confidence: float, resolution: Dict[str, Any]) -> float:
    if resolution.get("source_failure_mode") == "all_sources_failed":
        return round(min(confidence, 0.35), 4)
    if resolution.get("source_failure_mode") == "partial_outage":
        return round(min(confidence, 0.85), 4)
    return round(confidence, 4)


def _support_source_failure_note(resolution: Dict[str, Any]) -> str:
    if resolution.get("source_failure_mode") != "partial_outage":
        return ""
    failed = ", ".join(str(item) for item in resolution.get("sources_failed", []) if item)
    if not failed:
        return ""
    return f" Confidence is reduced because these sources failed: {failed}."


def _model_failure_details_from_assessed(assessed: List[tuple]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    seen = set()
    for _, assessment, _ in assessed:
        candidates = [
            {"backend": assessment.backend_name, "details": assessment.details},
        ]
        for component in assessment.details.get("components", []):
            if isinstance(component, dict):
                candidates.append(
                    {
                        "backend": component.get("backend", ""),
                        "details": component.get("details", {}),
                    }
                )
        for candidate in candidates:
            details = candidate.get("details", {})
            if not isinstance(details, dict) or details.get("error_code") != "model_unavailable":
                continue
            item = {
                "backend": str(candidate.get("backend", "")),
                "model_name": str(details.get("model_name", "")),
                "error_code": "model_unavailable",
                "error_type": str(details.get("error_type", "")),
                "message": str(details.get("message", "")),
            }
            key = tuple(sorted(item.items()))
            if key in seen:
                continue
            seen.add(key)
            failures.append(item)
    return failures


def _span_scope_priority(span: Dict[str, str]) -> int:
    scope = span.get("evidence_scope") or infer_evidence_scope(span.get("source_field", ""), span.get("source_url", ""))
    return {
        "full_text": 5,
        "abstract": 4,
        "metadata_snippet": 3,
        "metadata": 2,
        "title": 1,
        "unknown": 0,
        "none": 0,
    }.get(scope, 0)


def check_claim_support(
    claim: str,
    candidate: CitationRecord,
    source: MetadataSource,
    backend: Optional[SupportBackend] = None,
    policy: SupportDecisionPolicy = DEFAULT_SUPPORT_POLICY,
    lang: str = "",
) -> SupportResult:
    """Resolve the cited paper, then judge whether it supports the claim."""

    outcome = resolve_citation(candidate, source)
    checked = outcome.sources_checked
    failure_status = _resolution_source_status(outcome)
    if outcome.best is None or outcome.score < STRONG_MATCH:
        explanation = f"Could not locate the paper in {', '.join(checked)}; cannot judge support. Provide a DOI/arXiv id."
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
            evidence={"text": "", "source_field": "none", "source_url": "", "evidence_scope": "none"},
            nli_scores=None,
            engine="none",
            resolution={"verdict": "not_found", **failure_status},
            explanation=explanation,
            lang=lang,
            evidence_scope="none",
        )
    if outcome.ambiguous:
        return SupportResult(
            verdict=SupportVerdict.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
            claim=claim,
            evidence={"text": "", "source_field": "none", "source_url": "", "evidence_scope": "none"},
            nli_scores=None,
            engine="none",
            resolution={"verdict": "ambiguous", **failure_status, "recovery_code": "ambiguous_citation"},
            explanation="The citation is ambiguous; provide a DOI/arXiv id before judging support.",
            lang=lang,
            evidence_scope="none",
        )
    resolution = {
        "verdict": "matched",
        "title": outcome.best.title,
        "year": outcome.best.year,
        **failure_status,
    }
    resolved = _merge_candidate_evidence(outcome.best, candidate)
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
    requests: List[Union[ClaimSupportRequest, ClaimSupportAuditItem]],
    source: MetadataSource,
    backend: Optional[SupportBackend] = None,
    policy: SupportDecisionPolicy = DEFAULT_SUPPORT_POLICY,
    lang: str = "",
) -> SupportAuditReport:
    """Resolve and assess many claim-citation pairs."""

    results: List[Union[SupportResult, ClaimSupportSetResult]] = []
    input_modes: List[str] = []
    for request in requests:
        if isinstance(request, ClaimSupportAuditItem):
            mode = request.input_mode or ("citation_set" if len(request.citations) != 1 else "citation")
            if mode == "citation_set":
                results.append(
                    check_claim_support_set(
                        request.claim,
                        request.citations,
                        source,
                        backend=backend,
                        policy=policy,
                        lang=request.lang or lang,
                    )
                )
            else:
                results.append(
                    check_claim_support(
                        request.claim,
                        request.citations[0],
                        source,
                        backend=backend,
                        policy=policy,
                        lang=request.lang or lang,
                    )
                )
            input_modes.append(mode)
            continue
        results.append(
            check_claim_support(
                request.claim,
                request.citation,
                source,
                backend=backend,
                policy=policy,
                lang=request.lang or lang,
            )
        )
        input_modes.append("citation")
    summary = {verdict.value: 0 for verdict in SupportVerdict}
    for result in results:
        summary[result.verdict.value] += 1
    risk_ranking = sorted(
        [_support_audit_risk_item(index, result, input_modes[index]) for index, result in enumerate(results)],
        key=lambda item: item["risk_score"],
        reverse=True,
    )
    return SupportAuditReport(results=results, summary=summary, risk_ranking=risk_ranking, input_modes=input_modes)


def search_counterevidence_candidates(
    claim: str,
    source: MetadataSource,
    top_k: int = 5,
) -> CounterEvidenceSearchReport:
    """Search scholarly metadata for papers that may contain counter-evidence.

    The report is intentionally conservative. It returns ranked leads with
    lexical contradiction cues, but never changes the support verdict for a
    claim and never treats an empty result as proof that no counter-evidence
    exists.
    """

    cleaned_claim = " ".join(str(claim).split())
    checked = source_names(source)
    if not cleaned_claim:
        return CounterEvidenceSearchReport(
            claim=cleaned_claim,
            queries=[],
            candidates=[],
            sources_checked=checked,
            sources_responded=[],
        )

    query_plan = _counterevidence_query_plan(cleaned_claim)
    queries = [item["query"] for item in query_plan]
    records: List[CitationRecord] = []
    failures: List[str] = []
    failure_details: List[Dict[str, Any]] = []
    query_results: List[Dict[str, Any]] = []
    record_query_matches: Dict[str, Dict[str, Any]] = {}
    per_query = max(top_k * 2, 5)
    for query_item in query_plan:
        query = query_item["query"]
        query_records: List[CitationRecord] = []
        query_failures: List[str] = []
        query_failure_details: List[Dict[str, Any]] = []
        try:
            query_records = source.search(query, top_k=per_query)
            records.extend(query_records)
        except Exception as exc:
            query_failures.extend(checked)
            query_failure_details.extend(_exception_failure_details(checked, exc))
        query_failure_details.extend(_source_failure_details(source))
        inner = getattr(source, "inner", source)
        query_failures.extend(getattr(inner, "last_failures", []))
        query_failure_details.extend(getattr(inner, "last_failure_details", []))
        query_failures.extend(
            str(detail.get("source", ""))
            for detail in query_failure_details
            if detail.get("source") and detail.get("code")
        )
        for record in query_records:
            key = _counterevidence_record_key(record)
            match = record_query_matches.setdefault(key, {"queries": [], "roles": [], "rationales": []})
            if query not in match["queries"]:
                match["queries"].append(query)
            if query_item["role"] not in match["roles"]:
                match["roles"].append(query_item["role"])
            if query_item["rationale"] not in match["rationales"]:
                match["rationales"].append(query_item["rationale"])
        failures.extend(query_failures)
        failure_details.extend(query_failure_details)
        query_results.append(
            {
                "query": query,
                "role": query_item["role"],
                "rationale": query_item["rationale"],
                "returned": len(query_records),
                "sources_failed": sorted(set(query_failures)),
                "source_failure_mode": classify_source_failure_mode(
                    checked,
                    sorted(set(query_failures)),
                    sorted({record.source for record in query_records if record.source}),
                ),
            }
        )

    scored = _rank_counterevidence_records(
        cleaned_claim,
        _dedupe_counterevidence_records(records),
        record_query_matches=record_query_matches,
    )
    candidates = [item for item in scored[: max(0, int(top_k))]]
    responded = sorted({str(item.get("source", "")) for item in candidates if item.get("source")})
    failed = sorted(set(failures))
    failure_details = _dedupe_failure_details(failure_details)
    failed = sorted(
        set(failed)
        | {
            str(detail.get("source", ""))
            for detail in failure_details
            if detail.get("source") and detail.get("code")
        }
    )
    return CounterEvidenceSearchReport(
        claim=cleaned_claim,
        queries=queries,
        candidates=candidates,
        sources_checked=checked,
        sources_responded=responded,
        sources_failed=failed,
        source_failure_details=failure_details,
        source_failure_mode=classify_source_failure_mode(checked, failed, responded),
        query_plan=query_plan,
        query_results=query_results,
    )


def enrich_support_payload_with_counterevidence(
    payload: Dict[str, Any],
    source: MetadataSource,
    top_k: int = 3,
) -> Dict[str, Any]:
    """Attach counter-evidence lead searches to review-worthy support payloads."""

    enriched = dict(payload)
    cache: Dict[str, Dict[str, Any]] = {}

    def report_for_claim(claim: str) -> Dict[str, Any]:
        cleaned = " ".join(str(claim).split())
        if cleaned not in cache:
            cache[cleaned] = search_counterevidence_candidates(cleaned, source, top_k=top_k).to_dict()
        return cache[cleaned]

    def attach(item: Dict[str, Any]) -> None:
        if not item.get("counterevidence_review"):
            return
        claim = str(item.get("claim", "")).strip()
        if not claim:
            return
        item["counterevidence"] = report_for_claim(claim)

    results = []
    for result in enriched.get("results", []):
        item = dict(result)
        attach(item)
        results.append(item)
    if results:
        enriched["results"] = results

    risk_ranking = []
    for risk_item in enriched.get("risk_ranking", []):
        item = dict(risk_item)
        index = item.get("index")
        if isinstance(index, int) and 0 <= index < len(results):
            counterevidence = results[index].get("counterevidence")
            if counterevidence:
                item["counterevidence"] = counterevidence
        else:
            attach(item)
        risk_ranking.append(item)
    if risk_ranking:
        enriched["risk_ranking"] = risk_ranking

    if enriched.get("counterevidence_review") and "counterevidence" not in enriched:
        attach(enriched)

    enriched["counterevidence_included"] = True
    enriched["counterevidence_top_k"] = max(0, int(top_k))
    return enriched


def check_claim_support_set(
    claim: str,
    candidates: List[CitationRecord],
    source: MetadataSource,
    backend: Optional[SupportBackend] = None,
    policy: SupportDecisionPolicy = DEFAULT_SUPPORT_POLICY,
    lang: str = "",
) -> ClaimSupportSetResult:
    """Assess whether one claim is supported by a set of cited papers.

    This is an abstract-level aggregation over individual citation checks. It
    does not infer unstated multi-hop/full-text support.
    """

    results = [
        check_claim_support(claim, candidate, source, backend=backend, policy=policy, lang=lang)
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
        recommendation = "Do not present this claim with the current citation set without rewriting or replacing evidence."
        evidence_results = contradicted
    elif supported:
        best = max(supported, key=lambda item: item.confidence)
        verdict = SupportVerdict.SUPPORTED
        confidence = best.confidence
        risk = "low"
        support_mode = "single_strong_support" if len(supported) == 1 else "multiple_strong_support"
        explanation = "At least one resolved citation supports the claim at abstract level."
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
        explanation = "No citation in the set confirms the claim with available abstract-level evidence."
        recommendation = "Find a stronger citation or inspect full text before using the claim."
        evidence_results = []

    evidence = []
    result_indexes = {id(result): index for index, result in enumerate(results)}
    for result in evidence_results:
        item = dict(result.evidence)
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


def _counterevidence_queries(claim: str) -> List[str]:
    return [item["query"] for item in _counterevidence_query_plan(claim)]


def _counterevidence_query_plan(claim: str) -> List[Dict[str, str]]:
    queries = [
        {
            "query": claim,
            "role": "claim_similarity",
            "rationale": "Find papers closely related to the original claim before adding negation probes.",
        }
    ]
    normalized = normalize_text(claim)
    if re.search(r"\b(improves?|improved|increase[sd]?|boosts?|raises?|gains?)\b", normalized):
        queries.append(
            {
                "query": f"{claim} does not improve no improvement decreases worse",
                "role": "improvement_negation",
                "rationale": "Probe for papers reporting no improvement, decreases, or worse outcomes.",
            }
        )
    if re.search(r"\b(supports?|supported|proves?|demonstrates?|shows?)\b", normalized):
        queries.append(
            {
                "query": f"{claim} does not support fails to support no evidence",
                "role": "support_negation",
                "rationale": "Probe for papers saying the evidence does not support the claim.",
            }
        )
    if re.search(r"\b(always|must|required|requires|necessary|only|all|every)\b", normalized):
        queries.append(
            {
                "query": f"{claim} optional not required not necessary exception",
                "role": "necessity_exception",
                "rationale": "Probe for exceptions to absolute or necessity claims.",
            }
        )
    if re.search(
        r"\b(source|sources|outage|outages|unavailable|timeout|timeouts|not_found|not\s+found|fabricated|fake|hallucinated)\b",
        normalized,
    ) or any(term in normalized for term in _ZH_SOURCE_OUTAGE_TERMS + _ZH_FABRICATION_TERMS):
        zh_safety_terms = " ".join(
            _ZH_SOURCE_OUTAGE_TERMS
            + _ZH_PROOF_DENIAL_TERMS
            + _ZH_EVIDENCE_DENIAL_TERMS
            + _ZH_CONFIDENCE_REDUCTION_TERMS
            + _ZH_CERTAINTY_TERMS
            + _ZH_FABRICATION_TERMS
            + _ZH_RETRY_OR_HEALTH_TERMS
        )
        queries.append(
            {
                "query": (
                    f"{claim} source outage unavailable timeout not found "
                    f"not evidence fabricated lower confidence inconclusive {zh_safety_terms}"
                ),
                "role": "source_outage_safety",
                "rationale": (
                    "Probe for evidence that source outages or not-found results lower confidence "
                    "without proving fabrication."
                ),
            }
        )
    if any(term in normalized for term in ("提升", "提高", "增加", "改善")):
        queries.append(
            {
                "query": f"{claim} 未提升 没有提升 降低 减少",
                "role": "zh_improvement_negation",
                "rationale": "检索未提升、降低或减少等中文反向证据线索。",
            }
        )
    if any(term in normalized for term in ("一定", "总是", "所有", "全部", "必须")):
        queries.append(
            {
                "query": f"{claim} 未必 不一定 并非 可选",
                "role": "zh_necessity_exception",
                "rationale": "检索绝对化或必要性表述的例外线索。",
            }
        )
    deduped = []
    seen = set()
    for item in queries:
        query = item["query"]
        if query not in seen:
            seen.add(query)
            deduped.append(item)
    return deduped


def _counterevidence_record_key(record: CitationRecord) -> str:
    return record.doi.lower() or record.arxiv_id.lower() or normalize_text(record.title) or record.citation_id


def _dedupe_counterevidence_records(records: List[CitationRecord]) -> List[CitationRecord]:
    deduped: List[CitationRecord] = []
    seen = set()
    for record in records:
        key = _counterevidence_record_key(record)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _rank_counterevidence_records(
    claim: str,
    records: List[CitationRecord],
    record_query_matches: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    ranked = []
    record_query_matches = record_query_matches or {}
    for record in records:
        text = " ".join(part for part in [record.title, record.abstract] if part)
        if not text:
            continue
        claim_tokens = set(tokenize_text(claim))
        record_tokens = set(tokenize_text(text))
        overlap = len(claim_tokens & record_tokens)
        relatedness = overlap / max(len(claim_tokens), 1)
        source_outage_safety_cue = _source_outage_safety_pattern(claim, text)
        explicit_cue = (
            source_outage_safety_cue
            or _english_contradiction_pattern(claim, text)
            or _chinese_contradiction_pattern(claim, text)
        )
        cue_score = 1.0 if explicit_cue else 0.0
        source_score = float(record.metadata.get("source_score", 0.0))
        score = min(1.0, 0.55 * relatedness + 0.35 * cue_score + 0.10 * source_score)
        if score <= 0.0:
            continue
        query_match = record_query_matches.get(_counterevidence_record_key(record), {})
        ranked.append(
            (
                score,
                {
                    "title": record.title,
                    "authors": list(record.authors),
                    "year": record.year,
                    "venue": record.venue,
                    "doi": record.doi,
                    "arxiv_id": record.arxiv_id,
                    "url": record.url,
                    "source": record.source,
                    "score": round(score, 4),
                    "signal": (
                        "source_outage_safety_cue"
                        if source_outage_safety_cue
                        else "explicit_contradiction_cue"
                        if explicit_cue
                        else "related_candidate"
                    ),
                    "matched_queries": list(query_match.get("queries", [])),
                    "matched_query_roles": list(query_match.get("roles", [])),
                    "match_rationales": list(query_match.get("rationales", [])),
                    "evidence_scope": "abstract" if record.abstract else "title",
                    "abstract_snippet": _snippet(record.abstract),
                    "citation_id": record.citation_id,
                },
            )
        )
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in ranked]


def _snippet(text: str, limit: int = 360) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _exception_failure_details(names: List[str], exc: Exception) -> List[Dict[str, Any]]:
    code, kind = _classify_source_exception(exc)
    return [
        {
            "source": name,
            "code": code,
            "kind": kind,
            "status_code": None,
            "url": "",
            "error": exc.__class__.__name__,
        }
        for name in names
    ]


def _source_failure_details(source: MetadataSource) -> List[Dict[str, Any]]:
    inner = getattr(source, "inner", source)
    details = [dict(item) for item in getattr(inner, "last_failure_details", [])]
    http_client = getattr(inner, "http_client", None)
    code = getattr(http_client, "last_error_code", "") if http_client is not None else ""
    if code:
        details.append(
            {
                "source": getattr(inner, "name", "metadata_source"),
                "code": code,
                "kind": getattr(http_client, "last_error_kind", ""),
                "status_code": getattr(http_client, "last_status_code", None),
                "url": getattr(http_client, "last_url", ""),
                "error": getattr(http_client, "last_error", ""),
                "cache_hit": bool(getattr(http_client, "last_cache_hit", False)),
            }
        )
    return _dedupe_failure_details(details)


def _classify_source_exception(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout", "timeout"
    return "source_unavailable", "exception"


def _dedupe_failure_details(details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    for detail in details:
        if detail not in deduped:
            deduped.append(detail)
    return deduped


def _aggregate_evidence_scope(scopes: List[str]) -> str:
    unique = sorted({scope for scope in scopes if scope})
    if not unique:
        return "none"
    if len(unique) == 1:
        return unique[0]
    if "full_text" in unique:
        return "mixed_with_full_text"
    return "mixed"


def _merge_candidate_evidence(record: CitationRecord, candidate: CitationRecord) -> CitationRecord:
    """Attach caller-provided evidence snippets to a resolved canonical record."""

    candidate_chunks = candidate.metadata.get("evidence_chunks", [])
    candidate_abstract = str(candidate.abstract or "").strip()
    if not candidate_chunks and not candidate_abstract:
        return record

    metadata = dict(record.metadata)
    chunks = list(metadata.get("evidence_chunks", []))
    abstract = record.abstract

    if candidate_abstract:
        if not abstract:
            abstract = candidate_abstract
        elif normalize_text(candidate_abstract) != normalize_text(abstract):
            chunks.append(
                {
                    "text": candidate_abstract,
                    "source_field": "user_provided_abstract",
                    "source_url": "",
                    "evidence_scope": "abstract",
                }
            )

    if isinstance(candidate_chunks, list):
        chunks.extend(candidate_chunks)
    elif candidate_chunks:
        chunks.append(candidate_chunks)

    if chunks:
        metadata["evidence_chunks"] = chunks
    return replace(record, abstract=abstract, metadata=metadata)


def _counterevidence_review_for_result(result: SupportResult) -> Dict[str, Any]:
    if result.verdict == SupportVerdict.SUPPORTED:
        return {
            "counterevidence_review": False,
            "counterevidence_reason": "",
            "counterevidence_recommendation": "",
        }
    if result.verdict == SupportVerdict.CONTRADICTED:
        return {
            "counterevidence_review": True,
            "counterevidence_reason": "contradicted",
            "counterevidence_recommendation": (
                "Available evidence contradicts the claim; rewrite the claim or replace the citation before use."
            ),
        }
    if result.verdict == SupportVerdict.WEAKLY_SUPPORTED:
        return {
            "counterevidence_review": True,
            "counterevidence_reason": "weak_support",
            "counterevidence_recommendation": (
                "Support is only partial; inspect full text and look for stronger or contrary evidence."
            ),
        }

    resolution_verdict = result.resolution.get("verdict", "")
    if resolution_verdict in {"not_found", "ambiguous"}:
        return {
            "counterevidence_review": True,
            "counterevidence_reason": "unresolved_citation",
            "counterevidence_recommendation": (
                "Resolve the citation identity before treating the claim as supported or contradicted."
            ),
        }
    if result.engine == "heuristic":
        reason = "heuristic_limited"
    elif result.evidence_scope == "none":
        reason = "no_evidence_text"
    else:
        reason = "insufficient_evidence"
    return {
        "counterevidence_review": True,
        "counterevidence_reason": reason,
        "counterevidence_recommendation": (
            "Available evidence does not confirm the claim; inspect full text and review possible counter-evidence."
        ),
    }


def _counterevidence_review_for_set(verdict: SupportVerdict, summary: Dict[str, int]) -> Dict[str, Any]:
    if verdict == SupportVerdict.SUPPORTED:
        return {
            "counterevidence_review": False,
            "counterevidence_reason": "",
            "counterevidence_recommendation": "",
        }
    if verdict == SupportVerdict.CONTRADICTED:
        return {
            "counterevidence_review": True,
            "counterevidence_reason": "contradicted",
            "counterevidence_recommendation": (
                "At least one cited paper contradicts the claim; rewrite the claim or replace the citation set."
            ),
        }
    if summary.get(SupportVerdict.WEAKLY_SUPPORTED.value, 0):
        return {
            "counterevidence_review": True,
            "counterevidence_reason": "weak_support",
            "counterevidence_recommendation": (
                "The citation set is only weakly related; inspect full text and look for stronger or contrary evidence."
            ),
        }
    return {
        "counterevidence_review": True,
        "counterevidence_reason": "insufficient_evidence",
        "counterevidence_recommendation": (
            "No citation confirms the claim with available evidence; review full text or find stronger evidence."
        ),
    }


def _support_next_action(verdict: SupportVerdict, resolution: Dict[str, Any]) -> str:
    if verdict == SupportVerdict.SUPPORTED:
        return stable_next_action("keep_claim")
    if verdict == SupportVerdict.WEAKLY_SUPPORTED:
        return stable_next_action("tighten_claim_or_inspect_full_text")
    if verdict == SupportVerdict.CONTRADICTED:
        return stable_next_action("rewrite_or_replace_evidence")

    resolution_verdict = resolution.get("verdict", "")
    failure_mode = str(resolution.get("source_failure_mode", ""))
    if resolution_verdict == "ambiguous":
        return stable_next_action("disambiguate_identifier")
    if failure_mode == "all_sources_failed":
        return stable_next_action("retry_or_check_source_health")
    if resolution_verdict == "not_found":
        return stable_next_action("resolve_citation_identity")
    return stable_next_action("inspect_full_text_or_find_stronger_citation")


def _support_set_next_action(verdict: SupportVerdict) -> str:
    if verdict == SupportVerdict.SUPPORTED:
        return stable_next_action("keep_claim")
    if verdict == SupportVerdict.CONTRADICTED:
        return stable_next_action("rewrite_or_replace_evidence")
    if verdict == SupportVerdict.WEAKLY_SUPPORTED:
        return stable_next_action("tighten_claim_or_inspect_full_text")
    return stable_next_action("inspect_full_text_or_find_stronger_citation")


def _counterevidence_next_action(
    candidate_count: int,
    source_failure_mode: str = "none",
    sources_failed: Optional[List[str]] = None,
) -> str:
    if candidate_count > 0:
        return stable_next_action("review_counterevidence_leads")
    if source_failure_mode != "none" or sources_failed:
        return stable_next_action("retry_or_check_source_health")
    return stable_next_action("continue")


def _support_risk_item(index: int, result: SupportResult) -> Dict[str, Any]:
    if result.verdict == SupportVerdict.SUPPORTED:
        risk, score, recommendation = "low", 0.05, "Claim is supported by the available abstract-level evidence."
    elif result.verdict == SupportVerdict.WEAKLY_SUPPORTED:
        risk, score, recommendation = "medium", 0.55, "Treat as tentative; tighten the claim or inspect full text."
    elif result.verdict == SupportVerdict.CONTRADICTED:
        risk, score, recommendation = "high", 0.98, "Do not use this citation for the claim without rewriting or replacing it."
    else:
        resolution_verdict = result.resolution.get("verdict", "")
        if resolution_verdict in {"not_found", "ambiguous"}:
            risk, score = "high", 0.9
            recommendation = "Resolve the citation first with a DOI/arXiv id before judging support."
        else:
            risk, score = "medium", 0.7
            recommendation = "Available evidence cannot confirm the claim; inspect full text or use a stronger citation."
    next_action = _support_next_action(result.verdict, result.resolution)
    item = {
        "index": index,
        "verdict": result.verdict.value,
        "risk": risk,
        "risk_score": round(score, 4),
        "claim": result.claim,
        "support_confidence": round(result.confidence, 4),
        "support_engine": result.engine,
        "resolution": dict(result.resolution),
        "resolution_verdict": str(result.resolution.get("verdict", "")),
        "resolved_title": str(result.resolution.get("title", "")),
        "resolved_year": result.resolution.get("year"),
        "evidence_scope": result.evidence_scope,
        "evidence_source_field": str(result.evidence.get("source_field", "")),
        "evidence_source_url": str(result.evidence.get("source_url", "")),
        "next_action": next_action,
        "recommendation": recommendation,
    }
    item.update(_counterevidence_review_for_result(result))
    return item


def _support_set_risk_item(index: int, result: ClaimSupportSetResult) -> Dict[str, Any]:
    if result.risk == "high":
        score = 0.98
    elif result.risk == "low":
        score = 0.05
    else:
        score = 0.72 if result.verdict == SupportVerdict.INSUFFICIENT_EVIDENCE else 0.6
    item = {
        "index": index,
        "verdict": result.verdict.value,
        "risk": result.risk,
        "risk_score": round(score, 4),
        "claim": result.claim,
        "support_confidence": round(result.confidence, 4),
        "support_engine": "citation_set",
        "summary": dict(result.summary),
        "evidence_scope": result.evidence_scope,
        "support_mode": result.support_mode,
        "supporting_citation_count": result.supporting_citation_count,
        "contradicting_citation_count": result.contradicting_citation_count,
        "next_action": _support_set_next_action(result.verdict),
        "recommendation": result.recommendation,
    }
    item.update(_counterevidence_review_for_set(result.verdict, result.summary))
    return item


def _support_audit_risk_item(
    index: int,
    result: Union[SupportResult, ClaimSupportSetResult],
    input_mode: str,
) -> Dict[str, Any]:
    if isinstance(result, ClaimSupportSetResult):
        item = _support_set_risk_item(index, result)
    else:
        item = _support_risk_item(index, result)
    item["input_mode"] = input_mode
    return item
