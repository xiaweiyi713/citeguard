"""Tests for the support evaluation harness (metrics are model-free / synthetic)."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from citeguard.verification.support_eval import (
    SupportCase,
    SupportEvalValidationError,
    SupportLabelSidecarValidationError,
    build_support_label_sidecar_template,
    citation_record_for_support_case,
    compute_abstention_analysis,
    compute_release_blocker_summary,
    compute_support_confusion_matrix,
    compute_support_diagnostics,
    compute_support_error_bucket_counts,
    compute_support_error_buckets,
    compute_false_support_analysis,
    compute_false_support_acceptance_guard,
    compute_support_acceptance_slices,
    compute_support_label_sidecar_gate,
    compute_support_metrics,
    compute_support_quality_gate,
    compute_support_release_summary,
    compute_support_report,
    compute_support_review_queue,
    compute_support_review_queue_summary,
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

HIDDEN_PACKET_KEYS = {"gold", "predicted", "adjudicated_label", "annotator_labels", "label_notes"}


def _hidden_packet_key_leaks(value):
    if isinstance(value, dict):
        leaks = sorted(key for key in value if key in HIDDEN_PACKET_KEYS)
        for nested in value.values():
            leaks.extend(_hidden_packet_key_leaks(nested))
        return leaks
    if isinstance(value, list):
        leaks = []
        for item in value:
            leaks.extend(_hidden_packet_key_leaks(item))
        return leaks
    return []


def _rewrite_recommended_packet_command(command, *, output_path, instructions_path):
    rewritten = list(command)
    rewritten[0] = sys.executable
    for flag, value in (("--output", output_path), ("--instructions-output", instructions_path)):
        index = rewritten.index(flag)
        rewritten[index + 1] = value
    return rewritten


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
        self.assertEqual(m["macro_precision"], 0.625)
        self.assertEqual(m["macro_recall"], 0.625)
        self.assertEqual(m["macro_f1"], 0.5834)
        self.assertEqual(m["weighted_precision"], 0.875)
        self.assertEqual(m["weighted_recall"], 0.75)
        self.assertEqual(m["weighted_f1"], 0.75)
        self.assertEqual(m["false_support_rate"], 0.0)
        self.assertEqual(m["support_overcall_count"], 0)
        self.assertEqual(m["support_overcall_rate"], 0.0)
        self.assertEqual(m["abstention_rate"], 0.25)
        self.assertEqual(m["misjudged_support_rate"], 0.5)
        self.assertEqual(m["per_label"]["supported"]["tp"], 1)
        self.assertEqual(m["per_label"]["supported"]["gold"], 2)
        self.assertEqual(m["per_label"]["supported"]["predicted"], 1)
        self.assertEqual(m["per_label"]["supported"]["precision"], 1.0)
        self.assertEqual(m["per_label"]["supported"]["recall"], 0.5)
        self.assertEqual(round(m["per_label"]["supported"]["f1"], 4), 0.6667)
        self.assertEqual(m["per_label"]["contradicted"]["precision"], 0.5)
        self.assertEqual(m["per_label"]["insufficient_evidence"]["recall"], 1.0)

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
        self.assertGreaterEqual(len(cases), 40)
        self.assertGreaterEqual(len(set_cases), 6)
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
        self.assertIn("s31", case_ids)
        self.assertIn("s32", case_ids)
        self.assertIn("s33", case_ids)
        self.assertIn("s34", case_ids)
        self.assertIn("s35", case_ids)
        self.assertIn("s36", case_ids)
        self.assertIn("s37", case_ids)
        self.assertIn("s38", case_ids)
        self.assertIn("s39", case_ids)
        self.assertIn("s40", case_ids)
        self.assertIn("s41", case_ids)
        self.assertIn("s42", case_ids)
        self.assertIn("s43", case_ids)
        self.assertIn("s44", case_ids)
        self.assertIn("s47", case_ids)
        seeded_cases = {case.case_id: case for case in cases}
        self.assertEqual(seeded_cases["s31"].case_type, "hard_negative")
        self.assertEqual(seeded_cases["s31"].gold, "insufficient_evidence")
        self.assertIn("human-reviewed benchmark", seeded_cases["s31"].claim)
        self.assertEqual(seeded_cases["s32"].case_type, "contradiction")
        self.assertEqual(seeded_cases["s32"].gold, "contradicted")
        self.assertIn("source outage", seeded_cases["s32"].claim)
        self.assertEqual(seeded_cases["s33"].case_type, "full_text_required")
        self.assertEqual(seeded_cases["s33"].gold, "insufficient_evidence")
        self.assertIn("eligibility criterion", seeded_cases["s33"].claim)
        self.assertEqual(seeded_cases["s34"].case_type, "contradiction")
        self.assertEqual(seeded_cases["s34"].gold, "contradicted")
        self.assertIn("源不可达", seeded_cases["s34"].claim)
        self.assertEqual(seeded_cases["s35"].case_type, "hard_negative")
        self.assertEqual(seeded_cases["s35"].gold, "insufficient_evidence")
        self.assertIn("Crossref", seeded_cases["s35"].claim)
        self.assertEqual(seeded_cases["s36"].case_type, "contradiction")
        self.assertEqual(seeded_cases["s36"].gold, "contradicted")
        self.assertIn("限流", seeded_cases["s36"].claim)
        self.assertEqual(seeded_cases["s37"].case_type, "hard_negative")
        self.assertEqual(seeded_cases["s37"].gold, "insufficient_evidence")
        self.assertIn("caused reviewers", seeded_cases["s37"].claim)
        self.assertEqual(seeded_cases["s38"].case_type, "full_text_required")
        self.assertEqual(seeded_cases["s38"].gold, "insufficient_evidence")
        self.assertIn("excluded patients", seeded_cases["s38"].claim)
        self.assertEqual(seeded_cases["s39"].case_type, "contradiction")
        self.assertEqual(seeded_cases["s39"].gold, "contradicted")
        self.assertIn("来源暂时不可达", seeded_cases["s39"].claim)
        self.assertEqual(seeded_cases["s40"].case_type, "hard_negative")
        self.assertEqual(seeded_cases["s40"].gold, "insufficient_evidence")
        self.assertIn("自动替代人工审稿", seeded_cases["s40"].claim)
        self.assertEqual(seeded_cases["s41"].case_type, "hard_negative")
        self.assertEqual(seeded_cases["s41"].gold, "insufficient_evidence")
        self.assertIn("Two weakly related papers", seeded_cases["s41"].claim)
        self.assertEqual(seeded_cases["s42"].case_type, "contradiction")
        self.assertEqual(seeded_cases["s42"].gold, "contradicted")
        self.assertIn("model being available", seeded_cases["s42"].claim)
        self.assertEqual(seeded_cases["s43"].case_type, "full_text_required")
        self.assertEqual(seeded_cases["s43"].gold, "insufficient_evidence")
        self.assertIn("补充材料", seeded_cases["s43"].claim)
        self.assertEqual(seeded_cases["s44"].case_type, "contradiction")
        self.assertEqual(seeded_cases["s44"].gold, "contradicted")
        self.assertIn("Semantic Scholar", seeded_cases["s44"].claim)
        self.assertEqual(seeded_cases["s45"].case_type, "hard_negative")
        self.assertEqual(seeded_cases["s45"].gold, "insufficient_evidence")
        self.assertIn("deployed writing agents", seeded_cases["s45"].claim)
        self.assertEqual(seeded_cases["s46"].case_type, "hard_negative")
        self.assertEqual(seeded_cases["s46"].gold, "insufficient_evidence")
        self.assertIn("without human review", seeded_cases["s46"].claim)
        self.assertEqual(seeded_cases["s47"].case_type, "hard_negative")
        self.assertEqual(seeded_cases["s47"].gold, "insufficient_evidence")
        self.assertIn("manuscript acceptance rates", seeded_cases["s47"].claim)
        self.assertIn("s48", case_ids)
        self.assertEqual(seeded_cases["s48"].case_type, "contradiction")
        self.assertEqual(seeded_cases["s48"].gold, "contradicted")
        self.assertIn("Counter-evidence search leads", seeded_cases["s48"].claim)
        self.assertTrue(any(case.case_type == "hard_negative" for case in cases))
        self.assertTrue(any(case.case_type == "contradiction" for case in cases))
        self.assertTrue(any(case.case_type == "weak_support" for case in cases))
        self.assertTrue(any(case.case_type == "full_text_required" for case in cases))
        self.assertTrue(any(case.evidence_scope == "title" for case in cases))
        self.assertTrue(any(case.evidence_scope == "metadata_snippet" for case in cases))
        self.assertTrue(any(case.evidence_scope == "full_text" for case in cases))
        self.assertEqual(Counter(case.lang for case in cases), {"en": 36, "zh": 12})
        self.assertEqual({case.split for case in cases}, {"train", "dev", "test"})
        self.assertEqual(Counter(case.split for case in cases), {"train": 14, "dev": 15, "test": 19})
        self.assertTrue(any(case.case_type == "weak_set_boundary" for case in set_cases))
        self.assertTrue(any(case.case_type == "contradiction_set" for case in set_cases))
        set_case_ids = {case.case_id for case in set_cases}
        self.assertIn("ss05", set_case_ids)
        self.assertIn("ss06", set_case_ids)

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
        self.assertEqual(summary["sidecar_case_provenance"]["complete_count"], len(cases))
        self.assertEqual(summary["sidecar_case_provenance"]["complete_fraction"], 1.0)
        self.assertEqual(summary["sidecar_case_provenance"]["field_present_counts"]["label_source"], len(cases))
        self.assertEqual(summary["sidecar_case_provenance"]["field_present_counts"]["case_type"], len(cases))
        self.assertEqual(summary["sidecar_case_provenance"]["field_present_counts"]["evidence_scope"], len(cases))
        self.assertEqual(summary["sidecar_case_provenance"]["field_present_counts"]["split"], len(cases))
        self.assertEqual(summary["sidecar_case_provenance"]["field_present_counts"]["lang"], len(cases))
        self.assertEqual(summary["sidecar_case_provenance"]["missing_count"], 0)
        self.assertEqual(summary["sidecar_case_provenance"]["missing_case_ids"], [])
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
        self.assertEqual(summary["sidecar_case_provenance"]["missing_count"], 1)
        self.assertEqual(summary["sidecar_case_provenance"]["missing_case_ids"], ["b"])
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

    def test_support_label_sidecar_summarizes_high_risk_review_coverage(self):
        cases = [
            SupportCase("a", "claim", "evidence", "contradicted", lang="en", case_type="contradiction"),
            SupportCase("b", "claim", "evidence", "insufficient_evidence", lang="zh", case_type="hard_negative"),
            SupportCase("c", "claim", "evidence", "supported", lang="en", case_type="direct_support"),
            SupportCase(
                "d",
                "claim",
                "citation_verdicts: supported, contradicted",
                "contradicted",
                lang="zh",
                case_type="contradiction_set",
            ),
            SupportCase(
                "e",
                "claim",
                "citation_verdicts: weakly_supported, weakly_supported",
                "insufficient_evidence",
                lang="zh",
                case_type="weak_set_boundary",
            ),
            SupportCase(
                "f",
                "claim",
                "abstract evidence only",
                "insufficient_evidence",
                lang="en",
                case_type="full_text_required",
            ),
        ]
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
                },
                {
                    "case_id": "b",
                    "adjudication_status": "not_human_reviewed",
                    "annotator_count": 0,
                    "annotator_labels": [],
                    "adjudicated_label": "insufficient_evidence",
                    "disagreement": "not_applicable",
                },
                {
                    "case_id": "c",
                    "adjudication_status": "not_human_reviewed",
                    "annotator_count": 0,
                    "annotator_labels": [],
                    "adjudicated_label": "supported",
                    "disagreement": "not_applicable",
                },
                {
                    "case_id": "e",
                    "adjudication_status": "not_human_reviewed",
                    "annotator_count": 0,
                    "annotator_labels": [],
                    "adjudicated_label": "insufficient_evidence",
                    "disagreement": "not_applicable",
                },
            ],
        }

        summary = validate_support_label_sidecar(sidecar, cases)

        self.assertEqual(summary["high_risk_review"]["case_count"], 4)
        self.assertEqual(summary["high_risk_review"]["reviewed_count"], 1)
        self.assertEqual(summary["high_risk_review"]["unreviewed_count"], 3)
        self.assertEqual(summary["high_risk_review"]["case_count_by_language"], {"en": 2, "zh": 2})
        self.assertEqual(summary["high_risk_review"]["reviewed_by_language"], {"en": 1})
        self.assertEqual(summary["high_risk_review"]["unreviewed_by_language"], {"en": 1, "zh": 2})
        self.assertEqual(summary["high_risk_review"]["reviewed_case_ids"], ["a"])
        self.assertEqual(summary["high_risk_review"]["unreviewed_case_ids"], ["b", "d", "f"])
        self.assertEqual(summary["high_risk_review"]["reviewed_case_ids_by_language"], {"en": ["a"]})
        self.assertEqual(summary["high_risk_review"]["unreviewed_case_ids_by_language"], {"en": ["f"], "zh": ["b", "d"]})
        self.assertEqual(
            summary["high_risk_review"]["case_count_by_language_case_type"],
            {
                "en": {"contradiction": 1, "full_text_required": 1},
                "zh": {"contradiction_set": 1, "hard_negative": 1},
            },
        )
        self.assertEqual(
            summary["high_risk_review"]["reviewed_by_language_case_type"],
            {"en": {"contradiction": 1}},
        )
        self.assertEqual(
            summary["high_risk_review"]["unreviewed_by_language_case_type"],
            {
                "en": {"full_text_required": 1},
                "zh": {"contradiction_set": 1, "hard_negative": 1},
            },
        )
        self.assertEqual(
            summary["high_risk_review"]["unreviewed_by_case_type"],
            {"contradiction_set": 1, "full_text_required": 1, "hard_negative": 1},
        )
        self.assertEqual(summary["full_text_required_review"]["case_count"], 1)
        self.assertEqual(summary["full_text_required_review"]["reviewed_count"], 0)
        self.assertEqual(summary["full_text_required_review"]["unreviewed_count"], 1)
        self.assertEqual(summary["full_text_required_review"]["case_count_by_language"], {"en": 1})
        self.assertEqual(summary["full_text_required_review"]["unreviewed_by_language"], {"en": 1})
        self.assertEqual(summary["full_text_required_review"]["unreviewed_case_ids"], ["f"])
        self.assertEqual(summary["policy_boundary_review"]["case_count"], 1)
        self.assertEqual(summary["policy_boundary_review"]["reviewed_count"], 0)
        self.assertEqual(summary["policy_boundary_review"]["unreviewed_count"], 1)
        self.assertEqual(summary["policy_boundary_review"]["case_count_by_language"], {"zh": 1})
        self.assertEqual(summary["policy_boundary_review"]["unreviewed_by_language"], {"zh": 1})
        self.assertEqual(summary["policy_boundary_review"]["unreviewed_case_ids"], ["e"])
        self.assertEqual(summary["label_provenance"]["label_source_counts"], {"synthetic": 6})
        self.assertEqual(summary["label_provenance"]["status_by_label_source"]["synthetic"]["not_human_reviewed"], 3)
        self.assertEqual(summary["label_provenance"]["status_by_label_source"]["synthetic"]["single_annotator"], 1)
        self.assertEqual(summary["label_provenance"]["reviewed_by_label_source"], {"synthetic": 1})
        self.assertEqual(summary["label_provenance"]["unreviewed_by_label_source"], {"synthetic": 3})
        self.assertEqual(summary["label_provenance"]["reviewed_missing_source_locator_count"], 1)

    def test_support_label_sidecar_gate_checks_coverage_and_human_review(self):
        passing = compute_support_label_sidecar_gate(
            {
                "coverage": 1.0,
                "human_reviewed": 2,
                "dataset_cases": 4,
                "n": 4,
                "high_risk_review": {
                    "case_count": 2,
                    "reviewed_count": 1,
                    "unreviewed_count": 1,
                    "case_count_by_language": {"zh": 1},
                    "reviewed_by_language": {"zh": 1},
                    "unreviewed_by_language": {},
                    "case_count_by_language_case_type": {"zh": {"hard_negative": 1}},
                    "reviewed_by_language_case_type": {"zh": {"hard_negative": 1}},
                    "unreviewed_by_language_case_type": {},
                },
                "full_text_required_review": {
                    "case_count": 3,
                    "reviewed_count": 1,
                    "unreviewed_count": 2,
                    "case_count_by_language": {"en": 2, "zh": 1},
                    "reviewed_by_language": {"en": 1},
                    "unreviewed_by_language": {"en": 1, "zh": 1},
                    "unreviewed_case_ids": ["s30", "s43"],
                },
                "policy_boundary_review": {
                    "case_count": 2,
                    "reviewed_count": 1,
                    "unreviewed_count": 1,
                    "case_count_by_language": {"en": 1, "zh": 1},
                    "reviewed_by_language": {"en": 1},
                    "unreviewed_by_language": {"zh": 1},
                    "unreviewed_case_ids": ["ss05"],
                },
                "label_maturity": {
                    "dual_annotated_count": 1,
                    "unresolved_disagreement_count": 0,
                    "raw_dual_agreement_rate": 1.0,
                },
                "label_provenance": {
                    "label_source_counts": {"maintainer_synthetic": 4},
                    "reviewed_by_label_source": {"maintainer_synthetic": 2},
                    "unreviewed_by_label_source": {"maintainer_synthetic": 2},
                    "reviewed_source_locator_count": 1,
                    "reviewed_missing_source_locator_count": 1,
                    "published_benchmark_source_locator_count": 0,
                },
            },
            min_coverage=1.0,
            min_human_reviewed=2,
            min_high_risk_reviewed=1,
            min_high_risk_reviewed_by_language={"zh": 1},
            min_dual_annotated=1,
            max_unresolved_disagreements=0,
            min_raw_dual_agreement_rate=0.8,
        )
        failing = compute_support_label_sidecar_gate(
            {
                "coverage": 0.5,
                "human_reviewed": 0,
                "dataset_cases": 4,
                "n": 2,
                "high_risk_review": {
                    "case_count": 2,
                    "reviewed_count": 0,
                    "unreviewed_count": 2,
                    "case_count_by_language": {"en": 1, "zh": 1},
                    "reviewed_by_language": {},
                    "unreviewed_case_ids": ["b", "d"],
                    "unreviewed_case_ids_by_language": {"zh": ["b"], "en": ["d"]},
                },
            },
            min_coverage=1.0,
            min_human_reviewed=1,
            min_high_risk_reviewed=1,
            min_high_risk_reviewed_by_language={"zh": 1},
        )

        self.assertTrue(passing["ok"])
        self.assertEqual(passing["thresholds"]["min_high_risk_reviewed_by_language"], {"zh": 1})
        self.assertEqual(passing["metrics"]["high_risk_case_count_by_language"], {"zh": 1})
        self.assertEqual(passing["metrics"]["high_risk_reviewed_by_language"], {"zh": 1})
        self.assertEqual(passing["metrics"]["high_risk_unreviewed_by_language"], {})
        self.assertEqual(
            passing["metrics"]["high_risk_case_count_by_language_case_type"],
            {"zh": {"hard_negative": 1}},
        )
        self.assertEqual(
            passing["metrics"]["high_risk_reviewed_by_language_case_type"],
            {"zh": {"hard_negative": 1}},
        )
        self.assertEqual(passing["metrics"]["high_risk_unreviewed_by_language_case_type"], {})
        self.assertEqual(passing["metrics"]["full_text_required_case_count"], 3)
        self.assertEqual(passing["metrics"]["full_text_required_reviewed"], 1)
        self.assertEqual(passing["metrics"]["full_text_required_unreviewed"], 2)
        self.assertEqual(passing["metrics"]["full_text_required_unreviewed_by_language"], {"en": 1, "zh": 1})
        self.assertEqual(passing["metrics"]["full_text_required_unreviewed_case_ids"], ["s30", "s43"])
        self.assertEqual(passing["metrics"]["policy_boundary_case_count"], 2)
        self.assertEqual(passing["metrics"]["policy_boundary_reviewed"], 1)
        self.assertEqual(passing["metrics"]["policy_boundary_unreviewed"], 1)
        self.assertEqual(passing["metrics"]["policy_boundary_unreviewed_by_language"], {"zh": 1})
        self.assertEqual(passing["metrics"]["policy_boundary_unreviewed_case_ids"], ["ss05"])
        self.assertEqual(passing["metrics"]["label_source_counts"], {"maintainer_synthetic": 4})
        self.assertEqual(passing["metrics"]["reviewed_by_label_source"], {"maintainer_synthetic": 2})
        self.assertEqual(passing["metrics"]["unreviewed_by_label_source"], {"maintainer_synthetic": 2})
        self.assertEqual(passing["metrics"]["reviewed_source_locator_count"], 1)
        self.assertEqual(passing["metrics"]["reviewed_missing_source_locator_count"], 1)
        self.assertFalse(failing["ok"])
        self.assertEqual(
            {failure["code"] for failure in failing["failures"]},
            {
                "sidecar_coverage",
                "sidecar_human_reviewed",
                "sidecar_high_risk_reviewed",
                "sidecar_high_risk_reviewed_by_language",
            },
        )
        high_risk = next(
            failure for failure in failing["failures"] if failure["code"] == "sidecar_high_risk_reviewed"
        )
        self.assertEqual(high_risk["unreviewed_case_ids"], ["b", "d"])
        by_language = next(
            failure
            for failure in failing["failures"]
            if failure["code"] == "sidecar_high_risk_reviewed_by_language"
        )
        self.assertEqual(by_language["language"], "zh")
        self.assertEqual(by_language["unreviewed_case_ids"], ["b"])

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
                    "supported_disagreement_count": 1,
                    "supported_disagreement_case_ids": ["case-b"],
                },
            },
            min_dual_annotated=2,
            max_unresolved_disagreements=0,
            min_raw_dual_agreement_rate=0.8,
            max_supported_disagreements=0,
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
                "sidecar_supported_disagreements",
            },
        )
        unresolved = next(
            failure for failure in gate["failures"] if failure["code"] == "sidecar_unresolved_disagreements"
        )
        self.assertEqual(unresolved["case_ids"], ["case-b"])
        supported = next(
            failure for failure in gate["failures"] if failure["code"] == "sidecar_supported_disagreements"
        )
        self.assertEqual(supported["case_ids"], ["case-b"])
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
        self.assertEqual(template["cases"][0]["label_source"], "synthetic")
        self.assertEqual(template["cases"][0]["case_type"], "direct_support")
        self.assertEqual(template["cases"][0]["evidence_scope"], "abstract")
        self.assertEqual(template["cases"][0]["split"], "dev")
        self.assertEqual(template["cases"][1]["adjudication_status"], "not_human_reviewed")
        self.assertEqual(template["cases"][1]["annotator_count"], 0)
        self.assertEqual(template["cases"][1]["adjudicated_label"], "contradicted")
        self.assertEqual(template["cases"][1]["case_type"], "contradiction")
        self.assertEqual(template["cases"][1]["split"], "test")
        self.assertIn("Unreviewed seed label", template["cases"][1]["notes"])
        self.assertIn("evidence source", template["cases"][1]["notes"])
        self.assertEqual(template["cases"][1]["claim"], "claim b")
        self.assertEqual(template["cases"][1]["dataset_gold"], "contradicted")

    def test_validate_support_label_sidecar_rejects_case_provenance_mismatch(self):
        cases = [
            SupportCase(
                "a",
                "claim",
                "evidence",
                "supported",
                lang="en",
                evidence_scope="abstract",
                label_source="maintainer_synthetic",
                case_type="direct_support",
                split="test",
            )
        ]
        sidecar = build_support_label_sidecar_template(cases)
        sidecar["cases"][0]["case_type"] = "hard_negative"

        with self.assertRaises(SupportLabelSidecarValidationError) as raised:
            validate_support_label_sidecar(sidecar, cases)

        self.assertIn("case_type", str(raised.exception))
        self.assertIn("does not match dataset", str(raised.exception))

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
        self.assertTrue(payload["audit_gate"]["ok"])
        self.assertFalse(payload["audit_gate"]["thresholds"]["fail_on_high_risk_unreviewed"])
        self.assertEqual(payload["audit_gate"]["thresholds"]["fail_on_high_risk_unreviewed_languages"], [])
        self.assertFalse(payload["audit_gate"]["thresholds"]["fail_on_full_text_required_unreviewed"])
        self.assertFalse(payload["audit_gate"]["thresholds"]["fail_on_policy_boundary_unreviewed"])
        self.assertEqual(payload["audit_gate"]["metrics"]["unreviewed_count"], len(cases))
        self.assertEqual(
            payload["audit_gate"]["metrics"]["high_risk_unreviewed_count"],
            payload["high_risk_unreviewed_count"],
        )
        self.assertEqual(
            payload["audit_gate"]["metrics"]["full_text_required_unreviewed_count"],
            payload["full_text_required_unreviewed_count"],
        )
        self.assertEqual(
            payload["audit_gate"]["metrics"]["policy_boundary_unreviewed_count"],
            payload["policy_boundary_unreviewed_count"],
        )
        self.assertEqual(
            payload["audit_gate"]["metrics"]["high_risk_unreviewed_by_language"],
            payload["high_risk_unreviewed_by_language"],
        )
        self.assertEqual(
            payload["audit_gate"]["metrics"]["high_risk_unreviewed_by_language_case_type"],
            payload["high_risk_unreviewed_by_language_case_type"],
        )
        self.assertEqual(
            payload["audit_gate"]["metrics"]["full_text_required_unreviewed_by_language"],
            payload["full_text_required_unreviewed_by_language"],
        )
        self.assertEqual(
            payload["audit_gate"]["metrics"]["policy_boundary_unreviewed_by_language"],
            payload["policy_boundary_unreviewed_by_language"],
        )
        self.assertEqual(payload["audit_gate"]["failures"], [])
        self.assertEqual(payload["unreviewed_count"], len(cases))
        self.assertGreater(payload["high_risk_unreviewed_count"], 0)
        self.assertLess(payload["high_risk_unreviewed_count"], payload["unreviewed_count"])
        self.assertEqual(len(payload["unreviewed"]), len(cases))
        self.assertEqual(len(payload["high_risk_unreviewed"]), payload["high_risk_unreviewed_count"])
        self.assertEqual(
            len(payload["full_text_required_unreviewed"]),
            payload["full_text_required_unreviewed_count"],
        )
        self.assertEqual(payload["full_text_required_unreviewed_count"], 7)
        self.assertEqual(payload["full_text_required_unreviewed_by_language"], {"en": 6, "zh": 1})
        self.assertEqual(
            [item["case_id"] for item in payload["full_text_required_unreviewed"]],
            ["s17", "s30", "s43", "s13", "s38", "s20", "s33"],
        )
        self.assertEqual(len(payload["policy_boundary_unreviewed"]), payload["policy_boundary_unreviewed_count"])
        self.assertEqual(payload["policy_boundary_unreviewed_count"], 2)
        self.assertEqual(payload["policy_boundary_unreviewed_by_language"], {"en": 1, "zh": 1})
        self.assertEqual(
            [item["case_id"] for item in payload["policy_boundary_unreviewed"]],
            ["ss02", "ss05"],
        )
        self.assertEqual(payload["high_risk_unreviewed"][0]["priority"], "high")
        self.assertIn(
            payload["high_risk_unreviewed"][0]["case_type"],
            {"contradiction", "hard_negative", "full_text_required"},
        )
        self.assertIn("test", payload["unreviewed_by_split"])
        self.assertIn("zh", payload["unreviewed_by_language"])
        self.assertIn("zh", payload["high_risk_unreviewed_by_language"])
        self.assertEqual(
            payload["high_risk_unreviewed_by_language_case_type"],
            {
                "en": {
                    "contradiction": 9,
                    "contradiction_set": 1,
                    "full_text_required": 6,
                    "hard_negative": 10,
                },
                "zh": {
                    "contradiction": 6,
                    "full_text_required": 1,
                    "hard_negative": 2,
                },
            },
        )
        self.assertTrue(any("high-priority" in action for action in payload["next_actions"]))
        self.assertTrue(any("full-text-boundary review" in action for action in payload["next_actions"]))
        self.assertTrue(any("policy-boundary review" in action for action in payload["next_actions"]))
        recommendations = {item["id"]: item for item in payload["recommended_packets"]}
        self.assertIn("high_risk_unreviewed_balanced", recommendations)
        self.assertIn("high_risk_unreviewed_zh", recommendations)
        self.assertIn("high_risk_unreviewed_zh_contradiction", recommendations)
        self.assertIn("full_text_required_unreviewed", recommendations)
        self.assertIn("policy_boundary_unreviewed", recommendations)
        review_plan = payload["review_plan"]
        self.assertEqual(review_plan["schema_version"], 1)
        self.assertEqual(review_plan["status"], "blocked")
        self.assertEqual(review_plan["next_phase"], "first_review_high_risk")
        self.assertEqual(review_plan["human_reviewed"], 0)
        self.assertEqual(review_plan["high_risk_unreviewed"], payload["high_risk_unreviewed_count"])
        self.assertEqual(
            review_plan["high_risk_unreviewed_by_language_case_type"],
            payload["high_risk_unreviewed_by_language_case_type"],
        )
        self.assertEqual(review_plan["full_text_required_unreviewed"], 7)
        self.assertEqual(review_plan["policy_boundary_unreviewed"], 2)
        review_phases = {item["id"]: item for item in review_plan["phases"]}
        self.assertEqual(review_phases["first_review_high_risk"]["status"], "ready")
        self.assertEqual(review_phases["first_review_high_risk"]["candidate_case_count"], 37)
        self.assertEqual(
            review_phases["first_review_high_risk"]["candidate_case_count_by_language_case_type"],
            payload["high_risk_unreviewed_by_language_case_type"],
        )
        self.assertEqual(
            review_phases["first_review_high_risk"]["candidate_case_ids"][-2:],
            ["ss02", "ss05"],
        )
        self.assertEqual(
            len(review_phases["first_review_high_risk"]["recommended_packet_ids"]),
            len(set(review_phases["first_review_high_risk"]["recommended_packet_ids"])),
        )
        self.assertIn("high_risk_unreviewed_balanced", review_phases["first_review_high_risk"]["recommended_packet_ids"])
        self.assertIn(
            "high_risk_unreviewed_zh_contradiction",
            review_phases["first_review_high_risk"]["recommended_packet_ids"],
        )
        self.assertIn("policy_boundary_unreviewed", review_phases["first_review_high_risk"]["recommended_packet_ids"])
        self.assertEqual(review_phases["second_review"]["status"], "waiting_for_first_review")
        self.assertEqual(review_phases["adjudication"]["status"], "waiting_for_dual_annotation")
        self.assertIn("--apply-adjudications", review_phases["adjudication"]["command_template"])
        self.assertEqual(review_phases["raise_release_gates"]["status"], "blocked")
        self.assertEqual(
            review_phases["raise_release_gates"]["suggested_thresholds"]["max_supported_disagreements"],
            0,
        )
        self.assertIn("--max-supported-disagreements", review_phases["raise_release_gates"]["command_template"])
        balanced_command = recommendations["high_risk_unreviewed_balanced"]["command"]
        self.assertIn("--annotation-packet", balanced_command)
        self.assertIn("--review-phase", balanced_command)
        self.assertIn("first_review_high_risk", balanced_command)
        self.assertIn("--packet-purpose", balanced_command)
        self.assertIn("--unreviewed-only", balanced_command)
        self.assertIn("--limit-per-language", balanced_command)
        self.assertIn("--limit-per-case-type", balanced_command)
        self.assertIn("--limit-per-evidence-scope", balanced_command)
        self.assertEqual(
            recommendations["high_risk_unreviewed_balanced"]["candidate_case_count"],
            payload["high_risk_unreviewed_count"],
        )
        zh_recommendation = recommendations["high_risk_unreviewed_zh"]
        self.assertEqual(zh_recommendation["candidate_case_count"], payload["high_risk_unreviewed_by_language"]["zh"])
        self.assertIn("--lang", zh_recommendation["command"])
        self.assertIn("zh", zh_recommendation["command"])
        zh_contradiction_recommendation = recommendations["high_risk_unreviewed_zh_contradiction"]
        self.assertEqual(
            zh_contradiction_recommendation["candidate_case_count"],
            payload["high_risk_unreviewed_by_language_case_type"]["zh"]["contradiction"],
        )
        self.assertIn("--lang", zh_contradiction_recommendation["command"])
        self.assertIn("zh", zh_contradiction_recommendation["command"])
        self.assertIn("--case-type", zh_contradiction_recommendation["command"])
        self.assertIn("contradiction", zh_contradiction_recommendation["command"])
        full_text_recommendation = recommendations["full_text_required_unreviewed"]
        self.assertEqual(full_text_recommendation["candidate_case_count"], 7)
        self.assertEqual(
            full_text_recommendation["candidate_case_ids"],
            ["s17", "s30", "s43", "s13", "s38", "s20", "s33"],
        )
        self.assertIn("--case-type", full_text_recommendation["command"])
        self.assertIn("full_text_required", full_text_recommendation["command"])
        policy_recommendation = recommendations["policy_boundary_unreviewed"]
        self.assertEqual(policy_recommendation["candidate_case_count"], 2)
        self.assertEqual(policy_recommendation["candidate_case_ids"], ["ss02", "ss05"])
        self.assertIn("--case-type", policy_recommendation["command"])
        self.assertIn("weak_set_boundary", policy_recommendation["command"])
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = os.path.join(tmpdir, "recommended-zh-packet.json")
            instructions_path = os.path.join(tmpdir, "recommended-zh-instructions.md")
            command = _rewrite_recommended_packet_command(
                zh_recommendation["command"],
                output_path=packet_path,
                instructions_path=instructions_path,
            )
            subprocess.run(
                command,
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
            with open(packet_path, encoding="utf-8") as handle:
                packet = json.load(handle)
            with open(instructions_path, encoding="utf-8") as handle:
                instructions = handle.read()

        self.assertEqual(packet["packet_type"], "support_label_annotation_packet")
        self.assertEqual(packet["review_phase"], "first_review_high_risk")
        self.assertIn("high-risk `zh`", packet["packet_purpose"])
        self.assertEqual(packet["packet_summary"]["case_count_by_language"], {"zh": 9})
        self.assertEqual(packet["packet_summary"]["case_count_by_review_status"], {"not_human_reviewed": 9})
        self.assertTrue(all(item["lang"] == "zh" for item in packet["cases"]))
        self.assertTrue(all(item["review_phase"] == "first_review_high_risk" for item in packet["cases"]))
        self.assertIn("Packet summary", instructions)
        self.assertIn("Review phase", instructions)
        self.assertIn("Packet purpose", instructions)

        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = os.path.join(tmpdir, "recommended-full-text-packet.json")
            instructions_path = os.path.join(tmpdir, "recommended-full-text-instructions.md")
            command = _rewrite_recommended_packet_command(
                full_text_recommendation["command"],
                output_path=packet_path,
                instructions_path=instructions_path,
            )
            subprocess.run(
                command,
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
            with open(packet_path, encoding="utf-8") as handle:
                packet = json.load(handle)

        self.assertEqual(
            packet["packet_summary"]["case_ids"],
            ["s17", "s30", "s43", "s13", "s38", "s20", "s33"],
        )
        self.assertTrue(all(item["case_type"] == "full_text_required" for item in packet["cases"]))
        self.assertTrue(
            all("full-text" in item["review_focus"] or "full text" in item["review_focus"] for item in packet["cases"])
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = os.path.join(tmpdir, "recommended-policy-packet.json")
            instructions_path = os.path.join(tmpdir, "recommended-policy-instructions.md")
            command = _rewrite_recommended_packet_command(
                policy_recommendation["command"],
                output_path=packet_path,
                instructions_path=instructions_path,
            )
            subprocess.run(
                command,
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
            with open(packet_path, encoding="utf-8") as handle:
                packet = json.load(handle)

        self.assertEqual(packet["packet_summary"]["case_ids"], ["ss02", "ss05"])
        self.assertTrue(all(item["case_type"] == "weak_set_boundary" for item in packet["cases"]))
        self.assertTrue(
            all("multiple weak citations remain tentative" in item["review_focus"] for item in packet["cases"])
        )

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
                "--lang",
                "zh",
                "--include-context",
            ],
            check=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["filters"], {"priority": ["high"], "split": ["test"], "lang": ["zh"]})
        self.assertGreater(payload["unreviewed_count"], 0)
        self.assertEqual(payload["unreviewed_count"], payload["high_risk_unreviewed_count"])
        self.assertEqual(payload["summary"]["dataset_cases"], payload["unreviewed_count"])
        self.assertEqual(payload["unreviewed_by_language"], {"zh": payload["unreviewed_count"]})
        self.assertEqual(payload["high_risk_unreviewed_by_language"], {"zh": payload["high_risk_unreviewed_count"]})
        self.assertEqual(
            set(payload["high_risk_unreviewed_by_language_case_type"]),
            {"zh"},
        )
        self.assertEqual(
            sum(payload["high_risk_unreviewed_by_language_case_type"]["zh"].values()),
            payload["high_risk_unreviewed_count"],
        )
        self.assertTrue(all(item["priority"] == "high" for item in payload["unreviewed"]))
        self.assertTrue(all(item["split"] == "test" for item in payload["unreviewed"]))
        self.assertTrue(all(item["lang"] == "zh" for item in payload["unreviewed"]))
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
                "--lang",
                "zh",
                "--limit",
                "2",
            ],
            check=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["packet_type"], "support_label_annotation_packet")
        self.assertTrue(payload["packet_id"].startswith("support-packet-"))
        self.assertEqual(len(payload["packet_id"]), len("support-packet-") + 16)
        self.assertTrue(payload["packet_digest"].startswith("sha256:"))
        self.assertEqual(len(payload["packet_digest"]), len("sha256:") + 64)
        self.assertEqual(payload["filters"], {"priority": ["high"], "split": ["test"], "lang": ["zh"], "limit": 2})
        self.assertEqual(payload["n"], 2)
        self.assertEqual(payload["packet_summary"]["case_ids"], [item["case_id"] for item in payload["cases"]])
        self.assertEqual(payload["packet_summary"]["case_count_by_language"], {"zh": 2})
        self.assertEqual(payload["packet_summary"]["case_count_by_evidence_scope"], {"abstract": 1, "metadata_snippet": 1})
        self.assertEqual(payload["packet_summary"]["case_count_by_split"], {"test": 2})
        self.assertEqual(payload["packet_summary"]["case_count_by_priority"], {"high": 2})
        self.assertEqual(payload["packet_summary"]["case_count_by_review_status"], {"not_human_reviewed": 2})
        self.assertEqual(payload["review_protocol"]["packet_role"], "first_review")
        self.assertTrue(payload["review_protocol"]["independent_labeling_required"])
        self.assertTrue(payload["review_protocol"]["reviewer_must_not_see_hidden_labels"])
        self.assertEqual(payload["review_protocol"]["packet_target_annotator_count"], 1)
        self.assertEqual(payload["review_protocol"]["benchmark_target_annotator_count"], 2)
        self.assertEqual(payload["review_protocol"]["cases_already_single_annotated"], 0)
        self.assertTrue(payload["review_protocol"]["second_review_required_after_first_review"])
        self.assertTrue(payload["review_protocol"]["adjudication_required_on_disagreement"])
        self.assertTrue(all(item["review_protocol"] == payload["review_protocol"] for item in payload["cases"]))
        self.assertTrue(all(item["packet_id"] == payload["packet_id"] for item in payload["cases"]))
        self.assertTrue(all(item["packet_digest"] == payload["packet_digest"] for item in payload["cases"]))
        self.assertEqual([item["packet_case_index"] for item in payload["cases"]], [1, 2])
        self.assertEqual(payload["label_options"][0], "supported")
        self.assertEqual(
            payload["hidden_fields"],
            ["gold", "predicted", "adjudicated_label", "annotator_labels", "label_notes"],
        )
        self.assertTrue(all(item["priority"] == "high" for item in payload["cases"]))
        self.assertTrue(all(item["split"] == "test" for item in payload["cases"]))
        self.assertTrue(all(item["lang"] == "zh" for item in payload["cases"]))
        self.assertTrue(all(item["annotation"]["annotator_label"] == "" for item in payload["cases"]))
        self.assertTrue(all(item["annotation"]["evidence_scope_assessed"] == "" for item in payload["cases"]))
        self.assertTrue(all(item["annotation"]["full_text_needed"] == "" for item in payload["cases"]))
        self.assertIn("claim", payload["cases"][0])
        self.assertIn("evidence", payload["cases"][0])
        self.assertIn("review_focus", payload["cases"][0])
        self.assertIn("Check whether", payload["cases"][0]["review_focus"])
        self.assertIn("review_focus", payload["instructions"][-1])
        self.assertEqual(_hidden_packet_key_leaks(payload["cases"]), [])
        self.assertEqual(_hidden_packet_key_leaks(payload["packet_summary"]), [])

    def test_prepare_support_label_sidecar_can_build_packet_from_review_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = os.path.join(tmpdir, "review-queue-packet.json")
            instructions_path = os.path.join(tmpdir, "review-queue-instructions.md")
            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    os.path.join("data", "eval", "support_eval.json"),
                    "--existing-sidecar",
                    os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                    "--annotation-packet",
                    "--from-review-queue",
                    "--review-backend",
                    "heuristic",
                    "--split",
                    "test",
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
                raw = handle.read()
            payload = json.loads(raw)
            with open(instructions_path, encoding="utf-8") as handle:
                instructions = handle.read()

        self.assertEqual(completed.stdout, "")
        self.assertEqual(
            payload["filters"]["review_queue_case_ids"],
            ["s10", "s16", "s27", "s36", "s39", "s48", "s09", "s24"],
        )
        self.assertEqual(payload["filters"]["from_review_queue"], True)
        self.assertEqual(payload["filters"]["review_backend"], "heuristic")
        self.assertEqual(payload["filters"]["split"], ["test"])
        self.assertEqual(payload["packet_summary"]["case_ids"], payload["filters"]["review_queue_case_ids"])
        self.assertEqual([item["review_queue_rank"] for item in payload["cases"]], [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(payload["packet_summary"]["case_count_by_split"], {"test": 8})
        self.assertEqual(payload["packet_summary"]["case_count_by_review_status"], {"not_human_reviewed": 8})
        self.assertTrue(all(item["annotation"]["annotator_label"] == "" for item in payload["cases"]))
        self.assertIn("review_queue_rank", instructions)
        self.assertIn("do not treat it as a label hint", instructions)
        self.assertEqual(
            payload["hidden_fields"],
            ["gold", "predicted", "adjudicated_label", "annotator_labels", "label_notes"],
        )
        self.assertEqual(_hidden_packet_key_leaks(payload["cases"]), [])
        self.assertNotIn("missed_contradiction", raw)

    def test_prepare_support_label_sidecar_can_limit_annotation_packet_per_language(self):
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
                "--limit-per-language",
                "1",
            ],
            check=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        counts = Counter(item["lang"] for item in payload["cases"])

        self.assertEqual(
            payload["filters"],
            {"priority": ["high"], "split": ["test"], "limit_per_language": 1},
        )
        self.assertGreaterEqual(payload["n"], 2)
        self.assertLessEqual(max(counts.values()), 1)
        self.assertEqual(payload["packet_summary"]["case_count_by_language"], dict(counts))
        self.assertIn("en", counts)
        self.assertIn("zh", counts)

    def test_prepare_support_label_sidecar_can_limit_annotation_packet_per_case_type(self):
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
                "--limit-per-case-type",
                "1",
            ],
            check=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        counts = Counter(item["case_type"] for item in payload["cases"])

        self.assertEqual(payload["filters"], {"priority": ["high"], "limit_per_case_type": 1})
        self.assertGreaterEqual(payload["n"], 3)
        self.assertLessEqual(max(counts.values()), 1)
        self.assertEqual(payload["packet_summary"]["case_count_by_case_type"], dict(counts))
        self.assertIn("contradiction", counts)
        self.assertIn("hard_negative", counts)
        self.assertIn("full_text_required", counts)

    def test_prepare_support_label_sidecar_can_limit_annotation_packet_per_evidence_scope(self):
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
                "--limit-per-evidence-scope",
                "1",
            ],
            check=True,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)
        counts = Counter(item["evidence_scope"] for item in payload["cases"])

        self.assertEqual(payload["filters"], {"priority": ["high"], "limit_per_evidence_scope": 1})
        self.assertGreaterEqual(payload["n"], 3)
        self.assertLessEqual(max(counts.values()), 1)
        self.assertEqual(payload["packet_summary"]["case_count_by_evidence_scope"], dict(counts))
        self.assertIn("abstract", counts)
        self.assertIn("metadata_snippet", counts)
        self.assertIn("mixed", counts)

    def test_prepare_support_label_sidecar_can_filter_annotation_packet_to_unreviewed_cases(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sidecar_path = os.path.join(tmpdir, "sidecar.json")
            with open(os.path.join("data", "eval", "support_eval_label_sidecar.json"), encoding="utf-8") as handle:
                sidecar = json.load(handle)
            for item in sidecar["cases"]:
                if item["case_id"] == "s04":
                    item["adjudication_status"] = "single_annotator"
                    item["annotator_count"] = 1
                    item["annotator_labels"] = [item["adjudicated_label"]]
                    item["disagreement"] = "none"
                    item["notes"] = "Unit test reviewed case."
                    break
            with open(sidecar_path, "w", encoding="utf-8") as handle:
                json.dump(sidecar, handle)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    os.path.join("data", "eval", "support_eval.json"),
                    "--existing-sidecar",
                    sidecar_path,
                    "--annotation-packet",
                    "--case-id",
                    "s04",
                    "--case-id",
                    "s10",
                    "--unreviewed-only",
                ],
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["filters"], {"case_id": ["s04", "s10"], "unreviewed_only": True})
        self.assertEqual(payload["packet_summary"]["case_ids"], ["s10"])
        self.assertEqual(payload["n"], 1)
        self.assertEqual(payload["cases"][0]["case_id"], "s10")

    def test_prepare_support_label_sidecar_can_filter_annotation_packet_by_review_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sidecar_path = os.path.join(tmpdir, "sidecar.json")
            with open(os.path.join("data", "eval", "support_eval_label_sidecar.json"), encoding="utf-8") as handle:
                sidecar = json.load(handle)
            for item in sidecar["cases"]:
                if item["case_id"] == "s04":
                    item["adjudication_status"] = "single_annotator"
                    item["annotator_count"] = 1
                    item["annotator_labels"] = [item["adjudicated_label"]]
                    item["disagreement"] = "none"
                    item["notes"] = "Unit test first review complete."
                    break
            with open(sidecar_path, "w", encoding="utf-8") as handle:
                json.dump(sidecar, handle)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    os.path.join("data", "eval", "support_eval.json"),
                    "--existing-sidecar",
                    sidecar_path,
                    "--annotation-packet",
                    "--case-id",
                    "s04",
                    "--case-id",
                    "s10",
                    "--review-status",
                    "single_annotator",
                ],
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
        payload = json.loads(completed.stdout)

        self.assertEqual(payload["filters"], {"case_id": ["s04", "s10"], "review_status": ["single_annotator"]})
        self.assertEqual(payload["packet_summary"]["case_ids"], ["s04"])
        self.assertEqual(payload["packet_summary"]["case_count_by_review_status"], {"single_annotator": 1})
        self.assertEqual(payload["cases"][0]["review_status"], "single_annotator")

    def test_prepare_support_label_sidecar_audit_recommends_second_reviewer_packets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sidecar_path = os.path.join(tmpdir, "sidecar.json")
            with open(os.path.join("data", "eval", "support_eval_label_sidecar.json"), encoding="utf-8") as handle:
                sidecar = json.load(handle)
            for item in sidecar["cases"]:
                if item["case_id"] == "s04":
                    item["adjudication_status"] = "single_annotator"
                    item["annotator_count"] = 1
                    item["annotator_labels"] = [item["adjudicated_label"]]
                    item["disagreement"] = "none"
                    item["notes"] = "Unit test first review complete."
                    break
            with open(sidecar_path, "w", encoding="utf-8") as handle:
                json.dump(sidecar, handle)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    os.path.join("data", "eval", "support_eval.json"),
                    "--existing-sidecar",
                    sidecar_path,
                    "--audit",
                ],
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout)
            recommendations = {item["id"]: item for item in payload["recommended_packets"]}

            self.assertEqual(payload["label_maturity"]["single_annotator_count"], 1)
            self.assertEqual(payload["review_plan"]["next_phase"], "first_review_high_risk")
            review_phases = {item["id"]: item for item in payload["review_plan"]["phases"]}
            self.assertEqual(review_phases["second_review"]["status"], "ready")
            self.assertEqual(review_phases["second_review"]["candidate_case_count"], 1)
            self.assertEqual(
                review_phases["second_review"]["recommended_packet_ids"],
                ["single_annotator_second_reviewer"],
            )
            self.assertIn("single_annotator_second_reviewer", recommendations)
            command = recommendations["single_annotator_second_reviewer"]["command"]
            self.assertIn("--review-status", command)
            self.assertIn("single_annotator", command)
            self.assertEqual(recommendations["single_annotator_second_reviewer"]["candidate_case_count"], 1)
            packet_path = os.path.join(tmpdir, "second-review-packet.json")
            command = _rewrite_recommended_packet_command(
                command,
                output_path=packet_path,
                instructions_path=os.path.join(tmpdir, "second-review-instructions.md"),
            )
            subprocess.run(
                command,
                check=True,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )
            packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
        self.assertEqual(packet["review_protocol"]["packet_role"], "second_review")
        self.assertEqual(packet["review_protocol"]["cases_already_single_annotated"], 1)
        self.assertFalse(packet["review_protocol"]["second_review_required_after_first_review"])
        self.assertTrue(packet["review_protocol"]["independent_labeling_required"])

    def test_prepare_support_label_sidecar_rejects_conflicting_review_status_filters(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/prepare_support_label_sidecar.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--existing-sidecar",
                os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                "--annotation-packet",
                "--unreviewed-only",
                "--review-status",
                "single_annotator",
            ],
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )

        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("--unreviewed-only cannot be combined with --review-status", completed.stderr)

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
        self.assertIn("review_focus", instructions)
        self.assertIn("Packet id", instructions)
        self.assertIn("packet_case_index", instructions)
        self.assertIn("Packet summary", instructions)
        self.assertIn("Review protocol", instructions)
        self.assertIn("independent annotation", instructions)
        self.assertIn("review_protocol", instructions)
        self.assertIn("Hidden fields", instructions)
        self.assertIn("case_count_by_language", instructions)
        self.assertIn("case_count_by_evidence_scope", instructions)
        self.assertIn("case_count_by_review_status", instructions)
        self.assertIn("label hint", instructions)
        self.assertIn("Do not edit `case_id`", instructions)
        self.assertEqual(
            packet["hidden_fields"],
            ["gold", "predicted", "adjudicated_label", "annotator_labels", "label_notes"],
        )
        self.assertEqual(_hidden_packet_key_leaks(packet["cases"]), [])

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
        self.assertEqual(len({row["packet_id"] for row in rows}), 1)
        self.assertEqual(len({row["packet_digest"] for row in rows}), 1)
        self.assertTrue(rows[0]["packet_digest"].startswith("sha256:"))
        self.assertEqual([row["packet_case_index"] for row in rows], [1, 2])
        self.assertTrue(all(row["annotation"]["rationale"] == "" for row in rows))
        self.assertTrue(all(row["review_focus"] for row in rows))
        self.assertTrue(all(row["review_protocol"]["packet_role"] == "first_review" for row in rows))
        self.assertTrue(all(row["review_protocol"]["independent_labeling_required"] for row in rows))
        self.assertTrue(all(row["review_protocol"]["benchmark_target_annotator_count"] == 2 for row in rows))
        self.assertTrue(all("gold" not in row for row in rows))
        self.assertTrue(all("adjudicated_label" not in row for row in rows))

    def test_prepare_support_label_sidecar_merges_completed_annotation_packet(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = os.path.join(tmpdir, "completed_packet.json")
            packet = {
                "packet_type": "support_label_annotation_packet",
                "packet_id": "support-packet-test1234",
                "packet_digest": "sha256:" + "a" * 64,
                "review_phase": "first_review_high_risk",
                "packet_purpose": "Assign a balanced first-review packet for unreviewed high-risk support cases.",
                "cases": [
                    {
                        "packet_id": "support-packet-test1234",
                        "packet_case_index": 1,
                        "case_id": "s04",
                        "source_locator": "doi:10.123/example",
                        "annotation": {
                            "annotator_id": "reviewer-a",
                            "annotator_label": "contradicted",
                            "rationale": "Evidence directly says the method does not improve.",
                            "confidence": "high",
                            "evidence_scope_assessed": "abstract",
                            "full_text_needed": "no",
                        },
                    },
                    {
                        "packet_id": "support-packet-test1234",
                        "packet_case_index": 2,
                        "case_id": "s10",
                        "annotation": {
                            "annotator_id": "reviewer-a",
                            "annotator_label": "contradicted",
                            "rationale": "The evidence rejects the universal support claim.",
                        },
                    },
                    {
                        "packet_id": "support-packet-test1234",
                        "packet_case_index": 3,
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
        self.assertEqual(payload["merge_report"]["source_packet_ids"], ["support-packet-test1234"])
        self.assertEqual(
            payload["merge_report"]["source_packet_metadata"],
            [
                {
                    "packet_id": "support-packet-test1234",
                    "packet_digest": "sha256:" + "a" * 64,
                    "review_phase": "first_review_high_risk",
                    "packet_purpose": "Assign a balanced first-review packet for unreviewed high-risk support cases.",
                }
            ],
        )
        self.assertEqual(cases["s04"]["adjudication_status"], "single_annotator")
        self.assertEqual(cases["s04"]["source_locator"], "doi:10.123/example")
        self.assertIn("reviewer-a", cases["s04"]["notes"])
        self.assertIn("evidence_scope_assessed=abstract", cases["s04"]["notes"])
        self.assertIn("full_text_needed=no", cases["s04"]["notes"])
        self.assertIn("review_phase=first_review_high_risk", cases["s04"]["notes"])
        self.assertIn("packet_purpose=Assign a balanced first-review packet", cases["s04"]["notes"])
        self.assertIn("packet_digest=sha256:", cases["s04"]["notes"])
        self.assertEqual(cases["s10"]["adjudication_status"], "dual_annotator_agreed")
        self.assertEqual(cases["s10"]["annotator_count"], 2)
        self.assertEqual(cases["s10"]["annotator_labels"], ["contradicted", "contradicted"])

    def test_prepare_support_label_sidecar_reports_annotation_conflicts_without_overwriting(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = os.path.join(tmpdir, "conflict_packet.jsonl")
            rows = [
                {
                    "packet_id": "support-packet-conflict",
                    "packet_digest": "sha256:" + "b" * 64,
                    "packet_case_index": 1,
                    "case_id": "s04",
                    "review_phase": "first_review_high_risk",
                    "packet_purpose": "Assign a balanced first-review packet for unreviewed high-risk support cases.",
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
        self.assertEqual(payload["merge_report"]["conflicts"][0]["annotation_examples"][0]["packet_id"], "support-packet-conflict")
        self.assertEqual(payload["merge_report"]["conflicts"][0]["annotation_examples"][0]["packet_digest"], "sha256:" + "b" * 64)
        self.assertEqual(payload["merge_report"]["conflicts"][0]["annotation_examples"][0]["packet_case_index"], 1)
        self.assertEqual(payload["merge_report"]["conflicts"][0]["annotation_examples"][0]["annotator_id"], "reviewer-a")
        self.assertEqual(payload["merge_report"]["conflicts"][0]["annotation_examples"][0]["label"], "supported")
        self.assertEqual(
            payload["merge_report"]["conflicts"][0]["annotation_examples"][0]["review_phase"],
            "first_review_high_risk",
        )
        self.assertIn(
            "balanced first-review",
            payload["merge_report"]["conflicts"][0]["annotation_examples"][0]["packet_purpose"],
        )
        self.assertIn("Intentionally conflicts", payload["merge_report"]["conflicts"][0]["annotation_examples"][0]["rationale"])
        self.assertEqual(payload["merge_report"]["adjudication_queue"][0]["case_id"], "s04")
        self.assertEqual(payload["merge_report"]["adjudication_queue"][0]["conflict_code"], "label_mismatch")
        self.assertEqual(payload["merge_report"]["adjudication_queue"][0]["adjudication_template"]["case_id"], "s04")
        self.assertEqual(payload["merge_report"]["adjudication_queue"][0]["adjudication_template"]["annotator_labels"], ["supported"])
        self.assertEqual(payload["merge_report"]["adjudication_queue"][0]["adjudication_template"]["adjudicated_label"], "")
        self.assertEqual(payload["merge_report"]["adjudication_queue"][0]["adjudication_template"]["source_packet_ids"], ["support-packet-conflict"])
        self.assertEqual(
            payload["merge_report"]["adjudication_queue"][0]["adjudication_template"]["source_packet_metadata"],
            [
                {
                    "packet_id": "support-packet-conflict",
                    "packet_digest": "sha256:" + "b" * 64,
                    "review_phase": "first_review_high_risk",
                    "packet_purpose": "Assign a balanced first-review packet for unreviewed high-risk support cases.",
                }
            ],
        )
        self.assertEqual(cases["s04"]["adjudication_status"], "not_human_reviewed")
        self.assertEqual(cases["s04"]["annotator_labels"], [])

    def test_prepare_support_label_sidecar_reports_annotator_disagreement_queue(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            packet_path = os.path.join(tmpdir, "disagreement_packet.json")
            packet = {
                "packet_id": "support-packet-disagreement",
                "packet_digest": "sha256:" + "c" * 64,
                "review_phase": "first_review_high_risk",
                "packet_purpose": "Assign a balanced first-review packet for unreviewed high-risk support cases.",
                "cases": [
                    {
                        "packet_id": "support-packet-disagreement",
                        "packet_case_index": 1,
                        "case_id": "s04",
                        "annotation": {
                            "annotator_id": "reviewer-a",
                            "annotator_label": "contradicted",
                            "rationale": "The evidence rejects the claimed improvement.",
                            "confidence": "high",
                        },
                    },
                    {
                        "packet_id": "support-packet-disagreement",
                        "packet_case_index": 2,
                        "case_id": "s04",
                        "annotation": {
                            "annotator_id": "reviewer-b",
                            "annotator_label": "weakly_supported",
                            "rationale": "The evidence seems related but not decisive.",
                            "confidence": "low",
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
        cases = {item["case_id"]: item for item in payload["cases"]}
        conflict = payload["merge_report"]["conflicts"][0]
        queue_item = payload["merge_report"]["adjudication_queue"][0]

        self.assertEqual(completed.returncode, 1)
        self.assertFalse(payload["merge_report"]["ok"])
        self.assertEqual(conflict["code"], "annotator_disagreement")
        self.assertEqual(conflict["annotator_labels"], ["contradicted", "weakly_supported"])
        self.assertEqual([item["packet_id"] for item in conflict["annotation_examples"]], ["support-packet-disagreement", "support-packet-disagreement"])
        self.assertEqual([item["packet_digest"] for item in conflict["annotation_examples"]], ["sha256:" + "c" * 64, "sha256:" + "c" * 64])
        self.assertEqual([item["packet_case_index"] for item in conflict["annotation_examples"]], [1, 2])
        self.assertEqual([item["annotator_id"] for item in conflict["annotation_examples"]], ["reviewer-a", "reviewer-b"])
        self.assertEqual([item["confidence"] for item in conflict["annotation_examples"]], ["high", "low"])
        self.assertEqual(queue_item["conflict_code"], "annotator_disagreement")
        self.assertEqual(queue_item["adjudication_template"]["annotator_labels"], ["contradicted", "weakly_supported"])
        self.assertEqual(queue_item["adjudication_template"]["source_packet_ids"], ["support-packet-disagreement"])
        self.assertEqual(
            queue_item["adjudication_template"]["source_packet_metadata"],
            [
                {
                    "packet_id": "support-packet-disagreement",
                    "packet_digest": "sha256:" + "c" * 64,
                    "review_phase": "first_review_high_risk",
                    "packet_purpose": "Assign a balanced first-review packet for unreviewed high-risk support cases.",
                }
            ],
        )
        self.assertIn("--apply-adjudications", queue_item["recommended_action"])
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
                        "source_packet_ids": ["support-packet-conflict"],
                        "source_packet_metadata": [
                            {
                                "packet_id": "support-packet-conflict",
                                "packet_digest": "sha256:" + "d" * 64,
                                "review_phase": "first_review_high_risk",
                                "packet_purpose": "Assign a balanced first-review packet for unreviewed high-risk support cases.",
                            }
                        ],
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
        self.assertEqual(output["adjudication_report"]["source_packet_ids"], ["support-packet-conflict"])
        self.assertEqual(
            output["adjudication_report"]["source_packet_metadata"],
            [
                {
                    "packet_id": "support-packet-conflict",
                    "packet_digest": "sha256:" + "d" * 64,
                    "review_phase": "first_review_high_risk",
                    "packet_purpose": "Assign a balanced first-review packet for unreviewed high-risk support cases.",
                }
            ],
        )
        self.assertEqual(cases["s04"]["adjudication_status"], "dual_annotator_adjudicated")
        self.assertEqual(cases["s04"]["disagreement"], "resolved")
        self.assertEqual(cases["s04"]["adjudicator"], "reviewer-c")
        self.assertEqual(cases["s04"]["source_locator"], "doi:10.123/adjudicated")
        self.assertIn("annotator_labels=supported, contradicted", cases["s04"]["notes"])
        self.assertIn("source_packet_ids=support-packet-conflict", cases["s04"]["notes"])
        self.assertIn("review_phase=first_review_high_risk", cases["s04"]["notes"])
        self.assertIn("packet_purpose=Assign a balanced first-review packet", cases["s04"]["notes"])
        self.assertIn("packet_digest=sha256:", cases["s04"]["notes"])

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
        self.assertFalse(payload["audit_gate"]["ok"])
        self.assertTrue(payload["audit_gate"]["thresholds"]["fail_on_high_risk_unreviewed"])
        self.assertEqual(
            payload["audit_gate"]["metrics"]["high_risk_unreviewed_count"],
            payload["high_risk_unreviewed_count"],
        )
        self.assertEqual(payload["audit_gate"]["failures"][0]["code"], "high_risk_unreviewed")

    def test_prepare_support_label_sidecar_audit_can_fail_on_language_high_risk_cases(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/prepare_support_label_sidecar.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--existing-sidecar",
                os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                "--audit",
                "--fail-on-high-risk-unreviewed-language",
                "zh",
            ],
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 1)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["audit_gate"]["ok"])
        self.assertEqual(payload["audit_gate"]["thresholds"]["fail_on_high_risk_unreviewed_languages"], ["zh"])
        self.assertEqual(
            payload["audit_gate"]["metrics"]["high_risk_unreviewed_by_language"]["zh"],
            payload["high_risk_unreviewed_by_language"]["zh"],
        )
        failure = payload["audit_gate"]["failures"][0]
        self.assertEqual(failure["code"], "high_risk_unreviewed_by_language")
        self.assertEqual(failure["language"], "zh")
        self.assertEqual(failure["actual"], payload["high_risk_unreviewed_by_language"]["zh"])
        self.assertIn("s34", failure["case_ids"])

    def test_prepare_support_label_sidecar_audit_can_fail_on_full_text_boundary_cases(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/prepare_support_label_sidecar.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--existing-sidecar",
                os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                "--audit",
                "--fail-on-full-text-required-unreviewed",
            ],
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 1)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["audit_gate"]["ok"])
        self.assertTrue(payload["audit_gate"]["thresholds"]["fail_on_full_text_required_unreviewed"])
        self.assertEqual(
            payload["audit_gate"]["metrics"]["full_text_required_unreviewed_count"],
            payload["full_text_required_unreviewed_count"],
        )
        failure = payload["audit_gate"]["failures"][0]
        self.assertEqual(failure["code"], "full_text_required_unreviewed")
        self.assertEqual(failure["actual"], payload["full_text_required_unreviewed_count"])
        self.assertEqual(failure["case_ids"], ["s17", "s30", "s43", "s13", "s38", "s20", "s33"])

    def test_prepare_support_label_sidecar_audit_can_fail_on_policy_boundary_cases(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/prepare_support_label_sidecar.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--existing-sidecar",
                os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                "--audit",
                "--fail-on-policy-boundary-unreviewed",
            ],
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )
        payload = json.loads(completed.stdout)

        self.assertEqual(completed.returncode, 1)
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["audit_gate"]["ok"])
        self.assertTrue(payload["audit_gate"]["thresholds"]["fail_on_policy_boundary_unreviewed"])
        self.assertEqual(
            payload["audit_gate"]["metrics"]["policy_boundary_unreviewed_count"],
            payload["policy_boundary_unreviewed_count"],
        )
        failure = payload["audit_gate"]["failures"][0]
        self.assertEqual(failure["code"], "policy_boundary_unreviewed")
        self.assertEqual(failure["actual"], payload["policy_boundary_unreviewed_count"])
        self.assertEqual(failure["case_ids"], ["ss02", "ss05"])

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
        self.assertEqual(summary["label_provenance"]["published_benchmark_count"], 1)
        self.assertEqual(summary["label_provenance"]["published_benchmark_source_locator_count"], 1)
        self.assertEqual(summary["label_provenance"]["reviewed_source_locator_count"], 2)
        self.assertEqual(summary["label_provenance"]["reviewed_missing_source_locator_count"], 0)

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
                    "split": "test",
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
                    "split": "dev",
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
                    "split": "test",
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
            "set_cases": [
                {
                    "id": "set-a",
                    "claim": "claim",
                    "citation_verdicts": ["supported", "insufficient_evidence"],
                    "gold": "supported",
                    "lang": "en",
                    "label_source": "maintainer_synthetic",
                    "case_type": "set_aggregation",
                    "split": "dev",
                    "label_notes": "One strong citation can support the claim while an unresolved citation remains visible.",
                },
                {
                    "id": "set-b",
                    "claim": "claim",
                    "citation_verdicts": ["weakly_supported", "weakly_supported"],
                    "gold": "weakly_supported",
                    "lang": "en",
                    "label_source": "maintainer_synthetic",
                    "case_type": "weak_set_boundary",
                    "split": "test",
                    "label_notes": "Multiple weak citations stay tentative rather than becoming full support.",
                },
                {
                    "id": "set-c",
                    "claim": "claim",
                    "citation_verdicts": ["supported", "contradicted"],
                    "gold": "contradicted",
                    "lang": "en",
                    "label_source": "maintainer_synthetic",
                    "case_type": "contradiction_set",
                    "split": "test",
                    "label_notes": "Contradictory evidence should dominate the aggregate verdict.",
                },
                {
                    "id": "set-d",
                    "claim": "claim",
                    "citation_verdicts": ["insufficient_evidence", "insufficient_evidence"],
                    "gold": "insufficient_evidence",
                    "lang": "en",
                    "label_source": "maintainer_synthetic",
                    "case_type": "set_aggregation",
                    "split": "train",
                    "label_notes": "A set of non-confirming citations should abstain.",
                },
            ],
        }

        summary = validate_support_eval_dataset(dataset)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["n"], 7)
        self.assertEqual(summary["set_cases"]["n"], 4)
        self.assertEqual(summary["case_types"]["hard_negative"], 1)
        self.assertEqual(summary["splits"]["test"], 5)
        self.assertEqual(summary["test_split"]["case_types"]["hard_negative"], 1)
        self.assertEqual(summary["test_split"]["case_types"]["contradiction"], 1)
        self.assertEqual(summary["test_split"]["case_types"]["weak_support"], 1)
        self.assertEqual(summary["test_split"]["case_types"]["full_text_required"], 1)
        self.assertEqual(summary["test_split"]["gold_labels"]["weakly_supported"], 1)
        self.assertEqual(summary["test_split"]["required_case_types"], [
            "contradiction",
            "full_text_required",
            "hard_negative",
            "weak_support",
        ])
        self.assertEqual(summary["set_cases"]["case_types"]["set_aggregation"], 2)
        self.assertEqual(summary["set_cases"]["case_types"]["weak_set_boundary"], 1)
        self.assertEqual(summary["set_cases"]["case_types"]["contradiction_set"], 1)
        self.assertEqual(set(summary["set_cases"]["gold_labels"]), {
            "contradicted",
            "insufficient_evidence",
            "supported",
            "weakly_supported",
        })
        self.assertEqual(summary["set_cases"]["test_split"]["case_types"]["contradiction_set"], 1)
        self.assertEqual(summary["set_cases"]["test_split"]["case_types"]["weak_set_boundary"], 1)
        self.assertEqual(summary["set_cases"]["required_case_types"], [
            "contradiction_set",
            "set_aggregation",
            "weak_set_boundary",
        ])
        self.assertEqual(summary["set_cases"]["required_test_case_types"], [
            "contradiction_set",
            "weak_set_boundary",
        ])
        self.assertIn("maintainer_synthetic", summary["label_sources"])
        self.assertEqual(summary["label_source_counts"], {"maintainer_synthetic": 11})

    def test_validate_support_eval_dataset_reports_test_split_high_risk_coverage(self):
        with open(os.path.join("data", "eval", "support_eval.json"), encoding="utf-8") as handle:
            summary = validate_support_eval_dataset(json.load(handle))

        self.assertEqual(summary["test_split"]["case_types"]["hard_negative"], 6)
        self.assertEqual(summary["test_split"]["case_types"]["contradiction"], 6)
        self.assertEqual(summary["test_split"]["case_types"]["full_text_required"], 3)
        self.assertEqual(summary["test_split"]["case_types"]["weak_support"], 1)
        self.assertEqual(summary["languages"], {"en": 36, "zh": 12})
        self.assertEqual(summary["test_split"]["languages"], {"en": 13, "zh": 6})
        self.assertEqual(set(summary["test_split"]["gold_labels"]), {
            "contradicted",
            "insufficient_evidence",
            "supported",
            "weakly_supported",
        })

    def test_validate_support_eval_dataset_reports_set_case_coverage(self):
        with open(os.path.join("data", "eval", "support_eval.json"), encoding="utf-8") as handle:
            summary = validate_support_eval_dataset(json.load(handle))

        self.assertGreaterEqual(summary["set_cases"]["n"], 6)
        self.assertEqual(summary["set_cases"]["case_types"]["weak_set_boundary"], 2)
        self.assertEqual(summary["set_cases"]["case_types"]["set_aggregation"], 3)
        self.assertEqual(summary["set_cases"]["case_types"]["contradiction_set"], 1)
        self.assertEqual(set(summary["set_cases"]["gold_labels"]), {
            "contradicted",
            "insufficient_evidence",
            "supported",
            "weakly_supported",
        })
        self.assertEqual(summary["set_cases"]["test_split"]["case_types"]["weak_set_boundary"], 2)
        self.assertEqual(summary["set_cases"]["test_split"]["case_types"]["contradiction_set"], 1)
        self.assertEqual(summary["set_cases"]["required_case_types"], [
            "contradiction_set",
            "set_aggregation",
            "weak_set_boundary",
        ])
        self.assertIn("test", summary["set_cases"]["splits"])

    def test_validate_support_eval_dataset_rejects_unknown_set_case_type(self):
        with open(os.path.join("data", "eval", "support_eval.json"), encoding="utf-8") as handle:
            dataset = json.load(handle)
        dataset["set_cases"][0]["case_type"] = "unsupported_set_policy"

        with self.assertRaises(SupportEvalValidationError) as raised:
            validate_support_eval_dataset(dataset)

        self.assertIn("unsupported case_type 'unsupported_set_policy'", str(raised.exception))

    def test_validate_support_eval_dataset_rejects_missing_set_case_coverage(self):
        with open(os.path.join("data", "eval", "support_eval.json"), encoding="utf-8") as handle:
            dataset = json.load(handle)
        dataset["set_cases"] = [
            case for case in dataset["set_cases"] if case.get("case_type") != "weak_set_boundary"
        ]

        with self.assertRaises(SupportEvalValidationError) as raised:
            validate_support_eval_dataset(dataset)

        message = str(raised.exception)
        self.assertIn("set_cases are missing required case_type coverage: weak_set_boundary", message)
        self.assertIn("set_cases test split is missing required case_type coverage: weak_set_boundary", message)
        self.assertIn("set_cases are missing required gold label coverage: weakly_supported", message)

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

    def test_validate_support_eval_dataset_rejects_missing_test_split_high_risk_coverage(self):
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
                    "split": "test",
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
                    "split": "dev",
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
                    "split": "train",
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

        with self.assertRaises(SupportEvalValidationError) as raised:
            validate_support_eval_dataset(dataset)

        message = str(raised.exception)
        self.assertIn("test split is missing required high-risk case_type coverage", message)
        self.assertIn("hard_negative", message)
        self.assertIn("test split is missing required gold label coverage", message)
        self.assertIn("weakly_supported", message)

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
                lang="en",
                evidence_scope="abstract",
                case_type="direct_support",
            ),
            SupportCase(
                "b",
                "claim",
                "evidence",
                "insufficient_evidence",
                lang="zh",
                evidence_scope="abstract",
                case_type="hard_negative",
            ),
            SupportCase(
                "c",
                "claim",
                "evidence",
                "contradicted",
                lang="en",
                evidence_scope="title",
                case_type="contradiction",
            ),
        ]
        report = compute_support_report(cases, ["supported", "supported", "contradicted"], backend_name="fake_nli")

        self.assertEqual(report["dataset"]["n"], 3)
        self.assertEqual(report["dataset"]["case_types"]["hard_negative"], 1)
        self.assertEqual(report["dataset"]["evidence_scopes"]["abstract"], 2)
        self.assertEqual(report["dataset"]["languages"], {"en": 2, "zh": 1})
        self.assertEqual(report["dataset"]["splits"]["test"], 3)
        self.assertEqual(report["overall"]["n"], 3)
        self.assertEqual(report["overall"]["false_support_rate"], 0.5)
        self.assertEqual(report["overall"]["support_overcall_count"], 1)
        self.assertEqual(report["overall"]["support_overcall_rate"], 0.5)
        self.assertEqual(report["overall"]["per_label"]["supported"]["precision"], 0.5)
        self.assertEqual(report["overall"]["per_label"]["contradicted"]["recall"], 1.0)
        self.assertEqual(report["confusion_matrix"]["insufficient_evidence"]["supported"], 1)
        self.assertEqual(report["error_bucket_counts"]["false_support"], 1)
        self.assertEqual(report["error_bucket_counts"]["missed_contradiction"], 0)
        self.assertEqual(report["review_queue"][0]["case_id"], "b")
        self.assertEqual(report["review_queue"][0]["severity"], "critical")
        self.assertEqual(report["review_queue"][0]["recommended_action"], "rewrite_or_replace_evidence")
        self.assertEqual(report["review_queue_summary"]["count"], 1)
        self.assertEqual(report["review_queue_summary"]["by_severity"], {"critical": 1})
        self.assertEqual(report["review_queue_summary"]["by_recommended_action"], {"rewrite_or_replace_evidence": 1})
        self.assertTrue(report["release_blocker_summary"]["release_blocked"])
        self.assertFalse(report["release_blocker_summary"]["benchmark_claim_safe"])
        self.assertEqual(report["release_blocker_summary"]["blocking_case_ids"], ["b"])
        self.assertEqual(
            report["release_blocker_summary"]["next_action"],
            "block_release_until_false_support_reviewed",
        )
        self.assertEqual(report["release_summary"]["schema_version"], 1)
        self.assertEqual(report["release_summary"]["status"], "blocked")
        self.assertEqual(report["release_summary"]["next_action"], "block_release_until_false_support_reviewed")
        self.assertEqual(report["release_summary"]["metrics"]["case_count"], 3)
        self.assertEqual(report["release_summary"]["metrics"]["supported_precision"], 0.5)
        self.assertEqual(report["release_summary"]["metrics"]["false_support_rate"], 0.5)
        self.assertEqual(report["release_summary"]["risk_counts"]["false_support"], 1)
        self.assertEqual(report["release_summary"]["review_queue"]["blocking_case_ids"], ["b"])
        self.assertEqual(report["release_summary"]["acceptance"]["block_acceptance_case_ids"], ["b"])
        self.assertEqual(report["release_summary"]["acceptance"]["top_risk_slice_id"], "hard_negative_overcalled")
        self.assertEqual(report["release_summary"]["label_maturity"]["human_reviewed"], 0)
        self.assertEqual(report["false_support_analysis"]["false_support_count"], 1)
        self.assertEqual(report["false_support_analysis"]["weak_false_support_count"], 0)
        self.assertEqual(report["false_support_analysis"]["false_support_case_ids"], ["b"])
        self.assertEqual(report["false_support_analysis"]["weak_false_support_case_ids"], [])
        self.assertEqual(report["false_support_analysis"]["high_risk_overcall_case_ids"], ["b"])
        self.assertFalse(report["acceptance_guard"]["ok_to_accept_supported"])
        self.assertEqual(report["acceptance_guard"]["block_acceptance_case_ids"], ["b"])
        self.assertEqual(report["acceptance_guard"]["review_before_accepting_case_ids"], [])
        self.assertEqual(report["false_support_analysis"]["by_case_type"]["hard_negative"]["case_ids"], ["b"])
        self.assertEqual(report["false_support_analysis"]["by_language"]["zh"]["case_ids"], ["b"])
        self.assertEqual(report["false_support_analysis"]["top_risk_slice"]["id"], "hard_negative_overcalled")
        self.assertEqual(report["false_support_analysis"]["top_risk_slice"]["case_ids"], ["b"])
        acceptance_slices = {item["id"]: item for item in report["acceptance_slices"]}
        self.assertEqual(acceptance_slices["hard_negative"]["status"], "blocked")
        self.assertEqual(acceptance_slices["hard_negative"]["false_support_case_ids"], ["b"])
        self.assertEqual(acceptance_slices["contradiction"]["status"], "clear")
        self.assertEqual(acceptance_slices["full_text_boundary"]["status"], "clear")
        self.assertEqual(acceptance_slices["non_english"]["status"], "blocked")
        self.assertEqual(report["abstention_analysis"]["total_abstention_count"], 0)
        self.assertEqual(report["abstention_analysis"]["incorrect_case_ids"], [])
        self.assertEqual(report["by_case_type"]["direct_support"]["accuracy"], 1.0)
        self.assertEqual(report["by_case_type"]["direct_support"]["per_label"]["supported"]["f1"], 1.0)
        self.assertEqual(report["by_case_type"]["hard_negative"]["false_support_rate"], 1.0)
        self.assertEqual(report["by_evidence_scope"]["abstract"]["n"], 2)
        self.assertEqual(report["by_evidence_scope"]["title"]["contradiction_recall"], 1.0)
        self.assertEqual(report["by_language"]["zh"]["false_support_rate"], 1.0)
        self.assertEqual(report["by_split"]["test"]["n"], 3)
        self.assertEqual(report["diagnostics"]["backend"], "fake_nli")
        self.assertEqual(report["diagnostics"]["false_support_case_ids"], ["b"])
        self.assertEqual(report["cases"][1]["case_id"], "b")
        self.assertEqual(report["cases"][1]["lang"], "zh")
        self.assertEqual(report["cases"][1]["split"], "test")
        self.assertFalse(report["cases"][1]["correct"])

    def test_acceptance_slices_keep_clear_high_risk_groups_visible(self):
        cases = [
            SupportCase(
                "a",
                "claim",
                "evidence",
                "contradicted",
                case_type="contradiction",
                evidence_scope="metadata_snippet",
                split="test",
            ),
            SupportCase(
                "b",
                "claim",
                "evidence",
                "insufficient_evidence",
                case_type="full_text_required",
                evidence_scope="abstract",
                split="dev",
            ),
            SupportCase(
                "c",
                "claim",
                "evidence",
                "supported",
                case_type="direct_support",
                evidence_scope="abstract",
                lang="zh",
                split="test",
            ),
        ]

        slices = {item["id"]: item for item in compute_support_acceptance_slices(cases, ["weakly_supported", "supported", "supported"])}

        self.assertEqual(slices["contradiction"]["status"], "review_required")
        self.assertEqual(slices["contradiction"]["weak_false_support_case_ids"], ["a"])
        self.assertEqual(slices["hard_negative"]["status"], "clear")
        self.assertEqual(slices["hard_negative"]["case_count"], 0)
        self.assertEqual(slices["full_text_boundary"]["status"], "blocked")
        self.assertEqual(slices["full_text_boundary"]["false_support_case_ids"], ["b"])
        self.assertEqual(slices["test_split"]["case_count"], 2)
        self.assertEqual(slices["non_english"]["status"], "clear")
        self.assertEqual(slices["non_english"]["case_ids"], ["c"])

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
        self.assertEqual(predict_support_set_policy(by_id["ss05"]), "weakly_supported")
        self.assertEqual(predict_support_set_policy(by_id["ss06"]), "insufficient_evidence")
        self.assertEqual(report["overall"]["accuracy"], 1.0)
        self.assertEqual(report["dataset"]["case_types"]["weak_set_boundary"], 2)
        self.assertEqual(report["dataset"]["case_types"]["set_aggregation"], 3)
        self.assertEqual(report["dataset"]["languages"], {"en": 5, "zh": 1})
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

    def test_release_summary_separates_model_quality_from_label_maturity(self):
        cases = [
            SupportCase("a", "claim", "evidence", "supported", case_type="direct_support"),
            SupportCase("b", "claim", "evidence", "contradicted", case_type="contradiction"),
            SupportCase("c", "claim", "evidence", "insufficient_evidence", case_type="hard_negative"),
        ]
        report = run_support_eval_fixture_report(cases)
        report["label_sidecar_gate"] = {"ok": True, "metrics": {"high_risk_unreviewed": 3}}

        immature = compute_support_release_summary(report, compute_support_quality_gate(report))

        self.assertEqual(immature["status"], "evaluation_passed_but_labels_immature")
        self.assertTrue(immature["model_acceptance_ok"])
        self.assertFalse(immature["labels_mature_for_benchmark_claims"])
        self.assertFalse(immature["benchmark_claim_safe"])
        self.assertFalse(immature["ok_to_accept_supported"])
        self.assertEqual(immature["next_action"], "complete_human_label_review")

        report["label_sidecar"] = {
            "human_reviewed": 3,
            "label_maturity": {"dual_annotated_count": 2, "published_benchmark_count": 3},
        }
        report["label_sidecar_gate"] = {
            "ok": True,
            "metrics": {"dual_annotated": 2, "high_risk_reviewed": 3, "high_risk_unreviewed": 0},
        }
        mature = compute_support_release_summary(report, compute_support_quality_gate(report))

        self.assertTrue(mature["labels_mature_for_benchmark_claims"])
        self.assertTrue(mature["ok_to_accept_supported"])

    def test_quality_gate_fails_on_false_support(self):
        cases = [
            SupportCase("a", "claim", "evidence", "supported", case_type="direct_support"),
            SupportCase("b", "claim", "evidence", "insufficient_evidence", case_type="hard_negative"),
            SupportCase("c", "claim", "evidence", "contradicted", case_type="contradiction"),
        ]

        report = compute_support_report(cases, ["supported", "supported", "contradicted"])
        gate = compute_support_quality_gate(report)
        summary = compute_support_release_summary(report, gate)

        self.assertFalse(gate["ok"])
        self.assertEqual(summary["quality_gate_ok"], False)
        self.assertEqual(summary["status"], "blocked")
        self.assertEqual(summary["risk_counts"]["false_support"], 1)
        self.assertEqual(summary["review_queue"]["critical_case_ids"], ["b"])
        self.assertIn("false_support_count", {failure["code"] for failure in gate["failures"]})
        self.assertIn("supported_precision", {failure["code"] for failure in gate["failures"]})
        self.assertEqual(gate["failures"][0]["case_ids"], ["b"])
        self.assertEqual(gate["review_queue_case_ids"], ["b"])
        self.assertEqual(gate["critical_review_case_ids"], ["b"])
        self.assertEqual(gate["metrics"]["review_queue_count"], 1)
        self.assertEqual(gate["metrics"]["critical_review_count"], 1)
        self.assertEqual(gate["review_queue_summary"]["by_bucket"], {"false_support": 1})
        self.assertTrue(gate["release_blocker_summary"]["release_blocked"])
        self.assertEqual(
            gate["release_blocker_summary"]["next_action"],
            "block_release_until_false_support_reviewed",
        )

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
        self.assertEqual(gate["review_queue_case_ids"], ["b"])
        self.assertEqual(gate["critical_review_case_ids"], [])
        self.assertEqual(
            gate["release_blocker_summary"]["next_action"],
            "block_release_until_high_risk_reviewed",
        )

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
        self.assertEqual(payload["release_summary"]["quality_gate_ok"], False)
        self.assertEqual(payload["release_summary"]["status"], "blocked")
        self.assertEqual(payload["release_summary"]["next_action"], "inspect_support_quality_gate_failures")
        self.assertEqual(payload["quality_gate"]["failures"][0]["code"], "supported_precision")
        self.assertIn("review_queue_case_ids", payload["quality_gate"])
        self.assertIn("support_set_policy", payload)
        self.assertEqual(payload["support_set_policy"]["overall"]["accuracy"], 1.0)

    def test_eval_support_cli_can_print_review_queue_only(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/eval_support.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--split",
                "test",
                "--backend",
                "heuristic",
                "--quality-gate",
                "--label-sidecar",
                os.path.join("data", "eval", "support_eval_label_sidecar.json"),
                "--review-queue-only",
            ],
            check=False,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["backend"], "heuristic")
        self.assertEqual(payload["split"], "test")
        self.assertIn("macro_f1", payload["overall"])
        self.assertIn("macro_precision", payload["overall"])
        self.assertIn("macro_recall", payload["overall"])
        self.assertIn("weighted_f1", payload["overall"])
        self.assertIn("weighted_precision", payload["overall"])
        self.assertIn("weighted_recall", payload["overall"])
        self.assertIn("review_queue", payload)
        self.assertNotIn("cases", payload)
        self.assertEqual(payload["quality_gate"]["ok"], False)
        self.assertIn("false_support_analysis", payload)
        self.assertIn("acceptance_guard", payload)
        self.assertTrue(payload["acceptance_guard"]["ok_to_accept_supported"])
        self.assertEqual(payload["acceptance_guard"]["block_acceptance_case_ids"], [])
        self.assertEqual(payload["acceptance_guard"]["review_before_accepting_case_ids"], ["s39", "s48"])
        self.assertEqual(payload["acceptance_guard"]["next_action"], "review_before_accepting_weak_support")
        self.assertEqual(
            payload["acceptance_guard"]["policy"],
            "supported_overcalls_block_acceptance; weak_overcalls_require_review",
        )
        acceptance_slices = {item["id"]: item for item in payload["acceptance_slices"]}
        self.assertEqual(
            sorted(acceptance_slices),
            ["contradiction", "full_text_boundary", "hard_negative", "non_english", "test_split"],
        )
        self.assertEqual(acceptance_slices["contradiction"]["status"], "review_required")
        self.assertEqual(acceptance_slices["contradiction"]["weak_false_support_case_ids"], ["s39", "s48"])
        self.assertEqual(
            payload["quality_gate"]["acceptance_slices"],
            payload["acceptance_slices"],
        )
        self.assertEqual(payload["false_support_analysis"]["total_overcall_count"], 2)
        self.assertEqual(payload["false_support_analysis"]["false_support_case_ids"], [])
        self.assertEqual(payload["false_support_analysis"]["weak_false_support_case_ids"], ["s39", "s48"])
        self.assertEqual(payload["false_support_analysis"]["high_risk_overcall_case_ids"], ["s39", "s48"])
        self.assertEqual(
            payload["false_support_analysis"]["acceptance_guard"]["review_before_accepting_case_ids"],
            ["s39", "s48"],
        )
        self.assertEqual(
            payload["false_support_analysis"]["top_risk_slice"]["id"],
            "contradicted_overcalled",
        )
        self.assertEqual(payload["false_support_analysis"]["top_risk_slice"]["case_ids"], ["s39", "s48"])
        self.assertEqual(
            payload["false_support_analysis"]["risk_slices"][0]["recommended_action"],
            "inspect_contradiction_before_accepting_support",
        )
        self.assertIn("abstention_analysis", payload)
        self.assertGreater(payload["abstention_analysis"]["incorrect_abstention_count"], 0)
        self.assertIn("review_case_ids", payload["abstention_analysis"])
        self.assertIn("by_evidence_scope", payload["abstention_analysis"])
        self.assertTrue(payload["label_sidecar_gate"]["ok"])
        self.assertEqual(payload["label_maturity"]["coverage"], 1.0)
        self.assertEqual(payload["label_maturity"]["human_reviewed"], 0)
        self.assertEqual(payload["label_maturity"]["dual_annotated"], 0)
        self.assertEqual(payload["label_maturity"]["high_risk_unreviewed"], 35)
        self.assertEqual(payload["label_maturity"]["full_text_required_unreviewed"], 7)
        self.assertEqual(payload["label_maturity"]["policy_boundary_unreviewed"], 2)
        self.assertEqual(payload["label_maturity"]["dataset_cases"], 54)
        self.assertEqual(payload["label_maturity"]["sidecar_cases"], 54)
        self.assertEqual(payload["label_maturity"]["sidecar_provenance_complete_count"], 54)
        self.assertEqual(payload["label_maturity"]["sidecar_provenance_complete_fraction"], 1.0)
        self.assertEqual(payload["label_maturity"]["sidecar_provenance_missing_count"], 0)
        self.assertEqual(payload["label_maturity"]["sidecar_provenance_missing_case_ids"], [])
        self.assertEqual(payload["label_maturity"]["sidecar_provenance_missing_case_ids_by_field"], {})
        self.assertEqual(
            payload["label_maturity"]["sidecar_provenance_field_present_counts"]["case_type"],
            54,
        )
        self.assertIsNone(payload["label_maturity"]["raw_dual_agreement_rate"])
        self.assertEqual(payload["label_maturity"]["supported_disagreement_case_ids"], [])
        self.assertEqual(
            payload["label_sidecar_gate"]["metrics"],
            payload["label_maturity"],
        )
        self.assertEqual(payload["quality_gate"]["review_queue_case_ids"][:5], ["s10", "s16", "s27", "s36", "s39"])
        self.assertTrue(payload["release_blocker_summary"]["release_blocked"])
        self.assertFalse(payload["release_blocker_summary"]["benchmark_claim_safe"])
        self.assertEqual(
            payload["release_blocker_summary"]["next_action"],
            "block_release_until_high_risk_reviewed",
        )
        self.assertEqual(
            payload["quality_gate"]["release_blocker_summary"]["next_action"],
            payload["release_blocker_summary"]["next_action"],
        )
        self.assertEqual(payload["review_queue_summary"]["by_severity"]["high"], 6)
        self.assertEqual(
            payload["quality_gate"]["review_queue_summary"]["by_recommended_action"][
                "run_nli_or_human_contradiction_review"
            ],
            6,
        )
        self.assertEqual(payload["review_queue"][0]["recommended_action"], "run_nli_or_human_contradiction_review")

    def test_eval_support_cli_can_limit_review_queue_only_rows(self):
        completed = subprocess.run(
            [
                sys.executable,
                "scripts/eval_support.py",
                "--dataset",
                os.path.join("data", "eval", "support_eval.json"),
                "--split",
                "test",
                "--backend",
                "heuristic",
                "--quality-gate",
                "--review-queue-only",
                "--review-queue-limit",
                "2",
            ],
            check=False,
            cwd=os.getcwd(),
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["review_queue_limit"], 2)
        self.assertEqual(len(payload["review_queue"]), 2)
        self.assertEqual(payload["review_queue_filtered"]["limit"], 2)
        self.assertEqual(payload["review_queue_filtered"]["returned"], 2)
        self.assertEqual(payload["review_queue_filtered"]["original_count"], payload["review_queue_summary"]["count"])
        self.assertEqual(
            payload["review_queue_filtered"]["returned_case_ids"],
            payload["review_queue_summary"]["top_case_ids"][:2],
        )
        self.assertGreater(payload["review_queue_filtered"]["omitted"], 0)
        self.assertIn("review_queue_summary_and_quality_gate_counts_remain_full_queue", payload["review_queue_filtered"]["policy"])
        self.assertGreater(len(payload["quality_gate"]["review_queue_case_ids"]), len(payload["review_queue"]))

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
                "--min-high-risk-reviewed",
                "1",
                "--min-high-risk-reviewed-by-language",
                "zh=1",
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
                "sidecar_high_risk_reviewed",
                "sidecar_high_risk_reviewed_by_language",
                "sidecar_dual_annotated",
                "sidecar_raw_dual_agreement_rate",
            },
        )
        by_language_failure = next(
            failure
            for failure in payload["label_sidecar_gate"]["failures"]
            if failure["code"] == "sidecar_high_risk_reviewed_by_language"
        )
        self.assertEqual(by_language_failure["language"], "zh")
        self.assertEqual(by_language_failure["actual"], 0)
        self.assertEqual(by_language_failure["threshold"], 1)
        self.assertIn("s34", by_language_failure["unreviewed_case_ids"])

    def test_eval_support_cli_sidecar_gate_can_block_supported_disagreements(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            sidecar_path = os.path.join(tmpdir, "sidecar.json")
            with open(os.path.join("data", "eval", "support_eval_label_sidecar.json"), encoding="utf-8") as handle:
                sidecar = json.load(handle)
            for item in sidecar["cases"]:
                if item["case_id"] == "s04":
                    item.update(
                        {
                            "adjudication_status": "dual_annotator_adjudicated",
                            "annotator_count": 2,
                            "annotator_labels": ["supported", "contradicted"],
                            "adjudicated_label": "contradicted",
                            "disagreement": "resolved",
                            "adjudicator": "reviewer-c",
                            "notes": "Unit test resolved supported-label disagreement.",
                        }
                    )
                    break
            with open(sidecar_path, "w", encoding="utf-8") as handle:
                json.dump(sidecar, handle)

            completed = subprocess.run(
                [
                    sys.executable,
                    "scripts/eval_support.py",
                    "--validate-only",
                    "--label-sidecar",
                    sidecar_path,
                    "--max-supported-disagreements",
                    "0",
                ],
                check=False,
                cwd=os.getcwd(),
                capture_output=True,
                text=True,
            )

        self.assertEqual(completed.returncode, 1)
        payload = json.loads(completed.stdout)
        self.assertFalse(payload["label_sidecar_gate"]["ok"])
        failure = payload["label_sidecar_gate"]["failures"][0]
        self.assertEqual(failure["code"], "sidecar_supported_disagreements")
        self.assertEqual(failure["case_ids"], ["s04"])

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
        metrics = compute_support_metrics([(case.gold, pred) for case, pred in zip(cases, predictions)])
        self.assertEqual(metrics["support_overcall_count"], 2)
        self.assertEqual(metrics["support_overcall_rate"], 0.6667)

    def test_false_support_analysis_groups_overcalls_for_triage(self):
        cases = [
            SupportCase("a", "claim", "evidence", "insufficient_evidence", case_type="hard_negative", evidence_scope="abstract", split="test"),
            SupportCase("b", "claim", "evidence", "contradicted", case_type="contradiction", evidence_scope="metadata_snippet", split="test"),
            SupportCase("c", "claim", "evidence", "insufficient_evidence", case_type="full_text_required", evidence_scope="abstract", split="dev"),
        ]
        buckets = compute_support_error_buckets(cases, ["supported", "weakly_supported", "supported"])

        analysis = compute_false_support_analysis(buckets)
        guard = compute_false_support_acceptance_guard(buckets)

        self.assertEqual(analysis["false_support_count"], 2)
        self.assertEqual(analysis["weak_false_support_count"], 1)
        self.assertEqual(analysis["total_overcall_count"], 3)
        self.assertEqual(analysis["high_risk_case_ids"], ["a", "c"])
        self.assertEqual(analysis["false_support_case_ids"], ["a", "c"])
        self.assertEqual(analysis["weak_false_support_case_ids"], ["b"])
        self.assertEqual(analysis["high_risk_overcall_case_ids"], ["a", "c", "b"])
        self.assertFalse(analysis["acceptance_guard"]["ok_to_accept_supported"])
        self.assertEqual(analysis["acceptance_guard"]["block_acceptance_case_ids"], ["a", "c"])
        self.assertEqual(analysis["acceptance_guard"]["review_before_accepting_case_ids"], ["b"])
        self.assertEqual(analysis["acceptance_guard"], guard)
        self.assertEqual(guard["next_action"], "block_release_until_reviewed")
        self.assertEqual(analysis["review_plan"]["schema_version"], 1)
        self.assertEqual(analysis["review_plan"]["status"], "blocked")
        self.assertEqual(analysis["review_plan"]["next_action"], "review_supported_overcalls_before_release")
        self.assertEqual(analysis["review_plan"]["block_acceptance_case_ids"], ["a", "c"])
        self.assertEqual(analysis["review_plan"]["review_before_accepting_case_ids"], ["b"])
        self.assertEqual(analysis["review_plan"]["top_risk_slice_id"], "contradicted_overcalled")
        review_phases = {phase["id"]: phase for phase in analysis["review_plan"]["phases"]}
        self.assertEqual(review_phases["supported_overcall_blockers"]["status"], "blocked")
        self.assertEqual(review_phases["supported_overcall_blockers"]["case_ids"], ["a", "c"])
        self.assertEqual(review_phases["weak_support_overcall_review"]["status"], "review_required")
        self.assertEqual(review_phases["weak_support_overcall_review"]["case_ids"], ["b"])
        self.assertEqual(review_phases["highest_risk_slice_review"]["risk_slice_id"], "contradicted_overcalled")
        self.assertEqual(review_phases["highest_risk_slice_review"]["case_ids"], ["b"])
        blocker_packet = review_phases["supported_overcall_blockers"]["annotation_packet"]
        self.assertEqual(blocker_packet["schema_version"], 1)
        self.assertEqual(blocker_packet["packet_id"], "support-label-packet-supported-overcall-blockers")
        self.assertEqual(blocker_packet["review_phase"], "supported_overcall_blockers")
        self.assertEqual(blocker_packet["case_ids"], ["a", "c"])
        self.assertEqual(blocker_packet["count"], 2)
        self.assertIn("--annotation-packet", blocker_packet["command_template"])
        self.assertIn("--instructions-output", blocker_packet["command_template"])
        self.assertEqual(blocker_packet["command_template"].count("--case-id"), 2)
        self.assertIn("experiments/support-label-packet-supported-overcall-blockers.json", blocker_packet["output"])
        self.assertIn("create_blinded_annotation_packet", blocker_packet["policy"])
        self.assertEqual(review_phases["supported_overcall_blockers"]["packet_id"], blocker_packet["packet_id"])
        self.assertEqual(review_phases["supported_overcall_blockers"]["command_template"], blocker_packet["command_template"])
        self.assertEqual(
            [packet["packet_id"] for packet in analysis["review_plan"]["recommended_annotation_packets"]],
            [
                "support-label-packet-supported-overcall-blockers",
                "support-label-packet-weak-support-overcall-review",
                "support-label-packet-highest-risk-slice-review",
            ],
        )
        self.assertEqual(analysis["review_plan"]["recommended_annotation_packet_count"], 3)
        self.assertEqual(analysis["review_plan"]["recommended_annotation_case_ids"], ["a", "c", "b"])
        self.assertIn("annotation_packets_are_review_assignments", analysis["review_plan"]["policy"])
        self.assertEqual(analysis["by_case_type"]["hard_negative"]["false_support"], 1)
        self.assertEqual(analysis["by_case_type"]["hard_negative"]["false_support_case_ids"], ["a"])
        self.assertEqual(analysis["by_case_type"]["hard_negative"]["weak_false_support_case_ids"], [])
        self.assertEqual(analysis["by_case_type"]["contradiction"]["weak_false_support"], 1)
        self.assertEqual(analysis["by_case_type"]["contradiction"]["weak_false_support_case_ids"], ["b"])
        self.assertEqual(analysis["by_evidence_scope"]["abstract"]["total"], 2)
        self.assertEqual(analysis["by_split"]["test"]["case_ids"], ["a", "b"])
        self.assertEqual(analysis["by_split"]["test"]["false_support_case_ids"], ["a"])
        self.assertEqual(analysis["by_split"]["test"]["weak_false_support_case_ids"], ["b"])
        self.assertEqual(
            [item["id"] for item in analysis["risk_slices"]],
            [
                "contradicted_overcalled",
                "hard_negative_overcalled",
                "full_text_boundary_overcalled",
                "test_split_overcalled",
            ],
        )
        self.assertEqual(analysis["top_risk_slice"]["id"], "contradicted_overcalled")
        self.assertEqual(analysis["top_risk_slice"]["case_ids"], ["b"])
        self.assertEqual(analysis["top_risk_slice"]["weak_false_support_case_ids"], ["b"])
        self.assertEqual(analysis["risk_slices"][1]["recommended_action"], "rewrite_or_replace_evidence")
        self.assertEqual(analysis["risk_slices"][2]["false_support_case_ids"], ["c"])
        self.assertEqual(analysis["risk_slices"][3]["case_ids"], ["a", "b"])
        self.assertIn("highest-risk", analysis["interpretation"])

    def test_abstention_analysis_separates_correct_and_incorrect_refusals(self):
        cases = [
            SupportCase(
                "a",
                "claim",
                "evidence",
                "supported",
                case_type="direct_support",
                evidence_scope="abstract",
                split="test",
            ),
            SupportCase(
                "b",
                "claim",
                "evidence",
                "insufficient_evidence",
                case_type="hard_negative",
                evidence_scope="abstract",
                split="test",
            ),
            SupportCase(
                "c",
                "claim",
                "evidence",
                "contradicted",
                case_type="contradiction",
                evidence_scope="metadata_snippet",
                split="dev",
            ),
        ]
        buckets = compute_support_error_buckets(
            cases,
            ["insufficient_evidence", "insufficient_evidence", "insufficient_evidence"],
        )

        analysis = compute_abstention_analysis(buckets)

        self.assertEqual(analysis["incorrect_abstention_count"], 2)
        self.assertEqual(analysis["correct_abstention_count"], 1)
        self.assertEqual(analysis["total_abstention_count"], 3)
        self.assertEqual(analysis["incorrect_case_ids"], ["a", "c"])
        self.assertEqual(analysis["correct_case_ids"], ["b"])
        self.assertEqual(analysis["review_case_ids"], ["a", "c"])
        self.assertEqual(analysis["by_case_type"]["direct_support"]["incorrect_case_ids"], ["a"])
        self.assertEqual(analysis["by_case_type"]["hard_negative"]["correct_case_ids"], ["b"])
        self.assertEqual(analysis["by_evidence_scope"]["abstract"]["total"], 2)
        self.assertEqual(analysis["by_split"]["dev"]["incorrect_abstention"], 1)

    def test_support_review_queue_prioritizes_high_risk_support_failures(self):
        cases = [
            SupportCase("a", "claim", "evidence", "contradicted", case_type="contradiction", evidence_scope="abstract", split="test"),
            SupportCase("b", "claim", "evidence", "insufficient_evidence", case_type="hard_negative", evidence_scope="abstract", split="test"),
            SupportCase("c", "claim", "evidence", "contradicted", case_type="contradiction", evidence_scope="abstract", split="dev"),
            SupportCase("d", "claim", "evidence", "supported", case_type="direct_support", evidence_scope="abstract", split="test"),
        ]
        buckets = compute_support_error_buckets(
            cases,
            ["supported", "weakly_supported", "insufficient_evidence", "insufficient_evidence"],
        )

        queue = compute_support_review_queue(buckets)

        self.assertEqual([item["case_id"] for item in queue], ["a", "c", "b", "d"])
        self.assertEqual(queue[0]["severity"], "critical")
        self.assertEqual(queue[0]["risk_score"], 100)
        self.assertEqual(queue[0]["buckets"], ["false_support", "missed_contradiction"])
        self.assertEqual(queue[0]["recommended_action"], "inspect_contradiction_before_accepting_support")
        self.assertEqual(queue[1]["severity"], "high")
        self.assertEqual(queue[1]["recommended_action"], "run_nli_or_human_contradiction_review")
        self.assertEqual(queue[2]["buckets"], ["weak_false_support"])
        self.assertEqual(queue[2]["recommended_action"], "downgrade_or_find_stronger_evidence")
        self.assertEqual(queue[3]["recommended_action"], "inspect_recall_loss")

        summary = compute_support_review_queue_summary(queue)
        self.assertEqual(summary["count"], 4)
        self.assertEqual(summary["by_severity"], {"critical": 1, "high": 2, "medium": 1})
        self.assertEqual(summary["by_bucket"]["missed_contradiction"], 2)
        self.assertEqual(summary["top_case_ids"], ["a", "c", "b", "d"])
        self.assertEqual(summary["critical_case_ids"], ["a"])

        blocker_summary = compute_release_blocker_summary(queue)
        self.assertTrue(blocker_summary["release_blocked"])
        self.assertFalse(blocker_summary["benchmark_claim_safe"])
        self.assertEqual(blocker_summary["blocking_case_ids"], ["a", "c", "b"])
        self.assertEqual(blocker_summary["blocking_buckets"], {
            "false_support": 1,
            "incorrect_abstention": 1,
            "missed_contradiction": 2,
            "weak_false_support": 1,
        })
        self.assertEqual(
            blocker_summary["blocking_recommended_actions"],
            {
                "downgrade_or_find_stronger_evidence": 1,
                "inspect_contradiction_before_accepting_support": 1,
                "run_nli_or_human_contradiction_review": 1,
            },
        )
        self.assertEqual(
            blocker_summary["next_action"],
            "block_release_until_false_support_reviewed",
        )
        self.assertEqual(
            blocker_summary["policy"],
            "critical_or_high_support_eval_rows_block_release_claims",
        )

    def test_release_blocker_summary_distinguishes_medium_review_rows(self):
        queue = [
            {
                "case_id": "recall-loss",
                "severity": "medium",
                "buckets": ["supported_rejected"],
                "recommended_action": "inspect_recall_loss",
            }
        ]

        blocker_summary = compute_release_blocker_summary(queue)

        self.assertFalse(blocker_summary["release_blocked"])
        self.assertFalse(blocker_summary["benchmark_claim_safe"])
        self.assertEqual(blocker_summary["blocking_case_ids"], [])
        self.assertEqual(blocker_summary["review_required_case_ids"], ["recall-loss"])
        self.assertEqual(
            blocker_summary["next_action"],
            "review_medium_risk_before_benchmark_claims",
        )


if __name__ == "__main__":
    unittest.main()
