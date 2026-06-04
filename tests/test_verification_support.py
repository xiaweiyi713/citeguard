"""Tests for claim-support models and verdict mapping."""

import unittest

from src.verification.support import (
    DEFAULT_SUPPORT_POLICY,
    SupportDecisionPolicy,
    SupportResult,
    SupportVerdict,
)

from src.graph import CitationRecord
from src.verifiers import SupportAssessment
from src.verification.support import _extract_nli, build_evidence_spans


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


class SupportHelperTests(unittest.TestCase):
    def test_build_evidence_spans_from_title_abstract_chunks(self):
        citation = CitationRecord(
            citation_id="c",
            title="A Title",
            abstract="First sentence here. Second sentence about X improving Y.",
            metadata={"evidence_chunks": [{"text": "Chunk text.", "source_field": "openalex_remote_1", "source_url": "http://e"}]},
        )
        spans = build_evidence_spans(citation)
        texts = [s["text"] for s in spans]
        self.assertIn("A Title", texts)
        self.assertTrue(any("Second sentence about X" in t for t in texts))
        self.assertTrue(any(s["source_url"] == "http://e" for s in spans))

    def test_extract_nli_from_ensemble_components(self):
        ensemble = SupportAssessment(
            backend_name="ensemble_support",
            score=0.6,
            passed=True,
            rationale="x",
            details={"components": [
                {"backend": "transformers_nli", "score": 0.7, "passed": True,
                 "details": {"probabilities": {"entailment": 0.7, "contradiction": 0.1, "neutral": 0.2}}},
                {"backend": "heuristic_support", "score": 0.5, "passed": True, "details": {}},
            ]},
        )
        nli = _extract_nli(ensemble)
        self.assertEqual(nli["entailment"], 0.7)

    def test_extract_nli_none_for_heuristic(self):
        heuristic = SupportAssessment(backend_name="heuristic_support", score=0.5, passed=True, rationale="x", details={})
        self.assertIsNone(_extract_nli(heuristic))


if __name__ == "__main__":
    unittest.main()
