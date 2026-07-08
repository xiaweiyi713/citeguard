"""Tests for local package install smoke helpers."""

from __future__ import annotations

import io
import tarfile
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from scripts import smoke_package


class PackageSmokeTests(unittest.TestCase):
    def test_sdist_copy_ignores_local_worktrees_and_generated_outputs(self):
        patterns = set(smoke_package._SDIST_COPY_IGNORE_PATTERNS)

        for pattern in {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "*.pyc",
            ".pytest_cache",
            ".mypy_cache",
            "build",
            "dist",
            "*.egg-info",
            "citeguard-*.tar.gz",
            "citeguard-*.whl",
            "experiments",
            "paper",
            ".ipynb_checkpoints",
        }:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, patterns)

    def test_sdist_release_files_include_configuration_contract_doc(self):
        expected_release_files = smoke_package._expected_sdist_release_files()
        self.assertIn("docs/configuration.md", expected_release_files)

        with tempfile.TemporaryDirectory() as tmpdir:
            sdist_path = Path(tmpdir) / "citeguard-0.1.0.tar.gz"
            with tarfile.open(sdist_path, "w:gz") as archive:
                for relative in sorted(expected_release_files - {"docs/configuration.md"}):
                    data = b"placeholder\n"
                    info = tarfile.TarInfo(f"citeguard-0.1.0/{relative}")
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))

            with mock.patch.object(smoke_package, "_assert_sdist_metadata_contract"):
                with self.assertRaisesRegex(RuntimeError, "docs/configuration.md"):
                    smoke_package._assert_sdist_contains_release_files(sdist_path)

    def test_sdist_release_files_include_agent_skill_bundle(self):
        expected_release_files = smoke_package._expected_sdist_release_files()
        required_skill_files = {
            "skills/citeguard-verify/SKILL.md",
            "skills/citeguard-verify/agents/openai.yaml",
            "skills/citeguard-verify/references/examples.md",
        }

        self.assertTrue(required_skill_files.issubset(expected_release_files))

        with tempfile.TemporaryDirectory() as tmpdir:
            sdist_path = Path(tmpdir) / "citeguard-0.1.0.tar.gz"
            with tarfile.open(sdist_path, "w:gz") as archive:
                missing_agent_metadata = {"skills/citeguard-verify/agents/openai.yaml"}
                for relative in sorted(expected_release_files - missing_agent_metadata):
                    data = b"placeholder\n"
                    info = tarfile.TarInfo(f"citeguard-0.1.0/{relative}")
                    info.size = len(data)
                    archive.addfile(info, io.BytesIO(data))

            with mock.patch.object(smoke_package, "_assert_sdist_metadata_contract"):
                with self.assertRaisesRegex(RuntimeError, "skills/citeguard-verify/agents/openai.yaml"):
                    smoke_package._assert_sdist_contains_release_files(sdist_path)

    def test_sdist_release_files_include_all_release_notes(self):
        self.assertIn("docs/releases/v0.1.0.md", smoke_package._expected_sdist_release_files())

        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir)
            releases_dir = project_root / "docs" / "releases"
            releases_dir.mkdir(parents=True)
            (releases_dir / "v9.9.9.md").write_text("future release note\n", encoding="utf-8")

            expected = smoke_package._expected_sdist_release_files(project_root=project_root)

        self.assertIn("docs/releases/v9.9.9.md", expected)

    def test_mcp_stdio_smoke_requires_mcp_extra_with_dependencies(self):
        with self.assertRaisesRegex(RuntimeError, "--mcp-stdio-smoke requires --extra mcp --with-deps"):
            smoke_package.main(["--mcp-stdio-smoke"])

    def test_mcp_stdio_smoke_dispatches_installed_entrypoint(self):
        recorded = []

        def run(cmd, cwd=None):
            recorded.append((cmd, cwd))
            return mock.Mock(stdout="3.10\n")

        def run_json(cmd):
            recorded.append((cmd, None))
            return {"service": "CiteGuard"}

        with tempfile.TemporaryDirectory() as tmpdir, mock.patch.object(
            smoke_package,
            "_python_version_tuple",
            return_value=(3, 10),
        ), mock.patch.object(
            smoke_package,
            "_build_wheel",
            return_value=Path(tmpdir) / "citeguard-0.1.0-py3-none-any.whl",
        ), mock.patch.object(
            smoke_package,
            "_assert_wheel_contains_core_files",
        ), mock.patch.object(
            smoke_package,
            "_create_venv",
        ), mock.patch.object(
            smoke_package,
            "_run",
            side_effect=run,
        ), mock.patch.object(
            smoke_package,
            "_run_json",
            side_effect=run_json,
        ):
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                code = smoke_package.main(
                    [
                        "--project-root",
                        str(Path(tmpdir)),
                        "--venv-dir",
                        str(Path(tmpdir) / "venv"),
                        "--install-mode",
                        "wheel",
                        "--extra",
                        "mcp",
                        "--with-deps",
                        "--mcp-stdio-smoke",
                    ]
                )

        self.assertEqual(code, 0)
        self.assertIn("with MCP stdio smoke", stdout.getvalue())
        commands = [cmd for cmd, _ in recorded]
        mcp_commands = [cmd for cmd in commands if "smoke_mcp.py" in " ".join(str(part) for part in cmd)]
        self.assertEqual(len(mcp_commands), 1)
        self.assertIn("--require-sdk", mcp_commands[0])
        self.assertIn("--command", mcp_commands[0])
        self.assertTrue(str(mcp_commands[0][-1]).endswith("citeguard-mcp"))

        inline_scripts = [cmd[-1] for cmd in commands if len(cmd) >= 3 and cmd[-2] == "-c"]
        self.assertIn(smoke_package._LEGACY_NAMESPACE_ABSENT_SMOKE, inline_scripts)

    def test_installed_package_smoke_rejects_legacy_src_namespace(self):
        self.assertIn('importlib.import_module("src")', smoke_package._LEGACY_NAMESPACE_ABSENT_SMOKE)
        self.assertIn("ModuleNotFoundError", smoke_package._LEGACY_NAMESPACE_ABSENT_SMOKE)
        self.assertIn("published package must not expose legacy src namespace", smoke_package._LEGACY_NAMESPACE_ABSENT_SMOKE)

    def test_installed_package_smoke_validates_public_api_contract(self):
        smoke = smoke_package._IMPORT_SMOKE

        self.assertIn("error_code_registry", smoke)
        self.assertIn("from citeguard.errors import STABLE_ERROR_CODES", smoke)
        self.assertIn("STABLE_ERROR_CODES", smoke)
        self.assertIn("missing_citation_input", smoke)
        self.assertIn("provide_missing_input", smoke)
        self.assertIn("retry_or_check_source_health", smoke)
        self.assertIn("experimental_exports", smoke)
        self.assertIn("orchestrator", smoke)
        self.assertIn("planner", smoke)
        self.assertIn("writer", smoke)

    def test_no_build_isolation_prereq_reports_missing_wheel(self):
        with mock.patch.object(
            smoke_package.subprocess,
            "run",
            return_value=mock.Mock(returncode=1, stdout="", stderr="No module named wheel"),
        ):
            with self.assertRaisesRegex(RuntimeError, "requires the smoke venv to have wheel installed"):
                smoke_package._assert_no_build_isolation_install_prereqs(Path("/tmp/python"))

    def test_no_build_isolation_prereq_accepts_installed_wheel(self):
        with mock.patch.object(
            smoke_package.subprocess,
            "run",
            return_value=mock.Mock(returncode=0, stdout="", stderr=""),
        ):
            smoke_package._assert_no_build_isolation_install_prereqs(Path("/tmp/python"))


if __name__ == "__main__":
    unittest.main()
