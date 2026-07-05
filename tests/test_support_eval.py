"""Tests for the support evaluation harness (metrics are model-free / synthetic)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter

from citeguard.verification.support_eval import (
    SupportCase,
    SupportEvalValidationError,
    SupportLabelSidecarValidationError,
    build_support_label_sidecar_template,
    citation_record_for_support_case,
    compute_support_confusion_matrix,
    compute_support_diagnostics,
    compute_support_error_bucket_counts,
    compute_support_error_buckets,
    compute_false_support_analysis,
    compute_support_label_sidecar_gate,
    compute_support_metrics,
    compute_support_quality_gate,
    compute_support_report,
    filter_support_cases_by_split,
    load_support_label_cases,
    load_support_label_sidecar,
    load_support_eval,
    load_support_set_eval,
    predict_support_set_policy,
    run_support_eval_fixture,
    run_support_eval_fixture_report,
    run_support_set_policy_fixture_report,
    summarize_support_label_maturity,
    validate_support_label_sidecar,
    validate_support_eval_dataset,
)
from citeguard.verification.support import build_evidence_spans


class SupportEvalTests(unittest.TestCase):
    def test_compute_metrics_counts_correct_and_misjudgments(self):
        preds = [
            ("supported", "supported"),
            ("contradicted", "contradicted"),
            ("insufficient_evidence", "insufficient_evidence"),
            ("supported", "contradicted"),  # a misjudged true-support
        ]
        m = compute_support_metrics(preds)
        self.assertEqual(m["n"], 4)
        self.assertEqual(m["accuracy"], 0.75)
        self.assertEqual(m["supported_precision"], 1.0)
        self.assertEqual(m["supported_recall"], 0.5)
        self.assertEqual(round(m["supported_f1"], 4), 0.6667)
        self.assertEqual(m["false_support_rate"], 0.0)
        self.assertEqual(m["abstention_rate"], 0.25)
        self.assertEqual(m["misjudged_support_rate"], 0.5)

    def test_compute_confusion_matrix_counts_gold_predicted_pairs(self):
        matrix = compute_support_confusion_matrix(
            [
                ("supported", "supported"),
                ("supported", "insufficient_evidence"),
                ("contradicted", "insufficient_evidence"),
            ]
        )

        self.assertEqual(matrix["supported"]["supported"], 1)
        self.assertEqual(matrix["supported"]["insufficient_evidence"], 1)
        self.assertEqual(matrix["contradicted"]["insufficient_evidence"], 1)
        self.assertEqual(matrix["contradicted"]["supported"], 0)

    def test_load_support_eval_reads_seed_file(self):
        cases = load_support_eval(os.path.join("data", "eval", "support_eval.json"))
        set_cases = load_support_set_eval(os.path.join("data", "eval", "support_eval.json"))
        self.assertGreaterEqual(len(cases), 30)
        self.assertGreaterEqual(len(set_cases), 4)
        self.assertIn(cases[0].gold, {"supported", "weakly_supported", "insufficient_evidence", "contradicted"})
        self.assertEqual(cases[0].evidence_scope, "abstract")
        self.assertTrue(cases[0].label_source)
        self.assertIn(cases[0].split, {"train", "dev", "test"})
        case_ids = {case.case_id for case in cases}
        self.assertIn("s21", case_ids)
        self.assertIn("s22", case_ids)
        self.assertIn("s23", case_ids)
        self.assertIn("s28", case_ids)
        self.assertIn("s29", case_ids)
        self.assertIn("s30", case_ids)
        self.assertTrue(any(case.case_type == "hard_negative" for case in cases))
        self.assertTrue(any(case.case_type == "contradiction" for case in cases))
        self.assertTrue(any(case.case_type == "weak_support" for case in cases))
        self.assertTrue(any(case.case_type == "full_text_required" for case in cases))
        self.assertTrue(any(case.evidence_scope == "title" for case in cases))
        self.assertTrue(any(case.evidence_scope == "metadata_snippet" for case in cases))
        self.assertTrue(any(case.evidence_scope == "full_text" for case in cases))
        self.assertEqual({case.split for case in cases}, {"train", "dev", "test"})
        self.assertEqual(Counter(case.split for case in cases), {"train": 10, "dev": 10, "test": 10})
        self.assertTrue(any(case.case_type == "weak_set_boundary" for case in set_cases))
        self.assertTrue(any(case.case_type == "contradiction_set" for case in set_cases))

    def test_load_support_label_sidecar_reads_seed_file(self):
        cases = load_support_label_cases(os.path.join("data", "eval", "support_eval.json"))
        sidecar = load_support_label_sidecar(
            os.path.join("data", "eval", "support_eval_label_sidecar.json"),
            cases,
        )
        with open(os.path.join("data", "eval", "support_eval_label_sidecar.json"), encoding="utf-8") as handle:
            summary = validate_support_label_sidecar(json.load(handle), cases)

        self.assertEqual(len(sidecar), len(cases))
        self.assertEqual(summary["coverage"], 1.0)
        self.assertEqual(summary["human_reviewed"], 0)
        self.assertEqual(sidecar[0].adjudication_status, "not_human_reviewed")
        self.assertEqual(sidecar[0].annotator_labels, [])
        self.assertEqual(sidecar[0].adjudicated_label, cases[0].gold)
        self.assertIn("ss02", {item.case_id for item in sidecar})

    def test_validate_support_label_sidecar_reports_coverage(self):
        cases = [
            SupportCase("a", "claim", "evidence", "supported"),
            SupportCase("b", "claim", "evidence", "contradicted"),
        ]
        sidecar = {
            "schema_version": 1,
            "cases": [
                {
                    "case_id": "a",
                    "adjudication_status": "single_annotator",
                    "annotator_count": 1,
                    "annotator_labels": ["supported"],
                    "adjudicated_label": "supported",
                    "disagreement": "none",
                    "source_locator": "doi:10.123/example",
                    "notes": "Unit test label provenance.",
                }
            ],
        }

        summary = validate_support_label_sidecar(sidecar, cases)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["n"], 1)
        self.assertEqual(summary["dataset_cases"], 2)
        self.assertEqual(summary["coverage"], 0.5)
        self.assertEqual(summary["human_reviewed"], 1)
        self.assertEqual(summary["adjudication_statuses"]["single_annotator"], 1)
        self.assertEqual(summary["label_maturity"]["reviewed_count"], 1)
        self.assertEqual(summary["label_maturity"]["single_annotator_count"], 1)
        self.assertEqual(summary["label_maturity"]["reviewed_fraction"], 0.5)

    def test_support_label_maturity_summarizes_disagreement_and_adjudication(self):
        cases = [
            SupportCase("a", "claim", "evidence", "supported"),
            SupportCase("b", "claim", "evidence", "contradicted"),
            SupportCase("c", "claim", "evidence", "insufficient_evidence"),
        ]
        sidecar = {
            "schema_version": 1,
            "cases": [
                {
                    "case_id": "a",
                    "adjudication_status": "dual_annotator_agreed",
                    "annotator_count": 2,
                    "annotator_labels": ["supported", "supported"],
                    "adjudicated_label": "supported",
                    "disagreement": "none",
                },
                {
                    "case_id": "b",
                    "adjudication_status": "dual_annotator_adjudicated",
                    "annotator_count": 2,
                    "annotator_labels": ["supported", "contradicted"],
                    "adjudicated_label": "contradicted",
                    "disagreement": "resolved",
                    "adjudicator": "reviewer-c",
                },
                {
                    "case_id": "c",
                    "adjudication_status": "single_annotator",
                    "annotator_count": 1,
                    "annotator_labels": ["insufficient_evidence"],
                    "adjudicated_label": "insufficient_evidence",
                    "disagreement": "none",
                },
            ],
        }

        summary = validate_support_label_sidecar(sidecar, cases)
        direct = summarize_support_label_maturity(sidecar["cases"], dataset_case_count=len(cases))

        self.assertEqual(summary["label_maturity"], direct)
        self.assertEqual(summary["label_maturity"]["reviewed_count"], 3)
        self.assertEqual(summary["label_maturity"]["dual_annotated_count"], 2)
        self.assertEqual(summary["label_maturity"]["dual_agreed_count"], 1)
        self.assertEqual(summary["label_maturity"]["dual_disagreed_count"], 1)
        self.assertEqual(summary["label_maturity"]["raw_dual_agreement_rate"], 0.5)
        self.assertEqual(summary["label_maturity"]["adjudicated_count"], 1)
        self.assertEqual(summary["label_maturity"]["resolved_disagreement_count"], 1)
        self.assertEqual(summary["label_maturity"]["disagreement_case_ids"], ["b"])
        self.assertEqual(
            summary["label_maturity"]["dual_label_pair_counts"],
            {
                "supported|supported": 1,
                "supported|contradicted": 1,
            },
        )
        self.assertEqual(
            summary["label_maturity"]["dual_disagreement_label_pair_counts"],
            {"supported|contradicted": 1},
        )
        self.assertEqual(summary["label_maturity"]["supported_disagreement_count"], 1)
        self.assertEqual(summary["label_maturity"]["supported_disagreement_case_ids"], ["b"])

    def test_support_label_sidecar_gate_checks_coverage_and_human_review(self):
        passing = compute_support_label_sidecar_gate(
            {
                "coverage": 1.0,
                "human_reviewed": 2,
                "dataset_cases": 4,
                "n": 4,
                "label_maturity": {
                    "dual_annotated_count": 1,
                    "unresolved_disagreement_count": 0,
                    "raw_dual_agreement_rate": 1.0,
                },
            },
            min_coverage=1.0,
            min_human_reviewed=2,
            min_dual_annotated=1,
            max_unresolved_disagreements=0,
            min_raw_dual_agreement_rate=0.8,
        )
        failing = compute_support_label_sidecar_gate(
            {"coverage": 0.5, "human_reviewed": 0, "dataset_cases": 4, "n": 2},
            min_coverage=1.0,
            min_human_reviewed=1,
        )

        self.assertTrue(passing["ok"])
        self.assertFalse(failing["ok"])
        self.assertEqual(
            {failure["code"] for failure in failing["failures"]},
            {"sidecar_coverage", "sidecar_human_reviewed"},
        )

    def test_support_label_sidecar_gate_checks_maturity_thresholds(self):
        gate = compute_support_label_sidecar_gate(
            {
                "coverage": 1.0,
                "human_reviewed": 4,
                "dataset_cases": 4,
                "n": 4,
                "label_maturity": {
                    "dual_annotated_count": 1,
                    "unresolved_disagreement_count": 1,
                    "unresolved_disagreement_case_ids": ["case-b"],
                    "raw_dual_agreement_rate": 0.5,
                },
            },
            min_dual_annotated=2,
            max_unresolved_disagreements=0,
            min_raw_dual_agreement_rate=0.8,
        )
        missing_rate = compute_support_label_sidecar_gate(
            {
                "coverage": 1.0,
                "human_reviewed": 1,
                "dataset_cases": 1,
                "n": 1,
                "label_maturity": {
                    "dual_annotated_count": 0,
                    "unresolved_disagreement_count": 0,
                    "raw_dual_agreement_rate": None,
                },
            },
            min_raw_dual_agreement_rate=0.8,
        )

        self.assertFalse(gate["ok"])
        self.assertEqual(
            {failure["code"] for failure in gate["failures"]},
            {
                "sidecar_dual_annotated",
                "sidecar_unresolved_disagreements",
                "sidecar_raw_dual_agreement_rate",
            },
        )
        unresolved = next(
            failure for failure in gate["failures"] if failure["code"] == "sidecar_unresolved_disagreements"
        )
        self.assertEqual(unresolved["case_ids"], ["case-b"])
        self.assertFalse(missing_rate["ok"])
        self.assertEqual(missing_rate["failures"][0]["actual"], None)

    def test_build_support_label_sidecar_template_preserves_existing_and_fills_missing(self):
        cases = [
            SupportCase("a", "claim a", "evidence a", "supported", case_type="direct_support", split="dev"),
            SupportCase("b", "claim b", "evidence b", "contradicted", case_type="contradiction", split="test"),
        ]
        existing = {
            "schema_version": 1,
            "cases": [
                {
                    "case_id": "a",
                    "adjudication_status": "single_annotator",
                    "annotator_count": 1,
                    "annotator_labels": ["supported"],
                    "adjudicated_label": "supported",
                    "disagreement": "none",
                    "source_locator": "doi:10.123/example",
                    "notes": "Reviewed by annotator A.",
                }
            ],
        }

        template = build_support_label_sidecar_template(
            cases,
            existing_sidecar=existing,
            dataset_name="unit_support_eval.json",
            include_context=True,
        )
        summary = validate_support_label_sidecar(template, cases)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["coverage"], 1.0)
        self.assertEqual(template["dataset"], "unit_support_eval.json")
        self.assertEqual(template["cases"][0]["adjudication_status"], "single_annotator")
        self.assertEqual(template["cases"][0]["source_locator"], "doi:10.123/example")
        self.assertEqual(template["cases"][1]["adjudication_status"], "not_human_reviewed")
        self.assertEqual(template["cases"][1]["annotator_count"], 0)
        self.assertEqual(template["cases"][1]["adjudicated_label"], "contradicted")
        self.assertIn("Unreviewed seed label", template["cases"][1]["notes"])
        self.assertIn("evidence source", template["cases"][1]["notes"])
        self.assertEqual(template["cases"][1]["claim"], "claim b")
        self.assertEqual(template["cases"][1]["dataset_gold"], "contradicted")

    def test_prepare_support_label_sidecar_script_writes_valid_template(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "sidecar.json")
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    os.path.join("data", "eval", "support_eval.json"),
                    "--existing-sidecar",
                    os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                    "--include-context",
                    "--output",
                    output,
                ],
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.stdout, "")
            cases = load_support_label_cases(os.path.join("data", "eval", "support_eval.json"))
            with open(output, encoding="utf-8") as handle:
                payload = json.load(handle)
            summary = validate_support_label_sidecar(payload, cases)

        self.assertEqual(summary["coverage"], 1.0)
        self.assertEqual(summary["dataset_cases"], len(cases))
        self.assertIn("claim", payload["cases"][0])

    def test_prepare_support_label_sidecar_audit_lists_unreviewed_high_risk_cases(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/prepare_support_label_sidecar.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--existing-sidecar",
                os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                "--audit",
            ],
            check=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        cases = load_support_label_cases(os.path.join("data", "eval", "support_eval.json"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["summary"]["coverage"], 1.0)
        self.assertEqual(payload["summary"]["human_reviewed"], 0)
        self.assertEqual(payload["label_maturity"]["reviewed_count"], 0)
        self.assertIsNone(payload["label_maturity"]["raw_dual_agreement_rate"])
        self.assertEqual(payload["label_maturity"]["dual_label_pair_counts"], {})
        self.assertEqual(payload["label_maturity"]["supported_disagreement_case_ids"], [])
        self.assertEqual(payload["unreviewed_count"], len(cases))
        self.assertGreater(payload["high_risk_unreviewed_count"], 0)
        self.assertLess(payload["high_risk_unreviewed_count"], payload["unreviewed_count"])
        self.assertEqual(len(payload["unreviewed"]), len(cases))
        self.assertEqual(len(payload["high_risk_unreviewed"]), payload["high_risk_unreviewed_count"])
        self.assertEqual(payload["high_risk_unreviewed"][0]["priority"], "high")
        self.assertIn(
            payload["high_risk_unreviewed"][0]["case_type"],
            {"contradiction", "hard_negative", "full_text_required"},
        )
        self.assertIn("test", payload["unreviewed_by_split"])
        self.assertTrue(any("high-priority" in action for action in payload["next_actions"]))

    def test_prepare_support_label_sidecar_can_filter_annotation_packet(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/prepare_support_label_sidecar.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--existing-sidecar",
                os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                "--audit",
                "--priority",
                "high",
                "--split",
                "test",
                "--include-context",
            ],
            check=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["filters"], {"priority": ["high"], "split": ["test"]})
        self.assertGreater(payload["unreviewed_count"], 0)
        self.assertEqual(payload["unreviewed_count"], payload["high_risk_unreviewed_count"])
        self.assertEqual(payload["summary"]["dataset_cases"], payload["unreviewed_count"])
        self.assertTrue(all(item["priority"] == "high" for item in payload["unreviewed"]))
        self.assertTrue(all(item["split"] == "test" for item in payload["unreviewed"]))
        self.assertTrue(all("claim" in item and "evidence" in item for item in payload["unreviewed"]))

    def test_prepare_support_label_sidecar_writes_blinded_annotation_packet(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/prepare_support_label_sidecar.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--existing-sidecar",
                os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                "--annotation-packet",
                "--priority",
                "high",
                "--split",
                "test",
                "--limit",
                "2",
            ],
            check=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        raw = completed.stdout

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["packet_type"], "support_label_annotation_packet")
        self.assertEqual(payload["filters"], {"priority": ["high"], "split": ["test"], "limit": 2})
        self.assertEqual(payload["n"], 2)
        self.assertEqual(payload["label_options"][0], "supported")
        self.assertTrue(all(item["priority"] == "high" for item in payload["cases"]))
        self.assertTrue(all(item["split"] == "test" for item in payload["cases"]))
        self.assertTrue(all(item["annotation"]["annotator_label"] == "" for item in payload["cases"]))
        self.assertIn("claim", payload["cases"][0])
        self.assertIn("evidence", payload["cases"][0])
        self.assertNotIn('"gold"', raw)
        self.assertNotIn("adjudicated_label", raw)
        self.assertNotIn("label_notes", raw)

    def test_prepare_support_label_sidecar_writes_annotation_instructions(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = os.path.join(tmpdir, "packet.json")
            instructions_path = os.path.join(tmpdir, "instructions.md")
            subprocess.run(
                [
                    sys.executable,
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    os.path.join("data", "eval", "support_eval.json"),
                    "--existing-sidecar",
                    os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                    "--annotation-packet",
                    "--case-id",
                    "s04",
                    "--output",
                    packet_path,
                    "--instructions-output",
                    instructions_path,
                ],
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )

            with open(packet_path, encoding="utf-8") as handle:
                packet = json.loads(handle.read())
            with open(instructions_path, encoding="utf-8") as handle:
                instructions = handle.read()

        self.assertEqual(packet["n"], 1)
        self.assertIn("CiteGuard Support Annotation Instructions", instructions)
        self.assertIn("Use exactly one of", instructions)
        self.assertIn("When unsure, choose the more conservative label", instructions)
        self.assertIn("annotation.annotator_id", instructions)
        self.assertIn("Do not edit `case_id`", instructions)
        self.assertNotIn("adjudicated_label", instructions)
        self.assertNotIn('"gold"', instructions)
        self.assertNotIn("label_notes", instructions)

    def test_prepare_support_label_sidecar_writes_jsonl_annotation_packet(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/prepare_support_label_sidecar.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--annotation-packet",
                "--packet-format",
                "jsonl",
                "--case-id",
                "s04",
                "--case-id",
                "s10",
            ],
            check=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        rows = [json.loads(line) for line in completed.stdout.splitlines()]

        self.assertEqual({row["case_id"] for row in rows}, {"s04", "s10"})
        self.assertTrue(all(row["annotation"]["rationale"] == "" for row in rows))
        self.assertTrue(all("gold" not in row for row in rows))
        self.assertTrue(all("adjudicated_label" not in row for row in rows))

    def test_prepare_support_label_sidecar_merges_completed_annotation_packet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = os.path.join(tmpdir, "completed_packet.json")
            packet = {
                "packet_type": "support_label_annotation_packet",
                "cases": [
                    {
                        "case_id": "s04",
                        "source_locator": "doi:10.123/example",
                        "annotation": {
                            "annotator_id": "reviewer-a",
                            "annotator_label": "contradicted",
                            "rationale": "Evidence directly says the method does not improve.",
                            "confidence": "high",
                        },
                    },
                    {
                        "case_id": "s10",
                        "annotation": {
                            "annotator_id": "reviewer-a",
                            "annotator_label": "contradicted",
                            "rationale": "The evidence rejects the universal support claim.",
                        },
                    },
                    {
                        "case_id": "s10",
                        "annotation": {
                            "annotator_id": "reviewer-b",
                            "annotator_label": "contradicted",
                            "rationale": "Real papers need not support every citing sentence.",
                        },
                    },
                ],
            }
            with open(packet_path, "w", encoding="utf-8") as handle:
                json.dump(packet, handle)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    os.path.join("data", "eval", "support_eval.json"),
                    "--existing-sidecar",
                    os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                    "--merge-annotation-packet",
                    packet_path,
                ],
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
        payload = json.loads(completed.stdout)
        cases = {item["case_id"]: item for item in payload["cases"]}

        self.assertTrue(payload["merge_report"]["ok"])
        self.assertEqual(payload["merge_report"]["applied_count"], 2)
        self.assertEqual(cases["s04"]["adjudication_status"], "single_annotator")
        self.assertEqual(cases["s04"]["source_locator"], "doi:10.123/example")
        self.assertIn("reviewer-a", cases["s04"]["notes"])
        self.assertEqual(cases["s10"]["adjudication_status"], "dual_annotator_agreed")
        self.assertEqual(cases["s10"]["annotator_count"], 2)
        self.assertEqual(cases["s10"]["annotator_labels"], ["contradicted", "contradicted"])

    def test_prepare_support_label_sidecar_reports_annotation_conflicts_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = os.path.join(tmpdir, "conflict_packet.jsonl")
            rows = [
                {
                    "case_id": "s04",
                    "annotation": {
                        "annotator_id": "reviewer-a",
                        "annotator_label": "supported",
                        "rationale": "Intentionally conflicts with the seed gold label.",
                    },
                }
            ]
            with open(packet_path, "w", encoding="utf-8") as handle:
                for row in rows:
                    handle.write(json.dumps(row) + "\n")

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    os.path.join("data", "eval", "support_eval.json"),
                    "--existing-sidecar",
                    os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                    "--merge-annotation-packet",
                    packet_path,
                ],
                check=False,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
        payload = json.loads(completed.stdout)
        cases = {item["case_id"]: item for item in payload["cases"]}

        self.assertEqual(completed.returncode, 1)
        self.assertFalse(payload["merge_report"]["ok"])
        self.assertEqual(payload["merge_report"]["conflicts"][0]["code"], "label_mismatch")
        self.assertEqual(cases["s04"]["adjudication_status"], "not_human_reviewed")
        self.assertEqual(cases["s04"]["annotator_labels"], [])

    def test_prepare_support_label_sidecar_requires_annotator_identity_for_merge(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = os.path.join(tmpdir, "missing_annotator_packet.json")
            packet = {
                "cases": [
                    {
                        "case_id": "s04",
                        "annotation": {
                            "annotator_label": "contradicted",
                            "rationale": "Correct label but missing annotator identity.",
                        },
                    }
                ]
            }
            with open(packet_path, "w", encoding="utf-8") as handle:
                json.dump(packet, handle)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    os.path.join("data", "eval", "support_eval.json"),
                    "--existing-sidecar",
                    os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                    "--merge-annotation-packet",
                    packet_path,
                ],
                check=False,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
        payload = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(payload["merge_report"]["skipped"][0]["code"], "missing_annotator_id")
        self.assertEqual(payload["merge_report"]["applied_count"], 0)

    def test_prepare_support_label_sidecar_rejects_duplicate_annotator_for_same_case(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = os.path.join(tmpdir, "duplicate_annotator_packet.json")
            packet = {
                "cases": [
                    {
                        "case_id": "s10",
                        "annotation": {
                            "annotator_id": "reviewer-a",
                            "annotator_label": "contradicted",
                        },
                    },
                    {
                        "case_id": "s10",
                        "annotation": {
                            "annotator_id": "reviewer-a",
                            "annotator_label": "contradicted",
                        },
                    },
                ]
            }
            with open(packet_path, "w", encoding="utf-8") as handle:
                json.dump(packet, handle)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    os.path.join("data", "eval", "support_eval.json"),
                    "--existing-sidecar",
                    os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                    "--merge-annotation-packet",
                    packet_path,
                ],
                check=False,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
        payload = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 1)
        self.assertEqual(payload["merge_report"]["conflicts"][0]["code"], "duplicate_annotator")
        self.assertEqual(payload["merge_report"]["conflicts"][0]["annotator_ids"], ["reviewer-a"])

    def test_prepare_support_label_sidecar_applies_resolved_adjudication(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adjudication_path = os.path.join(tmpdir, "adjudication.json")
            payload = {
                "cases": [
                    {
                        "case_id": "s04",
                        "annotator_labels": ["supported", "contradicted"],
                        "adjudicated_label": "contradicted",
                        "adjudicator": "reviewer-c",
                        "rationale": "The evidence explicitly rejects the improvement claim.",
                        "source_locator": "doi:10.123/adjudicated",
                    }
                ]
            }
            with open(adjudication_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    os.path.join("data", "eval", "support_eval.json"),
                    "--existing-sidecar",
                    os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                    "--apply-adjudications",
                    adjudication_path,
                ],
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
        output = json.loads(completed.stdout)
        cases = {item["case_id"]: item for item in output["cases"]}

        self.assertTrue(output["adjudication_report"]["ok"])
        self.assertEqual(output["adjudication_report"]["applied_case_ids"], ["s04"])
        self.assertEqual(cases["s04"]["adjudication_status"], "dual_annotator_adjudicated")
        self.assertEqual(cases["s04"]["disagreement"], "resolved")
        self.assertEqual(cases["s04"]["adjudicator"], "reviewer-c")
        self.assertEqual(cases["s04"]["source_locator"], "doi:10.123/adjudicated")
        self.assertIn("annotator_labels=supported, contradicted", cases["s04"]["notes"])

    def test_prepare_support_label_sidecar_reports_adjudication_gold_conflict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            adjudication_path = os.path.join(tmpdir, "adjudication_conflict.jsonl")
            with open(adjudication_path, "w", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "case_id": "s04",
                            "annotator_labels": ["supported", "contradicted"],
                            "adjudicated_label": "supported",
                            "adjudicator": "reviewer-c",
                        }
                    )
                    + "\n"
                )

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    os.path.join("data", "eval", "support_eval.json"),
                    "--existing-sidecar",
                    os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                    "--apply-adjudications",
                    adjudication_path,
                ],
                check=False,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
        output = json.loads(completed.stdout)
        cases = {item["case_id"]: item for item in output["cases"]}

        self.assertEqual(completed.returncode, 1)
        self.assertFalse(output["adjudication_report"]["ok"])
        self.assertEqual(output["adjudication_report"]["conflicts"][0]["code"], "adjudicated_label_mismatch")
        self.assertEqual(cases["s04"]["adjudication_status"], "not_human_reviewed")

    def test_prepare_support_label_sidecar_template_can_write_filtered_packet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output = os.path.join(tmpdir, "high-risk-test-sidecar.json")
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    os.path.join("data", "eval", "support_eval.json"),
                    "--existing-sidecar",
                    os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                    "--priority",
                    "high",
                    "--split",
                    "test",
                    "--include-context",
                    "--output",
                    output,
                ],
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
            with open(output, encoding="utf-8") as handle:
                payload = json.load(handle)

        self.assertEqual(completed.stdout, "")
        self.assertGreater(len(payload["cases"]), 0)
        self.assertLess(len(payload["cases"]), len(load_support_label_cases(os.path.join("data", "eval", "support_eval.json"))))
        self.assertTrue(all(item["case_type"] in {"contradiction", "hard_negative", "full_text_required", "contradiction_set"} for item in payload["cases"]))
        self.assertTrue(all(item["split"] == "test" for item in payload["cases"]))
        self.assertTrue(all("claim" in item and "evidence" in item for item in payload["cases"]))

    def test_prepare_support_label_sidecar_can_select_case_ids_and_limit_packet(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/prepare_support_label_sidecar.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--existing-sidecar",
                os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                "--audit",
                "--case-id",
                "s03",
                "--case-id",
                "s04",
                "--case-id",
                "s05",
                "--limit",
                "2",
            ],
            check=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["filters"], {"case_id": ["s03", "s04", "s05"], "limit": 2})
        self.assertEqual(payload["summary"]["dataset_cases"], 2)
        self.assertEqual({item["case_id"] for item in payload["unreviewed"]}, {"s03", "s04"})

    def test_prepare_support_label_sidecar_rejects_unknown_case_id(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/prepare_support_label_sidecar.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--case-id",
                "does-not-exist",
            ],
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("unknown --case-id value", completed.stderr)

    def test_prepare_support_label_sidecar_audit_can_fail_on_unreviewed_high_risk_cases(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/prepare_support_label_sidecar.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--existing-sidecar",
                os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                "--audit",
                "--fail-on-high-risk-unreviewed",
            ],
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 1)
        self.assertGreater(payload["high_risk_unreviewed_count"], 0)
        self.assertTrue(payload["ok"])

    def test_validate_support_label_sidecar_rejects_gold_mismatch(self):
        cases = [SupportCase("a", "claim", "evidence", "supported")]
        sidecar = {
            "schema_version": 1,
            "cases": [
                {
                    "case_id": "a",
                    "adjudication_status": "single_annotator",
                    "annotator_count": 1,
                    "annotator_labels": ["contradicted"],
                    "adjudicated_label": "contradicted",
                    "disagreement": "none",
                }
            ],
        }

        with self.assertRaises(SupportLabelSidecarValidationError) as raised:
            validate_support_label_sidecar(sidecar, cases)

        self.assertIn("does not match dataset gold", str(raised.exception))

    def test_validate_support_label_sidecar_enforces_status_consistency(self):
        cases = [
            SupportCase("unreviewed", "claim", "evidence", "supported"),
            SupportCase("agreed", "claim", "evidence", "supported"),
            SupportCase("adjudicated", "claim", "evidence", "supported"),
            SupportCase("published", "claim", "evidence", "supported"),
        ]
        sidecar = {
            "schema_version": 1,
            "cases": [
                {
                    "case_id": "unreviewed",
                    "adjudication_status": "not_human_reviewed",
                    "annotator_count": 1,
                    "annotator_labels": ["supported"],
                    "adjudicated_label": "supported",
                    "disagreement": "none",
                },
                {
                    "case_id": "agreed",
                    "adjudication_status": "dual_annotator_agreed",
                    "annotator_count": 2,
                    "annotator_labels": ["supported", "weakly_supported"],
                    "adjudicated_label": "supported",
                    "disagreement": "none",
                },
                {
                    "case_id": "adjudicated",
                    "adjudication_status": "dual_annotator_adjudicated",
                    "annotator_count": 2,
                    "annotator_labels": ["supported", "supported"],
                    "adjudicated_label": "supported",
                    "disagreement": "none",
                    "adjudicator": "reviewer-c",
                },
                {
                    "case_id": "published",
                    "adjudication_status": "published_benchmark",
                    "annotator_count": 0,
                    "annotator_labels": [],
                    "adjudicated_label": "supported",
                    "disagreement": "none",
                },
            ],
        }

        with self.assertRaises(SupportLabelSidecarValidationError) as raised:
            validate_support_label_sidecar(sidecar, cases)

        message = str(raised.exception)
        self.assertIn("not_human_reviewed requires annotator_count 0", message)
        self.assertIn("not_human_reviewed requires empty annotator_labels", message)
        self.assertIn("dual_annotator_agreed requires all annotator labels to match", message)
        self.assertIn("dual_annotator_adjudicated requires at least two distinct annotator labels", message)
        self.assertIn("dual_annotator_adjudicated requires disagreement 'resolved'", message)
        self.assertIn("published_benchmark requires source_locator", message)

    def test_validate_support_label_sidecar_accepts_consistent_published_and_adjudicated_labels(self):
        cases = [
            SupportCase("adjudicated", "claim", "evidence", "supported"),
            SupportCase("published", "claim", "evidence", "supported"),
        ]
        sidecar = {
            "schema_version": 1,
            "cases": [
                {
                    "case_id": "adjudicated",
                    "adjudication_status": "dual_annotator_adjudicated",
                    "annotator_count": 2,
                    "annotator_labels": ["supported", "weakly_supported"],
                    "adjudicated_label": "supported",
                    "disagreement": "resolved",
                    "adjudicator": "reviewer-c",
                    "source_locator": "doi:10.123/example",
                },
                {
                    "case_id": "published",
                    "adjudication_status": "published_benchmark",
                    "annotator_count": 0,
                    "annotator_labels": [],
                    "adjudicated_label": "supported",
                    "disagreement": "none",
                    "source_locator": "https://example.org/benchmark",
                },
            ],
        }

        summary = validate_support_label_sidecar(sidecar, cases)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["label_maturity"]["adjudicated_count"], 1)
        self.assertEqual(summary["label_maturity"]["published_benchmark_count"], 1)

    def test_validate_support_eval_dataset_reports_schema_and_coverage(self):
        dataset = {
            "schema_version": 2,
            "label_policy": {
                "scope": "unit test",
                "label_source": "maintainer_synthetic",
                "notes": "Synthetic coverage contract test.",
            },
            "cases": [
                {
                    "id": "a",
                    "claim": "claim",
                    "evidence": "abstract support",
                    "gold": "supported",
                    "lang": "en",
                    "evidence_scope": "abstract",
                    "label_source": "maintainer_synthetic",
                    "case_type": "direct_support",
                    "split": "train",
                },
                {
                    "id": "b",
                    "claim": "claim",
                    "evidence": "title",
                    "gold": "weakly_supported",
                    "lang": "en",
                    "evidence_scope": "title",
                    "label_source": "maintainer_synthetic",
                    "case_type": "weak_support",
                    "split": "dev",
                    "label_notes": "Title-only topical relevance.",
                },
                {
                    "id": "c",
                    "claim": "claim",
                    "evidence": "related but too weak",
                    "gold": "insufficient_evidence",
                    "lang": "en",
                    "evidence_scope": "abstract",
                    "label_source": "maintainer_synthetic",
                    "case_type": "hard_negative",
                    "split": "test",
                    "label_notes": "Related but does not support the stronger claim.",
                },
                {
                    "id": "d",
                    "claim": "claim",
                    "evidence": "unrelated",
                    "gold": "insufficient_evidence",
                    "lang": "en",
                    "evidence_scope": "abstract",
                    "label_source": "maintainer_synthetic",
                    "case_type": "unrelated_negative",
                    "split": "train",
                },
                {
                    "id": "e",
                    "claim": "claim",
                    "evidence": "contradiction",
                    "gold": "contradicted",
                    "lang": "en",
                    "evidence_scope": "metadata_snippet",
                    "label_source": "maintainer_synthetic",
                    "case_type": "contradiction",
                    "split": "dev",
                    "label_notes": "Explicit contradiction cue.",
                },
                {
                    "id": "f",
                    "claim": "claim",
                    "evidence": "abstract lacks methods detail",
                    "gold": "insufficient_evidence",
                    "lang": "en",
                    "evidence_scope": "abstract",
                    "label_source": "maintainer_synthetic",
                    "case_type": "full_text_required",
                    "split": "test",
                    "label_notes": "Requires methods details.",
                },
                {
                    "id": "g",
                    "claim": "claim",
                    "evidence": "full text support",
                    "gold": "supported",
                    "lang": "en",
                    "evidence_scope": "full_text",
                    "label_source": "maintainer_synthetic",
                    "case_type": "direct_support",
                    "split": "test",
                },
            ],
        }

        summary = validate_support_eval_dataset(dataset)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["n"], 7)
        self.assertEqual(summary["set_cases"]["n"], 0)
        self.assertEqual(summary["case_types"]["hard_negative"], 1)
        self.assertEqual(summary["splits"]["test"], 3)
        self.assertIn("maintainer_synthetic", summary["label_sources"])

    def test_validate_support_eval_dataset_reports_set_case_coverage(self):
        with open(os.path.join("data", "eval", "support_eval.json"), encoding="utf-8") as handle:
            summary = validate_support_eval_dataset(json.load(handle))

        self.assertGreaterEqual(summary["set_cases"]["n"], 4)
        self.assertEqual(summary["set_cases"]["case_types"]["weak_set_boundary"], 1)
        self.assertIn("test", summary["set_cases"]["splits"])

    def test_validate_support_eval_dataset_rejects_missing_coverage(self):
        dataset = {
            "schema_version": 2,
            "label_policy": {"label_source": "maintainer_synthetic", "notes": "x"},
            "cases": [
                {
                    "id": "a",
                    "claim": "claim",
                    "evidence": "evidence",
                    "gold": "supported",
                    "lang": "en",
                    "evidence_scope": "abstract",
                    "label_source": "maintainer_synthetic",
                    "case_type": "direct_support",
                    "split": "train",
                }
            ],
        }

        with self.assertRaises(SupportEvalValidationError) as raised:
            validate_support_eval_dataset(dataset)

        self.assertIn("required case_type coverage", str(raised.exception))

    def test_filter_support_cases_by_split(self):
        cases = [
            SupportCase("train", "claim", "evidence", "supported", split="train"),
            SupportCase("dev", "claim", "evidence", "supported", split="dev"),
            SupportCase("test", "claim", "evidence", "supported", split="test"),
        ]

        filtered = filter_support_cases_by_split(cases, "dev")

        self.assertEqual([case.case_id for case in filtered], ["dev"])
        with self.assertRaises(ValueError):
            filter_support_cases_by_split(cases, "holdout")

    def test_support_cases_build_records_with_declared_evidence_scope(self):
        cases = [
            SupportCase("title", "claim", "Title evidence", "supported", evidence_scope="title"),
            SupportCase("metadata", "claim", "Metadata evidence", "supported", evidence_scope="metadata_snippet"),
            SupportCase("full", "claim", "Full text evidence", "supported", evidence_scope="full_text"),
        ]

        scopes = []
        for case in cases:
            record = citation_record_for_support_case(case)
            spans = build_evidence_spans(record)
            scopes.append(spans[0]["evidence_scope"])

        self.assertEqual(scopes, ["title", "metadata_snippet", "full_text"])

    def test_compute_report_groups_by_case_type_and_scope(self):
        cases = [
            SupportCase(
                "a",
                "claim",
                "evidence",
                "supported",
                evidence_scope="abstract",
                case_type="direct_support",
            ),
            SupportCase(
                "b",
                "claim",
                "evidence",
                "insufficient_evidence",
                evidence_scope="abstract",
                case_type="hard_negative",
            ),
            SupportCase(
                "c",
                "claim",
                "evidence",
                "contradicted",
                evidence_scope="title",
                case_type="contradiction",
            ),
        ]
        report = compute_support_report(cases, ["supported", "supported", "contradicted"], backend_name="fake_nli")

        self.assertEqual(report["dataset"]["n"], 3)
        self.assertEqual(report["dataset"]["case_types"]["hard_negative"], 1)
        self.assertEqual(report["dataset"]["evidence_scopes"]["abstract"], 2)
        self.assertEqual(report["dataset"]["splits"]["test"], 3)
        self.assertEqual(report["overall"]["n"], 3)
        self.assertEqual(report["overall"]["false_support_rate"], 0.5)
        self.assertEqual(report["confusion_matrix"]["insufficient_evidence"]["supported"], 1)
        self.assertEqual(report["error_bucket_counts"]["false_support"], 1)
        self.assertEqual(report["error_bucket_counts"]["missed_contradiction"], 0)
        self.assertEqual(report["false_support_analysis"]["false_support_count"], 1)
        self.assertEqual(report["false_support_analysis"]["weak_false_support_count"], 0)
        self.assertEqual(report["false_support_analysis"]["by_case_type"]["hard_negative"]["case_ids"], ["b"])
        self.assertEqual(report["by_case_type"]["direct_support"]["accuracy"], 1.0)
        self.assertEqual(report["by_case_type"]["hard_negative"]["false_support_rate"], 1.0)
        self.assertEqual(report["by_evidence_scope"]["abstract"]["n"], 2)
        self.assertEqual(report["by_evidence_scope"]["title"]["contradiction_recall"], 1.0)
        self.assertEqual(report["by_split"]["test"]["n"], 3)
        self.assertEqual(report["diagnostics"]["backend"], "fake_nli")
        self.assertEqual(report["diagnostics"]["false_support_case_ids"], ["b"])
        self.assertEqual(report["cases"][1]["case_id"], "b")
        self.assertEqual(report["cases"][1]["split"], "test")
        self.assertFalse(report["cases"][1]["correct"])

    def test_fixture_eval_report_is_deterministic_and_model_free(self):
        cases = [
            SupportCase("a", "claim", "evidence", "supported", case_type="direct_support"),
            SupportCase("b", "claim", "evidence", "contradicted", case_type="contradiction"),
        ]

        metrics = run_support_eval_fixture(cases)
        report = run_support_eval_fixture_report(cases)

        self.assertEqual(metrics["accuracy"], 1.0)
        self.assertEqual(report["diagnostics"]["backend"], "deterministic_fixture")
        self.assertEqual(report["overall"]["accuracy"], 1.0)
        self.assertTrue(all(item["correct"] for item in report["cases"]))

    def test_support_set_policy_fixture_keeps_weak_sets_tentative(self):
        cases = load_support_set_eval(os.path.join("data", "eval", "support_eval.json"))
        by_id = {case.case_id: case for case in cases}
        report = run_support_set_policy_fixture_report(cases)

        self.assertEqual(predict_support_set_policy(by_id["ss02"]), "weakly_supported")
        self.assertEqual(predict_support_set_policy(by_id["ss03"]), "contradicted")
        self.assertEqual(report["overall"]["accuracy"], 1.0)
        self.assertEqual(report["dataset"]["case_types"]["weak_set_boundary"], 1)
        self.assertTrue(all(item["correct"] for item in report["cases"]))

    def test_quality_gate_passes_for_deterministic_fixture_report(self):
        cases = [
            SupportCase("a", "claim", "evidence", "supported", case_type="direct_support"),
            SupportCase("b", "claim", "evidence", "contradicted", case_type="contradiction"),
            SupportCase("c", "claim", "evidence", "insufficient_evidence", case_type="hard_negative"),
        ]

        report = run_support_eval_fixture_report(cases)
        gate = compute_support_quality_gate(report)

        self.assertTrue(gate["ok"])
        self.assertEqual(gate["failures"], [])
        self.assertEqual(gate["metrics"]["false_support_count"], 0)

    def test_quality_gate_fails_on_false_support(self):
        cases = [
            SupportCase("a", "claim", "evidence", "supported", case_type="direct_support"),
            SupportCase("b", "claim", "evidence", "insufficient_evidence", case_type="hard_negative"),
            SupportCase("c", "claim", "evidence", "contradicted", case_type="contradiction"),
        ]

        report = compute_support_report(cases, ["supported", "supported", "contradicted"])
        gate = compute_support_quality_gate(report)

        self.assertFalse(gate["ok"])
        self.assertIn("false_support_count", {failure["code"] for failure in gate["failures"]})
        self.assertIn("supported_precision", {failure["code"] for failure in gate["failures"]})
        self.assertEqual(gate["failures"][0]["case_ids"], ["b"])

    def test_quality_gate_fails_on_missed_contradiction(self):
        cases = [
            SupportCase("a", "claim", "evidence", "supported", case_type="direct_support"),
            SupportCase("b", "claim", "evidence", "contradicted", case_type="contradiction"),
        ]

        report = compute_support_report(cases, ["supported", "insufficient_evidence"])
        gate = compute_support_quality_gate(report)

        self.assertFalse(gate["ok"])
        self.assertIn("contradiction_recall", {failure["code"] for failure in gate["failures"]})
        self.assertEqual(gate["metrics"]["contradiction_recall"], 0.0)

    def test_eval_support_cli_quality_gate_exits_nonzero_on_failure(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/eval_support.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--split",
                "test",
                "--quality-gate",
                "--min-supported-precision",
                "1.1",
            ],
            check=False,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["quality_gate"]["ok"])
        self.assertEqual(payload["quality_gate"]["failures"][0]["code"], "supported_precision")
        self.assertIn("support_set_policy", payload)
        self.assertEqual(payload["support_set_policy"]["overall"]["accuracy"], 1.0)

    def test_eval_support_cli_sidecar_gate_exits_nonzero_on_review_threshold(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/eval_support.py",
                "--validate-only",
                "--label-sidecar",
                os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                "--min-human-reviewed",
                "1",
                "--min-dual-annotated",
                "1",
                "--min-raw-dual-agreement-rate",
                "0.8",
            ],
            check=False,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["label_sidecar_gate"]["ok"])
        self.assertEqual(
            {failure["code"] for failure in payload["label_sidecar_gate"]["failures"]},
            {
                "sidecar_human_reviewed",
                "sidecar_dual_annotated",
                "sidecar_raw_dual_agreement_rate",
            },
        )

    def test_diagnostics_flag_missed_contradictions_for_nli_review(self):
        cases = [
            SupportCase("a", "claim", "evidence", "contradicted", case_type="contradiction"),
            SupportCase("b", "claim", "evidence", "insufficient_evidence", case_type="hard_negative"),
        ]

        diagnostics = compute_support_diagnostics(
            cases,
            ["insufficient_evidence", "insufficient_evidence"],
            backend_name="heuristic",
        )

        self.assertTrue(diagnostics["heuristic_limited"])
        self.assertTrue(diagnostics["needs_nli_contradiction_review"])
        self.assertEqual(diagnostics["missed_contradiction_case_ids"], ["a"])
        self.assertEqual(diagnostics["contradiction_recall"], 0.0)
        self.assertTrue(any("contradiction" in warning for warning in diagnostics["warnings"]))

    def test_compute_report_rejects_prediction_length_mismatch(self):
        cases = [SupportCase("a", "claim", "evidence", "supported")]

        with self.assertRaises(ValueError):
            compute_support_report(cases, [])

    def test_error_buckets_identify_high_risk_support_failures(self):
        cases = [
            SupportCase("a", "claim", "evidence", "insufficient_evidence", case_type="hard_negative"),
            SupportCase("b", "claim", "evidence", "contradicted", case_type="contradiction"),
            SupportCase("c", "claim", "evidence", "supported", case_type="direct_support"),
            SupportCase("d", "claim", "evidence", "insufficient_evidence", case_type="unrelated_negative"),
        ]
        predictions = ["supported", "weakly_supported", "insufficient_evidence", "insufficient_evidence"]

        buckets = compute_support_error_buckets(cases, predictions)
        counts = compute_support_error_bucket_counts(cases, predictions)

        self.assertEqual(counts["false_support"], 1)
        self.assertEqual(counts["weak_false_support"], 1)
        self.assertEqual(counts["missed_contradiction"], 1)
        self.assertEqual(counts["supported_rejected"], 1)
        self.assertEqual(counts["incorrect_abstention"], 1)
        self.assertEqual(counts["correct_abstention"], 1)
        self.assertEqual(buckets["false_support"][0]["case_id"], "a")
        self.assertEqual(buckets["missed_contradiction"][0]["case_type"], "contradiction")

    def test_false_support_analysis_groups_overcalls_for_triage(self):
        cases = [
            SupportCase("a", "claim", "evidence", "insufficient_evidence", case_type="hard_negative", evidence_scope="abstract", split="test"),
            SupportCase("b", "claim", "evidence", "contradicted", case_type="contradiction", evidence_scope="metadata_snippet", split="test"),
            SupportCase("c", "claim", "evidence", "insufficient_evidence", case_type="full_text_required", evidence_scope="abstract", split="dev"),
        ]
        buckets = compute_support_error_buckets(cases, ["supported", "weakly_supported", "supported"])

        analysis = compute_false_support_analysis(buckets)

        self.assertEqual(analysis["false_support_count"], 2)
        self.assertEqual(analysis["weak_false_support_count"], 1)
        self.assertEqual(analysis["total_overcall_count"], 3)
        self.assertEqual(analysis["high_risk_case_ids"], ["a", "c"])
        self.assertEqual(analysis["by_case_type"]["hard_negative"]["false_support"], 1)
        self.assertEqual(analysis["by_case_type"]["contradiction"]["weak_false_support"], 1)
        self.assertEqual(analysis["by_evidence_scope"]["abstract"]["total"], 2)
        self.assertEqual(analysis["by_split"]["test"]["case_ids"], ["a", "b"])
        self.assertIn("highest-risk", analysis["interpretation"])


if __name__ == "__main__":
    unittest.main()
