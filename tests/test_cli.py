"""Tests for the CiteGuard command line interface."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from unittest import mock

from citeguard import cli as cli_module
from citeguard.cli import run
from citeguard.runtime import build_configured_source
from citeguard.verification import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.verification.cache import CachingMetadataSource
from citeguard.verification import SupportAssessment


class EntailingSupportBackend:
    backend_name = "fake_nli"

    def is_available(self):
        return True

    def assess(self, claim_text, evidence_text):
        return SupportAssessment(
            backend_name="transformers_nli",
            score=0.91,
            passed=True,
            rationale="Fake entailment for CLI testing.",
            details={
                "probabilities": {
                    "entailment": 0.91,
                    "contradiction": 0.02,
                    "neutral": 0.07,
                }
            },
        )


class ContradictingSupportBackend:
    backend_name = "fake_nli"

    def is_available(self):
        return True

    def assess(self, claim_text, evidence_text):
        return SupportAssessment(
            backend_name="transformers_nli",
            score=0.88,
            passed=True,
            rationale="Fake contradiction for CLI testing.",
            details={
                "probabilities": {
                    "entailment": 0.05,
                    "contradiction": 0.88,
                    "neutral": 0.07,
                }
            },
        )


class FullTextOnlySupportBackend:
    backend_name = "fake_nli"

    def is_available(self):
        return True

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


class FailingMetadataSource:
    name = "timeout_source"

    def all_records(self):
        return []

    def lookup(self, candidate):
        return None

    def search(self, query, top_k=5):
        raise TimeoutError("source timed out")


class RateLimitedMetadataSource:
    name = "rate_limited_source"

    class HTTPDiagnostics:
        last_error_code = ""
        last_error_kind = ""
        last_error = ""
        last_status_code = None
        last_url = ""
        last_cache_hit = False
        last_attempt_count = 0
        last_retry_count = 0
        last_retry_after_seconds = None
        last_retry_delay_seconds = None

        def fail(self):
            self.last_error_code = "source_unavailable"
            self.last_error_kind = "rate_limited"
            self.last_error = "http_429"
            self.last_status_code = 429
            self.last_url = "https://api.example.test/search"
            self.last_cache_hit = False
            self.last_attempt_count = 2
            self.last_retry_count = 1
            self.last_retry_after_seconds = 2.0
            self.last_retry_delay_seconds = 1.5

    def __init__(self):
        self.http_client = self.HTTPDiagnostics()

    def all_records(self):
        return []

    def lookup(self, candidate):
        self.http_client.fail()
        return None

    def search(self, query, top_k=5):
        self.http_client.fail()
        return []


class CLITests(unittest.TestCase):
    def setUp(self):
        self.record = CitationRecord(
            citation_id="paper-1",
            title="GhostCite: A Large-Scale Analysis of Citation Validity",
            authors=["Zhe Xu", "Lin Wang"],
            year=2026,
            venue="arXiv",
            doi="10.48550/arxiv.2602.06718",
            source="memory",
            abstract="This paper studies citation validity and fabricated references in large language models.",
        )
        self.source = InMemoryMetadataSource([self.record])

    def test_status_prints_json_without_live_source(self):
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            code = run(["status"], stdout=stdout, source=self.source)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["service"], "CiteGuard")
        self.assertIn("configured_sources", payload)
        self.assertTrue(payload["cache_status"]["inspect_ok"])
        self.assertEqual(payload["cache_status"]["next_action"], "continue")

    def test_compact_output_can_follow_subcommand(self):
        stdout = io.StringIO()

        code = run(["status", "--compact"], stdout=stdout, source=self.source)

        self.assertEqual(code, 0)
        self.assertNotIn("\n  ", stdout.getvalue())
        self.assertEqual(json.loads(stdout.getvalue())["service"], "CiteGuard")

    def test_batch_help_documents_all_reference_input_shapes(self):
        parser = cli_module.build_parser()

        for command in ("audit", "support-set", "support-audit"):
            stdout = io.StringIO()
            with self.subTest(command=command):
                with mock.patch("sys.stdout", stdout), self.assertRaises(SystemExit) as raised:
                    parser.parse_args([command, "--help"])

                self.assertEqual(raised.exception.code, 0)
                help_text = stdout.getvalue()
                self.assertIn("JSON/JSONL", help_text)
                self.assertIn("Markdown/LaTeX/BibTeX/BBL/DOCX/plain-text", help_text)

    def test_status_can_request_live_source_probe(self):
        stdout = io.StringIO()
        status = mock.Mock(
            return_value={
                "service": "CiteGuard",
                "source_health": {"live_check_performed": True, "sources": []},
            }
        )

        with mock.patch.dict(run.__globals__, {"environment_status": status}):
            code = run(
                ["status", "--check-sources", "--health-query", "Custom Probe Paper"],
                stdout=stdout,
                source=self.source,
            )

        self.assertEqual(code, 0)
        status.assert_called_once_with(check_sources=True, health_query="Custom Probe Paper")
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["source_health"]["live_check_performed"])

    def test_verify_prints_verification_result(self):
        stdout = io.StringIO()

        code = run(
            [
                "verify",
                "--title",
                "GhostCite: A Large-Scale Analysis of Citation Validity",
                "--year",
                "2026",
            ],
            source=self.source,
            stdout=stdout,
        )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], "verified")
        self.assertEqual(payload["next_action"], "keep")
        self.assertEqual(payload["canonical_record"]["doi"], "10.48550/arxiv.2602.06718")

    def test_verify_prints_structured_source_failure_details(self):
        stdout = io.StringIO()

        code = run(
            ["verify", "--title", "Slow Source Paper"],
            source=FailingMetadataSource(),
            stdout=stdout,
        )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], "not_found")
        self.assertEqual(payload["sources_checked"], ["timeout_source"])
        self.assertEqual(payload["sources_available"], [])
        self.assertEqual(payload["sources_failed"], ["timeout_source"])
        self.assertEqual(payload["source_failure_details"][0]["source"], "timeout_source")
        self.assertEqual(payload["source_failure_details"][0]["code"], "timeout")
        self.assertEqual(payload["source_failure_mode"], "all_sources_failed")
        self.assertTrue(payload["outage_limited"])
        self.assertEqual(payload["next_action"], "retry_or_check_source_health")
        self.assertEqual(payload["confidence"], 0.35)

    def test_verify_requires_citation_input(self):
        stderr = io.StringIO()

        code = run(["verify"], source=self.source, stderr=stderr)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["error"]["code"], "missing_citation_input")
        self.assertIn("DOI", payload["error"]["recovery"])
        self.assertEqual(payload["error"]["next_action"], "provide_missing_input")

    def test_cache_inspect_and_clear_use_machine_readable_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.source, db_path=path)
            cached.search("GhostCite", top_k=5)

            inspect_stdout = io.StringIO()
            inspect_code = run(["cache", "inspect", "--path", path], stdout=inspect_stdout)
            clear_stdout = io.StringIO()
            clear_code = run(["cache", "clear", "--path", path], stdout=clear_stdout)

        self.assertEqual(inspect_code, 0)
        inspect_payload = json.loads(inspect_stdout.getvalue())
        self.assertEqual(inspect_payload["entries"], 1)
        self.assertEqual(inspect_payload["entry_prefixes"]["search"], 1)
        self.assertEqual(clear_code, 0)
        clear_payload = json.loads(clear_stdout.getvalue())
        self.assertEqual(clear_payload["cleared_entries"], 1)
        self.assertEqual(clear_payload["remaining_entries"], 0)
        self.assertEqual(clear_payload["clear_filters"], {"operation": None, "source": None})

    def test_cache_inspect_can_filter_selected_counts_by_operation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.source, db_path=path)
            cached.search("GhostCite", top_k=5)
            cached.lookup(CitationRecord(citation_id="candidate", title=self.record.title, year=2026))

            stdout = io.StringIO()
            code = run(["cache", "inspect", "--path", path, "--operation", "lookup"], stdout=stdout)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["entries"], 2)
        self.assertEqual(payload["entry_prefixes"]["search"], 1)
        self.assertEqual(payload["entry_prefixes"]["lookup"], 1)
        self.assertEqual(payload["selected_entries"], 1)
        self.assertEqual(payload["selected_entry_prefixes"]["lookup"], 1)
        self.assertEqual(payload["selected_entry_prefixes"]["search"], 0)
        self.assertEqual(payload["inspect_filters"], {"operation": "lookup", "source": None})
        self.assertNotIn("GhostCite", json.dumps(payload, sort_keys=True))

    def test_cache_clear_can_filter_by_operation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.source, db_path=path)
            cached.search("GhostCite", top_k=5)
            cached.lookup(CitationRecord(citation_id="candidate", title=self.record.title, year=2026))

            clear_stdout = io.StringIO()
            clear_code = run(["cache", "clear", "--path", path, "--operation", "lookup"], stdout=clear_stdout)
            inspect_stdout = io.StringIO()
            inspect_code = run(["cache", "inspect", "--path", path], stdout=inspect_stdout)

        self.assertEqual(clear_code, 0)
        clear_payload = json.loads(clear_stdout.getvalue())
        self.assertEqual(clear_payload["cleared_entries"], 1)
        self.assertEqual(clear_payload["remaining_entries"], 1)
        self.assertEqual(clear_payload["clear_filters"], {"operation": "lookup", "source": None})
        self.assertEqual(clear_payload["selected_entry_prefixes"]["lookup"], 1)
        self.assertEqual(inspect_code, 0)
        inspect_payload = json.loads(inspect_stdout.getvalue())
        self.assertEqual(inspect_payload["entries"], 1)
        self.assertEqual(inspect_payload["entry_prefixes"]["search"], 1)
        self.assertEqual(inspect_payload["entry_prefixes"]["lookup"], 0)

    def test_cache_clear_can_filter_by_source_without_deleting_nonmatches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.source, db_path=path)
            cached.search("GhostCite", top_k=5)

            missing_stdout = io.StringIO()
            missing_code = run(["cache", "clear", "--path", path, "--source", "openalex"], stdout=missing_stdout)
            inspect_stdout = io.StringIO()
            inspect_code = run(["cache", "inspect", "--path", path], stdout=inspect_stdout)
            matching_stdout = io.StringIO()
            matching_code = run(["cache", "clear", "--path", path, "--source", "metadata_source"], stdout=matching_stdout)

        self.assertEqual(missing_code, 0)
        missing_payload = json.loads(missing_stdout.getvalue())
        self.assertEqual(missing_payload["cleared_entries"], 0)
        self.assertEqual(missing_payload["remaining_entries"], 1)
        self.assertEqual(missing_payload["clear_filters"], {"operation": None, "source": "openalex"})
        self.assertEqual(inspect_code, 0)
        inspect_payload = json.loads(inspect_stdout.getvalue())
        self.assertEqual(inspect_payload["entries"], 1)
        self.assertEqual(inspect_payload["entry_prefixes"]["search"], 1)
        self.assertEqual(matching_code, 0)
        matching_payload = json.loads(matching_stdout.getvalue())
        self.assertEqual(matching_payload["cleared_entries"], 1)
        self.assertEqual(matching_payload["remaining_entries"], 0)
        self.assertEqual(matching_payload["clear_filters"], {"operation": None, "source": "metadata_source"})

    def test_cache_export_writes_offline_replay_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_db = os.path.join(tmpdir, "cache.sqlite")
            fixture_path = os.path.join(tmpdir, "fixture.json")
            cached = CachingMetadataSource(self.source, db_path=cache_db)
            cached.search("GhostCite", top_k=5)

            stdout = io.StringIO()
            code = run(["cache", "export", "--path", cache_db, "--output", fixture_path], stdout=stdout)
            replay_source = build_configured_source(env={"CITEGUARD_FIXTURE_CITATIONS": fixture_path})

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["record_count"], 1)
        self.assertEqual(replay_source.all_records()[0].title, self.record.title)

    def test_cache_export_can_write_deterministic_replay_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            outputs = []
            manifests = []
            for index in range(2):
                cache_db = os.path.join(tmpdir, f"cache-{index}.sqlite")
                fixture_path = os.path.join(tmpdir, f"fixture-{index}.json")
                cached = CachingMetadataSource(self.source, db_path=cache_db)
                cached.search("GhostCite", top_k=5)

                stdout = io.StringIO()
                code = run(
                    [
                        "cache",
                        "export",
                        "--path",
                        cache_db,
                        "--deterministic",
                        "--output",
                        fixture_path,
                    ],
                    stdout=stdout,
                )
                self.assertEqual(code, 0)
                manifests.append(json.loads(stdout.getvalue()))
                with open(fixture_path, encoding="utf-8") as handle:
                    outputs.append(json.load(handle))

            replay_source = build_configured_source(env={"CITEGUARD_FIXTURE_CITATIONS": os.path.join(tmpdir, "fixture-0.json")})

        self.assertEqual(outputs[0], outputs[1])
        self.assertTrue(manifests[0]["deterministic"])
        self.assertIsNone(manifests[0]["exported_at"])
        self.assertIsNone(manifests[0]["cache_oldest_entry_timestamp"])
        self.assertIsNone(manifests[0]["cache_newest_entry_timestamp"])
        metadata = outputs[0][0]["metadata"]
        self.assertNotIn("cache_updated_at", metadata)
        self.assertNotIn("timestamp", metadata["cache_provenance"])
        self.assertEqual(replay_source.all_records()[0].title, self.record.title)

    def test_cache_export_can_write_manifest_replay_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_db = os.path.join(tmpdir, "cache.sqlite")
            fixture_path = os.path.join(tmpdir, "fixture.json")
            cached = CachingMetadataSource(self.source, db_path=cache_db)
            cached.search("GhostCite", top_k=5)

            stdout = io.StringIO()
            code = run(
                [
                    "cache",
                    "export",
                    "--path",
                    cache_db,
                    "--deterministic",
                    "--include-manifest",
                    "--output",
                    fixture_path,
                ],
                stdout=stdout,
            )
            with open(fixture_path, encoding="utf-8") as handle:
                fixture = json.load(handle)
            replay_source = build_configured_source(env={"CITEGUARD_FIXTURE_CITATIONS": fixture_path})

        self.assertEqual(code, 0)
        manifest = json.loads(stdout.getvalue())
        self.assertEqual(manifest["fixture_format"], "manifest_records")
        self.assertEqual(fixture["fixture_manifest"]["fixture_format"], "manifest_records")
        self.assertTrue(fixture["fixture_manifest"]["deterministic"])
        self.assertEqual(fixture["fixture_manifest"]["record_count"], 1)
        self.assertEqual(fixture["records"][0]["title"], self.record.title)
        replayed = replay_source.all_records()[0]
        self.assertEqual(replayed.title, self.record.title)
        self.assertEqual(replayed.metadata["cache_provenance"]["operation"], "search")

    def test_cache_export_can_filter_replay_fixture_by_operation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_db = os.path.join(tmpdir, "cache.sqlite")
            fixture_path = os.path.join(tmpdir, "fixture.json")
            cached = CachingMetadataSource(self.source, db_path=cache_db)
            cached.search("GhostCite", top_k=5)
            cached.lookup(CitationRecord(citation_id="candidate", title=self.record.title, year=2026))

            stdout = io.StringIO()
            code = run(
                [
                    "cache",
                    "export",
                    "--path",
                    cache_db,
                    "--deterministic",
                    "--operation",
                    "lookup",
                    "--output",
                    fixture_path,
                ],
                stdout=stdout,
            )
            with open(fixture_path, encoding="utf-8") as handle:
                fixture = json.load(handle)
            replay_source = build_configured_source(env={"CITEGUARD_FIXTURE_CITATIONS": fixture_path})

        self.assertEqual(code, 0)
        manifest = json.loads(stdout.getvalue())
        self.assertEqual(manifest["cache_entry_count"], 2)
        self.assertEqual(manifest["selected_cache_entry_count"], 1)
        self.assertEqual(manifest["selected_cache_entry_prefixes"]["lookup"], 1)
        self.assertEqual(manifest["selected_cache_entry_prefixes"]["search"], 0)
        self.assertEqual(manifest["export_filters"]["operation"], "lookup")
        self.assertIsNone(manifest["export_filters"]["source"])
        self.assertEqual(fixture[0]["metadata"]["cache_provenance"]["operation"], "lookup")
        self.assertEqual(replay_source.all_records()[0].title, self.record.title)

    def test_cache_export_prints_fixture_payload_without_output_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_db = os.path.join(tmpdir, "cache.sqlite")
            cached = CachingMetadataSource(self.source, db_path=cache_db)
            cached.search("GhostCite", top_k=5)
            stdout = io.StringIO()

            code = run(["cache", "export", "--path", cache_db], stdout=stdout)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["record_count"], 1)
        self.assertEqual(payload["records"][0]["title"], self.record.title)

    def test_cache_export_output_file_error_includes_command_and_filename(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cache_db = os.path.join(tmpdir, "cache.sqlite")
            missing_dir = os.path.join(tmpdir, "missing")
            output_path = os.path.join(missing_dir, "fixture.json")
            cached = CachingMetadataSource(self.source, db_path=cache_db)
            cached.search("GhostCite", top_k=5)
            stderr = io.StringIO()

            code = run(
                ["cache", "export", "--path", cache_db, "--output", output_path],
                stderr=stderr,
            )

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "file_error")
        self.assertEqual(payload["error"]["details"]["command"], "cache")
        self.assertEqual(payload["error"]["details"]["cache_command"], "export")
        self.assertEqual(payload["error"]["details"]["field"], "output")
        self.assertEqual(payload["error"]["details"]["filename"], output_path)
        self.assertIsInstance(payload["error"]["details"]["errno"], int)

    def test_support_checks_claim_against_citation(self):
        stdout = io.StringIO()

        code = run(
            [
                "support",
                "--claim",
                "GhostCite studies citation validity.",
                "--title",
                "GhostCite: A Large-Scale Analysis of Citation Validity",
                "--lang",
                "en",
            ],
            source=self.source,
            support_backend=EntailingSupportBackend(),
            stdout=stdout,
        )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], "supported")
        self.assertEqual(payload["engine"], "ensemble")
        self.assertEqual(payload["lang"], "en")
        self.assertEqual(payload["evidence_scope"], "abstract")
        self.assertEqual(payload["next_action"], "keep_claim")
        self.assertEqual(payload["resolution"]["verdict"], "matched")
        self.assertFalse(payload["counterevidence_review"])

    def test_support_resolution_exposes_source_outage_status(self):
        stdout = io.StringIO()

        code = run(
            [
                "support",
                "--claim",
                "Slow Source Paper supports this claim.",
                "--title",
                "Slow Source Paper",
            ],
            source=FailingMetadataSource(),
            support_backend=EntailingSupportBackend(),
            stdout=stdout,
        )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], "insufficient_evidence")
        self.assertEqual(payload["next_action"], "retry_or_check_source_health")
        self.assertEqual(payload["resolution"]["verdict"], "not_found")
        self.assertEqual(payload["resolution"]["source_failure_mode"], "all_sources_failed")
        self.assertTrue(payload["resolution"]["outage_limited"])

    def test_support_accepts_lawful_full_text_excerpt(self):
        stdout = io.StringIO()
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-2",
                    title="Sparse Retrieval for Citation Auditing",
                    authors=["Zhe Xu"],
                    year=2026,
                    source="memory",
                )
            ]
        )

        code = run(
            [
                "support",
                "--claim",
                "Sparse retrieval improves citation audit recall.",
                "--title",
                "Sparse Retrieval for Citation Auditing",
                "--full-text",
                "The lawful full-text excerpt shows sparse retrieval improves citation audit recall.",
            ],
            source=source,
            support_backend=FullTextOnlySupportBackend(),
            stdout=stdout,
        )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], "supported")
        self.assertEqual(payload["evidence_scope"], "full_text")
        self.assertEqual(payload["evidence"]["source_field"], "user_full_text_excerpt_1")

    def test_support_accepts_lawful_full_text_excerpt_file(self):
        stdout = io.StringIO()
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-2",
                    title="Sparse Retrieval for Citation Auditing",
                    authors=["Zhe Xu"],
                    year=2026,
                    source="memory",
                )
            ]
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as handle:
            handle.write("The lawful full-text excerpt shows sparse retrieval improves citation audit recall.")
            excerpt_path = handle.name

        try:
            code = run(
                [
                    "support",
                    "--claim",
                    "Sparse retrieval improves citation audit recall.",
                    "--title",
                    "Sparse Retrieval for Citation Auditing",
                    "--full-text-file",
                    excerpt_path,
                ],
                source=source,
                support_backend=FullTextOnlySupportBackend(),
                stdout=stdout,
            )
        finally:
            os.unlink(excerpt_path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], "supported")
        self.assertEqual(payload["evidence_scope"], "full_text")
        self.assertEqual(payload["evidence"]["source_field"], "user_full_text_file_1")

    def test_support_accepts_lawful_full_text_pdf_file(self):
        stdout = io.StringIO()
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-2",
                    title="Sparse Retrieval for Citation Auditing",
                    authors=["Zhe Xu"],
                    year=2026,
                    source="memory",
                )
            ]
        )
        with tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as handle:
            handle.write(b"%PDF-1.4\n% local lawful test fixture\n")
            pdf_path = handle.name

        try:
            with mock.patch.object(
                cli_module,
                "_read_pdf_text",
                return_value="The lawful full-text excerpt shows sparse retrieval improves citation audit recall.",
            ):
                code = run(
                    [
                        "support",
                        "--claim",
                        "Sparse retrieval improves citation audit recall.",
                        "--title",
                        "Sparse Retrieval for Citation Auditing",
                        "--full-text-file",
                        pdf_path,
                    ],
                    source=source,
                    support_backend=FullTextOnlySupportBackend(),
                    stdout=stdout,
                )
        finally:
            os.unlink(pdf_path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], "supported")
        self.assertEqual(payload["evidence_scope"], "full_text")
        self.assertEqual(payload["evidence"]["source_field"], "user_full_text_file_1")

    def test_support_pdf_file_reports_missing_optional_dependency(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as handle:
            handle.write(b"%PDF-1.4\n% local lawful test fixture\n")
            pdf_path = handle.name

        try:
            with mock.patch.object(cli_module.importlib, "import_module", side_effect=ImportError):
                code = run(
                    [
                        "support",
                        "--claim",
                        "Sparse retrieval improves citation audit recall.",
                        "--title",
                        "Sparse Retrieval for Citation Auditing",
                        "--full-text-file",
                        pdf_path,
                    ],
                    source=self.source,
                    support_backend=FullTextOnlySupportBackend(),
                    stderr=stderr,
                )
        finally:
            os.unlink(pdf_path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(payload["error"]["details"]["command"], "support")
        self.assertEqual(payload["error"]["details"]["field"], "full_text_file")
        self.assertEqual(payload["error"]["details"]["dependency"], "pypdf")

    def test_support_requires_citation_input(self):
        stderr = io.StringIO()

        code = run(
            ["support", "--claim", "GhostCite studies citation validity."],
            source=self.source,
            support_backend=EntailingSupportBackend(),
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_citation_input")

    def test_support_requires_non_empty_claim(self):
        stderr = io.StringIO()

        code = run(
            ["support", "--claim", "", "--title", "GhostCite"],
            source=self.source,
            support_backend=EntailingSupportBackend(),
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_claim")

    def test_support_set_checks_one_claim_against_many_citations(self):
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {"title": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks"},
                    {"title": "GhostCite: A Large-Scale Analysis of Citation Validity", "year": 2026},
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                [
                    "support-set",
                    path,
                    "--claim",
                    "GhostCite studies citation validity.",
                    "--lang",
                    "en",
                ],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stdout=stdout,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], "supported")
        self.assertEqual(payload["summary"]["supported"], 1)
        self.assertEqual(payload["summary"]["insufficient_evidence"], 1)
        self.assertEqual(payload["risk"], "low")
        self.assertEqual(payload["lang"], "en")
        self.assertEqual(payload["evidence_scope"], "abstract")
        self.assertFalse(payload["counterevidence_review"])
        self.assertEqual(payload["support_mode"], "single_strong_support")
        self.assertEqual(payload["supporting_citation_count"], 1)
        self.assertEqual(payload["contradicting_citation_count"], 0)
        self.assertEqual(payload["support_mode_details"]["decision"], "one_strong_citation_supports_claim")
        self.assertEqual(payload["support_mode_details"]["supported_indexes"], [1])
        self.assertEqual(payload["support_mode_details"]["insufficient_evidence_indexes"], [0])
        self.assertIn(
            "no_unstated_multi_hop_or_full_text_support",
            payload["support_mode_details"]["policy"],
        )

    def test_support_set_can_read_markdown_references_directly(self):
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
            handle.write(
                "## References\n\n"
                "1. Xu, Zhe and Wang, Lin. GhostCite: A Large-Scale Analysis of Citation Validity. "
                "arXiv, 2026. DOI: 10.48550/arxiv.2602.06718.\n"
            )
            path = handle.name

        try:
            code = run(
                [
                    "support-set",
                    path,
                    "--claim",
                    "GhostCite studies citation validity.",
                    "--lang",
                    "en",
                ],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stdout=stdout,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], "supported")
        self.assertEqual(payload["summary"]["supported"], 1)
        self.assertEqual(payload["support_mode"], "single_strong_support")
        self.assertEqual(payload["results"][0]["resolution"]["verdict"], "matched")
        self.assertEqual(payload["input_source_paths"], [path])
        self.assertEqual(payload["input_source_formats"], ["markdown"])
        self.assertEqual(payload["input_source_indexes"], [1])
        self.assertEqual(payload["input_source_locators"], [f"{path}#citation-1"])
        self.assertEqual(payload["input_source_line_starts"], [3])
        self.assertEqual(payload["input_source_line_ends"], [3])
        self.assertEqual(payload["results"][0]["resolution"]["input_source_path"], path)
        self.assertEqual(payload["results"][0]["resolution"]["input_source_line_start"], 3)
        self.assertEqual(payload["results"][0]["resolution"]["input_source_line_end"], 3)
        self.assertEqual(
            payload["results"][0]["resolution"]["title"],
            "GhostCite: A Large-Scale Analysis of Citation Validity",
        )
        self.assertEqual(payload["results"][0]["resolution"]["year"], 2026)

    def test_support_set_reads_full_text_excerpts_from_json(self):
        stdout = io.StringIO()
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-2",
                    title="Sparse Retrieval for Citation Auditing",
                    authors=["Zhe Xu"],
                    year=2026,
                    source="memory",
                )
            ]
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "title": "Sparse Retrieval for Citation Auditing",
                        "full_text": "The lawful full-text excerpt shows sparse retrieval improves citation audit recall.",
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                [
                    "support-set",
                    path,
                    "--claim",
                    "Sparse retrieval improves citation audit recall.",
                ],
                source=source,
                support_backend=FullTextOnlySupportBackend(),
                stdout=stdout,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], "supported")
        self.assertEqual(payload["evidence_scope"], "full_text")
        self.assertEqual(payload["evidence"][0]["source_field"], "user_full_text_excerpt_1")
        self.assertEqual(payload["evidence"][0]["index"], 0)
        self.assertEqual(payload["support_mode"], "single_strong_support")

    def test_support_set_reads_full_text_excerpt_file_from_json(self):
        stdout = io.StringIO()
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-2",
                    title="Sparse Retrieval for Citation Auditing",
                    authors=["Zhe Xu"],
                    year=2026,
                    source="memory",
                )
            ]
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as excerpt:
            excerpt.write("The lawful full-text excerpt shows sparse retrieval improves citation audit recall.")
            excerpt_path = excerpt.name
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "title": "Sparse Retrieval for Citation Auditing",
                        "full_text_file": excerpt_path,
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                [
                    "support-set",
                    path,
                    "--claim",
                    "Sparse retrieval improves citation audit recall.",
                ],
                source=source,
                support_backend=FullTextOnlySupportBackend(),
                stdout=stdout,
            )
        finally:
            os.unlink(path)
            os.unlink(excerpt_path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], "supported")
        self.assertEqual(payload["evidence_scope"], "full_text")
        self.assertEqual(payload["evidence"][0]["source_field"], "user_full_text_file_1")
        self.assertEqual(payload["evidence"][0]["index"], 0)

    def test_support_set_reads_full_text_pdf_file_from_json(self):
        stdout = io.StringIO()
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-2",
                    title="Sparse Retrieval for Citation Auditing",
                    authors=["Zhe Xu"],
                    year=2026,
                    source="memory",
                )
            ]
        )
        with tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as pdf:
            pdf.write(b"%PDF-1.4\n% local lawful test fixture\n")
            pdf_path = pdf.name
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "title": "Sparse Retrieval for Citation Auditing",
                        "full_text_file": pdf_path,
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            with mock.patch.object(
                cli_module,
                "_read_pdf_text",
                return_value="The lawful full-text excerpt shows sparse retrieval improves citation audit recall.",
            ):
                code = run(
                    [
                        "support-set",
                        path,
                        "--claim",
                        "Sparse retrieval improves citation audit recall.",
                    ],
                    source=source,
                    support_backend=FullTextOnlySupportBackend(),
                    stdout=stdout,
                )
        finally:
            os.unlink(path)
            os.unlink(pdf_path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["verdict"], "supported")
        self.assertEqual(payload["evidence_scope"], "full_text")
        self.assertEqual(payload["evidence"][0]["source_field"], "user_full_text_file_1")

    def test_support_set_requires_citation_input_per_item(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump([{"title": "GhostCite: A Large-Scale Analysis of Citation Validity"}, {}], handle)
            path = handle.name

        try:
            code = run(
                ["support-set", path, "--claim", "GhostCite studies citation validity."],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stderr=stderr,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_citation_input")
        self.assertEqual(payload["error"]["details"]["index"], 2)

    def test_support_set_rejects_invalid_full_text_file_type_with_item_index(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                        "full_text_file": {"path": "not-a-string"},
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                ["support-set", path, "--claim", "GhostCite studies citation validity."],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stderr=stderr,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(payload["error"]["details"]["command"], "support-set")
        self.assertEqual(payload["error"]["details"]["index"], 1)
        self.assertEqual(payload["error"]["details"]["field"], "full_text_file")

    def test_support_set_reports_missing_full_text_file_with_item_index(self):
        stderr = io.StringIO()
        missing_path = os.path.join(tempfile.gettempdir(), "citeguard-missing-full-text-evidence.txt")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                        "full_text_file": missing_path,
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                ["support-set", path, "--claim", "GhostCite studies citation validity."],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stderr=stderr,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "file_error")
        self.assertEqual(payload["error"]["details"]["command"], "support-set")
        self.assertEqual(payload["error"]["details"]["index"], 1)
        self.assertEqual(payload["error"]["details"]["field"], "full_text_file")
        self.assertEqual(payload["error"]["details"]["filename"], missing_path)

    def test_support_set_requires_non_empty_claim(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump([{"title": "GhostCite: A Large-Scale Analysis of Citation Validity"}], handle)
            path = handle.name

        try:
            code = run(
                ["support-set", path, "--claim", ""],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stderr=stderr,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_claim")

    def test_argparse_errors_are_json(self):
        stderr = io.StringIO()

        code = run(["support", "--title", "GhostCite"], source=self.source, stderr=stderr)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "argument_parse_error")
        self.assertEqual(payload["error"]["next_action"], "repair_input")
        self.assertEqual(payload["error"]["details"]["prog"], "citeguard support")
        self.assertEqual(payload["error"]["details"]["command"], "support")
        self.assertEqual(payload["error"]["details"]["arguments"], ["--claim"])
        self.assertIn("--claim", payload["error"]["message"])

    def test_runtime_configuration_errors_include_field_details(self):
        stderr = io.StringIO()

        with mock.patch.dict(os.environ, {"CITEGUARD_SOURCES": "bad"}, clear=False):
            code = run(["verify", "--title", "GhostCite"], stderr=stderr)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(payload["error"]["details"]["command"], "verify")
        self.assertEqual(payload["error"]["details"]["field"], "CITEGUARD_SOURCES")
        self.assertEqual(payload["error"]["details"]["source"], "environment")
        self.assertEqual(payload["error"]["details"]["invalid_values"], ["bad"])
        self.assertIn("openalex", payload["error"]["details"]["valid_values"])

    def test_numeric_runtime_configuration_errors_include_expected_details(self):
        stderr = io.StringIO()

        with mock.patch.dict(os.environ, {"CITEGUARD_HTTP_TIMEOUT": "0"}, clear=False):
            code = run(["verify", "--title", "GhostCite"], stderr=stderr)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(payload["error"]["details"]["command"], "verify")
        self.assertEqual(payload["error"]["details"]["field"], "CITEGUARD_HTTP_TIMEOUT")
        self.assertEqual(payload["error"]["details"]["source"], "environment")
        self.assertEqual(payload["error"]["details"]["expected"], "positive integer")
        self.assertEqual(payload["error"]["details"]["received"], "0")

    def test_support_audit_reads_claim_citation_pairs(self):
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "claim": "GhostCite studies citation validity.",
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                        "lang": "en",
                    },
                    {
                        "claim": "An unknown paper supports a claim.",
                        "title": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks",
                    },
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                ["support-audit", path],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stdout=stdout,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["supported"], 1)
        self.assertEqual(payload["summary"]["insufficient_evidence"], 1)
        self.assertEqual(payload["results"][0]["lang"], "en")
        self.assertEqual(payload["risk_ranking"][0]["evidence_scope"], "none")
        self.assertEqual(payload["risk_ranking"][0]["next_action"], "resolve_citation_identity")
        self.assertEqual(payload["risk_ranking"][0]["risk_reason"], "citation_identity_unresolved")
        self.assertEqual(payload["risk_ranking"][0]["suggested_fix"]["kind"], "resolve_citation_identity")
        self.assertTrue(payload["risk_ranking"][0]["suggested_fix"]["requires_user_confirmation"])
        self.assertEqual(
            payload["risk_ranking"][0]["suggested_fix"]["policy"],
            "resolve_identity_before_judging_support",
        )
        self.assertEqual(payload["risk_ranking"][0]["support_confidence"], 0.0)
        self.assertEqual(payload["risk_ranking"][0]["support_engine"], "none")
        self.assertEqual(payload["risk_ranking"][0]["resolution_verdict"], "not_found")
        self.assertEqual(payload["risk_ranking"][0]["resolved_title"], "")
        self.assertEqual(payload["risk_ranking"][0]["evidence_source_field"], "none")
        self.assertEqual(payload["risk_ranking"][0]["evidence_source_name"], "none")
        self.assertEqual(payload["risk_ranking"][1]["support_engine"], "ensemble")
        self.assertEqual(payload["risk_ranking"][1]["risk_reason"], "available_evidence_supports_claim")
        self.assertEqual(payload["risk_ranking"][1]["suggested_fix"]["kind"], "keep_claim")
        self.assertFalse(payload["risk_ranking"][1]["suggested_fix"]["requires_user_confirmation"])
        self.assertEqual(payload["risk_ranking"][1]["resolution_verdict"], "matched")
        self.assertEqual(payload["risk_ranking"][1]["resolved_title"], "GhostCite: A Large-Scale Analysis of Citation Validity")
        self.assertEqual(payload["risk_ranking"][1]["resolved_year"], 2026)
        self.assertEqual(payload["risk_ranking"][1]["evidence_source_field"], "abstract_sentence_1")
        self.assertEqual(payload["risk_ranking"][1]["evidence_source_name"], "memory")
        self.assertTrue(payload["risk_ranking"][0]["counterevidence_review"])
        self.assertEqual(payload["risk_ranking"][0]["counterevidence_reason"], "unresolved_citation")

    def test_support_audit_exposes_source_metadata_quality(self):
        stdout = io.StringIO()
        sparse_record = CitationRecord(
            citation_id="support-sparse",
            title="Sparse Source Metadata for Support Audits",
            authors=["Ada Lovelace"],
            year=2026,
            doi="10.5555/support-sparse",
            abstract="Sparse source metadata improves citation support audits.",
            source="crossref",
            metadata={
                "metadata_quality": {
                    "schema_version": 1,
                    "present_fields": ["title", "authors", "year", "identifier", "abstract"],
                    "missing_fields": ["venue", "url"],
                    "identifiers": {"doi": True, "arxiv_id": False},
                    "completeness": 0.7143,
                    "confidence_effect": "missing_metadata_lowers_confidence_not_fabrication_evidence",
                }
            },
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "claim": "Sparse source metadata improves citation support audits.",
                        "title": "Sparse Source Metadata for Support Audits",
                        "year": 2026,
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                ["support-audit", path],
                source=InMemoryMetadataSource([sparse_record]),
                support_backend=EntailingSupportBackend(),
                stdout=stdout,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        result = payload["results"][0]
        risk_item = payload["risk_ranking"][0]
        self.assertEqual(result["verdict"], "supported")
        self.assertEqual(result["resolution"]["source_metadata_missing_fields"], ["venue", "url"])
        self.assertEqual(result["source_metadata_missing_fields"], ["venue", "url"])
        self.assertEqual(
            result["source_metadata_confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )
        self.assertEqual(risk_item["source_metadata_missing_fields"], ["venue", "url"])
        self.assertEqual(
            risk_item["source_metadata_confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )
        self.assertTrue(risk_item["canonical_metadata_quality"]["identifiers"]["doi"])

    def test_support_audit_accepts_citation_set_items(self):
        stdout = io.StringIO()
        source = InMemoryMetadataSource(
            [
                self.record,
                CitationRecord(
                    citation_id="paper-2",
                    title="Citation Auditing with Metadata Checks",
                    abstract="Metadata checks help citation auditing workflows.",
                    year=2026,
                    source="memory",
                ),
            ]
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "claim": "GhostCite studies citation validity.",
                        "citations": [
                            {"title": "GhostCite: A Large-Scale Analysis of Citation Validity"},
                            {"title": "Citation Auditing with Metadata Checks"},
                        ],
                        "lang": "en",
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                ["support-audit", path],
                source=source,
                support_backend=EntailingSupportBackend(),
                stdout=stdout,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["supported"], 1)
        self.assertEqual(payload["results"][0]["input_mode"], "citation_set")
        self.assertEqual(payload["results"][0]["support_mode"], "multiple_strong_support")
        self.assertEqual(payload["results"][0]["lang"], "en")
        self.assertEqual(payload["results"][0]["evidence_scopes"], ["abstract"])
        self.assertEqual(payload["results"][0]["evidence_source_names"], ["memory"])
        self.assertEqual(payload["results"][0]["evidence_source_fields"], ["abstract_sentence_1"])
        self.assertEqual(
            payload["results"][0]["support_mode_details"]["decision"],
            "multiple_strong_citations_support_claim",
        )
        self.assertEqual(payload["results"][0]["support_mode_details"]["supported_indexes"], [0, 1])
        self.assertEqual(payload["risk_ranking"][0]["input_mode"], "citation_set")
        self.assertEqual(payload["risk_ranking"][0]["risk_reason"], "citation_set_has_multiple_strong_support")
        self.assertEqual(payload["risk_ranking"][0]["suggested_fix"]["kind"], "keep_claim")
        self.assertEqual(payload["risk_ranking"][0]["suggested_fix"]["support_mode"], "multiple_strong_support")
        self.assertEqual(payload["risk_ranking"][0]["supporting_citation_count"], 2)
        self.assertEqual(payload["risk_ranking"][0]["next_action"], "keep_claim")
        self.assertEqual(payload["risk_ranking"][0]["support_engine"], "citation_set")
        self.assertGreater(payload["risk_ranking"][0]["support_confidence"], 0)
        self.assertEqual(payload["risk_ranking"][0]["evidence_scopes"], ["abstract"])
        self.assertEqual(payload["risk_ranking"][0]["evidence_source_names"], ["memory"])
        self.assertEqual(payload["risk_ranking"][0]["evidence_source_fields"], ["abstract_sentence_1"])
        self.assertEqual(
            payload["risk_ranking"][0]["support_mode_details"]["decision"],
            "multiple_strong_citations_support_claim",
        )

    def test_support_audit_rejects_invalid_citation_set_item_with_nested_index(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "claim": "GhostCite studies citation validity.",
                        "citations": [
                            {"title": "GhostCite: A Large-Scale Analysis of Citation Validity"},
                            {"title": 42},
                        ],
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                ["support-audit", path],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stderr=stderr,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(payload["error"]["details"]["command"], "support-audit")
        self.assertEqual(payload["error"]["details"]["index"], 1)
        self.assertEqual(payload["error"]["details"]["citation_index"], 2)
        self.assertEqual(payload["error"]["details"]["field"], "title")

    def test_support_audit_marks_contradicted_for_counterevidence_review(self):
        stdout = io.StringIO()
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-2",
                    title="GhostCite: A Large-Scale Analysis of Citation Validity",
                    authors=["Zhe Xu"],
                    year=2026,
                    source="memory",
                    abstract="This paper shows GhostCite does not study citation validity.",
                )
            ]
        )
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "claim": "GhostCite studies citation validity.",
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                ["support-audit", path],
                source=source,
                support_backend=ContradictingSupportBackend(),
                stdout=stdout,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["results"][0]["verdict"], "contradicted")
        self.assertTrue(payload["risk_ranking"][0]["counterevidence_review"])
        self.assertEqual(payload["risk_ranking"][0]["counterevidence_reason"], "contradicted")
        self.assertEqual(payload["risk_ranking"][0]["next_action"], "rewrite_or_replace_evidence")

    def test_support_audit_reads_jsonl_claim_citation_pairs(self):
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl", delete=False) as handle:
            handle.write(
                json.dumps(
                    {
                        "claim": "GhostCite studies citation validity.",
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                    }
                )
                + "\n"
            )
            handle.write(
                json.dumps(
                    {
                        "claim": "An unknown paper supports a claim.",
                        "title": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks",
                    }
                )
                + "\n"
            )
            path = handle.name

        try:
            code = run(
                ["support-audit", path],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stdout=stdout,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["supported"], 1)
        self.assertEqual(payload["summary"]["insufficient_evidence"], 1)

    def test_support_audit_can_read_markdown_references_with_one_claim(self):
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
            handle.write(
                "# References\n\n"
                "1. Zhe Xu. GhostCite: A Large-Scale Analysis of Citation Validity. 2026.\n"
                "2. Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks. "
                "Journal of Imaginary Methods, 2024.\n"
            )
            path = handle.name

        try:
            code = run(
                [
                    "support-audit",
                    path,
                    "--claim",
                    "GhostCite studies citation validity.",
                ],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stdout=stdout,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["supported"], 1)
        self.assertEqual(payload["summary"]["insufficient_evidence"], 1)
        self.assertEqual(len(payload["results"]), 2)
        self.assertEqual(payload["results"][0]["claim"], "GhostCite studies citation validity.")
        self.assertEqual(payload["results"][0]["input_mode"], "citation")
        self.assertEqual(payload["results"][0]["resolution"]["input_source_path"], path)
        self.assertEqual(payload["results"][0]["resolution"]["input_source_format"], "markdown")
        self.assertEqual(payload["results"][0]["resolution"]["input_source_index"], 1)
        self.assertEqual(payload["risk_ranking"][0]["input_source_path"], path)
        self.assertIn(payload["risk_ranking"][0]["input_source_index"], [1, 2])
        self.assertTrue(str(payload["risk_ranking"][0]["input_source_locator"]).startswith(f"{path}#citation-"))
        self.assertEqual(payload["review_summary"]["total"], 2)
        self.assertEqual(payload["review_summary"]["high_risk_count"], 1)
        traceability = payload["review_summary"]["source_traceability"]
        self.assertTrue(traceability["has_source_backed_items"])
        self.assertEqual(traceability["source_backed_count"], 2)
        self.assertEqual(traceability["source_paths"], [path])
        self.assertEqual(traceability["source_formats"], ["markdown"])
        self.assertEqual(traceability["source_indexes"], [1, 2])
        self.assertEqual(traceability["high_risk_source_indexes"], [2])
        self.assertTrue(traceability["review_required_source_locators"][0].startswith(f"{path}#citation-"))

    def test_support_audit_reference_file_requires_claim(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
            handle.write("# References\n\n1. GhostCite: A Large-Scale Analysis of Citation Validity. 2026.\n")
            path = handle.name

        try:
            code = run(
                ["support-audit", path],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stderr=stderr,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_claim")
        self.assertIn("BibTeX", payload["error"]["message"])
        self.assertIn("BBL", payload["error"]["message"])
        self.assertEqual(payload["error"]["details"]["command"], "support-audit")
        self.assertEqual(payload["error"]["details"]["field"], "claim")

    def test_support_audit_reads_full_text_pdf_file_from_json(self):
        stdout = io.StringIO()
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="paper-2",
                    title="Sparse Retrieval for Citation Auditing",
                    authors=["Zhe Xu"],
                    year=2026,
                    source="memory",
                )
            ]
        )
        with tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as pdf:
            pdf.write(b"%PDF-1.4\n% local lawful test fixture\n")
            pdf_path = pdf.name
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "claim": "Sparse retrieval improves citation audit recall.",
                        "title": "Sparse Retrieval for Citation Auditing",
                        "full_text_file": pdf_path,
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            with mock.patch.object(
                cli_module,
                "_read_pdf_text",
                return_value="The lawful full-text excerpt shows sparse retrieval improves citation audit recall.",
            ):
                code = run(
                    ["support-audit", path],
                    source=source,
                    support_backend=FullTextOnlySupportBackend(),
                    stdout=stdout,
                )
        finally:
            os.unlink(path)
            os.unlink(pdf_path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["supported"], 1)
        self.assertEqual(payload["results"][0]["evidence_scope"], "full_text")
        self.assertEqual(payload["results"][0]["evidence"]["source_field"], "user_full_text_file_1")

    def test_support_audit_requires_citation_input(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump([{"claim": "Missing citation."}], handle)
            path = handle.name

        try:
            code = run(
                ["support-audit", path],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stderr=stderr,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_citation_input")
        self.assertEqual(payload["error"]["details"]["index"], 1)
        self.assertIn("raw_text, title, doi, or arxiv_id", payload["error"]["message"])

    def test_support_audit_rejects_invalid_full_text_file_type_with_item_index(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "claim": "GhostCite studies citation validity.",
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                        "full_text_file": {"path": "not-a-string"},
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                ["support-audit", path],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stderr=stderr,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(payload["error"]["details"]["command"], "support-audit")
        self.assertEqual(payload["error"]["details"]["index"], 1)
        self.assertEqual(payload["error"]["details"]["field"], "full_text_file")

    def test_support_audit_keeps_item_index_when_full_text_precedes_invalid_file(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "claim": "GhostCite studies citation validity.",
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                    },
                    {
                        "claim": "GhostCite studies citation validity.",
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                        "full_text": ["lawful full-text excerpt before the bad file"],
                        "full_text_file": {"path": "not-a-string"},
                    },
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                ["support-audit", path],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stderr=stderr,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(payload["error"]["details"]["command"], "support-audit")
        self.assertEqual(payload["error"]["details"]["index"], 2)
        self.assertEqual(payload["error"]["details"]["field"], "full_text_file")

    def test_support_audit_reports_missing_full_text_file_with_item_index(self):
        stderr = io.StringIO()
        missing_path = os.path.join(tempfile.gettempdir(), "citeguard-missing-support-audit-evidence.txt")
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "claim": "GhostCite studies citation validity.",
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                        "full_text_file": missing_path,
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                ["support-audit", path],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stderr=stderr,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "file_error")
        self.assertEqual(payload["error"]["details"]["command"], "support-audit")
        self.assertEqual(payload["error"]["details"]["index"], 1)
        self.assertEqual(payload["error"]["details"]["field"], "full_text_file")
        self.assertEqual(payload["error"]["details"]["filename"], missing_path)

    def test_support_audit_requires_claim(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump([{"title": "Missing claim."}], handle)
            path = handle.name

        try:
            code = run(
                ["support-audit", path],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stderr=stderr,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_claim")
        self.assertEqual(payload["error"]["details"]["index"], 1)

    def test_support_audit_high_risk_only_filters_results(self):
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
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
                handle,
            )
            path = handle.name

        try:
            code = run(
                ["support-audit", path, "--high-risk-only"],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stdout=stdout,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["filtered"]["original_results"], 2)
        self.assertEqual(payload["filtered"]["returned"], 1)
        self.assertEqual(payload["filtered"]["returned_indexes"], [1])
        self.assertEqual(payload["filtered"]["omitted_indexes"], [0])
        self.assertEqual(payload["review_summary"]["total"], 2)
        self.assertEqual(payload["review_summary"]["high_risk_count"], 1)
        self.assertEqual(payload["review_summary"]["low_risk_count"], 1)
        self.assertEqual(payload["review_summary"]["top_high_risk_indexes"], [1])
        self.assertEqual(payload["review_summary"]["recommended_next_steps"]["first_queue"], "identity_resolution_indexes")
        self.assertEqual(payload["review_summary"]["recommended_next_steps"]["steps"][0]["indexes"], [1])
        self.assertFalse(payload["review_summary"]["source_traceability"]["has_source_backed_items"])
        self.assertEqual(
            payload["filtered"]["omitted_review_summary"]["recommended_next_steps"]["safe_to_keep_indexes"],
            [0],
        )
        self.assertFalse(
            payload["filtered"]["omitted_review_summary"]["source_traceability"]["has_source_backed_items"]
        )
        self.assertEqual(payload["results"][0]["resolution"]["verdict"], "not_found")

    def test_audit_reads_json_list(self):
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                        "year": 2026,
                    },
                    {"title": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks"},
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(["audit", path], source=self.source, stdout=stdout)
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["verified"], 1)
        self.assertEqual(payload["summary"]["not_found"], 1)
        self.assertEqual(payload["review_summary"]["total"], 2)
        self.assertEqual(payload["review_summary"]["high_risk_count"], 1)
        self.assertEqual(payload["review_summary"]["low_risk_count"], 1)
        self.assertEqual(payload["review_summary"]["next_actions"]["keep"], 1)
        self.assertEqual(payload["review_summary"]["next_actions"]["resolve_identifier_or_replace"], 1)
        self.assertEqual(payload["risk_ranking"][0]["risk"], "high")

    def test_audit_risk_ranking_includes_suggested_metadata_fix(self):
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "title": "GhostCite: A Large-Scale Analysis of Citation Validity",
                        "authors": ["Zhe Xu"],
                        "year": 2024,
                        "venue": "Journal of Imaginary Methods",
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(["audit", path], source=self.source, stdout=stdout)
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        risk_item = payload["risk_ranking"][0]
        self.assertEqual(risk_item["verdict"], "metadata_mismatch")
        self.assertEqual(risk_item["next_action"], "review_metadata")
        self.assertEqual(risk_item["mismatched_fields"], ["year", "venue"])
        self.assertIn("GhostCite: A Large-Scale Analysis of Citation Validity", risk_item["suggested_citation"])
        self.assertEqual(risk_item["canonical_year"], 2026)
        self.assertEqual(risk_item["canonical_venue"], "arXiv")
        self.assertEqual(risk_item["canonical_doi"], "10.48550/arxiv.2602.06718")

    def test_audit_risk_ranking_exposes_source_metadata_quality(self):
        stdout = io.StringIO()
        sparse_record = CitationRecord(
            citation_id="sparse",
            title="Sparse Source Metadata for Citation Audits",
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
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump([{"title": "Sparse Source Metadata for Citation Audits", "year": 2026}], handle)
            path = handle.name

        try:
            code = run(["audit", path], source=InMemoryMetadataSource([sparse_record]), stdout=stdout)
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        risk_item = payload["risk_ranking"][0]
        self.assertEqual(risk_item["verdict"], "verified")
        self.assertEqual(risk_item["source_metadata_missing_fields"], ["venue", "abstract", "url"])
        self.assertEqual(
            risk_item["source_metadata_confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )

    def test_audit_risk_ranking_includes_structured_source_failure_details(self):
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump([{"title": "Slow Source Paper"}], handle)
            path = handle.name

        try:
            code = run(["audit", path], source=FailingMetadataSource(), stdout=stdout)
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["results"][0]["sources_failed"], ["timeout_source"])
        self.assertEqual(payload["results"][0]["sources_available"], [])
        self.assertEqual(payload["results"][0]["source_failure_details"][0]["code"], "timeout")
        self.assertEqual(payload["results"][0]["source_failure_mode"], "all_sources_failed")
        self.assertTrue(payload["results"][0]["outage_limited"])
        self.assertEqual(payload["risk_ranking"][0]["sources_failed"], ["timeout_source"])
        self.assertEqual(payload["risk_ranking"][0]["sources_available"], [])
        self.assertEqual(payload["risk_ranking"][0]["source_failure_details"][0]["source"], "timeout_source")
        self.assertEqual(payload["risk_ranking"][0]["source_failure_mode"], "all_sources_failed")
        self.assertTrue(payload["risk_ranking"][0]["outage_limited"])
        self.assertEqual(payload["risk_ranking"][0]["next_action"], "retry_or_check_source_health")
        self.assertIn("inspect source health", payload["risk_ranking"][0]["recommendation"])

    def test_audit_source_failure_details_preserve_retry_after_hint(self):
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump([{"title": "Rate Limited Source Paper"}], handle)
            path = handle.name

        try:
            code = run(["audit", path], source=RateLimitedMetadataSource(), stdout=stdout)
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        result_detail = payload["results"][0]["source_failure_details"][0]
        risk_detail = payload["risk_ranking"][0]["source_failure_details"][0]
        self.assertEqual(result_detail["kind"], "rate_limited")
        self.assertEqual(result_detail["attempt_count"], 2)
        self.assertEqual(result_detail["retry_count"], 1)
        self.assertEqual(result_detail["retry_after_seconds"], 2.0)
        self.assertEqual(result_detail["retry_delay_seconds"], 1.5)
        self.assertEqual(risk_detail["retry_after_seconds"], 2.0)
        self.assertEqual(risk_detail["retry_delay_seconds"], 1.5)
        self.assertEqual(payload["risk_ranking"][0]["next_action"], "retry_or_check_source_health")

    def test_audit_high_risk_only_filters_results(self):
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {"title": "GhostCite: A Large-Scale Analysis of Citation Validity", "year": 2026},
                    {"title": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks"},
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(["audit", path, "--high-risk-only"], source=self.source, stdout=stdout)
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["filtered"]["original_results"], 2)
        self.assertEqual(payload["filtered"]["returned"], 1)
        self.assertEqual(payload["filtered"]["returned_indexes"], [1])
        self.assertEqual(payload["filtered"]["omitted_indexes"], [0])
        self.assertEqual(payload["review_summary"]["total"], 2)
        self.assertEqual(payload["review_summary"]["high_risk_count"], 1)
        self.assertEqual(payload["review_summary"]["low_risk_count"], 1)
        self.assertEqual(payload["review_summary"]["top_high_risk_indexes"], [1])
        self.assertEqual(payload["review_summary"]["recommended_next_steps"]["first_queue"], "identity_resolution_indexes")
        self.assertEqual(payload["review_summary"]["recommended_next_steps"]["steps"][0]["indexes"], [1])
        self.assertEqual(
            payload["filtered"]["omitted_review_summary"]["recommended_next_steps"]["safe_to_keep_indexes"],
            [0],
        )
        self.assertEqual(payload["results"][0]["verdict"], "not_found")
        self.assertTrue(all(item["risk"] == "high" for item in payload["risk_ranking"]))

    def test_audit_reads_jsonl(self):
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl", delete=False) as handle:
            handle.write(json.dumps({"title": "GhostCite: A Large-Scale Analysis of Citation Validity", "year": 2026}) + "\n")
            handle.write(json.dumps({"title": "Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks"}) + "\n")
            path = handle.name

        try:
            code = run(["audit", path], source=self.source, stdout=stdout)
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["verified"], 1)
        self.assertEqual(payload["summary"]["not_found"], 1)

    def test_audit_rejects_non_list_json(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump({"title": "not a list"}, handle)
            path = handle.name

        try:
            code = run(["audit", path], source=self.source, stderr=stderr)
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertIn("must be a JSON list", payload["error"]["message"])
        self.assertEqual(payload["error"]["details"]["command"], "audit")
        self.assertEqual(payload["error"]["details"]["expected"], "JSON list or JSONL object stream")
        self.assertEqual(payload["error"]["details"]["received"], "dict")

    def test_audit_missing_json_file_error_includes_command_and_filename(self):
        stderr = io.StringIO()
        missing_path = os.path.join(tempfile.gettempdir(), "citeguard-missing-audit-input.json")
        try:
            os.unlink(missing_path)
        except FileNotFoundError:
            pass

        code = run(["audit", missing_path], source=self.source, stderr=stderr)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "file_error")
        self.assertEqual(payload["error"]["details"]["command"], "audit")
        self.assertEqual(payload["error"]["details"]["field"], "path")
        self.assertEqual(payload["error"]["details"]["filename"], missing_path)
        self.assertIsInstance(payload["error"]["details"]["errno"], int)

    def test_audit_rejects_non_object_json_items_with_index(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump([{"title": "GhostCite"}, "not an object"], handle)
            path = handle.name

        try:
            code = run(["audit", path], source=self.source, stderr=stderr)
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(payload["error"]["details"]["command"], "audit")
        self.assertEqual(payload["error"]["details"]["index"], 2)
        self.assertEqual(payload["error"]["details"]["expected"], "object")
        self.assertEqual(payload["error"]["details"]["received"], "str")

    def test_audit_rejects_invalid_citation_field_types(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump([{"title": "GhostCite", "year": {"published": 2026}}], handle)
            path = handle.name

        try:
            code = run(["audit", path], source=self.source, stderr=stderr)
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(payload["error"]["details"]["command"], "audit")
        self.assertEqual(payload["error"]["details"]["index"], 1)
        self.assertEqual(payload["error"]["details"]["field"], "year")

    def test_audit_requires_citation_input_per_item(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump([{"title": "GhostCite: A Large-Scale Analysis of Citation Validity"}, {}], handle)
            path = handle.name

        try:
            code = run(["audit", path], source=self.source, stderr=stderr)
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_citation_input")
        self.assertEqual(payload["error"]["details"]["index"], 2)

    def test_invalid_json_error_has_machine_readable_location(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            handle.write("[{")
            path = handle.name

        try:
            code = run(["audit", path], source=self.source, stderr=stderr)
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"]["code"], "invalid_json")
        self.assertEqual(payload["error"]["details"]["command"], "audit")
        self.assertIn("line", payload["error"]["details"])
        self.assertIn("column", payload["error"]["details"])

    def test_support_set_rejects_non_object_jsonl_items_with_index(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl", delete=False) as handle:
            handle.write(json.dumps({"title": "GhostCite"}) + "\n")
            handle.write(json.dumps(["not", "an", "object"]) + "\n")
            path = handle.name

        try:
            code = run(
                ["support-set", path, "--claim", "GhostCite studies citation validity."],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stderr=stderr,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(payload["error"]["details"]["command"], "support-set")
        self.assertEqual(payload["error"]["details"]["index"], 2)
        self.assertEqual(payload["error"]["details"]["expected"], "object")
        self.assertEqual(payload["error"]["details"]["received"], "list")

    def test_support_audit_jsonl_parse_error_includes_command_and_location(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl", delete=False) as handle:
            handle.write(json.dumps({"claim": "A claim.", "title": "GhostCite"}) + "\n")
            handle.write("{bad json\n")
            path = handle.name

        try:
            code = run(
                ["support-audit", path],
                source=self.source,
                support_backend=EntailingSupportBackend(),
                stderr=stderr,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "invalid_json")
        self.assertEqual(payload["error"]["details"]["command"], "support-audit")
        self.assertEqual(payload["error"]["details"]["line"], 2)
        self.assertIn("column", payload["error"]["details"])

    def test_support_audit_missing_jsonl_file_error_includes_command_and_filename(self):
        stderr = io.StringIO()
        missing_path = os.path.join(tempfile.gettempdir(), "citeguard-missing-support-audit-input.jsonl")
        try:
            os.unlink(missing_path)
        except FileNotFoundError:
            pass

        code = run(
            ["support-audit", missing_path],
            source=self.source,
            support_backend=EntailingSupportBackend(),
            stderr=stderr,
        )

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "file_error")
        self.assertEqual(payload["error"]["details"]["command"], "support-audit")
        self.assertEqual(payload["error"]["details"]["field"], "path")
        self.assertEqual(payload["error"]["details"]["filename"], missing_path)

    def test_extract_missing_file_error_includes_command_and_filename(self):
        stderr = io.StringIO()
        missing_path = os.path.join(tempfile.gettempdir(), "citeguard-missing-references.md")
        try:
            os.unlink(missing_path)
        except FileNotFoundError:
            pass

        code = run(["extract", missing_path], stderr=stderr)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "file_error")
        self.assertEqual(payload["error"]["details"]["command"], "extract")
        self.assertEqual(payload["error"]["details"]["field"], "path")
        self.assertEqual(payload["error"]["details"]["filename"], missing_path)

    def test_extract_malformed_docx_error_is_machine_readable(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("wb", suffix=".docx", delete=False) as handle:
            handle.write(b"not a zip")
            docx_path = handle.name

        try:
            code = run(["extract", docx_path], stderr=stderr)
        finally:
            os.unlink(docx_path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "file_error")
        self.assertEqual(payload["error"]["category"], "input_repair")
        self.assertFalse(payload["error"]["retryable"])
        self.assertEqual(payload["error"]["details"]["command"], "extract")
        self.assertEqual(payload["error"]["details"]["field"], "path")
        self.assertEqual(payload["error"]["details"]["filename"], docx_path)
        self.assertIn("Could not read DOCX file", payload["error"]["message"])

    def test_counterevidence_search_returns_candidate_leads(self):
        source = InMemoryMetadataSource(
            [
                self.record,
                CitationRecord(
                    citation_id="paper-2",
                    title="GhostCite Does Not Improve Citation Validity",
                    abstract="GhostCite does not improve citation validity in generated references.",
                    year=2026,
                    source="memory",
                ),
            ]
        )
        stdout = io.StringIO()

        code = run(
            ["counterevidence", "--claim", "GhostCite improves citation validity.", "--top-k", "1"],
            stdout=stdout,
            source=source,
        )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["candidates"][0]["signal"], "explicit_contradiction_cue")
        self.assertIn("improvement_negation", {item["role"] for item in payload["query_plan"]})
        self.assertEqual(len(payload["query_results"]), len(payload["queries"]))
        self.assertIn("improvement_negation", payload["candidates"][0]["matched_query_roles"])
        self.assertEqual(payload["review_summary"]["candidate_count"], 1)
        self.assertEqual(payload["review_summary"]["signal_counts"]["explicit_contradiction_cue"], 1)
        self.assertEqual(payload["review_summary"]["top_candidate"]["signal"], "explicit_contradiction_cue")
        self.assertEqual(
            payload["review_summary"]["recommended_next_steps"]["first_queue"],
            "explicit_contradiction_candidate_indexes",
        )
        self.assertEqual(
            payload["review_summary"]["recommended_next_steps"]["explicit_contradiction_candidate_indexes"],
            [0],
        )
        self.assertEqual(payload["review_summary"]["policy"], "review_leads_not_contradiction_verdicts")
        self.assertEqual(payload["source_failure_mode"], "none")
        self.assertEqual(payload["next_action"], "review_counterevidence_leads")

    def test_counterevidence_search_flags_source_outage_safety_leads(self):
        source = InMemoryMetadataSource(
            [
                self.record,
                CitationRecord(
                    citation_id="source-outage-safety",
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
        stdout = io.StringIO()

        code = run(
            [
                "counterevidence",
                "--claim",
                "A source outage increases confidence that a citation is fabricated.",
                "--top-k",
                "1",
            ],
            stdout=stdout,
            source=source,
        )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["candidates"][0]["signal"], "source_outage_safety_cue")
        self.assertIn("source_outage_safety", {item["role"] for item in payload["query_plan"]})
        self.assertIn("source_outage_safety", payload["candidates"][0]["matched_query_roles"])
        self.assertEqual(
            payload["review_summary"]["recommended_next_steps"]["first_queue"],
            "source_outage_safety_candidate_indexes",
        )
        self.assertEqual(payload["next_action"], "review_counterevidence_leads")

    def test_counterevidence_search_flags_chinese_source_outage_safety_leads(self):
        source = InMemoryMetadataSource(
            [
                self.record,
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
        stdout = io.StringIO()

        code = run(
            [
                "counterevidence",
                "--claim",
                "源不可达会提高引用被判定为伪造的置信度。",
                "--top-k",
                "1",
            ],
            stdout=stdout,
            source=source,
        )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["candidate_count"], 1)
        self.assertEqual(payload["candidates"][0]["signal"], "source_outage_safety_cue")
        self.assertIn("source_outage_safety", {item["role"] for item in payload["query_plan"]})
        self.assertIn("source_outage_safety", payload["candidates"][0]["matched_query_roles"])
        self.assertIn("不能证明引用是伪造的", payload["candidates"][0]["abstract_snippet"])
        self.assertEqual(payload["next_action"], "review_counterevidence_leads")

    def test_counterevidence_requires_claim_and_valid_top_k(self):
        stderr = io.StringIO()
        missing = run(["counterevidence", "--claim", ""], stderr=stderr, source=self.source)

        self.assertEqual(missing, 2)
        payload = json.loads(stderr.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "missing_claim")

        stderr = io.StringIO()
        invalid = run(
            ["counterevidence", "--claim", "GhostCite improves citation validity.", "--top-k", "-1"],
            stderr=stderr,
            source=self.source,
        )

        self.assertEqual(invalid, 2)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"]["code"], "invalid_input")

    def test_support_audit_can_attach_counterevidence_leads(self):
        source = InMemoryMetadataSource(
            [
                self.record,
                CitationRecord(
                    citation_id="paper-2",
                    title="GhostCite Does Not Improve Citation Validity",
                    abstract="GhostCite does not improve citation validity in generated references.",
                    year=2026,
                    source="memory",
                ),
            ]
        )
        stdout = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump(
                [
                    {
                        "claim": "GhostCite improves citation validity.",
                        "title": "A Paper That Does Not Exist Anywhere",
                    }
                ],
                handle,
            )
            path = handle.name

        try:
            code = run(
                [
                    "support-audit",
                    path,
                    "--with-counterevidence",
                    "--counterevidence-top-k",
                    "1",
                ],
                stdout=stdout,
                source=source,
                support_backend=EntailingSupportBackend(),
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["counterevidence_included"])
        self.assertEqual(payload["results"][0]["counterevidence"]["candidate_count"], 1)
        self.assertEqual(payload["risk_ranking"][0]["counterevidence"]["candidates"][0]["signal"], "explicit_contradiction_cue")
        self.assertIn(
            "improvement_negation",
            payload["risk_ranking"][0]["counterevidence"]["candidates"][0]["matched_query_roles"],
        )

    def test_support_audit_reference_file_can_attach_counterevidence_leads(self):
        source = InMemoryMetadataSource(
            [
                self.record,
                CitationRecord(
                    citation_id="paper-2",
                    title="GhostCite Does Not Improve Citation Validity",
                    abstract="GhostCite does not improve citation validity in generated references.",
                    year=2026,
                    source="memory",
                ),
            ]
        )
        stdout = io.StringIO()
        reference_text = """
# References

1. Xu, Zhe and Wang, Lin. GhostCite: A Large-Scale Analysis of Citation Validity. arXiv, 2026. doi:10.48550/arxiv.2602.06718.
2. A Paper That Does Not Exist Anywhere. Journal of Missing Works, 2024.
"""
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
            handle.write(reference_text)
            path = handle.name

        try:
            code = run(
                [
                    "support-audit",
                    path,
                    "--claim",
                    "GhostCite improves citation validity.",
                    "--with-counterevidence",
                    "--counterevidence-top-k",
                    "1",
                ],
                stdout=stdout,
                source=source,
                support_backend=ContradictingSupportBackend(),
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["counterevidence_included"])
        self.assertEqual(len(payload["results"]), 2)
        self.assertEqual(payload["summary"]["contradicted"], 1)
        self.assertEqual(payload["summary"]["insufficient_evidence"], 1)
        self.assertTrue(all(item["counterevidence_review"] for item in payload["results"]))
        self.assertEqual([row["index"] for row in payload["risk_ranking"]], [0, 1])
        self.assertEqual(payload["risk_ranking"][0]["counterevidence"]["candidate_count"], 1)
        self.assertIn(
            "improvement_negation",
            payload["risk_ranking"][0]["counterevidence"]["candidates"][0]["matched_query_roles"],
        )

    def test_support_audit_reference_file_high_risk_only_keeps_counterevidence_traceability(self):
        source = InMemoryMetadataSource(
            [
                self.record,
                CitationRecord(
                    citation_id="paper-2",
                    title="GhostCite Does Not Improve Citation Validity",
                    abstract="GhostCite does not improve citation validity in generated references.",
                    year=2026,
                    source="memory",
                ),
            ]
        )
        stdout = io.StringIO()
        reference_text = """
# References

1. Xu, Zhe and Wang, Lin. GhostCite: A Large-Scale Analysis of Citation Validity. arXiv, 2026. doi:10.48550/arxiv.2602.06718.
2. A Paper That Does Not Exist Anywhere. Journal of Missing Works, 2024.
"""
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
            handle.write(reference_text)
            path = handle.name

        try:
            code = run(
                [
                    "support-audit",
                    path,
                    "--claim",
                    "GhostCite improves citation validity.",
                    "--with-counterevidence",
                    "--counterevidence-top-k",
                    "1",
                    "--high-risk-only",
                ],
                stdout=stdout,
                source=source,
                support_backend=EntailingSupportBackend(),
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["counterevidence_included"])
        self.assertEqual(payload["filtered"]["original_results"], 2)
        self.assertEqual(payload["filtered"]["returned_indexes"], [1])
        self.assertEqual(payload["filtered"]["omitted_indexes"], [0])
        self.assertEqual(payload["filtered"]["omitted_review_summary"]["low_risk_count"], 1)
        self.assertEqual(len(payload["results"]), 1)
        self.assertTrue(payload["results"][0]["counterevidence_review"])
        self.assertEqual(payload["risk_ranking"][0]["index"], 1)
        self.assertEqual(payload["risk_ranking"][0]["counterevidence"]["candidate_count"], 1)
        self.assertEqual(
            payload["risk_ranking"][0]["counterevidence"]["candidates"][0]["signal"],
            "explicit_contradiction_cue",
        )

    def test_support_audit_rejects_invalid_counterevidence_top_k(self):
        stderr = io.StringIO()
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
            json.dump([{"claim": "A claim.", "title": "GhostCite"}], handle)
            path = handle.name

        try:
            code = run(
                ["support-audit", path, "--with-counterevidence", "--counterevidence-top-k", "-1"],
                stderr=stderr,
                source=self.source,
            )
        finally:
            os.unlink(path)

        self.assertEqual(code, 2)
        payload = json.loads(stderr.getvalue())
        self.assertEqual(payload["error"]["code"], "invalid_input")
        self.assertEqual(payload["error"]["details"]["field"], "counterevidence_top_k")


if __name__ == "__main__":
    unittest.main()
