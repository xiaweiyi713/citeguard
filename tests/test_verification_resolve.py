"""Tests for citation resolution."""

import unittest

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource, MultiSourceMetadataSource
from src.verification.parse import parse_citation
from src.verification.resolve import (
    STRONG_MATCH,
    resolve_citation,
    source_names,
    verification_match_score,
)


class ResolveTests(unittest.TestCase):
    def setUp(self):
        self.openscholar = CitationRecord(
            citation_id="openscholar",
            title="OpenScholar: Synthesizing Scientific Literature with Retrieval-augmented LMs",
            authors=["Akari Asai", "Jacqueline He"],
            year=2024,
            venue="arXiv",
            doi="10.48550/arxiv.2411.14199",
            source="memory",
        )
        self.source = InMemoryMetadataSource([self.openscholar])

    def test_title_match_reaches_strong_threshold_without_doi(self):
        candidate = parse_citation(
            title="OpenScholar: Synthesizing Scientific Literature with Retrieval-augmented LMs",
            authors=["Akari Asai"],
            year=2024,
        )
        score = verification_match_score(candidate, self.openscholar)
        self.assertGreaterEqual(score, STRONG_MATCH)

    def test_doi_match_is_definitive(self):
        candidate = parse_citation(title="Totally Different Title", doi="10.48550/arXiv.2411.14199")
        self.assertEqual(verification_match_score(candidate, self.openscholar), 1.0)

    def test_resolve_returns_best_match(self):
        candidate = parse_citation(title=self.openscholar.title, year=2024)
        outcome = resolve_citation(candidate, self.source)
        self.assertIsNotNone(outcome.best)
        self.assertEqual(outcome.best.citation_id, "openscholar")
        self.assertGreaterEqual(outcome.score, STRONG_MATCH)
        self.assertFalse(outcome.ambiguous)

    def test_resolve_unknown_title_returns_no_strong_match(self):
        candidate = parse_citation(title="A Completely Unrelated Quantum Chemistry Paper")
        outcome = resolve_citation(candidate, self.source)
        self.assertTrue(outcome.best is None or outcome.score < STRONG_MATCH)

    def test_resolve_flags_ambiguous_near_duplicates(self):
        twin_a = CitationRecord(citation_id="a", title="Deep Learning for Citation Analysis", year=2022, source="memory")
        twin_b = CitationRecord(citation_id="b", title="Deep Learning for Citation Analyses", year=2022, source="memory")
        source = InMemoryMetadataSource([twin_a, twin_b])
        candidate = parse_citation(title="Deep Learning for Citation Analysis")
        outcome = resolve_citation(candidate, source)
        self.assertTrue(outcome.ambiguous)

    def test_source_names_unwraps_multi_source(self):
        multi = MultiSourceMetadataSource([self.source])
        self.assertIsInstance(source_names(multi), list)


if __name__ == "__main__":
    unittest.main()
