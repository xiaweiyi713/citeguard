"""Tests for shared runtime configuration."""

import json
import os
import tempfile
import unittest

from citeguard.runtime import (
    SOURCE_HEALTH_SCHEMA_VERSION,
    build_configured_source,
    environment_status,
    evidence_timeout,
    http_retries,
    http_retry_backoff,
    http_timeout,
    load_fixture_records,
    remote_evidence_enabled,
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


class RateLimitedDiagnostics:
    last_error_code = "source_unavailable"
    last_error_kind = "rate_limited"
    last_error = "HTTP Error 429: Too Many Requests"
    last_status_code = 429
    last_url = "https://api.semanticscholar.org/graph/v1/paper/search"
    last_cache_hit = False


class CachedHealthSource(FakeHealthSource):
    http_client = FakeHTTPDiagnostics()


class RateLimitedHealthSource(FakeHealthSource):
    http_client = RateLimitedDiagnostics()


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
    if name == "semantic_scholar":
        return RateLimitedHealthSource(name)
    raise TimeoutError("health probe timed out")


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
    def test_remote_evidence_is_disabled_by_default(self):
        self.assertFalse(remote_evidence_enabled(env={}))
        status = environment_status(env={})
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
        self.assertEqual(status["source_health"]["summary"]["next_action"], "inspect_source_health")
        self.assertEqual(status["http_timeout_seconds"], 10)
        self.assertEqual(status["evidence_timeout_seconds"], 2)
        self.assertEqual(status["cache_status"]["path"], status["cache_path"])
        self.assertTrue(status["cache_status"]["inspect_ok"])
        self.assertGreaterEqual(status["cache_status"]["entries"], 0)
        self.assertIn("search", status["cache_status"]["entry_prefixes"])
        self.assertEqual(status["cache_status"]["next_action"], "continue")
        self.assertTrue(any("Remote landing-page evidence" in warning for warning in status["warnings"]))

    def test_remote_evidence_can_be_enabled(self):
        env = {
            "CITEGUARD_REMOTE_EVIDENCE": "true",
            "CITEGUARD_HTTP_TIMEOUT": "7",
            "CITEGUARD_HTTP_RETRIES": "2",
            "CITEGUARD_HTTP_RETRY_BACKOFF": "0.5",
            "CITEGUARD_EVIDENCE_TIMEOUT": "3",
            "CITEGUARD_MAILTO": "researcher@university.edu",
            "CITEGUARD_SOURCES": "openalex,s2",
            "SEMANTIC_SCHOLAR_API_KEY": "test-key",
        }

        self.assertTrue(remote_evidence_enabled(env=env))
        self.assertEqual(http_timeout(env=env), 7)
        self.assertEqual(http_retries(env=env), 2)
        self.assertEqual(http_retry_backoff(env=env), 0.5)
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
        self.assertEqual(source_health["summary"]["sources_configured"], ["openalex", "semantic_scholar"])
        self.assertEqual(source_health["summary"]["sources_checked"], [])
        self.assertEqual(source_health["summary"]["sources_responded"], [])
        self.assertEqual(source_health["summary"]["sources_unchecked"], ["openalex", "semantic_scholar"])
        self.assertEqual(source_health["summary"]["sources_available"], [])
        self.assertEqual(source_health["summary"]["next_action"], "inspect_source_health")
        self.assertEqual([item["name"] for item in source_health["sources"]], ["openalex", "semantic_scholar"])
        self.assertEqual(source_health["sources"][0]["http_retries"], 2)
        self.assertEqual(source_health["sources"][0]["http_retry_backoff_seconds"], 0.5)
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
                "CITEGUARD_EVIDENCE_TIMEOUT": "abc",
            }
        )

        self.assertIsNone(status["http_timeout_seconds"])
        self.assertIsNone(status["http_retries"])
        self.assertIsNone(status["http_retry_backoff_seconds"])
        self.assertIsNone(status["evidence_timeout_seconds"])
        self.assertTrue(any("CITEGUARD_HTTP_TIMEOUT" in warning for warning in status["warnings"]))
        self.assertTrue(any("CITEGUARD_HTTP_RETRIES" in warning for warning in status["warnings"]))
        self.assertTrue(any("CITEGUARD_HTTP_RETRY_BACKOFF" in warning for warning in status["warnings"]))
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
        self.assertTrue(health["summary"]["degraded"])
        self.assertEqual(health["summary"]["invalid_sources"], ["not-a-source"])
        self.assertEqual(health["summary"]["recovery_code"], "invalid_input")
        self.assertEqual(health["summary"]["next_action"], "fix_configuration")

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
        self.assertEqual(by_name["crossref"]["status"], "empty")
        self.assertEqual(by_name["crossref"]["response_count"], 0)
        self.assertEqual(by_name["arxiv"]["status"], "unavailable")
        self.assertEqual(by_name["arxiv"]["failure"]["code"], "timeout")
        self.assertEqual(by_name["arxiv"]["failure"]["kind"], "timeout")
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
        self.assertEqual(health["summary"]["failure_kind_counts"], {"timeout": 1})
        self.assertEqual(health["summary"]["failure_kind_sources"], {"timeout": ["arxiv"]})
        self.assertTrue(health["summary"]["degraded"])
        self.assertFalse(health["summary"]["all_checked_sources_failed"])
        self.assertEqual(health["summary"]["recovery_code"], "timeout")
        self.assertEqual(health["summary"]["next_action"], "retry_or_check_source_health")

    def test_source_health_summarizes_failure_kinds_for_agent_branching(self):
        health = source_health_status(
            env={"CITEGUARD_SOURCES": "arxiv,semantic_scholar"},
            check_live=True,
            source_factory=mixed_failure_health_source_factory,
        )

        self.assertEqual(health["summary"]["sources_failed"], ["arxiv", "semantic_scholar"])
        self.assertEqual(health["summary"]["failure_kind_counts"], {"timeout": 1, "rate_limited": 1})
        self.assertEqual(
            health["summary"]["failure_kind_sources"],
            {"timeout": ["arxiv"], "rate_limited": ["semantic_scholar"]},
        )
        self.assertTrue(health["summary"]["all_checked_sources_failed"])
        self.assertEqual(health["summary"]["recovery_code"], "timeout")
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
        self.assertEqual(status["source_health"]["summary"]["next_action"], "continue")

    def test_source_health_marks_all_checked_sources_failed(self):
        health = source_health_status(
            env={"CITEGUARD_SOURCES": "arxiv"},
            check_live=True,
            source_factory=fake_health_source_factory,
        )

        self.assertEqual(health["sources"][0]["status"], "unavailable")
        self.assertEqual(health["summary"]["sources_failed"], ["arxiv"])
        self.assertTrue(health["summary"]["all_checked_sources_failed"])
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
        self.assertNotIn("failure", source)
        self.assertFalse(health["summary"]["degraded"])
        self.assertEqual(health["summary"]["failure_count"], 0)
        self.assertEqual(health["summary"]["failure_details"], [])
        self.assertEqual(health["summary"]["failure_kind_counts"], {})
        self.assertEqual(health["summary"]["failure_kind_sources"], {})
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
        self.assertEqual(health["summary"]["mode"], "fixture")
        self.assertEqual(health["summary"]["sources_configured"], ["fixture"])
        self.assertEqual(health["summary"]["sources_available"], ["fixture"])
        self.assertFalse(health["summary"]["degraded"])
        self.assertEqual(health["summary"]["failure_count"], 0)
        self.assertEqual(health["summary"]["failure_details"], [])
        self.assertEqual(health["summary"]["failure_kind_counts"], {})
        self.assertEqual(health["summary"]["failure_kind_sources"], {})
        self.assertEqual(health["summary"]["next_action"], "continue")
        self.assertTrue(status["polite_access"]["compliant"])
        self.assertEqual(status["polite_access"]["status"], "fixture_bypasses_live_sources")
        self.assertEqual(status["polite_access"]["next_action"], "continue")
        self.assertTrue(any("fixture" in warning.lower() for warning in status["warnings"]))


if __name__ == "__main__":
    unittest.main()
