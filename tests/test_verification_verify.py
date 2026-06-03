"""Tests for single-citation verification."""

import unittest

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource
from src.verification.models import Verdict
from src.verification.parse import parse_citation
from src.verification.verify import verify_citation


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
        candidate = parse_citation(title="Quantum Teleportation of Citation Hallucinations in Llamas")
        result = verify_citation(candidate, self.source)
        self.assertEqual(result.verdict, Verdict.NOT_FOUND)
        self.assertIn("Could not be verified", result.explanation)

    def test_not_found_notes_possible_outage_when_no_source_responded(self):
        empty_source = InMemoryMetadataSource([])
        candidate = parse_citation(title="Anything At All")
        result = verify_citation(candidate, empty_source)
        self.assertEqual(result.verdict, Verdict.NOT_FOUND)
        self.assertEqual(result.sources_responded, [])
        self.assertIn("outage", result.explanation)


if __name__ == "__main__":
    unittest.main()
