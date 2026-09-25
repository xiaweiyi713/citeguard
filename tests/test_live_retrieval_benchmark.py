"""Tests for real-source retrieval collection and observation contracts."""

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from citeguard.benchmark.live_retrieval import (
    LIVE_RETRIEVAL_OBSERVATION_EXPERIMENT_NAME,
    LiveRetrievalCase,
    audit_live_retrieval_collection,
    audit_live_retrieval_observations,
    observe_live_retrieval,
)
from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from scripts import audit_live_retrieval_benchmark as audit_script
from scripts import observe_live_retrieval_benchmark as observe_script
from scripts import summarize_live_retrieval_observations as summary_script
from scripts.release_package_gate import _record_live_retrieval_benchmark_campaign


ROOT = Path(__file__).resolve().parents[1]


class NamedSource(InMemoryMetadataSource):
    name = "openalex"


class FailingSource(NamedSource):
    def search(self, query, top_k=5):
        raise TimeoutError("live source timed out")

    def lookup(self, candidate):
        raise TimeoutError("live source timed out")


def _campaign():
    return {
        "schema_version": 1,
        "campaign_id": "live-test-v1",
        "targets": {
            "minimum_case_count": 3,
            "minimum_by_query_kind": {"doi": 1, "arxiv_id": 1, "title": 1},
            "minimum_observations_per_case": 1,
        },
        "allowed_values": {
            "benchmark_origin": ["real_source"],
            "rights_basis": ["public_metadata"],
        },
    }


def _dataset():
    return {
        "schema_version": 1,
        "campaign_id": "live-test-v1",
        "cases": [
            {
                "id": "lr-doi",
                "benchmark_origin": "real_source",
                "query_kind": "doi",
                "fields": {"doi": "10.1000/example-doi"},
                "expected_identity": {"doi": "10.1000/example-doi"},
                "ground_truth_locator": "doi:10.1000/example-doi",
                "rights_basis": "public_metadata",
                "lang": "en",
                "domain": "computer_science",
            },
            {
                "id": "lr-arxiv",
                "benchmark_origin": "real_source",
                "query_kind": "arxiv_id",
                "fields": {"arxiv_id": "1706.03762"},
                "expected_identity": {"arxiv_id": "1706.03762"},
                "ground_truth_locator": "arxiv:1706.03762",
                "rights_basis": "public_metadata",
                "lang": "en",
                "domain": "computer_science",
            },
            {
                "id": "lr-title",
                "benchmark_origin": "real_source",
                "query_kind": "title",
                "fields": {"title": "Known Title Observation"},
                "expected_identity": {"title": "Known Title Observation"},
                "ground_truth_locator": "https://example.invalid/known-title",
                "rights_basis": "public_metadata",
                "lang": "zh",
                "domain": "biomedicine",
            },
        ],
    }


def _records():
    return [
        CitationRecord(
            citation_id="doi-record",
            title="DOI Record",
            authors=["Example"],
            year=2020,
            doi="10.1000/example-doi",
        ),
        CitationRecord(
            citation_id="arxiv-record",
            title="Attention Is All You Need",
            authors=["Vaswani"],
            year=2017,
            arxiv_id="1706.03762",
        ),
        CitationRecord(
            citation_id="title-record",
            title="Known Title Observation",
            authors=["Example"],
            year=2021,
        ),
    ]


def _observation_artifact(dataset, campaign, timestamp, run_id, source=None):
    cases = [
        LiveRetrievalCase(
            case_id=row["id"],
            query_kind=row["query_kind"],
            fields=row["fields"],
            expected_identity=row["expected_identity"],
            ground_truth_locator=row["ground_truth_locator"],
            lang=row["lang"],
            domain=row["domain"],
            rights_basis=row["rights_basis"],
        )
        for row in dataset["cases"]
    ]
    observation = observe_live_retrieval(
        cases,
        {"openalex": source or NamedSource(_records())},
        observer_region="CN-Shanghai",
        observed_at=timestamp,
        monotonic=lambda: 0.0,
    )
    return {
        "artifact_path": f"/tmp/{run_id}",
        "manifest": {
            "schema_version": 1,
            "experiment_name": LIVE_RETRIEVAL_OBSERVATION_EXPERIMENT_NAME,
            "run_id": run_id,
            "files": {"result": "result.json", "config": "config.json", "manifest": "manifest.json"},
        },
        "config": {
            "script": "scripts/observe_live_retrieval_benchmark.py",
            "dataset": "fixture.json",
            "campaign": "fixture-campaign.json",
            "sources": ["openalex"],
            "observer_region": "CN-Shanghai",
        },
        "result": {
            "schema_version": 1,
            "collection": audit_live_retrieval_collection(dataset, campaign),
            "observation": observation,
            "benchmark_claim_safe": False,
        },
    }


class LiveRetrievalBenchmarkTests(unittest.TestCase):
    def test_default_collection_reports_pilot_progress_without_claiming_readiness(self):
        dataset = json.loads((ROOT / "data" / "eval" / "live_retrieval_benchmark.json").read_text(encoding="utf-8"))
        campaign = json.loads(
            (ROOT / "data" / "eval" / "live_retrieval_benchmark_campaign.json").read_text(encoding="utf-8")
        )

        report = audit_live_retrieval_collection(dataset, campaign)

        self.assertEqual(report["status"], "collection_incomplete")
        self.assertFalse(report["benchmark_claim_safe"])
        self.assertEqual(report["counts"]["qualified_real_cases"], 12)
        self.assertEqual(report["counts"]["qualified_by_query_kind"], {"arxiv_id": 4, "doi": 4, "title": 4})
        self.assertEqual(report["next_action"], "continue_balanced_case_collection")

    def test_observation_splits_identity_latency_and_source_limit_metrics(self):
        cases = [
            LiveRetrievalCase(
                case_id=row["id"],
                query_kind=row["query_kind"],
                fields=row["fields"],
                expected_identity=row["expected_identity"],
                ground_truth_locator=row["ground_truth_locator"],
                lang=row["lang"],
                domain=row["domain"],
                rights_basis=row["rights_basis"],
            )
            for row in _dataset()["cases"]
        ]
        ticks = iter([0.0, 0.010, 0.100, 0.130, 0.200, 0.260])
        report = observe_live_retrieval(
            cases,
            {"openalex": NamedSource(_records())},
            observer_region="CN-Shanghai",
            observed_at="2026-08-07T12:00:00Z",
            monotonic=lambda: next(ticks),
        )

        self.assertEqual(report["observation"]["observer_region"], "CN-Shanghai")
        self.assertEqual(report["observation"]["source_versions"]["openalex"]["source_api_version"], "not_disclosed")
        self.assertEqual(report["summary"]["attempt_count"], 3)
        self.assertEqual(report["summary"]["identity_accuracy"], 1.0)
        self.assertEqual(report["summary"]["source_limited_count"], 0)
        self.assertEqual(report["summary"]["latency_ms"]["p95"], 60.0)
        self.assertEqual(report["by_query_kind"]["doi"]["identity_accuracy"], 1.0)
        self.assertFalse(report["permanent_source_ranking_allowed"])

    def test_source_timeout_is_inconclusive_not_an_identity_miss(self):
        case = LiveRetrievalCase(
            case_id="timeout",
            query_kind="doi",
            fields={"doi": "10.1000/example-doi"},
            expected_identity={"doi": "10.1000/example-doi"},
            ground_truth_locator="doi:10.1000/example-doi",
            lang="en",
            domain="computer_science",
            rights_basis="public_metadata",
        )
        report = observe_live_retrieval(
            [case],
            {"openalex": FailingSource([])},
            observer_region="us-east-1",
            observed_at="2026-08-07T12:00:00Z",
        )

        self.assertEqual(report["summary"]["identity_accuracy_eligible_count"], 0)
        self.assertIsNone(report["summary"]["identity_accuracy"])
        self.assertEqual(report["summary"]["source_limited_count"], 1)
        self.assertEqual(report["rows"][0]["status"], "source_limited")
        self.assertNotEqual(report["rows"][0]["status"], "not_found")

    def test_registered_doi_or_arxiv_alias_can_establish_one_canonical_work(self):
        case = LiveRetrievalCase(
            case_id="alias",
            query_kind="doi",
            fields={"title": "Attention Is All You Need", "doi": "10.1000/doi-alias"},
            expected_identity={"doi": "10.1000/doi-alias", "arxiv_id": "1706.03762"},
            ground_truth_locator="https://doi.org/10.1000/doi-alias",
            lang="en",
            domain="computer_science",
            rights_basis="public_metadata",
        )
        source = NamedSource(
            [
                CitationRecord(
                    citation_id="arxiv-alias",
                    title="Attention Is All You Need",
                    arxiv_id="1706.03762v7",
                )
            ]
        )
        report = observe_live_retrieval(
            [case],
            {"openalex": source},
            observer_region="CN-Shanghai",
            observed_at="2026-08-07T12:00:00Z",
        )
        self.assertTrue(report["rows"][0]["identity_match"])
        self.assertEqual(report["summary"]["identity_accuracy"], 1.0)

    def test_longitudinal_summary_requires_three_distinct_eligible_timestamps(self):
        campaign = _campaign()
        campaign["targets"]["minimum_observations_per_case"] = 3
        dataset = _dataset()
        artifacts = [
            _observation_artifact(dataset, campaign, "2026-08-07T12:00:00Z", "run-one"),
            _observation_artifact(dataset, campaign, "2026-08-07T12:00:00Z", "run-one-repeat"),
            _observation_artifact(dataset, campaign, "2026-08-08T12:00:00Z", "run-two"),
        ]

        incomplete = audit_live_retrieval_observations(dataset, campaign, artifacts)

        self.assertEqual(incomplete["status"], "observation_incomplete")
        self.assertEqual(incomplete["coverage"]["by_case"]["lr-doi"]["recorded_observation_count"], 2)
        self.assertEqual(incomplete["coverage"]["by_case"]["lr-doi"]["eligible_observation_count"], 2)
        self.assertEqual(
            incomplete["coverage"]["case_ids_below_minimum_eligible_observations"],
            ["lr-arxiv", "lr-doi", "lr-title"],
        )

        ready = audit_live_retrieval_observations(
            dataset,
            campaign,
            artifacts + [_observation_artifact(dataset, campaign, "2026-08-09T12:00:00Z", "run-three")],
        )

        self.assertEqual(ready["status"], "ready")
        self.assertTrue(ready["benchmark_claim_safe"])
        self.assertEqual(ready["summary"]["attempt_count"], 12)
        self.assertEqual(ready["summary"]["identity_accuracy"], 1.0)
        self.assertEqual(ready["counts"]["distinct_observed_at_count"], 3)
        self.assertFalse(ready["permanent_source_ranking_allowed"])

    def test_longitudinal_summary_does_not_credit_source_limited_timestamps(self):
        campaign = _campaign()
        campaign["targets"]["minimum_observations_per_case"] = 3
        dataset = _dataset()
        report = audit_live_retrieval_observations(
            dataset,
            campaign,
            [
                _observation_artifact(dataset, campaign, "2026-08-07T12:00:00Z", "limited", FailingSource([])),
                _observation_artifact(dataset, campaign, "2026-08-08T12:00:00Z", "healthy-one"),
                _observation_artifact(dataset, campaign, "2026-08-09T12:00:00Z", "healthy-two"),
            ],
        )

        self.assertEqual(report["status"], "observation_incomplete")
        self.assertEqual(report["coverage"]["by_case"]["lr-doi"]["recorded_observation_count"], 3)
        self.assertEqual(report["coverage"]["by_case"]["lr-doi"]["eligible_observation_count"], 2)
        self.assertEqual(report["coverage"]["by_case"]["lr-doi"]["source_limited_only_observation_count"], 1)
        self.assertEqual(report["summary"]["identity_accuracy_eligible_count"], 6)
        self.assertEqual(report["summary"]["source_limited_count"], 3)

    def test_longitudinal_summary_rejects_stale_case_provenance(self):
        campaign = _campaign()
        dataset = _dataset()
        artifact = _observation_artifact(dataset, campaign, "2026-08-07T12:00:00Z", "tampered")
        artifact["result"]["observation"]["rows"][0]["case_sha256"] = "sha256:stale"

        report = audit_live_retrieval_observations(dataset, campaign, [artifact])

        self.assertEqual(report["status"], "observation_invalid")
        self.assertEqual(report["artifacts"]["valid_count"], 0)
        self.assertIn("rows[0]_case_sha256_mismatch", report["artifacts"]["invalid_artifacts"][0]["issues"])

    def test_summary_script_reads_archived_artifacts_without_network_access(self):
        campaign = _campaign()
        campaign["targets"]["minimum_observations_per_case"] = 3
        dataset = _dataset()
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            dataset_path = temp_path / "dataset.json"
            campaign_path = temp_path / "campaign.json"
            dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
            campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
            observation_stdout = io.StringIO()
            with mock.patch.object(observe_script, "_build_sources", return_value={"openalex": NamedSource(_records())}):
                with redirect_stdout(observation_stdout):
                    observation_code = observe_script.main(
                        [
                            "--dataset",
                            str(dataset_path),
                            "--campaign",
                            str(campaign_path),
                            "--source",
                            "openalex",
                            "--observer-region",
                            "CN-Shanghai",
                            "--mailto",
                            "research-contact@example.org",
                            "--output-dir",
                            temp_dir,
                            "--run-id",
                            "archived",
                        ]
                    )
            observation_payload = json.loads(observation_stdout.getvalue())
            persisted_result = json.loads(
                Path(observation_payload["experiment_artifact"]["files"]["result"]).read_text(encoding="utf-8")
            )
            summary_stdout = io.StringIO()
            with redirect_stdout(summary_stdout):
                code = summary_script.main(
                    [
                        "--dataset",
                        str(dataset_path),
                        "--campaign",
                        str(campaign_path),
                        "--artifact-dir",
                        observation_payload["experiment_artifact"]["path"],
                    ]
                )

        payload = json.loads(summary_stdout.getvalue())
        self.assertEqual(observation_code, 0)
        self.assertEqual(persisted_result["schema_version"], 1)
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "observation_incomplete")
        self.assertEqual(payload["artifacts"]["valid_count"], 1)

    def test_release_gate_reports_live_collection_readiness_without_blocking_software_validation(self):
        summary = {"ok": True, "steps": []}

        _record_live_retrieval_benchmark_campaign(
            summary,
            project_root=ROOT,
            dataset="data/eval/live_retrieval_benchmark.json",
            campaign="data/eval/live_retrieval_benchmark_campaign.json",
            observation_artifact_dirs=[],
        )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "live_retrieval_benchmark_campaign")
        self.assertEqual(summary["steps"][0]["status"], "incomplete")
        self.assertEqual(summary["steps"][0]["collection_status"], "collection_incomplete")
        self.assertFalse(summary["steps"][0]["benchmark_claim_safe"])

    def test_collection_and_observation_scripts_stay_non_networked_when_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            dataset_path = temp_path / "dataset.json"
            campaign_path = temp_path / "campaign.json"
            dataset_path.write_text(
                json.dumps({"schema_version": 1, "campaign_id": "empty-live", "cases": []}),
                encoding="utf-8",
            )
            campaign_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "campaign_id": "empty-live",
                        "targets": {
                            "minimum_case_count": 1,
                            "minimum_by_query_kind": {"doi": 1, "arxiv_id": 1, "title": 1},
                            "minimum_observations_per_case": 1,
                        },
                        "allowed_values": {
                            "benchmark_origin": ["real_source"],
                            "rights_basis": ["public_metadata"],
                        },
                    }
                ),
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()):
                self.assertEqual(audit_script.main(["--dataset", str(dataset_path), "--campaign", str(campaign_path)]), 0)
                self.assertEqual(
                    audit_script.main(["--dataset", str(dataset_path), "--campaign", str(campaign_path), "--strict"]),
                    1,
                )
                self.assertEqual(
                    observe_script.main(["--dataset", str(dataset_path), "--campaign", str(campaign_path)]),
                    0,
                )
                self.assertEqual(
                    summary_script.main(["--dataset", str(dataset_path), "--campaign", str(campaign_path)]),
                    0,
                )
                self.assertEqual(
                    summary_script.main(
                        ["--dataset", str(dataset_path), "--campaign", str(campaign_path), "--strict"]
                    ),
                    1,
                )


if __name__ == "__main__":
    unittest.main()
