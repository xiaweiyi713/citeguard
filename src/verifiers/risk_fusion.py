"""Risk aggregation over verifier outputs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable

from src.graph import VerificationFinding


@dataclass(frozen=True)
class RiskProfile:
    """Aggregate view over a candidate citation."""

    quality_score: float
    risk_score: float
    verifier_scores: Dict[str, float]


class RiskFusion:
    """Combines verifier outputs into a single quality and risk score."""

    DEFAULT_WEIGHTS = {
        "ExistenceVerifier": 0.35,
        "MetadataVerifier": 0.25,
        "SupportVerifier": 0.30,
        "ContradictionVerifier": 0.10,
    }

    def combine(self, findings: Iterable[VerificationFinding]) -> RiskProfile:
        findings = list(findings)
        if not findings:
            return RiskProfile(quality_score=0.0, risk_score=1.0, verifier_scores={})

        weighted_score = 0.0
        total_weight = 0.0
        verifier_scores: Dict[str, float] = {}
        for finding in findings:
            weight = self.DEFAULT_WEIGHTS.get(finding.verifier_name, 0.0)
            weighted_score += finding.score * weight
            total_weight += weight
            verifier_scores[finding.verifier_name] = finding.score

        quality_score = weighted_score / total_weight if total_weight else 0.0
        return RiskProfile(
            quality_score=quality_score,
            risk_score=1.0 - quality_score,
            verifier_scores=verifier_scores,
        )
