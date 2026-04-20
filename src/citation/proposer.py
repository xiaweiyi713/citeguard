"""Citation proposal logic."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from src.graph import CitationRecord, Claim
from src.retrieval.types import RetrievedCitation


@dataclass(frozen=True)
class CandidateCitation:
    """Candidate citation selected for a claim."""

    claim_id: str
    citation: CitationRecord
    retrieval_score: float
    rationale: str


class CitationProposer:
    """Selects the highest-value citation candidates from retrieval results."""

    def propose(
        self, claim: Claim, retrieved: List[RetrievedCitation], top_k: int = 3
    ) -> List[CandidateCitation]:
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        candidates: List[CandidateCitation] = []
        for result in retrieved[:top_k]:
            rationale = (
                f"Selected by {result.retriever_name} with retrieval score {result.score:.3f} "
                f"for claim {claim.claim_id}."
            )
            candidates.append(
                CandidateCitation(
                    claim_id=claim.claim_id,
                    citation=result.citation,
                    retrieval_score=result.score,
                    rationale=rationale,
                )
            )
        return candidates
