"""Provenance extraction from the graph."""

from __future__ import annotations

from typing import Dict, List

from src.graph import CCEG


class ProvenanceBuilder:
    """Builds sentence-level provenance records from the graph."""

    def build(self, graph: CCEG) -> List[Dict[str, object]]:
        rows: List[Dict[str, object]] = []
        for claim_id, claim in graph.claims.items():
            decision = graph.decisions.get(claim_id)
            if decision and decision.selected_citation_ids:
                claim_findings = []
                for citation_id in decision.selected_citation_ids:
                    claim_findings.extend(graph.claim_findings_for_citation(claim_id, citation_id))
            else:
                claim_findings = graph.claim_findings(claim_id)
            rows.append(
                {
                    "claim_id": claim_id,
                    "section_id": claim.section_id,
                    "claim_text": claim.text,
                    "action": decision.action.value if decision else "missing",
                    "risk_score": decision.risk_score if decision else 1.0,
                    "citations": decision.selected_citation_ids if decision else [],
                    "candidate_attempts": len({finding.citation_id for finding in graph.claim_findings(claim_id)}),
                    "findings": [
                        {
                            "verifier": finding.verifier_name,
                            "passed": finding.passed,
                            "score": round(finding.score, 4),
                            "reason": finding.reason,
                        }
                        for finding in claim_findings
                    ],
                }
            )
        return rows
