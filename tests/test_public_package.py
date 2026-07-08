"""Tests for the public citeguard package facade."""

import importlib
import json
import subprocess
import sys
import unittest
import warnings


LEGACY_PACKAGE = "s" + "rc"

warnings.filterwarnings(
    "ignore",
    message=r"The `src` compatibility package is deprecated;.*",
    category=DeprecationWarning,
)


class PublicPackageTests(unittest.TestCase):
    def setUp(self):
        warnings.filterwarnings(
            "ignore",
            message=r"The `src` compatibility package is deprecated;.*",
            category=DeprecationWarning,
        )

    def test_legacy_root_package_emits_deprecation_warning(self):
        from citeguard.version import __version__

        for name in list(sys.modules):
            if name == LEGACY_PACKAGE or name.startswith(LEGACY_PACKAGE + "."):
                sys.modules.pop(name, None)

        with self.assertWarnsRegex(DeprecationWarning, "compatibility package is deprecated"):
            legacy = importlib.import_module(LEGACY_PACKAGE)

        self.assertEqual(legacy.__version__, __version__)

    def test_top_level_exports_core_verification_api(self):
        from citeguard import (
            ClaimSupportRequest,
            ClaimSupportSetResult,
            CounterEvidenceSearchReport,
            ERROR_CODE_CATEGORY,
            ERROR_CODE_NEXT_ACTION,
            ERROR_CODE_RETRYABLE,
            ERROR_SCHEMA_VERSION,
            REVIEW_ACTION_QUEUE_BY_NEXT_ACTION,
            REVIEW_ACTION_QUEUE_KEYS,
            STABLE_NEXT_ACTIONS,
            Verdict,
            __version__,
            audit_claim_support,
            available_sources,
            check_claim_support_set,
            error_code_registry,
            error_payload,
            filter_high_risk_payload,
            infer_evidence_scope,
            parse_citation,
            search_counterevidence_candidates,
            source_failure_recovery_code,
            stable_next_action,
            verification_next_action,
            verification_recovery_code,
            verify_citation,
        )

        self.assertEqual(Verdict.VERIFIED.value, "verified")
        self.assertTrue(parse_citation(title="A Paper").title)
        self.assertTrue(hasattr(ClaimSupportRequest, "__dataclass_fields__"))
        self.assertTrue(hasattr(ClaimSupportSetResult, "__dataclass_fields__"))
        self.assertTrue(hasattr(CounterEvidenceSearchReport, "__dataclass_fields__"))
        self.assertTrue(callable(audit_claim_support))
        self.assertEqual(available_sources(["openalex", "arxiv"], ["arxiv"]), ["openalex"])
        self.assertEqual(source_failure_recovery_code([{"code": "timeout"}]), "timeout")
        self.assertIn("resolve_identifier_or_replace", STABLE_NEXT_ACTIONS)
        self.assertIn("identity_resolution_indexes", REVIEW_ACTION_QUEUE_KEYS)
        self.assertEqual(REVIEW_ACTION_QUEUE_BY_NEXT_ACTION["resolve_identifier_or_replace"], "identity_resolution_indexes")
        self.assertEqual(REVIEW_ACTION_QUEUE_BY_NEXT_ACTION["keep_claim"], "safe_to_keep_indexes")
        self.assertEqual(stable_next_action("keep"), "keep")
        self.assertEqual(verification_recovery_code(Verdict.AMBIGUOUS, []), "ambiguous_citation")
        self.assertEqual(verification_next_action(Verdict.NOT_FOUND), "resolve_identifier_or_replace")
        self.assertEqual(ERROR_SCHEMA_VERSION, 1)
        self.assertRegex(__version__, r"^\d+\.\d+\.\d+")
        self.assertTrue(callable(check_claim_support_set))
        self.assertTrue(callable(search_counterevidence_candidates))
        self.assertEqual(infer_evidence_scope("abstract_sentence_1"), "abstract")
        self.assertEqual(error_payload("x", "message")["error"]["code"], "x")
        self.assertEqual(error_code_registry()["schema_version"], ERROR_SCHEMA_VERSION)
        self.assertIn("missing_citation_input", error_code_registry()["codes"])
        self.assertEqual(error_payload("timeout", "Timed out")["error"]["recovery"], "Retry, raise the timeout, or continue with reduced confidence.")
        self.assertEqual(error_payload("timeout", "Timed out")["error"]["next_action"], "retry_or_check_source_health")
        self.assertTrue(error_payload("timeout", "Timed out")["error"]["retryable"])
        self.assertEqual(error_payload("timeout", "Timed out")["error"]["category"], "source_limited")
        self.assertEqual(ERROR_CODE_NEXT_ACTION["missing_citation_input"], "provide_missing_input")
        self.assertEqual(ERROR_CODE_RETRYABLE["source_unavailable"], True)
        self.assertEqual(ERROR_CODE_CATEGORY["model_unavailable"], "dependency_limited")
        self.assertTrue(callable(filter_high_risk_payload))
        self.assertTrue(callable(verify_citation))

    def test_public_errors_module_exports_error_payload(self):
        from citeguard.errors import (
            ERROR_CODE_CATEGORY,
            ERROR_CODE_NEXT_ACTION,
            ERROR_CODE_RECOVERY,
            ERROR_CODE_RETRYABLE,
            ERROR_SCHEMA_VERSION,
            STABLE_ERROR_CODES,
            error_code_registry,
            error_payload,
            is_stable_error_code,
            runtime_config_error_details,
        )

        self.assertFalse(error_payload("bad", "Bad input")["ok"])
        self.assertEqual(ERROR_SCHEMA_VERSION, 1)
        self.assertEqual(error_payload("bad", "Bad input")["schema_version"], ERROR_SCHEMA_VERSION)
        self.assertEqual(error_payload("bad", "Bad input")["error"]["recovery"], "")
        self.assertEqual(error_payload("bad", "Bad input")["error"]["next_action"], "")
        self.assertEqual(error_payload("bad", "Bad input")["error"]["retryable"], False)
        self.assertEqual(error_payload("bad", "Bad input")["error"]["category"], "")
        self.assertIn("DOI", error_payload("missing_citation_input", "Missing citation")["error"]["recovery"])
        self.assertEqual(error_payload("missing_citation_input", "Missing citation")["error"]["next_action"], "provide_missing_input")
        self.assertEqual(error_payload("missing_citation_input", "Missing citation")["error"]["category"], "missing_input")
        self.assertIn("missing_citation_input", STABLE_ERROR_CODES)
        self.assertIn("Ask for", ERROR_CODE_RECOVERY["missing_citation_input"])
        self.assertEqual(set(ERROR_CODE_NEXT_ACTION), STABLE_ERROR_CODES)
        self.assertEqual(set(ERROR_CODE_RETRYABLE), STABLE_ERROR_CODES)
        self.assertEqual(set(ERROR_CODE_CATEGORY), STABLE_ERROR_CODES)
        registry = error_code_registry()
        self.assertEqual(registry["schema_version"], ERROR_SCHEMA_VERSION)
        self.assertEqual(set(registry["codes"]), STABLE_ERROR_CODES)
        self.assertEqual(
            registry["codes"]["missing_citation_input"]["next_action"],
            "provide_missing_input",
        )
        self.assertIn("DOI", registry["codes"]["missing_citation_input"]["recovery"])
        self.assertFalse(registry["codes"]["missing_citation_input"]["retryable"])
        self.assertEqual(registry["codes"]["missing_citation_input"]["category"], "missing_input")
        self.assertTrue(registry["codes"]["source_unavailable"]["retryable"])
        self.assertEqual(registry["codes"]["source_unavailable"]["category"], "source_limited")
        self.assertTrue(is_stable_error_code("timeout"))
        self.assertFalse(is_stable_error_code("private_experimental_code"))
        details = runtime_config_error_details(
            "Unknown CITEGUARD_SOURCES value(s): bad. Valid values: arxiv, openalex.",
            base={"tool": "verify_citation_tool"},
        )
        self.assertEqual(details["tool"], "verify_citation_tool")
        self.assertEqual(details["field"], "CITEGUARD_SOURCES")
        self.assertEqual(details["source"], "environment")
        self.assertEqual(details["invalid_values"], ["bad"])
        self.assertEqual(details["valid_values"], ["arxiv", "openalex"])
        numeric_details = runtime_config_error_details(
            "CITEGUARD_HTTP_TIMEOUT must be a positive integer.",
            env={"CITEGUARD_HTTP_TIMEOUT": "0"},
        )
        self.assertEqual(numeric_details["field"], "CITEGUARD_HTTP_TIMEOUT")
        self.assertEqual(numeric_details["source"], "environment")
        self.assertEqual(numeric_details["expected"], "positive integer")
        self.assertEqual(numeric_details["received"], "0")

    def test_legacy_error_module_is_public_shim(self):
        from citeguard import errors as public_errors
        legacy_errors = importlib.import_module("s" + "rc.errors")

        self.assertIs(legacy_errors.error_payload, public_errors.error_payload)
        self.assertEqual(legacy_errors.ERROR_SCHEMA_VERSION, public_errors.ERROR_SCHEMA_VERSION)
        self.assertIs(legacy_errors.STABLE_ERROR_CODES, public_errors.STABLE_ERROR_CODES)
        self.assertIs(legacy_errors.ERROR_CODE_NEXT_ACTION, public_errors.ERROR_CODE_NEXT_ACTION)
        self.assertIs(legacy_errors.runtime_config_error_details, public_errors.runtime_config_error_details)

    def test_legacy_graph_modules_are_public_shims(self):
        from citeguard import graph as public_graph
        from citeguard.graph import cceg as public_cceg
        from citeguard.graph import graph_store as public_graph_store

        legacy_graph = importlib.import_module("s" + "rc.graph")
        legacy_cceg = importlib.import_module("s" + "rc.graph.cceg")
        legacy_graph_store = importlib.import_module("s" + "rc.graph.graph_store")

        self.assertIs(legacy_graph.CitationRecord, public_graph.CitationRecord)
        self.assertIs(legacy_cceg.CCEG, public_cceg.CCEG)
        self.assertIs(legacy_cceg.Claim, public_cceg.Claim)
        self.assertIs(legacy_graph_store.InMemoryGraphStore, public_graph_store.InMemoryGraphStore)

    def test_legacy_citation_modules_are_public_shims(self):
        from citeguard import citation as public_citation
        from citeguard.citation import formatter as public_formatter
        from citeguard.citation import normalizer as public_normalizer
        from citeguard.citation import proposer as public_proposer

        legacy_citation = importlib.import_module("s" + "rc.citation")
        legacy_formatter = importlib.import_module("s" + "rc.citation.formatter")
        legacy_normalizer = importlib.import_module("s" + "rc.citation.normalizer")
        legacy_proposer = importlib.import_module("s" + "rc.citation.proposer")

        self.assertIs(legacy_citation.tokenize_text, public_citation.tokenize_text)
        self.assertIs(legacy_formatter.CitationFormatter, public_formatter.CitationFormatter)
        self.assertIs(legacy_normalizer.normalize_text, public_normalizer.normalize_text)
        self.assertIs(legacy_proposer.CandidateCitation, public_proposer.CandidateCitation)
        self.assertIs(legacy_proposer.CitationProposer, public_proposer.CitationProposer)

    def test_legacy_verifier_modules_are_public_shims(self):
        from citeguard import verifiers as public_verifiers
        from citeguard.verifiers import contradiction_verifier as public_contradiction
        from citeguard.verifiers import existence_verifier as public_existence
        from citeguard.verifiers import metadata_verifier as public_metadata
        from citeguard.verifiers import risk_fusion as public_risk
        from citeguard.verifiers import support_backends as public_backends
        from citeguard.verifiers import support_verifier as public_support
        from citeguard.verifiers import uncertainty_gate as public_gate

        legacy_verifiers = importlib.import_module("s" + "rc.verifiers")
        legacy_contradiction = importlib.import_module("s" + "rc.verifiers.contradiction_verifier")
        legacy_existence = importlib.import_module("s" + "rc.verifiers.existence_verifier")
        legacy_metadata = importlib.import_module("s" + "rc.verifiers.metadata_verifier")
        legacy_risk = importlib.import_module("s" + "rc.verifiers.risk_fusion")
        legacy_backends = importlib.import_module("s" + "rc.verifiers.support_backends")
        legacy_support = importlib.import_module("s" + "rc.verifiers.support_verifier")
        legacy_gate = importlib.import_module("s" + "rc.verifiers.uncertainty_gate")

        self.assertIs(legacy_verifiers.SupportAssessment, public_verifiers.SupportAssessment)
        self.assertIs(legacy_contradiction.ContradictionVerifier, public_contradiction.ContradictionVerifier)
        self.assertIs(legacy_existence.ExistenceVerifier, public_existence.ExistenceVerifier)
        self.assertIs(legacy_metadata.MetadataVerifier, public_metadata.MetadataVerifier)
        self.assertIs(legacy_risk.RiskFusion, public_risk.RiskFusion)
        self.assertIs(legacy_risk.RiskProfile, public_risk.RiskProfile)
        self.assertIs(legacy_backends.SupportAssessment, public_backends.SupportAssessment)
        self.assertIs(legacy_backends.HeuristicSupportBackend, public_backends.HeuristicSupportBackend)
        self.assertIs(legacy_backends.combine_support_assessments, public_backends.combine_support_assessments)
        self.assertIs(legacy_support.SupportVerifier, public_support.SupportVerifier)
        self.assertIs(legacy_gate.UncertaintyGate, public_gate.UncertaintyGate)
        self.assertIs(legacy_gate.GateDecision, public_gate.GateDecision)

    def test_legacy_benchmark_modules_are_public_shims(self):
        from citeguard import benchmark as public_benchmark
        from citeguard.benchmark import baselines as public_baselines
        from citeguard.benchmark import dataset_builder as public_dataset_builder
        from citeguard.benchmark import experiments as public_experiments
        from citeguard.benchmark import metrics as public_metrics
        from citeguard.benchmark import support_calibration as public_support_calibration

        legacy_benchmark = importlib.import_module("s" + "rc.benchmark")
        legacy_baselines = importlib.import_module("s" + "rc.benchmark.baselines")
        legacy_dataset_builder = importlib.import_module("s" + "rc.benchmark.dataset_builder")
        legacy_experiments = importlib.import_module("s" + "rc.benchmark.experiments")
        legacy_metrics = importlib.import_module("s" + "rc.benchmark.metrics")
        legacy_support_calibration = importlib.import_module("s" + "rc.benchmark.support_calibration")

        self.assertIs(legacy_benchmark.MetricsCalculator, public_benchmark.MetricsCalculator)
        self.assertIs(legacy_baselines.RAGWriteBaseline, public_baselines.RAGWriteBaseline)
        self.assertIs(legacy_dataset_builder.BenchmarkExample, public_dataset_builder.BenchmarkExample)
        self.assertIs(legacy_experiments.write_experiment_artifacts, public_experiments.write_experiment_artifacts)
        self.assertIs(legacy_benchmark.write_experiment_artifacts, public_benchmark.write_experiment_artifacts)
        self.assertIs(legacy_metrics.EvaluationRecord, public_metrics.EvaluationRecord)
        self.assertIs(legacy_support_calibration.SupportCalibrationExample, public_support_calibration.SupportCalibrationExample)
        self.assertIs(legacy_support_calibration.evaluate_support_config, public_support_calibration.evaluate_support_config)

    def test_legacy_api_modules_are_public_shims(self):
        from citeguard import api as public_api
        from citeguard.api import app as public_app
        from citeguard.api import schemas as public_schemas

        legacy_api = importlib.import_module("s" + "rc.api")
        legacy_app = importlib.import_module("s" + "rc.api.app")
        legacy_schemas = importlib.import_module("s" + "rc.api.schemas")

        self.assertIs(legacy_api.GenerateRequest, public_api.GenerateRequest)
        self.assertIs(legacy_app.create_app, public_app.create_app)
        self.assertIs(legacy_schemas.GenerateRequest, public_schemas.GenerateRequest)
        self.assertIs(legacy_schemas.GenerateResponse, public_schemas.GenerateResponse)

    def test_legacy_writing_pipeline_modules_are_public_shims(self):
        from citeguard import audit as public_audit
        from citeguard import orchestrator as public_orchestrator
        from citeguard import planner as public_planner
        from citeguard import writer as public_writer
        from citeguard.audit import provenance as public_provenance
        from citeguard.audit import report_builder as public_report_builder
        from citeguard.audit import visualization as public_visualization
        from citeguard.orchestrator import graph as public_orchestrator_graph
        from citeguard.orchestrator import policies as public_policies
        from citeguard.orchestrator import states as public_states
        from citeguard.planner import claim_decomposer as public_claim_decomposer
        from citeguard.planner import outline_planner as public_outline_planner
        from citeguard.writer import abstention_controller as public_abstention
        from citeguard.writer import constrained_writer as public_constrained_writer
        from citeguard.writer import reviser as public_reviser

        legacy_audit = importlib.import_module("s" + "rc.audit")
        legacy_provenance = importlib.import_module("s" + "rc.audit.provenance")
        legacy_report_builder = importlib.import_module("s" + "rc.audit.report_builder")
        legacy_visualization = importlib.import_module("s" + "rc.audit.visualization")
        legacy_planner = importlib.import_module("s" + "rc.planner")
        legacy_claim_decomposer = importlib.import_module("s" + "rc.planner.claim_decomposer")
        legacy_outline_planner = importlib.import_module("s" + "rc.planner.outline_planner")
        legacy_writer = importlib.import_module("s" + "rc.writer")
        legacy_abstention = importlib.import_module("s" + "rc.writer.abstention_controller")
        legacy_constrained_writer = importlib.import_module("s" + "rc.writer.constrained_writer")
        legacy_reviser = importlib.import_module("s" + "rc.writer.reviser")
        legacy_orchestrator = importlib.import_module("s" + "rc.orchestrator")
        legacy_orchestrator_graph = importlib.import_module("s" + "rc.orchestrator.graph")
        legacy_policies = importlib.import_module("s" + "rc.orchestrator.policies")
        legacy_states = importlib.import_module("s" + "rc.orchestrator.states")

        self.assertIs(legacy_audit.AuditReportBuilder, public_audit.AuditReportBuilder)
        self.assertIs(legacy_provenance.ProvenanceBuilder, public_provenance.ProvenanceBuilder)
        self.assertIs(legacy_report_builder.AuditReportBuilder, public_report_builder.AuditReportBuilder)
        self.assertIs(legacy_visualization.GraphVisualizer, public_visualization.GraphVisualizer)
        self.assertIs(legacy_planner.OutlinePlanner, public_planner.OutlinePlanner)
        self.assertIs(legacy_claim_decomposer.ClaimDecomposer, public_claim_decomposer.ClaimDecomposer)
        self.assertIs(legacy_outline_planner.OutlineSection, public_outline_planner.OutlineSection)
        self.assertIs(legacy_writer.ConstrainedWriter, public_writer.ConstrainedWriter)
        self.assertIs(legacy_abstention.AbstentionController, public_abstention.AbstentionController)
        self.assertIs(legacy_constrained_writer.ConstrainedWriter, public_constrained_writer.ConstrainedWriter)
        self.assertIs(legacy_reviser.ConservativeReviser, public_reviser.ConservativeReviser)
        self.assertIs(legacy_orchestrator.CiteGuardAgent, public_orchestrator.CiteGuardAgent)
        self.assertIs(legacy_orchestrator_graph.CiteGuardAgent, public_orchestrator_graph.CiteGuardAgent)
        self.assertIs(legacy_policies.RiskPolicy, public_policies.RiskPolicy)
        self.assertIs(legacy_states.AgentTask, public_states.AgentTask)

    def test_public_subpackages_export_retrieval_and_verification(self):
        from citeguard.retrieval.scholarly_clients import HTTPClient, InMemoryMetadataSource
        from citeguard.verification import (
            CACHE_SCHEMA_VERSION,
            STABLE_NEXT_ACTIONS,
            Verdict,
            audit_citations,
            available_sources,
            check_claim_support_set,
            extract_citation_candidates,
            inspect_cache,
            search_counterevidence_candidates,
            source_failure_recovery_code,
            stable_next_action,
            verification_next_action,
        )

        self.assertTrue(callable(audit_citations))
        self.assertEqual(available_sources(["openalex", "crossref"], ["crossref"]), ["openalex"])
        self.assertEqual(source_failure_recovery_code([{"code": "source_unavailable"}]), "source_unavailable")
        self.assertIn("rewrite_or_replace_evidence", STABLE_NEXT_ACTIONS)
        self.assertEqual(stable_next_action("keep_claim"), "keep_claim")
        self.assertEqual(verification_next_action(Verdict.VERIFIED), "keep")
        self.assertTrue(callable(check_claim_support_set))
        self.assertTrue(callable(search_counterevidence_candidates))
        self.assertTrue(callable(extract_citation_candidates))
        self.assertEqual(inspect_cache(":memory:")["schema_version"], CACHE_SCHEMA_VERSION)
        self.assertTrue(callable(HTTPClient))
        self.assertEqual(InMemoryMetadataSource([]).all_records(), [])

    def test_public_retrieval_package_exports_retrievers_lazily(self):
        from citeguard.retrieval import BM25LikeRetriever, MetadataSourceRetriever, RetrievedCitation

        self.assertTrue(callable(BM25LikeRetriever))
        self.assertTrue(callable(MetadataSourceRetriever))
        self.assertTrue(hasattr(RetrievedCitation, "__dataclass_fields__"))

    def test_legacy_package_entrypoints_are_public_shims(self):
        import citeguard.retrieval as public_retrieval
        import citeguard.verification as public_verification

        legacy_retrieval = importlib.import_module("s" + "rc.retrieval")
        legacy_verification = importlib.import_module("s" + "rc.verification")

        self.assertEqual(legacy_retrieval.__all__, public_retrieval.__all__)
        self.assertEqual(legacy_verification.__all__, public_verification.__all__)
        self.assertIs(legacy_retrieval.BM25LikeRetriever, public_retrieval.BM25LikeRetriever)
        self.assertIs(legacy_retrieval.MetadataSourceRetriever, public_retrieval.MetadataSourceRetriever)
        self.assertIs(legacy_verification.verify_citation, public_verification.verify_citation)
        self.assertIs(legacy_verification.audit_claim_support, public_verification.audit_claim_support)
        self.assertIs(legacy_verification.stable_next_action, public_verification.stable_next_action)

    def test_legacy_retrieval_modules_are_public_shims(self):
        from citeguard.retrieval import bm25_retriever as public_bm25
        from citeguard.retrieval import dense_retriever as public_dense
        from citeguard.retrieval import hybrid_retriever as public_hybrid
        from citeguard.retrieval import metadata_source_retriever as public_metadata_retriever
        from citeguard.retrieval import types as public_types

        legacy_bm25 = importlib.import_module("s" + "rc.retrieval.bm25_retriever")
        legacy_dense = importlib.import_module("s" + "rc.retrieval.dense_retriever")
        legacy_hybrid = importlib.import_module("s" + "rc.retrieval.hybrid_retriever")
        legacy_metadata_retriever = importlib.import_module("s" + "rc.retrieval.metadata_source_retriever")
        legacy_types = importlib.import_module("s" + "rc.retrieval.types")

        self.assertIs(legacy_bm25.BM25LikeRetriever, public_bm25.BM25LikeRetriever)
        self.assertIs(legacy_dense.DenseLikeRetriever, public_dense.DenseLikeRetriever)
        self.assertIs(legacy_hybrid.HybridRetriever, public_hybrid.HybridRetriever)
        self.assertIs(legacy_metadata_retriever.MetadataSourceRetriever, public_metadata_retriever.MetadataSourceRetriever)
        self.assertIs(legacy_types.RetrievedCitation, public_types.RetrievedCitation)

    def test_legacy_retrieval_scholarly_clients_are_public_shims(self):
        from citeguard.retrieval.scholarly_clients import HTTPClient, InMemoryMetadataSource, MultiSourceMetadataSource
        from citeguard.retrieval.scholarly_clients import ArxivMetadataSource, CrossrefMetadataSource
        from citeguard.retrieval.scholarly_clients import OpenAlexMetadataSource, SemanticScholarMetadataSource
        from citeguard.retrieval.scholarly_clients import build_live_metadata_source
        from citeguard.retrieval.scholarly_clients import arxiv as public_arxiv
        from citeguard.retrieval.scholarly_clients import base as public_base
        from citeguard.retrieval.scholarly_clients import crossref as public_crossref
        from citeguard.retrieval.scholarly_clients import evidence as public_evidence
        from citeguard.retrieval.scholarly_clients import factory as public_factory
        from citeguard.retrieval.scholarly_clients import http as public_http
        from citeguard.retrieval.scholarly_clients import in_memory as public_in_memory
        from citeguard.retrieval.scholarly_clients import multi_source as public_multi_source
        from citeguard.retrieval.scholarly_clients import openalex as public_openalex
        from citeguard.retrieval.scholarly_clients import semantic_scholar as public_semantic_scholar
        from citeguard.retrieval.scholarly_clients import utils as public_utils

        legacy_arxiv = importlib.import_module("s" + "rc.retrieval.scholarly_clients.arxiv")
        legacy_base = importlib.import_module("s" + "rc.retrieval.scholarly_clients.base")
        legacy_crossref = importlib.import_module("s" + "rc.retrieval.scholarly_clients.crossref")
        legacy_evidence = importlib.import_module("s" + "rc.retrieval.scholarly_clients.evidence")
        legacy_factory = importlib.import_module("s" + "rc.retrieval.scholarly_clients.factory")
        legacy_http = importlib.import_module("s" + "rc.retrieval.scholarly_clients.http")
        legacy_in_memory = importlib.import_module("s" + "rc.retrieval.scholarly_clients.in_memory")
        legacy_multi_source = importlib.import_module("s" + "rc.retrieval.scholarly_clients.multi_source")
        legacy_openalex = importlib.import_module("s" + "rc.retrieval.scholarly_clients.openalex")
        legacy_semantic_scholar = importlib.import_module("s" + "rc.retrieval.scholarly_clients.semantic_scholar")
        legacy_utils = importlib.import_module("s" + "rc.retrieval.scholarly_clients.utils")

        self.assertIs(legacy_arxiv.ArxivMetadataSource, public_arxiv.ArxivMetadataSource)
        self.assertIs(legacy_base.MetadataSource, public_base.MetadataSource)
        self.assertIs(legacy_crossref.CrossrefMetadataSource, public_crossref.CrossrefMetadataSource)
        self.assertIs(legacy_evidence.merge_evidence_chunks, public_evidence.merge_evidence_chunks)
        self.assertIs(legacy_factory.build_live_metadata_source, public_factory.build_live_metadata_source)
        self.assertIs(legacy_http.HTTPClient, public_http.HTTPClient)
        self.assertIs(legacy_in_memory.InMemoryMetadataSource, public_in_memory.InMemoryMetadataSource)
        self.assertIs(legacy_multi_source.MultiSourceMetadataSource, public_multi_source.MultiSourceMetadataSource)
        self.assertIs(legacy_openalex.OpenAlexMetadataSource, public_openalex.OpenAlexMetadataSource)
        self.assertIs(
            legacy_semantic_scholar.SemanticScholarMetadataSource,
            public_semantic_scholar.SemanticScholarMetadataSource,
        )
        self.assertIs(legacy_utils.normalize_doi, public_utils.normalize_doi)
        self.assertIs(ArxivMetadataSource, public_arxiv.ArxivMetadataSource)
        self.assertIs(CrossrefMetadataSource, public_crossref.CrossrefMetadataSource)
        self.assertIs(HTTPClient, public_http.HTTPClient)
        self.assertIs(InMemoryMetadataSource, public_in_memory.InMemoryMetadataSource)
        self.assertIs(MultiSourceMetadataSource, public_multi_source.MultiSourceMetadataSource)
        self.assertIs(OpenAlexMetadataSource, public_openalex.OpenAlexMetadataSource)
        self.assertIs(SemanticScholarMetadataSource, public_semantic_scholar.SemanticScholarMetadataSource)
        self.assertIs(build_live_metadata_source, public_factory.build_live_metadata_source)

    def test_public_verification_submodule_facades_are_importable(self):
        from citeguard.verification import compute_support_release_summary
        from citeguard.verification.cache import export_cache_records, inspect_cache
        from citeguard.verification.eval import load_eval
        from citeguard.verification.extract import extract_citation_candidates
        from citeguard.verification.parse import parse_citation
        from citeguard.verification.support_eval import compute_support_metrics

        self.assertTrue(callable(inspect_cache))
        self.assertTrue(callable(export_cache_records))
        self.assertTrue(callable(load_eval))
        self.assertTrue(callable(extract_citation_candidates))
        self.assertEqual(compute_support_release_summary({"overall": {"n": 0}})["schema_version"], 1)
        self.assertEqual(parse_citation(title="A Paper").title, "A Paper")
        self.assertEqual(compute_support_metrics([])["n"], 0)

    def test_legacy_verification_models_module_is_public_shim(self):
        from citeguard.verification import models as public_models
        legacy_models = importlib.import_module("s" + "rc.verification.models")

        self.assertIs(legacy_models.VerificationResult, public_models.VerificationResult)
        self.assertIs(legacy_models.Verdict, public_models.Verdict)
        self.assertIs(legacy_models.available_sources, public_models.available_sources)
        self.assertIs(legacy_models.source_failure_recovery_code, public_models.source_failure_recovery_code)
        self.assertIs(legacy_models.verification_next_action, public_models.verification_next_action)

    def test_legacy_verification_parse_extract_modules_are_public_shims(self):
        from citeguard.verification import extract as public_extract
        from citeguard.verification import parse as public_parse

        legacy_extract = importlib.import_module("s" + "rc.verification.extract")
        legacy_parse = importlib.import_module("s" + "rc.verification.parse")

        self.assertIs(legacy_parse.parse_citation, public_parse.parse_citation)
        self.assertIs(legacy_extract.extract_citation_candidates, public_extract.extract_citation_candidates)

    def test_legacy_verification_resolve_module_is_public_shim(self):
        from citeguard.verification import resolve as public_resolve

        legacy_resolve = importlib.import_module("s" + "rc.verification.resolve")

        self.assertIs(legacy_resolve.ResolveOutcome, public_resolve.ResolveOutcome)
        self.assertIs(legacy_resolve.resolve_citation, public_resolve.resolve_citation)
        self.assertIs(legacy_resolve.verification_match_score, public_resolve.verification_match_score)

    def test_legacy_verification_verify_audit_modules_are_public_shims(self):
        from citeguard.verification import audit as public_audit
        from citeguard.verification import verify as public_verify

        legacy_audit = importlib.import_module("s" + "rc.verification.audit")
        legacy_verify = importlib.import_module("s" + "rc.verification.verify")

        self.assertIs(legacy_verify.verify_citation, public_verify.verify_citation)
        self.assertIs(legacy_audit.audit_citations, public_audit.audit_citations)

    def test_legacy_verification_cache_module_is_public_shim(self):
        from citeguard.verification import cache as public_cache

        legacy_cache = importlib.import_module("s" + "rc.verification.cache")

        self.assertEqual(legacy_cache.CACHE_SCHEMA_VERSION, public_cache.CACHE_SCHEMA_VERSION)
        self.assertIs(legacy_cache.CachingMetadataSource, public_cache.CachingMetadataSource)
        self.assertIs(legacy_cache.inspect_cache, public_cache.inspect_cache)
        self.assertIs(legacy_cache.clear_cache, public_cache.clear_cache)
        self.assertIs(legacy_cache.export_cache_records, public_cache.export_cache_records)

    def test_legacy_verification_eval_modules_are_public_shims(self):
        from citeguard.verification import eval as public_eval
        from citeguard.verification import support_eval as public_support_eval

        legacy_eval = importlib.import_module("s" + "rc.verification.eval")
        legacy_support_eval = importlib.import_module("s" + "rc.verification.support_eval")

        self.assertIs(legacy_eval.EvalCase, public_eval.EvalCase)
        self.assertIs(legacy_eval.load_eval, public_eval.load_eval)
        self.assertIs(legacy_eval.run_eval, public_eval.run_eval)
        self.assertIs(legacy_support_eval.SupportCase, public_support_eval.SupportCase)
        self.assertIs(legacy_support_eval.load_support_eval, public_support_eval.load_support_eval)
        self.assertIs(legacy_support_eval.compute_support_report, public_support_eval.compute_support_report)
        self.assertIs(
            legacy_support_eval.compute_support_release_summary,
            public_support_eval.compute_support_release_summary,
        )

    def test_legacy_verification_support_module_is_public_shim(self):
        from citeguard.verification import support as public_support

        legacy_support = importlib.import_module("s" + "rc.verification.support")

        self.assertIs(legacy_support.SupportResult, public_support.SupportResult)
        self.assertIs(legacy_support.SupportVerdict, public_support.SupportVerdict)
        self.assertIs(legacy_support.assess_support, public_support.assess_support)
        self.assertIs(legacy_support.check_claim_support, public_support.check_claim_support)
        self.assertIs(legacy_support.check_claim_support_set, public_support.check_claim_support_set)
        self.assertIs(legacy_support._extract_nli, public_support._extract_nli)

    def test_public_advanced_facades_are_importable(self):
        from citeguard.benchmark import MetricsCalculator
        from citeguard.benchmark.support_calibration import SupportCalibrationExample
        from citeguard.verifiers import SupportAssessment

        self.assertTrue(callable(MetricsCalculator))
        self.assertTrue(hasattr(SupportCalibrationExample, "__dataclass_fields__"))
        self.assertTrue(hasattr(SupportAssessment, "__dataclass_fields__"))

    def test_public_runtime_exports_status_helper(self):
        from citeguard.runtime import build_configured_support_backend, environment_status

        status = environment_status(env={})
        self.assertEqual(status["service"], "CiteGuard")
        self.assertTrue(callable(build_configured_support_backend))

    def test_legacy_runtime_module_is_public_shim(self):
        from citeguard import runtime as public_runtime
        legacy_runtime = importlib.import_module("s" + "rc.runtime")

        self.assertIs(legacy_runtime.environment_status, public_runtime.environment_status)
        self.assertIs(legacy_runtime.build_configured_source, public_runtime.build_configured_source)

    def test_public_cli_module_exports_runner(self):
        from citeguard.cli import run

        self.assertTrue(callable(run))

    def test_package_module_entrypoint_runs_cli(self):
        completed = subprocess.run(
            [sys.executable, "-m", "citeguard", "status", "--compact"],
            cwd=".",
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["service"], "CiteGuard")
        self.assertEqual(payload["schema_version"], 1)

    def test_legacy_cli_module_is_public_shim(self):
        from citeguard import cli as public_cli
        legacy_cli = importlib.import_module("s" + "rc.cli")

        self.assertIs(legacy_cli.run, public_cli.run)
        self.assertIs(legacy_cli.main, public_cli.main)

    def test_public_mcp_module_exports_entry_point(self):
        from citeguard.mcp.server import main

        self.assertTrue(callable(main))

    def test_legacy_mcp_module_is_public_shim(self):
        from citeguard.mcp import server as public_mcp_server
        legacy_mcp_server = importlib.import_module("s" + "rc.mcp_server.server")

        self.assertIs(legacy_mcp_server.main, public_mcp_server.main)
        self.assertIs(legacy_mcp_server.verify_citation_tool, public_mcp_server.verify_citation_tool)


if __name__ == "__main__":
    unittest.main()
