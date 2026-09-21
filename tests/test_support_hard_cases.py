"""Tests for the first real-source hard-case support slice."""

from __future__ import annotations

import unittest
from pathlib import Path

from citeguard.verification.support_hard_cases import (
    ALLOWED_ERROR_FAMILIES,
    load_support_hard_cases,
)


DATASET = Path("data/eval/support_hard_cases_v1.json")


class SupportHardCaseTests(unittest.TestCase):
    def test_dataset_is_paper_grouped_and_covers_error_families(self):
        data = load_support_hard_cases(str(DATASET))
        cases = data["cases"]
        self.assertGreaterEqual(len(cases), 35)
        paper_splits = {}
        for case in cases:
            paper_id = case["paper_id"]
            split = case["split"]
            if paper_id in paper_splits:
                self.assertEqual(paper_splits[paper_id], split)
            paper_splits[paper_id] = split
            self.assertEqual(case["benchmark_origin"], "real_source")
            self.assertIn(case["origin"], {"natural_excerpt", "maintainer_perturbation"})
        families = {case["error_family"] for case in cases}
        families.update(case.get("error_family", "multi_citation_aggregation") for case in data.get("set_cases") or [])
        self.assertTrue(ALLOWED_ERROR_FAMILIES <= families)
        origins = {case["origin"] for case in cases}
        self.assertEqual(origins, {"natural_excerpt", "maintainer_perturbation"})
        languages = {case["lang"] for case in cases}
        self.assertIn("en", languages)
        self.assertIn("zh", languages)
        self.assertTrue(any(case["label_source"] == "maintainer_reviewed" for case in cases))
        self.assertIn("maintainer-reviewed", data["label_policy"]["notes"])


if __name__ == "__main__":
    unittest.main()
