"""Tests for conservative real-record curation helpers."""

from __future__ import annotations

import unittest

from citeguard.benchmark.live_case_collection import (
    LiveCaseCollectionError,
    collect_live_retrieval_dataset,
    load_collection_requests,
    merge_collected_cases,
)
from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients.in_memory import InMemoryMetadataSource


class LiveCaseCollectionTests(unittest.TestCase):
    def setUp(self):
        self.source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="canonical",
                    title="Known Paper",
                    authors=["A. Author"],
                    year=2020,
                    venue="Journal",
                    abstract="A public abstract.",
                    doi="10.1000/known",
                    arxiv_id="2001.00001",
                    url="https://doi.org/10.1000/known",
                ),
                CitationRecord(
                    citation_id="polluted",
                    title="Known Paper",
                    year=2025,
                    doi="10.9999/polluted",
                    url="https://example.invalid/polluted",
                ),
            ]
        )

    def test_manifest_normalizes_identifiers_and_requires_dimensions(self):
        requests = load_collection_requests(
            {
                "requests": [
                    {
                        "id": "doi-case",
                        "query_kind": "doi",
                        "query": "https://doi.org/10.1000/KNOWN",
                        "lang": "en",
                        "domain": "computer_science",
                    }
                ]
            }
        )
        self.assertEqual(requests[0].query, "10.1000/known")
        with self.assertRaises(LiveCaseCollectionError):
            load_collection_requests({"requests": [{"id": "bad", "query_kind": "doi", "query": "x"}]})

    def test_identifier_and_expected_title_cases_are_curated(self):
        requests = load_collection_requests(
            {
                "requests": [
                    {
                        "id": "doi-case",
                        "query_kind": "doi",
                        "query": "10.1000/known",
                        "lang": "en",
                        "domain": "computer_science",
                    },
                    {
                        "id": "title-case",
                        "query_kind": "title",
                        "query": "Known Paper",
                        "expected_identity": {"doi": "10.1000/known"},
                        "lang": "en",
                        "domain": "computer_science",
                    },
                ]
            }
        )
        payload = collect_live_retrieval_dataset(requests, {"fixture": self.source}, collected_at="2026-08-07T12:00:00Z")
        self.assertEqual(payload["report"]["accepted_count"], 2)
        self.assertEqual(payload["report"]["rejected_count"], 0)
        title_case = next(row for row in payload["cases"] if row["id"] == "title-case")
        self.assertEqual(title_case["expected_identity"], {"doi": "10.1000/known"})
        self.assertNotIn("doi", title_case["fields"])
        self.assertEqual(title_case["metadata_snapshot"]["abstract"], "A public abstract.")

    def test_title_only_ambiguous_candidates_are_rejected(self):
        requests = load_collection_requests(
            {
                "requests": [
                    {
                        "id": "ambiguous",
                        "query_kind": "title",
                        "query": "Known Paper",
                        "lang": "en",
                        "domain": "computer_science",
                    }
                ]
            }
        )
        payload = collect_live_retrieval_dataset(requests, {"fixture": self.source}, collected_at="2026-08-07T12:00:00Z")
        self.assertEqual(payload["report"]["accepted_count"], 0)
        self.assertEqual(payload["report"]["rejected"][0]["reason"], "no_verified_candidate")

    def test_merge_protects_existing_case_ids(self):
        base = {"schema_version": 1, "campaign_id": "citeguard-live-retrieval-v1", "cases": []}
        collected = {
            "collected_at": "2026-08-07T12:00:00Z",
            "collector": {},
            "cases": [{"id": "one", "benchmark_origin": "real_source"}],
        }
        merged = merge_collected_cases(base, collected)
        self.assertEqual([row["id"] for row in merged["cases"]], ["one"])
        with self.assertRaises(LiveCaseCollectionError):
            merge_collected_cases(merged, collected)


if __name__ == "__main__":
    unittest.main()
