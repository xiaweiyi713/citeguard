"""End-to-end stdio smoke test for the optional MCP server."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest import mock

from citeguard.runtime import SOURCE_HEALTH_SCHEMA_VERSION
from citeguard.verification import CACHE_SCHEMA_VERSION
from scripts.smoke_mcp import _require_status_payload, _server_command, main as run_smoke


class MCPStdioSmokeCommandTests(unittest.TestCase):
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
                "summary": {
                    "sources_available": ["fixture"],
                    "sources_failed": [],
                    "failure_count": 0,
                    "failure_details": [],
                    "degraded": False,
                    "next_action": "continue",
                },
            },
        }

        _require_status_payload(payload, fixture_path)


@unittest.skipUnless(importlib.util.find_spec("mcp") is not None, "MCP SDK is not installed")
class MCPStdioSmokeTests(unittest.TestCase):
    def test_stdio_server_initializes_verifies_supports_fixture_and_returns_structured_errors(self):
        self.assertEqual(run_smoke([]), 0)


if __name__ == "__main__":
    unittest.main()
