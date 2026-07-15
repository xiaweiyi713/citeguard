"""Tests for bundled agent-skill installation."""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest

from citeguard.cli import run
from citeguard.skill_install import bundled_skill_path, install_skill, skill_destination


class SkillInstallTests(unittest.TestCase):
    def test_source_checkout_exposes_complete_skill_bundle(self):
        bundle = bundled_skill_path({})

        self.assertTrue((bundle / "SKILL.md").is_file())
        self.assertTrue((bundle / "agents" / "openai.yaml").is_file())
        self.assertTrue((bundle / "references" / "tool-payloads.md").is_file())
        self.assertTrue((bundle / "references" / "result-policy.md").is_file())

    def test_project_destinations_follow_client_conventions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir).resolve()
            self.assertEqual(
                skill_destination("codex", "project", project_dir=temp_dir),
                root / ".codex" / "skills" / "citeguard-verify",
            )
            self.assertEqual(
                skill_destination("claude", "project", project_dir=temp_dir),
                root / ".claude" / "skills" / "citeguard-verify",
            )
            self.assertEqual(
                skill_destination("cursor", "project", project_dir=temp_dir),
                root / ".cursor" / "skills" / "citeguard-verify",
            )

    def test_install_is_idempotent_and_requires_force_for_differences(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "citeguard-verify"
            first = install_skill("codex", destination=str(destination))
            second = install_skill("codex", destination=str(destination))

            self.assertTrue(first["installed"])
            self.assertTrue(second["unchanged"])
            (destination / "SKILL.md").write_text("different", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                install_skill("codex", destination=str(destination))

            replaced = install_skill("codex", destination=str(destination), force=True)
            self.assertTrue(replaced["installed"])
            self.assertTrue(replaced["overwritten"])
            self.assertIn("name: citeguard-verify", (destination / "SKILL.md").read_text(encoding="utf-8"))

    def test_cli_installs_skill_with_machine_readable_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "skill"
            stdout = io.StringIO()

            code = run(
                ["skill", "install", "--client", "codex", "--destination", str(destination)],
                stdout=stdout,
            )

            self.assertEqual(code, 0)
            payload = json.loads(stdout.getvalue())
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["destination"], str(destination.resolve()))
            self.assertTrue((destination / "SKILL.md").is_file())


if __name__ == "__main__":
    unittest.main()
