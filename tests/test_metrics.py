"""Tests for benchmark metrics."""

import unittest

from src.benchmark import EvaluationRecord, MetricsCalculator


class MetricsTests(unittest.TestCase):
    def test_metrics_are_computed_consistently(self):
        records = [
            EvaluationRecord(
                phantom_citation=False,
                metadata_error=False,
                claim_supported=True,
                unsupported_citation=False,
                abstained=False,
            ),
            EvaluationRecord(
                phantom_citation=False,
                metadata_error=True,
                claim_supported=False,
                unsupported_citation=True,
                abstained=True,
            ),
        ]
        metrics = MetricsCalculator().compute(records)
        self.assertEqual(metrics["PCR"], 0.0)
        self.assertEqual(metrics["MCR"], 0.5)
        self.assertEqual(metrics["CSR"], 0.5)
        self.assertEqual(metrics["UCR"], 0.5)
        self.assertEqual(metrics["AU"], 0.5)
        self.assertGreater(metrics["RIS"], 0.0)
