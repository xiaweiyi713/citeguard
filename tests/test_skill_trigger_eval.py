"""Tests for the executable skill-trigger evaluation contract."""

import json
from pathlib import Path
import tempfile
import unittest

from scripts.eval_skill_trigger import (
    TriggerEvalError,
    evaluate_gate,
    load_cases,
    load_predictions,
    prediction_template,
    score_predictions,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "eval" / "skill_trigger_eval.json"


class SkillTriggerEvalTests(unittest.TestCase):
    def test_repository_dataset_is_balanced_and_valid(self):
        cases = load_cases(str(DATASET))

        self.assertGreaterEqual(len(cases), 8)
        self.assertTrue(any(case["should_trigger"] for case in cases))
        self.assertTrue(any(not case["should_trigger"] for case in cases))
        self.assertEqual(len(cases), len({case["id"] for case in cases}))

    def test_perfect_predictions_pass_strict_gate(self):
        cases = load_cases(str(DATASET))
        predictions = [{"id": case["id"], "triggered": case["should_trigger"]} for case in cases]

        report = score_predictions(cases, predictions)
        gate = evaluate_gate(report, min_accuracy=1.0, min_positive_recall=1.0, min_negative_recall=1.0)

        self.assertTrue(gate["ok"])
        self.assertEqual(report["metrics"]["accuracy"], 1.0)
        self.assertEqual(report["false_positive_case_ids"], [])
        self.assertEqual(report["false_negative_case_ids"], [])

    def test_false_trigger_fails_negative_recall_gate(self):
        cases = load_cases(str(DATASET))
        predictions = [{"id": case["id"], "triggered": case["should_trigger"]} for case in cases]
        negative = next(row for row in predictions if not row["triggered"])
        negative["triggered"] = True

        report = score_predictions(cases, predictions)
        gate = evaluate_gate(report, min_accuracy=0.0, min_positive_recall=0.0, min_negative_recall=1.0)

        self.assertFalse(gate["ok"])
        self.assertEqual(report["false_positive_case_ids"], [negative["id"]])

    def test_incomplete_predictions_are_rejected_by_default(self):
        cases = load_cases(str(DATASET))
        with self.assertRaisesRegex(TriggerEvalError, "missing case ids"):
            score_predictions(cases, [{"id": cases[0]["id"], "triggered": True}])

    def test_prediction_template_does_not_leak_expected_decisions(self):
        template = prediction_template(load_cases(str(DATASET)))
        serialized = json.dumps(template)

        self.assertNotIn("should_trigger", serialized)
        self.assertTrue(all(row["triggered"] is None for row in template["predictions"]))

    def test_jsonl_prediction_loader_accepts_boolean_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "predictions.jsonl"
            path.write_text('{"id":"one","triggered":true}\n{"id":"two","triggered":false}\n', encoding="utf-8")

            self.assertEqual(
                load_predictions(str(path)),
                [{"id": "one", "triggered": True}, {"id": "two", "triggered": False}],
            )


if __name__ == "__main__":
    unittest.main()
