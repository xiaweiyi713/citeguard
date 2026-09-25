"""Tests for the versioned evidence provenance object."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from citeguard.cli_input import _normalize_evidence_chunks as normalize_cli_evidence_chunks
from citeguard.evidence import (
    EVIDENCE_OBJECT_SCHEMA_VERSION,
    build_evidence_object,
    local_file_evidence_provenance,
)
from citeguard.graph import CitationRecord
from citeguard.mcp.input import _normalize_evidence_chunks as normalize_mcp_evidence_chunks
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.retrieval.scholarly_clients.evidence import merge_evidence_chunks
from citeguard.retrieval.scholarly_clients.oa_fulltext import OaFulltextFetcher
from citeguard.verification import check_claim_support, parse_citation
from citeguard.verification.support import build_evidence_spans
from citeguard.verifiers import SupportAssessment


class _EntailingBackend:
    backend_name = "evidence-object-test"

    def assess(self, claim_text: str, evidence_text: str) -> SupportAssessment:
        return SupportAssessment(
            backend_name=self.backend_name,
            score=0.94,
            passed=True,
            rationale="fixture evidence entails the claim",
            details={"probabilities": {"entailment": 0.94, "contradiction": 0.02, "neutral": 0.04}},
        )


class EvidenceObjectTests(unittest.TestCase):
    def test_builder_hashes_the_returned_fragment_without_inventing_retrieval_time(self):
        text = "The user-provided excerpt supports the claim."
        payload = build_evidence_object(
            {
                "text": text,
                "source_field": "user_full_text_excerpt_1",
                "source_name": "user_provided",
                "source_locator": "user-provided://full-text-1",
            }
        )

        self.assertEqual(payload["schema_version"], EVIDENCE_OBJECT_SCHEMA_VERSION)
        self.assertEqual(payload["fragment"]["text"], text)
        self.assertEqual(payload["fragment"]["sha256"], "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest())
        self.assertEqual(payload["locator"]["value"], "user-provided://full-text-1")
        self.assertEqual(payload["retrieval"]["method"], "user_provided")
        self.assertIsNone(payload["retrieval"]["retrieved_at"])
        self.assertEqual(payload["license"]["status"], "user_provided_not_verified")
        self.assertEqual(payload["license"]["rights_basis"], "user_provided")

    def test_support_result_keeps_user_full_text_location_and_rights_provenance(self):
        record = CitationRecord(
            citation_id="full-text-fixture",
            title="Evidence Object Support",
            source="fixture",
        )
        candidate = parse_citation(
            title=record.title,
            evidence_chunks=[
                {
                    "text": "The lawful local excerpt directly supports the claim.",
                    "source_field": "user_full_text_file_1",
                    "source_name": "user_provided",
                    "evidence_scope": "full_text",
                    "source_path": "/workspace/evidence.txt",
                    "source_locator": "/workspace/evidence.txt#lines-4-6",
                    "source_line_start": 4,
                    "source_line_end": 6,
                    "retrieved_at": "2026-08-07T00:00:00Z",
                    "retrieval_method": "local_file_read",
                    "license_status": "user_provided_not_verified",
                    "rights_basis": "user_provided",
                }
            ],
        )

        payload = check_claim_support(
            "The local excerpt directly supports the claim.",
            candidate,
            InMemoryMetadataSource([record]),
            backend=_EntailingBackend(),
        ).to_dict()
        evidence = payload["evidence"]
        evidence_object = evidence["evidence_object"]

        self.assertEqual(payload["evidence_scope"], "full_text")
        self.assertEqual(evidence["source_locator"], "/workspace/evidence.txt#lines-4-6")
        self.assertEqual(evidence_object["source"]["path"], "/workspace/evidence.txt")
        self.assertEqual(evidence_object["locator"]["kind"], "line_range")
        self.assertEqual(evidence_object["locator"]["line_start"], 4)
        self.assertEqual(evidence_object["locator"]["line_end"], 6)
        self.assertEqual(evidence_object["retrieval"], {"method": "local_file_read", "retrieved_at": "2026-08-07T00:00:00Z"})
        self.assertEqual(evidence_object["license"]["status"], "user_provided_not_verified")

    def test_duplicate_full_text_span_supersedes_the_same_abstract_text(self):
        text = "The paper directly supports the claim."
        spans = build_evidence_spans(
            CitationRecord(
                citation_id="duplicate-evidence",
                title="Evidence priority",
                abstract=text,
                source="fixture",
                metadata={
                    "evidence_chunks": [
                        {
                            "text": text,
                            "source_field": "user_full_text_excerpt_1",
                            "source_name": "user_provided",
                            "evidence_scope": "full_text",
                            "source_locator": "user-provided://full-text-1",
                        }
                    ]
                },
            )
        )

        selected = next(span for span in spans if span["text"] == text)
        self.assertEqual(selected["evidence_scope"], "full_text")
        self.assertEqual(selected["source_locator"], "user-provided://full-text-1")

    def test_oa_full_text_attaches_timestamped_open_access_provenance(self):
        record = CitationRecord(
            citation_id="oa-fixture",
            title="Open Access Evidence Object",
            source="openalex",
            metadata={
                "open_access": {
                    "is_oa": True,
                    "pdf_url": "",
                    "landing_page_url": "https://example.org/oa-evidence",
                    "license": "cc-by-4.0",
                }
            },
        )
        fetcher = OaFulltextFetcher()
        fetcher._fetch_bytes = lambda url: (
            b"<html><body><p>The open access paper directly supports the claim.</p></body></html>",
            "",
        )

        payload = check_claim_support(
            "The open access paper directly supports the claim.",
            parse_citation(title=record.title),
            InMemoryMetadataSource([record]),
            backend=_EntailingBackend(),
            oa_fulltext_fetcher=fetcher,
        ).to_dict()
        evidence_object = payload["evidence"]["evidence_object"]

        self.assertEqual(payload["evidence_scope"], "full_text")
        self.assertEqual(evidence_object["source"]["name"], "openalex_oa")
        self.assertEqual(evidence_object["retrieval"]["method"], "oa_fulltext_fetch")
        self.assertRegex(evidence_object["retrieval"]["retrieved_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
        self.assertEqual(evidence_object["license"], {
            "status": "open_access_license_known",
            "value": "cc-by-4.0",
            "rights_basis": "source_marked_open_access",
        })
        self.assertEqual(evidence_object["locator"]["kind"], "paragraph_range")
        self.assertEqual(evidence_object["locator"]["value"], "https://example.org/oa-evidence#paragraph-1")
        self.assertEqual(evidence_object["locator"]["paragraph_start"], 1)
        self.assertEqual(evidence_object["locator"]["paragraph_end"], 1)

    def test_cli_and_mcp_full_text_files_add_the_same_local_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "excerpt.txt"
            text = "A local full-text excerpt.\nA second line keeps the locator test honest."
            path.write_text(text, encoding="utf-8")

            cli_chunk = normalize_cli_evidence_chunks({"full_text_file": str(path)}, command="support")[0]
            with mock.patch.dict(os.environ, {"CITEGUARD_ALLOWED_FILE_ROOTS": directory}, clear=False):
                mcp_chunk = normalize_mcp_evidence_chunks(
                    {"full_text_file": str(path)}, tool="check_claim_support_tool"
                )[0]

        for chunk in (cli_chunk, mcp_chunk):
            with self.subTest(source=chunk["source_field"]):
                self.assertEqual(chunk["source_name"], "user_provided")
                self.assertEqual(chunk["source_path"], str(path.resolve()))
                self.assertEqual(chunk["source_locator"], f"{path.resolve()}#lines-1-2")
                self.assertEqual(chunk["source_line_start"], 1)
                self.assertEqual(chunk["source_line_end"], 2)
                self.assertEqual(chunk["char_start"], 0)
                self.assertEqual(chunk["char_end"], len(text))
                self.assertEqual(chunk["retrieval_method"], "local_file_read")
                self.assertRegex(chunk["retrieved_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
                self.assertEqual(chunk["license_status"], "user_provided_not_verified")
                self.assertEqual(chunk["rights_basis"], "user_provided")

    def test_pdf_local_file_provenance_does_not_claim_page_coordinates(self):
        provenance = local_file_evidence_provenance("/workspace/evidence.pdf", "Extracted PDF text.")

        self.assertEqual(provenance["source_locator"], "/workspace/evidence.pdf#extracted-text")
        self.assertNotIn("source_line_start", provenance)
        self.assertEqual(provenance["char_start"], 0)
        self.assertEqual(provenance["char_end"], len("Extracted PDF text."))

    def test_evidence_chunk_merge_keeps_a_zero_character_offset(self):
        chunks = merge_evidence_chunks(
            [
                {
                    "text": "A first character offset must survive deduplication.",
                    "source_field": "user_full_text_file_1",
                    "char_start": 0,
                    "char_end": 52,
                }
            ]
        )

        self.assertEqual(chunks[0]["char_start"], 0)
        self.assertEqual(chunks[0]["char_end"], 52)


if __name__ == "__main__":
    unittest.main()
