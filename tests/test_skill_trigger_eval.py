"""Tests for the executable skill-trigger evaluation contract."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import hashlib
from pathlib import Path
import tempfile
import unittest

from jsonschema import Draft202012Validator

from citeguard.contracts import load_skill_trigger_prediction_schema, skill_trigger_prediction_schema_path
from citeguard.skill_install import bundled_skill_path, install_skill, skill_digest, skill_status
from scripts.eval_skill_trigger import (
    PREDICTION_SCHEMA_VERSION,
    REQUIRED_BUNDLED_CATEGORIES,
    SUPPORTED_CLIENTS,
    TriggerEvalError,
    dataset_summary,
    evaluate_gate,
    load_cases,
    load_dataset,
    load_prediction_artifact,
    load_prediction_run,
    load_predictions,
    main,
    prediction_template,
    score_predictions,
    validate_run_metadata,
)


ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "data" / "eval" / "skill_trigger_eval.json"
SKILL_DIGEST = "sha256:" + ("a" * 64)
DATASET_DIGEST = "sha256:" + ("b" * 64)


class SkillTriggerEvalTests(unittest.TestCase):
    def _run_main(self, argv):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(argv)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_repository_dataset_is_balanced_and_valid(self):
        suite = load_dataset(str(DATASET))
        cases = suite["cases"]
        coverage = dataset_summary(cases)

        self.assertGreaterEqual(len(cases), 100)
        self.assertTrue(any(case["should_trigger"] for case in cases))
        self.assertTrue(any(not case["should_trigger"] for case in cases))
        self.assertEqual(len(cases), len({case["id"] for case in cases}))
        self.assertEqual(suite["target_clients"], list(SUPPORTED_CLIENTS))
        self.assertEqual(set(coverage["by_language"]), {"en", "zh"})
        self.assertTrue(REQUIRED_BUNDLED_CATEGORIES.issubset(coverage["by_category"]))

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
        template = prediction_template(
            load_cases(str(DATASET)), client="codex", dataset_digest=DATASET_DIGEST, skill_digest_value=SKILL_DIGEST
        )
        serialized = json.dumps(template)

        self.assertNotIn("should_trigger", serialized)
        self.assertTrue(all(row["triggered"] is None for row in template["predictions"]))
        self.assertEqual(template["run"]["client"], "codex")
        self.assertEqual(template["run"]["suite_id"], "")
        self.assertEqual(template["run"]["dataset_digest"], DATASET_DIGEST)
        self.assertEqual(template["run"]["skill_digest"], SKILL_DIGEST)
        self.assertTrue(
            all(
                row["request_digest"]
                == "sha256:" + hashlib.sha256(row["request"].encode("utf-8")).hexdigest()
                for row in template["predictions"]
            )
        )

    def test_prediction_template_rejects_invalid_explicit_digests(self):
        with self.assertRaisesRegex(TriggerEvalError, "template dataset_digest"):
            prediction_template(load_cases(str(DATASET)), dataset_digest="sha256:fixture-dataset")
        with self.assertRaisesRegex(TriggerEvalError, "template skill_digest"):
            prediction_template(load_cases(str(DATASET)), skill_digest_value="sha256:skill-fixture")
        with self.assertRaisesRegex(TriggerEvalError, "template client"):
            prediction_template(load_cases(str(DATASET)), client="unknown-client")

    def test_prediction_artifact_schema_validates_templates_and_completed_runs(self):
        schema = load_skill_trigger_prediction_schema()
        Draft202012Validator.check_schema(schema)
        validator = Draft202012Validator(schema)
        template = prediction_template(
            [{"id": "one", "request": "verify this citation", "should_trigger": True}],
            client="codex",
            suite_id="fixture-suite",
            dataset_digest=DATASET_DIGEST,
            skill_digest_value=SKILL_DIGEST,
        )

        self.assertTrue(skill_trigger_prediction_schema_path().is_file())
        self.assertEqual([], list(validator.iter_errors(template)))

        completed = json.loads(json.dumps(template))
        completed["run"]["client_version"] = "test-client-1.0"
        completed["run"]["recorded_at"] = "2026-08-07T12:00:00Z"
        completed["predictions"][0]["triggered"] = True
        self.assertEqual([], list(validator.iter_errors(completed)))

        completed["predictions"][0]["gold"] = True
        self.assertNotEqual([], list(validator.iter_errors(completed)))

    def test_jsonl_prediction_loader_accepts_boolean_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "predictions.jsonl"
            path.write_text('{"id":"one","triggered":true}\n{"id":"two","triggered":false}\n', encoding="utf-8")

            self.assertEqual(
                load_predictions(str(path)),
                [{"id": "one", "triggered": True}, {"id": "two", "triggered": False}],
            )

    def test_versioned_prediction_run_preserves_client_provenance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "predictions.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "run": {
                            "client": "claude",
                            "client_version": "1.2.3",
                            "suite_id": "fixture-suite",
                            "skill_digest": SKILL_DIGEST,
                            "recorded_at": "2026-08-07T12:00:00Z",
                            "dataset_digest": DATASET_DIGEST,
                        },
                        "predictions": [{"id": "one", "triggered": True}],
                    }
                ),
                encoding="utf-8",
            )

            predictions, run = load_prediction_run(str(path))

        self.assertEqual(predictions, [{"id": "one", "triggered": True}])
        self.assertEqual(validate_run_metadata(run, expected_client="claude")["client_version"], "1.2.3")
        with self.assertRaisesRegex(TriggerEvalError, "does not match"):
            validate_run_metadata(run, expected_client="codex")

    def test_prediction_loader_rejects_gold_like_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "predictions.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": PREDICTION_SCHEMA_VERSION,
                        "run": {},
                        "predictions": [{"id": "one", "triggered": True, "should_trigger": True}],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(TriggerEvalError, "gold-like field"):
                load_prediction_artifact(str(path))

    def test_versioned_prediction_artifacts_require_id_but_legacy_case_id_remains_readable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "predictions.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": PREDICTION_SCHEMA_VERSION,
                        "run": {},
                        "predictions": [{"case_id": "one", "triggered": True}],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TriggerEvalError, "must use an id field"):
                load_prediction_artifact(str(path))

            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "predictions": [{"case_id": "one", "triggered": True}],
                    }
                ),
                encoding="utf-8",
            )
            predictions, _, schema_version = load_prediction_artifact(str(path))

        self.assertEqual(predictions, [{"id": "one", "triggered": True}])
        self.assertEqual(schema_version, 1)

    def test_direct_scoring_rejects_duplicate_case_ids(self):
        cases = [{"id": "one", "request": "verify this citation", "should_trigger": True}]
        with self.assertRaisesRegex(TriggerEvalError, "duplicate case ids"):
            score_predictions(
                cases,
                [{"id": "one", "triggered": True}, {"id": "one", "triggered": True}],
            )

    def test_request_provenance_rejects_tampered_request(self):
        cases = [{"id": "one", "request": "verify this citation", "should_trigger": True}]
        digest = "sha256:" + hashlib.sha256(cases[0]["request"].encode("utf-8")).hexdigest()
        with self.assertRaisesRegex(TriggerEvalError, "request does not match"):
            score_predictions(
                cases,
                [{"id": "one", "request": "verify a different citation", "request_digest": digest, "triggered": True}],
                require_request_provenance=True,
            )

    def test_request_provenance_rejects_tampered_request_digest(self):
        cases = [{"id": "one", "request": "verify this citation", "should_trigger": True}]
        with self.assertRaisesRegex(TriggerEvalError, "request_digest does not match"):
            score_predictions(
                cases,
                [{"id": "one", "request": cases[0]["request"], "request_digest": SKILL_DIGEST, "triggered": True}],
                require_request_provenance=True,
            )

    def test_run_metadata_rejects_dataset_and_skill_digest_mismatches(self):
        run = {
            "client": "codex",
            "client_version": "1.2.3",
            "suite_id": "fixture-suite",
            "skill_digest": SKILL_DIGEST,
            "recorded_at": "2026-08-07T12:00:00Z",
            "dataset_digest": DATASET_DIGEST,
        }
        with self.assertRaisesRegex(TriggerEvalError, "dataset_digest does not match"):
            validate_run_metadata(run, expected_dataset_digest=SKILL_DIGEST)
        with self.assertRaisesRegex(TriggerEvalError, "skill_digest does not match"):
            validate_run_metadata(run, expected_skill_digest=DATASET_DIGEST)
        with self.assertRaisesRegex(TriggerEvalError, "suite_id does not match"):
            validate_run_metadata(run, expected_suite_id="other-suite")

    def test_skill_digest_matches_install_status_digest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            destination = Path(tmpdir) / "citeguard-verify"
            install_report = install_skill("codex", destination=str(destination))
            status = skill_status("codex", destination=str(destination))

            self.assertEqual(skill_digest(destination), install_report["installed_digest"])
            self.assertEqual(skill_digest(destination), status["installed_digest"])
            self.assertEqual(skill_digest(destination), status["source_digest"])

    def test_strict_cli_rejects_an_unbound_skill_digest(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "predictions.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": PREDICTION_SCHEMA_VERSION,
                        "run": {},
                        "predictions": [{"id": "one", "triggered": True}],
                    }
                ),
                encoding="utf-8",
            )
            code, _, stderr = self._run_main(
                ["--dataset", str(DATASET), "--client", "codex", "--predictions", str(path)]
            )

        self.assertEqual(code, 2)
        self.assertIn("requires --skill-path or --expected-skill-digest", stderr)

    def test_strict_cli_rejects_legacy_or_jsonl_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "predictions.jsonl"
            path.write_text('{"id":"one","triggered":true}\n', encoding="utf-8")
            code, _, stderr = self._run_main(
                [
                    "--dataset",
                    str(DATASET),
                    "--client",
                    "codex",
                    "--expected-skill-digest",
                    SKILL_DIGEST,
                    "--predictions",
                    str(path),
                ]
            )

        self.assertEqual(code, 2)
        self.assertIn("top-level schema_version=2", stderr)

    def test_strict_cli_scores_a_bound_v2_artifact(self):
        suite = load_dataset(str(DATASET))
        cases = suite["cases"]
        bundle = bundled_skill_path({})
        bundle_digest = skill_digest(bundle)
        artifact = prediction_template(
            cases,
            client="codex",
            suite_id=suite["suite_id"],
            dataset_digest="sha256:" + hashlib.sha256(DATASET.read_bytes()).hexdigest(),
            skill_digest_value=bundle_digest,
        )
        artifact["run"]["client_version"] = "test-client-1.0"
        artifact["run"]["recorded_at"] = "2026-08-07T12:00:00Z"
        for case, prediction in zip(cases, artifact["predictions"]):
            prediction["triggered"] = case["should_trigger"]

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "predictions.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            code, stdout, stderr = self._run_main(
                [
                    "--dataset",
                    str(DATASET),
                    "--client",
                    "codex",
                    "--skill-path",
                    str(bundle),
                    "--require-run-metadata",
                    "--predictions",
                    str(path),
                ]
            )

        self.assertEqual(code, 0, stderr)
        payload = json.loads(stdout)
        self.assertTrue(payload["strict_provenance"])
        self.assertEqual(payload["prediction_artifact_schema_version"], PREDICTION_SCHEMA_VERSION)
        self.assertEqual(payload["agent_run"]["skill_digest"], bundle_digest)

    def test_cli_rejects_template_and_prediction_output_collision(self):
        code, _, stderr = self._run_main(
            ["--write-template", "/tmp/predictions.json", "--predictions", "/tmp/predictions.json"]
        )

        self.assertEqual(code, 2)
        self.assertIn("cannot be combined", stderr)


if __name__ == "__main__":
    unittest.main()
