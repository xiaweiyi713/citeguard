"""Batch verification across many citations."""

from __future__ import annotations

from typing import Any, List, Optional

from citeguard.citation import CitationFormatter
from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients.base import MetadataSource

from .models import AuditReport, Verdict, verification_risk_item
from .verify import verify_citation


def audit_citations(
    candidates: List[CitationRecord],
    source: MetadataSource,
    doi_registry: Optional[Any] = None,
) -> AuditReport:
    formatter = CitationFormatter()
    results = [verify_citation(candidate, source, formatter, doi_registry=doi_registry) for candidate in candidates]
    summary = {verdict.value: 0 for verdict in Verdict}
    for result in results:
        summary[result.verdict.value] += 1
    risk_ranking = sorted(
        [verification_risk_item(index, result) for index, result in enumerate(results)],
        key=lambda item: item["risk_score"],
        reverse=True,
    )
    return AuditReport(results=results, summary=summary, risk_ranking=risk_ranking)
