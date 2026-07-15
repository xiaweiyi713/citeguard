"""Governance tests for lexical support and outage-safety rules."""

import unittest

from citeguard.verification.support_patterns import (
    chinese_contradiction_pattern,
    english_contradiction_pattern,
    full_text_boundary_pattern,
    human_review_provenance_boundary_pattern,
    load_support_pattern_registry,
    source_outage_safety_pattern,
)


class SupportPatternRegistryTests(unittest.TestCase):
    def test_every_rule_has_provenance_positive_and_counterexamples(self):
        registry = load_support_pattern_registry()

        self.assertEqual(registry["schema_version"], 1)
        self.assertTrue(registry["term_sets"])
        self.assertEqual(len({rule["id"] for rule in registry["rules"]}), len(registry["rules"]))
        for rule in registry["rules"]:
            with self.subTest(rule=rule["id"]):
                self.assertTrue(rule["intent"])
                self.assertTrue(rule["source_case_ids"])
                self.assertTrue(rule["positive"]["claim"])
                self.assertTrue(rule["positive"]["evidence"])
                self.assertTrue(rule["counterexamples"])

    def test_registered_examples_enforce_positive_and_negative_behavior(self):
        registry = load_support_pattern_registry()
        for rule in registry["rules"]:
            matcher = (
                full_text_boundary_pattern
                if rule.get("matcher") == "full_text_boundary"
                else human_review_provenance_boundary_pattern
                if rule.get("matcher") == "human_review_provenance_boundary"
                else source_outage_safety_pattern
                if rule["id"] == "source_outage_safety"
                else chinese_contradiction_pattern
                if rule["language"] == "zh"
                else english_contradiction_pattern
            )
            with self.subTest(rule=rule["id"], kind="positive"):
                self.assertTrue(matcher(rule["positive"]["claim"], rule["positive"]["evidence"]))
            for counterexample in rule["counterexamples"]:
                with self.subTest(rule=rule["id"], kind="counterexample"):
                    self.assertFalse(matcher(counterexample["claim"], counterexample["evidence"]))


if __name__ == "__main__":
    unittest.main()
