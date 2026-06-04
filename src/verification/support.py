"""Claim-support verification: does a paper support a claim? (abstract-level)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from src.graph import CitationRecord
from src.verifiers import SupportAssessment
from src.verifiers.support_backends import split_evidence_text

from src.retrieval.scholarly_clients.base import MetadataSource
from src.verifiers import SupportBackend, build_default_support_backend

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
    relatedness_floor: float = 0.30   # min combined score for a contradiction span to count
    weak_relatedness: float = 0.40    # combined score that yields weakly_supported


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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 4),
            "claim": self.claim,
            "evidence": dict(self.evidence),
            "nli_scores": dict(self.nli_scores) if self.nli_scores else None,
            "engine": self.engine,
            "resolution": dict(self.resolution),
            "explanation": self.explanation,
            "lang": self.lang,
        }


def build_evidence_spans(citation: CitationRecord) -> List[Dict[str, str]]:
    """Candidate evidence spans: title + abstract sentences + metadata chunks."""

    spans: List[Dict[str, str]] = []
    seen = set()

    def add(text: str, source_field: str, source_url: str = "") -> None:
        cleaned = " ".join(str(text).split())
        if not cleaned or cleaned in seen:
            return
        seen.add(cleaned)
        spans.append({"text": cleaned, "source_field": source_field, "source_url": source_url})

    if citation.title:
        add(citation.title, "title")
    if citation.abstract:
        for index, sentence in enumerate(split_evidence_text(citation.abstract), start=1):
            add(sentence, f"abstract_sentence_{index}")
    for index, chunk in enumerate(citation.metadata.get("evidence_chunks", []), start=1):
        if isinstance(chunk, dict):
            add(chunk.get("text", ""), str(chunk.get("source_field", f"metadata_chunk_{index}")), str(chunk.get("source_url", "")))
        else:
            add(str(chunk), f"metadata_chunk_{index}")
    return spans


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


def _prob(nli: Optional[Dict[str, float]], key: str) -> float:
    return float(nli.get(key, 0.0)) if nli else 0.0


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
            verdict=SupportVerdict.INSUFFICIENT_EVIDENCE, confidence=0.0, claim=claim,
            evidence={"text": "", "source_field": "none", "source_url": ""}, nli_scores=None,
            engine="heuristic", resolution=resolution,
            explanation="No abstract or evidence text was available to judge support.", lang=lang,
        )

    assessed = []  # (span, assessment, nli)
    for span in spans:
        assessment = backend.assess(claim, span["text"])
        assessed.append((span, assessment, _extract_nli(assessment)))

    engine = "ensemble" if any(nli for _, _, nli in assessed) else "heuristic"
    best_score_span, best_score_assessment, _ = max(assessed, key=lambda item: item[1].score)
    best_score = best_score_assessment.score

    if engine == "ensemble":
        ent_span, _, ent_nli = max(assessed, key=lambda item: _prob(item[2], "entailment"))
        entailment = _prob(ent_nli, "entailment")
        ent_contra = _prob(ent_nli, "contradiction")
        related = [item for item in assessed if item[1].score >= policy.relatedness_floor]
        con_span, _, con_nli = max(
            related or assessed, key=lambda item: _prob(item[2], "contradiction")
        )
        contradiction = _prob(con_nli, "contradiction") if related else 0.0

        if entailment >= policy.entail_strong and entailment >= ent_contra + policy.margin:
            return _result(SupportVerdict.SUPPORTED, entailment, claim, ent_span, ent_nli, engine, resolution,
                           "The abstract entails the claim.", lang)
        if contradiction >= policy.contra_strong:
            return _result(SupportVerdict.CONTRADICTED, contradiction, claim, con_span, con_nli, engine, resolution,
                           "The abstract contradicts the claim.", lang)
        if entailment >= policy.entail_weak or best_score >= policy.weak_relatedness:
            span = ent_span if entailment >= best_score else best_score_span
            return _result(SupportVerdict.WEAKLY_SUPPORTED, max(entailment, best_score), claim, span, ent_nli, engine,
                           resolution, "Partial or related evidence, but not strong enough.", lang)
        return _result(SupportVerdict.INSUFFICIENT_EVIDENCE, round(1.0 - best_score, 4), claim, best_score_span, ent_nli,
                       engine, resolution, "The abstract does not address the claim (cannot confirm).", lang)

    # heuristic engine: never SUPPORTED/CONTRADICTED (lexical overlap can't prove either)
    if best_score >= policy.weak_relatedness:
        return _result(SupportVerdict.WEAKLY_SUPPORTED, best_score, claim, best_score_span, None, engine, resolution,
                       "Lexical overlap suggests relatedness; deep models not loaded.", lang)
    return _result(SupportVerdict.INSUFFICIENT_EVIDENCE, round(1.0 - best_score, 4), claim, best_score_span, None, engine,
                   resolution, "Insufficient lexical overlap; deep models not loaded.", lang)


def _result(verdict, confidence, claim, span, nli, engine, resolution, explanation, lang) -> SupportResult:
    return SupportResult(
        verdict=verdict, confidence=round(float(confidence), 4), claim=claim,
        evidence={"text": span["text"], "source_field": span["source_field"], "source_url": span.get("source_url", "")},
        nli_scores=nli, engine=engine, resolution=resolution, explanation=explanation, lang=lang,
    )


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
    if outcome.best is None or outcome.score < STRONG_MATCH:
        return SupportResult(
            verdict=SupportVerdict.INSUFFICIENT_EVIDENCE, confidence=0.0, claim=claim,
            evidence={"text": "", "source_field": "none", "source_url": ""}, nli_scores=None, engine="none",
            resolution={"verdict": "not_found", "sources_checked": checked},
            explanation=f"Could not locate the paper in {', '.join(checked)}; cannot judge support. Provide a DOI/arXiv id.",
            lang=lang,
        )
    if outcome.ambiguous:
        return SupportResult(
            verdict=SupportVerdict.INSUFFICIENT_EVIDENCE, confidence=0.0, claim=claim,
            evidence={"text": "", "source_field": "none", "source_url": ""}, nli_scores=None, engine="none",
            resolution={"verdict": "ambiguous", "sources_checked": checked},
            explanation="The citation is ambiguous; provide a DOI/arXiv id before judging support.", lang=lang,
        )
    resolution = {
        "verdict": "matched",
        "title": outcome.best.title,
        "year": outcome.best.year,
        "sources_checked": checked,
    }
    return assess_support(claim, outcome.best, backend=backend, policy=policy, lang=lang, resolution=resolution)
