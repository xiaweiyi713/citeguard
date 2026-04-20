"""Tests for support calibration helpers."""

import unittest

from src.benchmark.support_calibration import (
    ScoredSupportExample,
    SupportCalibrationConfig,
    SupportCalibrationExample,
    evaluate_support_config,
    grid_search_support_configs,
)
from src.verifiers import EnsembleSupportPolicy


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


if __name__ == "__main__":
    unittest.main()
