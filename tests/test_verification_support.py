"""Tests for claim-support models and verdict mapping."""

import unittest

from citeguard.verification.support import (
    ClaimSupportRequest,
    DEFAULT_SUPPORT_POLICY,
    SupportResult,
    SupportVerdict,
    audit_claim_support,
    check_claim_support,
    check_claim_support_set,
    infer_evidence_scope,
    infer_evidence_source_name,
)

from citeguard.verification import CitationRecord
from citeguard.verification import SupportAssessment
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
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
        self.assertEqual(data["evidence"]["source_name"], "citation_metadata")
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
            metadata={
                "evidence_chunks": [
                    {
                        "text": "Chunk text.",
                        "source_field": "openalex_remote_1",
                        "source_url": "http://e",
                    }
                ]
            },
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
        sources = {s["source_field"]: s["source_name"] for s in spans}
        self.assertEqual(sources["title"], "citation_metadata")
        self.assertEqual(sources["abstract_sentence_1"], "citation_metadata")
        self.assertEqual(sources["openalex_remote_1"], "openalex")

    def test_infer_evidence_scope_is_conservative(self):
        self.assertEqual(infer_evidence_scope("abstract_sentence_2"), "abstract")
        self.assertEqual(infer_evidence_scope("publisher_full_text_paragraph_1"), "full_text")
        self.assertEqual(infer_evidence_scope("metadata_chunk_1"), "metadata")
        self.assertEqual(infer_evidence_scope("remote_chunk_1", "https://example.org"), "metadata_snippet")
        self.assertEqual(infer_evidence_scope("none"), "none")

    def test_infer_evidence_source_name_is_stable_for_agents(self):
        self.assertEqual(infer_evidence_source_name("abstract_sentence_2"), "citation_metadata")
        self.assertEqual(infer_evidence_source_name("user_full_text_excerpt_1"), "user_provided")
        self.assertEqual(infer_evidence_source_name("openalex_remote_1_paragraph_1"), "openalex")
        self.assertEqual(infer_evidence_source_name("metadata_chunk_1", "https://api.crossref.org/work"), "crossref")
        self.assertEqual(infer_evidence_source_name("none"), "none")

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


def _sparse_quality_record():
    return CitationRecord(
        citation_id="sparse",
        title="Sparse source metadata improves audits",
        authors=["Ada Lovelace"],
        year=2026,
        doi="10.5555/sparse",
        source="crossref",
        metadata={
            "metadata_quality": {
                "schema_version": 1,
                "present_fields": ["title", "authors", "year", "identifier"],
                "missing_fields": ["venue", "abstract", "url"],
                "identifiers": {"doi": True, "arxiv_id": False},
                "completeness": 0.5714,
                "confidence_effect": "missing_metadata_lowers_confidence_not_fabrication_evidence",
            }
        },
    )


class AssessSupportTests(unittest.TestCase):
    def test_supported_when_entailment_strong(self):
        backend = _FakeBackend({"X improves Y": (0.6, {"entailment": 0.8, "contradiction": 0.05, "neutral": 0.15})})
        result = assess_support("X improves Y.", _paper("Study shows X improves Y in trials."), backend)
        self.assertEqual(result.verdict, SupportVerdict.SUPPORTED)
        self.assertEqual(result.engine, "ensemble")
        self.assertEqual(result.evidence_scope, "abstract")
        self.assertEqual(result.evidence["evidence_scope"], "abstract")

    def test_check_claim_support_exposes_source_metadata_quality(self):
        record = _sparse_quality_record()
        backend = _FakeBackend(
            {
                "Sparse source metadata improves audits": (
                    0.6,
                    {"entailment": 0.8, "contradiction": 0.05, "neutral": 0.15},
                )
            }
        )

        result = check_claim_support(
            "Sparse source metadata improves audits.",
            CitationRecord(citation_id="candidate", title=record.title, year=2026),
            InMemoryMetadataSource([record]),
            backend=backend,
        )
        payload = result.to_dict()

        self.assertEqual(result.verdict, SupportVerdict.SUPPORTED)
        self.assertEqual(payload["resolution"]["canonical_metadata_quality"]["missing_fields"], ["venue", "abstract", "url"])
        self.assertEqual(payload["source_metadata_missing_fields"], ["venue", "abstract", "url"])
        self.assertEqual(
            payload["source_metadata_confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )

    def test_support_audit_risk_ranking_exposes_source_metadata_quality(self):
        record = _sparse_quality_record()
        backend = _FakeBackend(
            {
                "Sparse source metadata improves audits": (
                    0.6,
                    {"entailment": 0.8, "contradiction": 0.05, "neutral": 0.15},
                )
            }
        )

        report = audit_claim_support(
            [ClaimSupportRequest("Sparse source metadata improves audits.", CitationRecord("candidate", title=record.title, year=2026))],
            InMemoryMetadataSource([record]),
            backend=backend,
        )
        risk_item = report.to_dict()["risk_ranking"][0]

        self.assertEqual(risk_item["verdict"], "supported")
        self.assertEqual(risk_item["source_metadata_missing_fields"], ["venue", "abstract", "url"])
        self.assertEqual(
            risk_item["source_metadata_confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )
        self.assertTrue(risk_item["canonical_metadata_quality"]["identifiers"]["doi"])

    def test_support_set_aggregates_source_metadata_quality(self):
        record = _sparse_quality_record()
        backend = _FakeBackend(
            {
                "Sparse source metadata improves audits": (
                    0.6,
                    {"entailment": 0.8, "contradiction": 0.05, "neutral": 0.15},
                )
            }
        )

        result = check_claim_support_set(
            "Sparse source metadata improves audits.",
            [CitationRecord("candidate", title=record.title, year=2026)],
            InMemoryMetadataSource([record]),
            backend=backend,
        )
        payload = result.to_dict()

        self.assertEqual(payload["verdict"], "supported")
        self.assertEqual(payload["source_metadata_missing_fields"], ["venue", "abstract", "url"])
        self.assertEqual(
            payload["source_metadata_confidence_effects"],
            ["missing_metadata_lowers_confidence_not_fabrication_evidence"],
        )
        self.assertEqual(payload["support_mode_details"]["schema_version"], 1)
        self.assertEqual(payload["support_mode_details"]["support_mode"], "single_strong_support")
        self.assertEqual(payload["support_mode_details"]["decision"], "one_strong_citation_supports_claim")
        self.assertEqual(payload["support_mode_details"]["supported_indexes"], [0])
        self.assertEqual(payload["support_mode_details"]["weakly_supported_indexes"], [])
        self.assertEqual(payload["support_mode_details"]["contradicted_indexes"], [])
        self.assertEqual(payload["support_mode_details"]["full_text_evidence_present"], False)
        self.assertIn(
            "no_unstated_multi_hop_or_full_text_support",
            payload["support_mode_details"]["policy"],
        )

    def test_support_set_mode_details_keep_multiple_weak_citations_tentative(self):
        records = [
            CitationRecord(
                citation_id="weak-1",
                title="CiteGuardBench: A Benchmark for Citation Auditing",
                source="memory",
            ),
            CitationRecord(
                citation_id="weak-2",
                title="Citation Auditing Workflows for Reviewers",
                source="memory",
            ),
        ]
        backend = _FakeBackend(
            {
                "Citation Auditing": (
                    0.30,
                    {"entailment": 0.02, "contradiction": 0.01, "neutral": 0.97},
                )
            }
        )

        result = check_claim_support_set(
            "The cited papers prove that citation auditing improves research integrity.",
            records,
            InMemoryMetadataSource(records),
            backend=backend,
        )
        payload = result.to_dict()

        self.assertEqual(payload["verdict"], "weakly_supported")
        self.assertEqual(payload["support_mode"], "multiple_weak_support")
        self.assertEqual(
            payload["support_mode_details"]["decision"],
            "multiple_weak_citations_remain_tentative",
        )
        self.assertEqual(payload["support_mode_details"]["strong_support_count"], 0)
        self.assertEqual(payload["support_mode_details"]["weak_support_count"], 2)
        self.assertEqual(payload["support_mode_details"]["weakly_supported_indexes"], [0, 1])
        self.assertEqual(payload["support_mode_details"]["supported_indexes"], [])
        self.assertIn(
            "weak_sources_do_not_become_strong_support",
            payload["support_mode_details"]["reasons"],
        )
        self.assertIn(
            "no_full_text_evidence_in_aggregate",
            payload["support_mode_details"]["reasons"],
        )

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
        self.assertEqual(result.evidence["source_name"], "remote_metadata")

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
