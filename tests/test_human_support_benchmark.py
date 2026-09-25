"""Tests for the real, independently double-annotated benchmark campaign gate."""

from __future__ import annotations

from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest

from citeguard.verification.support_eval import load_support_label_cases
from citeguard.verification.support_eval_labels import (
    SupportLabelSidecarValidationError,
    build_support_label_sidecar_template,
    validate_support_label_sidecar,
)
from scripts import audit_human_support_benchmark as campaign_tool
from scripts import freeze_human_support_benchmark_test_split as freeze_tool
from scripts.release_package_gate import _record_human_support_benchmark_campaign, _record_release_claim_policy_gate


ROOT = Path(__file__).resolve().parents[1]


class HumanSupportBenchmarkTests(unittest.TestCase):
    def test_default_campaign_remains_explicitly_incomplete(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = campaign_tool.main([])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["status"], "collection_incomplete")
        self.assertFalse(payload["benchmark_claim_safe"])
        self.assertEqual(payload["counts"]["qualified_double_annotated_cases"], 0)
        self.assertEqual(payload["next_action"], "collect_real_sourced_cases_before_labeling")

    def test_strict_campaign_refuses_unreviewed_seed_data(self):
        with redirect_stdout(io.StringIO()):
            code = campaign_tool.main(["--strict"])

        self.assertEqual(code, 1)

    def test_ready_requires_real_provenance_and_two_distinct_reviewers(self):
        dataset = json.loads((ROOT / "data" / "eval" / "support_eval.json").read_text(encoding="utf-8"))
        sidecar = json.loads((ROOT / "data" / "eval" / "support_eval_label_sidecar.json").read_text(encoding="utf-8"))
        campaign = json.loads((ROOT / "data" / "eval" / "human_support_benchmark_campaign.json").read_text(encoding="utf-8"))

        for index in range(250):
            is_english = index < 125
            is_abstract = index < 125
            case_id = f"human-benchmark-fixture-{index:03d}"
            source_locator = f"doi:10.5555/human-benchmark-fixture-{index:03d}"
            scope = "abstract" if is_abstract else "full_text"
            dataset["cases"].append(
                {
                    "id": case_id,
                    "claim": f"Fixture claim {index} is directly supported.",
                    "evidence": f"Fixture evidence {index} directly supports the claim.",
                    "gold": "supported",
                    "lang": "en" if is_english else "zh",
                    "evidence_scope": scope,
                    "label_source": "human_benchmark",
                    "label_notes": "Temporary test fixture only; not a published human label.",
                    "case_type": "direct_support",
                    "split": "test" if index < 50 else "train",
                    "benchmark_origin": "real_source",
                    "domain": "computer_science" if is_english else "biomedicine",
                    "writing_context": "literature_review" if index < 80 else "research_article",
                    "source_locator": source_locator,
                    "evidence_locator": "abstract" if is_abstract else "section:results paragraph:1",
                    "rights_basis": "public_abstract" if is_abstract else "open_access",
                }
            )
            sidecar["cases"].append(
                {
                    "case_id": case_id,
                    "adjudication_status": "dual_annotator_agreed",
                    "annotator_count": 2,
                    "annotator_labels": ["supported", "supported"],
                    "annotator_ids": [f"reviewer-a-{index:03d}", f"reviewer-b-{index:03d}"],
                    "adjudicated_label": "supported",
                    "disagreement": "none",
                    "adjudicator": "",
                    "source_locator": source_locator,
                    "notes": "Temporary test fixture only.",
                    "label_source": "human_benchmark",
                    "case_type": "direct_support",
                    "evidence_scope": scope,
                    "split": "test" if index < 50 else "train",
                    "lang": "en" if is_english else "zh",
                }
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            dataset_path = Path(temp_dir) / "support_eval.json"
            sidecar_path = Path(temp_dir) / "support_eval_label_sidecar.json"
            campaign_path = Path(temp_dir) / "human_support_benchmark_campaign.json"
            manifest_path = Path(temp_dir) / "human_support_benchmark_test_manifest.json"
            dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
            sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
            campaign_path.write_text(json.dumps(campaign), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                freeze_code = freeze_tool.main(
                    [
                        "--dataset",
                        str(dataset_path),
                        "--label-sidecar",
                        str(sidecar_path),
                        "--campaign",
                        str(campaign_path),
                        "--output",
                        str(manifest_path),
                        "--frozen-at",
                        "2026-08-07T12:00:00Z",
                    ]
                )
            self.assertEqual(freeze_code, 0)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            report = campaign_tool.audit_human_benchmark(
                dataset,
                sidecar,
                campaign,
                dataset_path=str(dataset_path),
                test_split_manifest=manifest,
            )

        self.assertEqual(report["status"], "ready")
        self.assertTrue(report["benchmark_claim_safe"])
        self.assertEqual(report["counts"]["qualified_double_annotated_cases"], 250)
        self.assertEqual(report["invalid_cases"], [])
        self.assertTrue(report["test_split"]["frozen"])
        self.assertEqual(report["test_split"]["qualified_case_count"], 50)

        drifted_dataset = copy.deepcopy(dataset)
        next(item for item in drifted_dataset["cases"] if item["id"] == "human-benchmark-fixture-000")["evidence"] = (
            "Modified evidence after the held-out split was frozen."
        )
        drift_report = campaign_tool.audit_test_split_manifest(
            dataset=drifted_dataset,
            sidecar=sidecar,
            campaign=campaign,
            qualified_case_ids=report["qualified_case_ids"],
            manifest=manifest,
        )
        self.assertFalse(drift_report["frozen"])
        self.assertIn("test_cases_sha256 does not match current qualified test split", drift_report["manifest_errors"])

    def test_sidecar_retains_and_validates_annotator_ids(self):
        cases = load_support_label_cases(str(ROOT / "data" / "eval" / "support_eval.json"))
        template = build_support_label_sidecar_template(cases)
        item = template["cases"][0]
        self.assertEqual(item["annotator_ids"], [])

        item.update(
            {
                "adjudication_status": "dual_annotator_agreed",
                "annotator_count": 2,
                "annotator_labels": [item["adjudicated_label"], item["adjudicated_label"]],
                "annotator_ids": ["reviewer-a", "reviewer-b"],
                "disagreement": "none",
            }
        )
        validate_support_label_sidecar(template, cases)
        summary = validate_support_label_sidecar(template, cases)
        self.assertEqual(summary["label_maturity"]["dual_independent_count"], 1)
        self.assertEqual(summary["label_maturity"]["dual_independent_case_ids"], [item["case_id"]])

        duplicate = copy.deepcopy(template)
        duplicate["cases"][0]["annotator_ids"] = ["reviewer-a", "reviewer-a"]
        with self.assertRaises(SupportLabelSidecarValidationError):
            validate_support_label_sidecar(duplicate, cases)

    def test_release_gate_reports_incomplete_collection_without_blocking_software_validation(self):
        summary = {"ok": True, "steps": []}

        _record_human_support_benchmark_campaign(
            summary,
            project_root=ROOT,
            dataset="data/eval/support_eval.json",
            label_sidecar="data/eval/support_eval_label_sidecar.json",
            campaign="data/eval/human_support_benchmark_campaign.json",
            test_split_manifest="data/eval/human_support_benchmark_test_manifest.json",
        )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["status"], "incomplete")
        self.assertFalse(summary["steps"][0]["benchmark_claim_safe"])
        self.assertEqual(summary["steps"][0]["next_action"], "collect_real_sourced_cases_before_labeling")

    def test_human_benchmark_release_mode_requires_ready_campaign(self):
        summary = {
            "ok": True,
            "steps": [
                {"name": "support_label_sidecar_gate", "status": "passed"},
                {
                    "name": "human_support_benchmark_campaign",
                    "status": "incomplete",
                    "benchmark_claim_safe": False,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            report_path = Path(temp_dir) / "automated-release-review.json"
            report_path.write_text("{}", encoding="utf-8")
            from unittest import mock

            with mock.patch(
                "scripts.release_package_gate.validate_automated_review_artifact",
                return_value={"validated": True},
            ):
                _record_release_claim_policy_gate(
                    summary,
                    project_root=ROOT,
                    claim_mode="human-benchmark",
                    automated_review_report=str(report_path),
                    dataset="data/eval/support_eval.json",
                    min_human_reviewed=250,
                    min_high_risk_reviewed=50,
                    min_dual_annotated=250,
                    min_raw_dual_agreement_rate=0.8,
                    max_supported_disagreements=0,
                )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["steps"][-1]["status"], "failed")
        self.assertIn("ready real-source campaign", summary["steps"][-1]["message"])


if __name__ == "__main__":
    unittest.main()
