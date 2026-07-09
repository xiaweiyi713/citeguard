"""Tests for post-publish package smoke helpers."""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from scripts import smoke_published_package


class PublishedPackageSmokeTests(unittest.TestCase):
    def test_package_spec_supports_version_and_extras(self):
        self.assertEqual(
            smoke_published_package._package_spec("citeguard", version="0.1.0", extras=["mcp", "pdf"]),
            "citeguard[mcp,pdf]==0.1.0",
        )

    def test_pip_install_command_can_target_testpypi(self):
        command = smoke_published_package._pip_install_command(
            "citationguard[mcp]==0.1.0",
            index_url="https://test.pypi.org/simple/",
            extra_index_urls=["https://pypi.org/simple"],
        )

        self.assertEqual(
            command,
            [
                "python",
                "-m",
                "pip",
                "install",
                "--index-url",
                "https://test.pypi.org/simple/",
                "--extra-index-url",
                "https://pypi.org/simple",
                "citationguard[mcp]==0.1.0",
            ],
        )

    def test_dry_run_outputs_machine_readable_plan_without_installing(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = smoke_published_package.main(
                [
                    "--version",
                    "0.1.0",
                    "--extra",
                    "mcp",
                    "--index-url",
                    "https://test.pypi.org/simple/",
                    "--extra-index-url",
                    "https://pypi.org/simple",
                    "--require-extra-import",
                    "mcp",
                    "--mcp-stdio-smoke",
                ]
            )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["package_spec"], "citationguard[mcp]==0.1.0")
        self.assertEqual(payload["checks"], [])
        self.assertIn("version_contract", payload["planned_checks"])
        self.assertIn("public_package_files", payload["planned_checks"])
        self.assertIn("public_api_contract", payload["planned_checks"])
        self.assertIn("distribution_metadata", payload["planned_checks"])
        self.assertIn("legacy_src_namespace_absent", payload["planned_checks"])
        self.assertIn("entry_points", payload["planned_checks"])
        self.assertIn("citeguard_cli_help", payload["planned_checks"])
        self.assertIn("python_m_citeguard_cli_help", payload["planned_checks"])
        self.assertIn("citeguard_cli_fixture_verify", payload["planned_checks"])
        self.assertIn("python_m_citeguard_cli_fixture_verify", payload["planned_checks"])
        self.assertIn("citeguard_cli_fixture_support", payload["planned_checks"])
        self.assertIn("python_m_citeguard_cli_fixture_support", payload["planned_checks"])
        self.assertIn("citeguard_cli_fixture_batch", payload["planned_checks"])
        self.assertIn("python_m_citeguard_cli_fixture_batch", payload["planned_checks"])
        self.assertIn("citeguard_cli_fixture_extract", payload["planned_checks"])
        self.assertIn("python_m_citeguard_cli_fixture_extract", payload["planned_checks"])
        self.assertIn("citeguard_cli_error_contract", payload["planned_checks"])
        self.assertIn("python_m_citeguard_cli_error_contract", payload["planned_checks"])
        self.assertIn("import_mcp", payload["planned_checks"])
        self.assertIn("mcp_stdio_smoke", payload["planned_checks"])
        self.assertIn("--index-url", payload["install_command"])
        self.assertIn("https://test.pypi.org/simple/", payload["install_command"])

    def test_dry_run_allows_dotted_required_extra_imports(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = smoke_published_package.main(
                [
                    "--version",
                    "0.1.0",
                    "--require-extra-import",
                    "mcp.client.stdio",
                ]
            )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["config_errors"], [])
        self.assertIn("import_mcp.client.stdio", payload["planned_checks"])

    def test_mcp_stdio_smoke_requires_mcp_extra_in_machine_readable_plan(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = smoke_published_package.main(["--version", "0.1.0", "--mcp-stdio-smoke"])

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["package_spec"], "citationguard==0.1.0")
        self.assertEqual(payload["checks"], [])
        self.assertEqual(
            payload["config_errors"][0]["code"],
            "mcp_stdio_smoke_requires_mcp_extra",
        )
        self.assertEqual(payload["config_errors"][0]["details"]["required_extra"], "mcp")

    def test_required_extra_import_rejects_non_module_name(self):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            code = smoke_published_package.main(
                [
                    "--version",
                    "0.1.0",
                    "--require-extra-import",
                    "mcp;raise SystemExit(2)",
                ]
            )

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["checks"], [])
        self.assertEqual(
            payload["config_errors"][0]["code"],
            "invalid_required_extra_import",
        )
        self.assertEqual(
            payload["config_errors"][0]["details"]["invalid_values"],
            ["mcp;raise SystemExit(2)"],
        )

    def test_run_records_console_entry_point_check(self):
        recorded = []

        def record_subprocess(summary, name, cmd, *, cwd=None):
            recorded.append((name, cwd))
            summary["checks"].append({"name": name, "status": "passed", "command": cmd, "cwd": str(cwd or "")})

        def record_json(summary, name, cmd, *, cwd=None):
            recorded.append((name, cwd))
            summary["checks"].append(
                {"name": name, "status": "passed", "command": cmd, "cwd": str(cwd or ""), "service": "CiteGuard"}
            )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            smoke_published_package, "_create_venv"
        ), mock.patch.object(
            smoke_published_package,
            "_venv_python",
            return_value=Path(tmpdir) / "bin" / "python",
        ), mock.patch.object(
            smoke_published_package,
            "_record_subprocess",
            side_effect=record_subprocess,
        ), mock.patch.object(
            smoke_published_package,
            "_record_json_command",
            side_effect=record_json,
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = smoke_published_package.main(["--run", "--venv-dir", tmpdir, "--require-extra-import", "mcp"])

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["dry_run"])
        recorded_names = [name for name, _ in recorded]
        self.assertIn("entry_points", recorded_names)
        self.assertIn("public_package_files", recorded_names)
        self.assertIn("public_api_contract", recorded_names)
        self.assertIn("distribution_metadata", recorded_names)
        self.assertIn("legacy_src_namespace_absent", recorded_names)
        self.assertIn("citeguard_cli_help", recorded_names)
        self.assertIn("python_m_citeguard_cli_help", recorded_names)
        self.assertIn("citeguard_cli_fixture_verify", recorded_names)
        self.assertIn("python_m_citeguard_cli_fixture_verify", recorded_names)
        self.assertIn("citeguard_cli_fixture_support", recorded_names)
        self.assertIn("python_m_citeguard_cli_fixture_support", recorded_names)
        self.assertIn("citeguard_cli_fixture_batch", recorded_names)
        self.assertIn("python_m_citeguard_cli_fixture_batch", recorded_names)
        self.assertIn("citeguard_cli_fixture_extract", recorded_names)
        self.assertIn("python_m_citeguard_cli_fixture_extract", recorded_names)
        self.assertIn("citeguard_cli_error_contract", recorded_names)
        self.assertIn("python_m_citeguard_cli_error_contract", recorded_names)
        self.assertEqual(payload["planned_checks"], recorded_names)
        self.assertTrue(payload["smoke_cwd"].endswith("smoke-cwd"))
        self.assertTrue(all(str(cwd).endswith("smoke-cwd") for _, cwd in recorded))

    def test_venv_creation_failure_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            smoke_published_package,
            "_create_venv",
            side_effect=subprocess.CalledProcessError(3, ["python", "-m", "venv", tmpdir], "", "venv failed"),
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = smoke_published_package.main(["--run", "--venv-dir", tmpdir])

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertFalse(payload["dry_run"])
        self.assertEqual(payload["checks"][0]["name"], "venv_create")
        self.assertEqual(payload["checks"][0]["status"], "failed")
        self.assertEqual(payload["checks"][0]["stderr_tail"], ["venv failed"])

    def test_missing_console_script_is_recorded_as_machine_readable_failure(self):
        summary = {"ok": True, "checks": []}

        smoke_published_package._record_json_command(
            summary,
            "citeguard_status",
            ["/definitely/missing/citeguard", "status", "--compact"],
        )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["checks"][0]["name"], "citeguard_status")
        self.assertEqual(summary["checks"][0]["status"], "failed")
        self.assertIn("/definitely/missing/citeguard", summary["checks"][0]["message"])

    def test_run_can_record_installed_mcp_stdio_smoke(self):
        recorded = []

        def record_subprocess(summary, name, cmd, *, cwd=None):
            recorded.append((name, cmd, cwd))
            summary["checks"].append({"name": name, "status": "passed", "command": cmd, "cwd": str(cwd or "")})

        def record_json(summary, name, cmd, *, cwd=None):
            recorded.append((name, cmd, cwd))
            summary["checks"].append(
                {"name": name, "status": "passed", "command": cmd, "cwd": str(cwd or ""), "service": "CiteGuard"}
            )

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            smoke_published_package, "_create_venv"
        ), mock.patch.object(
            smoke_published_package,
            "_venv_python",
            return_value=Path(tmpdir) / "bin" / "python",
        ), mock.patch.object(
            smoke_published_package,
            "_record_subprocess",
            side_effect=record_subprocess,
        ), mock.patch.object(
            smoke_published_package,
            "_record_json_command",
            side_effect=record_json,
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = smoke_published_package.main(
                    [
                        "--run",
                        "--venv-dir",
                        tmpdir,
                        "--extra",
                        "mcp",
                        "--require-extra-import",
                        "mcp",
                        "--mcp-stdio-smoke",
                    ]
                )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        recorded_names = [name for name, _, _ in recorded]
        self.assertIn("mcp_stdio_smoke", recorded_names)
        self.assertEqual(payload["planned_checks"], recorded_names)
        mcp_cmd = {name: cmd for name, cmd, _ in recorded}["mcp_stdio_smoke"]
        self.assertEqual(mcp_cmd[1], "-c")
        self.assertIn("citeguard-mcp", mcp_cmd[-1])
        self.assertTrue(all(str(cwd).endswith("smoke-cwd") for _, _, cwd in recorded))

    def test_console_entry_point_smoke_uses_public_package_targets(self):
        self.assertIn('scripts["citeguard"] == "citeguard.cli:main"', smoke_published_package._ENTRY_POINT_SMOKE)
        self.assertIn(
            'scripts["citeguard-mcp"] == "citeguard.mcp.server:main"',
            smoke_published_package._ENTRY_POINT_SMOKE,
        )
        legacy_namespace = "s" + "rc."
        self.assertNotIn(legacy_namespace, smoke_published_package._ENTRY_POINT_SMOKE)

    def test_post_publish_smoke_rejects_legacy_namespace_files(self):
        self.assertIn("distribution(\"citationguard\").files", smoke_published_package._PUBLIC_PACKAGE_FILES_SMOKE)
        self.assertIn("citeguard/mcp/server.py", smoke_published_package._PUBLIC_PACKAGE_FILES_SMOKE)
        self.assertIn("legacy_files", smoke_published_package._PUBLIC_PACKAGE_FILES_SMOKE)

    def test_post_publish_smoke_validates_public_api_contract(self):
        smoke = smoke_published_package._PUBLIC_API_CONTRACT_SMOKE

        self.assertIn("citeguard.error_code_registry()", smoke)
        self.assertIn("STABLE_ERROR_CODES", smoke)
        self.assertIn("missing_citation_input", smoke)
        self.assertIn("provide_missing_input", smoke)
        self.assertIn("citeguard.verify_citation", smoke)
        self.assertIn("citeguard.check_claim_support_set", smoke)
        self.assertIn("experimental_exports", smoke)
        self.assertIn("orchestrator", smoke)
        self.assertIn("writer", smoke)

    def test_post_publish_smoke_validates_distribution_metadata(self):
        smoke = smoke_published_package._DISTRIBUTION_METADATA_SMOKE

        self.assertIn('distribution("citationguard").metadata', smoke)
        self.assertIn("skeptical citation auditor", smoke)
        self.assertIn("agent writing workflows", smoke)
        self.assertIn("citation-verification", smoke)
        self.assertIn("skeptical-citation-auditor", smoke)
        self.assertIn("agent-tools", smoke)
        self.assertIn("research-integrity", smoke)
        self.assertIn("Topic :: Text Processing :: Linguistic", smoke)
        self.assertIn("Typing :: Typed", smoke)
        self.assertIn("Documentation", smoke)
        self.assertIn("License-File", smoke)
        self.assertIn("LICENSE", smoke)
        self.assertIn("research-agents", smoke)

    def test_post_publish_smoke_validates_installed_cli_help_shape(self):
        smoke = smoke_published_package._CLI_HELP_SMOKE

        self.assertIn('cmd = sys.argv[1:] + ["--help"]', smoke)
        self.assertIn("support-audit", smoke)
        self.assertIn("extract", smoke)
        self.assertIn("cache", smoke)
        self.assertIn("status", smoke)
        self.assertIn("citation", smoke)

    def test_post_publish_smoke_validates_installed_cli_fixture_verify(self):
        smoke = smoke_published_package._CLI_FIXTURE_VERIFY_SMOKE

        self.assertIn("CITEGUARD_FIXTURE_CITATIONS", smoke)
        self.assertIn("CITEGUARD_CACHE", smoke)
        self.assertIn("Attention Is All You Need", smoke)
        self.assertIn('"verify"', smoke)
        self.assertIn('"--compact"', smoke)
        self.assertIn('payload["verdict"] == "verified"', smoke)
        self.assertIn('payload["next_action"] == "keep"', smoke)
        self.assertIn('payload["sources_checked"] == ["metadata_source"]', smoke)
        self.assertIn('payload["sources_responded"] == ["fixture"]', smoke)

    def test_post_publish_smoke_validates_installed_cli_fixture_support(self):
        smoke = smoke_published_package._CLI_FIXTURE_SUPPORT_SMOKE

        self.assertIn("CITEGUARD_FIXTURE_CITATIONS", smoke)
        self.assertIn("Attention Is All You Need", smoke)
        self.assertIn('"support"', smoke)
        self.assertIn("The Transformer relies entirely on attention mechanisms.", smoke)
        self.assertIn('payload["verdict"] in {"supported", "weakly_supported"}', smoke)
        self.assertIn('payload["resolution"]["verdict"] == "matched"', smoke)
        self.assertIn('payload["resolution"]["sources_responded"] == ["fixture"]', smoke)
        self.assertIn('payload["evidence_scope"] == "abstract"', smoke)
        self.assertIn('payload["evidence"]["source_name"] == "fixture"', smoke)

    def test_post_publish_smoke_validates_installed_cli_fixture_batch_workflows(self):
        smoke = smoke_published_package._CLI_FIXTURE_BATCH_SMOKE

        self.assertIn("citations.jsonl", smoke)
        self.assertIn("claim_citations.jsonl", smoke)
        self.assertIn('"audit"', smoke)
        self.assertIn('"support-audit"', smoke)
        self.assertIn('"--high-risk-only"', smoke)
        self.assertIn('audit["filtered"]["returned_indexes"] == [1]', smoke)
        self.assertIn('support_audit["filtered"]["returned_indexes"] == [1]', smoke)
        self.assertIn('risk_reason"] == "no_strong_match"', smoke)
        self.assertIn('risk_reason"] == "citation_identity_unresolved"', smoke)
        self.assertIn('requires_user_confirmation"] is True', smoke)

    def test_post_publish_smoke_validates_installed_cli_fixture_extract_workflows(self):
        smoke = smoke_published_package._CLI_FIXTURE_EXTRACT_SMOKE

        self.assertIn("references.md", smoke)
        self.assertIn('"extract"', smoke)
        self.assertIn('"audit"', smoke)
        self.assertIn('"--high-risk-only"', smoke)
        self.assertIn('extracted[0]["source_format"] == "markdown"', smoke)
        self.assertIn('source_locator"].endswith("references.md#citation-1")', smoke)
        self.assertIn('source_traceability"]["high_risk_source_indexes"] == [2]', smoke)
        self.assertIn('input_source_line_start"] == 4', smoke)
        self.assertIn('input_source_locator"].endswith("references.md#citation-2")', smoke)

    def test_post_publish_smoke_validates_installed_cli_error_contract(self):
        smoke = smoke_published_package._CLI_ERROR_CONTRACT_SMOKE

        self.assertIn('"verify"', smoke)
        self.assertIn('"support-audit"', smoke)
        self.assertIn("bad.jsonl", smoke)
        self.assertIn("completed.stdout == \"\"", smoke)
        self.assertIn("json.loads(completed.stderr)", smoke)
        self.assertIn('payload["ok"] is False', smoke)
        self.assertIn('payload["schema_version"] == 1', smoke)
        self.assertIn('payload["exit_code"] == 2', smoke)
        self.assertIn('error["code"] == "missing_citation_input"', smoke)
        self.assertIn('error["details"]["command"] == "verify"', smoke)
        self.assertIn('error["next_action"] == "provide_missing_input"', smoke)
        self.assertIn('error["category"] == "missing_input"', smoke)
        self.assertIn('error["code"] == "invalid_json"', smoke)
        self.assertIn('error["details"]["command"] == "support-audit"', smoke)
        self.assertIn('error["details"]["line"] == 1', smoke)
        self.assertIn('error["details"]["column"] == 2', smoke)
        self.assertIn('error["next_action"] == "repair_input"', smoke)
        self.assertIn('error["category"] == "input_repair"', smoke)

    def test_post_publish_smoke_validates_installed_version_contract(self):
        smoke = smoke_published_package._VERSION_CONTRACT_SMOKE

        self.assertIn('version("citationguard")', smoke)
        self.assertIn("citeguard.__version__", smoke)
        self.assertIn("__version__ == expected", smoke)

    def test_post_publish_smoke_rejects_legacy_namespace_import(self):
        smoke = smoke_published_package._LEGACY_NAMESPACE_ABSENT_SMOKE
        self.assertIn('importlib.import_module("src")', smoke)
        self.assertIn("ModuleNotFoundError", smoke)
        self.assertIn("published package must not expose legacy src namespace", smoke)

    def test_published_mcp_stdio_smoke_uses_installed_entrypoint_and_fixture(self):
        smoke = smoke_published_package._PUBLISHED_MCP_STDIO_SMOKE
        self.assertIn("StdioServerParameters(command=command", smoke)
        self.assertIn("CITEGUARD_FIXTURE_CITATIONS", smoke)
        self.assertIn("verify_citation_tool", smoke)
        self.assertIn("check_claim_support_set_tool", smoke)
        self.assertIn("require_support_mode_details", smoke)
        self.assertIn("support_mode_details", smoke)
        self.assertIn("no_unstated_multi_hop_or_full_text_support", smoke)
        self.assertIn("Citation Auditing with Metadata Checks", smoke)
        self.assertIn("missing_citation_input", smoke)


if __name__ == "__main__":
    unittest.main()
