"""Compatibility coverage for the versioned CLI and MCP agent output contract."""

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    Draft202012Validator = None

from citeguard.cli import run
from citeguard.contracts import (
    CITATION_VERDICTS,
    CONTRACT_VERSION,
    EVIDENCE_SCOPES,
    RISK_LEVELS,
    SUPPORT_VERDICTS,
    contract_schema_path,
    load_contract_schema,
    with_contract_version,
)
from citeguard.evidence import EVIDENCE_OBJECT_SCHEMA_VERSION
from citeguard.errors import error_payload
from citeguard.graph import CitationRecord
from citeguard.mcp import server
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.verification import STABLE_NEXT_ACTIONS, SupportAssessment, SupportVerdict, Verdict
from citeguard.verification.models import RISK_BY_VERDICT
from citeguard.verification.support import infer_evidence_scope


class EntailingSupportBackend:
    """Deterministic backend for public-contract tests; it is not an eval model."""

    backend_name = "contract-test"

    def is_available(self):
        return True

    def assess(self, claim_text, evidence_text):
        return SupportAssessment(
            backend_name=self.backend_name,
            score=0.91,
            passed=True,
            rationale="Contract test evidence entails the claim.",
            details={
                "probabilities": {
                    "entailment": 0.91,
                    "contradiction": 0.02,
                    "neutral": 0.07,
                }
            },
        )


class AgentOutputContractTests(unittest.TestCase):
    def setUp(self):
        if Draft202012Validator is None:
            self.skipTest("jsonschema is not installed")
        self.schema = load_contract_schema()
        Draft202012Validator.check_schema(self.schema)
        self.record = CitationRecord(
            citation_id="contract-paper",
            title="Contract Testing for Citation Auditors",
            authors=["Ada Reviewer"],
            year=2026,
            venue="Journal of Reproducible Tools",
            doi="10.5555/contract-testing",
            source="fixture",
            abstract="This study evaluates citation auditor output contracts and evidence traceability.",
        )
        self.source = InMemoryMetadataSource([self.record])
        self.previous_source = server._SOURCE
        self.previous_backend = server._SUPPORT_BACKEND
        server._SOURCE = self.source
        server._SUPPORT_BACKEND = EntailingSupportBackend()

    def tearDown(self):
        server._SOURCE = self.previous_source
        server._SUPPORT_BACKEND = self.previous_backend

    def _validator(self, definition: str) -> Draft202012Validator:
        return Draft202012Validator(
            {
                "$schema": self.schema["$schema"],
                "$defs": self.schema["$defs"],
                "$ref": f"#/$defs/{definition}",
            }
        )

    def assert_matches_contract(self, definition: str, payload: dict) -> None:
        errors = sorted(self._validator(definition).iter_errors(payload), key=lambda error: list(error.path))
        self.assertEqual([], errors, "\n".join(error.message for error in errors))

    def test_schema_is_bundled_and_vocabulary_matches_public_python_values(self):
        self.assertTrue(contract_schema_path().is_file())
        definitions = self.schema["$defs"]

        self.assertEqual(tuple(definitions["citation_verdict"]["enum"]), CITATION_VERDICTS)
        self.assertEqual(tuple(verdict.value for verdict in Verdict), CITATION_VERDICTS)
        self.assertEqual(tuple(definitions["support_verdict"]["enum"]), SUPPORT_VERDICTS)
        self.assertEqual(tuple(verdict.value for verdict in SupportVerdict), SUPPORT_VERDICTS)
        self.assertEqual(tuple(definitions["risk"]["enum"]), RISK_LEVELS)
        self.assertEqual({item[0] for item in RISK_BY_VERDICT.values()}, set(RISK_LEVELS))
        self.assertEqual(tuple(definitions["evidence_scope"]["enum"]), EVIDENCE_SCOPES)
        self.assertEqual(infer_evidence_scope("abstract_sentence_1"), "abstract")
        self.assertEqual(infer_evidence_scope("unrecognized_field"), "unknown")
        self.assertEqual(
            definitions["evidence_object"]["properties"]["schema_version"]["const"],
            EVIDENCE_OBJECT_SCHEMA_VERSION,
        )
        self.assertEqual(set(definitions["next_action"]["enum"]), STABLE_NEXT_ACTIONS)

    def test_cli_verification_output_matches_v1_schema(self):
        stdout = io.StringIO()

        code = run(["verify", "--title", self.record.title, "--year", "2026"], source=self.source, stdout=stdout)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["contract_version"], CONTRACT_VERSION)
        self.assert_matches_contract("verification_result", payload)

    def test_mcp_batch_and_support_outputs_match_v1_schema(self):
        audit = server.audit_citations_tool([{"title": self.record.title}, {"title": "Unresolved contract paper"}])
        support = server.check_claim_support_tool(
            claim="The study evaluates citation auditor output contracts.",
            title=self.record.title,
        )
        support_audit = server.audit_claim_support_tool(
            [
                {
                    "claim": "The study evaluates citation auditor output contracts.",
                    "title": self.record.title,
                }
            ]
        )

        self.assert_matches_contract("citation_audit_response", audit)
        self.assert_matches_contract("support_result", support)
        self.assert_matches_contract("support_audit_response", support_audit)
        self.assertEqual(support["evidence"]["evidence_object"]["schema_version"], EVIDENCE_OBJECT_SCHEMA_VERSION)
        self.assertTrue(support["evidence"]["evidence_object"]["fragment"]["sha256"].startswith("sha256:"))

    def test_actual_mcp_document_audit_response_matches_v1_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            document = Path(directory) / "references.md"
            document.write_text(
                "## References\n\n"
                "1. Unresolved, U. A Contract Fixture. Imaginary Journal, 2026. DOI: 10.9999/contract-fixture.\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"CITEGUARD_ALLOWED_FILE_ROOTS": directory}, clear=False):
                payload = server.audit_document_tool(str(document))

        self.assert_matches_contract("document_audit_response", payload)
        self.assertEqual(payload["review_status"]["state"], "review_required")
        self.assertEqual(
            payload["review_status"]["snapshot_digest"],
            payload["document"]["snapshot"]["digest"],
        )

    def test_error_responses_are_versioned_and_schema_valid(self):
        direct_error = error_payload("missing_citation_input", "Provide a citation.")
        mcp_error = server.verify_citation_tool()

        self.assert_matches_contract("error_response", direct_error)
        self.assert_matches_contract("error_response", mcp_error)
        self.assertEqual(mcp_error["contract_version"], CONTRACT_VERSION)

    def test_wrapper_rejects_a_conflicting_existing_contract_version(self):
        self.assertEqual(with_contract_version({"ok": True})["contract_version"], CONTRACT_VERSION)
        with self.assertRaises(ValueError):
            with_contract_version({"contract_version": "v2"})


if __name__ == "__main__":
    unittest.main()
