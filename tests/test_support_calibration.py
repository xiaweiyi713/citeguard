"""Tests for uncalibrated threshold sweeps on the real-source hard-case slice."""

from __future__ import annotations

import unittest
from pathlib import Path

from citeguard.verification.support_calibration import (
    MIN_CALIBRATION_GROUP_N,
    evaluate_hard_case_thresholds,
)


class SupportCalibrationTests(unittest.TestCase):
    def test_hard_case_threshold_sweep_stays_uncalibrated_and_reports_tradeoff(self):
        report = evaluate_hard_case_thresholds(Path("data/eval/support_hard_cases_v1.json"))
        self.assertEqual(report["calibration_status"], "uncalibrated")
        self.assertGreaterEqual(report["case_count"], 35)
        self.assertTrue(report["thresholds"])
        first = report["thresholds"][0]
        self.assertIn("false_support_rate", first)
        self.assertIn("supported_recall", first)
        self.assertIn("abstention_rate", first)
        self.assertIn("accepted_support_rate", first)
        for group in report["groups"]:
            if group["case_count"] < MIN_CALIBRATION_GROUP_N:
                self.assertEqual(group["calibration_status"], "uncalibrated")
        self.assertTrue(any(group["by"] == "lang" for group in report["groups"]))
        self.assertTrue(any(group["by"] == "error_family" for group in report["groups"]))


if __name__ == "__main__":
    unittest.main()
