"""Tests for the optional MCP server helpers without requiring the mcp extra."""

from __future__ import annotations

import importlib
import inspect
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from citeguard.verification import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.runtime import canonical_source_names, ensure_cache_parent
from citeguard.verification import SupportAssessment


class EntailingSupportBackend:
    def assess(self, claim_text, evidence_text):
        return SupportAssessment(
            backend_name="transformers_nli",
            score=0.9,
            passed=True,
            rationale="Fake entailment for MCP testing.",
            details={
                "probabilities": {
                    "entailment": 0.9,
                    "contradiction": 0.02,
                    "neutral": 0.08,
                }
            },
        )


class FullTextOnlySupportBackend:
    def assess(self, claim_text, evidence_text):
        if "lawful full-text excerpt" in evidence_text:
            probs = {"entailment": 0.92, "contradiction": 0.02, "neutral": 0.06}
            return SupportAssessment(
                backend_name="transformers_nli",
                score=0.92,
                passed=True,
                rationale="Full-text excerpt entails the claim.",
                details={"probabilities": probs},
            )
        return SupportAssessment(
            backend_name="transformers_nli",
            score=0.04,
            passed=False,
            rationale="No full-text evidence.",
            details={"probabilities": {"entailment": 0.04, "contradiction": 0.04, "neutral": 0.92}},
        )


class FakeFastMCP:
    def __init__(self, name):
        self.name = name
        self.tools = []

    def tool(self):
        def decorator(func):
            self.tools.append(func.__name__)
            return func

        return decorator

    def run(self):
        return None


def import_server_with_fake_mcp():
    fastmcp_module = types.ModuleType("mcp.server.fastmcp")
    fastmcp_module.FastMCP = FakeFastMCP
    server_module = types.ModuleType("mcp.server")
    server_module.fastmcp = fastmcp_module
    root_module = types.ModuleType("mcp")
    root_module.server = server_module

    with mock.patch.dict(
        sys.modules,
        {
            "mcp": root_module,
            "mcp.server": server_module,
            "mcp.server.fastmcp": fastmcp_module,
        },
    ):
        _clear_mcp_server_modules()
        return importlib.import_module("citeguard.mcp.server")


def _clear_mcp_server_modules():
    for name in list(sys.modules):
        if name == "citeguard.mcp.server" or name.endswith(".mcp_server.server"):
            sys.modules.pop(name, None)


class MCPServerHelperTests(unittest.TestCase):
    def setUp(self):
        self.server = import_server_with_fake_mcp()

    def tearDown(self):
        _clear_mcp_server_modules()

    def test_batch_tool_metadata_documents_high_risk_filtering(self):
        for tool_name in ("audit_citations_tool", "audit_claim_support_tool"):
            with self.subTest(tool=tool_name):
                tool = getattr(self.server, tool_name)
                signature = inspect.signature(tool)
                doc = inspect.getdoc(tool) or ""

                self.assertIn("high_risk_only", signature.parameters)
                self.assertEqual(signature.parameters["high_risk_only"].default, False)
                self.assertIn("high_risk_only=true", doc)
                self.assertIn("filtered.returned_indexes", doc)
                self.assertIn("filtered.omitted_indexes", doc)

    def test_status_tool_reports_default_configuration_without_live_queries(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            status = self.server.citeguard_status_tool()

        self.assertEqual(status["service"], "CiteGuard")
        self.assertEqual(status["transport"], "stdio")
        self.assertEqual(status["configured_sources"], ["openalex", "crossref", "arxiv"])
        self.assertIn("mcp_sdk_available", status)
        self.assertIn("python_mcp_compatible", status)
        self.assertFalse(status["mailto_configured"])
        self.assertIn("support_models", status)
        self.assertIn("warnings", status)

    def test_status_tool_can_request_live_source_probe(self):
        status = mock.Mock(
            return_value={
                "service": "CiteGuard",
                "source_health": {
                    "live_check_performed": True,
                    "health_query": "Custom Probe Paper",
                    "sources": [],
                },
            }
        )

        with mock.patch.object(self.server, "environment_status", status):
            payload = self.server.citeguard_status_tool(
                check_sources=True,
                health_query="Custom Probe Paper",
            )

        status.assert_called_once_with(
            mcp_sdk_available=True,
            check_sources=True,
            health_query="Custom Probe Paper",
        )
        self.assertTrue(payload["source_health"]["live_check_performed"])
        self.assertEqual(payload["source_health"]["health_query"], "Custom Probe Paper")

    def test_source_aliases_are_canonicalized_and_deduplicated(self):
        names = canonical_source_names(["OpenAlex", "s2", "semantic-scholar", "arxiv"])
        self.assertEqual(names, ["openalex", "semantic_scholar", "arxiv"])

    def test_unknown_source_is_reported_by_status_tool(self):
        with mock.patch.dict(os.environ, {"CITEGUARD_SOURCES": "openalex,not-a-source"}, clear=True):
            status = self.server.citeguard_status_tool()

        self.assertEqual(status["configured_sources"], [])
        self.assertTrue(any("Unknown CITEGUARD_SOURCES" in warning for warning in status["warnings"]))

    def test_cache_parent_is_created_for_sqlite_cache(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_path = os.path.join(tmpdir, "nested", "cache.sqlite")
            self.assertFalse(os.path.exists(os.path.dirname(cache_path)))

            ensure_cache_parent(cache_path)

            self.assertTrue(os.path.isdir(os.path.dirname(cache_path)))

    def test_cache_parent_creation_skips_memory_cache(self):
        ensure_cache_parent(":memory:")

    def test_audit_citations_tool_returns_review_summary(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-1",
                    title="GhostCite: A Large-Scale Analysis of Citation Validity",
                    abstract="GhostCite studies citation validity in generated references.",
                    year=2026,
                    source="memory",
                )
            ]
        )
        with mock.patch.object(self.server, "_source", return_value=source):
            report = self.server.audit_citations_tool(
                [
                    {
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                        "year": 2026,
                    },
                    {
                        "title": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks",
                    },
                ]
            )

        self.assertEqual(report["summary"]["verified"], 1)
        self.assertEqual(report["summary"]["not_found"], 1)
        self.assertEqual(report["review_summary"]["total"], 2)
        self.assertEqual(report["review_summary"]["high_risk_count"], 1)
        self.assertEqual(report["review_summary"]["low_risk_count"], 1)
        self.assertEqual(report["review_summary"]["top_high_risk_indexes"], [1])
        self.assertEqual(report["review_summary"]["next_actions"]["keep"], 1)
        self.assertEqual(report["review_summary"]["next_actions"]["resolve_identifier_or_replace"], 1)
        self.assertEqual(report["review_summary"]["action_queues"]["safe_to_keep_indexes"], [0])
        self.assertEqual(report["review_summary"]["action_queues"]["identity_resolution_indexes"], [1])

    def test_audit_citations_tool_risk_ranking_includes_suggested_metadata_fix(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-1",
                    title="GhostCite: A Large-Scale Analysis of Citation Validity",
                    authors=["Zhe Xu", "Lin Wang"],
                    abstract="GhostCite studies citation validity in generated references.",
                    year=2026,
                    venue="arXiv",
                    doi="10.48550/arxiv.2602.06718",
                    source="memory",
                )
            ]
        )
        with mock.patch.object(self.server, "_source", return_value=source):
            report = self.server.audit_citations_tool(
                [
                    {
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                        "authors": ["Zhe Xu"],
                        "year": 2024,
                        "venue": "Journal of Imaginary Methods",
                    },
                ]
            )

        risk_item = report["risk_ranking"][0]
        self.assertEqual(risk_item["verdict"], "metadata_mismatch")
        self.assertEqual(risk_item["next_action"], "review_metadata")
        self.assertEqual(risk_item["mismatched_fields"], ["year", "venue"])
        self.assertIn("GhostCite: A Large-Scale Analysis of Citation Validity", risk_item["suggested_citation"])
        self.assertEqual(risk_item["canonical_year"], 2026)
        self.assertEqual(risk_item["canonical_venue"], "arXiv")

    def test_audit_citations_tool_can_filter_high_risk_only(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-1",
                    title="GhostCite: A Large-Scale Analysis of Citation Validity",
                    abstract="GhostCite studies citation validity in generated references.",
                    year=2026,
                    source="memory",
                )
            ]
        )
        with mock.patch.object(self.server, "_source", return_value=source):
            report = self.server.audit_citations_tool(
                [
                    {
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                        "year": 2026,
                    },
                    {
                        "title": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks",
                    },
                ],
                high_risk_only=True,
            )

        self.assertEqual(report["filtered"]["returned_indexes"], [1])
        self.assertEqual(report["filtered"]["omitted_indexes"], [0])
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["verdict"], "not_found")
        self.assertEqual(report["review_summary"]["total"], 2)

    def test_audit_claim_support_tool_summarizes_batch(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-1",
                    title="GhostCite: A Large-Scale Analysis of Citation Validity",
                    abstract="GhostCite studies citation validity in generated references.",
                    year=2026,
                    source="memory",
                )
            ]
        )
        with mock.patch.object(self.server, "_source", return_value=source), mock.patch.object(
            self.server, "_support_backend", return_value=EntailingSupportBackend()
        ):
            report = self.server.audit_claim_support_tool(
                [
                    {
                        "claim": "GhostCite studies citation validity.",
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                    },
                    {
                        "claim": "An unknown paper supports a claim.",
                        "title": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks",
                    },
                ],
                lang="en",
            )

        self.assertEqual(report["summary"]["supported"], 1)
        self.assertEqual(report["summary"]["insufficient_evidence"], 1)
        self.assertEqual(report["results"][0]["resolution"]["verdict"], "matched")
        self.assertEqual(report["review_summary"]["total"], 2)
        self.assertEqual(report["review_summary"]["high_risk_count"], 1)
        self.assertEqual(report["review_summary"]["low_risk_count"], 1)
        self.assertEqual(report["review_summary"]["top_high_risk_indexes"], [1])
        self.assertEqual(report["review_summary"]["next_actions"]["resolve_citation_identity"], 1)
        self.assertEqual(report["review_summary"]["next_actions"]["keep_claim"], 1)
        self.assertEqual(report["review_summary"]["action_queues"]["safe_to_keep_indexes"], [0])
        self.assertEqual(report["review_summary"]["action_queues"]["identity_resolution_indexes"], [1])
        self.assertTrue(report["risk_ranking"][0]["counterevidence_review"])
        self.assertEqual(report["risk_ranking"][0]["counterevidence_reason"], "unresolved_citation")
        self.assertEqual(report["risk_ranking"][0]["next_action"], "resolve_citation_identity")
        self.assertEqual(report["risk_ranking"][0]["support_confidence"], 0.0)
        self.assertEqual(report["risk_ranking"][0]["support_engine"], "none")
        self.assertEqual(report["risk_ranking"][0]["resolution_verdict"], "not_found")
        self.assertEqual(report["risk_ranking"][0]["resolved_title"], "")
        self.assertEqual(report["risk_ranking"][0]["evidence_source_field"], "none")
        self.assertEqual(report["risk_ranking"][1]["support_engine"], "ensemble")
        self.assertEqual(report["risk_ranking"][1]["resolution_verdict"], "matched")
        self.assertEqual(report["risk_ranking"][1]["resolved_title"], "GhostCite: A Large-Scale Analysis of Citation Validity")
        self.assertEqual(report["risk_ranking"][1]["resolved_year"], 2026)
        self.assertEqual(report["risk_ranking"][1]["evidence_source_field"], "abstract_sentence_1")

    def test_audit_claim_support_tool_can_filter_high_risk_only(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-1",
                    title="GhostCite: A Large-Scale Analysis of Citation Validity",
                    abstract="GhostCite studies citation validity in generated references.",
                    year=2026,
                    source="memory",
                )
            ]
        )
        with mock.patch.object(self.server, "_source", return_value=source), mock.patch.object(
            self.server, "_support_backend", return_value=EntailingSupportBackend()
        ):
            report = self.server.audit_claim_support_tool(
                [
                    {
                        "claim": "GhostCite studies citation validity.",
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                    },
                    {
                        "claim": "An unknown paper supports a claim.",
                        "title": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks",
                    },
                ],
                lang="en",
                high_risk_only=True,
            )

        self.assertEqual(report["filtered"]["returned_indexes"], [1])
        self.assertEqual(report["filtered"]["omitted_indexes"], [0])
        self.assertEqual(len(report["results"]), 1)
        self.assertEqual(report["results"][0]["resolution"]["verdict"], "not_found")
        self.assertEqual(report["review_summary"]["total"], 2)

    def test_audit_claim_support_tool_can_attach_counterevidence(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-1",
                    title="GhostCite Studies Citation Validity",
                    abstract="GhostCite studies citation validity in generated references.",
                    year=2026,
                    source="memory",
                ),
                CitationRecord(
                    citation_id="paper-2",
                    title="GhostCite Does Not Improve Citation Validity",
                    abstract="GhostCite does not improve citation validity in generated references.",
                    year=2026,
                    source="memory",
                ),
            ]
        )
        with mock.patch.object(self.server, "_source", return_value=source), mock.patch.object(
            self.server, "_support_backend", return_value=EntailingSupportBackend()
        ):
            report = self.server.audit_claim_support_tool(
                [
                    {
                        "claim": "GhostCite improves citation validity.",
                        "title": "A Paper That Does Not Exist Anywhere",
                    }
                ],
                include_counterevidence=True,
                counterevidence_top_k=1,
            )

        self.assertTrue(report["counterevidence_included"])
        self.assertEqual(report["results"][0]["counterevidence"]["candidate_count"], 1)
        self.assertEqual(report["risk_ranking"][0]["counterevidence"]["candidates"][0]["signal"], "explicit_contradiction_cue")

    def test_check_claim_support_set_tool_aggregates_one_claim(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-1",
                    title="GhostCite: A Large-Scale Analysis of Citation Validity",
                    abstract="GhostCite studies citation validity in generated references.",
                    year=2026,
                    source="memory",
                )
            ]
        )
        with mock.patch.object(self.server, "_source", return_value=source), mock.patch.object(
            self.server, "_support_backend", return_value=EntailingSupportBackend()
        ):
            report = self.server.check_claim_support_set_tool(
                "GhostCite studies citation validity.",
                [
                    {"title": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks"},
                    {"title": "GhostCite: A Large-Scale Analysis of Citation Validity"},
                ],
                lang="en",
            )

        self.assertEqual(report["verdict"], "supported")
        self.assertEqual(report["summary"]["supported"], 1)
        self.assertEqual(report["summary"]["insufficient_evidence"], 1)
        self.assertFalse(report["counterevidence_review"])
        self.assertEqual(report["support_mode"], "single_strong_support")
        self.assertEqual(report["next_action"], "keep_claim")
        self.assertEqual(report["supporting_citation_count"], 1)
        self.assertEqual(report["contradicting_citation_count"], 0)
        self.assertEqual(report["evidence"][0]["index"], 1)

    def test_check_claim_support_tool_accepts_full_text_excerpt(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-2",
                    title="Sparse Retrieval for Citation Auditing",
                    year=2026,
                    source="memory",
                )
            ]
        )
        with mock.patch.object(self.server, "_source", return_value=source), mock.patch.object(
            self.server, "_support_backend", return_value=FullTextOnlySupportBackend()
        ):
            report = self.server.check_claim_support_tool(
                "Sparse retrieval improves citation audit recall.",
                title="Sparse Retrieval for Citation Auditing",
                full_text=[
                    "The lawful full-text excerpt shows sparse retrieval improves citation audit recall."
                ],
            )

        self.assertEqual(report["verdict"], "supported")
        self.assertEqual(report["evidence_scope"], "full_text")
        self.assertEqual(report["next_action"], "keep_claim")
        self.assertEqual(report["evidence"]["source_field"], "user_full_text_excerpt_1")

    def test_audit_claim_support_tool_accepts_citation_set_items(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-1",
                    title="GhostCite: A Large-Scale Analysis of Citation Validity",
                    abstract="GhostCite studies citation validity in generated references.",
                    year=2026,
                    source="memory",
                ),
                CitationRecord(
                    citation_id="paper-2",
                    title="Citation Auditing with Metadata Checks",
                    abstract="Metadata checks help citation auditing workflows.",
                    year=2026,
                    source="memory",
                ),
            ]
        )
        with mock.patch.object(self.server, "_source", return_value=source), mock.patch.object(
            self.server, "_support_backend", return_value=EntailingSupportBackend()
        ):
            report = self.server.audit_claim_support_tool(
                [
                    {
                        "claim": "GhostCite studies citation validity.",
                        "citations": [
                            {"title": "GhostCite: A Large-Scale Analysis of Citation Validity"},
                            {"title": "Citation Auditing with Metadata Checks"},
                        ],
                        "lang": "en",
                    }
                ]
            )

        self.assertEqual(report["summary"]["supported"], 1)
        self.assertEqual(report["results"][0]["input_mode"], "citation_set")
        self.assertEqual(report["results"][0]["support_mode"], "multiple_strong_support")
        self.assertEqual(report["review_summary"]["total"], 1)
        self.assertEqual(report["review_summary"]["low_risk_count"], 1)
        self.assertEqual(report["review_summary"]["top_risk_indexes"], [0])
        self.assertEqual(report["review_summary"]["next_actions"]["keep_claim"], 1)
        self.assertEqual(report["risk_ranking"][0]["input_mode"], "citation_set")
        self.assertEqual(report["risk_ranking"][0]["supporting_citation_count"], 2)
        self.assertEqual(report["risk_ranking"][0]["next_action"], "keep_claim")
        self.assertEqual(report["risk_ranking"][0]["support_engine"], "citation_set")
        self.assertGreater(report["risk_ranking"][0]["support_confidence"], 0)

    def test_search_counterevidence_tool_returns_review_candidates(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-1",
                    title="GhostCite Studies Citation Validity",
                    abstract="GhostCite studies citation validity in generated references.",
                    year=2026,
                    source="memory",
                ),
                CitationRecord(
                    citation_id="paper-2",
                    title="GhostCite Does Not Improve Citation Validity",
                    abstract="GhostCite does not improve citation validity in generated references.",
                    year=2026,
                    source="memory",
                ),
            ]
        )
        with mock.patch.object(self.server, "_source", return_value=source):
            report = self.server.search_counterevidence_tool(
                "GhostCite improves citation validity.",
                top_k=1,
            )

        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["candidates"][0]["signal"], "explicit_contradiction_cue")
        self.assertIn("improvement_negation", {item["role"] for item in report["query_plan"]})
        self.assertEqual(len(report["query_results"]), len(report["queries"]))
        self.assertIn("improvement_negation", report["candidates"][0]["matched_query_roles"])
        self.assertIn("review leads", report["interpretation"])

    def test_search_counterevidence_tool_returns_source_outage_safety_candidates(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-1",
                    title="Source Outages Are Not Fabrication Evidence",
                    abstract=(
                        "Source outages and not_found results lower confidence and are not evidence "
                        "that a citation is fabricated."
                    ),
                    year=2026,
                    source="memory",
                ),
            ]
        )
        with mock.patch.object(self.server, "_source", return_value=source):
            report = self.server.search_counterevidence_tool(
                "A source outage increases confidence that a citation is fabricated.",
                top_k=1,
            )

        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["candidates"][0]["signal"], "source_outage_safety_cue")
        self.assertIn("source_outage_safety", {item["role"] for item in report["query_plan"]})
        self.assertIn("source_outage_safety", report["candidates"][0]["matched_query_roles"])
        self.assertIn("review leads", report["interpretation"])

    def test_search_counterevidence_tool_returns_chinese_source_outage_safety_candidates(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="zh-source-outage-safety",
                    title="源不可达不能证明引用伪造",
                    abstract=(
                        "源不可达和未找到结果只会降低核验置信度，不能证明引用是伪造的，"
                        "应检查来源健康或稍后重试。"
                    ),
                    year=2026,
                    source="memory",
                ),
            ]
        )
        with mock.patch.object(self.server, "_source", return_value=source):
            report = self.server.search_counterevidence_tool(
                "源不可达会提高引用被判定为伪造的置信度。",
                top_k=1,
            )

        self.assertEqual(report["candidate_count"], 1)
        self.assertEqual(report["candidates"][0]["signal"], "source_outage_safety_cue")
        self.assertIn("source_outage_safety", {item["role"] for item in report["query_plan"]})
        self.assertIn("source_outage_safety", report["candidates"][0]["matched_query_roles"])
        self.assertIn("不能证明引用是伪造的", report["candidates"][0]["abstract_snippet"])
        self.assertEqual(report["next_action"], "review_counterevidence_leads")

    def test_mcp_tools_return_structured_errors_for_expected_input_errors(self):
        missing_verify = self.server.verify_citation_tool()
        self.assertFalse(missing_verify["ok"])
        self.assertEqual(missing_verify["schema_version"], 1)
        self.assertEqual(missing_verify["error"]["code"], "missing_citation_input")
        self.assertEqual(missing_verify["error"]["details"]["tool"], "verify_citation_tool")
        self.assertIn("DOI", missing_verify["error"]["recovery"])
        self.assertEqual(missing_verify["error"]["next_action"], "provide_missing_input")

        missing_support_claim = self.server.check_claim_support_tool(claim="", title="GhostCite")
        self.assertFalse(missing_support_claim["ok"])
        self.assertEqual(missing_support_claim["error"]["code"], "missing_claim")
        self.assertIn("sentence", missing_support_claim["error"]["recovery"])
        self.assertEqual(missing_support_claim["error"]["next_action"], "provide_missing_input")

        missing_support_citation = self.server.check_claim_support_tool(claim="A claim.")
        self.assertFalse(missing_support_citation["ok"])
        self.assertEqual(missing_support_citation["error"]["code"], "missing_citation_input")
        self.assertEqual(missing_support_citation["error"]["next_action"], "provide_missing_input")

        missing_counterevidence_claim = self.server.search_counterevidence_tool(claim="")
        self.assertFalse(missing_counterevidence_claim["ok"])
        self.assertEqual(missing_counterevidence_claim["error"]["code"], "missing_claim")

        invalid_counterevidence_top_k = self.server.search_counterevidence_tool(claim="A claim.", top_k="many")
        self.assertFalse(invalid_counterevidence_top_k["ok"])
        self.assertEqual(invalid_counterevidence_top_k["error"]["code"], "invalid_input")

        invalid_audit_counterevidence_top_k = self.server.audit_claim_support_tool(
            [{"claim": "A claim.", "title": "GhostCite"}],
            include_counterevidence=True,
            counterevidence_top_k=-1,
        )
        self.assertFalse(invalid_audit_counterevidence_top_k["ok"])
        self.assertEqual(invalid_audit_counterevidence_top_k["error"]["code"], "invalid_input")
        self.assertEqual(
            invalid_audit_counterevidence_top_k["error"]["details"]["field"],
            "counterevidence_top_k",
        )

    def test_mcp_tools_return_structured_errors_for_invalid_citation_fields(self):
        invalid_authors = self.server.verify_citation_tool(title="GhostCite", authors="Zhe Xu")
        self.assertFalse(invalid_authors["ok"])
        self.assertEqual(invalid_authors["error"]["code"], "invalid_input")
        self.assertEqual(invalid_authors["error"]["details"]["tool"], "verify_citation_tool")
        self.assertEqual(invalid_authors["error"]["details"]["field"], "authors")

        invalid_year = self.server.audit_citations_tool(
            citations=[{"title": "GhostCite", "year": {"published": 2026}}]
        )
        self.assertFalse(invalid_year["ok"])
        self.assertEqual(invalid_year["error"]["code"], "invalid_input")
        self.assertEqual(invalid_year["error"]["details"]["tool"], "audit_citations_tool")
        self.assertEqual(invalid_year["error"]["details"]["index"], 1)
        self.assertEqual(invalid_year["error"]["details"]["field"], "year")

    def test_mcp_batch_tools_return_structured_errors_for_invalid_items(self):
        invalid_citations_shape = self.server.audit_citations_tool(citations="not a list")
        self.assertFalse(invalid_citations_shape["ok"])
        self.assertEqual(invalid_citations_shape["error"]["code"], "invalid_input")
        self.assertEqual(invalid_citations_shape["error"]["details"]["tool"], "audit_citations_tool")
        self.assertEqual(invalid_citations_shape["error"]["details"]["field"], "citations")
        self.assertEqual(invalid_citations_shape["error"]["details"]["expected"], "list")
        self.assertEqual(invalid_citations_shape["error"]["details"]["received"], "str")

        invalid_audit = self.server.audit_citations_tool(citations=[{"title": "GhostCite"}, "not an object"])
        self.assertFalse(invalid_audit["ok"])
        self.assertEqual(invalid_audit["error"]["code"], "invalid_input")
        self.assertEqual(invalid_audit["error"]["details"]["index"], 2)
        self.assertEqual(invalid_audit["error"]["details"]["field"], "citations")
        self.assertEqual(invalid_audit["error"]["details"]["expected"], "object")
        self.assertEqual(invalid_audit["error"]["details"]["received"], "str")

        missing_audit_citation = self.server.audit_citations_tool(citations=[{}])
        self.assertFalse(missing_audit_citation["ok"])
        self.assertEqual(missing_audit_citation["error"]["code"], "missing_citation_input")
        self.assertEqual(missing_audit_citation["error"]["details"]["index"], 1)

        missing_claim = self.server.audit_claim_support_tool([{"title": "GhostCite"}])
        self.assertFalse(missing_claim["ok"])
        self.assertEqual(missing_claim["error"]["code"], "missing_claim")
        self.assertEqual(missing_claim["error"]["details"]["index"], 1)

        missing_citation = self.server.audit_claim_support_tool([{"claim": "A claim."}])
        self.assertFalse(missing_citation["ok"])
        self.assertEqual(missing_citation["error"]["code"], "missing_citation_input")
        self.assertEqual(missing_citation["error"]["details"]["tool"], "audit_claim_support_tool")

        empty_set = self.server.check_claim_support_set_tool("A claim.", [])
        self.assertFalse(empty_set["ok"])
        self.assertEqual(empty_set["error"]["code"], "missing_citation_input")
        self.assertEqual(empty_set["error"]["details"]["tool"], "check_claim_support_set_tool")
        self.assertEqual(empty_set["error"]["details"]["field"], "citations")
        self.assertEqual(empty_set["error"]["details"]["expected"], "non_empty_list")

        invalid_set_shape = self.server.check_claim_support_set_tool("A claim.", "not a list")
        self.assertFalse(invalid_set_shape["ok"])
        self.assertEqual(invalid_set_shape["error"]["code"], "invalid_input")
        self.assertEqual(invalid_set_shape["error"]["details"]["tool"], "check_claim_support_set_tool")
        self.assertEqual(invalid_set_shape["error"]["details"]["field"], "citations")
        self.assertEqual(invalid_set_shape["error"]["details"]["expected"], "non_empty_list")
        self.assertEqual(invalid_set_shape["error"]["details"]["received"], "str")

        invalid_set_item = self.server.check_claim_support_set_tool("A claim.", ["not an object"])
        self.assertFalse(invalid_set_item["ok"])
        self.assertEqual(invalid_set_item["error"]["code"], "invalid_input")
        self.assertEqual(invalid_set_item["error"]["details"]["index"], 1)
        self.assertEqual(invalid_set_item["error"]["details"]["field"], "citations")
        self.assertEqual(invalid_set_item["error"]["details"]["expected"], "object")
        self.assertEqual(invalid_set_item["error"]["details"]["received"], "str")

        invalid_support_items_shape = self.server.audit_claim_support_tool("not a list")
        self.assertFalse(invalid_support_items_shape["ok"])
        self.assertEqual(invalid_support_items_shape["error"]["code"], "invalid_input")
        self.assertEqual(invalid_support_items_shape["error"]["details"]["tool"], "audit_claim_support_tool")
        self.assertEqual(invalid_support_items_shape["error"]["details"]["field"], "items")
        self.assertEqual(invalid_support_items_shape["error"]["details"]["expected"], "list")
        self.assertEqual(invalid_support_items_shape["error"]["details"]["received"], "str")

        invalid_audit_set_item = self.server.audit_claim_support_tool(
            [{"claim": "A claim.", "citations": [{"title": "GhostCite"}, {"title": 42}]}]
        )
        self.assertFalse(invalid_audit_set_item["ok"])
        self.assertEqual(invalid_audit_set_item["error"]["code"], "invalid_input")
        self.assertEqual(invalid_audit_set_item["error"]["details"]["index"], 1)
        self.assertEqual(invalid_audit_set_item["error"]["details"]["citation_index"], 2)
        self.assertEqual(invalid_audit_set_item["error"]["details"]["field"], "title")


if __name__ == "__main__":
    unittest.main()
