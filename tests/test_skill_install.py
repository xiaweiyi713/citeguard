"""Tests for bundled agent-skill installation."""

from __future__ import annotations

import io
import json
from pathlib import Path
import tempfile
import unittest

from citeguard.cli import run
from citeguard.skill_install import (
    bundled_skill_path,
    check_skill,
    install_skill,
    skill_digest,
    skill_destination,
    skill_status,
    upgrade_skill,
)


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
            skill_text = (destination / "SKILL.md").read_text(encoding="utf-8")
            (destination / "SKILL.md").write_text(skill_text + "\n<!-- local customization -->\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                install_skill("codex", destination=str(destination))

            replaced = install_skill("codex", destination=str(destination), force=True)
            self.assertTrue(replaced["installed"])
            self.assertTrue(replaced["overwritten"])
            self.assertIn("name: citeguard-verify", (destination / "SKILL.md").read_text(encoding="utf-8"))

    def test_status_check_and_upgrade_distinguish_missing_current_and_modified_skills(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "citeguard-verify"

            missing = skill_status("codex", destination=str(destination))
            self.assertEqual(missing["state"], "not_installed")
            self.assertTrue(missing["ok"])
            self.assertFalse(check_skill("codex", destination=str(destination))["ok"])

            install_skill("codex", destination=str(destination))
            current = check_skill("codex", destination=str(destination))
            self.assertTrue(current["ok"])
            self.assertEqual(current["state"], "current")

            skill_text = (destination / "SKILL.md").read_text(encoding="utf-8")
            (destination / "SKILL.md").write_text(skill_text + "\n<!-- local customization -->\n", encoding="utf-8")
            modified = skill_status("codex", destination=str(destination))
            self.assertEqual(modified["state"], "modified_or_outdated")
            self.assertFalse(check_skill("codex", destination=str(destination))["ok"])

            pending = upgrade_skill("codex", destination=str(destination))
            self.assertFalse(pending["ok"])
            self.assertTrue(pending["requires_force"])
            upgraded = upgrade_skill("codex", destination=str(destination), force=True)
            self.assertTrue(upgraded["ok"])
            self.assertTrue(upgraded["upgraded"])
            self.assertEqual(check_skill("codex", destination=str(destination))["state"], "current")

    def test_force_never_replaces_an_unidentified_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "other-skill"
            destination.mkdir()
            (destination / "SKILL.md").write_text("---\nname: another-skill\n---\n", encoding="utf-8")

            with self.assertRaisesRegex(FileExistsError, "not an identified citeguard-verify"):
                install_skill("codex", destination=str(destination), force=True)

    def test_force_never_follows_a_skill_destination_symlink(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = root / "citeguard-verify"
            actual = root / "actual-skill"
            install_skill("codex", destination=str(actual))
            target.symlink_to(actual, target_is_directory=True)

            status = skill_status("codex", destination=str(target))
            self.assertEqual(status["state"], "invalid")
            self.assertIn("skill_root_must_not_be_symlink", status["integrity_errors"])
            with self.assertRaisesRegex(FileExistsError, "not an identified citeguard-verify"):
                install_skill("codex", destination=str(target), force=True)

    def test_nested_skill_symlinks_are_invalid_and_not_treated_as_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            destination = root / "citeguard-verify"
            outside = root / "outside.txt"
            outside.write_text("untrusted", encoding="utf-8")
            install_skill("codex", destination=str(destination))
            (destination / "untrusted-link").symlink_to(outside)

            status = skill_status("codex", destination=str(destination))

            self.assertEqual(status["state"], "invalid")
            self.assertIn("skill_bundle_must_not_contain_symlinks", status["integrity_errors"])
            with self.assertRaisesRegex(ValueError, "must_not_contain_symlinks"):
                skill_digest(destination)
            with self.assertRaises(FileExistsError):
                install_skill("codex", destination=str(destination))

            replaced = install_skill("codex", destination=str(destination), force=True)
            self.assertTrue(replaced["installed"])
            self.assertFalse((destination / "untrusted-link").exists())

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

            stdout = io.StringIO()
            check_code = run(["skill", "check", "--client", "codex", "--destination", str(destination)], stdout=stdout)
            self.assertEqual(check_code, 0)
            self.assertEqual(json.loads(stdout.getvalue())["state"], "current")


if __name__ == "__main__":
    unittest.main()
