"""Tests for citation resolution."""

import unittest

from citeguard.verification import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource, MultiSourceMetadataSource
from citeguard.verification.parse import parse_citation
from citeguard.verification.resolve import (
    STRONG_MATCH,
    resolve_citation,
    source_names,
    verification_match_score,
)


class FakeHTTPDiagnostics:
    def __init__(self):
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_error = ""
        self.last_status_code = None
        self.last_url = ""
        self.last_cache_hit = False

    def fail_rate_limited(self):
        self.last_error_code = "source_unavailable"
        self.last_error_kind = "rate_limited"
        self.last_error = "http_429"
        self.last_status_code = 429
        self.last_url = "https://api.example.test/lookup"
        self.last_cache_hit = False

    def clear(self):
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_error = ""
        self.last_status_code = 200
        self.last_url = "https://api.example.test/search"
        self.last_cache_hit = False


class LookupFailureThenSearchSuccessSource:
    name = "diagnostic_source"

    def __init__(self, record):
        self.record = record
        self.http_client = FakeHTTPDiagnostics()

    def all_records(self):
        return [self.record]

    def lookup(self, candidate):
        self.http_client.fail_rate_limited()
        return None

    def search(self, query, top_k=5):
        self.http_client.clear()
        return [self.record]


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

    def test_resolve_preserves_lookup_failure_diagnostics_after_successful_search(self):
        source = LookupFailureThenSearchSuccessSource(self.openscholar)
        candidate = parse_citation(title=self.openscholar.title, doi="10.48550/arxiv.2411.14199")

        outcome = resolve_citation(candidate, source)

        self.assertIsNotNone(outcome.best)
        self.assertEqual(outcome.sources_failed, ["diagnostic_source"])
        self.assertEqual(outcome.source_failure_details[0]["source"], "diagnostic_source")
        self.assertEqual(outcome.source_failure_details[0]["code"], "source_unavailable")
        self.assertEqual(outcome.source_failure_details[0]["kind"], "rate_limited")
        self.assertEqual(outcome.source_failure_details[0]["status_code"], 429)


if __name__ == "__main__":
    unittest.main()
