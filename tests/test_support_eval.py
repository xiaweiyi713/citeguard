"""Tests for the support evaluation harness (metrics are model-free / synthetic)."""

import os
import unittest

from src.verification.support_eval import compute_support_metrics, load_support_eval


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
        self.assertEqual(m["misjudged_support_rate"], 0.5)

    def test_load_support_eval_reads_seed_file(self):
        cases = load_support_eval(os.path.join("data", "eval", "support_eval.json"))
        self.assertGreaterEqual(len(cases), 6)
        self.assertIn(cases[0].gold, {"supported", "weakly_supported", "insufficient_evidence", "contradicted"})


if __name__ == "__main__":
    unittest.main()
