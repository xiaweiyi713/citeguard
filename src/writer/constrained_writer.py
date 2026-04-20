"""Writing logic that only uses verified citations."""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from src.citation import CitationFormatter
from src.graph import ActionType, CitationRecord, Claim, ClaimDecision
from src.planner import OutlineSection


class ConstrainedWriter:
    """Produces section text from verified or revised claims only."""

    def __init__(self, formatter: Optional[CitationFormatter] = None) -> None:
        self.formatter = formatter or CitationFormatter()

    def write_section(
        self,
        section: OutlineSection,
        claims: Iterable[Claim],
        decisions: Dict[str, ClaimDecision],
        citations_by_id: Dict[str, CitationRecord],
    ) -> str:
        sentences: List[str] = [f"{section.title}."]
        for claim in claims:
            decision = decisions[claim.claim_id]
            if decision.action == ActionType.CITE:
                inline = self._inline_citations(decision.selected_citation_ids, citations_by_id)
                sentences.append(f"{claim.text} {inline}".strip())
            elif decision.action == ActionType.REWRITE:
                body = decision.rewritten_claim or claim.text
                inline = self._inline_citations(decision.selected_citation_ids, citations_by_id)
                sentences.append(f"{body} {inline}".strip())
            else:
                sentences.append(
                    "Evidence remains insufficient to safely support a stronger claim in this area."
                )
        return " ".join(sentences)

    def build_references(
        self,
        decisions: Iterable[ClaimDecision],
        citations_by_id: Dict[str, CitationRecord],
    ) -> List[str]:
        ordered_ids: List[str] = []
        seen = set()
        for decision in decisions:
            for citation_id in decision.selected_citation_ids:
                if citation_id not in seen and citation_id in citations_by_id:
                    seen.add(citation_id)
                    ordered_ids.append(citation_id)
        return [
            self.formatter.format_reference(citations_by_id[citation_id])
            for citation_id in ordered_ids
        ]

    def _inline_citations(
        self,
        citation_ids: List[str],
        citations_by_id: Dict[str, CitationRecord],
    ) -> str:
        if not citation_ids:
            return ""
        inline = [
            self.formatter.format_inline(citations_by_id[citation_id])
            for citation_id in citation_ids
            if citation_id in citations_by_id
        ]
        return " ".join(inline)
