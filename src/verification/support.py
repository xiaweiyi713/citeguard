"""Claim-support verification: does a paper support a claim? (abstract-level)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from src.graph import CitationRecord
from src.verifiers import SupportAssessment
from src.verifiers.support_backends import split_evidence_text


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
