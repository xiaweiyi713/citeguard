"""Behavioral tests for automated software-release authorization."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from scripts.automated_release_review import (
    REQUIRED_MODEL_REVIEWERS,
    compute_review_contract_digest,
    validate_automated_review_artifact,
)
from scripts.release_package_gate import _record_release_claim_policy_gate


ROOT = Path(__file__).resolve().parents[1]
DATASET = "data/eval/support_eval.json"


def _valid_payload() -> dict:
    dataset_digest = hashlib.sha256((ROOT / DATASET).read_bytes()).hexdigest()
    return {
        "schema_version": 1,
        "review_type": "automated_release_review",
        "dataset": {
            "path": DATASET,
            "sha256": dataset_digest,
            "split": "test",
            "case_count": 19,
            "label_sources": ["maintainer_synthetic"],
        },
        "implementation_digest": compute_review_contract_digest(ROOT),
        "reviewers": {
            "model_components": [
                {"id": reviewer, "available": True}
                for reviewer in sorted(REQUIRED_MODEL_REVIEWERS)
            ],
            "all_required_available": True,
        },
        "quality_gate": {"ok": True},
        "support_set_policy": {"ok": True},
        "authorization": {
            "software_release_allowed": True,
            "human_benchmark_claim_allowed": False,
        },
        "label_provenance": {"human_reviewed": False},
    }


class AutomatedReleaseReviewTests(unittest.TestCase):
    def test_valid_automation_artifact_authorizes_software_only(self):
        details = validate_automated_review_artifact(
            _valid_payload(),
            project_root=ROOT,
            dataset=DATASET,
        )

        self.assertTrue(details["software_release_allowed"])
        self.assertFalse(details["human_benchmark_claim_allowed"])
        self.assertEqual(set(details["reviewer_ids"]), REQUIRED_MODEL_REVIEWERS)

    def test_stale_or_provenance_inflating_artifact_is_rejected(self):
        payload = _valid_payload()
        payload["implementation_digest"] = "stale"
        payload["authorization"]["human_benchmark_claim_allowed"] = True
        payload["label_provenance"]["human_reviewed"] = True

        with self.assertRaisesRegex(ValueError, "implementation digest is stale"):
            validate_automated_review_artifact(
                payload,
                project_root=ROOT,
                dataset=DATASET,
            )

    def test_software_mode_accepts_valid_automation_without_human_thresholds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "automated-review.json"
            report_path.write_text(json.dumps(_valid_payload()), encoding="utf-8")
            summary = {"ok": True, "steps": []}

            _record_release_claim_policy_gate(
                summary,
                project_root=ROOT,
                claim_mode="software",
                automated_review_report=str(report_path),
                dataset=DATASET,
                min_human_reviewed=0,
                min_high_risk_reviewed=0,
                min_dual_annotated=0,
                min_raw_dual_agreement_rate=None,
                max_supported_disagreements=None,
            )

        self.assertTrue(summary["ok"])
        self.assertTrue(summary["release_policy"]["software_release_allowed"])
        self.assertFalse(summary["release_policy"]["human_benchmark_claim_allowed"])

    def test_human_benchmark_mode_rejects_automation_only_thresholds(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "automated-review.json"
            report_path.write_text(json.dumps(_valid_payload()), encoding="utf-8")
            summary = {"ok": True, "steps": [{"name": "support_label_sidecar_gate", "status": "passed"}]}

            _record_release_claim_policy_gate(
                summary,
                project_root=ROOT,
                claim_mode="human-benchmark",
                automated_review_report=str(report_path),
                dataset=DATASET,
                min_human_reviewed=0,
                min_high_risk_reviewed=0,
                min_dual_annotated=0,
                min_raw_dual_agreement_rate=None,
                max_supported_disagreements=None,
            )

        self.assertFalse(summary["ok"])
        self.assertFalse(summary["release_policy"]["human_benchmark_claim_allowed"])
        self.assertIn("positive human-review thresholds", summary["steps"][-1]["message"])

    def test_publish_workflow_uses_software_mode_and_preserves_review_artifact(self):
        workflow = (ROOT / ".github" / "workflows" / "publish.yml").read_text(encoding="utf-8")

        self.assertIn("python scripts/automated_release_review.py", workflow)
        self.assertIn("--release-claim-mode software", workflow)
        self.assertIn("--automated-review-report automated-release-review.json", workflow)
        self.assertNotIn("--min-human-reviewed 20", workflow)
        self.assertIn("name: automated-release-review", workflow)


if __name__ == "__main__":
    unittest.main()
