"""Tests for the SQLite-backed caching metadata source."""

import json
import os
import sqlite3
import tempfile
import unittest
from dataclasses import asdict

from citeguard.verification import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.verification.cache import (
    CACHE_SCHEMA_VERSION,
    CachingMetadataSource,
    clear_cache,
    export_cache_records,
    inspect_cache,
)


class _CountingSource(InMemoryMetadataSource):
    def __init__(self, records):
        super().__init__(records)
        self.search_calls = 0

    def search(self, query, top_k=5):
        self.search_calls += 1
        return super().search(query, top_k=top_k)


class _PartiallyFailingSource(_CountingSource):
    def __init__(self, records):
        super().__init__(records)
        self.last_failures = ["openalex"]


class _HTTPDiagnostics:
    def __init__(self):
        self.last_error_code = ""

    def fail(self):
        self.last_error_code = "source_unavailable"

    def clear(self):
        self.last_error_code = ""


class _HTTPFailingSearchSource(_CountingSource):
    def __init__(self, records):
        super().__init__(records)
        self.http_client = _HTTPDiagnostics()

    def search(self, query, top_k=5):
        self.search_calls += 1
        self.http_client.fail()
        return self.all_records()[:top_k]


class _HTTPFailingLookupSource(_CountingSource):
    def __init__(self, records):
        super().__init__(records)
        self.http_client = _HTTPDiagnostics()
        self.lookup_calls = 0

    def lookup(self, candidate):
        self.lookup_calls += 1
        self.http_client.fail()
        return None


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

    def test_partial_source_failures_are_not_cached(self):
        inner = _PartiallyFailingSource([self.record])
        cached = CachingMetadataSource(inner, db_path=":memory:")

        cached.search("citation hallucination", top_k=5)
        cached.search("citation hallucination", top_k=5)

        self.assertEqual(inner.search_calls, 2)

    def test_single_source_http_search_failures_are_not_cached(self):
        inner = _HTTPFailingSearchSource([self.record])
        cached = CachingMetadataSource(inner, db_path=":memory:")

        cached.search("citation hallucination", top_k=5)
        cached.search("citation hallucination", top_k=5)

        self.assertEqual(inner.search_calls, 2)

    def test_single_source_http_lookup_failures_are_not_cached(self):
        inner = _HTTPFailingLookupSource([self.record])
        cached = CachingMetadataSource(inner, db_path=":memory:")
        candidate = CitationRecord(citation_id="candidate", title=self.record.title)

        self.assertIsNone(cached.lookup(candidate))
        self.assertIsNone(cached.lookup(candidate))

        self.assertEqual(inner.lookup_calls, 2)

    def test_inspect_and_clear_cache_report_schema_and_counts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.inner, db_path=path)
            cached.search("citation hallucination", top_k=5)
            before = inspect_cache(path)

            cleared = clear_cache(path)
            after = inspect_cache(path)

        self.assertEqual(before["schema_version"], CACHE_SCHEMA_VERSION)
        self.assertEqual(before["entries"], 1)
        self.assertEqual(before["entry_prefixes"]["search"], 1)
        self.assertEqual(cleared["cleared_entries"], 1)
        self.assertEqual(after["entries"], 0)

    def test_export_cache_records_returns_offline_fixture_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.inner, db_path=path)
            cached.search("citation hallucination", top_k=5)
            exported = export_cache_records(path)

        self.assertTrue(exported["exists"])
        self.assertEqual(exported["schema_version"], CACHE_SCHEMA_VERSION)
        self.assertEqual(exported["cache_entry_count"], 1)
        self.assertEqual(exported["cache_entry_prefixes"]["search"], 1)
        self.assertIsNotNone(exported["cache_oldest_entry_timestamp"])
        self.assertIsNotNone(exported["cache_newest_entry_timestamp"])
        self.assertIsInstance(exported["exported_at"], float)
        self.assertEqual(exported["record_count"], 1)
        self.assertEqual(exported["records"][0]["title"], self.record.title)
        self.assertEqual(exported["records"][0]["metadata"]["cache_key"], "search:citation hallucination:5")
        provenance = exported["records"][0]["metadata"]["cache_provenance"]
        self.assertEqual(provenance["operation"], "search")
        self.assertEqual(provenance["source"], "metadata_source")
        self.assertEqual(provenance["record_source"], "memory")
        self.assertEqual(provenance["query"], "citation hallucination")
        self.assertEqual(provenance["normalized_query"], "citation hallucination")
        self.assertIn("timestamp", provenance)
        self.assertIn("raw_match_score", provenance)
        self.assertIsInstance(exported["records"][0]["metadata"]["cache_raw_match_score"], float)

    def test_export_cache_records_can_strip_timestamp_provenance_for_deterministic_fixtures(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.inner, db_path=path)
            cached.search("citation hallucination", top_k=5)
            exported = export_cache_records(path, deterministic=True)

        metadata = exported["records"][0]["metadata"]
        provenance = metadata["cache_provenance"]
        self.assertTrue(exported["deterministic"])
        self.assertNotIn("cache_updated_at", metadata)
        self.assertNotIn("timestamp", provenance)
        self.assertEqual(provenance["operation"], "search")
        self.assertEqual(provenance["query"], "citation hallucination")
        self.assertIn("raw_match_score", provenance)

    def test_lookup_cache_records_candidate_match_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.inner, db_path=path)
            cached.lookup(CitationRecord(citation_id="candidate", title=self.record.title, year=2025))
            exported = export_cache_records(path)

        provenance = exported["records"][0]["metadata"]["cache_provenance"]
        self.assertEqual(provenance["operation"], "lookup")
        self.assertEqual(provenance["source"], "metadata_source")
        self.assertEqual(provenance["record_source"], "memory")
        self.assertEqual(provenance["query"], "title:citation hallucination in scientific writing")
        self.assertGreaterEqual(provenance["raw_match_score"], 0.25)

    def test_cache_schema_upgrade_preserves_legacy_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            conn = sqlite3.connect(path)
            conn.execute(
                "CREATE TABLE cache ("
                "key TEXT PRIMARY KEY, "
                "value TEXT, "
                "created_at REAL NOT NULL DEFAULT 0, "
                "updated_at REAL NOT NULL DEFAULT 0"
                ")"
            )
            conn.execute(
                "INSERT INTO cache (key, value, created_at, updated_at) VALUES (?, ?, ?, ?)",
                ("search:legacy:5", f"[{json.dumps(asdict(self.record))}]", 1.0, 2.0),
            )
            conn.commit()
            conn.close()

            info = inspect_cache(path)
            exported = export_cache_records(path)

        self.assertEqual(info["schema_version"], CACHE_SCHEMA_VERSION)
        self.assertEqual(exported["schema_version"], CACHE_SCHEMA_VERSION)
        self.assertEqual(exported["cache_entry_count"], 1)
        self.assertEqual(exported["record_count"], 1)
        self.assertEqual(exported["records"][0]["metadata"]["cache_key"], "search:legacy:5")

    def test_export_missing_cache_returns_empty_manifest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "missing.sqlite")
            exported = export_cache_records(path)

        self.assertFalse(exported["exists"])
        self.assertEqual(exported["schema_version"], CACHE_SCHEMA_VERSION)
        self.assertEqual(exported["cache_entry_count"], 0)
        self.assertEqual(exported["cache_entry_prefixes"]["search"], 0)
        self.assertEqual(exported["record_count"], 0)
        self.assertEqual(exported["records"], [])


if __name__ == "__main__":
    unittest.main()
