"""Tests for optional, local-only runtime metrics."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from citeguard.runtime_metrics import cli_metric_event, metrics_status, record_runtime_metric


class RuntimeMetricsTests(unittest.TestCase):
    def test_metrics_are_disabled_by_default(self):
        status = metrics_status({})

        self.assertFalse(status["enabled"])
        self.assertEqual(status["transport"], "disabled")
        self.assertFalse(status["network_transmission"])
        self.assertFalse(record_runtime_metric("cli:verify", "success", 0.05, env={}))

    def test_enabled_metrics_only_write_the_allowlisted_aggregate_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.jsonl"
            env = {"CITEGUARD_METRICS_PATH": str(path)}

            self.assertTrue(record_runtime_metric("cli:verify", "success", 0.25, env=env))
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(
            set(payload),
            {"schema_version", "event", "outcome", "duration_bucket", "occurred_at"},
        )
        self.assertEqual(payload["event"], "cli:verify")
        self.assertEqual(payload["outcome"], "success")
        self.assertEqual(payload["duration_bucket"], "100ms_to_lt_1s")
        self.assertNotIn("title", payload)
        self.assertNotIn("path", payload)
        self.assertNotIn("evidence", payload)
        self.assertTrue(metrics_status(env)["enabled"])
        self.assertFalse(metrics_status(env)["path_exposed"])

    def test_unallowlisted_events_are_discarded_without_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.jsonl"
            env = {"CITEGUARD_METRICS_PATH": str(path)}

            self.assertFalse(record_runtime_metric("cli:claim with private text", "success", 0.01, env=env))
            self.assertFalse(path.exists())

    @unittest.skipUnless(hasattr(os, "symlink"), "symbolic links are unavailable")
    def test_enabled_metrics_reject_symbolic_link_destinations(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.jsonl"
            target.write_text("unchanged\n", encoding="utf-8")
            path = Path(directory) / "metrics.jsonl"
            path.symlink_to(target)

            self.assertFalse(record_runtime_metric("cli:verify", "success", 0.25, env={"CITEGUARD_METRICS_PATH": str(path)}))
            self.assertEqual(target.read_text(encoding="utf-8"), "unchanged\n")

    @unittest.skipUnless(os.name == "posix", "POSIX file modes are unavailable")
    def test_enabled_metrics_restrict_regular_file_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.jsonl"

            self.assertTrue(record_runtime_metric("cli:verify", "success", 0.25, env={"CITEGUARD_METRICS_PATH": str(path)}))

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_metrics_refuse_an_event_that_would_exceed_the_file_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.jsonl"
            path.write_bytes(b"x" * 31)

            with patch("citeguard.runtime_metrics.MAX_METRICS_FILE_BYTES", 32):
                self.assertFalse(record_runtime_metric("cli:verify", "success", 0.25, env={"CITEGUARD_METRICS_PATH": str(path)}))

            self.assertEqual(path.read_bytes(), b"x" * 31)

    def test_cli_entry_point_records_only_an_aggregate_status_event(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "metrics.jsonl"
            environment = {
                **os.environ,
                "CITEGUARD_CACHE": ":memory:",
                "CITEGUARD_METRICS_PATH": str(path),
            }

            completed = subprocess.run(
                [sys.executable, "-m", "citeguard", "status", "--compact"],
                cwd=Path(__file__).resolve().parents[1],
                env=environment,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertNotIn(str(path), completed.stdout)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["event"], "cli:status")
            self.assertEqual(payload["outcome"], "success")
            self.assertEqual(
                set(payload),
                {"schema_version", "event", "outcome", "duration_bucket", "occurred_at"},
            )

    def test_cli_event_mapping_never_returns_an_argument_value(self):
        event = cli_metric_event(["verify", "--title", "private manuscript title"])

        self.assertEqual(event, "cli:verify")
        self.assertNotIn("private", event)


if __name__ == "__main__":
    unittest.main()
