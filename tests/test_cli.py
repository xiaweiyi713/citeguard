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
        self.assertIn("--claim", payload["error"]["message"])

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
        self.assertTrue(payload["risk_ranking"][0]["counterevidence_review"])
        self.assertEqual(payload["risk_ranking"][0]["counterevidence_reason"], "unresolved_citation")

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
        self.assertEqual(payload["risk_ranking"][0]["input_mode"], "citation_set")
        self.assertEqual(payload["risk_ranking"][0]["supporting_citation_count"], 2)
        self.assertEqual(payload["risk_ranking"][0]["next_action"], "keep_claim")

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
        self.assertEqual(payload["source_failure_mode"], "none")
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
