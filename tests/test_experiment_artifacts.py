"""Tests for standardized benchmark experiment artifacts."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from citeguard.benchmark.experiments import (
    EXPERIMENT_ARTIFACT_SCHEMA_VERSION,
    write_experiment_artifacts,
)


class ExperimentArtifactTests(unittest.TestCase):
    def test_write_experiment_artifacts_creates_manifest_result_and_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = write_experiment_artifacts(
                "Support Eval",
                {"overall": {"accuracy": 1.0}, "quality_gate": {"ok": True}},
                {"dataset": "data/eval/support_eval.json", "split": "test"},
                output_dir=tmpdir,
                run_id="unit support run",
            )

            run_path = Path(artifact["path"])
            manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
            result = json.loads((run_path / "result.json").read_text(encoding="utf-8"))
            config = json.loads((run_path / "config.json").read_text(encoding="utf-8"))

        self.assertEqual(artifact["schema_version"], EXPERIMENT_ARTIFACT_SCHEMA_VERSION)
        self.assertEqual(artifact["run_id"], "unit-support-run")
        self.assertEqual(manifest["experiment_name"], "Support-Eval")
        self.assertEqual(manifest["result_summary"]["accuracy"], 1.0)
        self.assertTrue(manifest["result_summary"]["quality_gate_ok"])
        self.assertEqual(result["overall"]["accuracy"], 1.0)
        self.assertEqual(config["split"], "test")

    def test_manifest_summarizes_support_label_gate_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = write_experiment_artifacts(
                "support provenance",
                {
                    "label_sidecar_gate": {
                        "ok": True,
                        "metrics": {
                            "coverage": 1.0,
                            "human_reviewed": 0,
                            "high_risk_unreviewed": 35,
                            "full_text_required_unreviewed": 7,
                            "policy_boundary_unreviewed": 2,
                            "dual_annotated": 2,
                            "unresolved_disagreements": 1,
                            "supported_disagreements": 1,
                            "raw_dual_agreement_rate": 0.5,
                            "unresolved_disagreement_case_ids": ["s04"],
                            "supported_disagreement_case_ids": ["s04"],
                            "high_risk_case_count_by_language_case_type": {
                                "en": {"contradiction": 2, "hard_negative": 1},
                                "zh": {"full_text_required": 1},
                            },
                            "high_risk_reviewed_by_language_case_type": {
                                "en": {"contradiction": 1},
                            },
                            "high_risk_unreviewed_by_language_case_type": {
                                "en": {"contradiction": 1, "hard_negative": 1},
                                "zh": {"full_text_required": 1},
                            },
                            "label_source_counts": {"maintainer_synthetic": 54},
                            "reviewed_by_label_source": {},
                            "unreviewed_by_label_source": {"maintainer_synthetic": 54},
                            "reviewed_source_locator_count": 0,
                            "published_benchmark_source_locator_count": 0,
                            "sidecar_provenance_complete_count": 54,
                            "sidecar_provenance_complete_fraction": 1.0,
                            "sidecar_provenance_missing_count": 0,
                            "sidecar_provenance_missing_case_ids": [],
                            "sidecar_provenance_missing_case_ids_by_field": {},
                            "sidecar_provenance_field_present_counts": {
                                "label_source": 54,
                                "case_type": 54,
                            },
                            "dataset_cases": 54,
                            "sidecar_cases": 54,
                        },
                    }
                },
                {"script": "unit"},
                output_dir=tmpdir,
                run_id="support-label-summary",
            )

            run_path = Path(artifact["path"])
            manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))

        summary = manifest["result_summary"]
        self.assertTrue(summary["support_label_gate_ok"])
        self.assertEqual(summary["support_label_sidecar_coverage"], 1.0)
        self.assertEqual(summary["support_label_human_reviewed"], 0)
        self.assertEqual(summary["support_label_high_risk_unreviewed"], 35)
        self.assertEqual(summary["support_label_full_text_required_unreviewed"], 7)
        self.assertEqual(summary["support_label_policy_boundary_unreviewed"], 2)
        self.assertEqual(summary["support_label_dual_annotated"], 2)
        self.assertEqual(summary["support_label_unresolved_disagreements"], 1)
        self.assertEqual(summary["support_label_supported_disagreements"], 1)
        self.assertEqual(summary["support_label_raw_dual_agreement_rate"], 0.5)
        self.assertEqual(summary["support_label_unresolved_disagreement_case_ids"], ["s04"])
        self.assertEqual(summary["support_label_supported_disagreement_case_ids"], ["s04"])
        self.assertEqual(
            summary["support_label_high_risk_case_count_by_language_case_type"],
            {
                "en": {"contradiction": 2, "hard_negative": 1},
                "zh": {"full_text_required": 1},
            },
        )
        self.assertEqual(
            summary["support_label_high_risk_reviewed_by_language_case_type"],
            {"en": {"contradiction": 1}},
        )
        self.assertEqual(
            summary["support_label_high_risk_unreviewed_by_language_case_type"],
            {
                "en": {"contradiction": 1, "hard_negative": 1},
                "zh": {"full_text_required": 1},
            },
        )
        self.assertEqual(summary["support_label_label_source_counts"], {"maintainer_synthetic": 54})
        self.assertEqual(summary["support_label_reviewed_by_label_source"], {})
        self.assertEqual(summary["support_label_unreviewed_by_label_source"], {"maintainer_synthetic": 54})
        self.assertEqual(summary["support_label_reviewed_source_locator_count"], 0)
        self.assertEqual(summary["support_label_published_benchmark_source_locator_count"], 0)
        self.assertEqual(summary["support_label_sidecar_provenance_complete_count"], 54)
        self.assertEqual(summary["support_label_sidecar_provenance_complete_fraction"], 1.0)
        self.assertEqual(summary["support_label_sidecar_provenance_missing_count"], 0)
        self.assertEqual(summary["support_label_sidecar_provenance_missing_case_ids"], [])
        self.assertEqual(summary["support_label_sidecar_provenance_missing_case_ids_by_field"], {})
        self.assertEqual(
            summary["support_label_sidecar_provenance_field_present_counts"],
            {"label_source": 54, "case_type": 54},
        )
        self.assertEqual(summary["support_label_dataset_cases"], 54)
        self.assertEqual(summary["support_label_sidecar_cases"], 54)

    def test_manifest_summarizes_release_blockers(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = write_experiment_artifacts(
                "support eval",
                {
                    "quality_gate": {"ok": False},
                    "release_blocker_summary": {
                        "release_blocked": True,
                        "benchmark_claim_safe": False,
                        "blocking_count": 2,
                        "blocking_case_ids": ["s01", "s02"],
                        "review_required_count": 3,
                        "review_required_case_ids": ["s01", "s02", "s03"],
                        "next_action": "block_release_until_false_support_reviewed",
                    },
                },
                {"script": "unit"},
                output_dir=tmpdir,
                run_id="support-release-blockers",
            )

            run_path = Path(artifact["path"])
            manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))

        summary = manifest["result_summary"]
        self.assertFalse(summary["quality_gate_ok"])
        self.assertTrue(summary["release_blocked"])
        self.assertFalse(summary["benchmark_claim_safe"])
        self.assertEqual(summary["release_blocking_count"], 2)
        self.assertEqual(summary["release_blocking_case_ids"], ["s01", "s02"])
        self.assertEqual(summary["release_review_required_count"], 3)
        self.assertEqual(summary["release_review_required_case_ids"], ["s01", "s02", "s03"])
        self.assertEqual(summary["release_next_action"], "block_release_until_false_support_reviewed")

    def test_manifest_summarizes_support_release_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = write_experiment_artifacts(
                "support eval",
                {
                    "overall": {
                        "supported_precision": 0.5,
                        "supported_recall": 0.25,
                        "supported_f1": 0.3333,
                        "macro_f1": 0.4,
                        "weighted_f1": 0.45,
                        "false_support_rate": 0.2,
                        "abstention_rate": 0.3,
                        "contradiction_recall": 0.0,
                    },
                    "release_summary": {
                        "schema_version": 1,
                        "status": "blocked",
                        "next_action": "block_release_until_high_risk_reviewed",
                        "quality_gate_ok": False,
                        "label_sidecar_gate_ok": True,
                        "benchmark_claim_safe": False,
                        "ok_to_accept_supported": True,
                        "metrics": {
                            "case_count": 19,
                            "supported_precision": 0.5,
                            "supported_recall": 0.25,
                            "supported_f1": 0.3333,
                            "macro_f1": 0.4,
                            "weighted_f1": 0.45,
                            "false_support_rate": 0.2,
                            "abstention_rate": 0.3,
                            "contradiction_recall": 0.0,
                        },
                        "risk_counts": {
                            "false_support": 1,
                            "weak_false_support": 2,
                            "missed_contradiction": 3,
                            "incorrect_abstention": 4,
                        },
                        "review_queue": {
                            "count": 5,
                            "top_case_ids": ["s10", "s39"],
                            "blocking_case_ids": ["s10"],
                            "review_required_case_ids": ["s10", "s39"],
                        },
                        "acceptance": {
                            "block_acceptance_case_ids": [],
                            "review_before_accepting_case_ids": ["s39"],
                            "top_risk_slice_id": "contradicted_overcalled",
                            "top_risk_slice_case_ids": ["s39"],
                        },
                        "abstention": {"review_case_ids": ["s09"]},
                        "label_maturity": {
                            "human_reviewed": 0,
                            "dual_annotated": 0,
                            "published_benchmark": 0,
                            "high_risk_unreviewed": 35,
                        },
                    },
                },
                {"script": "unit"},
                output_dir=tmpdir,
                run_id="support-release-summary",
            )

            run_path = Path(artifact["path"])
            manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))

        summary = manifest["result_summary"]
        self.assertEqual(summary["support_release_status"], "blocked")
        self.assertEqual(summary["support_release_next_action"], "block_release_until_high_risk_reviewed")
        self.assertEqual(summary["support_release_quality_gate_ok"], False)
        self.assertEqual(summary["support_release_label_sidecar_gate_ok"], True)
        self.assertFalse(summary["support_release_benchmark_claim_safe"])
        self.assertTrue(summary["support_release_ok_to_accept_supported"])
        self.assertEqual(summary["support_release_case_count"], 19)
        self.assertEqual(summary["support_release_supported_precision"], 0.5)
        self.assertEqual(summary["support_release_supported_recall"], 0.25)
        self.assertEqual(summary["support_release_supported_f1"], 0.3333)
        self.assertEqual(summary["support_release_macro_f1"], 0.4)
        self.assertEqual(summary["support_release_weighted_f1"], 0.45)
        self.assertEqual(summary["support_release_false_support_rate"], 0.2)
        self.assertEqual(summary["support_release_abstention_rate"], 0.3)
        self.assertEqual(summary["support_release_contradiction_recall"], 0.0)
        self.assertEqual(summary["support_release_false_support_count"], 1)
        self.assertEqual(summary["support_release_weak_false_support_count"], 2)
        self.assertEqual(summary["support_release_missed_contradiction_count"], 3)
        self.assertEqual(summary["support_release_incorrect_abstention_count"], 4)
        self.assertEqual(summary["support_release_review_queue_count"], 5)
        self.assertEqual(summary["support_release_review_top_case_ids"], ["s10", "s39"])
        self.assertEqual(summary["support_release_blocking_case_ids"], ["s10"])
        self.assertEqual(summary["support_release_review_required_case_ids"], ["s10", "s39"])
        self.assertEqual(summary["support_release_review_before_accepting_case_ids"], ["s39"])
        self.assertEqual(summary["support_release_top_risk_slice_id"], "contradicted_overcalled")
        self.assertEqual(summary["support_release_top_risk_slice_case_ids"], ["s39"])
        self.assertEqual(summary["support_release_abstention_review_case_ids"], ["s09"])
        self.assertEqual(summary["support_release_label_high_risk_unreviewed"], 35)

    def test_manifest_summarizes_support_calibration_top_result(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = write_experiment_artifacts(
                "support_calibration",
                {
                    "profile": "quick",
                    "input_mode": "scored_dataset",
                    "dataset_size": 2,
                    "top_results": [
                        {
                            "metrics": {
                                "f1": 0.8,
                                "precision": 1.0,
                                "recall": 0.6667,
                                "false_support_rate": 0.0,
                                "false_negative": 1,
                            },
                            "diagnostics": {
                                "false_positive_case_ids": ["hard-negative-1"],
                                "false_negative_case_ids": ["missed-positive-1"],
                                "decision_path_counts": {
                                    "false_positive": {"nli_pass": 1},
                                    "false_negative": {"paired_reranker_nli_reject": 1},
                                },
                                "bucket_summaries": {
                                    "false_positive": {
                                        "count": 1,
                                        "avg_nli_entailment": 0.72,
                                        "avg_nli_neutral": 0.24,
                                        "avg_nli_contradiction": 0.04,
                                    },
                                    "false_negative": {
                                        "count": 1,
                                        "avg_nli_entailment": 0.10,
                                        "avg_nli_neutral": 0.88,
                                        "avg_nli_contradiction": 0.02,
                                    },
                                },
                            },
                        }
                    ],
                },
                {"script": "scripts/calibrate_support.py"},
                output_dir=tmpdir,
                run_id="support-calibration-summary",
            )

            run_path = Path(artifact["path"])
            manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))

        summary = manifest["result_summary"]
        self.assertEqual(summary["dataset_size"], 2)
        self.assertEqual(summary["support_calibration_top_result_count"], 1)
        self.assertEqual(summary["support_calibration_top_f1"], 0.8)
        self.assertEqual(summary["support_calibration_top_precision"], 1.0)
        self.assertEqual(summary["support_calibration_top_recall"], 0.6667)
        self.assertEqual(summary["support_calibration_top_false_support_rate"], 0.0)
        self.assertEqual(summary["support_calibration_top_false_negative"], 1)
        self.assertEqual(summary["support_calibration_top_false_positive_case_ids"], ["hard-negative-1"])
        self.assertEqual(summary["support_calibration_top_false_negative_case_ids"], ["missed-positive-1"])
        self.assertEqual(summary["support_calibration_top_false_positive_decision_paths"], {"nli_pass": 1})
        self.assertEqual(
            summary["support_calibration_top_false_negative_decision_paths"],
            {"paired_reranker_nli_reject": 1},
        )
        self.assertEqual(summary["support_calibration_top_false_positive_score_summary"]["avg_nli_neutral"], 0.24)
        self.assertEqual(summary["support_calibration_top_false_negative_score_summary"]["avg_nli_neutral"], 0.88)
        self.assertEqual(summary["support_calibration_input_mode"], "scored_dataset")
        self.assertEqual(summary["support_calibration_profile"], "quick")

    def test_eval_verification_cli_can_write_experiment_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/eval_verification.py",
                    "--output-dir",
                    tmpdir,
                    "--run-id",
                    "verification-smoke",
                ],
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            artifact = payload["experiment_artifact"]
            run_path = Path(artifact["path"])
            manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
            config = json.loads((run_path / "config.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["accuracy"], 1.0)
        self.assertEqual(artifact["run_id"], "verification-smoke")
        self.assertEqual(manifest["experiment_name"], "verification_eval")
        self.assertEqual(config["script"], "scripts/eval_verification.py")
        self.assertEqual(config["case_count"], payload["n"])

    def test_eval_support_cli_can_write_quality_gated_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/eval_support.py",
                    "--report",
                    "--split",
                    "test",
                    "--quality-gate",
                    "--output-dir",
                    tmpdir,
                    "--run-id",
                    "support-smoke",
                ],
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            artifact = payload["experiment_artifact"]
            run_path = Path(artifact["path"])
            manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
            result = json.loads((run_path / "result.json").read_text(encoding="utf-8"))
            config = json.loads((run_path / "config.json").read_text(encoding="utf-8"))

        self.assertTrue(payload["quality_gate"]["ok"])
        self.assertEqual(artifact["run_id"], "support-smoke")
        self.assertEqual(manifest["result_summary"]["quality_gate_ok"], True)
        self.assertIn("macro_precision", manifest["result_summary"])
        self.assertIn("macro_recall", manifest["result_summary"])
        self.assertIn("macro_f1", manifest["result_summary"])
        self.assertIn("weighted_precision", manifest["result_summary"])
        self.assertIn("weighted_recall", manifest["result_summary"])
        self.assertIn("weighted_f1", manifest["result_summary"])
        self.assertEqual(manifest["result_summary"]["false_support_total_overcall_count"], 0)
        self.assertEqual(manifest["result_summary"]["false_support_risk_slice_count"], 0)
        self.assertTrue(manifest["result_summary"]["false_support_ok_to_accept_supported"])
        self.assertEqual(manifest["result_summary"]["false_support_block_acceptance_count"], 0)
        self.assertEqual(manifest["result_summary"]["false_support_block_acceptance_case_ids"], [])
        self.assertEqual(manifest["result_summary"]["false_support_review_before_accepting_case_ids"], [])
        self.assertIsNone(manifest["result_summary"]["false_support_top_risk_slice_id"])
        self.assertEqual(manifest["result_summary"]["false_support_top_risk_slice_case_ids"], [])
        self.assertEqual(
            manifest["result_summary"]["support_acceptance_slice_ids"],
            ["contradiction", "hard_negative", "full_text_boundary", "test_split", "non_english"],
        )
        self.assertEqual(manifest["result_summary"]["support_acceptance_blocked_slice_ids"], [])
        self.assertEqual(manifest["result_summary"]["support_acceptance_review_required_slice_ids"], [])
        self.assertIn("test_split", manifest["result_summary"]["support_acceptance_slice_case_counts"])
        self.assertIn("abstention_total_count", manifest["result_summary"])
        self.assertIn("abstention_incorrect_count", manifest["result_summary"])
        self.assertIn("abstention_correct_count", manifest["result_summary"])
        self.assertIsInstance(manifest["result_summary"]["abstention_review_case_ids"], list)
        self.assertEqual(manifest["result_summary"]["support_set_policy_case_count"], 3)
        self.assertEqual(
            manifest["result_summary"]["support_set_policy_case_types"],
            {"contradiction_set": 1, "weak_set_boundary": 2},
        )
        self.assertEqual(manifest["result_summary"]["support_set_policy_languages"], {"en": 2, "zh": 1})
        self.assertEqual(manifest["result_summary"]["support_set_policy_case_ids"], ["ss02", "ss03", "ss05"])
        self.assertEqual(result["quality_gate"]["ok"], True)
        self.assertEqual(config["split"], "test")
        self.assertTrue(config["quality_gate"])

    def test_calibrate_support_cli_can_write_scored_fixture_artifacts(self):
        scored_rows = [
            {
                "example": {
                    "example_id": "pos",
                    "claim_text": "The paper studies citation hallucinations.",
                    "evidence_text": "The paper studies citation hallucinations in academic writing.",
                    "supported": True,
                },
                "heuristic_score": 0.24,
                "heuristic_details": {"overlap_terms": ["paper", "studies", "citation", "hallucinations"]},
                "reranker_score": 0.82,
                "reranker_details": {},
                "nli_probabilities": {"entailment": 0.76, "contradiction": 0.03, "neutral": 0.21},
                "nli_details": {"model_name": "fixture"},
            },
            {
                "example": {
                    "example_id": "neg",
                    "claim_text": "The paper proves tokenizer bugs cause citation hallucinations.",
                    "evidence_text": "The paper studies citation hallucinations in academic writing.",
                    "supported": False,
                },
                "heuristic_score": 0.12,
                "heuristic_details": {"overlap_terms": ["paper", "citation", "hallucinations"]},
                "reranker_score": 0.41,
                "reranker_details": {},
                "nli_probabilities": {"entailment": 0.12, "contradiction": 0.08, "neutral": 0.80},
                "nli_details": {"model_name": "fixture"},
            },
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            scored_path = Path(tmpdir) / "scored-support.json"
            scored_path.write_text(json.dumps(scored_rows), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/calibrate_support.py",
                    "--scored-dataset",
                    str(scored_path),
                    "--profile",
                    "quick",
                    "--top-k",
                    "2",
                    "--output-dir",
                    tmpdir,
                    "--run-id",
                    "support-calibration-smoke",
                ],
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            artifact = payload["experiment_artifact"]
            run_path = Path(artifact["path"])
            manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
            result = json.loads((run_path / "result.json").read_text(encoding="utf-8"))
            config = json.loads((run_path / "config.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["input_mode"], "scored_dataset")
        self.assertEqual(payload["dataset_size"], 2)
        self.assertEqual(len(payload["top_results"]), 2)
        self.assertEqual(artifact["run_id"], "support-calibration-smoke")
        self.assertEqual(manifest["experiment_name"], "support_calibration")
        self.assertEqual(manifest["result_summary"]["support_calibration_input_mode"], "scored_dataset")
        self.assertEqual(manifest["result_summary"]["support_calibration_profile"], "quick")
        self.assertEqual(manifest["result_summary"]["support_calibration_top_result_count"], 2)
        self.assertIn("support_calibration_top_false_positive_case_ids", manifest["result_summary"])
        self.assertIn("support_calibration_top_false_negative_case_ids", manifest["result_summary"])
        self.assertIn("support_calibration_top_false_positive_decision_paths", manifest["result_summary"])
        self.assertIn("support_calibration_top_false_positive_score_summary", manifest["result_summary"])
        self.assertIn("diagnostics", payload["top_results"][0])
        self.assertIn("false_positive_case_ids", payload["top_results"][0]["diagnostics"])
        self.assertIn("bucket_summaries", payload["top_results"][0]["diagnostics"])
        self.assertIn("decision_path_counts", payload["top_results"][0]["diagnostics"])
        self.assertEqual(result["input_mode"], "scored_dataset")
        self.assertEqual(config["script"], "scripts/calibrate_support.py")
        self.assertEqual(config["profile"], "quick")
        self.assertEqual(config["top_k"], 2)

    def test_calibrate_support_cli_rejects_multiple_input_modes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            binary_path = Path(tmpdir) / "binary.json"
            scored_path = Path(tmpdir) / "scored.json"
            binary_path.write_text("[]", encoding="utf-8")
            scored_path.write_text("[]", encoding="utf-8")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/calibrate_support.py",
                    "--dataset",
                    str(binary_path),
                    "--support-eval-dataset",
                    "data/eval/support_eval.json",
                    "--scored-dataset",
                    str(scored_path),
                ],
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("mutually exclusive", completed.stderr)

    def test_baseline_manifest_keeps_stable_false_support_fields_without_overcalls(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = write_experiment_artifacts(
                "support_baseline_comparison",
                {
                    "comparison": [
                        {
                            "backend": "fixture",
                            "quality_gate_ok": True,
                            "total_overcall_count": 0,
                            "false_support_risk_slices": [],
                            "top_false_support_risk_slice": None,
                        }
                    ]
                },
                {"script": "scripts/compare_support_baselines.py"},
                output_dir=tmpdir,
                run_id="no-overcall-baseline",
            )

            run_path = Path(artifact["path"])
            manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(manifest["result_summary"]["false_support_overcall_backends"], [])
        self.assertIsNone(manifest["result_summary"]["false_support_top_overcall_backend"])
        self.assertIsNone(manifest["result_summary"]["false_support_top_risk_slice_id"])
        self.assertEqual(manifest["result_summary"]["false_support_top_risk_slice_case_ids"], [])

    def test_compare_support_baselines_cli_writes_reproducible_table(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/compare_support_baselines.py",
                    "--split",
                    "test",
                    "--min-high-risk-reviewed-by-language",
                    "zh=0",
                    "--output-dir",
                    tmpdir,
                    "--run-id",
                    "support-baselines-smoke",
                ],
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            artifact = payload["experiment_artifact"]
            run_path = Path(artifact["path"])
            manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
            result = json.loads((run_path / "result.json").read_text(encoding="utf-8"))
            config = json.loads((run_path / "config.json").read_text(encoding="utf-8"))

        self.assertEqual([row["backend"] for row in payload["comparison"]], ["fixture", "heuristic"])
        self.assertNotIn("ok", payload)
        self.assertFalse(payload["quality_gates_ok"])
        self.assertEqual(payload["support_set_case_count"], 3)
        self.assertEqual(payload["support_set_policy"]["dataset"]["n"], 3)
        self.assertEqual(
            payload["support_set_policy"]["dataset"]["case_types"],
            {"contradiction_set": 1, "weak_set_boundary": 2},
        )
        self.assertEqual(payload["support_set_policy"]["dataset"]["languages"], {"en": 2, "zh": 1})
        self.assertEqual(
            [case["case_id"] for case in payload["support_set_policy"]["cases"]],
            ["ss02", "ss03", "ss05"],
        )
        self.assertTrue(payload["comparison"][0]["quality_gate_ok"])
        self.assertTrue(payload["comparison"][1]["heuristic_limited"])
        for row in payload["comparison"]:
            self.assertIn("macro_precision", row)
            self.assertIn("macro_recall", row)
            self.assertIn("macro_f1", row)
            self.assertIn("weighted_precision", row)
            self.assertIn("weighted_recall", row)
            self.assertIn("weighted_f1", row)
        self.assertTrue(payload["comparison"][0]["ok_to_accept_supported"])
        self.assertTrue(payload["comparison"][1]["ok_to_accept_supported"])
        self.assertEqual(payload["comparison"][1]["block_acceptance_case_ids"], [])
        self.assertEqual(payload["comparison"][1]["review_before_accepting_case_ids"], ["s39", "s48"])
        self.assertIn("false_support_risk_slices", payload["comparison"][1])
        self.assertIn("top_false_support_risk_slice", payload["comparison"][1])
        self.assertTrue(payload["comparison"][1]["false_support_risk_slices"])
        self.assertEqual(
            payload["comparison"][1]["top_false_support_risk_slice"]["id"],
            payload["comparison"][1]["false_support_risk_slices"][0]["id"],
        )
        self.assertIn("label_sidecar_gate", payload)
        self.assertEqual(artifact["run_id"], "support-baselines-smoke")
        self.assertEqual(manifest["result_summary"]["false_support_overcall_backends"], ["heuristic"])
        self.assertEqual(manifest["result_summary"]["false_support_top_overcall_backend"], "heuristic")
        self.assertEqual(
            manifest["result_summary"]["false_support_top_risk_slice_id"],
            payload["comparison"][1]["top_false_support_risk_slice"]["id"],
        )
        self.assertEqual(
            manifest["result_summary"]["false_support_top_risk_slice_case_ids"],
            payload["comparison"][1]["top_false_support_risk_slice"]["case_ids"],
        )
        self.assertEqual(manifest["result_summary"]["support_set_policy_case_count"], 3)
        self.assertEqual(
            manifest["result_summary"]["support_set_policy_case_types"],
            {"contradiction_set": 1, "weak_set_boundary": 2},
        )
        self.assertEqual(manifest["result_summary"]["support_set_policy_languages"], {"en": 2, "zh": 1})
        self.assertEqual(manifest["result_summary"]["support_set_policy_case_ids"], ["ss02", "ss03", "ss05"])
        self.assertTrue(manifest["result_summary"]["support_label_gate_ok"])
        self.assertEqual(manifest["result_summary"]["support_label_sidecar_coverage"], 1.0)
        self.assertEqual(manifest["result_summary"]["support_label_human_reviewed"], 0)
        self.assertEqual(manifest["result_summary"]["support_label_high_risk_unreviewed"], 35)
        self.assertEqual(manifest["result_summary"]["support_label_full_text_required_unreviewed"], 7)
        self.assertEqual(manifest["result_summary"]["support_label_policy_boundary_unreviewed"], 2)
        self.assertEqual(manifest["result_summary"]["support_label_dual_annotated"], 0)
        self.assertEqual(manifest["result_summary"]["support_label_unresolved_disagreements"], 0)
        self.assertEqual(manifest["result_summary"]["support_label_supported_disagreements"], 0)
        self.assertIsNone(manifest["result_summary"]["support_label_raw_dual_agreement_rate"])
        self.assertEqual(manifest["result_summary"]["support_label_unresolved_disagreement_case_ids"], [])
        self.assertEqual(manifest["result_summary"]["support_label_supported_disagreement_case_ids"], [])
        self.assertEqual(manifest["result_summary"]["support_label_sidecar_provenance_missing_count"], 0)
        self.assertEqual(manifest["result_summary"]["support_label_sidecar_provenance_missing_case_ids"], [])
        self.assertEqual(
            manifest["result_summary"]["support_label_high_risk_unreviewed_by_language_case_type"]["zh"],
            {"contradiction": 6, "full_text_required": 1, "hard_negative": 2},
        )
        self.assertEqual(
            manifest["result_summary"]["support_label_label_source_counts"],
            {"maintainer_synthetic": 54},
        )
        self.assertEqual(
            manifest["result_summary"]["support_label_unreviewed_by_label_source"],
            {"maintainer_synthetic": 54},
        )
        self.assertEqual(manifest["result_summary"]["support_label_reviewed_source_locator_count"], 0)
        self.assertEqual(manifest["result_summary"]["support_label_published_benchmark_source_locator_count"], 0)
        self.assertEqual(
            manifest["result_summary"]["support_baseline_metric_fields"],
            [
                "accuracy",
                "macro_precision",
                "macro_recall",
                "macro_f1",
                "weighted_precision",
                "weighted_recall",
                "weighted_f1",
                "false_support_rate",
                "abstention_rate",
                "supported_precision",
                "contradiction_recall",
            ],
        )
        self.assertEqual(
            sorted(manifest["result_summary"]["support_baseline_metrics"]),
            ["fixture", "heuristic"],
        )
        self.assertEqual(
            manifest["result_summary"]["support_baseline_metrics"]["fixture"]["macro_f1"],
            payload["comparison"][0]["macro_f1"],
        )
        self.assertEqual(
            manifest["result_summary"]["support_baseline_metrics"]["heuristic"]["weighted_f1"],
            payload["comparison"][1]["weighted_f1"],
        )
        self.assertEqual(result["comparison"], payload["comparison"])
        self.assertEqual(config["script"], "scripts/compare_support_baselines.py")
        self.assertEqual(config["backends"], ["fixture", "heuristic"])
        self.assertEqual(config["thresholds"]["min_dual_annotated"], 0)
        self.assertEqual(config["thresholds"]["min_high_risk_reviewed_by_language"], {"zh": 0})
        self.assertEqual(config["thresholds"]["max_unresolved_disagreements"], 0)
        self.assertIsNone(config["thresholds"]["min_raw_dual_agreement_rate"])

    def test_compare_support_baselines_cli_can_fail_on_quality_gate(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/compare_support_baselines.py",
                "--split",
                "test",
                "--min-high-risk-reviewed-by-language",
                "zh=1",
                "--fail-on-gate",
            ],
            check=False,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 1)
        self.assertFalse(payload["quality_gates_ok"])
        self.assertFalse(payload["comparison"][1]["quality_gate_ok"])
        self.assertEqual(
            payload["label_sidecar_gate"]["failures"][0]["code"],
            "sidecar_high_risk_reviewed_by_language",
        )


if __name__ == "__main__":
    unittest.main()
