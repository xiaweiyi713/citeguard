"""Release metadata and public-interface guardrails."""

from pathlib import Path
import re
import subprocess
import unittest
from unittest import mock

from citeguard.errors import ERROR_CODE_NEXT_ACTION, ERROR_SCHEMA_VERSION, STABLE_ERROR_CODES
from citeguard.retrieval.scholarly_clients.factory import DEFAULT_USER_AGENT
from citeguard.verification import STABLE_NEXT_ACTIONS
from citeguard.version import __version__
from scripts.release_package_gate import (
    _record_mcp_extra_smoke,
    _record_mcp_stdio_smoke,
    _record_published_smoke_plan,
    _record_support_label_sidecar_gate,
)
from scripts.smoke_package import _assert_archive_excludes_generated_files, _assert_distribution_metadata_contract


ROOT = Path(__file__).resolve().parents[1]
INTERNAL_PACKAGE = "s" + "rc"


class ReleaseMetadataTests(unittest.TestCase):
    def test_pyproject_declares_public_entry_points_and_extras(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn(f'version = "{__version__}"', pyproject)
        self.assertIn('citeguard = "citeguard.cli:main"', pyproject)
        self.assertIn('citeguard-mcp = "citeguard.mcp.server:main"', pyproject)
        self.assertIn(f'include = ["citeguard", "citeguard.*", "{INTERNAL_PACKAGE}", "{INTERNAL_PACKAGE}.*"]', pyproject)
        self.assertIn("mcp = [", pyproject)
        self.assertIn('"mcp>=1.2"', pyproject)
        self.assertIn("pdf = [", pyproject)
        self.assertIn('"pypdf>=4,<6"', pyproject)
        self.assertIn("models = [", pyproject)

    def test_legacy_setup_matches_public_console_scripts(self):
        setup = (ROOT / "setup.py").read_text(encoding="utf-8")

        self.assertIn(f'version="{__version__}"', setup)
        self.assertIn('"citeguard=citeguard.cli:main"', setup)
        self.assertIn('"citeguard-mcp=citeguard.mcp.server:main"', setup)
        self.assertIn(
            f'find_packages(include=["citeguard", "citeguard.*", "{INTERNAL_PACKAGE}", "{INTERNAL_PACKAGE}.*"])',
            setup,
        )
        self.assertIn('"mcp": [', setup)
        self.assertIn('"pdf": [', setup)
        self.assertIn('"pypdf>=4,<6"', setup)

    def test_runtime_version_surfaces_match_package_metadata(self):
        api_app = (ROOT / "citeguard" / "api" / "app.py").read_text(encoding="utf-8")
        factory = (ROOT / "citeguard" / "retrieval" / "scholarly_clients" / "factory.py").read_text(encoding="utf-8")
        http_client = (ROOT / "citeguard" / "retrieval" / "scholarly_clients" / "http.py").read_text(encoding="utf-8")

        self.assertEqual(DEFAULT_USER_AGENT, f"CiteGuard/{__version__}")
        self.assertIn("version=__version__", api_app)
        self.assertIn('DEFAULT_USER_AGENT = f"CiteGuard/{__version__}"', factory)
        self.assertIn('DEFAULT_HTTP_USER_AGENT = f"CiteGuard/{__version__}"', http_client)

    def test_manifest_ships_docs_examples_eval_data_and_skill(self):
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

        expected_patterns = [
            r"include README\.md",
            r"include CHANGELOG\.md",
            r"recursive-include docs \*\.md \*\.svg \*\.csv \*\.yml",
            r"recursive-include examples \*\.json \*\.jsonl \*\.md",
            r"recursive-include data/eval \*\.json",
            r"recursive-include skills \*\.md",
            r"recursive-include scripts \*\.py",
        ]
        for pattern in expected_patterns:
            with self.subTest(pattern=pattern):
                self.assertRegex(manifest, pattern)

    def test_package_smoke_rejects_generated_archive_files(self):
        smoke = (ROOT / "scripts" / "smoke_package.py").read_text(encoding="utf-8")

        self.assertIn('"pdf"', smoke)
        self.assertIn("Requires-Dist", smoke)
        self.assertIn("pypdf", smoke)
        self.assertIn('"citeguard/__main__.py"', smoke)
        self.assertIn('"-m", "citeguard"', smoke)
        _assert_archive_excludes_generated_files(
            {"citeguard/__init__.py", "citeguard.egg-info/SOURCES.txt"},
            archive_label="unit",
        )
        with self.assertRaisesRegex(RuntimeError, "generated/local files"):
            _assert_archive_excludes_generated_files(
                {
                    "citeguard/__pycache__/__init__.cpython-311.pyc",
                    "docs/.DS_Store",
                },
                archive_label="unit",
            )

    def test_package_smoke_validates_distribution_metadata_contract(self):
        good_metadata = f"""Metadata-Version: 2.1
Name: citeguard
Version: {__version__}
Summary: A falsification-first toolkit for trustworthy citation verification.
Requires-Python: >=3.9
Classifier: Intended Audience :: Science/Research
Classifier: License :: OSI Approved :: MIT License
Classifier: Programming Language :: Python :: 3
Classifier: Programming Language :: Python :: 3.10
Classifier: Topic :: Scientific/Engineering :: Artificial Intelligence
Classifier: Topic :: Scientific/Engineering :: Information Analysis
Provides-Extra: api
Provides-Extra: mcp
Provides-Extra: models
Provides-Extra: pdf
Requires-Dist: mcp>=1.2; extra == "mcp"
Requires-Dist: pypdf<6,>=4; extra == "pdf"
Project-URL: Homepage, https://github.com/xiaweiyi713/citeguard
Project-URL: Repository, https://github.com/xiaweiyi713/citeguard
Project-URL: Issues, https://github.com/xiaweiyi713/citeguard/issues
Project-URL: Changelog, https://github.com/xiaweiyi713/citeguard/blob/main/CHANGELOG.md
License-File: LICENSE
"""
        _assert_distribution_metadata_contract(good_metadata, archive_label="unit")

        bad_metadata = good_metadata.replace(
            "A falsification-first toolkit for trustworthy citation verification.",
            "TODO research agent prototype",
        )
        with self.assertRaisesRegex(RuntimeError, "metadata contract failed"):
            _assert_distribution_metadata_contract(bad_metadata, archive_label="unit")

    def test_public_docs_tests_and_scripts_do_not_use_src_imports(self):
        public_paths = [
            ROOT / "README.md",
            ROOT / "CHANGELOG.md",
            ROOT / "docs" / "benchmark_design.md",
            ROOT / "docs" / "cli_reference.md",
            ROOT / "docs" / "mcp_setup.md",
            ROOT / "docs" / "error_codes.md",
            ROOT / "docs" / "release_checklist.md",
            ROOT / "docs" / "security_compliance.md",
            ROOT / "docs" / "support_labeling_guidelines.md",
            ROOT / "skills" / "citeguard-verify" / "SKILL.md",
        ]
        public_paths.extend(sorted((ROOT / "tests").glob("test_*.py")))
        public_paths.extend(sorted((ROOT / "scripts").glob("*.py")))

        pattern = re.compile(r"\b(from {0}\.|import {0}\b|{0}\.)".format(INTERNAL_PACKAGE))
        offenders = []
        for path in public_paths:
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                offenders.append(str(path.relative_to(ROOT)))

        self.assertEqual(offenders, [])

    def test_public_citeguard_package_does_not_depend_on_legacy_src_package(self):
        pattern = re.compile(r"\b(from {0}\.|import {0}\b|{0}\.)".format(INTERNAL_PACKAGE))
        offenders = []
        for path in sorted((ROOT / "citeguard").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                offenders.append(str(path.relative_to(ROOT)))

        self.assertEqual(offenders, [])

    def test_public_docs_are_citeguard_package_first(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        benchmark_design = (ROOT / "docs" / "benchmark_design.md").read_text(encoding="utf-8")

        self.assertIn("citeguard/", readme)
        self.assertIn("src/                       # legacy compatibility shims", readme)
        self.assertIn("docs/public_api_migration.md", readme)
        self.assertNotIn("src/\n  verification/", readme)
        self.assertIn("citeguard/benchmark/metrics.py", benchmark_design)
        self.assertNotIn("src/benchmark/metrics.py", benchmark_design)

    def test_public_api_migration_documents_legacy_deprecation(self):
        migration = (ROOT / "docs" / "public_api_migration.md").read_text(encoding="utf-8")
        legacy_init = (ROOT / INTERNAL_PACKAGE / "__init__.py").read_text(encoding="utf-8")

        for public_package in [
            "citeguard.verification",
            "citeguard.retrieval",
            "citeguard.mcp",
            "citeguard.cli",
            "citeguard.runtime",
        ]:
            with self.subTest(public_package=public_package):
                self.assertIn(public_package, migration)

        self.assertIn("DeprecationWarning", migration)
        self.assertIn("temporary compatibility bridge", migration)
        self.assertIn("compatibility package is deprecated", legacy_init)
        self.assertIn("from citeguard.version import __version__", legacy_init)

    def test_historical_superpowers_docs_do_not_look_like_current_api_guidance(self):
        docs_root = ROOT / "docs" / "superpowers"
        legacy_name = INTERNAL_PACKAGE
        pattern = re.compile(r"\b(from {0}\.|import {0}\b|{0}\.)".format(legacy_name))
        offenders = []
        for path in sorted(docs_root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            if not pattern.search(text):
                continue
            required_phrases = [
                "Archived historical",
                "pre-migration",
                "stable public `citeguard.*` package",
                "historical compatibility context",
                "docs/public_api_migration.md",
            ]
            missing = [phrase for phrase in required_phrases if phrase not in text]
            if missing:
                offenders.append(f"{path.relative_to(ROOT)} missing {missing}")

        self.assertEqual(offenders, [])

    def test_roadmap_tracks_agent_auditor_release_state(self):
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")

        required_phrases = [
            "stable agent-facing skeptical citation auditor",
            "`Alpha agent-auditor package`",
            "Public `citeguard.*` package facades",
            "legacy `src` root package",
            "MCP stdio smoke coverage",
            "Batch citation and claim-support audits with JSON/JSONL input",
            "Source-health/status contracts",
            "checked/failed source separation",
            "SQLite cache schema/version inspection",
            "deterministic offline replay fixtures",
            "Agent skill instructions",
            "false-support risk",
            "human review coverage",
            "full-text evidence opt-in",
            "do not bypass paywalls or gated sources",
            "Codex",
            "Claude Code",
            "Cursor",
            "source outages, model failures, and missing snippets as uncertainty",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, roadmap)

    def test_error_code_documentation_matches_public_registry(self):
        docs = (ROOT / "docs" / "error_codes.md").read_text(encoding="utf-8")
        stable_codes_section = docs.split("## Stable Codes", 1)[1].split("## Details Contract", 1)[0]
        documented = set(re.findall(r"\| `([^`]+)` \|", stable_codes_section))

        self.assertEqual(documented, STABLE_ERROR_CODES)
        self.assertEqual(set(ERROR_CODE_NEXT_ACTION), STABLE_ERROR_CODES)
        self.assertTrue(set(ERROR_CODE_NEXT_ACTION.values()).issubset(STABLE_NEXT_ACTIONS))
        self.assertIn("ERROR_SCHEMA_VERSION", docs)
        self.assertIn(f'"schema_version": {ERROR_SCHEMA_VERSION}', docs)
        self.assertIn('"recovery": "Ask for a DOI, arXiv id, title, or pasted reference."', docs)
        self.assertIn('"next_action": "provide_missing_input"', docs)
        self.assertIn("`error.recovery` is present on every error payload", docs)
        self.assertIn("`error.next_action` is present on every error payload", docs)
        self.assertIn("ERROR_CODE_NEXT_ACTION", docs)

    def test_next_action_documentation_matches_public_registry(self):
        docs = (ROOT / "docs" / "error_codes.md").read_text(encoding="utf-8")
        next_action_section = docs.split("## Stable next_action Values", 1)[1].split("## Stable Codes", 1)[0]
        documented = set(re.findall(r"\| `([^`]+)` \|", next_action_section))

        self.assertEqual(documented, STABLE_NEXT_ACTIONS)
        self.assertIn("Prefer `next_action` for workflow branching", docs)

    def test_ci_runs_release_and_mcp_smoke_gates(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn("python scripts/eval_verification.py", workflow)
        self.assertIn("python scripts/eval_support.py --validate-only", workflow)
        self.assertIn("python scripts/eval_support.py --report --split test", workflow)
        self.assertIn("python scripts/compare_support_baselines.py --split test", workflow)
        self.assertIn("--label-sidecar data/eval/support_eval_label_sidecar.json", workflow)
        self.assertIn("--min-sidecar-coverage 1.0", workflow)
        self.assertIn("--min-human-reviewed 0", workflow)
        self.assertIn("--min-high-risk-reviewed 0", workflow)
        self.assertIn("--min-high-risk-reviewed-by-language zh=0", workflow)
        self.assertIn("python scripts/smoke_package.py --install-mode wheel", workflow)
        self.assertIn("python scripts/smoke_package.py --install-mode sdist", workflow)
        self.assertIn(
            "python scripts/release_package_gate.py --skip-install-smoke --include-mcp-extra-smoke --require-mcp-extra-smoke",
            workflow,
        )
        self.assertIn(
            "python scripts/release_package_gate.py --skip-install-smoke --include-mcp-stdio-smoke --require-mcp-stdio-smoke",
            workflow,
        )
        self.assertIn("python -m pip install build twine", workflow)
        self.assertIn("python scripts/release_package_gate.py --skip-install-smoke --require-build-tools", workflow)
        self.assertIn('python-version: "3.10"', workflow)
        self.assertIn('python -m pip install -e ".[mcp]"', workflow)
        self.assertIn("python scripts/smoke_mcp.py --require-sdk", workflow)

    def test_release_package_gate_is_documented_and_packaged(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        checklist = (ROOT / "docs" / "release_checklist.md").read_text(encoding="utf-8")
        smoke = (ROOT / "scripts" / "smoke_package.py").read_text(encoding="utf-8")
        gate = (ROOT / "scripts" / "release_package_gate.py").read_text(encoding="utf-8")
        combined = f"{readme}\n{checklist}\n{smoke}\n{gate}"

        required_phrases = [
            "scripts/release_package_gate.py",
            "scripts/smoke_published_package.py",
            "--require-build-tools",
            "--skip-install-smoke",
            "--include-mcp-extra-smoke",
            "--require-mcp-extra-smoke",
            "--include-mcp-stdio-smoke",
            "--require-mcp-stdio-smoke",
            "--include-published-smoke-plan",
            "--include-published-mcp-smoke-plan",
            "--skip-support-label-gate",
            "--support-label-sidecar",
            "--support-eval-dataset",
            "--min-high-risk-reviewed-by-language",
            "--with-deps",
            "--extra mcp",
            "support_label_sidecar_gate",
            'gate.get("thresholds", {})',
            'gate.get("metrics", {})',
            'gate.get("failures", [])',
            "structured",
            "_MCP_EXTRA_SMOKE",
            "mcp_extra_wheel_install_smoke",
            "mcp_stdio_smoke",
            "published_package_smoke_plan",
            "published_mcp_smoke_plan",
            "MCP extra install smoke requires Python 3.10+",
            "MCP stdio smoke requires Python 3.10+",
            "python -m build",
            "python -m twine check",
            "pep517_build_and_twine_check",
            "project_metadata_contract",
            "distribution metadata contract",
            "python -m citeguard",
            "python scripts/smoke_package.py --install-mode wheel --extra mcp --with-deps",
            "python scripts/release_package_gate.py --skip-install-smoke --include-mcp-extra-smoke --require-mcp-extra-smoke",
            "python scripts/release_package_gate.py --skip-install-smoke --include-mcp-stdio-smoke --require-mcp-stdio-smoke",
            "python scripts/release_package_gate.py --skip-install-smoke --include-published-smoke-plan --include-published-mcp-smoke-plan",
            "python scripts/release_package_gate.py --require-build-tools --min-high-risk-reviewed-by-language zh=0",
            "python scripts/smoke_mcp.py --require-sdk",
            "python scripts/smoke_published_package.py --version 0.1.0",
            "--index-url https://test.pypi.org/simple/",
            "--extra-index-url https://pypi.org/simple",
            "--require-extra-import mcp",
            "citeguard.mcp.server",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_readme_test_command_avoids_stale_fixed_test_count(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        tests_section = readme.split("## Tests & reproducibility", 1)[1].split("## Cache and reproducibility", 1)[0]

        self.assertIn("python3 -m unittest discover -s tests -v", tests_section)
        self.assertIn("full unittest suite", tests_section)
        self.assertIn("optional MCP stdio smoke skips without the MCP SDK", tests_section)
        self.assertIsNone(re.search(r"\b\d+\s+tests\b", tests_section))

    def test_release_gate_records_mcp_extra_smoke_policy(self):
        summary = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 9)):
            _record_mcp_extra_smoke(summary, python="python3", project_root=ROOT, require=False)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "mcp_extra_wheel_install_smoke")
        self.assertEqual(summary["steps"][0]["status"], "skipped")

        required = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 9)):
            _record_mcp_extra_smoke(required, python="python3", project_root=ROOT, require=True)

        self.assertFalse(required["ok"])
        self.assertEqual(required["steps"][0]["status"], "failed")

        dispatched = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 10)), mock.patch(
            "scripts.release_package_gate._record_subprocess_step"
        ) as record:
            _record_mcp_extra_smoke(dispatched, python="python3.10", project_root=ROOT, require=True)

        record.assert_called_once()
        args, kwargs = record.call_args
        self.assertEqual(args[1], "mcp_extra_wheel_install_smoke")
        self.assertEqual(
            args[2],
            [
                "python3.10",
                "scripts/smoke_package.py",
                "--install-mode",
                "wheel",
                "--extra",
                "mcp",
                "--with-deps",
            ],
        )
        self.assertEqual(kwargs["cwd"], ROOT)

    def test_release_gate_records_mcp_stdio_smoke_policy(self):
        summary = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 9)):
            _record_mcp_stdio_smoke(summary, python="python3", project_root=ROOT, require=False)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "mcp_stdio_smoke")
        self.assertEqual(summary["steps"][0]["status"], "skipped")
        self.assertIn("Python 3.10+", summary["steps"][0]["message"])

        required_py39 = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 9)):
            _record_mcp_stdio_smoke(required_py39, python="python3", project_root=ROOT, require=True)

        self.assertFalse(required_py39["ok"])
        self.assertEqual(required_py39["steps"][0]["status"], "failed")

        missing_sdk = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 10)), mock.patch(
            "scripts.release_package_gate._module_available", return_value=False
        ):
            _record_mcp_stdio_smoke(missing_sdk, python="python3.10", project_root=ROOT, require=False)

        self.assertTrue(missing_sdk["ok"])
        self.assertEqual(missing_sdk["steps"][0]["status"], "skipped")
        self.assertIn("MCP SDK is not installed", missing_sdk["steps"][0]["message"])

        required_missing_sdk = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 10)), mock.patch(
            "scripts.release_package_gate._module_available", return_value=False
        ):
            _record_mcp_stdio_smoke(required_missing_sdk, python="python3.10", project_root=ROOT, require=True)

        self.assertFalse(required_missing_sdk["ok"])
        self.assertEqual(required_missing_sdk["steps"][0]["status"], "failed")

        dispatched = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 10)), mock.patch(
            "scripts.release_package_gate._module_available", return_value=True
        ), mock.patch("scripts.release_package_gate._record_subprocess_step") as record:
            _record_mcp_stdio_smoke(dispatched, python="python3.10", project_root=ROOT, require=True)

        record.assert_called_once()
        args, kwargs = record.call_args
        self.assertEqual(args[1], "mcp_stdio_smoke")
        self.assertEqual(args[2], ["python3.10", "scripts/smoke_mcp.py", "--require-sdk"])
        self.assertEqual(kwargs["cwd"], ROOT)

    def test_release_gate_records_published_smoke_plan(self):
        summary = {"ok": True, "steps": []}
        completed = mock.Mock(
            stdout='{"ok": true, "dry_run": true, "package_spec": "citeguard==0.1.0", "install_command": ["python", "-m", "pip", "install", "citeguard==0.1.0"]}'
        )
        with mock.patch("scripts.release_package_gate._run", return_value=completed) as run:
            _record_published_smoke_plan(
                summary,
                python="python3",
                project_root=ROOT,
                extra="",
                require_extra_import="",
            )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "published_package_smoke_plan")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["package_spec"], "citeguard==0.1.0")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["python3", "scripts/smoke_published_package.py", "--version", __version__])

        mcp_summary = {"ok": True, "steps": []}
        mcp_completed = mock.Mock(
            stdout='{"ok": true, "dry_run": true, "package_spec": "citeguard[mcp]==0.1.0", "install_command": ["python", "-m", "pip", "install", "citeguard[mcp]==0.1.0"]}'
        )
        with mock.patch("scripts.release_package_gate._run", return_value=mcp_completed) as mcp_run:
            _record_published_smoke_plan(
                mcp_summary,
                python="python3",
                project_root=ROOT,
                extra="mcp",
                require_extra_import="mcp",
            )

        self.assertTrue(mcp_summary["ok"])
        self.assertEqual(mcp_summary["steps"][0]["name"], "published_mcp_smoke_plan")
        self.assertEqual(mcp_summary["steps"][0]["package_spec"], "citeguard[mcp]==0.1.0")
        self.assertEqual(
            mcp_run.call_args.args[0],
            [
                "python3",
                "scripts/smoke_published_package.py",
                "--version",
                __version__,
                "--extra",
                "mcp",
                "--require-extra-import",
                "mcp",
            ],
        )

    def test_release_gate_records_support_label_sidecar_gate(self):
        summary = {"ok": True, "steps": []}
        completed = mock.Mock(
            stdout=(
                '{"label_sidecar_gate": {"ok": true, '
                '"thresholds": {"min_high_risk_reviewed_by_language": {"zh": 1}}, '
                '"metrics": {"high_risk_case_count_by_language": {"zh": 5}, '
                '"high_risk_reviewed_by_language": {"zh": 1}}, '
                '"failures": []}}'
            )
        )
        with mock.patch("scripts.release_package_gate._run", return_value=completed) as run:
            _record_support_label_sidecar_gate(
                summary,
                python="python3",
                project_root=ROOT,
                dataset="data/eval/support_eval.json",
                label_sidecar="data/eval/support_eval_label_sidecar.json",
                min_sidecar_coverage=1.0,
                min_human_reviewed=2,
                min_high_risk_reviewed=1,
                min_high_risk_reviewed_by_language=["zh=1"],
                min_dual_annotated=2,
                max_unresolved_disagreements=0,
                min_raw_dual_agreement_rate=0.8,
                max_supported_disagreements=0,
            )

        run.assert_called_once()
        self.assertEqual(
            run.call_args.args[0],
            [
                "python3",
                "scripts/eval_support.py",
                "--validate-only",
                "--dataset",
                "data/eval/support_eval.json",
                "--label-sidecar",
                "data/eval/support_eval_label_sidecar.json",
                "--min-sidecar-coverage",
                "1.0",
                "--min-human-reviewed",
                "2",
                "--min-high-risk-reviewed",
                "1",
                "--min-dual-annotated",
                "2",
                "--max-unresolved-disagreements",
                "0",
                "--min-high-risk-reviewed-by-language",
                "zh=1",
                "--min-raw-dual-agreement-rate",
                "0.8",
                "--max-supported-disagreements",
                "0",
            ],
        )
        self.assertEqual(run.call_args.kwargs["cwd"], ROOT)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["thresholds"]["min_high_risk_reviewed_by_language"], {"zh": 1})
        self.assertEqual(summary["steps"][0]["metrics"]["high_risk_case_count_by_language"], {"zh": 5})
        self.assertEqual(summary["steps"][0]["failures"], [])

    def test_release_gate_records_failed_support_label_sidecar_gate_payload(self):
        summary = {"ok": True, "steps": []}
        error = subprocess.CalledProcessError(
            1,
            ["python3", "scripts/eval_support.py"],
            output=(
                '{"label_sidecar_gate": {"ok": false, '
                '"thresholds": {"min_high_risk_reviewed_by_language": {"zh": 1}}, '
                '"metrics": {"high_risk_case_count_by_language": {"zh": 5}, '
                '"high_risk_reviewed_by_language": {}}, '
                '"failures": [{"code": "sidecar_high_risk_reviewed_by_language", '
                '"language": "zh", "actual": 0, "threshold": 1}]}}'
            ),
            stderr="",
        )
        with mock.patch("scripts.release_package_gate._run", side_effect=error):
            _record_support_label_sidecar_gate(
                summary,
                python="python3",
                project_root=ROOT,
                dataset="data/eval/support_eval.json",
                label_sidecar="data/eval/support_eval_label_sidecar.json",
                min_sidecar_coverage=1.0,
                min_human_reviewed=0,
                min_high_risk_reviewed=0,
                min_high_risk_reviewed_by_language=["zh=1"],
                min_dual_annotated=0,
                max_unresolved_disagreements=0,
                min_raw_dual_agreement_rate=None,
                max_supported_disagreements=None,
            )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["steps"][0]["status"], "failed")
        self.assertEqual(summary["steps"][0]["failures"][0]["code"], "sidecar_high_risk_reviewed_by_language")
        self.assertEqual(summary["steps"][0]["failures"][0]["language"], "zh")
        self.assertEqual(summary["steps"][0]["metrics"]["high_risk_case_count_by_language"], {"zh": 5})

    def test_mcp_smoke_checks_structured_errors(self):
        smoke = (ROOT / "scripts" / "smoke_mcp.py").read_text(encoding="utf-8")
        setup_doc = (ROOT / "docs" / "mcp_setup.md").read_text(encoding="utf-8")

        self.assertIn("_require_error_payload", smoke)
        self.assertIn("_require_shape_error_payload", smoke)
        self.assertIn("_require_status_payload", smoke)
        self.assertIn("_require_stable_next_action", smoke)
        self.assertIn("_require_support_next_action", smoke)
        self.assertIn("_require_support_payload", smoke)
        self.assertIn("_require_support_audit_set_payload", smoke)
        self.assertIn("_require_audit_citations_payload", smoke)
        self.assertIn("_require_review_summary", smoke)
        self.assertIn("_require_action_queues", smoke)
        self.assertIn("--require-sdk", smoke)
        self.assertIn("require_sdk", smoke)
        self.assertIn("source_health", smoke)
        self.assertIn("sources_available", smoke)
        self.assertIn("sources_failed", smoke)
        self.assertIn("STABLE_NEXT_ACTIONS", smoke)
        self.assertIn("schema_version", smoke)
        self.assertIn("error.recovery", smoke)
        self.assertIn("error.next_action", smoke)
        self.assertIn("details.expected", smoke)
        self.assertIn("details.received", smoke)
        self.assertIn("batch shape error details", smoke)
        self.assertIn('shutil.which("citeguard-mcp")', smoke)
        self.assertIn("missing_citation_input", smoke)
        self.assertIn("missing_claim", smoke)
        self.assertIn("audit_citations_tool", smoke)
        self.assertIn("audit_claim_support_tool", smoke)
        self.assertIn("review_summary", smoke)
        self.assertIn("action_queues", smoke)
        self.assertIn("high_risk_only", smoke)
        self.assertIn("_require_high_risk_filtered_payload", smoke)
        self.assertIn("filtered.returned_indexes", smoke)
        self.assertIn("filtered.omitted_review_summary", smoke)
        self.assertIn("search_counterevidence_tool", smoke)
        self.assertIn("_require_counterevidence_payload", smoke)
        self.assertIn("review_counterevidence_leads", smoke)
        self.assertIn("explicit_contradiction_cue", smoke)
        self.assertIn("improvement_negation", smoke)
        self.assertIn("source_outage_safety", smoke)
        self.assertIn("source_outage_safety_cue", smoke)
        self.assertIn("source-outage safety counter-evidence leads", smoke)
        self.assertIn("Chinese source-outage safety leads", smoke)
        self.assertIn("源不可达会提高引用被判定为伪造的置信度", smoke)
        self.assertIn("input_mode", smoke)
        self.assertIn("citation_set", smoke)
        self.assertIn("installed `citeguard-mcp`", setup_doc)
        self.assertIn("audit_citations_tool", setup_doc)
        self.assertIn("check_claim_support_tool", setup_doc)
        self.assertIn("audit_claim_support_tool", setup_doc)
        self.assertIn("review_summary", setup_doc)
        self.assertIn("action_queues", setup_doc)
        self.assertIn("high_risk_only=true", setup_doc)
        self.assertIn("filtered.returned_indexes", setup_doc)
        self.assertIn("top risk indexes", setup_doc)
        self.assertIn("python scripts/smoke_mcp.py --require-sdk", setup_doc)
        self.assertIn("missing MCP dependencies are a failure", setup_doc)
        self.assertIn("search_counterevidence_tool", setup_doc)
        self.assertIn("signal=explicit_contradiction_cue", setup_doc)
        self.assertIn("input_mode=citation_set", setup_doc)
        self.assertIn("MCP SDK requires Python 3.10+", setup_doc)
        self.assertIn("Top-level batch shape errors", setup_doc)
        self.assertIn("details.expected", setup_doc)
        self.assertIn("details.received", setup_doc)
        self.assertIn("details.field=citations", setup_doc)
        self.assertIn("details.field=items", setup_doc)
        self.assertIn("MCP SDK requires Python 3.10+", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertIn("structured error contract", setup_doc)
        self.assertIn("error.recovery", setup_doc)
        self.assertIn("error.next_action", setup_doc)
        self.assertIn("source_health.schema_version", setup_doc)
        self.assertIn("configured/checked/responded/unchecked sources", setup_doc)
        self.assertIn("source_health.summary", setup_doc)
        self.assertIn("failure_details", setup_doc)
        self.assertIn("failure_count", setup_doc)
        self.assertIn("next_action", setup_doc)
        self.assertIn("next_action=review_counterevidence_leads", setup_doc)
        self.assertIn("cache_status", setup_doc)
        self.assertIn("without exposing", setup_doc)
        self.assertIn("raw cache queries", setup_doc)
        self.assertIn("polite_access", setup_doc)
        self.assertIn("CITEGUARD_MAILTO", setup_doc)
        self.assertIn("fix_configuration", setup_doc)
        self.assertIn("not evidence that a citation is", setup_doc)
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        support = (ROOT / "citeguard" / "verification" / "support.py").read_text(encoding="utf-8")
        combined_counterevidence_contract = f"{readme}\n{setup_doc}\n{cli_reference}\n{support}"
        self.assertIn("source_outage_safety", combined_counterevidence_contract)
        self.assertIn("source_outage_safety_cue", combined_counterevidence_contract)
        self.assertIn("not_found", combined_counterevidence_contract)
        self.assertIn("Chinese source-outage/not-found overclaims", combined_counterevidence_contract)
        self.assertIn("源不可达", combined_counterevidence_contract)

    def test_cli_reference_documents_status_schema_contract(self):
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")

        required_phrases = [
            "schema_version",
            "source_health.schema_version",
            "sources_configured",
            "sources_checked",
            "sources_responded",
            "sources_unchecked",
            "failure_details",
            "failure_count",
            "next_action",
            "cache_status",
            "inspect_ok",
            "polite_access",
            "configured_contact_required_sources",
            "contact_env_var",
            "polite_access.status",
            "error.next_action",
            "Crossref records with missing `container-title`",
            "Semantic Scholar",
            "non-object `externalIds`",
            "arXiv Atom entries",
            "blank entries are skipped",
            "incomplete metadata, not evidence",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, cli_reference)

    def test_cache_replay_fixture_export_is_documented_as_deterministic(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        mcp_setup = (ROOT / "docs" / "mcp_setup.md").read_text(encoding="utf-8")
        checklist = (ROOT / "docs" / "release_checklist.md").read_text(encoding="utf-8")
        combined = f"{readme}\n{cli_reference}\n{mcp_setup}\n{checklist}"

        required_phrases = [
            "cache export --deterministic --output",
            "deterministic records-only fixture",
            "strip timestamp-only",
            "timestamp-only manifest fields",
            "raw match score",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_cli_reference_documents_full_text_file_error_contract(self):
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        error_docs = (ROOT / "docs" / "error_codes.md").read_text(encoding="utf-8")
        combined = f"{cli_reference}\n{error_docs}"

        required_phrases = [
            "details.field=full_text_file",
            "details.dependency=pypdf",
            "details.command",
            "details.index",
            "file_error",
            "details.filename",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_cli_reference_documents_batch_shape_error_contract(self):
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        error_docs = (ROOT / "docs" / "error_codes.md").read_text(encoding="utf-8")
        combined = f"{cli_reference}\n{error_docs}"

        required_phrases = [
            "details.command",
            "details.expected",
            "details.received",
            "1-based `details.index`",
            "details.line",
            "details.column",
            "JSON/JSONL parse errors",
            "filtered.returned_indexes",
            "filtered.omitted_indexes",
            "filtered.omitted_review_summary",
            "omitted rows' risk counts",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_cli_reference_documents_input_file_error_contract(self):
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        error_docs = (ROOT / "docs" / "error_codes.md").read_text(encoding="utf-8")
        combined = f"{cli_reference}\n{error_docs}"

        required_phrases = [
            "Missing or unreadable input files",
            "file_error",
            "details.field=path",
            "details.command",
            "details.filename",
            "details.errno",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_cli_reference_documents_output_file_error_contract(self):
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        error_docs = (ROOT / "docs" / "error_codes.md").read_text(encoding="utf-8")
        combined = f"{cli_reference}\n{error_docs}"

        required_phrases = [
            "cache export --output",
            "details.field=output",
            "details.command=cache",
            "details.cache_command=export",
            "details.filename",
            "details.errno",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_support_audit_citation_set_workflow_is_documented(self):
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        mcp_setup = (ROOT / "docs" / "mcp_setup.md").read_text(encoding="utf-8")
        skill = (ROOT / "skills" / "citeguard-verify" / "SKILL.md").read_text(encoding="utf-8")
        example = (ROOT / "examples" / "claim_citations.json").read_text(encoding="utf-8")
        combined = f"{cli_reference}\n{mcp_setup}\n{skill}\n{example}"

        required_phrases = [
            "citation-set item",
            "`citations`, a non-empty list of citation objects",
            "input_mode=citation_set",
            "support_mode",
            '"citations"',
            "audit_claim_support_tool",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_support_set_policy_fixture_is_documented_for_release(self):
        benchmark_design = (ROOT / "docs" / "benchmark_design.md").read_text(encoding="utf-8")
        benchmark_todo = (ROOT / "docs" / "benchmark_todo.md").read_text(encoding="utf-8")
        checklist = (ROOT / "docs" / "release_checklist.md").read_text(encoding="utf-8")
        eval_script = (ROOT / "scripts" / "eval_support.py").read_text(encoding="utf-8")
        combined = f"{benchmark_design}\n{benchmark_todo}\n{checklist}\n{eval_script}"

        required_phrases = [
            "support_set_policy",
            "citation-set",
            "multiple weak",
            "run_support_set_policy_fixture_report",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_false_support_analysis_is_documented_for_release(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        benchmark_design = (ROOT / "docs" / "benchmark_design.md").read_text(encoding="utf-8")
        benchmark_todo = (ROOT / "docs" / "benchmark_todo.md").read_text(encoding="utf-8")
        compare_script = (ROOT / "scripts" / "compare_support_baselines.py").read_text(encoding="utf-8")
        combined = f"{readme}\n{benchmark_design}\n{benchmark_todo}\n{compare_script}"

        required_phrases = [
            "false_support_analysis",
            "total_overcall_count",
            "high-risk false support case ids",
            "high_risk_false_support_case_ids",
            "false_support_case_ids",
            "weak_false_support_case_ids",
            "by_language",
            "language 覆盖",
            "test split",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_support_seed_documents_new_high_risk_boundaries(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        benchmark_todo = (ROOT / "docs" / "benchmark_todo.md").read_text(encoding="utf-8")
        support_eval = (ROOT / "data" / "eval" / "support_eval.json").read_text(encoding="utf-8")
        sidecar = (ROOT / "data" / "eval" / "support_eval_label_sidecar.json").read_text(encoding="utf-8")
        combined = f"{readme}\n{changelog}\n{benchmark_todo}\n{support_eval}\n{sidecar}"

        required_phrases = [
            "36 evidence-level cases",
            "benchmark provenance",
            "source-outage-to-fabrication inferences",
            "source outage",
            "Chinese source-outage/not-found safety benchmark cases",
            "eligibility criteria",
            '"id": "s31"',
            '"id": "s32"',
            '"id": "s33"',
            '"id": "s34"',
            '"id": "s35"',
            '"id": "s36"',
            '"case_id": "s31"',
            '"case_id": "s32"',
            '"case_id": "s33"',
            '"case_id": "s34"',
            '"case_id": "s35"',
            '"case_id": "s36"',
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_release_checklist_includes_support_label_audit(self):
        checklist = (ROOT / "docs" / "release_checklist.md").read_text(encoding="utf-8")
        benchmark_design = (ROOT / "docs" / "benchmark_design.md").read_text(encoding="utf-8")
        benchmark_todo = (ROOT / "docs" / "benchmark_todo.md").read_text(encoding="utf-8")
        guidelines = (ROOT / "docs" / "support_labeling_guidelines.md").read_text(encoding="utf-8")
        combined = f"{checklist}\n{benchmark_design}\n{benchmark_todo}\n{guidelines}"

        self.assertIn("prepare_support_label_sidecar.py", checklist)
        self.assertIn("--audit", checklist)
        self.assertIn("--annotation-packet --priority high --split test", checklist)
        self.assertIn("--instructions-output", checklist)
        self.assertIn("annotator instruction", checklist)
        self.assertIn("--merge-annotation-packet", checklist)
        self.assertIn("merge_report.conflicts", checklist)
        self.assertIn("--apply-adjudications", checklist)
        self.assertIn("adjudication_report.conflicts", checklist)
        self.assertIn("annotation.annotator_id", checklist)
        self.assertIn("review_focus", combined)
        self.assertIn("label hint", guidelines)
        self.assertIn("不能当作 label", benchmark_design)
        self.assertIn("duplicate_annotator", checklist)
        self.assertIn("adjudicated_label", checklist)
        self.assertIn("human-reviewed benchmark", checklist)
        self.assertIn("compare_support_baselines.py", checklist)
        self.assertIn("support-baselines-release", checklist)
        self.assertIn("package archive cleanliness", checklist)
        self.assertIn("__pycache__", checklist)
        self.assertIn("baseline comparison table", benchmark_design)
        self.assertIn('python -m pip install -e ".[pdf]"', checklist)
        self.assertIn("local PDF full-text evidence support", checklist)
        self.assertIn("--fail-on-high-risk-unreviewed", checklist)
        self.assertIn("--fail-on-high-risk-unreviewed-language", checklist)
        self.assertIn("high-risk unreviewed gate", checklist)
        self.assertIn("--fail-on-high-risk-unreviewed", benchmark_design)
        self.assertIn("--fail-on-high-risk-unreviewed-language", benchmark_design)
        self.assertIn("audit_gate", benchmark_design)
        self.assertIn("high-risk test packet", benchmark_design)
        self.assertIn("--case-type", benchmark_design)
        self.assertIn("--case-id", benchmark_design)
        self.assertIn("--lang", benchmark_design)
        self.assertIn("--limit", benchmark_design)
        self.assertIn("--limit 3", checklist)
        self.assertIn("label_maturity", combined)
        self.assertIn("high_risk_unreviewed_by_language", combined)
        self.assertIn("raw_dual_agreement_rate", combined)
        self.assertIn("unresolved_disagreement_count", combined)
        self.assertIn("dual_disagreement_label_pair_counts", combined)
        self.assertIn("supported_disagreement_case_ids", combined)
        self.assertIn("high_risk_review", combined)
        self.assertIn("case_count_by_language", combined)
        self.assertIn("reviewed_by_language", combined)
        self.assertIn("unreviewed_by_language", combined)
        self.assertIn("high_risk_case_count_by_language", combined)
        self.assertIn("high_risk_reviewed_by_language", combined)
        self.assertIn("high_risk_unreviewed_by_language", combined)
        self.assertIn("reviewed_case_ids_by_language", combined)
        self.assertIn("unreviewed_case_ids_by_language", combined)
        self.assertIn("test_split", combined)
        self.assertIn("weak support, hard negatives, contradictions, full-text-required cases", combined)
        self.assertIn("--min-high-risk-reviewed", combined)
        self.assertIn("--min-high-risk-reviewed-by-language", combined)
        self.assertIn("--min-dual-annotated", combined)
        self.assertIn("--max-unresolved-disagreements", combined)
        self.assertIn("--min-raw-dual-agreement-rate", combined)
        self.assertIn("--max-supported-disagreements", combined)
        self.assertIn("status consistency", combined)
        self.assertIn("not_human_reviewed", combined)
        self.assertIn("dual_annotator_agreed", combined)
        self.assertIn("dual_annotator_adjudicated", combined)
        self.assertIn("published_benchmark", combined)
        self.assertIn("source locator", combined)

    def test_agent_skill_documents_product_contract(self):
        skill = (ROOT / "skills" / "citeguard-verify" / "SKILL.md").read_text(encoding="utf-8")

        required_phrases = [
            "related work",
            "literature review",
            "bibliography",
            "pasted Markdown/LaTeX/Word-style reference section",
            "Do not silently change",
            "Do not translate `not_found`, `source_unavailable`, or `timeout` into \"fake\"",
            "Do not claim full-text support from an abstract-level support result",
            "local lawful text/PDF file",
            "citeguard[pdf]",
            "Codex:",
            "Claude Code:",
            "Cursor:",
            "verify_citation_tool",
            "audit_citations_tool",
            "check_claim_support_tool",
            "check_claim_support_set_tool",
            "search_counterevidence_tool",
            "audit_claim_support_tool",
            "Ambiguous citation:",
            "Metadata mismatch:",
            "Claim/citation batch:",
            "Sort or summarize by risk first",
            "Always include a next step",
            "review_summary",
            "action_queues",
            "top risk indexes",
            "next_action",
            "review_counterevidence_leads",
            "signal=source_outage_safety_cue",
            "error.next_action",
            "error.recovery",
            "error.details.expected",
            "error.details.received",
            "MCP batch shape errors",
            "Do not quote raw validation prose",
            "metadata.evidence_harvest_failures",
            "stage=remote_evidence",
            "Do not",
            "claim full-text or landing-page support from the missing snippet",
            "failure_kind_counts",
            "failure_kind_sources",
            "rate_limited",
            "source_health.summary.next_action",
            "not evidence of fabrication",
            "## Response template",
            "One-sentence bottom line",
            "Review queue summary from `review_summary.action_queues`",
            "`filtered.returned_indexes` / `filtered.omitted_indexes`",
            "`index`, `citation/claim`, `verdict`, `risk`, `next_action`, `why`, `next step`",
            "source retry is inconclusive",
            "Scope / limitations",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, skill)

    def test_security_compliance_boundaries_are_documented(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        security = (ROOT / "docs" / "security_compliance.md").read_text(encoding="utf-8")
        combined = f"{readme}\n{security}"

        required_phrases = [
            "does not scrape CNKI",
            "Wanfang",
            "must not bypass paywalls",
            "local user-provided text/PDF readers",
            "robots.txt",
            "CITEGUARD_MAILTO",
            "Remote landing-page evidence harvesting is disabled by default",
            "metadata.evidence_harvest_failures",
            "stage=remote_evidence",
            "not as proof the citation is unavailable or fabricated",
            "not proof that a citation is fake",
            "not a legal authority",
            "Final decisions about research integrity",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)


if __name__ == "__main__":
    unittest.main()
