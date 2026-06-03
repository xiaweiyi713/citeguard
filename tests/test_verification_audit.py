"""Tests for batch citation auditing."""

import unittest

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource
from src.verification.audit import audit_citations
from src.verification.parse import parse_citation


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.real = CitationRecord(
            citation_id="openscholar",
            title="OpenScholar: Synthesizing Scientific Literature",
            authors=["Akari Asai"],
            year=2024,
            source="memory",
        )
        self.source = InMemoryMetadataSource([self.real])

    def test_audit_counts_each_verdict(self):
        candidates = [
            parse_citation(title="OpenScholar: Synthesizing Scientific Literature", year=2024),  # verified
            parse_citation(title="OpenScholar: Synthesizing Scientific Literature", year=2010),  # mismatch
            parse_citation(title="A Fabricated Paper That Does Not Exist"),                      # not_found
        ]
        report = audit_citations(candidates, self.source)
        self.assertEqual(len(report.results), 3)
        self.assertEqual(report.summary["verified"], 1)
        self.assertEqual(report.summary["metadata_mismatch"], 1)
        self.assertEqual(report.summary["not_found"], 1)
        self.assertEqual(report.summary["ambiguous"], 0)


if __name__ == "__main__":
    unittest.main()
