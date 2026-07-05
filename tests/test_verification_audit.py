"""Tests for batch citation auditing."""

import unittest

from citeguard.verification import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.verification.audit import audit_citations
from citeguard.verification.parse import parse_citation


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
        self.assertEqual(report.risk_ranking[0]["verdict"], "not_found")
        self.assertEqual(report.risk_ranking[0]["risk"], "high")
        self.assertEqual(report.risk_ranking[0]["next_action"], "resolve_identifier_or_replace")
        self.assertEqual(report.risk_ranking[1]["next_action"], "review_metadata")
        self.assertEqual(report.risk_ranking[-1]["next_action"], "keep")
        self.assertEqual(report.risk_ranking[-1]["risk"], "low")
        self.assertIn("recommendation", report.to_dict()["risk_ranking"][0])
        review_summary = report.to_dict()["review_summary"]
        self.assertEqual(review_summary["total"], 3)
        self.assertEqual(review_summary["risk_counts"], {"high": 1, "medium": 1, "low": 1})
        self.assertEqual(review_summary["high_risk_count"], 1)
        self.assertEqual(review_summary["medium_risk_count"], 1)
        self.assertEqual(review_summary["low_risk_count"], 1)
        self.assertEqual(review_summary["next_actions"]["resolve_identifier_or_replace"], 1)
        self.assertEqual(review_summary["next_actions"]["review_metadata"], 1)
        self.assertEqual(review_summary["next_actions"]["keep"], 1)
        self.assertEqual(review_summary["top_high_risk_indexes"], [2])
        self.assertEqual(review_summary["top_risk_indexes"], [2, 1, 0])
        self.assertEqual(review_summary["action_queues"]["identity_resolution_indexes"], [2])
        self.assertEqual(review_summary["action_queues"]["metadata_review_indexes"], [1])
        self.assertEqual(review_summary["action_queues"]["safe_to_keep_indexes"], [0])
        self.assertEqual(review_summary["action_queues"]["source_retry_indexes"], [])


if __name__ == "__main__":
    unittest.main()
