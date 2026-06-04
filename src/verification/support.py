"""Claim-support verification: does a paper support a claim? (abstract-level)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, Optional


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
