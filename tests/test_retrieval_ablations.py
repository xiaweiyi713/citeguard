"""Tests for deterministic and source-limited retrieval ablation reporting."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from citeguard.benchmark.retrieval_ablations import (
    RETRIEVAL_ABLATION_SOURCE_NAMES,
    build_offline_snapshot_sources,
    load_retrieval_ablation_dataset,
    run_retrieval_source_ablation,
    validate_retrieval_ablation_dataset,
)
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource


ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "data" / "eval" / "retrieval_source_eval.json"


class FailingSnapshotSource(InMemoryMetadataSource):
    name = "openalex"

    def search(self, query, top_k=5):
        raise TimeoutError("snapshot source timed out")

    def lookup(self, candidate):
        raise TimeoutError("snapshot source timed out")


class RetrievalAblationTests(unittest.TestCase):
    def setUp(self):
        self.dataset = load_retrieval_ablation_dataset(str(DATASET_PATH))

    def test_seed_fixture_declares_stable_sources_and_safety_policy(self):
        self.assertEqual(self.dataset.schema_version, 1)
        self.assertEqual(
            self.dataset.snapshot_sources,
            ("in_memory", "openalex", "crossref", "arxiv", "semantic_scholar"),
        )
        self.assertEqual(RETRIEVAL_ABLATION_SOURCE_NAMES[-1], "multi_source")
        self.assertIn("not a captured live-source benchmark", self.dataset.snapshot_policy["notes"])
        self.assertGreaterEqual(len(self.dataset.cases), 8)

    def test_offline_matrix_is_deterministic_but_forbids_permanent_source_rankings(self):
        sources = build_offline_snapshot_sources(self.dataset)

        result = run_retrieval_source_ablation(self.dataset, sources)

        self.assertTrue(result["deterministic"])
        self.assertTrue(result["matrix_complete"])
        self.assertFalse(result["permanent_source_ranking_allowed"])
        self.assertEqual(result["completed_sources"], list(RETRIEVAL_ABLATION_SOURCE_NAMES))
        self.assertEqual(result["source_limited_sources"], [])
        rows = {row["source"]: row for row in result["comparison"]}
        self.assertEqual(rows["multi_source"]["accuracy"], 1.0)
        self.assertGreater(rows["crossref"]["real_citation_not_found_rate"], 0.0)
        self.assertGreater(rows["crossref"]["verified_not_found_rate"], 0.0)
        self.assertNotIn("false_accusation_rate", rows["crossref"])
        self.assertTrue(all(row["regression_comparison_allowed"] for row in rows.values()))
        self.assertTrue(all(not row["quality_comparison_allowed"] for row in rows.values()))
        self.assertIn("not_found_is_unresolved_not_fabrication", result["policy"])

    def test_source_outage_is_source_limited_not_source_quality_evidence(self):
        result = run_retrieval_source_ablation(
            self.dataset,
            {"openalex": FailingSnapshotSource([])},
            ["openalex"],
            mode="live",
        )

        self.assertEqual(result["source_limited_sources"], ["openalex"])
        self.assertFalse(result["deterministic"])
        self.assertFalse(result["permanent_source_ranking_allowed"])
        row = result["comparison"][0]
        self.assertEqual(row["status"], "source_limited")
        self.assertFalse(row["quality_comparison_allowed"])
        self.assertFalse(row["regression_comparison_allowed"])
        self.assertEqual(row["sources_failed"], ["openalex"])
        self.assertTrue(row["source_limited_case_ids"])

    def test_missing_requested_source_is_unavailable_without_fake_metrics(self):
        result = run_retrieval_source_ablation(
            self.dataset,
            {},
            ["semantic_scholar"],
        )

        self.assertEqual(result["unavailable_sources"], ["semantic_scholar"])
        row = result["comparison"][0]
        self.assertEqual(row["status"], "unavailable")
        self.assertNotIn("accuracy", row)

    def test_dataset_validator_rejects_live_benchmark_overclaim(self):
        payload = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        unsafe = copy.deepcopy(payload)
        unsafe["snapshot_policy"]["notes"] = "Permanent live source benchmark."

        with self.assertRaisesRegex(ValueError, "prohibit live-source benchmark claims"):
            validate_retrieval_ablation_dataset(unsafe)


if __name__ == "__main__":
    unittest.main()
