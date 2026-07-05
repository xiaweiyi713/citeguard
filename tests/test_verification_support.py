"""Tests for claim-support models and verdict mapping."""

import unittest

from citeguard.verification.support import (
    DEFAULT_SUPPORT_POLICY,
    SupportDecisionPolicy,
    SupportResult,
    SupportVerdict,
    infer_evidence_scope,
)

from citeguard.verification import CitationRecord
from citeguard.verification import SupportAssessment
from citeguard.verification.support import _extract_nli, build_evidence_spans
from citeguard.verification.support import assess_support


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
        self.assertEqual(data["evidence_scope"], "abstract")
        self.assertEqual(data["next_action"], "keep_claim")
        self.assertFalse(data["counterevidence_review"])
        self.assertEqual(data["counterevidence_reason"], "")

    def test_support_result_to_dict_carries_next_action_for_unresolved_source_outage(self):
        result = SupportResult(
            verdict=SupportVerdict.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
            claim="X improves Y.",
            evidence={"text": "", "source_field": "none", "source_url": "", "evidence_scope": "none"},
            nli_scores=None,
            engine="none",
            resolution={"verdict": "not_found", "source_failure_mode": "all_sources_failed"},
            explanation="source unavailable",
            lang="en",
            evidence_scope="none",
        )
        data = result.to_dict()

        self.assertEqual(data["next_action"], "retry_or_check_source_health")
        self.assertTrue(data["counterevidence_review"])
        self.assertEqual(data["counterevidence_reason"], "unresolved_citation")


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
        scopes = {s["source_field"]: s["evidence_scope"] for s in spans}
        self.assertEqual(scopes["title"], "title")
        self.assertEqual(scopes["abstract_sentence_1"], "abstract")
        self.assertEqual(scopes["openalex_remote_1"], "metadata_snippet")

    def test_infer_evidence_scope_is_conservative(self):
        self.assertEqual(infer_evidence_scope("abstract_sentence_2"), "abstract")
        self.assertEqual(infer_evidence_scope("publisher_full_text_paragraph_1"), "full_text")
        self.assertEqual(infer_evidence_scope("metadata_chunk_1"), "metadata")
        self.assertEqual(infer_evidence_scope("remote_chunk_1", "https://example.org"), "metadata_snippet")
        self.assertEqual(infer_evidence_scope("none"), "none")

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


class _FailingModelEnsembleBackend:
    def assess(self, claim_text, evidence_text):
        return SupportAssessment(
            backend_name="ensemble_support",
            score=0.12,
            passed=False,
            rationale="fallback",
            details={
                "components": [
                    {
                        "backend": "transformers_nli",
                        "score": 0.0,
                        "passed": False,
                        "details": {
                            "error_code": "model_unavailable",
                            "error_type": "TimeoutError",
                            "message": "model hub timed out",
                            "model_name": "nli-model",
                        },
                    },
                    {
                        "backend": "heuristic_support",
                        "score": 0.12,
                        "passed": False,
                        "details": {},
                    },
                ]
            },
        )


def _paper(abstract):
    return CitationRecord(citation_id="p", title="Some Paper", abstract=abstract, source="memory")


class AssessSupportTests(unittest.TestCase):
    def test_supported_when_entailment_strong(self):
        backend = _FakeBackend({"X improves Y": (0.6, {"entailment": 0.8, "contradiction": 0.05, "neutral": 0.15})})
        result = assess_support("X improves Y.", _paper("Study shows X improves Y in trials."), backend)
        self.assertEqual(result.verdict, SupportVerdict.SUPPORTED)
        self.assertEqual(result.engine, "ensemble")
        self.assertEqual(result.evidence_scope, "abstract")
        self.assertEqual(result.evidence["evidence_scope"], "abstract")

    def test_tie_break_prefers_abstract_over_title(self):
        backend = _FakeBackend(
            {
                "X improves Y": (
                    0.6,
                    {"entailment": 0.8, "contradiction": 0.05, "neutral": 0.15},
                )
            }
        )
        paper = CitationRecord(
            citation_id="p",
            title="X improves Y",
            abstract="Study shows X improves Y in trials.",
            source="memory",
        )

        result = assess_support("X improves Y.", paper, backend)

        self.assertEqual(result.verdict, SupportVerdict.SUPPORTED)
        self.assertEqual(result.evidence_scope, "abstract")

    def test_contradicted_when_contradiction_strong_and_related(self):
        backend = _FakeBackend({"X improves Y": (0.6, {"entailment": 0.05, "contradiction": 0.8, "neutral": 0.15})})
        result = assess_support("X improves Y.", _paper("We find X improves Y is false; X does not improve Y."), backend)
        self.assertEqual(result.verdict, SupportVerdict.CONTRADICTED)

    def test_explicit_contradiction_cue_can_override_low_nli_contradiction(self):
        backend = _FakeBackend({
            "does not improve": (0.21, {"entailment": 0.12, "contradiction": 0.20, "neutral": 0.68})
        })

        result = assess_support(
            "Model M increases accuracy on task T.",
            _paper("We find that model M does not improve, and in fact reduces, accuracy on task T."),
            backend,
        )

        self.assertEqual(result.verdict, SupportVerdict.CONTRADICTED)
        self.assertGreaterEqual(result.confidence, DEFAULT_SUPPORT_POLICY.contra_strong)
        self.assertIn("explicit contradiction", result.explanation)

    def test_source_outage_fabrication_claim_can_be_explicitly_contradicted(self):
        backend = _FakeBackend({
            "does not mark": (0.22, {"entailment": 0.20, "contradiction": 0.22, "neutral": 0.58})
        })

        result = assess_support(
            "CiteGuard treats source outages as fabricated citations.",
            _paper("When sources fail or time out, CiteGuard lowers confidence and does not mark the citation as fabricated."),
            backend,
        )

        self.assertEqual(result.verdict, SupportVerdict.CONTRADICTED)
        self.assertIn("explicit contradiction", result.explanation)

    def test_unrelated_negation_is_not_treated_as_contradiction(self):
        backend = _FakeBackend({
            "does not include": (0.12, {"entailment": 0.10, "contradiction": 0.20, "neutral": 0.70})
        })

        result = assess_support(
            "The intervention improves long-term retention over six months.",
            _paper("The abstract reports immediate post-test gains but does not include follow-up measurements."),
            backend,
        )

        self.assertEqual(result.verdict, SupportVerdict.INSUFFICIENT_EVIDENCE)

    def test_negative_support_claim_is_not_contradicted_by_matching_negative_evidence(self):
        backend = _FakeBackend({
            "do not support": (0.62, {"entailment": 0.62, "contradiction": 0.18, "neutral": 0.20})
        })

        result = assess_support(
            "A paper can be real while failing to support the nearby claim.",
            _paper("We include hard negatives where real papers do not support the claim."),
            backend,
        )

        self.assertNotEqual(result.verdict, SupportVerdict.CONTRADICTED)

    def test_weak_support_requires_an_explainable_anchor(self):
        backend = _FakeBackend({
            "图像压缩算法": (0.0, {"entailment": 0.48, "contradiction": 0.39, "neutral": 0.13})
        })

        result = assess_support(
            "该方法显著提升了检索准确率。",
            _paper("本文主要讨论了一种无关的图像压缩算法。"),
            backend,
            lang="zh",
        )

        self.assertEqual(result.verdict, SupportVerdict.INSUFFICIENT_EVIDENCE)

    def test_title_anchor_can_be_weak_support_without_strong_nli(self):
        backend = _FakeBackend({
            "Citation Auditing": (0.30, {"entailment": 0.02, "contradiction": 0.01, "neutral": 0.97})
        })
        paper = CitationRecord(
            citation_id="p",
            title="CiteGuardBench: A Benchmark for Citation Auditing",
            source="memory",
        )

        result = assess_support(
            "The cited paper proves that citation auditing improves research integrity.",
            paper,
            backend,
        )

        self.assertEqual(result.verdict, SupportVerdict.WEAKLY_SUPPORTED)
        self.assertEqual(result.evidence_scope, "title")

    def test_metadata_snippet_can_directly_support_source_outage_claim(self):
        backend = _FakeBackend({
            "sources_checked": (0.27, {"entailment": 0.42, "contradiction": 0.10, "neutral": 0.48})
        })
        paper = CitationRecord(
            citation_id="p",
            title="",
            source="memory",
            metadata={
                "evidence_chunks": [
                    {
                        "text": "Status metadata reports sources_checked separately from sources_failed and lowers confidence during source outages.",
                        "source_field": "source_status_snippet",
                        "source_url": "https://example.org/status",
                        "evidence_scope": "metadata_snippet",
                    }
                ]
            },
        )

        result = assess_support(
            "The system distinguishes source outages from fabricated citations.",
            paper,
            backend,
        )

        self.assertEqual(result.verdict, SupportVerdict.SUPPORTED)
        self.assertEqual(result.evidence_scope, "metadata_snippet")

    def test_insufficient_when_neutral(self):
        backend = _FakeBackend({"unrelated topic": (0.1, {"entailment": 0.1, "contradiction": 0.1, "neutral": 0.8})})
        result = assess_support("X improves Y.", _paper("This is an unrelated topic about birds."), backend)
        self.assertEqual(result.verdict, SupportVerdict.INSUFFICIENT_EVIDENCE)

    def test_heuristic_engine_never_contradicts(self):
        backend = _FakeBackend({"X improves Y": (0.7, None)}, ensemble=False)
        result = assess_support("X improves Y.", _paper("X improves Y greatly."), backend)
        self.assertEqual(result.engine, "heuristic")
        self.assertIn(result.verdict, (SupportVerdict.WEAKLY_SUPPORTED, SupportVerdict.INSUFFICIENT_EVIDENCE))

    def test_model_failure_details_are_exposed_without_raising(self):
        result = assess_support(
            "X improves Y.",
            _paper("The paper evaluates X and Y."),
            _FailingModelEnsembleBackend(),
        )

        payload = result.to_dict()
        self.assertEqual(payload["verdict"], "insufficient_evidence")
        self.assertEqual(payload["model_failure_details"][0]["error_code"], "model_unavailable")
        self.assertEqual(payload["model_failure_details"][0]["backend"], "transformers_nli")
        self.assertIn("timed out", payload["model_failure_details"][0]["message"])


if __name__ == "__main__":
    unittest.main()
