"""Audit report assembly."""

from __future__ import annotations

from typing import Dict, List, Optional

from src.graph import CCEG

from .provenance import ProvenanceBuilder


class AuditReportBuilder:
    """Creates machine-friendly and human-friendly audit reports."""

    def __init__(self, provenance_builder: Optional[ProvenanceBuilder] = None) -> None:
        self.provenance_builder = provenance_builder or ProvenanceBuilder()

    def build(self, graph: CCEG, sections: List[Dict[str, str]], references: List[str]) -> Dict[str, object]:
        provenance = self.provenance_builder.build(graph)
        return {
            "summary": {
                "claims": len(graph.claims),
                "citations": len(graph.citations),
                "decisions": len(graph.decisions),
            },
            "sections": sections,
            "references": references,
            "provenance": provenance,
        }

    def to_markdown(self, report: Dict[str, object]) -> str:
        lines = ["# CiteGuard Audit Report", ""]
        summary = report["summary"]
        lines.append(f"- Claims: {summary['claims']}")
        lines.append(f"- Citations: {summary['citations']}")
        lines.append(f"- Decisions: {summary['decisions']}")
        lines.append("")
        lines.append("## Provenance")
        for row in report["provenance"]:
            lines.append(
                f"- {row['claim_id']}: action={row['action']}, risk={row['risk_score']:.3f}, citations={row['citations']}"
            )
        return "\n".join(lines)
