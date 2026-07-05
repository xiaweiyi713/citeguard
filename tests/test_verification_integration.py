"""End-to-end smoke test for the verification package public API."""

import unittest

from citeguard.verification import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.verification import (
    AuditReport,
    CachingMetadataSource,
    Verdict,
    VerificationResult,
    audit_citations,
    parse_citation,
    verify_citation,
)


class IntegrationTests(unittest.TestCase):
    def test_public_api_end_to_end_through_cache(self):
        record = CitationRecord(
            citation_id="x",
            title="The AI Scientist-v2: Workshop-Level Automated Scientific Discovery",
            authors=["Yutaro Yamada"],
            year=2025,
            source="memory",
        )
        source = CachingMetadataSource(InMemoryMetadataSource([record]), db_path=":memory:")
        candidate = parse_citation(title=record.title, authors=["Yutaro Yamada"], year=2025)

        result = verify_citation(candidate, source)
        self.assertIsInstance(result, VerificationResult)
        self.assertEqual(result.verdict, Verdict.VERIFIED)

        report = audit_citations([candidate], source)
        self.assertIsInstance(report, AuditReport)
        self.assertEqual(report.summary["verified"], 1)


if __name__ == "__main__":
    unittest.main()
