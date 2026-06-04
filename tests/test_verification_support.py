"""Tests for claim-support models and verdict mapping."""

import unittest

from src.verification.support import (
    DEFAULT_SUPPORT_POLICY,
    SupportDecisionPolicy,
    SupportResult,
    SupportVerdict,
)


class SupportModelTests(unittest.TestCase):
    def test_default_policy_values(self):
        self.assertEqual(DEFAULT_SUPPORT_POLICY.entail_strong, 0.55)
        self.assertEqual(DEFAULT_SUPPORT_POLICY.contra_strong, 0.55)

    def test_support_result_to_dict(self):
        result = SupportResult(
            verdict=SupportVerdict.SUPPORTED,
            confidence=0.8,
            claim="X improves Y.",
            evidence={"text": "X improves Y by 10%.", "source_field": "abstract_sentence_1", "source_url": ""},
            nli_scores={"entailment": 0.8, "contradiction": 0.05, "neutral": 0.15},
            engine="ensemble",
            resolution={"verdict": "matched", "title": "A Paper", "year": 2024, "sources_checked": ["openalex"]},
            explanation="ok",
            lang="en",
        )
        data = result.to_dict()
        self.assertEqual(data["verdict"], "supported")
        self.assertEqual(data["evidence"]["source_field"], "abstract_sentence_1")
        self.assertEqual(data["nli_scores"]["entailment"], 0.8)
        self.assertEqual(data["engine"], "ensemble")
        self.assertEqual(data["resolution"]["title"], "A Paper")


if __name__ == "__main__":
    unittest.main()
