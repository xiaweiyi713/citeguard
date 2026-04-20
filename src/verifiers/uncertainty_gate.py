"""Decision gate that translates verifier outputs into claim actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List

from src.graph import ActionType, VerificationFinding

from .risk_fusion import RiskProfile


@dataclass(frozen=True)
class GateDecision:
    """Result of uncertainty-aware gating."""

    action: ActionType
    reason: str
    selected_citation_ids: List[str]


class UncertaintyGate:
    """Applies conservative safety rules before writing."""

    def __init__(self, cite_threshold: float = 0.35, rewrite_threshold: float = 0.55) -> None:
        self.cite_threshold = cite_threshold
        self.rewrite_threshold = rewrite_threshold

    def evaluate(
        self,
        citation_id: str,
        risk_profile: RiskProfile,
        findings: Iterable[VerificationFinding],
    ) -> GateDecision:
        findings = list(findings)
        failure_names = {finding.verifier_name for finding in findings if not finding.passed}

        if "ExistenceVerifier" in failure_names or "MetadataVerifier" in failure_names:
            return GateDecision(
                action=ActionType.ABSTAIN,
                reason="Citation failed existence or metadata validation.",
                selected_citation_ids=[],
            )

        if risk_profile.risk_score <= self.cite_threshold and "SupportVerifier" not in failure_names:
            return GateDecision(
                action=ActionType.CITE,
                reason="Verification evidence is strong enough for direct citation.",
                selected_citation_ids=[citation_id],
            )

        if risk_profile.risk_score <= self.rewrite_threshold:
            selected = [citation_id] if "SupportVerifier" not in failure_names else []
            return GateDecision(
                action=ActionType.REWRITE,
                reason="Evidence is partially reliable; rewrite into a more conservative claim.",
                selected_citation_ids=selected,
            )

        return GateDecision(
            action=ActionType.ABSTAIN,
            reason="Verification risk remains too high after gating.",
            selected_citation_ids=[],
        )
