"""Contradiction risk detection."""

from __future__ import annotations

from src.citation import tokenize_text
from src.graph import CitationRecord, Claim, VerificationFinding


CONTRADICTION_CUES = {
    "but",
    "cannot",
    "fail",
    "failed",
    "fails",
    "however",
    "inconsistent",
    "limited",
    "low",
    "negative",
    "no",
    "not",
    "unclear",
    "weak",
}


class ContradictionVerifier:
    """Flags evidence that materially weakens a claim."""

    def verify(self, claim: Claim, citation: CitationRecord) -> VerificationFinding:
        claim_tokens = set(tokenize_text(claim.text))
        evidence_tokens = tokenize_text(citation.abstract or citation.title)
        overlap = claim_tokens & set(evidence_tokens)
        contradiction_hits = CONTRADICTION_CUES & set(evidence_tokens)
        overlap_based_risk = 0.0
        if overlap:
            overlap_based_risk = min(1.0, len(contradiction_hits) / max(len(overlap), 1))

        # Strongly negative evidence should still be surfaced even when wording differs
        # from the claim, because academic counter-evidence often reframes the result.
        cue_based_risk = min(1.0, len(contradiction_hits) / 3.0)
        contradiction_risk = max(overlap_based_risk, cue_based_risk)

        passed = contradiction_risk <= 0.35
        reason = (
            "No material contradiction signal detected in the evidence."
            if passed
            else "Evidence contains contradiction cues that weaken the claim."
        )
        return VerificationFinding(
            claim_id=claim.claim_id,
            citation_id=citation.citation_id,
            verifier_name=self.__class__.__name__,
            passed=passed,
            score=1.0 - contradiction_risk,
            reason=reason,
            details={"contradiction_terms": sorted(contradiction_hits)},
        )
