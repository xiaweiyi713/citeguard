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
        self.assertEqual(report.risk_ranking[0]["risk_reason"], "no_strong_match")
        self.assertEqual(report.risk_ranking[0]["next_action"], "resolve_identifier_or_replace")
        self.assertEqual(report.risk_ranking[0]["suggested_fix"]["kind"], "add_identifier_or_replace")
        self.assertTrue(report.risk_ranking[0]["suggested_fix"]["requires_user_confirmation"])
        self.assertEqual(report.risk_ranking[0]["suggested_fix"]["policy"], "not_found_is_high_risk_not_fabrication_proof")
        self.assertEqual(report.risk_ranking[1]["next_action"], "review_metadata")
        self.assertEqual(report.risk_ranking[1]["risk_reason"], "metadata_fields_mismatch")
        self.assertEqual(report.risk_ranking[1]["suggested_fix"]["kind"], "review_metadata_correction")
        self.assertEqual(report.risk_ranking[1]["suggested_fix"]["mismatched_fields"], ["year"])
        self.assertEqual(report.risk_ranking[-1]["next_action"], "keep")
        self.assertEqual(report.risk_ranking[-1]["risk"], "low")
        self.assertEqual(report.risk_ranking[-1]["risk_reason"], "metadata_verified")
        self.assertEqual(report.risk_ranking[-1]["suggested_fix"]["kind"], "keep")
        self.assertIn("recommendation", report.to_dict()["risk_ranking"][0])
        review_summary = report.to_dict()["review_summary"]
        batch_execution = report.to_dict()["batch_execution"]
        self.assertEqual(batch_execution["progress"], {"completed_items": 3, "total_items": 3, "fraction": 1.0})
        self.assertTrue(batch_execution["input_order_preserved"])
        self.assertFalse(batch_execution["streaming"])
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
        self.assertEqual(review_summary["triage_plan"]["schema_version"], 1)
        self.assertEqual(review_summary["triage_plan"]["status"], "review_required")
        self.assertEqual(review_summary["triage_plan"]["next_action"], "resolve_identifier_or_replace")
        self.assertEqual(review_summary["triage_plan"]["first_queue"], "identity_resolution_indexes")
        self.assertEqual(review_summary["triage_plan"]["review_required_indexes"], [2, 1])
        self.assertEqual(review_summary["triage_plan"]["high_risk_indexes"], [2])
        self.assertEqual(review_summary["triage_plan"]["medium_risk_indexes"], [1])
        self.assertEqual(review_summary["triage_plan"]["safe_to_keep_indexes"], [0])
        self.assertIn(
            "source_retry_is_inconclusive_not_fabrication",
            review_summary["triage_plan"]["policy"],
        )

    def test_risk_ranking_exposes_source_metadata_quality(self):
        sparse_record = CitationRecord(
            citation_id="sparse",
            title="Sparse Source Metadata for Citation Audits",
            authors=["Ada Lovelace"],
            year=2026,
            doi="10.5555/sparse",
            source="crossref",
            metadata={
                "metadata_quality": {
                    "schema_version": 1,
                    "present_fields": ["title", "authors", "year", "identifier"],
                    "missing_fields": ["venue", "abstract", "url"],
                    "identifiers": {"doi": True, "arxiv_id": False},
                    "completeness": 0.5714,
                    "confidence_effect": "missing_metadata_lowers_confidence_not_fabrication_evidence",
                }
            },
        )
        report = audit_citations(
            [parse_citation(title="Sparse Source Metadata for Citation Audits", year=2026)],
            InMemoryMetadataSource([sparse_record]),
        )

        risk_item = report.to_dict()["risk_ranking"][0]
        self.assertEqual(risk_item["verdict"], "verified")
        self.assertEqual(risk_item["source_metadata_missing_fields"], ["venue", "abstract", "url"])
        self.assertEqual(
            risk_item["source_metadata_confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )
        self.assertEqual(risk_item["canonical_metadata_quality"]["identifiers"]["doi"], True)
        triage_plan = report.to_dict()["review_summary"]["triage_plan"]
        self.assertEqual(triage_plan["status"], "clear")
        self.assertEqual(triage_plan["next_action"], "keep")
        self.assertEqual(triage_plan["safe_to_keep_indexes"], [0])
        self.assertEqual(triage_plan["review_required_indexes"], [])


if __name__ == "__main__":
    unittest.main()
