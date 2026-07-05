"""Tests for single-citation verification."""

import unittest

from citeguard.verification import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource, MultiSourceMetadataSource
from citeguard.verification.models import Verdict
from citeguard.verification.parse import parse_citation
from citeguard.verification.verify import verify_citation


class VerifyTests(unittest.TestCase):
    def setUp(self):
        self.real = CitationRecord(
            citation_id="ghostcite",
            title="GhostCite: A Large-Scale Analysis of Citation Validity",
            authors=["Zhe Xu", "Lin Wang"],
            year=2026,
            venue="arXiv",
            doi="10.48550/arxiv.2602.06718",
            source="memory",
        )
        self.source = InMemoryMetadataSource([self.real])

    def test_correct_citation_is_verified(self):
        candidate = parse_citation(
            title="GhostCite: A Large-Scale Analysis of Citation Validity",
            authors=["Zhe Xu"],
            year=2026,
        )
        result = verify_citation(candidate, self.source)
        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.suggested_citation, "")

    def test_wrong_year_is_metadata_mismatch_with_suggestion(self):
        candidate = parse_citation(
            title="GhostCite: A Large-Scale Analysis of Citation Validity",
            authors=["Zhe Xu"],
            year=2021,
        )
        result = verify_citation(candidate, self.source)
        self.assertEqual(result.verdict, Verdict.METADATA_MISMATCH)
        self.assertIn("year", [diff.field for diff in result.field_diffs if not diff.matches])
        self.assertTrue(result.suggested_citation)

    def test_fabricated_citation_is_not_found(self):
        candidate = parse_citation(title="Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks")
        result = verify_citation(candidate, self.source)
        self.assertEqual(result.verdict, Verdict.NOT_FOUND)
        self.assertIn("Could not be verified", result.explanation)

    def test_not_found_notes_no_matching_record_when_sources_return_empty(self):
        empty_source = InMemoryMetadataSource([])
        candidate = parse_citation(title="Anything At All")
        result = verify_citation(candidate, empty_source)
        self.assertEqual(result.verdict, Verdict.NOT_FOUND)
        self.assertEqual(result.sources_responded, [])
        self.assertEqual(result.source_failure_mode, "none")
        self.assertFalse(result.outage_limited)
        self.assertEqual(result.to_dict()["sources_available"], ["metadata_source"])
        self.assertIn("No source returned a matching record", result.explanation)

    def test_source_failure_is_reported_without_blocking_other_sources(self):
        candidate = parse_citation(
            title="GhostCite: A Large-Scale Analysis of Citation Validity",
            authors=["Zhe Xu"],
            year=2026,
        )
        source = MultiSourceMetadataSource([FailingMetadataSource(), self.source])

        result = verify_citation(candidate, source)

        self.assertEqual(result.verdict, Verdict.VERIFIED)
        self.assertEqual(result.confidence, 0.85)
        self.assertEqual(result.source_failure_mode, "partial_outage")
        self.assertFalse(result.outage_limited)
        self.assertIn("failing_source", result.sources_failed)
        self.assertIn("memory", result.sources_responded)
        self.assertIn("Confidence is reduced", result.explanation)
        self.assertEqual(result.to_dict()["sources_available"], ["metadata_source"])
        self.assertEqual(result.source_failure_details[0]["source"], "failing_source")
        self.assertEqual(result.source_failure_details[0]["code"], "timeout")
        self.assertEqual(result.source_failure_details[0]["kind"], "timeout")
        self.assertEqual(result.to_dict()["source_failure_details"][0]["error"], "TimeoutError")

    def test_all_sources_failed_not_found_is_low_confidence_and_outage_limited(self):
        candidate = parse_citation(title="Slow Source Paper")
        result = verify_citation(candidate, FailingMetadataSource())

        self.assertEqual(result.verdict, Verdict.NOT_FOUND)
        self.assertEqual(result.confidence, 0.35)
        self.assertEqual(result.source_failure_mode, "all_sources_failed")
        self.assertTrue(result.outage_limited)
        self.assertEqual(result.to_dict()["sources_available"], [])
        self.assertEqual(result.to_dict()["recovery_code"], "timeout")
        self.assertIn("inconclusive", result.explanation)
        self.assertTrue(result.to_dict()["outage_limited"])

    def test_ambiguous_citation_exposes_recovery_code(self):
        twin_a = CitationRecord(citation_id="a", title="Deep Learning for Citation Analysis", year=2022, source="memory")
        twin_b = CitationRecord(citation_id="b", title="Deep Learning for Citation Analyses", year=2022, source="memory")
        result = verify_citation(
            parse_citation(title="Deep Learning for Citation Analysis"),
            InMemoryMetadataSource([twin_a, twin_b]),
        )

        payload = result.to_dict()
        self.assertEqual(result.verdict, Verdict.AMBIGUOUS)
        self.assertEqual(payload["recovery_code"], "ambiguous_citation")
        self.assertGreaterEqual(len(payload["alternatives"]), 1)


class FailingMetadataSource(InMemoryMetadataSource):
    name = "failing_source"

    def __init__(self):
        super().__init__([])

    def search(self, query, top_k=5):
        raise TimeoutError("source timed out")

    def lookup(self, candidate):
        raise TimeoutError("source timed out")


if __name__ == "__main__":
    unittest.main()
