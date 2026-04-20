"""Claim-to-evidence support verification."""

from __future__ import annotations

from typing import List, Optional, Tuple

from src.graph import CitationRecord, Claim, EvidenceSpan, VerificationFinding

from .support_backends import SupportAssessment, SupportBackend, build_default_support_backend, split_evidence_text


class SupportVerifier:
    """Estimates whether a citation's text supports a claim."""

    def __init__(self, backend: Optional[SupportBackend] = None) -> None:
        self.backend = backend or build_default_support_backend()

    def verify(
        self,
        claim: Claim,
        citation: CitationRecord,
    ) -> Tuple[VerificationFinding, EvidenceSpan]:
        evidence_candidates = self._build_candidates(citation)
        best_assessment, best_candidate = self._select_best_evidence(claim.text, evidence_candidates)

        evidence = EvidenceSpan(
            evidence_id=f"{claim.claim_id}-{citation.citation_id}-evidence",
            citation_id=citation.citation_id,
            text=best_candidate["text"],
            source_field=best_candidate["source_field"],
            source_url=best_candidate.get("source_url", ""),
            support_score=best_assessment.score,
        )
        return (
            VerificationFinding(
                claim_id=claim.claim_id,
                citation_id=citation.citation_id,
                verifier_name=self.__class__.__name__,
                passed=best_assessment.passed,
                score=best_assessment.score,
                reason=best_assessment.rationale,
                details={
                    "backend": best_assessment.backend_name,
                    "backend_details": best_assessment.details,
                    "selected_source_field": best_candidate["source_field"],
                    "selected_source_url": best_candidate.get("source_url", ""),
                    "candidate_count": len(evidence_candidates),
                },
            ),
            evidence,
        )

    def _build_candidates(self, citation: CitationRecord) -> List[dict]:
        candidates: List[dict] = []
        seen_texts = set()

        def add_candidate(text: str, source_field: str, source_url: str = "") -> None:
            cleaned = " ".join(str(text).split())
            if not cleaned or cleaned in seen_texts:
                return
            seen_texts.add(cleaned)
            candidates.append(
                {
                    "text": cleaned,
                    "source_field": source_field,
                    "source_url": source_url,
                }
            )

        if citation.title:
            add_candidate(citation.title, "title")
        if citation.abstract:
            for index, span in enumerate(split_evidence_text(citation.abstract), start=1):
                add_candidate(span, f"abstract_sentence_{index}")
        for index, chunk in enumerate(citation.metadata.get("evidence_chunks", []), start=1):
            if isinstance(chunk, dict):
                add_candidate(
                    chunk.get("text", ""),
                    str(chunk.get("source_field", f"metadata_chunk_{index}")),
                    str(chunk.get("source_url", "")),
                )
            else:
                add_candidate(str(chunk), f"metadata_chunk_{index}")
        for index, span in enumerate(citation.metadata.get("evidence_spans", []), start=1):
            if isinstance(span, dict):
                add_candidate(
                    span.get("text", ""),
                    str(span.get("source_field", f"metadata_span_{index}")),
                    str(span.get("source_url", "")),
                )
            elif span:
                add_candidate(str(span), f"metadata_span_{index}")
        if not candidates:
            add_candidate(citation.title, "title")
        return candidates

    def _select_best_evidence(
        self,
        claim_text: str,
        candidates: List[dict],
    ) -> Tuple[SupportAssessment, dict]:
        best_assessment: Optional[SupportAssessment] = None
        best_candidate: Optional[dict] = None
        for candidate in candidates:
            assessment = self.backend.assess(claim_text, candidate["text"])
            if best_assessment is None or assessment.score > best_assessment.score:
                best_assessment = assessment
                best_candidate = candidate
        return best_assessment or build_default_support_backend().assess(claim_text, ""), best_candidate or {"text": "", "source_field": "unknown"}
