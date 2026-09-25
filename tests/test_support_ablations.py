"""Tests for reproducible claim-support verifier component ablations."""

from __future__ import annotations

import unittest
from unittest import mock

from citeguard.benchmark.support_ablations import (
    SUPPORT_ABLATION_COMPONENTS,
    SUPPORT_ABLATION_NAMES,
    build_support_ablation_runtime,
    run_support_ablation_matrix,
)
from citeguard.verification.support_eval import SupportCase
from citeguard.verifiers import (
    SentenceTransformerRerankerBackend,
    SupportAssessment,
    TransformersNLIBackend,
)


class SupportAblationTests(unittest.TestCase):
    def setUp(self):
        self.cases = [
            SupportCase(
                "positive",
                "Method M improves task T accuracy.",
                "Method M improves task T accuracy by five points.",
                "supported",
                case_type="direct_support",
            ),
            SupportCase(
                "hard-negative",
                "Method M always improves task T accuracy.",
                "Method M has mixed results on task T accuracy.",
                "insufficient_evidence",
                case_type="hard_negative",
            ),
        ]

    def test_default_matrix_has_the_six_declared_component_combinations(self):
        self.assertEqual(
            SUPPORT_ABLATION_NAMES,
            (
                "heuristic_only",
                "reranker_only",
                "nli_only",
                "heuristic_reranker",
                "reranker_nli",
                "full_ensemble",
            ),
        )
        self.assertEqual(
            SUPPORT_ABLATION_COMPONENTS["full_ensemble"],
            (
                "heuristic_support",
                "sentence_transformer_reranker",
                "transformers_nli",
            ),
        )

    def test_heuristic_ablation_completes_with_false_support_sensitive_metrics(self):
        result = run_support_ablation_matrix(self.cases, ["heuristic_only"])

        self.assertTrue(result["matrix_complete"])
        self.assertEqual(result["completed_ablations"], ["heuristic_only"])
        self.assertEqual(result["comparison"][0]["status"], "completed")
        self.assertIn("false_support_rate", result["comparison"][0])
        self.assertIn("support_overcall_count", result["comparison"][0])
        self.assertIn("contradiction_recall", result["comparison"][0])
        self.assertIn("synthetic_seed_results_do_not_establish", result["policy"])

    def test_missing_models_are_unavailable_and_never_get_zero_score_metrics(self):
        with mock.patch.object(SentenceTransformerRerankerBackend, "is_available", return_value=False), mock.patch.object(
            TransformersNLIBackend,
            "is_available",
            return_value=False,
        ):
            result = run_support_ablation_matrix(self.cases, SUPPORT_ABLATION_NAMES, plan_only=True)

        self.assertEqual(result["planned_ablations"], ["heuristic_only"])
        self.assertEqual(
            result["unavailable_ablations"],
            [
                "reranker_only",
                "nli_only",
                "heuristic_reranker",
                "reranker_nli",
                "full_ensemble",
            ],
        )
        for row in result["comparison"]:
            if row["status"] != "completed":
                self.assertNotIn("accuracy", row)
                self.assertIsNone(row["quality_gate_ok"])

    def test_runtime_model_error_is_not_reported_as_completed_ablation(self):
        failed = SupportAssessment(
            backend_name="transformers_nli",
            score=0.0,
            passed=False,
            rationale="model unavailable",
            details={
                "available": False,
                "error_code": "model_unavailable",
                "error_type": "OSError",
                "message": "weights unavailable",
                "model_name": "test-nli",
            },
        )
        with mock.patch.object(TransformersNLIBackend, "is_available", return_value=True), mock.patch.object(
            TransformersNLIBackend,
            "assess",
            return_value=failed,
        ):
            result = run_support_ablation_matrix(
                self.cases,
                ["nli_only"],
                nli_model_name="test-nli",
            )

        self.assertEqual(result["model_error_ablations"], ["nli_only"])
        self.assertFalse(result["matrix_complete"])
        self.assertEqual(result["comparison"][0]["status"], "model_error")
        self.assertNotIn("accuracy", result["comparison"][0])
        self.assertEqual(result["runs"][0]["model_failure_details"][0]["error_code"], "model_unavailable")

    def test_unknown_ablation_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unknown support ablation"):
            build_support_ablation_runtime("not-a-real-ablation")


if __name__ == "__main__":
    unittest.main()
