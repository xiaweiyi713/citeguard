"""Tests for the SQLite-backed caching metadata source."""

import json
import os
import sqlite3
import tempfile
from concurrent.futures import ThreadPoolExecutor
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
        self.assertEqual(before["selected_entries"], 1)
        self.assertEqual(before["selected_entry_prefixes"]["search"], 1)
        self.assertEqual(before["inspect_filters"], {"operation": None, "source": None})
        self.assertEqual(cleared["cleared_entries"], 1)
        self.assertEqual(cleared["remaining_entries"], 0)
        self.assertEqual(cleared["clear_filters"], {"operation": None, "source": None})
        self.assertEqual(cleared["selected_entry_prefixes"]["search"], 1)
        self.assertEqual(after["entries"], 0)

    def test_clear_cache_can_filter_by_operation_and_preserve_other_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.inner, db_path=path)
            cached.search("citation hallucination", top_k=5)
            cached.lookup(CitationRecord(citation_id="candidate", title=self.record.title, year=2025))

            cleared = clear_cache(path, operation="lookup")
            after_lookup_clear = inspect_cache(path)
            final_clear = clear_cache(path)

        self.assertEqual(cleared["cleared_entries"], 1)
        self.assertEqual(cleared["remaining_entries"], 1)
        self.assertEqual(cleared["clear_filters"], {"operation": "lookup", "source": None})
        self.assertEqual(cleared["selected_entry_prefixes"]["lookup"], 1)
        self.assertEqual(cleared["selected_entry_prefixes"]["search"], 0)
        self.assertEqual(after_lookup_clear["entries"], 1)
        self.assertEqual(after_lookup_clear["entry_prefixes"]["search"], 1)
        self.assertEqual(after_lookup_clear["entry_prefixes"]["lookup"], 0)
        self.assertEqual(final_clear["cleared_entries"], 1)
        self.assertEqual(final_clear["remaining_entries"], 0)

    def test_clear_cache_can_filter_by_source_without_deleting_nonmatches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.inner, db_path=path)
            cached.search("citation hallucination", top_k=5)

            missing_source_clear = clear_cache(path, source="openalex")
            after_missing_source_clear = inspect_cache(path)
            matching_source_clear = clear_cache(path, source="metadata_source")
            after_matching_source_clear = inspect_cache(path)

        self.assertEqual(missing_source_clear["cleared_entries"], 0)
        self.assertEqual(missing_source_clear["remaining_entries"], 1)
        self.assertEqual(missing_source_clear["clear_filters"], {"operation": None, "source": "openalex"})
        self.assertEqual(after_missing_source_clear["entries"], 1)
        self.assertEqual(after_missing_source_clear["entry_prefixes"]["search"], 1)
        self.assertEqual(matching_source_clear["cleared_entries"], 1)
        self.assertEqual(matching_source_clear["remaining_entries"], 0)
        self.assertEqual(matching_source_clear["clear_filters"], {"operation": None, "source": "metadata_source"})
        self.assertEqual(matching_source_clear["selected_entry_prefixes"]["search"], 1)
        self.assertEqual(after_matching_source_clear["entries"], 0)

    def test_inspect_cache_can_filter_by_operation_and_source_without_raw_queries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.inner, db_path=path)
            cached.search("citation hallucination", top_k=5)
            cached.lookup(CitationRecord(citation_id="candidate", title=self.record.title, year=2025))

            lookup_info = inspect_cache(path, operation="lookup")
            source_info = inspect_cache(path, source="metadata_source")
            missing_source_info = inspect_cache(path, source="openalex")

        self.assertEqual(lookup_info["entries"], 2)
        self.assertEqual(lookup_info["entry_prefixes"]["search"], 1)
        self.assertEqual(lookup_info["entry_prefixes"]["lookup"], 1)
        self.assertEqual(lookup_info["selected_entries"], 1)
        self.assertEqual(lookup_info["selected_entry_prefixes"]["lookup"], 1)
        self.assertEqual(lookup_info["selected_entry_prefixes"]["search"], 0)
        self.assertEqual(lookup_info["inspect_filters"], {"operation": "lookup", "source": None})
        self.assertNotIn("citation hallucination", json.dumps(lookup_info, sort_keys=True))
        self.assertEqual(source_info["selected_entries"], 2)
        self.assertEqual(source_info["inspect_filters"], {"operation": None, "source": "metadata_source"})
        self.assertEqual(missing_source_info["selected_entries"], 0)
        self.assertEqual(missing_source_info["selected_entry_prefixes"], {"search": 0, "lookup": 0, "other": 0})

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
        cache_key = exported["records"][0]["metadata"]["cache_key"]
        self.assertTrue(cache_key.startswith("search:"))
        self.assertTrue(cache_key.endswith(":citation hallucination:5"))
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
            exported_again = export_cache_records(path, deterministic=True)

        metadata = exported["records"][0]["metadata"]
        provenance = metadata["cache_provenance"]
        self.assertTrue(exported["deterministic"])
        self.assertEqual(exported, exported_again)
        self.assertIsNone(exported["exported_at"])
        self.assertIsNone(exported["cache_oldest_entry_timestamp"])
        self.assertIsNone(exported["cache_newest_entry_timestamp"])
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

    def test_export_cache_records_can_filter_by_operation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.inner, db_path=path)
            cached.search("citation hallucination", top_k=5)
            cached.lookup(CitationRecord(citation_id="candidate", title=self.record.title, year=2025))

            exported = export_cache_records(path, deterministic=True, operation="lookup")

        self.assertEqual(exported["cache_entry_count"], 2)
        self.assertEqual(exported["cache_entry_prefixes"]["search"], 1)
        self.assertEqual(exported["cache_entry_prefixes"]["lookup"], 1)
        self.assertEqual(exported["selected_cache_entry_count"], 1)
        self.assertEqual(exported["selected_cache_entry_prefixes"]["lookup"], 1)
        self.assertEqual(exported["selected_cache_entry_prefixes"]["search"], 0)
        self.assertEqual(exported["export_filters"]["operation"], "lookup")
        self.assertIsNone(exported["export_filters"]["source"])
        self.assertEqual(exported["record_count"], 1)
        self.assertEqual(exported["records"][0]["metadata"]["cache_provenance"]["operation"], "lookup")

    def test_export_cache_records_can_filter_by_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.inner, db_path=path)
            cached.search("citation hallucination", top_k=5)

            matching = export_cache_records(path, deterministic=True, source="metadata_source")
            missing = export_cache_records(path, deterministic=True, source="openalex")

        self.assertEqual(matching["selected_cache_entry_count"], 1)
        self.assertEqual(matching["record_count"], 1)
        self.assertEqual(matching["export_filters"]["source"], "metadata_source")
        self.assertEqual(missing["cache_entry_count"], 1)
        self.assertEqual(missing["selected_cache_entry_count"], 0)
        self.assertEqual(missing["record_count"], 0)
        self.assertEqual(missing["records"], [])

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

    def test_cache_namespace_prevents_cross_source_reuse(self):
        class _NamedSource(_CountingSource):
            def __init__(self, records, name):
                super().__init__(records)
                self.name = name

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            source_a = _NamedSource(
                [CitationRecord(citation_id="a", title=self.record.title, source="source_a")],
                "source_a",
            )
            source_b = _NamedSource(
                [CitationRecord(citation_id="b", title=self.record.title, source="source_b")],
                "source_b",
            )
            first = CachingMetadataSource(source_a, db_path=path).search("citation hallucination")
            second = CachingMetadataSource(source_b, db_path=path).search("citation hallucination")

        self.assertEqual(first[0].citation_id, "a")
        self.assertEqual(second[0].citation_id, "b")
        self.assertEqual(source_b.search_calls, 1)

    def test_positive_and_negative_entries_expire_with_separate_ttls(self):
        now = [100.0]
        positive_inner = _CountingSource([self.record])
        positive = CachingMetadataSource(
            positive_inner,
            ttl_seconds=10,
            negative_ttl_seconds=2,
            clock=lambda: now[0],
        )
        positive.search("citation hallucination")
        now[0] = 109.0
        positive.search("citation hallucination")
        now[0] = 111.0
        positive.search("citation hallucination")
        self.assertEqual(positive_inner.search_calls, 2)

        now[0] = 200.0
        negative_inner = _CountingSource([])
        negative = CachingMetadataSource(
            negative_inner,
            ttl_seconds=10,
            negative_ttl_seconds=2,
            clock=lambda: now[0],
        )
        negative.search("missing paper")
        now[0] = 201.0
        negative.search("missing paper")
        now[0] = 203.0
        negative.search("missing paper")
        self.assertEqual(negative_inner.search_calls, 2)

    def test_cache_connection_is_safe_across_worker_threads(self):
        cached = CachingMetadataSource(_CountingSource([self.record]), db_path=":memory:")
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: cached.search("citation hallucination"), range(2)))

        self.assertEqual([items[0].citation_id for items in results], ["r1", "r1"])

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
