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
        self.assertEqual(result["quality_gate"]["ok"], True)
        self.assertEqual(config["split"], "test")
        self.assertTrue(config["quality_gate"])

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
            result = json.loads((run_path / "result.json").read_text(encoding="utf-8"))
            config = json.loads((run_path / "config.json").read_text(encoding="utf-8"))

        self.assertEqual([row["backend"] for row in payload["comparison"]], ["fixture", "heuristic"])
        self.assertNotIn("ok", payload)
        self.assertFalse(payload["quality_gates_ok"])
        self.assertTrue(payload["comparison"][0]["quality_gate_ok"])
        self.assertTrue(payload["comparison"][1]["heuristic_limited"])
        self.assertIn("false_support_risk_slices", payload["comparison"][1])
        self.assertIn("top_false_support_risk_slice", payload["comparison"][1])
        self.assertTrue(payload["comparison"][1]["false_support_risk_slices"])
        self.assertEqual(
            payload["comparison"][1]["top_false_support_risk_slice"]["id"],
            payload["comparison"][1]["false_support_risk_slices"][0]["id"],
        )
        self.assertIn("label_sidecar_gate", payload)
        self.assertEqual(artifact["run_id"], "support-baselines-smoke")
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
