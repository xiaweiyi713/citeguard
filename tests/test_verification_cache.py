"""Tests for the SQLite-backed caching metadata source."""

import unittest

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource
from src.verification.cache import CachingMetadataSource


class _CountingSource(InMemoryMetadataSource):
    def __init__(self, records):
        super().__init__(records)
        self.search_calls = 0

    def search(self, query, top_k=5):
        self.search_calls += 1
        return super().search(query, top_k=top_k)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.record = CitationRecord(
            citation_id="r1",
            title="Citation Hallucination in Scientific Writing",
            authors=["A. Author"],
            year=2025,
            source="memory",
        )
        self.inner = _CountingSource([self.record])
        self.cached = CachingMetadataSource(self.inner, db_path=":memory:")

    def test_second_identical_search_hits_cache(self):
        first = self.cached.search("citation hallucination", top_k=5)
        second = self.cached.search("citation hallucination", top_k=5)
        self.assertEqual([r.citation_id for r in first], [r.citation_id for r in second])
        self.assertEqual(self.inner.search_calls, 1)

    def test_cache_roundtrip_preserves_fields(self):
        self.cached.search("citation hallucination", top_k=5)
        cached_again = self.cached.search("citation hallucination", top_k=5)
        self.assertEqual(cached_again[0].title, self.record.title)
        self.assertEqual(cached_again[0].year, 2025)
        self.assertEqual(cached_again[0].authors, ["A. Author"])

    def test_inner_is_exposed_for_unwrapping(self):
        self.assertIs(self.cached.inner, self.inner)


if __name__ == "__main__":
    unittest.main()
