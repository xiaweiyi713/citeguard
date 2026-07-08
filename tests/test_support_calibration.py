"""Tests for support calibration helpers."""

import unittest

from citeguard.benchmark.support_calibration import (
    ScoredSupportExample,
    SupportCalibrationConfig,
    SupportCalibrationExample,
    evaluate_support_config,
    evaluate_support_config_diagnostics,
    grid_search_support_configs,
    load_support_eval_calibration_examples,
    support_eval_cases_to_calibration_examples,
)
from citeguard.verification.support_eval import SupportCase
from citeguard.verifiers import EnsembleSupportPolicy


class SupportCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.examples = [
            ScoredSupportExample(
                example=SupportCalibrationExample(
                    example_id="pos",
                    claim_text="Work studies phantom references in language models.",
                    evidence_text="The paper studies phantom references in large language models.",
                    supported=True,
                ),
                heuristic_score=0.24,
                heuristic_details={"overlap_terms": ["phantom", "references", "language", "models"]},
                reranker_score=0.81,
                reranker_details={},
                nli_probabilities={"entailment": 0.74, "contradiction": 0.05, "neutral": 0.21},
                nli_details={"model_name": "mock"},
            ),
            ScoredSupportExample(
                example=SupportCalibrationExample(
                    example_id="neg",
                    claim_text="The paper proves tokenizer bugs cause citation hallucinations.",
                    evidence_text="The paper studies citation hallucinations in academic writing.",
                    supported=False,
                ),
                heuristic_score=0.12,
                heuristic_details={"overlap_terms": ["citation", "hallucinations"]},
                reranker_score=0.59,
                reranker_details={},
                nli_probabilities={"entailment": 0.18, "contradiction": 0.12, "neutral": 0.70},
                nli_details={"model_name": "mock"},
            ),
        ]

    def test_evaluate_support_config_counts_confusion_matrix(self):
        config = SupportCalibrationConfig(
            heuristic_threshold=0.18,
            reranker_threshold=0.48,
            nli_threshold=0.55,
            nli_margin=0.05,
            ensemble_policy=EnsembleSupportPolicy(
                weights={
                    "transformers_nli": 0.55,
                    "sentence_transformer_reranker": 0.30,
                    "heuristic_support": 0.15,
                },
                pair_nli_floor=0.30,
                pair_combined_threshold=0.28,
                contradiction_max=0.10,
                fallback_combined_threshold=0.48,
            ),
        )
        metrics = evaluate_support_config(self.examples, config)
        self.assertEqual(metrics.true_positive, 1)
        self.assertEqual(metrics.true_negative, 1)
        self.assertEqual(metrics.false_positive, 0)
        self.assertEqual(metrics.false_negative, 0)
        self.assertEqual(metrics.f1, 1.0)

    def test_grid_search_returns_ranked_results(self):
        ranked = grid_search_support_configs(self.examples, top_k=3, profile="quick")
        self.assertEqual(len(ranked), 3)
        self.assertGreaterEqual(ranked[0]["metrics"]["f1"], ranked[-1]["metrics"]["f1"])
        self.assertIn("diagnostics", ranked[0])
        self.assertIn("false_positive_case_ids", ranked[0]["diagnostics"])
        self.assertIn("bucket_summaries", ranked[0]["diagnostics"])
        self.assertIn("decision_path_counts", ranked[0]["diagnostics"])

    def test_diagnostics_report_false_support_and_false_reject_case_ids(self):
        examples = [
            ScoredSupportExample(
                example=SupportCalibrationExample(
                    example_id="missed-positive",
                    claim_text="The paper studies citation hallucinations.",
                    evidence_text="The paper studies citation hallucinations.",
                    supported=True,
                    note="should be supported but scores are too low",
                ),
                heuristic_score=0.05,
                heuristic_details={"overlap_terms": ["citation", "hallucinations"]},
                reranker_score=0.10,
                reranker_details={},
                nli_probabilities={"entailment": 0.10, "contradiction": 0.02, "neutral": 0.88},
                nli_details={"model_name": "mock"},
            ),
            ScoredSupportExample(
                example=SupportCalibrationExample(
                    example_id="overcalled-negative",
                    claim_text="The paper proves tokenizer bugs cause citation hallucinations.",
                    evidence_text="The paper studies citation hallucinations.",
                    supported=False,
                    note="hard negative with high fixture scores",
                ),
                heuristic_score=0.24,
                heuristic_details={"overlap_terms": ["paper", "citation", "hallucinations"]},
                reranker_score=0.80,
                reranker_details={},
                nli_probabilities={"entailment": 0.72, "contradiction": 0.04, "neutral": 0.24},
                nli_details={"model_name": "mock"},
            ),
        ]
        config = SupportCalibrationConfig(
            heuristic_threshold=0.18,
            reranker_threshold=0.48,
            nli_threshold=0.55,
            nli_margin=0.05,
            ensemble_policy=EnsembleSupportPolicy(
                weights={
                    "transformers_nli": 0.55,
                    "sentence_transformer_reranker": 0.30,
                    "heuristic_support": 0.15,
                },
                pair_nli_floor=0.30,
                pair_combined_threshold=0.28,
                contradiction_max=0.10,
                fallback_combined_threshold=0.48,
            ),
        )

        metrics = evaluate_support_config(examples, config)
        diagnostics = evaluate_support_config_diagnostics(examples, config)

        self.assertEqual(metrics.false_positive, 1)
        self.assertEqual(metrics.false_negative, 1)
        self.assertEqual(diagnostics.false_positive_case_ids, ["overcalled-negative"])
        self.assertEqual(diagnostics.false_negative_case_ids, ["missed-positive"])
        self.assertEqual(diagnostics.false_support_examples[0]["example_id"], "overcalled-negative")
        self.assertEqual(diagnostics.false_support_examples[0]["decision_path"], "nli_pass")
        self.assertEqual(diagnostics.false_support_examples[0]["nli_neutral"], 0.24)
        self.assertEqual(diagnostics.true_positive_case_ids, [])
        self.assertEqual(diagnostics.true_negative_case_ids, [])
        self.assertEqual(diagnostics.bucket_summaries["false_positive"]["count"], 1)
        self.assertEqual(diagnostics.bucket_summaries["false_positive"]["avg_nli_entailment"], 0.72)
        self.assertEqual(diagnostics.bucket_summaries["false_positive"]["avg_nli_neutral"], 0.24)
        self.assertEqual(diagnostics.bucket_summaries["false_negative"]["avg_nli_neutral"], 0.88)
        self.assertEqual(diagnostics.decision_path_counts["false_positive"], {"nli_pass": 1})
        self.assertEqual(diagnostics.decision_path_counts["false_negative"], {"paired_reranker_nli_reject": 1})

    def test_support_eval_cases_convert_to_strong_support_binary_examples(self):
        cases = [
            SupportCase("s1", "Claim A", "Evidence A", "supported", split="dev", case_type="direct_support"),
            SupportCase("s2", "Claim B", "Evidence B", "weakly_supported", split="dev", case_type="weak_support"),
            SupportCase("s3", "Claim C", "Evidence C", "contradicted", split="dev", case_type="contradiction"),
        ]

        examples = support_eval_cases_to_calibration_examples(cases)

        self.assertEqual([example.example_id for example in examples], ["s1", "s2", "s3"])
        self.assertEqual([example.supported for example in examples], [True, False, False])
        self.assertIn("gold=weakly_supported", examples[1].note)
        self.assertIn("case_type=weak_support", examples[1].note)

    def test_load_support_eval_calibration_examples_uses_requested_split(self):
        examples = load_support_eval_calibration_examples("data/eval/support_eval.json", split="dev")

        self.assertTrue(examples)
        self.assertTrue(all("split=dev" in example.note for example in examples))
        self.assertTrue(any(example.supported for example in examples))
        self.assertTrue(any(not example.supported for example in examples))
        self.assertFalse(any("split=test" in example.note for example in examples))


if __name__ == "__main__":
    unittest.main()
