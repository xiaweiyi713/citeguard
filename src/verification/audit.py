"""Batch verification across many citations."""

from __future__ import annotations

from typing import List

from src.citation import CitationFormatter
from src.graph import CitationRecord
from src.retrieval.scholarly_clients.base import MetadataSource

from .models import AuditReport, Verdict
from .verify import verify_citation


def audit_citations(candidates: List[CitationRecord], source: MetadataSource) -> AuditReport:
    formatter = CitationFormatter()
    results = [verify_citation(candidate, source, formatter) for candidate in candidates]
    summary = {verdict.value: 0 for verdict in Verdict}
    for result in results:
        summary[result.verdict.value] += 1
    return AuditReport(results=results, summary=summary)
