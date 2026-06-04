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
from src.verification.support import assess_support


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


class _FakeBackend:
    """Returns a preset SupportAssessment per evidence text (keyword-matched)."""

    def __init__(self, table, ensemble=True):
        self.table = table          # {substring: (score, probs_or_None)}
        self.ensemble = ensemble

    def assess(self, claim_text, evidence_text):
        score, probs = 0.0, None
        for key, (s, p) in self.table.items():
            if key in evidence_text:
                score, probs = s, p
                break
        if self.ensemble and probs is not None:
            return SupportAssessment(
                backend_name="ensemble_support", score=score, passed=score >= 0.5, rationale="x",
                details={"components": [
                    {"backend": "transformers_nli", "score": probs["entailment"], "passed": False, "details": {"probabilities": probs}},
                    {"backend": "heuristic_support", "score": score, "passed": False, "details": {}},
                ]},
            )
        return SupportAssessment(backend_name="heuristic_support", score=score, passed=score >= 0.5, rationale="x", details={})


def _paper(abstract):
    return CitationRecord(citation_id="p", title="Some Paper", abstract=abstract, source="memory")


class AssessSupportTests(unittest.TestCase):
    def test_supported_when_entailment_strong(self):
        backend = _FakeBackend({"X improves Y": (0.6, {"entailment": 0.8, "contradiction": 0.05, "neutral": 0.15})})
        result = assess_support("X improves Y.", _paper("Study shows X improves Y in trials."), backend)
        self.assertEqual(result.verdict, SupportVerdict.SUPPORTED)
        self.assertEqual(result.engine, "ensemble")

    def test_contradicted_when_contradiction_strong_and_related(self):
        backend = _FakeBackend({"X improves Y": (0.6, {"entailment": 0.05, "contradiction": 0.8, "neutral": 0.15})})
        result = assess_support("X improves Y.", _paper("We find X improves Y is false; X does not improve Y."), backend)
        self.assertEqual(result.verdict, SupportVerdict.CONTRADICTED)

    def test_insufficient_when_neutral(self):
        backend = _FakeBackend({"unrelated topic": (0.1, {"entailment": 0.1, "contradiction": 0.1, "neutral": 0.8})})
        result = assess_support("X improves Y.", _paper("This is an unrelated topic about birds."), backend)
        self.assertEqual(result.verdict, SupportVerdict.INSUFFICIENT_EVIDENCE)

    def test_heuristic_engine_never_contradicts(self):
        backend = _FakeBackend({"X improves Y": (0.7, None)}, ensemble=False)
        result = assess_support("X improves Y.", _paper("X improves Y greatly."), backend)
        self.assertEqual(result.engine, "heuristic")
        self.assertIn(result.verdict, (SupportVerdict.WEAKLY_SUPPORTED, SupportVerdict.INSUFFICIENT_EVIDENCE))


if __name__ == "__main__":
    unittest.main()
