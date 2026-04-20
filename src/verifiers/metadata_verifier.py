"""Metadata consistency verification."""

from __future__ import annotations

from typing import Optional

from src.citation import author_coverage, sequence_similarity, year_matches
from src.graph import CitationRecord, Claim, VerificationFinding

from src.citation.proposer import CandidateCitation


class MetadataVerifier:
    """Checks whether candidate metadata agrees with the canonical record."""

    def verify(
        self,
        claim: Claim,
        candidate: CandidateCitation,
        canonical: Optional[CitationRecord],
    ) -> VerificationFinding:
        if canonical is None:
            return VerificationFinding(
                claim_id=claim.claim_id,
                citation_id=candidate.citation.citation_id,
                verifier_name=self.__class__.__name__,
                passed=False,
                score=0.0,
                reason="Metadata cannot be validated without a canonical record.",
            )

        title_score = sequence_similarity(candidate.citation.title, canonical.title)
        author_score = author_coverage(candidate.citation.authors, canonical.authors)
        year_score = 1.0 if year_matches(candidate.citation.year, canonical.year) else 0.0
        venue_score = sequence_similarity(candidate.citation.venue, canonical.venue) if (
            candidate.citation.venue and canonical.venue
        ) else 0.5
        score = 0.45 * title_score + 0.25 * author_score + 0.15 * year_score + 0.15 * venue_score

        passed = title_score >= 0.9 and (author_score >= 0.5 or not candidate.citation.authors)
        reason = (
            "Candidate metadata aligns with the canonical record."
            if passed
            else "Metadata shows mismatches against the canonical record."
        )
        return VerificationFinding(
            claim_id=claim.claim_id,
            citation_id=canonical.citation_id,
            verifier_name=self.__class__.__name__,
            passed=passed,
            score=score,
            reason=reason,
            details={
                "title_score": round(title_score, 4),
                "author_score": round(author_score, 4),
                "year_score": round(year_score, 4),
                "venue_score": round(venue_score, 4),
            },
        )
