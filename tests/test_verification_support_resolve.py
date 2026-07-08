"""End-to-end check_claim_support over an in-memory source (no models, no network)."""

import unittest

from citeguard.verification import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.verification import SupportAssessment
from citeguard.verification.parse import parse_citation
from citeguard.verification.support import (
    ClaimSupportAuditItem,
    ClaimSupportRequest,
    ClaimSupportSetResult,
    SupportAuditReport,
    SupportVerdict,
    audit_claim_support,
    check_claim_support,
    check_claim_support_set,
    enrich_support_payload_with_counterevidence,
    search_counterevidence_candidates,
)


class _FakeEnsembleBackend:
    def assess(self, claim_text, evidence_text):
        probs = {"entailment": 0.82, "contradiction": 0.05, "neutral": 0.13} if "improves" in evidence_text else {"entailment": 0.1, "contradiction": 0.1, "neutral": 0.8}
        return SupportAssessment(
            backend_name="ensemble_support", score=0.6, passed=True, rationale="x",
            details={"components": [{"backend": "transformers_nli", "score": probs["entailment"], "passed": True, "details": {"probabilities": probs}}]},
        )


class _ContradictingBackend:
    def assess(self, claim_text, evidence_text):
        probs = {"entailment": 0.05, "contradiction": 0.86, "neutral": 0.09}
        return SupportAssessment(
            backend_name="ensemble_support",
            score=0.65,
            passed=True,
            rationale="x",
            details={
                "components": [
                    {
                        "backend": "transformers_nli",
                        "score": probs["contradiction"],
                        "passed": True,
                        "details": {"probabilities": probs},
                    }
                ]
            },
        )


class _FullTextOnlyBackend:
    def assess(self, claim_text, evidence_text):
        if "lawful full-text excerpt" in evidence_text:
            probs = {"entailment": 0.91, "contradiction": 0.03, "neutral": 0.06}
            return SupportAssessment(
                backend_name="ensemble_support",
                score=0.8,
                passed=True,
                rationale="full-text excerpt entails",
                details={
                    "components": [
                        {
                            "backend": "transformers_nli",
                            "score": probs["entailment"],
                            "passed": True,
                            "details": {"probabilities": probs},
                        }
                    ]
                },
            )
        probs = {"entailment": 0.05, "contradiction": 0.05, "neutral": 0.9}
        return SupportAssessment(
            backend_name="ensemble_support",
            score=0.05,
            passed=False,
            rationale="not enough evidence",
            details={
                "components": [
                    {
                        "backend": "transformers_nli",
                        "score": probs["entailment"],
                        "passed": False,
                        "details": {"probabilities": probs},
                    }
                ]
            },
        )


class _WeakOnlyBackend:
    def assess(self, claim_text, evidence_text):
        probs = {"entailment": 0.34, "contradiction": 0.04, "neutral": 0.62}
        return SupportAssessment(
            backend_name="ensemble_support",
            score=0.45,
            passed=True,
            rationale="weak related evidence",
            details={
                "components": [
                    {
                        "backend": "transformers_nli",
                        "score": probs["entailment"],
                        "passed": True,
                        "details": {"probabilities": probs},
                    }
                ]
            },
        )


class _StrongSupportBackend:
    def assess(self, claim_text, evidence_text):
        probs = {"entailment": 0.93, "contradiction": 0.02, "neutral": 0.05}
        return SupportAssessment(
            backend_name="ensemble_support",
            score=0.8,
            passed=True,
            rationale="strong support",
            details={
                "components": [
                    {
                        "backend": "transformers_nli",
                        "score": probs["entailment"],
                        "passed": True,
                        "details": {"probabilities": probs},
                    }
                ]
            },
        )


class _HTTPDiagnostics:
    def __init__(self):
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_error = ""
        self.last_status_code = None
        self.last_url = ""
        self.last_cache_hit = False
        self.last_attempt_count = 0
        self.last_retry_count = 0
        self.last_retry_after_seconds = None
        self.last_retry_delay_seconds = None

    def fail_rate_limited(self):
        self.last_error_code = "source_unavailable"
        self.last_error_kind = "rate_limited"
        self.last_error = "http_429"
        self.last_status_code = 429
        self.last_url = "https://api.example.test/support"
        self.last_cache_hit = False
        self.last_attempt_count = 2
        self.last_retry_count = 1
        self.last_retry_after_seconds = 2.0
        self.last_retry_delay_seconds = 1.5

    def clear(self):
        self.last_error_code = ""
        self.last_error_kind = ""
        self.last_error = ""
        self.last_status_code = 200
        self.last_url = "https://api.example.test/support"
        self.last_cache_hit = False
        self.last_attempt_count = 0
        self.last_retry_count = 0
        self.last_retry_after_seconds = None
        self.last_retry_delay_seconds = None


class _FailingMetadataSource(InMemoryMetadataSource):
    name = "timeout_source"

    def __init__(self):
        super().__init__([])

    def search(self, query, top_k=5):
        raise TimeoutError("source timed out")

    def lookup(self, candidate):
        raise TimeoutError("source timed out")


class _LookupFailureThenSearchSuccessSource:
    name = "diagnostic_source"

    def __init__(self, record):
        self.record = record
        self.http_client = _HTTPDiagnostics()

    def all_records(self):
        return [self.record]

    def lookup(self, candidate):
        self.http_client.fail_rate_limited()
        return None

    def search(self, query, top_k=5):
        self.http_client.clear()
        return [self.record]


class _HTTPFailingCounterEvidenceSource(InMemoryMetadataSource):
    name = "diagnostic_source"

    def __init__(self, records):
        super().__init__(records)
        self.http_client = _HTTPDiagnostics()

    def search(self, query, top_k=5):
        self.http_client.fail_rate_limited()
        return []


class CheckClaimSupportTests(unittest.TestCase):
    def setUp(self):
        self.paper = CitationRecord(
            citation_id="p1", title="Method M for Task T", abstract="We show method M improves task T accuracy.",
            authors=["A. Author"], year=2024, source="memory",
        )
        self.source = InMemoryMetadataSource([self.paper])

    def test_supported_end_to_end(self):
        candidate = parse_citation(title="Method M for Task T", year=2024)
        result = check_claim_support("Method M improves task T.", candidate, self.source, backend=_FakeEnsembleBackend())
        self.assertEqual(result.verdict, SupportVerdict.SUPPORTED)
        self.assertEqual(result.resolution["verdict"], "matched")

    def test_matched_support_confidence_is_reduced_by_partial_source_outage(self):
        diagnostic_paper = CitationRecord(
            citation_id=self.paper.citation_id,
            title=self.paper.title,
            abstract=self.paper.abstract,
            authors=list(self.paper.authors),
            year=self.paper.year,
            source="diagnostic_source",
        )
        candidate = parse_citation(title="Method M for Task T", doi="10.1000/method-m")
        result = check_claim_support(
            "Method M improves task T.",
            candidate,
            _LookupFailureThenSearchSuccessSource(diagnostic_paper),
            backend=_StrongSupportBackend(),
        )

        self.assertEqual(result.verdict, SupportVerdict.SUPPORTED)
        self.assertEqual(result.confidence, 0.85)
        self.assertEqual(result.resolution["source_failure_mode"], "partial_outage")
        self.assertEqual(result.resolution["sources_failed"], ["diagnostic_source"])
        self.assertEqual(result.resolution["source_failure_details"][0]["code"], "source_unavailable")
        self.assertEqual(result.resolution["source_failure_details"][0]["kind"], "rate_limited")
        self.assertEqual(result.resolution["source_failure_details"][0]["attempt_count"], 2)
        self.assertEqual(result.resolution["source_failure_details"][0]["retry_count"], 1)
        self.assertEqual(result.resolution["source_failure_details"][0]["retry_after_seconds"], 2.0)
        self.assertEqual(result.resolution["source_failure_details"][0]["retry_delay_seconds"], 1.5)
        self.assertIn("Confidence is reduced", result.explanation)

    def test_unresolved_paper_is_insufficient_not_unsupported(self):
        candidate = parse_citation(title="A Paper That Does Not Exist Anywhere")
        result = check_claim_support("Some claim.", candidate, self.source, backend=_FakeEnsembleBackend())
        self.assertEqual(result.verdict, SupportVerdict.INSUFFICIENT_EVIDENCE)
        self.assertEqual(result.resolution["verdict"], "not_found")
        self.assertEqual(result.resolution["source_failure_mode"], "none")
        self.assertEqual(result.resolution["sources_available"], ["metadata_source"])
        self.assertFalse(result.resolution["outage_limited"])

    def test_unresolved_support_exposes_source_outage_status(self):
        candidate = parse_citation(title="Slow Source Paper")
        result = check_claim_support("Some claim.", candidate, _FailingMetadataSource(), backend=_FakeEnsembleBackend())

        self.assertEqual(result.verdict, SupportVerdict.INSUFFICIENT_EVIDENCE)
        self.assertEqual(result.resolution["verdict"], "not_found")
        self.assertEqual(result.resolution["source_failure_mode"], "all_sources_failed")
        self.assertTrue(result.resolution["outage_limited"])
        self.assertEqual(result.resolution["sources_available"], [])
        self.assertEqual(result.resolution["sources_failed"], ["timeout_source"])
        self.assertEqual(result.resolution["source_failure_details"][0]["code"], "timeout")
        self.assertEqual(result.resolution["recovery_code"], "timeout")
        self.assertIn("inconclusive", result.explanation)

    def test_user_provided_full_text_excerpt_survives_resolution(self):
        paper = CitationRecord(
            citation_id="p3",
            title="Sparse Retrieval for Citation Auditing",
            authors=["A. Author"],
            year=2025,
            source="memory",
        )
        candidate = parse_citation(
            title="Sparse Retrieval for Citation Auditing",
            year=2025,
            evidence_chunks=[
                {
                    "text": "The lawful full-text excerpt shows sparse retrieval improves citation audit recall.",
                    "source_field": "user_full_text_excerpt_1",
                    "evidence_scope": "full_text",
                }
            ],
        )

        result = check_claim_support(
            "Sparse retrieval improves citation audit recall.",
            candidate,
            InMemoryMetadataSource([paper]),
            backend=_FullTextOnlyBackend(),
        )

        self.assertEqual(result.verdict, SupportVerdict.SUPPORTED)
        self.assertEqual(result.evidence_scope, "full_text")
        self.assertEqual(result.evidence["source_field"], "user_full_text_excerpt_1")

    def test_audit_claim_support_summarizes_batch(self):
        report = audit_claim_support(
            [
                ClaimSupportRequest(
                    claim="Method M improves task T.",
                    citation=parse_citation(title="Method M for Task T", year=2024),
                    lang="en",
                ),
                ClaimSupportRequest(
                    claim="Unknown paper supports a claim.",
                    citation=parse_citation(title="A Paper That Does Not Exist Anywhere"),
                ),
            ],
            self.source,
            backend=_FakeEnsembleBackend(),
        )

        self.assertIsInstance(report, SupportAuditReport)
        self.assertEqual(report.summary["supported"], 1)
        self.assertEqual(report.summary["insufficient_evidence"], 1)
        self.assertEqual(report.results[0].lang, "en")
        self.assertEqual(report.risk_ranking[0]["risk"], "high")
        self.assertEqual(report.risk_ranking[0]["resolution"]["verdict"], "not_found")
        self.assertEqual(report.risk_ranking[0]["resolution"]["source_failure_mode"], "none")
        self.assertEqual(report.risk_ranking[0]["support_confidence"], 0.0)
        self.assertEqual(report.risk_ranking[0]["support_engine"], "none")
        self.assertEqual(report.risk_ranking[0]["resolution_verdict"], "not_found")
        self.assertEqual(report.risk_ranking[0]["resolved_title"], "")
        self.assertEqual(report.risk_ranking[0]["evidence_source_field"], "none")
        self.assertEqual(report.risk_ranking[0]["evidence_source_name"], "none")
        self.assertEqual(report.risk_ranking[1]["support_engine"], "ensemble")
        self.assertEqual(report.risk_ranking[1]["resolution_verdict"], "matched")
        self.assertEqual(report.risk_ranking[1]["resolved_title"], "Method M for Task T")
        self.assertEqual(report.risk_ranking[1]["evidence_source_field"], "abstract_sentence_1")
        self.assertEqual(report.risk_ranking[1]["evidence_source_name"], "memory")
        self.assertTrue(report.risk_ranking[0]["counterevidence_review"])
        self.assertEqual(report.risk_ranking[0]["counterevidence_reason"], "unresolved_citation")
        self.assertTrue(report.results[1].to_dict()["counterevidence_review"])
        self.assertIn("recommendation", report.to_dict()["risk_ranking"][0])
        review_summary = report.to_dict()["review_summary"]
        self.assertEqual(review_summary["total"], 2)
        self.assertEqual(review_summary["high_risk_count"], 1)
        self.assertEqual(review_summary["low_risk_count"], 1)
        self.assertEqual(review_summary["next_actions"]["resolve_citation_identity"], 1)
        self.assertEqual(review_summary["next_actions"]["keep_claim"], 1)
        self.assertEqual(review_summary["top_high_risk_indexes"], [1])
        self.assertEqual(review_summary["top_risk_indexes"], [1, 0])
        self.assertEqual(review_summary["action_queues"]["identity_resolution_indexes"], [1])
        self.assertEqual(review_summary["action_queues"]["safe_to_keep_indexes"], [0])
        self.assertEqual(review_summary["action_queues"]["evidence_review_indexes"], [])
        self.assertEqual(review_summary["recommended_next_steps"]["first_queue"], "identity_resolution_indexes")
        self.assertEqual(review_summary["recommended_next_steps"]["first_action"], "resolve_identity")
        self.assertEqual(review_summary["triage_plan"]["next_action"], "resolve_citation_identity")
        self.assertEqual(review_summary["triage_plan"]["first_queue"], "identity_resolution_indexes")
        self.assertEqual(
            review_summary["recommended_next_steps"]["steps"],
            [
                {
                    "priority": 3,
                    "action": "resolve_identity",
                    "queue": "identity_resolution_indexes",
                    "count": 1,
                    "indexes": [1],
                }
            ],
        )
        self.assertEqual(review_summary["recommended_next_steps"]["safe_to_keep_indexes"], [0])

    def test_audit_claim_support_flags_contradicted_for_counterevidence_review(self):
        contradictory = CitationRecord(
            citation_id="p2",
            title="Method M for Task T",
            abstract="We show method M does not improve task T accuracy.",
            authors=["A. Author"],
            year=2024,
            source="memory",
        )
        report = audit_claim_support(
            [
                ClaimSupportRequest(
                    claim="Method M improves task T.",
                    citation=parse_citation(title="Method M for Task T", year=2024),
                )
            ],
            InMemoryMetadataSource([contradictory]),
            backend=_ContradictingBackend(),
        )

        self.assertEqual(report.results[0].verdict, SupportVerdict.CONTRADICTED)
        self.assertTrue(report.risk_ranking[0]["counterevidence_review"])
        self.assertEqual(report.risk_ranking[0]["counterevidence_reason"], "contradicted")
        self.assertIn("contradicts", report.results[0].to_dict()["counterevidence_recommendation"])

    def test_search_counterevidence_candidates_returns_review_leads_only(self):
        contradictory = CitationRecord(
            citation_id="p2",
            title="Method M Does Not Improve Task T",
            abstract="We show method M does not improve task T accuracy.",
            authors=["A. Author"],
            year=2024,
            source="memory",
        )
        source = InMemoryMetadataSource([self.paper, contradictory])

        report = search_counterevidence_candidates("Method M improves task T.", source, top_k=2)
        payload = report.to_dict()

        self.assertEqual(payload["claim"], "Method M improves task T.")
        self.assertGreaterEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["candidates"][0]["title"], "Method M Does Not Improve Task T")
        self.assertEqual(payload["candidates"][0]["signal"], "explicit_contradiction_cue")
        self.assertEqual(payload["query_plan"][0]["role"], "claim_similarity")
        self.assertIn("improvement_negation", {item["role"] for item in payload["query_plan"]})
        self.assertEqual(len(payload["query_results"]), len(payload["queries"]))
        self.assertIn("improvement_negation", payload["candidates"][0]["matched_query_roles"])
        self.assertTrue(payload["candidates"][0]["matched_queries"])
        self.assertEqual(payload["review_summary"]["candidate_count"], payload["candidate_count"])
        self.assertEqual(payload["review_summary"]["signal_counts"]["explicit_contradiction_cue"], 1)
        self.assertGreaterEqual(payload["review_summary"]["matched_query_role_counts"]["improvement_negation"], 1)
        self.assertEqual(payload["review_summary"]["top_candidate"]["title"], "Method M Does Not Improve Task T")
        self.assertEqual(
            payload["review_summary"]["recommended_next_steps"]["first_action"],
            "review_explicit_contradiction_leads",
        )
        self.assertEqual(
            payload["review_summary"]["recommended_next_steps"]["explicit_contradiction_candidate_indexes"],
            [0],
        )
        self.assertEqual(
            payload["review_summary"]["recommended_next_steps"]["queue_order"][0],
            "explicit_contradiction_candidate_indexes",
        )
        self.assertIn(
            "related_candidate_indexes",
            payload["review_summary"]["recommended_next_steps"]["queue_order"],
        )
        self.assertEqual(payload["review_summary"]["policy"], "review_leads_not_contradiction_verdicts")
        self.assertIn("review leads", payload["interpretation"])
        self.assertEqual(payload["source_failure_mode"], "none")
        self.assertEqual(payload["sources_available"], ["metadata_source"])
        self.assertEqual(payload["next_action"], "review_counterevidence_leads")

    def test_search_counterevidence_candidates_flags_source_outage_safety_leads(self):
        safety_record = CitationRecord(
            citation_id="source-outage-safety",
            title="Source Outages Are Not Fabrication Evidence",
            abstract=(
                "Source outages and not_found results lower confidence and are not evidence "
                "that a citation is fabricated."
            ),
            authors=["A. Auditor"],
            year=2026,
            source="memory",
        )
        source = InMemoryMetadataSource([self.paper, safety_record])

        report = search_counterevidence_candidates(
            "A source outage increases confidence that a citation is fabricated.",
            source,
            top_k=1,
        )
        payload = report.to_dict()

        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["candidates"][0]["title"], "Source Outages Are Not Fabrication Evidence")
        self.assertEqual(payload["candidates"][0]["signal"], "source_outage_safety_cue")
        self.assertIn("source_outage_safety", {item["role"] for item in payload["query_plan"]})
        self.assertIn("source_outage_safety", payload["candidates"][0]["matched_query_roles"])
        self.assertEqual(payload["review_summary"]["signal_counts"]["source_outage_safety_cue"], 1)
        self.assertEqual(payload["review_summary"]["top_candidate"]["signal"], "source_outage_safety_cue")
        self.assertEqual(
            payload["review_summary"]["recommended_next_steps"]["first_action"],
            "review_source_outage_safety_leads",
        )
        self.assertEqual(
            payload["review_summary"]["recommended_next_steps"]["source_outage_safety_candidate_indexes"],
            [0],
        )
        self.assertIn("not_found results lower confidence", payload["candidates"][0]["abstract_snippet"])
        self.assertEqual(payload["next_action"], "review_counterevidence_leads")

    def test_search_counterevidence_candidates_flags_chinese_source_outage_safety_leads(self):
        safety_record = CitationRecord(
            citation_id="zh-source-outage-safety",
            title="源不可达不能证明引用伪造",
            abstract=(
                "源不可达和未找到结果只会降低核验置信度，不能证明引用是伪造的，"
                "应检查来源健康或稍后重试。"
            ),
            authors=["A. Auditor"],
            year=2026,
            source="memory",
        )
        source = InMemoryMetadataSource([self.paper, safety_record])

        report = search_counterevidence_candidates(
            "源不可达会提高引用被判定为伪造的置信度。",
            source,
            top_k=1,
        )
        payload = report.to_dict()

        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["candidates"][0]["title"], "源不可达不能证明引用伪造")
        self.assertEqual(payload["candidates"][0]["signal"], "source_outage_safety_cue")
        self.assertIn("source_outage_safety", {item["role"] for item in payload["query_plan"]})
        self.assertIn("source_outage_safety", payload["candidates"][0]["matched_query_roles"])
        self.assertIn("不能证明引用是伪造的", payload["candidates"][0]["abstract_snippet"])
        self.assertEqual(payload["next_action"], "review_counterevidence_leads")

    def test_search_counterevidence_candidates_reports_source_outage(self):
        report = search_counterevidence_candidates("Method M improves task T.", _FailingMetadataSource())
        payload = report.to_dict()

        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(payload["source_failure_mode"], "all_sources_failed")
        self.assertTrue(payload["outage_limited"])
        self.assertEqual(payload["sources_available"], [])
        self.assertEqual(payload["sources_failed"], ["timeout_source"])
        self.assertEqual(payload["source_failure_details"][0]["code"], "timeout")
        self.assertEqual(payload["recovery_code"], "timeout")
        self.assertEqual(payload["next_action"], "retry_or_check_source_health")
        self.assertEqual(payload["review_summary"]["recommended_next_steps"]["status"], "source_retry")
        self.assertEqual(
            payload["review_summary"]["recommended_next_steps"]["first_action"],
            "retry_or_check_source_health",
        )
        self.assertEqual(
            payload["review_summary"]["recommended_next_steps"]["source_retry_sources"],
            ["timeout_source"],
        )
        self.assertEqual(len(payload["query_results"]), len(payload["queries"]))
        self.assertTrue(all(item["source_failure_mode"] == "all_sources_failed" for item in payload["query_results"]))

    def test_search_counterevidence_candidates_continues_when_no_leads_and_sources_ok(self):
        source = InMemoryMetadataSource([])

        report = search_counterevidence_candidates("Method M improves task T.", source, top_k=2)
        payload = report.to_dict()

        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(payload["source_failure_mode"], "none")
        self.assertFalse(payload["outage_limited"])
        self.assertEqual(payload["next_action"], "continue")
        self.assertEqual(payload["review_summary"]["recommended_next_steps"]["status"], "clear")
        self.assertEqual(payload["review_summary"]["recommended_next_steps"]["first_action"], "continue")

    def test_counterevidence_reports_single_source_http_failure_diagnostics(self):
        report = search_counterevidence_candidates(
            "Method M improves task T.",
            _HTTPFailingCounterEvidenceSource([self.paper]),
        )
        payload = report.to_dict()

        self.assertEqual(payload["candidate_count"], 0)
        self.assertEqual(payload["source_failure_mode"], "all_sources_failed")
        self.assertEqual(payload["sources_failed"], ["diagnostic_source"])
        self.assertEqual(payload["source_failure_details"][0]["code"], "source_unavailable")
        self.assertEqual(payload["source_failure_details"][0]["kind"], "rate_limited")
        self.assertEqual(payload["source_failure_details"][0]["status_code"], 429)
        self.assertEqual(payload["source_failure_details"][0]["retry_after_seconds"], 2.0)
        self.assertEqual(payload["source_failure_details"][0]["retry_delay_seconds"], 1.5)
        self.assertTrue(all(item["sources_failed"] == ["diagnostic_source"] for item in payload["query_results"]))

    def test_enrich_support_payload_adds_counterevidence_only_for_review_items(self):
        source = InMemoryMetadataSource(
            [
                self.paper,
                CitationRecord(
                    citation_id="p2",
                    title="Method M Does Not Improve Task T",
                    abstract="We show method M does not improve task T accuracy.",
                    year=2024,
                    source="memory",
                ),
            ]
        )
        report = audit_claim_support(
            [
                ClaimSupportRequest(
                    claim="Method M improves task T.",
                    citation=parse_citation(title="Method M for Task T", year=2024),
                ),
                ClaimSupportRequest(
                    claim="Method M improves task T.",
                    citation=parse_citation(title="A Paper That Does Not Exist Anywhere"),
                ),
            ],
            source,
            backend=_FakeEnsembleBackend(),
        )

        enriched = enrich_support_payload_with_counterevidence(report.to_dict(), source, top_k=1)

        self.assertTrue(enriched["counterevidence_included"])
        self.assertNotIn("counterevidence", enriched["results"][0])
        self.assertIn("counterevidence", enriched["results"][1])
        self.assertEqual(enriched["results"][1]["counterevidence"]["candidate_count"], 1)
        self.assertEqual(enriched["risk_ranking"][0]["counterevidence"]["candidate_count"], 1)

    def test_check_claim_support_set_aggregates_many_citations_for_one_claim(self):
        result = check_claim_support_set(
            "Method M improves task T.",
            [
                parse_citation(title="A Paper That Does Not Exist Anywhere"),
                parse_citation(title="Method M for Task T", year=2024),
            ],
            self.source,
            backend=_FakeEnsembleBackend(),
            lang="en",
        )

        self.assertIsInstance(result, ClaimSupportSetResult)
        self.assertEqual(result.verdict, SupportVerdict.SUPPORTED)
        self.assertEqual(result.summary["supported"], 1)
        self.assertEqual(result.summary["insufficient_evidence"], 1)
        self.assertEqual(result.risk, "low")
        self.assertEqual(result.lang, "en")
        self.assertEqual(result.evidence_scope, "abstract")
        self.assertEqual(result.support_mode, "single_strong_support")
        self.assertEqual(result.supporting_citation_count, 1)
        self.assertEqual(result.contradicting_citation_count, 0)
        self.assertEqual(result.to_dict()["next_action"], "keep_claim")
        self.assertFalse(result.to_dict()["counterevidence_review"])
        self.assertTrue(result.evidence)
        self.assertEqual(result.to_dict()["evidence"][0]["evidence_scope"], "abstract")
        self.assertEqual(result.to_dict()["evidence"][0]["index"], 1)
        self.assertEqual(result.to_dict()["evidence_scopes"], ["none", "abstract"])
        self.assertEqual(result.to_dict()["evidence_source_names"], ["none", "memory"])
        self.assertEqual(result.to_dict()["evidence_source_fields"], ["none", "abstract_sentence_1"])

    def test_claim_support_set_keeps_multiple_weak_support_tentative(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="p2",
                    title="Method M for Task T",
                    abstract="Method M and task T are evaluated.",
                    year=2024,
                    source="memory",
                ),
                CitationRecord(
                    citation_id="p3",
                    title="Task T Evaluation with Method M",
                    abstract="Task T evaluation includes method M.",
                    year=2025,
                    source="memory",
                ),
            ]
        )
        result = check_claim_support_set(
            "Method M improves task T.",
            [
                parse_citation(title="Method M for Task T", year=2024),
                parse_citation(title="Task T Evaluation with Method M", year=2025),
            ],
            source,
            backend=_WeakOnlyBackend(),
        )

        payload = result.to_dict()
        self.assertEqual(payload["verdict"], "weakly_supported")
        self.assertEqual(payload["support_mode"], "multiple_weak_support")
        self.assertEqual(payload["supporting_citation_count"], 2)
        self.assertEqual(payload["contradicting_citation_count"], 0)
        self.assertEqual(payload["next_action"], "tighten_claim_or_inspect_full_text")
        self.assertEqual([item["index"] for item in payload["evidence"]], [0, 1])
        self.assertTrue(payload["counterevidence_review"])

    def test_claim_support_set_recommends_counterevidence_review_when_contradicted(self):
        contradictory = CitationRecord(
            citation_id="p2",
            title="Method M for Task T",
            abstract="We show method M does not improve task T accuracy.",
            authors=["A. Author"],
            year=2024,
            source="memory",
        )
        result = check_claim_support_set(
            "Method M improves task T.",
            [parse_citation(title="Method M for Task T", year=2024)],
            InMemoryMetadataSource([contradictory]),
            backend=_ContradictingBackend(),
        )

        payload = result.to_dict()
        self.assertEqual(payload["verdict"], "contradicted")
        self.assertEqual(payload["support_mode"], "contradiction_dominates")
        self.assertEqual(payload["contradicting_citation_count"], 1)
        self.assertEqual(payload["next_action"], "rewrite_or_replace_evidence")
        self.assertTrue(payload["counterevidence_review"])
        self.assertEqual(payload["counterevidence_reason"], "contradicted")

    def test_audit_claim_support_accepts_mixed_single_and_citation_set_items(self):
        report = audit_claim_support(
            [
                ClaimSupportAuditItem(
                    claim="Method M improves task T.",
                    citations=[
                        parse_citation(title="Method M for Task T", year=2024),
                        parse_citation(title="A Paper That Does Not Exist Anywhere"),
                    ],
                    input_mode="citation_set",
                ),
                ClaimSupportRequest(
                    claim="Unknown paper supports a claim.",
                    citation=parse_citation(title="A Paper That Does Not Exist Anywhere"),
                ),
            ],
            self.source,
            backend=_FakeEnsembleBackend(),
        )

        payload = report.to_dict()
        self.assertIsInstance(report, SupportAuditReport)
        self.assertEqual(payload["summary"]["supported"], 1)
        self.assertEqual(payload["summary"]["insufficient_evidence"], 1)
        self.assertEqual(payload["results"][0]["input_mode"], "citation_set")
        self.assertEqual(payload["results"][0]["support_mode"], "single_strong_support")
        self.assertEqual(payload["results"][0]["evidence_scopes"], ["abstract", "none"])
        self.assertEqual(payload["results"][0]["evidence_source_names"], ["memory", "none"])
        self.assertEqual(payload["results"][0]["evidence_source_fields"], ["abstract_sentence_1", "none"])
        self.assertEqual(payload["results"][1]["input_mode"], "citation")
        self.assertEqual(payload["risk_ranking"][0]["input_mode"], "citation")
        self.assertEqual(payload["risk_ranking"][1]["input_mode"], "citation_set")
        self.assertEqual(payload["risk_ranking"][1]["evidence_scopes"], ["abstract", "none"])
        self.assertEqual(payload["risk_ranking"][1]["evidence_source_names"], ["memory", "none"])
        self.assertEqual(payload["risk_ranking"][1]["evidence_source_fields"], ["abstract_sentence_1", "none"])
        self.assertEqual(payload["review_summary"]["total"], 2)
        self.assertEqual(payload["review_summary"]["high_risk_count"], 1)
        self.assertEqual(payload["review_summary"]["low_risk_count"], 1)

    def test_unresolved_support_has_none_evidence_scope(self):
        candidate = parse_citation(title="A Paper That Does Not Exist Anywhere")
        result = check_claim_support("Some claim.", candidate, self.source, backend=_FakeEnsembleBackend())

        self.assertEqual(result.evidence_scope, "none")
        self.assertEqual(result.to_dict()["evidence_scope"], "none")
        self.assertEqual(result.evidence["evidence_scope"], "none")


class SupportExportTests(unittest.TestCase):
    def test_support_api_exported_from_package(self):
        from citeguard.verification import (
            DEFAULT_SUPPORT_POLICY,
            ClaimSupportAuditItem,
            ClaimSupportRequest,
            SupportDecisionPolicy,
            SupportAuditReport,
            ClaimSupportSetResult,
            CounterEvidenceSearchReport,
            SupportResult,
            SupportVerdict,
            assess_support,
            audit_claim_support,
            check_claim_support,
            check_claim_support_set,
            enrich_support_payload_with_counterevidence,
            search_counterevidence_candidates,
        )
        self.assertTrue(callable(audit_claim_support))
        self.assertTrue(callable(check_claim_support))
        self.assertTrue(callable(check_claim_support_set))
        self.assertTrue(callable(enrich_support_payload_with_counterevidence))
        self.assertTrue(callable(search_counterevidence_candidates))
        self.assertTrue(callable(assess_support))
        self.assertEqual(SupportVerdict.SUPPORTED.value, "supported")
        self.assertIsInstance(DEFAULT_SUPPORT_POLICY, SupportDecisionPolicy)
        self.assertTrue(hasattr(ClaimSupportRequest, "__dataclass_fields__"))
        self.assertTrue(hasattr(ClaimSupportAuditItem, "__dataclass_fields__"))
        self.assertTrue(hasattr(SupportAuditReport, "to_dict"))
        self.assertTrue(hasattr(ClaimSupportSetResult, "to_dict"))
        self.assertTrue(hasattr(CounterEvidenceSearchReport, "to_dict"))
        self.assertTrue(hasattr(SupportResult, "to_dict"))


if __name__ == "__main__":
    unittest.main()
