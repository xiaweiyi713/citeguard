"""Tests for post-publish package smoke helpers."""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from scripts import smoke_published_package


class PublishedPackageSmokeTests(unittest.TestCase):
    def test_package_spec_supports_version_and_extras(self):
        self.assertEqual(
            smoke_published_package._package_spec("citeguard", version="0.1.0", extras=["mcp", "pdf"]),
            "citeguard[mcp,pdf]==0.1.0",
        )

    def test_pip_install_command_can_target_testpypi(self):
        command = smoke_published_package._pip_install_command(
            "citeguard[mcp]==0.1.0",
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
                "citeguard[mcp]==0.1.0",
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
                ]
            )

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["dry_run"])
        self.assertEqual(payload["package_spec"], "citeguard[mcp]==0.1.0")
        self.assertEqual(payload["checks"], [])
        self.assertIn("--index-url", payload["install_command"])
        self.assertIn("https://test.pypi.org/simple/", payload["install_command"])


if __name__ == "__main__":
    unittest.main()
