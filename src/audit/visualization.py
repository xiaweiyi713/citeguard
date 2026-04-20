"""Graph visualization helpers."""

from __future__ import annotations

from typing import List

from src.graph import CCEG


class GraphVisualizer:
    """Produces Mermaid graph text for quick inspection."""

    def to_mermaid(self, graph: CCEG) -> str:
        lines: List[str] = ["flowchart TD"]
        for claim in graph.claims.values():
            lines.append(f'    {claim.claim_id}["{claim.text}"]')
        for citation in graph.citations.values():
            lines.append(f'    {citation.citation_id}["{citation.title}"]')
        for link in graph.links:
            lines.append(
                f"    {link.claim_id} -->|{link.relation.value}:{link.score:.2f}| {link.citation_id}"
            )
        return "\n".join(lines)
