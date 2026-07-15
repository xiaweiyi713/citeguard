"""Tests for the public citeguard package facade."""

import importlib.util
import json
import subprocess
import sys
import unittest


class PublicPackageTests(unittest.TestCase):

    def test_writing_agent_prototype_modules_absent_from_package(self):
        for module_name in [
            "citeguard.orchestrator",
            "citeguard.planner",
            "citeguard.writer",
            "citeguard.api",
            "citeguard.benchmark.baselines",
            "citeguard.benchmark.dataset_builder",
        ]:
            with self.subTest(module_name=module_name):
                self.assertIsNone(
                    importlib.util.find_spec(module_name),
                    f"{module_name} moved to the repo-root legacy/ prototype directory "
                    "and must not be importable from the citeguard package",
                )

        import citeguard.benchmark as benchmark

        for moved_export in ["BenchmarkExample", "CiteGuardBenchBuilder", "DirectWriteBaseline", "RAGWriteBaseline"]:
            with self.subTest(moved_export=moved_export):
                self.assertFalse(hasattr(benchmark, moved_export))
                self.assertNotIn(moved_export, benchmark.__all__)

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


    def test_public_mcp_module_exports_entry_point(self):
        from citeguard.mcp.server import main

        self.assertTrue(callable(main))

