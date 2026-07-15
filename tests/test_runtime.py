"""Tests for shared runtime configuration."""

import json
import os
import tempfile
import unittest

from citeguard.runtime import (
    SOURCE_HEALTH_SCHEMA_VERSION,
    build_configured_source,
    cache_path,
    cache_ttl,
    environment_status,
    evidence_timeout,
    http_min_interval,
    http_retries,
    http_retry_backoff,
    http_timeout,
    load_fixture_records,
    remote_evidence_enabled,
    negative_cache_ttl,
    source_budget,
    source_health_status,
)
from citeguard.verification import CachingMetadataSource, CitationRecord
from citeguard.version import __version__

EXPECTED_USER_AGENT = f"CiteGuard/{__version__}"


class FakeHealthSource:
    def __init__(self, name, records=None, exc=None):
        self.name = name
        self.records = records or []
        self.exc = exc

    def all_records(self):
        return self.records

    def lookup(self, candidate):
        return self.records[0] if self.records else None

    def search(self, query, top_k=5):
        if self.exc is not None:
            raise self.exc
        return self.records[:top_k]


class FakeHTTPDiagnostics:
    last_error_code = ""
    last_error_kind = ""
    last_error = ""
    last_status_code = None
    last_url = "https://example.test/health"
    last_cache_hit = True
    last_attempt_count = 0
    last_retry_count = 0


class RateLimitedDiagnostics:
    last_error_code = "source_unavailable"
    last_error_kind = "rate_limited"
    last_error = "HTTP Error 429: Too Many Requests"
    last_status_code = 429
    last_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    last_cache_hit = False
    last_attempt_count = 2
    last_retry_count = 1
    last_retry_after_seconds = 2.0
    last_retry_delay_seconds = 1.5


class ExpiredRetryAfterDiagnostics(RateLimitedDiagnostics):
    last_retry_after_seconds = 0.0
    last_retry_delay_seconds = None


class InvalidJSONDiagnostics:
    last_error_code = "source_unavailable"
    last_error_kind = "invalid_json"
    last_error = "JSONDecodeError"
    last_status_code = 200
    last_url = "https://api.crossref.org/works?query.title=broken"
    last_cache_hit = False
    last_attempt_count = 1
    last_retry_count = 0
    last_retry_after_seconds = None
    last_retry_delay_seconds = None


class CachedHealthSource(FakeHealthSource):
    http_client = FakeHTTPDiagnostics()


class RateLimitedHealthSource(FakeHealthSource):
    http_client = RateLimitedDiagnostics()


class ExpiredRetryAfterHealthSource(FakeHealthSource):
    http_client = ExpiredRetryAfterDiagnostics()


class InvalidJSONHealthSource(FakeHealthSource):
    http_client = InvalidJSONDiagnostics()


def fake_health_source_factory(names, **kwargs):
    name = names[0]
    if name == "openalex":
        return FakeHealthSource(
            name,
            records=[
                CitationRecord(
                    citation_id="health-1",
                    title="Attention Is All You Need",
                    source=name,
                )
            ],
        )
    if name == "crossref":
        return FakeHealthSource(name)
    raise TimeoutError("health probe timed out")


def mixed_failure_health_source_factory(names, **kwargs):
    name = names[0]
    if name == "crossref":
        return InvalidJSONHealthSource(name)
    if name == "semantic_scholar":
        return RateLimitedHealthSource(name)
    raise TimeoutError("health probe timed out")


def expired_retry_after_health_source_factory(names, **kwargs):
    return ExpiredRetryAfterHealthSource(names[0])


def cached_health_source_factory(names, **kwargs):
    return CachedHealthSource(
        names[0],
        records=[
            CitationRecord(
                citation_id="health-cache-1",
                title="Attention Is All You Need",
                source=names[0],
            )
        ],
    )


class RuntimeConfigTests(unittest.TestCase):
    def test_default_cache_uses_user_cache_directory_not_working_directory(self):
        path = cache_path({})

        self.assertTrue(path.endswith(os.path.join("citeguard", "verification_cache.sqlite")))
        self.assertTrue(os.path.isabs(path))
        self.assertNotIn(os.path.join("data", "logs"), path)

    def test_xdg_cache_home_and_explicit_cache_override(self):
        self.assertEqual(
            cache_path({"XDG_CACHE_HOME": "/tmp/custom-cache"}),
            "/tmp/custom-cache/citeguard/verification_cache.sqlite",
        )
        self.assertEqual(cache_path({"CITEGUARD_CACHE": ":memory:"}), ":memory:")

    def test_cache_ttls_and_source_budget_are_strictly_validated(self):
        self.assertEqual(cache_ttl({}), 86400.0)
        self.assertEqual(negative_cache_ttl({}), 900.0)
        self.assertEqual(source_budget({}), 8.0)
        self.assertEqual(source_budget({"CITEGUARD_SOURCE_BUDGET": "0.25"}), 0.25)
        for name, function in (
            ("CITEGUARD_CACHE_TTL", cache_ttl),
            ("CITEGUARD_NEGATIVE_CACHE_TTL", negative_cache_ttl),
            ("CITEGUARD_SOURCE_BUDGET", source_budget),
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                function({name: "invalid"})

    def test_remote_evidence_is_disabled_by_default(self):
        self.assertFalse(remote_evidence_enabled(env={}))
        status = environment_status(env={}, module_checker=lambda name: False)
        self.assertFalse(status["remote_evidence_enabled"])
        self.assertEqual(status["schema_version"], 1)
        self.assertFalse(status["remote_evidence_policy"]["enabled"])
        self.assertFalse(status["remote_evidence_policy"]["default_enabled"])
        self.assertFalse(status["remote_evidence_policy"]["non_http_urls_allowed"])
        self.assertIn("cnki.net", status["remote_evidence_policy"]["blocked_host_suffixes"])
        self.assertIn("wanfangdata.com.cn", status["remote_evidence_policy"]["blocked_host_suffixes"])
        self.assertIn("cqvip.com", status["remote_evidence_policy"]["blocked_host_suffixes"])
        self.assertEqual(status["http_user_agent"], EXPECTED_USER_AGENT)
        self.assertFalse(status["polite_access"]["compliant"])
        self.assertEqual(status["polite_access"]["status"], "missing_contact_email")
        self.assertEqual(status["polite_access"]["configured_contact_required_sources"], ["openalex", "crossref"])
        self.assertEqual(status["polite_access"]["next_action"], "fix_configuration")
        self.assertEqual(status["source_health"]["sources"][0]["http_user_agent"], EXPECTED_USER_AGENT)
        self.assertEqual(status["source_health"]["sources"][0]["polite_access"]["status"], "missing_contact_email")
        self.assertEqual(status["source_health"]["sources"][0]["polite_access"]["next_action"], "fix_configuration")
        self.assertEqual(status["source_health"]["sources"][0]["next_action"], "inspect_source_health")
        self.assertEqual(status["source_health"]["sources"][0]["confidence_effect"], "not_checked")
        self.assertEqual(status["source_health"]["summary"]["next_action"], "inspect_source_health")
        self.assertEqual(status["http_timeout_seconds"], 10)
        self.assertEqual(status["evidence_timeout_seconds"], 2)
        self.assertEqual(status["cache_status"]["path"], status["cache_path"])
        self.assertTrue(status["cache_status"]["inspect_ok"])
        self.assertGreaterEqual(status["cache_status"]["entries"], 0)
        self.assertIn("search", status["cache_status"]["entry_prefixes"])
        self.assertEqual(status["cache_status"]["next_action"], "continue")
        support_models = status["support_models"]
        self.assertFalse(support_models["deep_models_available"])
        self.assertEqual(support_models["engine"], "heuristic_fallback")
        self.assertEqual(support_models["next_action"], "install_or_configure_dependency")
        self.assertIn("sentence_transformers", support_models["missing_dependencies"])
        self.assertIn('python -m pip install "citationguard[models]"', support_models["install_hint"])
        self.assertIn('python -m pip install -e ".[models]"', support_models["install_hint"])
        self.assertLess(
            support_models["install_hint"].index('python -m pip install "citationguard[models]"'),
            support_models["install_hint"].index('python -m pip install -e ".[models]"'),
        )
        self.assertEqual(support_models["warmup_command"], "citeguard models warmup")
        self.assertFalse(support_models["model_weights_loaded"])
        self.assertTrue(any("Remote landing-page evidence" in warning for warning in status["warnings"]))
        mcp_warning = next(warning for warning in status["warnings"] if "MCP SDK is not installed" in warning)
        self.assertIn("python -m pip install citationguard", mcp_warning)
        self.assertIn("python -m pip install -e .", mcp_warning)
        self.assertLess(
            mcp_warning.index("python -m pip install citationguard"),
            mcp_warning.index("python -m pip install -e ."),
        )

    def test_status_reports_production_support_engine_when_model_dependencies_are_available(self):
        status = environment_status(env={"CITEGUARD_SOURCES": "arxiv"}, module_checker=lambda name: True)

        support_models = status["support_models"]
        self.assertTrue(support_models["deep_models_available"])
        self.assertEqual(support_models["engine"], "production_ensemble")
        self.assertEqual(support_models["next_action"], "continue")
        self.assertEqual(support_models["missing_dependencies"], [])
        self.assertEqual(support_models["install_hint"], "")
        self.assertEqual(support_models["model_dependencies"], {
            "sentence_transformers": True,
            "transformers": True,
            "torch": True,
        })

    def test_remote_evidence_can_be_enabled(self):
        env = {
            "CITEGUARD_REMOTE_EVIDENCE": "true",
            "CITEGUARD_HTTP_TIMEOUT": "7",
            "CITEGUARD_HTTP_RETRIES": "2",
            "CITEGUARD_HTTP_RETRY_BACKOFF": "0.5",
            "CITEGUARD_HTTP_MIN_INTERVAL": "0.25",
            "CITEGUARD_EVIDENCE_TIMEOUT": "3",
            "CITEGUARD_MAILTO": "researcher@university.edu",
            "CITEGUARD_SOURCES": "openalex,s2",
            "SEMANTIC_SCHOLAR_API_KEY": "test-key",
        }

        self.assertTrue(remote_evidence_enabled(env=env))
        self.assertEqual(http_timeout(env=env), 7)
        self.assertEqual(http_retries(env=env), 2)
        self.assertEqual(http_retry_backoff(env=env), 0.5)
        self.assertEqual(http_min_interval(env=env), 0.25)
        self.assertEqual(evidence_timeout(env=env), 3)
        status = environment_status(env=env)
        self.assertTrue(status["remote_evidence_enabled"])
        self.assertTrue(status["remote_evidence_policy"]["enabled"])
        self.assertTrue(status["polite_access"]["compliant"])
        self.assertEqual(status["polite_access"]["status"], "configured")
        self.assertEqual(status["polite_access"]["configured_contact_required_sources"], ["openalex"])
        self.assertEqual(status["polite_access"]["next_action"], "continue")
        self.assertEqual(status["http_timeout_seconds"], 7)
        self.assertEqual(status["http_retries"], 2)
        self.assertEqual(status["http_retry_backoff_seconds"], 0.5)
        self.assertEqual(status["http_min_interval_seconds"], 0.25)
        self.assertEqual(status["http_user_agent"], f"{EXPECTED_USER_AGENT} (mailto:researcher@university.edu)")
        self.assertEqual(status["evidence_timeout_seconds"], 3)
        source_health = status["source_health"]
        self.assertEqual(source_health["mode"], "live")
        self.assertEqual(source_health["schema_version"], SOURCE_HEALTH_SCHEMA_VERSION)
        self.assertFalse(source_health["live_check_performed"])
        self.assertEqual(source_health["summary"]["status_counts"]["configured_not_checked"], 2)
        self.assertFalse(source_health["summary"]["degraded"])
        self.assertEqual(source_health["summary"]["failure_count"], 0)
        self.assertEqual(source_health["summary"]["failure_details"], [])
        self.assertEqual(source_health["summary"]["failure_kind_counts"], {})
        self.assertEqual(source_health["summary"]["failure_kind_sources"], {})
        self.assertIsNone(source_health["summary"]["retry_after_seconds"])
        self.assertEqual(source_health["summary"]["retry_after_sources"], [])
        self.assertEqual(source_health["summary"]["retry_guidance"], "inspect_source_health")
        self.assertEqual(source_health["summary"]["sources_configured"], ["openalex", "semantic_scholar"])
        self.assertEqual(source_health["summary"]["sources_checked"], [])
        self.assertEqual(source_health["summary"]["sources_responded"], [])
        self.assertEqual(source_health["summary"]["sources_unchecked"], ["openalex", "semantic_scholar"])
        self.assertEqual(source_health["summary"]["sources_available"], [])
        self.assertEqual(source_health["summary"]["next_action"], "inspect_source_health")
        self.assertEqual(source_health["summary"]["confidence_effect"], "not_checked")
        self.assertEqual(
            source_health["summary"]["interpretation"],
            "run_live_health_check_before_drawing_source_reliability_conclusions",
        )
        self.assertEqual([item["name"] for item in source_health["sources"]], ["openalex", "semantic_scholar"])
        self.assertEqual(source_health["sources"][0]["http_retries"], 2)
        self.assertEqual(source_health["sources"][0]["http_retry_backoff_seconds"], 0.5)
        self.assertEqual(source_health["sources"][0]["http_min_interval_seconds"], 0.25)
        self.assertEqual(source_health["sources"][0]["http_user_agent"], f"{EXPECTED_USER_AGENT} (mailto:researcher@university.edu)")
        self.assertTrue(source_health["sources"][0]["mailto_configured"])
        self.assertEqual(source_health["sources"][0]["polite_access"]["status"], "configured")
        self.assertEqual(source_health["sources"][1]["polite_access"]["status"], "not_required")
        self.assertTrue(source_health["sources"][1]["api_key_configured"])

    def test_missing_cache_parent_is_ok_when_ancestor_is_writable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "missing", "verification_cache.sqlite")
            status = environment_status(env={"CITEGUARD_CACHE": path})

        cache_status = status["cache_status"]
        self.assertEqual(cache_status["path"], path)
        self.assertFalse(cache_status["exists"])
        self.assertFalse(cache_status["parent_exists"])
        self.assertTrue(cache_status["parent_writable"])
        self.assertEqual(cache_status["next_action"], "continue")
        self.assertTrue(any("will create it on first verification" in warning for warning in status["warnings"]))

    def test_invalid_timeout_is_reported_by_status(self):
        status = environment_status(
            env={
                "CITEGUARD_HTTP_TIMEOUT": "0",
                "CITEGUARD_HTTP_RETRIES": "-1",
                "CITEGUARD_HTTP_RETRY_BACKOFF": "-0.1",
                "CITEGUARD_HTTP_MIN_INTERVAL": "-0.1",
                "CITEGUARD_EVIDENCE_TIMEOUT": "abc",
            }
        )

        self.assertIsNone(status["http_timeout_seconds"])
        self.assertIsNone(status["http_retries"])
        self.assertIsNone(status["http_retry_backoff_seconds"])
        self.assertIsNone(status["http_min_interval_seconds"])
        self.assertIsNone(status["evidence_timeout_seconds"])
        self.assertTrue(any("CITEGUARD_HTTP_TIMEOUT" in warning for warning in status["warnings"]))
        self.assertTrue(any("CITEGUARD_HTTP_RETRIES" in warning for warning in status["warnings"]))
        self.assertTrue(any("CITEGUARD_HTTP_RETRY_BACKOFF" in warning for warning in status["warnings"]))
        self.assertTrue(any("CITEGUARD_HTTP_MIN_INTERVAL" in warning for warning in status["warnings"]))
        self.assertTrue(any("CITEGUARD_EVIDENCE_TIMEOUT" in warning for warning in status["warnings"]))

    def test_environment_status_reports_non_sensitive_cache_statistics(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            source = CachingMetadataSource(
                FakeHealthSource(
                    "memory",
                    records=[CitationRecord(citation_id="cached-paper", title="Cached Paper")],
                ),
                db_path=path,
            )
            source.search("Cached Paper", top_k=5)

            status = environment_status(env={"CITEGUARD_CACHE": path})

        cache_status = status["cache_status"]
        self.assertEqual(cache_status["path"], path)
        self.assertTrue(cache_status["inspect_ok"])
        self.assertTrue(cache_status["exists"])
        self.assertEqual(cache_status["entries"], 1)
        self.assertEqual(cache_status["entry_prefixes"]["search"], 1)
        self.assertTrue(cache_status["parent_exists"])
        self.assertTrue(cache_status["parent_writable"])
        self.assertEqual(cache_status["next_action"], "continue")

    def test_source_health_reports_invalid_source_without_live_query(self):
        health = source_health_status(env={"CITEGUARD_SOURCES": "openalex,not-a-source"})

        self.assertEqual(health["mode"], "live")
        self.assertEqual(health["sources"][0]["status"], "configured_not_checked")
        self.assertEqual(health["sources"][1]["status"], "invalid_config")
        self.assertEqual(health["sources"][0]["next_action"], "inspect_source_health")
        self.assertEqual(health["sources"][0]["confidence_effect"], "not_checked")
        self.assertEqual(health["sources"][1]["next_action"], "fix_configuration")
        self.assertEqual(health["sources"][1]["confidence_effect"], "invalid_configuration")
        self.assertEqual(health["sources"][1]["recovery_code"], "invalid_input")
        self.assertEqual(health["sources"][1]["retry_guidance"], "fix_configuration")
        self.assertTrue(health["summary"]["degraded"])
        self.assertEqual(health["summary"]["invalid_sources"], ["not-a-source"])
        self.assertEqual(health["summary"]["recovery_code"], "invalid_input")
        self.assertEqual(health["summary"]["next_action"], "fix_configuration")
        self.assertIsNone(health["summary"]["retry_after_seconds"])
        self.assertEqual(health["summary"]["retry_after_sources"], [])
        self.assertEqual(health["summary"]["retry_guidance"], "fix_configuration")
        self.assertEqual(health["summary"]["confidence_effect"], "invalid_configuration")
        self.assertEqual(
            health["summary"]["interpretation"],
            "invalid_source_configuration_must_be_fixed_before_source_reliability_conclusions",
        )

    def test_source_health_can_probe_sources_when_explicitly_requested(self):
        health = source_health_status(
            env={
                "CITEGUARD_SOURCES": "openalex,crossref,arxiv",
                "CITEGUARD_HTTP_TIMEOUT": "1",
                "CITEGUARD_HTTP_RETRIES": "0",
            },
            check_live=True,
            source_factory=fake_health_source_factory,
        )

        self.assertTrue(health["live_check_performed"])
        self.assertEqual(health["health_query"], "Attention Is All You Need")
        by_name = {item["name"]: item for item in health["sources"]}
        self.assertEqual(by_name["openalex"]["status"], "available")
        self.assertEqual(by_name["openalex"]["response_count"], 1)
        self.assertEqual(by_name["openalex"]["next_action"], "continue")
        self.assertEqual(by_name["openalex"]["confidence_effect"], "none")
        self.assertEqual(by_name["openalex"]["interpretation"], "source_health_ok")
        self.assertEqual(by_name["crossref"]["status"], "empty")
        self.assertEqual(by_name["crossref"]["response_count"], 0)
        self.assertEqual(by_name["crossref"]["next_action"], "continue")
        self.assertEqual(by_name["crossref"]["confidence_effect"], "none")
        self.assertEqual(by_name["arxiv"]["status"], "unavailable")
        self.assertEqual(by_name["arxiv"]["failure"]["code"], "timeout")
        self.assertEqual(by_name["arxiv"]["failure"]["kind"], "timeout")
        self.assertEqual(by_name["arxiv"]["next_action"], "retry_or_check_source_health")
        self.assertEqual(by_name["arxiv"]["confidence_effect"], "source_unavailable")
        self.assertEqual(by_name["arxiv"]["interpretation"], "source_outage_lowers_confidence_not_fabrication_evidence")
        self.assertEqual(by_name["arxiv"]["recovery_code"], "timeout")
        self.assertEqual(health["summary"]["status_counts"], {"available": 1, "empty": 1, "unavailable": 1})
        self.assertEqual(health["summary"]["sources_configured"], ["openalex", "crossref", "arxiv"])
        self.assertEqual(health["summary"]["sources_checked"], ["openalex", "crossref", "arxiv"])
        self.assertEqual(health["summary"]["sources_responded"], ["openalex", "crossref"])
        self.assertEqual(health["summary"]["sources_unchecked"], [])
        self.assertEqual(health["summary"]["sources_available"], ["openalex", "crossref"])
        self.assertEqual(health["summary"]["sources_failed"], ["arxiv"])
        self.assertEqual(health["summary"]["failure_count"], 1)
        self.assertEqual(health["summary"]["failure_details"][0]["source"], "arxiv")
        self.assertEqual(health["summary"]["failure_details"][0]["code"], "timeout")
        self.assertFalse(health["summary"]["failure_details"][0]["cache_hit"])
        self.assertEqual(health["summary"]["failure_details"][0]["attempt_count"], 0)
        self.assertEqual(health["summary"]["failure_details"][0]["retry_count"], 0)
        self.assertEqual(health["summary"]["failure_kind_counts"], {"timeout": 1})
        self.assertEqual(health["summary"]["failure_kind_sources"], {"timeout": ["arxiv"]})
        self.assertIsNone(health["summary"]["retry_after_seconds"])
        self.assertEqual(health["summary"]["retry_after_sources"], [])
        self.assertEqual(health["summary"]["retry_guidance"], "retry_or_check_source_health")
        self.assertTrue(health["summary"]["degraded"])
        self.assertFalse(health["summary"]["all_checked_sources_failed"])
        self.assertEqual(health["summary"]["confidence_effect"], "partial_source_limited")
        self.assertEqual(
            health["summary"]["interpretation"],
            "source_outage_lowers_confidence_not_fabrication_evidence",
        )
        self.assertEqual(health["summary"]["recovery_code"], "timeout")
        self.assertEqual(health["summary"]["next_action"], "retry_or_check_source_health")

    def test_source_health_summarizes_failure_kinds_for_agent_branching(self):
        health = source_health_status(
            env={"CITEGUARD_SOURCES": "arxiv,crossref,semantic_scholar"},
            check_live=True,
            source_factory=mixed_failure_health_source_factory,
        )

        self.assertEqual(health["summary"]["sources_failed"], ["arxiv", "crossref", "semantic_scholar"])
        self.assertEqual(
            health["summary"]["failure_kind_counts"],
            {"timeout": 1, "invalid_json": 1, "rate_limited": 1},
        )
        self.assertEqual(
            health["summary"]["failure_kind_sources"],
            {"timeout": ["arxiv"], "invalid_json": ["crossref"], "rate_limited": ["semantic_scholar"]},
        )
        details = {item["source"]: item for item in health["summary"]["failure_details"]}
        sources = {item["name"]: item for item in health["sources"]}
        self.assertEqual(details["crossref"]["code"], "source_unavailable")
        self.assertEqual(details["crossref"]["kind"], "invalid_json")
        self.assertEqual(details["crossref"]["status_code"], 200)
        self.assertEqual(details["crossref"]["error"], "JSONDecodeError")
        self.assertEqual(sources["crossref"]["next_action"], "retry_or_check_source_health")
        self.assertEqual(sources["crossref"]["recovery_code"], "source_unavailable")
        self.assertEqual(sources["crossref"]["retry_guidance"], "retry_or_check_source_health")
        self.assertEqual(details["semantic_scholar"]["attempt_count"], 2)
        self.assertEqual(details["semantic_scholar"]["retry_count"], 1)
        self.assertEqual(details["semantic_scholar"]["retry_after_seconds"], 2.0)
        self.assertEqual(details["semantic_scholar"]["retry_delay_seconds"], 1.5)
        self.assertEqual(sources["semantic_scholar"]["retry_after_seconds"], 2.0)
        self.assertEqual(sources["semantic_scholar"]["retry_delay_seconds"], 1.5)
        self.assertEqual(sources["semantic_scholar"]["retry_guidance"], "wait_before_retry")
        self.assertEqual(health["summary"]["retry_after_seconds"], 2.0)
        self.assertEqual(health["summary"]["retry_after_sources"], ["semantic_scholar"])
        self.assertEqual(health["summary"]["retry_delay_seconds"], 1.5)
        self.assertEqual(health["summary"]["retry_delay_sources"], ["semantic_scholar"])
        self.assertEqual(health["summary"]["retry_guidance"], "wait_before_retry")
        self.assertTrue(health["summary"]["all_checked_sources_failed"])
        self.assertEqual(health["summary"]["confidence_effect"], "all_sources_unavailable")
        self.assertEqual(
            health["summary"]["interpretation"],
            "source_outage_lowers_confidence_not_fabrication_evidence",
        )
        self.assertEqual(health["summary"]["recovery_code"], "timeout")
        self.assertEqual(health["summary"]["next_action"], "retry_or_check_source_health")

    def test_source_health_zero_retry_after_does_not_request_wait(self):
        health = source_health_status(
            env={"CITEGUARD_SOURCES": "semantic_scholar"},
            check_live=True,
            source_factory=expired_retry_after_health_source_factory,
        )

        source = health["sources"][0]
        self.assertEqual(source["retry_after_seconds"], 0.0)
        self.assertIsNone(source["retry_delay_seconds"])
        self.assertEqual(source["retry_guidance"], "retry_or_check_source_health")
        self.assertEqual(health["summary"]["retry_after_seconds"], 0.0)
        self.assertEqual(health["summary"]["retry_after_sources"], ["semantic_scholar"])
        self.assertIsNone(health["summary"]["retry_delay_seconds"])
        self.assertEqual(health["summary"]["retry_delay_sources"], [])
        self.assertEqual(health["summary"]["retry_guidance"], "retry_or_check_source_health")
        self.assertEqual(health["summary"]["next_action"], "retry_or_check_source_health")

    def test_environment_status_can_include_live_source_probe(self):
        status = environment_status(
            env={"CITEGUARD_SOURCES": "openalex"},
            check_sources=True,
            health_query="Custom Probe Paper",
            source_factory=fake_health_source_factory,
        )

        self.assertTrue(status["source_health"]["live_check_performed"])
        self.assertEqual(status["source_health"]["health_query"], "Custom Probe Paper")
        self.assertEqual(status["source_health"]["sources"][0]["status"], "available")
        self.assertEqual(status["source_health"]["summary"]["sources_available"], ["openalex"])
        self.assertEqual(status["source_health"]["summary"]["confidence_effect"], "none")
        self.assertEqual(status["source_health"]["summary"]["interpretation"], "source_health_ok")
        self.assertEqual(status["source_health"]["summary"]["next_action"], "continue")

    def test_source_health_marks_all_checked_sources_failed(self):
        health = source_health_status(
            env={"CITEGUARD_SOURCES": "arxiv"},
            check_live=True,
            source_factory=fake_health_source_factory,
        )

        self.assertEqual(health["sources"][0]["status"], "unavailable")
        self.assertEqual(health["sources"][0]["next_action"], "retry_or_check_source_health")
        self.assertEqual(health["sources"][0]["confidence_effect"], "source_unavailable")
        self.assertEqual(
            health["sources"][0]["interpretation"],
            "source_outage_lowers_confidence_not_fabrication_evidence",
        )
        self.assertEqual(health["summary"]["sources_failed"], ["arxiv"])
        self.assertTrue(health["summary"]["all_checked_sources_failed"])
        self.assertEqual(health["summary"]["confidence_effect"], "all_sources_unavailable")
        self.assertEqual(
            health["summary"]["interpretation"],
            "source_outage_lowers_confidence_not_fabrication_evidence",
        )
        self.assertEqual(health["summary"]["recovery_code"], "timeout")
        self.assertEqual(health["summary"]["next_action"], "retry_or_check_source_health")

    def test_source_health_reports_cache_hit_without_failure(self):
        health = source_health_status(
            env={"CITEGUARD_SOURCES": "openalex"},
            check_live=True,
            source_factory=cached_health_source_factory,
        )

        source = health["sources"][0]
        self.assertEqual(source["status"], "available")
        self.assertTrue(source["cache_hit"])
        self.assertEqual(source["next_action"], "continue")
        self.assertEqual(source["confidence_effect"], "none")
        self.assertEqual(source["retry_guidance"], "continue")
        self.assertNotIn("failure", source)
        self.assertFalse(health["summary"]["degraded"])
        self.assertEqual(health["summary"]["failure_count"], 0)
        self.assertEqual(health["summary"]["failure_details"], [])
        self.assertEqual(health["summary"]["failure_kind_counts"], {})
        self.assertEqual(health["summary"]["failure_kind_sources"], {})
        self.assertIsNone(health["summary"]["retry_after_seconds"])
        self.assertEqual(health["summary"]["retry_after_sources"], [])
        self.assertEqual(health["summary"]["retry_guidance"], "continue")
        self.assertEqual(health["summary"]["confidence_effect"], "none")
        self.assertEqual(health["summary"]["interpretation"], "source_health_ok")
        self.assertEqual(health["summary"]["next_action"], "continue")

    def test_fixture_citations_enable_offline_source(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl", delete=False) as handle:
            handle.write(
                json.dumps(
                    {
                        "citation_id": "fixture-1",
                        "title": "Fixture Citation",
                        "authors": ["Test Author"],
                        "year": 2026,
                        "source": "fixture",
                    }
                )
                + "\n"
            )
            path = handle.name

        try:
            records = load_fixture_records(path)
            source = build_configured_source(env={"CITEGUARD_FIXTURE_CITATIONS": path})
            status = environment_status(env={"CITEGUARD_FIXTURE_CITATIONS": path})
            health = source_health_status(env={"CITEGUARD_FIXTURE_CITATIONS": path})
        finally:
            os.unlink(path)

        self.assertEqual(records[0].title, "Fixture Citation")
        self.assertEqual(source.all_records()[0].citation_id, "fixture-1")
        self.assertEqual(status["fixture_citations_path"], path)
        self.assertEqual(health["mode"], "fixture")
        self.assertEqual(health["schema_version"], SOURCE_HEALTH_SCHEMA_VERSION)
        self.assertEqual(health["sources"][0]["status"], "offline_fixture")
        self.assertEqual(health["sources"][0]["polite_access"]["status"], "fixture_bypasses_live_sources")
        self.assertEqual(health["sources"][0]["next_action"], "continue")
        self.assertEqual(health["sources"][0]["confidence_effect"], "none")
        self.assertEqual(health["sources"][0]["interpretation"], "fixture_mode_bypasses_live_sources")
        self.assertEqual(health["summary"]["mode"], "fixture")
        self.assertEqual(health["summary"]["sources_configured"], ["fixture"])
        self.assertEqual(health["summary"]["sources_available"], ["fixture"])
        self.assertFalse(health["summary"]["degraded"])
        self.assertEqual(health["summary"]["failure_count"], 0)
        self.assertEqual(health["summary"]["failure_details"], [])
        self.assertEqual(health["summary"]["failure_kind_counts"], {})
        self.assertEqual(health["summary"]["failure_kind_sources"], {})
        self.assertIsNone(health["summary"]["retry_after_seconds"])
        self.assertEqual(health["summary"]["retry_after_sources"], [])
        self.assertEqual(health["summary"]["retry_guidance"], "continue")
        self.assertEqual(health["summary"]["confidence_effect"], "none")
        self.assertEqual(health["summary"]["interpretation"], "fixture_mode_bypasses_live_sources")
        self.assertEqual(health["summary"]["next_action"], "continue")
        self.assertTrue(status["polite_access"]["compliant"])
        self.assertEqual(status["polite_access"]["status"], "fixture_bypasses_live_sources")
        self.assertEqual(status["polite_access"]["next_action"], "continue")
        self.assertTrue(any("fixture" in warning.lower() for warning in status["warnings"]))

    def test_fixture_citations_can_load_manifest_records_object(self):
        fixture = {
            "fixture_manifest": {
                "fixture_format": "manifest_records",
                "deterministic": True,
                "record_count": 1,
            },
            "records": [
                {
                    "citation_id": "fixture-object-1",
                    "title": "Manifest Fixture Citation",
                    "authors": ["Test Author"],
                    "year": 2026,
                    "source": "fixture",
                    "metadata": {
                        "cache_provenance": {
                            "operation": "search",
                            "source": "metadata_source",
                            "query": "Manifest Fixture Citation",
                            "raw_match_score": 1.0,
                        }
                    },
                }
            ],
        }
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(fixture, handle)
            path = handle.name

        try:
            records = load_fixture_records(path)
            source = build_configured_source(env={"CITEGUARD_FIXTURE_CITATIONS": path})
        finally:
            os.unlink(path)

        self.assertEqual(records[0].title, "Manifest Fixture Citation")
        self.assertEqual(records[0].metadata["cache_provenance"]["raw_match_score"], 1.0)
        self.assertEqual(source.all_records()[0].metadata["cache_provenance"]["operation"], "search")


if __name__ == "__main__":
    unittest.main()
