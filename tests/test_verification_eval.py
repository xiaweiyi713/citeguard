"""Tests for the verification evaluation harness."""

import os
import unittest

from src.verification.eval import compute_metrics, load_eval, run_eval

EVAL_PATH = os.path.join("data", "eval", "verification_eval.json")


class EvalTests(unittest.TestCase):
    def test_compute_metrics_on_known_predictions(self):
        preds = [
            ("verified", "verified"),
            ("metadata_mismatch", "metadata_mismatch"),
            ("not_found", "not_found"),
            ("verified", "not_found"),  # a false accusation
        ]
        metrics = compute_metrics(preds)
        self.assertEqual(metrics["n"], 4)
        self.assertEqual(metrics["accuracy"], 0.75)
        self.assertEqual(metrics["false_accusation_rate"], 0.5)
        self.assertEqual(metrics["fabrication_recall"], 1.0)

    def test_seed_eval_set_meets_baseline_quality(self):
        corpus, cases = load_eval(EVAL_PATH)
        self.assertGreaterEqual(len(cases), 12)
        metrics = run_eval(corpus, cases)
        self.assertEqual(metrics["false_accusation_rate"], 0.0)
        self.assertEqual(metrics["fabrication_recall"], 1.0)
        self.assertGreaterEqual(metrics["accuracy"], 0.9)


if __name__ == "__main__":
    unittest.main()
