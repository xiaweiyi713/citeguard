"""End-to-end stdio smoke test for the optional MCP server."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest import mock

from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.runtime import SOURCE_HEALTH_SCHEMA_VERSION
from citeguard.verification import CACHE_SCHEMA_VERSION, search_counterevidence_candidates
from scripts.smoke_mcp import (
    _require_counterevidence_payload,
    _require_document_audit_payload,
    _require_not_found_safety_payload,
    _require_status_payload,
    _require_tool_description,
    _server_command,
    main as run_smoke,
)


class MCPStdioSmokeCommandTests(unittest.TestCase):
    def test_tool_description_contract_normalizes_sdk_whitespace(self):
        tool = mock.Mock(description="The response never\n  edits the document.")

        _require_tool_description({"audit_document_tool": tool}, "audit_document_tool", ["never edits the document"])

    def test_default_command_prefers_installed_console_script(self):
        with mock.patch("scripts.smoke_mcp.shutil.which", return_value="/tmp/bin/citeguard-mcp"):
            command, args = _server_command("", None)

        self.assertEqual(command, "/tmp/bin/citeguard-mcp")
        self.assertEqual(args, [])

    def test_default_command_falls_back_to_module_entrypoint(self):
        with mock.patch("scripts.smoke_mcp.shutil.which", return_value=None):
            command, args = _server_command("", None)

        self.assertTrue(command)
        self.assertEqual(args, ["-m", "citeguard.mcp.server"])

    def test_explicit_command_uses_explicit_args(self):
        command, args = _server_command("custom-mcp", ["--debug"])

        self.assertEqual(command, "custom-mcp")
        self.assertEqual(args, ["--debug"])

    def test_missing_sdk_skip_is_default_but_can_be_required(self):
        with mock.patch("scripts.smoke_mcp._load_mcp_client", return_value=None):
            self.assertEqual(run_smoke([]), 0)
            self.assertEqual(run_smoke(["--require-sdk"]), 1)

    def test_status_payload_contract_accepts_current_source_health_schema(self):
        fixture_path = Path("/tmp/citeguard-fixture.json")
        payload = {
            "schema_version": 1,
            "service": "CiteGuard",
            "fixture_citations_path": str(fixture_path),
            "cache_status": {
                "path": ":memory:",
                "inspect_ok": True,
                "schema_version": CACHE_SCHEMA_VERSION,
                "next_action": "continue",
            },
            "source_health": {
                "schema_version": SOURCE_HEALTH_SCHEMA_VERSION,
                "mode": "fixture",
                "sources": [
                    {
                        "name": "fixture",
                        "status": "offline_fixture",
                        "next_action": "continue",
                        "confidence_effect": "none",
                        "interpretation": "fixture_mode_bypasses_live_sources",
                        "recovery_code": "",
                        "retry_after_seconds": None,
                        "retry_delay_seconds": None,
                        "retry_guidance": "continue",
                    }
                ],
                "summary": {
                    "sources_available": ["fixture"],
                    "sources_failed": [],
                    "failure_count": 0,
                    "failure_details": [],
                    "failure_kind_counts": {},
                    "failure_kind_sources": {},
                    "retry_delay_seconds": None,
                    "retry_delay_sources": [],
                    "degraded": False,
                    "confidence_effect": "none",
                    "interpretation": "fixture_mode_bypasses_live_sources",
                    "next_action": "continue",
                },
            },
            "support_models": {
                "engine": "heuristic_fallback",
                "next_action": "install_or_configure_dependency",
                "deep_models_available": False,
                "requested_engine": "auto",
                "effective_engine": "auto",
                "model_loading_enabled": True,
                "configuration_error": "",
                "model_dependencies": {
                    "sentence_transformers": False,
                    "transformers": False,
                    "torch": False,
                },
                "missing_dependencies": ["sentence_transformers", "torch", "transformers"],
            },
            "support_engine": "auto",
        }

        _require_status_payload(payload, fixture_path)

    def test_not_found_safety_payload_contract_rejects_fabrication_assertions(self):
        payload = {
            "verdict": "not_found",
            "next_action": "resolve_identifier_or_replace",
            "outage_limited": False,
            "source_failure_mode": "none",
            "sources_failed": [],
            "explanation": "Could not be verified in metadata_source.",
        }

        _require_not_found_safety_payload(payload)

        unsafe = dict(payload)
        unsafe["explanation"] = "This citation is fabricated."
        with self.assertRaises(RuntimeError):
            _require_not_found_safety_payload(unsafe)

    def test_counterevidence_payload_contract_checks_source_provenance_without_sdk(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="fixture-counterevidence",
                    title="Method M Does Not Improve Task T",
                    abstract="We show method M does not improve task T accuracy.",
                    source="fixture",
                )
            ]
        )
        payload = search_counterevidence_candidates(
            "Method M improves task T.",
            source,
            top_k=1,
        ).to_dict()

        _require_counterevidence_payload(payload)

        unsafe = dict(payload)
        unsafe["sources_responded"] = []
        with self.assertRaises(RuntimeError):
            _require_counterevidence_payload(unsafe)

    def test_document_audit_payload_contract_requires_locator_and_no_mutation(self):
        fixture_path = Path("/tmp/citeguard-document-fixture.md")
        payload = {
            "contract_version": "v1",
            "tool": "audit_document",
            "document": {
                "path": str(fixture_path.resolve()),
                "snapshot": {"digest": "sha256:" + "a" * 64, "file_count": 1},
            },
            "extraction": {
                "candidate_count": 1,
                "candidates": [{"document_locator": f"{fixture_path.resolve()}#line-3"}],
            },
            "edit_policy": {"document_modified": False, "automatic_apply_allowed": False},
        }

        _require_document_audit_payload(payload, fixture_path)

        unsafe = dict(payload)
        unsafe["edit_policy"] = {"document_modified": True, "automatic_apply_allowed": True}
        with self.assertRaises(RuntimeError):
            _require_document_audit_payload(unsafe, fixture_path)


@unittest.skipUnless(importlib.util.find_spec("mcp") is not None, "MCP SDK is not installed")
class MCPStdioSmokeTests(unittest.TestCase):
    def test_stdio_server_initializes_verifies_supports_fixture_and_returns_structured_errors(self):
        self.assertEqual(run_smoke([]), 0)


if __name__ == "__main__":
    unittest.main()
