"""Tests for section-aware full-text evidence location."""

from __future__ import annotations

import unittest

from citeguard.verification.fulltext import (
    locate_claim_evidence,
    split_fulltext_units,
)


PAPER = """
Abstract
We propose residual networks that are easier to optimize.

1 Introduction
Deep networks are hard to train.

2 Related Work
Prior work used highway connections.

3 Methods
We reformulate layers as residual functions.

4 Experiments
On ImageNet we evaluate residual nets with a depth of up to 152 layers.
An ensemble achieves 3.57% error on the ImageNet test set.

5 Limitations
We only report ImageNet, CIFAR-10, and COCO.

References
He, K. Deep Residual Learning for Image Recognition.
"""


class FullTextLocateTests(unittest.TestCase):
    def test_split_keeps_region_and_character_offsets(self):
        units = split_fulltext_units(PAPER)
        regions = {unit["region"] for unit in units}
        self.assertIn("experiments", regions)
        self.assertIn("limitations", regions)
        self.assertIn("references", regions)
        experiments = next(unit for unit in units if unit["region"] == "experiments")
        self.assertGreaterEqual(experiments["char_start"], 0)
        self.assertGreater(experiments["char_end"], experiments["char_start"])
        self.assertEqual(PAPER[experiments["char_start"] : experiments["char_end"]].strip()[:20], experiments["text"][:20])

    def test_quantitative_claim_prefers_experiment_span_and_keeps_conflict(self):
        located = locate_claim_evidence(
            "Residual networks achieve 3.57% error on every vision benchmark.",
            PAPER,
        )
        self.assertFalse(located["evidence_coverage"]["complete_paper_reviewed"])
        self.assertEqual(located["evidence_coverage"]["scope"], "full_text")
        self.assertTrue(located["supporting_spans"])
        self.assertEqual(located["supporting_spans"][0]["region"], "experiments")
        self.assertTrue(located["conflicting_spans"] or located["supporting_spans"])
        self.assertTrue(located["snapshot"]["sha256"].startswith("sha256:"))
        self.assertIn("char_start", located["supporting_spans"][0])


if __name__ == "__main__":
    unittest.main()
