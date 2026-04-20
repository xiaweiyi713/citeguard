"""Builds final claim decisions from gating results."""

from __future__ import annotations

from typing import Optional

from src.graph import Claim, ClaimDecision
from src.verifiers import GateDecision, RiskProfile

from .reviser import ConservativeReviser


class AbstentionController:
    """Converts gate decisions into stored graph decisions."""

    def __init__(self, reviser: Optional[ConservativeReviser] = None) -> None:
        self.reviser = reviser or ConservativeReviser()

    def build_decision(
        self,
        claim: Claim,
        gate_decision: GateDecision,
        risk_profile: RiskProfile,
    ) -> ClaimDecision:
        rewritten_claim = ""
        if gate_decision.action.value == "rewrite":
            rewritten_claim = self.reviser.rewrite(claim.text)

        return ClaimDecision(
            claim_id=claim.claim_id,
            action=gate_decision.action,
            reason=gate_decision.reason,
            risk_score=risk_profile.risk_score,
            selected_citation_ids=gate_decision.selected_citation_ids,
            rewritten_claim=rewritten_claim,
        )
