"""Offline guardrails for the golden-case live canary.

Validates the golden dataset shape (unique ids, supported expect keys, pinned
hard-line cases) and unit-tests the pure ``evaluate_case`` helper with
synthetic verification result dicts. No network access is required.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from scripts.canary_live import HARD_LINE_CASE_IDS, SUPPORTED_EXPECT_KEYS, evaluate_case, load_dataset

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "data" / "eval" / "canary_golden.json"

KNOWN_VERDICTS = {"verified", "metadata_mismatch", "not_found", "ambiguous"}


def _result(**overrides):
    """Build a minimal synthetic VerificationResult.to_dict() payload."""

    payload = {
        "verdict": "verified",
        "confidence": 1.0,
        "canonical_record": {"title": "Attention Is All You Need", "year": 2017},
        "outage_limited": False,
        "doi_registration": None,
        "identifier_lookup": None,
        "sources_failed": [],
    }
    payload.update(overrides)
    return payload


class CanaryDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = load_dataset(DATASET_PATH)
        cls.by_id = {case["id"]: case for case in cls.cases}

    def test_dataset_loads_with_unique_case_ids(self):
        ids = [case["id"] for case in self.cases]
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)))

    def test_every_case_has_nonempty_fields_and_expect(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                self.assertIsInstance(case["fields"], dict)
                self.assertTrue(case["fields"])
                self.assertIsInstance(case["expect"], dict)
                self.assertTrue(case["expect"])

    def test_expect_blocks_use_only_supported_keys(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                unsupported = set(case["expect"]) - SUPPORTED_EXPECT_KEYS
                self.assertEqual(unsupported, set())

    def test_expect_values_are_well_typed(self):
        for case in self.cases:
            expect = case["expect"]
            with self.subTest(case=case["id"]):
                for key in ("verdict_in", "must_not"):
                    if key in expect:
                        self.assertIsInstance(expect[key], list)
                        self.assertTrue(expect[key])
                        self.assertTrue(set(expect[key]) <= KNOWN_VERDICTS)
                if "canonical_year" in expect:
                    self.assertIsInstance(expect["canonical_year"], int)
                if "canonical_year_in" in expect:
                    self.assertIsInstance(expect["canonical_year_in"], list)
                    self.assertTrue(all(isinstance(item, int) for item in expect["canonical_year_in"]))
                if "doi_registered" in expect:
                    self.assertIsInstance(expect["doi_registered"], bool)

    def test_hard_line_cases_are_present_and_pinned(self):
        self.assertEqual(HARD_LINE_CASE_IDS, frozenset({"g01", "g02", "g04", "g05"}))
        for case_id in sorted(HARD_LINE_CASE_IDS):
            with self.subTest(case=case_id):
                self.assertIn(case_id, self.by_id)

        g01 = self.by_id["g01"]
        self.assertEqual(
            g01["fields"],
            {"title": "Attention Is All You Need", "arxiv_id": "1706.03762", "year": 2017},
        )
        self.assertEqual(g01["expect"], {"verdict_in": ["verified"], "canonical_year": 2017})

        g02 = self.by_id["g02"]
        self.assertEqual(
            g02["fields"],
            {"title": "Attention Is All You Need", "authors": ["Ashish Vaswani"], "year": 2017},
        )
        self.assertEqual(g02["expect"], {"must_not": ["metadata_mismatch"]})

        for case_id in ("g04", "g05"):
            with self.subTest(case=case_id):
                self.assertEqual(self.by_id[case_id]["expect"], {"verdict_in": ["not_found"]})

    def test_load_dataset_rejects_duplicate_ids(self):
        raw = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        raw["cases"].append(dict(raw["cases"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_dataset(payload=raw)

    def test_load_dataset_rejects_unsupported_expect_keys(self):
        raw = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
        raw["cases"][0]["expect"]["surprise_key"] = True
        with self.assertRaisesRegex(ValueError, "surprise_key"):
            load_dataset(payload=raw)


class EvaluateCaseTests(unittest.TestCase):
    def test_pass_when_verdict_allowed_and_canonical_year_matches(self):
        status, reasons = evaluate_case(
            _result(verdict="verified"),
            {"verdict_in": ["verified"], "canonical_year": 2017},
        )
        self.assertEqual(status, "pass")
        self.assertEqual(reasons, [])

    def test_pass_when_canonical_year_in_tolerance_set(self):
        status, reasons = evaluate_case(
            _result(verdict="metadata_mismatch", canonical_record={"year": 2025}),
            {"verdict_in": ["verified", "metadata_mismatch"], "canonical_year_in": [2024, 2025]},
        )
        self.assertEqual(status, "pass")
        self.assertEqual(reasons, [])

    def test_fail_when_verdict_not_in_allowed_set(self):
        status, reasons = evaluate_case(_result(verdict="not_found", canonical_record=None), {"verdict_in": ["verified"]})
        self.assertEqual(status, "fail")
        self.assertTrue(any("not_found" in reason for reason in reasons))

    def test_fail_when_must_not_verdict_observed(self):
        status, reasons = evaluate_case(_result(verdict="metadata_mismatch"), {"must_not": ["metadata_mismatch"]})
        self.assertEqual(status, "fail")
        self.assertTrue(any("metadata_mismatch" in reason for reason in reasons))

    def test_skip_when_outage_limited(self):
        status, reasons = evaluate_case(
            _result(verdict="not_found", canonical_record=None, outage_limited=True),
            {"verdict_in": ["verified"], "canonical_year": 2017},
        )
        self.assertEqual(status, "skip")
        self.assertTrue(any("outage" in reason for reason in reasons))

    def test_fail_when_canonical_year_differs(self):
        status, reasons = evaluate_case(
            _result(canonical_record={"year": 2018}),
            {"verdict_in": ["verified"], "canonical_year": 2017},
        )
        self.assertEqual(status, "fail")
        self.assertTrue(any("2018" in reason and "2017" in reason for reason in reasons))

    def test_fail_when_canonical_record_missing_but_year_expected(self):
        status, reasons = evaluate_case(
            _result(verdict="verified", canonical_record=None),
            {"verdict_in": ["verified"], "canonical_year": 2017},
        )
        self.assertEqual(status, "fail")
        self.assertTrue(any("canonical_record" in reason for reason in reasons))

    def test_fail_when_canonical_record_missing_but_year_set_expected(self):
        status, reasons = evaluate_case(
            _result(verdict="verified", canonical_record=None),
            {"canonical_year_in": [2024, 2025]},
        )
        self.assertEqual(status, "fail")
        self.assertTrue(any("canonical_record" in reason for reason in reasons))

    def test_doi_registered_expectation_passes(self):
        status, reasons = evaluate_case(
            _result(verdict="not_found", canonical_record=None, doi_registration={"registered": True, "status": "registered"}),
            {"verdict_in": ["not_found"], "doi_registered": True},
        )
        self.assertEqual(status, "pass")
        self.assertEqual(reasons, [])

    def test_doi_registered_expectation_fails_on_mismatch(self):
        status, reasons = evaluate_case(
            _result(verdict="not_found", canonical_record=None, doi_registration={"registered": False, "status": "not_registered"}),
            {"verdict_in": ["not_found"], "doi_registered": True},
        )
        self.assertEqual(status, "fail")
        self.assertTrue(any("doi_registered" in reason for reason in reasons))

    def test_doi_registered_expectation_fails_when_registry_not_consulted(self):
        status, reasons = evaluate_case(
            _result(verdict="not_found", canonical_record=None, doi_registration=None),
            {"verdict_in": ["not_found"], "doi_registered": True},
        )
        self.assertEqual(status, "fail")
        self.assertTrue(any("doi_registration" in reason for reason in reasons))

    def test_doi_registry_outage_is_skip_not_fail(self):
        status, reasons = evaluate_case(
            _result(
                verdict="not_found",
                canonical_record=None,
                doi_registration={"registered": None, "status": "unavailable"},
            ),
            {"verdict_in": ["not_found"], "doi_registered": True},
        )
        self.assertEqual(status, "skip")
        self.assertTrue(any("unavailable" in reason for reason in reasons))

    def test_fail_wins_over_registry_outage_skip(self):
        status, reasons = evaluate_case(
            _result(
                verdict="ambiguous",
                canonical_record=None,
                doi_registration={"registered": None, "status": "unavailable"},
            ),
            {"verdict_in": ["not_found"], "doi_registered": True},
        )
        self.assertEqual(status, "fail")
        self.assertTrue(any("ambiguous" in reason for reason in reasons))


if __name__ == "__main__":
    unittest.main()
