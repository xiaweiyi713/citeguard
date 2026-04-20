"""Existence verification for candidate citations."""

from __future__ import annotations

from typing import Optional, Tuple

from src.citation import sequence_similarity
from src.graph import CitationRecord, Claim, VerificationFinding
from src.retrieval.scholarly_clients import MetadataSource

from src.citation.proposer import CandidateCitation


class ExistenceVerifier:
    """Verifies whether a citation candidate resolves to a canonical record."""

    def verify(
        self,
        claim: Claim,
        candidate: CandidateCitation,
        metadata_source: MetadataSource,
    ) -> Tuple[VerificationFinding, Optional[CitationRecord]]:
        canonical = metadata_source.lookup(candidate.citation)
        if canonical is None:
            return (
                VerificationFinding(
                    claim_id=claim.claim_id,
                    citation_id=candidate.citation.citation_id,
                    verifier_name=self.__class__.__name__,
                    passed=False,
                    score=0.0,
                    reason="No canonical record matched the candidate citation.",
                ),
                None,
            )

        score = max(
            sequence_similarity(candidate.citation.title, canonical.title),
            0.5 if candidate.citation.doi and candidate.citation.doi == canonical.doi else 0.0,
            0.5 if candidate.citation.arxiv_id and candidate.citation.arxiv_id == canonical.arxiv_id else 0.0,
        )
        score = min(1.0, score + 0.5)
        return (
            VerificationFinding(
                claim_id=claim.claim_id,
                citation_id=canonical.citation_id,
                verifier_name=self.__class__.__name__,
                passed=True,
                score=score,
                reason="Canonical citation record was found.",
                details={"canonical_citation_id": canonical.citation_id},
            ),
            canonical,
        )
