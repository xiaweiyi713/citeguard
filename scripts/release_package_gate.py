#!/usr/bin/env python3
"""Run package release gates with machine-readable output."""

from __future__ import annotations

import argparse
import ast
import errno
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.errors import (
    ERROR_CODE_CATEGORY,
    ERROR_CODE_NEXT_ACTION,
    ERROR_CODE_RECOVERY,
    ERROR_CODE_RETRYABLE,
    ERROR_SCHEMA_VERSION,
    STABLE_ERROR_CODES,
)
from citeguard.version import __version__
from scripts.smoke_package import (
    _IMPORT_SMOKE,
    _assert_sdist_contains_release_files,
    _assert_wheel_contains_core_files,
    _expected_sdist_release_files,
)


SUPPORT_ACCEPTANCE_SLICE_IDS = [
    "contradiction",
    "hard_negative",
    "full_text_boundary",
    "test_split",
    "non_english",
]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run CiteGuard package release gates: wheel/sdist smoke plus optional build/twine checks."
    )
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--python", default=sys.executable, help="Python executable used for release checks.")
    parser.add_argument(
        "--require-build-tools",
        action="store_true",
        help="Fail instead of skipping when the optional build/twine modules are unavailable.",
    )
    parser.add_argument(
        "--skip-install-smoke",
        action="store_true",
        help="Skip fresh-venv wheel/sdist install smoke checks. Intended only for local debugging.",
    )
    parser.add_argument(
        "--skip-support-label-gate",
        action="store_true",
        help="Skip support label sidecar provenance validation. Intended only for local debugging.",
    )
    parser.add_argument(
        "--skip-support-review-queue",
        action="store_true",
        help="Skip support eval review-queue contract validation. Intended only for local debugging.",
    )
    parser.add_argument("--support-eval-dataset", default="data/eval/support_eval.json")
    parser.add_argument("--support-label-sidecar", default="data/eval/support_eval_label_sidecar.json")
    parser.add_argument("--min-sidecar-coverage", type=float, default=1.0)
    parser.add_argument("--min-human-reviewed", type=int, default=0)
    parser.add_argument("--min-high-risk-reviewed", type=int, default=0)
    parser.add_argument(
        "--min-high-risk-reviewed-by-language",
        action="append",
        default=[],
        metavar="LANG=N",
        help="Minimum required human-reviewed high-risk labels for one language; repeat for multiple languages.",
    )
    parser.add_argument("--min-dual-annotated", type=int, default=0)
    parser.add_argument("--max-unresolved-disagreements", type=int, default=0)
    parser.add_argument("--min-raw-dual-agreement-rate", type=float, default=None)
    parser.add_argument("--max-supported-disagreements", type=int, default=None)
    parser.add_argument(
        "--include-mcp-extra-smoke",
        action="store_true",
        help="Run a fresh-venv wheel install smoke for the mcp extra and its dependencies.",
    )
    parser.add_argument(
        "--require-mcp-extra-smoke",
        action="store_true",
        help="Fail instead of skipping when the mcp extra smoke cannot run, for example on Python < 3.10.",
    )
    parser.add_argument(
        "--include-mcp-stdio-smoke",
        action="store_true",
        help="Run the offline MCP stdio smoke from this environment when the MCP SDK is available.",
    )
    parser.add_argument(
        "--require-mcp-stdio-smoke",
        action="store_true",
        help="Fail instead of skipping when the offline MCP stdio smoke cannot run.",
    )
    parser.add_argument(
        "--include-published-smoke-plan",
        action="store_true",
        help="Record a dry-run post-publish PyPI install smoke plan in the release summary.",
    )
    parser.add_argument(
        "--include-published-mcp-smoke-plan",
        action="store_true",
        help="Record a dry-run post-publish MCP-extra install smoke plan in the release summary.",
    )
    parser.add_argument(
        "--include-published-smoke-run",
        action="store_true",
        help="Run the real post-publish PyPI install smoke and record its checks in the release summary.",
    )
    parser.add_argument(
        "--include-published-mcp-smoke-run",
        action="store_true",
        help="Run the real post-publish PyPI MCP-extra install smoke and record its checks in the release summary.",
    )
    parser.add_argument(
        "--include-testpypi-smoke-plan",
        action="store_true",
        help="Record a dry-run TestPyPI install smoke plan with PyPI dependency fallback.",
    )
    parser.add_argument(
        "--include-testpypi-mcp-smoke-plan",
        action="store_true",
        help="Record a dry-run TestPyPI MCP-extra install smoke plan with PyPI dependency fallback.",
    )
    parser.add_argument(
        "--include-testpypi-smoke-run",
        action="store_true",
        help="Run the real TestPyPI install smoke with PyPI dependency fallback.",
    )
    parser.add_argument(
        "--include-testpypi-mcp-smoke-run",
        action="store_true",
        help="Run the real TestPyPI MCP-extra install smoke with PyPI dependency fallback.",
    )
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    summary: Dict[str, Any] = {
        "ok": True,
        "project_root": str(project_root),
        "python": args.python,
        "steps": [],
    }

    _record_project_metadata_contract(summary, project_root)
    _record_release_artifact_contract_gate(summary, project_root)
    _record_legacy_src_shim_contract(summary, project_root)
    _record_public_api_contract_gate(summary, project_root)
    _record_cache_replay_fixture_gate(summary, python=args.python, project_root=project_root)
    _record_error_codes_contract_gate(summary, project_root=project_root)
    _record_configuration_contract_gate(summary, project_root=project_root)
    _record_mcp_stdio_smoke_contract_gate(summary, project_root=project_root)
    _record_ci_mcp_smoke_contract_gate(summary, project_root=project_root)
    _record_mcp_error_contract_gate(summary)
    _record_cli_error_contract_gate(summary, python=args.python, project_root=project_root)
    _record_source_outage_safety_gate(summary, project_root=project_root)
    _record_counterevidence_safety_contract_gate(summary, project_root=project_root)
    _record_full_text_evidence_boundary_contract_gate(summary, project_root=project_root)
    _record_support_set_aggregation_contract_gate(summary, project_root=project_root)
    _record_live_source_health_contract_gate(summary, project_root=project_root)
    _record_security_compliance_contract_gate(summary, project_root=project_root)
    _record_agent_skill_contract_gate(summary, project_root=project_root)
    _record_batch_workflow_examples_gate(summary, python=args.python, project_root=project_root)

    if not args.skip_support_label_gate:
        _record_support_label_sidecar_gate(
            summary,
            python=args.python,
            project_root=project_root,
            dataset=args.support_eval_dataset,
            label_sidecar=args.support_label_sidecar,
            min_sidecar_coverage=args.min_sidecar_coverage,
            min_human_reviewed=args.min_human_reviewed,
            min_high_risk_reviewed=args.min_high_risk_reviewed,
            min_high_risk_reviewed_by_language=args.min_high_risk_reviewed_by_language,
            min_dual_annotated=args.min_dual_annotated,
            max_unresolved_disagreements=args.max_unresolved_disagreements,
            min_raw_dual_agreement_rate=args.min_raw_dual_agreement_rate,
            max_supported_disagreements=args.max_supported_disagreements,
        )
    _record_benchmark_claim_safety_gate(
        summary,
        project_root=project_root,
        dataset=args.support_eval_dataset,
        label_sidecar=args.support_label_sidecar,
    )
    if not args.skip_support_review_queue:
        _record_support_review_queue_gate(
            summary,
            python=args.python,
            project_root=project_root,
            dataset=args.support_eval_dataset,
            label_sidecar=args.support_label_sidecar,
        )
        _record_support_baseline_comparison_gate(
            summary,
            python=args.python,
            project_root=project_root,
            dataset=args.support_eval_dataset,
            label_sidecar=args.support_label_sidecar,
            min_sidecar_coverage=args.min_sidecar_coverage,
            min_human_reviewed=args.min_human_reviewed,
            min_high_risk_reviewed=args.min_high_risk_reviewed,
            min_high_risk_reviewed_by_language=args.min_high_risk_reviewed_by_language,
            min_dual_annotated=args.min_dual_annotated,
            max_unresolved_disagreements=args.max_unresolved_disagreements,
            min_raw_dual_agreement_rate=args.min_raw_dual_agreement_rate,
            max_supported_disagreements=args.max_supported_disagreements,
        )
        _record_support_calibration_artifact_gate(
            summary,
            python=args.python,
            project_root=project_root,
        )
        _record_support_review_queue_annotation_packet_gate(
            summary,
            python=args.python,
            project_root=project_root,
            dataset=args.support_eval_dataset,
            label_sidecar=args.support_label_sidecar,
        )

    if not args.skip_install_smoke:
        _record_subprocess_step(
            summary,
            "wheel_install_smoke",
            [args.python, "scripts/smoke_package.py", "--install-mode", "wheel"],
            cwd=project_root,
        )
        _record_subprocess_step(
            summary,
            "sdist_install_smoke",
            [args.python, "scripts/smoke_package.py", "--install-mode", "sdist"],
            cwd=project_root,
        )

    if args.include_mcp_extra_smoke or args.require_mcp_extra_smoke:
        _record_mcp_extra_smoke(
            summary,
            python=args.python,
            project_root=project_root,
            require=args.require_mcp_extra_smoke,
        )

    if args.include_mcp_stdio_smoke or args.require_mcp_stdio_smoke:
        _record_mcp_stdio_smoke(
            summary,
            python=args.python,
            project_root=project_root,
            require=args.require_mcp_stdio_smoke,
        )

    if args.include_published_smoke_plan:
        _record_published_smoke_plan(
            summary,
            python=args.python,
            project_root=project_root,
            extra="",
            require_extra_import="",
            mcp_stdio_smoke=False,
        )

    if args.include_published_mcp_smoke_plan:
        _record_published_smoke_plan(
            summary,
            python=args.python,
            project_root=project_root,
            extra="mcp",
            require_extra_import="mcp",
            mcp_stdio_smoke=True,
        )

    if args.include_published_smoke_run:
        _record_published_smoke_plan(
            summary,
            python=args.python,
            project_root=project_root,
            extra="",
            require_extra_import="",
            mcp_stdio_smoke=False,
            run=True,
        )

    if args.include_published_mcp_smoke_run:
        _record_published_smoke_plan(
            summary,
            python=args.python,
            project_root=project_root,
            extra="mcp",
            require_extra_import="mcp",
            mcp_stdio_smoke=True,
            run=True,
        )

    if args.include_testpypi_smoke_plan:
        _record_published_smoke_plan(
            summary,
            python=args.python,
            project_root=project_root,
            extra="",
            require_extra_import="",
            mcp_stdio_smoke=False,
            index_label="testpypi",
            index_url="https://test.pypi.org/simple/",
            extra_index_urls=["https://pypi.org/simple"],
        )

    if args.include_testpypi_mcp_smoke_plan:
        _record_published_smoke_plan(
            summary,
            python=args.python,
            project_root=project_root,
            extra="mcp",
            require_extra_import="mcp",
            mcp_stdio_smoke=True,
            index_label="testpypi",
            index_url="https://test.pypi.org/simple/",
            extra_index_urls=["https://pypi.org/simple"],
        )

    if args.include_testpypi_smoke_run:
        _record_published_smoke_plan(
            summary,
            python=args.python,
            project_root=project_root,
            extra="",
            require_extra_import="",
            mcp_stdio_smoke=False,
            index_label="testpypi",
            index_url="https://test.pypi.org/simple/",
            extra_index_urls=["https://pypi.org/simple"],
            run=True,
        )

    if args.include_testpypi_mcp_smoke_run:
        _record_published_smoke_plan(
            summary,
            python=args.python,
            project_root=project_root,
            extra="mcp",
            require_extra_import="mcp",
            mcp_stdio_smoke=True,
            index_label="testpypi",
            index_url="https://test.pypi.org/simple/",
            extra_index_urls=["https://pypi.org/simple"],
            run=True,
        )

    _record_official_build_and_twine_check(
        summary,
        python=args.python,
        project_root=project_root,
        require_build_tools=args.require_build_tools,
    )

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["ok"] else 1


def _record_project_metadata_contract(summary: Dict[str, Any], project_root: Path) -> None:
    try:
        details = _check_project_metadata_contract(project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "project_metadata_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "project_metadata_contract",
            "status": "passed",
            **details,
        }
    )


def _record_release_artifact_contract_gate(summary: Dict[str, Any], project_root: Path) -> None:
    try:
        details = _check_release_artifact_contract(project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "release_artifact_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "release_artifact_contract",
            "status": "passed",
            **details,
        }
    )


def _check_release_artifact_contract(project_root: Path) -> Dict[str, Any]:
    expected_files = sorted(_expected_sdist_release_files(project_root=project_root))
    missing_files = [relative for relative in expected_files if not (project_root / relative).exists()]
    release_notes = sorted(
        path.relative_to(project_root).as_posix()
        for path in (project_root / "docs" / "releases").glob("*.md")
    )
    manifest = _read_required_text(project_root / "MANIFEST.in")
    required_manifest_rules = [
        "include README.md",
        "include LICENSE",
        "include CHANGELOG.md",
        "include CITATION.cff",
        "recursive-include docs *.md *.svg *.csv *.yml",
        "recursive-include examples *.json *.jsonl *.md *.txt",
        "recursive-include data/eval *.json",
        "recursive-include skills *.md *.yaml",
        "recursive-include scripts *.py",
        "recursive-include configs *.yaml",
        "prune docs/superpowers",
        "prune docs/issues",
        "exclude docs/proposal.md",
        "exclude scripts/run_agent.py",
        "exclude scripts/evaluate.py",
    ]
    missing_manifest_rules = [rule for rule in required_manifest_rules if rule not in manifest]
    expected_release_notes = sorted(relative for relative in expected_files if relative.startswith("docs/releases/"))
    errors = []

    if missing_files:
        errors.append("expected sdist release files are missing from the project tree: " + ", ".join(missing_files))
    if missing_manifest_rules:
        errors.append("MANIFEST.in missing release artifact rules: " + ", ".join(missing_manifest_rules))
    if release_notes != expected_release_notes:
        errors.append(
            "dynamic release-note sdist contract mismatch: "
            f"notes={release_notes}, expected_entries={expected_release_notes}"
        )
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "expected_sdist_release_file_count": len(expected_files),
        "expected_sdist_release_files": expected_files,
        "release_notes": release_notes,
        "release_note_count": len(release_notes),
        "manifest_rules_checked": required_manifest_rules,
        "excluded_legacy_paths": [
            "src/",
            "docs/superpowers/",
            "docs/issues/",
            "docs/proposal.md",
            "scripts/run_agent.py",
            "scripts/evaluate.py",
        ],
        "policy": "release artifacts ship public docs, examples, configs, eval fixtures, scripts, and the agent skill while excluding legacy source and historical planning surfaces",
    }


def _record_legacy_src_shim_contract(summary: Dict[str, Any], project_root: Path) -> None:
    try:
        details = _check_legacy_src_shim_contract(project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "legacy_src_shim_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "legacy_src_shim_contract",
            "status": "passed",
            **details,
        }
    )


def _check_legacy_src_shim_contract(project_root: Path) -> Dict[str, Any]:
    legacy_root = project_root / "src"
    if not legacy_root.exists():
        raise RuntimeError("legacy src compatibility package is missing")

    errors: List[str] = []
    files = sorted(legacy_root.rglob("*.py"))
    for path in files:
        relative = path.relative_to(project_root).as_posix()
        text = path.read_text(encoding="utf-8")
        line_count = len(text.splitlines())
        if line_count > 25:
            errors.append(f"{relative} has {line_count} lines; legacy shims should stay thin")
        if re.search(r"^\s*(from\s+src\b|import\s+src\b)", text, flags=re.MULTILINE):
            errors.append(f"{relative} imports from the legacy src namespace")
        if relative != "src/__init__.py" and "citeguard" not in text:
            errors.append(f"{relative} does not forward to citeguard.*")
        if relative != "src/__init__.py" and not re.search(
            r"(Backward-compatible|Compatibility shim|compatibility shim)",
            text,
        ):
            errors.append(f"{relative} does not identify itself as a compatibility shim")

    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "file_count": len(files),
        "max_lines": max((len(path.read_text(encoding="utf-8").splitlines()) for path in files), default=0),
        "checked_root": "src",
        "policy": "legacy shims only; new code imports citeguard.*",
    }


def _record_public_api_contract_gate(summary: Dict[str, Any], project_root: Path) -> None:
    try:
        details = _check_public_api_contract(project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "public_api_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "public_api_contract",
            "status": "passed",
            **details,
        }
    )


def _check_public_api_contract(project_root: Path) -> Dict[str, Any]:
    public_paths = _public_api_contract_paths(project_root)
    package_paths = sorted((project_root / "citeguard").rglob("*.py"))
    legacy_namespace = "s" + "rc"
    pattern = re.compile(rf"\b(from\s+{legacy_namespace}\.|import\s+{legacy_namespace}\b|{legacy_namespace}\.)")
    public_offenders = _paths_with_legacy_src_references(project_root, public_paths, pattern)
    package_offenders = _paths_with_legacy_src_references(project_root, package_paths, pattern)
    migration = _read_required_text(project_root / "docs" / "public_api_migration.md")
    root_exports = _literal_module_all(project_root / "citeguard" / "__init__.py")

    missing_migration_targets = [
        package
        for package in [
            "citeguard.verification",
            "citeguard.retrieval",
            "citeguard.mcp",
            "citeguard.cli",
            "citeguard.runtime",
        ]
        if package not in migration
    ]
    required_root_exports = {
        "__version__",
        "audit_citations",
        "check_claim_support",
        "check_claim_support_set",
        "error_code_registry",
        "error_payload",
        "parse_citation",
        "verify_citation",
    }
    experimental_root_exports = {"api", "benchmark", "orchestrator", "planner", "writer"}
    errors = []
    if public_offenders:
        errors.append("public docs/tests/scripts reference legacy src namespace: " + ", ".join(public_offenders))
    if package_offenders:
        errors.append("citeguard package references legacy src namespace: " + ", ".join(package_offenders))
    if missing_migration_targets:
        errors.append("docs/public_api_migration.md missing public packages: " + ", ".join(missing_migration_targets))
    if "temporary compatibility bridge" not in migration or "DeprecationWarning" not in migration:
        errors.append("public API migration doc must describe legacy src as a temporary compatibility bridge")
    missing_root_exports = sorted(required_root_exports - root_exports)
    if missing_root_exports:
        errors.append("citeguard root facade missing stable exports: " + ", ".join(missing_root_exports))
    experimental_exports = sorted(experimental_root_exports & root_exports)
    if experimental_exports:
        errors.append("citeguard root facade should not expose experimental modules in __all__: " + ", ".join(experimental_exports))
    if "root package facade" not in migration or "does not export the experimental source-checkout modules" not in migration:
        errors.append("public API migration doc should describe the root package facade export boundary")
    local_smoke_public_api_contract = _local_package_smoke_public_api_contract()
    if not local_smoke_public_api_contract["ok"]:
        errors.append(
            "scripts/smoke_package.py _IMPORT_SMOKE missing public API contract checks: "
            + ", ".join(local_smoke_public_api_contract["missing_checks"])
        )
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "public_files_checked": len(public_paths),
        "package_files_checked": len(package_paths),
        "migration_doc": "docs/public_api_migration.md",
        "public_packages": [
            "citeguard.verification",
            "citeguard.retrieval",
            "citeguard.mcp",
            "citeguard.cli",
            "citeguard.runtime",
        ],
        "legacy_reference_pattern": "legacy namespace import/use",
        "public_offenders": public_offenders,
        "package_offenders": package_offenders,
        "root_facade_exports": sorted(root_exports),
        "root_facade_required_exports": sorted(required_root_exports),
        "root_facade_experimental_exports": experimental_exports,
        "local_package_smoke_public_api_contract": local_smoke_public_api_contract,
        "policy": "README, tests, scripts, user-facing docs, and citeguard.* code stay on public citeguard.* imports",
    }


def _local_package_smoke_public_api_contract() -> Dict[str, Any]:
    required_checks = {
        "error_code_registry": "error_code_registry()" in _IMPORT_SMOKE,
        "stable_error_codes": "STABLE_ERROR_CODES" in _IMPORT_SMOKE,
        "stable_error_codes_from_errors_module": "from citeguard.errors import STABLE_ERROR_CODES" in _IMPORT_SMOKE,
        "missing_citation_next_action": "missing_citation_input" in _IMPORT_SMOKE and "provide_missing_input" in _IMPORT_SMOKE,
        "timeout_next_action": "retry_or_check_source_health" in _IMPORT_SMOKE,
        "timeout_retryable": 'error_payload("timeout", "Timed out")["error"]["retryable"] is True' in _IMPORT_SMOKE,
        "error_category": 'ERROR_CODE_CATEGORY["model_unavailable"] == "dependency_limited"' in _IMPORT_SMOKE,
        "root_experimental_exports": "experimental_exports" in _IMPORT_SMOKE
        and all(name in _IMPORT_SMOKE for name in ["api", "benchmark", "orchestrator", "planner", "writer"]),
    }
    missing_checks = sorted(name for name, present in required_checks.items() if not present)
    return {
        "ok": not missing_checks,
        "script": "scripts/smoke_package.py",
        "inline_script": "_IMPORT_SMOKE",
        "checks": sorted(required_checks),
        "missing_checks": missing_checks,
        "stable_error_codes_import": "citeguard.errors",
    }


def _literal_module_all(path: Path) -> set[str]:
    module = ast.parse(_read_required_text(path), filename=str(path))
    for node in module.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__all__":
                    value = ast.literal_eval(node.value)
                    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                        raise RuntimeError(f"{path.relative_to(path.parents[1])} __all__ must be a literal list of strings")
                    return set(value)
    raise RuntimeError(f"{path.relative_to(path.parents[1])} missing literal __all__ export list")


def _public_api_contract_paths(project_root: Path) -> List[Path]:
    paths = [
        project_root / "README.md",
        project_root / "CHANGELOG.md",
        project_root / "ROADMAP.md",
        project_root / "pyproject.toml",
        project_root / "setup.py",
        project_root / "docs" / "architecture.md",
        project_root / "docs" / "benchmark_design.md",
        project_root / "docs" / "benchmark_todo.md",
        project_root / "docs" / "chinaxiv_spike.md",
        project_root / "docs" / "cli_reference.md",
        project_root / "docs" / "configuration.md",
        project_root / "docs" / "mcp_setup.md",
        project_root / "docs" / "error_codes.md",
        project_root / "docs" / "github_launch.md",
        project_root / "docs" / "release_checklist.md",
        project_root / "docs" / "security_compliance.md",
        project_root / "docs" / "support_labeling_guidelines.md",
        project_root / "skills" / "citeguard-verify" / "SKILL.md",
        project_root / "skills" / "citeguard-verify" / "references" / "examples.md",
        project_root / "skills" / "citeguard-verify" / "agents" / "openai.yaml",
    ]
    for pattern in ("*.json", "*.jsonl", "*.md", "*.txt"):
        paths.extend(sorted((project_root / "examples").glob(pattern)))
    releases_dir = project_root / "docs" / "releases"
    if releases_dir.exists():
        paths.extend(sorted(releases_dir.glob("*.md")))
    paths.extend(sorted((project_root / "tests").glob("test_*.py")))
    paths.extend(sorted((project_root / "scripts").glob("*.py")))
    return [path for path in paths if path.exists()]


def _paths_with_legacy_src_references(project_root: Path, paths: List[Path], pattern: re.Pattern[str]) -> List[str]:
    offenders = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if pattern.search(text):
            offenders.append(path.relative_to(project_root).as_posix())
    return offenders


def _record_cache_replay_fixture_gate(summary: Dict[str, Any], *, python: str, project_root: Path) -> None:
    try:
        details = _check_cache_replay_fixture_gate(python=python, project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "cache_replay_fixture",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "cache_replay_fixture",
            "status": "passed",
            **details,
        }
    )


def _check_cache_replay_fixture_gate(*, python: str, project_root: Path) -> Dict[str, Any]:
    from citeguard.graph import CitationRecord
    from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
    from citeguard.runtime import build_configured_source
    from citeguard.verification.cache import CachingMetadataSource

    with tempfile.TemporaryDirectory(prefix="citeguard-cache-replay-") as tmpdir:
        tmp = Path(tmpdir)
        cache_db = tmp / "verification_cache.sqlite"
        fixture_a = tmp / "fixture-a.json"
        fixture_b = tmp / "fixture-b.json"
        fixture_manifest = tmp / "fixture-manifest.json"
        fixture_lookup = tmp / "fixture-lookup.json"
        record = CitationRecord(
            citation_id="release-cache-1",
            title="Release Cache Replay Fixture",
            authors=["CiteGuard Maintainer"],
            year=2026,
            venue="Release Gate",
            source="release_fixture",
            abstract="A deterministic cache replay fixture for release validation.",
        )
        cached = CachingMetadataSource(InMemoryMetadataSource([record]), db_path=str(cache_db))
        cached.search("Release Cache Replay Fixture", top_k=5)

        inspect_before_cmd = [
            python,
            "-m",
            "citeguard",
            "cache",
            "inspect",
            "--path",
            str(cache_db),
        ]
        inspect_before = json.loads(_run(inspect_before_cmd, cwd=project_root).stdout)

        manifests = []
        commands = []
        for fixture_path in (fixture_a, fixture_b):
            cmd = [
                python,
                "-m",
                "citeguard",
                "cache",
                "export",
                "--path",
                str(cache_db),
                "--deterministic",
                "--output",
                str(fixture_path),
            ]
            completed = _run(cmd, cwd=project_root)
            commands.append(cmd)
            manifests.append(json.loads(completed.stdout))

        fixture_text_a = fixture_a.read_text(encoding="utf-8")
        fixture_text_b = fixture_b.read_text(encoding="utf-8")
        fixture_records = json.loads(fixture_text_a)
        replay_source = build_configured_source(env={"CITEGUARD_FIXTURE_CITATIONS": str(fixture_a)})
        replay_records = replay_source.all_records()
        manifest_cmd = [
            python,
            "-m",
            "citeguard",
            "cache",
            "export",
            "--path",
            str(cache_db),
            "--deterministic",
            "--include-manifest",
            "--output",
            str(fixture_manifest),
        ]
        manifest_stdout = json.loads(_run(manifest_cmd, cwd=project_root).stdout)
        manifest_fixture_payload = json.loads(fixture_manifest.read_text(encoding="utf-8"))
        manifest_replay_source = build_configured_source(env={"CITEGUARD_FIXTURE_CITATIONS": str(fixture_manifest)})
        manifest_replay_records = manifest_replay_source.all_records()

        cached.lookup(CitationRecord(citation_id="release-cache-candidate", title="Release Cache Replay Fixture", year=2026))
        lookup_cmd = [
            python,
            "-m",
            "citeguard",
            "cache",
            "export",
            "--path",
            str(cache_db),
            "--deterministic",
            "--operation",
            "lookup",
            "--output",
            str(fixture_lookup),
        ]
        lookup_stdout = json.loads(_run(lookup_cmd, cwd=project_root).stdout)
        lookup_fixture_records = json.loads(fixture_lookup.read_text(encoding="utf-8"))
        lookup_replay_source = build_configured_source(env={"CITEGUARD_FIXTURE_CITATIONS": str(fixture_lookup)})
        lookup_replay_records = lookup_replay_source.all_records()
        lookup_inspect_cmd = [
            python,
            "-m",
            "citeguard",
            "cache",
            "inspect",
            "--path",
            str(cache_db),
            "--operation",
            "lookup",
        ]
        lookup_inspect = json.loads(_run(lookup_inspect_cmd, cwd=project_root).stdout)

        missing_source_clear_cmd = [
            python,
            "-m",
            "citeguard",
            "cache",
            "clear",
            "--path",
            str(cache_db),
            "--source",
            "openalex",
        ]
        missing_source_clear_payload = json.loads(_run(missing_source_clear_cmd, cwd=project_root).stdout)

        lookup_clear_cmd = [
            python,
            "-m",
            "citeguard",
            "cache",
            "clear",
            "--path",
            str(cache_db),
            "--operation",
            "lookup",
        ]
        lookup_clear_payload = json.loads(_run(lookup_clear_cmd, cwd=project_root).stdout)
        inspect_after_lookup_clear_cmd = [
            python,
            "-m",
            "citeguard",
            "cache",
            "inspect",
            "--path",
            str(cache_db),
        ]
        inspect_after_lookup_clear = json.loads(_run(inspect_after_lookup_clear_cmd, cwd=project_root).stdout)

        clear_cmd = [
            python,
            "-m",
            "citeguard",
            "cache",
            "clear",
            "--path",
            str(cache_db),
        ]
        clear_payload = json.loads(_run(clear_cmd, cwd=project_root).stdout)
        inspect_after_cmd = [
            python,
            "-m",
            "citeguard",
            "cache",
            "inspect",
            "--path",
            str(cache_db),
        ]
        inspect_after = json.loads(_run(inspect_after_cmd, cwd=project_root).stdout)

    leaked_timestamp_fields = []
    provenance_fields: Dict[str, Any] = {}
    for item in fixture_records if isinstance(fixture_records, list) else []:
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
        provenance = metadata.get("cache_provenance", {}) if isinstance(metadata, dict) else {}
        if isinstance(provenance, dict):
            provenance_fields = {
                "operation": provenance.get("operation"),
                "source": provenance.get("source"),
                "query": provenance.get("query"),
                "normalized_query": provenance.get("normalized_query"),
                "record_source": provenance.get("record_source"),
                "raw_match_score": provenance.get("raw_match_score"),
            }
        if "cache_updated_at" in metadata:
            leaked_timestamp_fields.append("metadata.cache_updated_at")
        if "timestamp" in provenance:
            leaked_timestamp_fields.append("metadata.cache_provenance.timestamp")

    errors = []
    if not manifests or not all(manifest.get("deterministic") for manifest in manifests):
        errors.append("cache export manifest did not report deterministic=true")
    if any(manifest.get("exported_at") is not None for manifest in manifests):
        errors.append("deterministic cache export manifest leaked exported_at")
    if any(manifest.get("cache_oldest_entry_timestamp") is not None for manifest in manifests):
        errors.append("deterministic cache export manifest leaked oldest cache timestamp")
    if any(manifest.get("cache_newest_entry_timestamp") is not None for manifest in manifests):
        errors.append("deterministic cache export manifest leaked newest cache timestamp")
    if fixture_text_a != fixture_text_b:
        errors.append("deterministic cache fixture exports were not byte-identical")
    if not isinstance(fixture_records, list) or len(fixture_records) != 1:
        errors.append("deterministic cache fixture should contain exactly one record")
    if leaked_timestamp_fields:
        errors.append("deterministic cache fixture leaked timestamp-only provenance")
    if provenance_fields.get("operation") != "search":
        errors.append("deterministic cache fixture should preserve cache_provenance.operation=search")
    if provenance_fields.get("source") != "metadata_source":
        errors.append("deterministic cache fixture should preserve cache_provenance.source")
    if provenance_fields.get("query") != "Release Cache Replay Fixture":
        errors.append("deterministic cache fixture should preserve cache_provenance.query")
    if provenance_fields.get("normalized_query") != "release cache replay fixture":
        errors.append("deterministic cache fixture should preserve cache_provenance.normalized_query")
    if provenance_fields.get("record_source") != "release_fixture":
        errors.append("deterministic cache fixture should preserve cache_provenance.record_source")
    if not isinstance(provenance_fields.get("raw_match_score"), (int, float)):
        errors.append("deterministic cache fixture should preserve numeric cache_provenance.raw_match_score")
    if not replay_records or replay_records[0].title != "Release Cache Replay Fixture":
        errors.append("offline fixture replay did not load the exported record")
    if replay_records and replay_records[0].metadata.get("cache_provenance", {}).get("operation") != "search":
        errors.append("offline fixture replay should preserve record metadata.cache_provenance")
    if manifest_stdout.get("fixture_format") != "manifest_records":
        errors.append("manifest cache fixture export should report fixture_format=manifest_records")
    if manifest_fixture_payload.get("fixture_manifest", {}).get("fixture_format") != "manifest_records":
        errors.append("manifest cache fixture should include fixture_manifest.fixture_format")
    if manifest_fixture_payload.get("fixture_manifest", {}).get("deterministic") is not True:
        errors.append("manifest cache fixture should preserve deterministic=true")
    if len(manifest_fixture_payload.get("records", [])) != 1:
        errors.append("manifest cache fixture should include exactly one record")
    if not manifest_replay_records or manifest_replay_records[0].title != "Release Cache Replay Fixture":
        errors.append("manifest cache fixture replay did not load the exported record")
    if manifest_replay_records and manifest_replay_records[0].metadata.get("cache_provenance", {}).get("operation") != "search":
        errors.append("manifest cache fixture replay should preserve record metadata.cache_provenance")
    if lookup_stdout.get("cache_entry_count") != 2:
        errors.append("filtered lookup cache export should preserve total cache entry count")
    if lookup_stdout.get("selected_cache_entry_count") != 1:
        errors.append("filtered lookup cache export should report one selected cache entry")
    if lookup_stdout.get("selected_cache_entry_prefixes", {}).get("lookup") != 1:
        errors.append("filtered lookup cache export should report selected lookup prefix count")
    if lookup_stdout.get("selected_cache_entry_prefixes", {}).get("search") != 0:
        errors.append("filtered lookup cache export should exclude search prefix count")
    if lookup_stdout.get("export_filters", {}).get("operation") != "lookup":
        errors.append("filtered lookup cache export should report export_filters.operation=lookup")
    if not isinstance(lookup_fixture_records, list) or len(lookup_fixture_records) != 1:
        errors.append("filtered lookup cache fixture should include exactly one deduped record")
    if lookup_fixture_records and lookup_fixture_records[0].get("metadata", {}).get("cache_provenance", {}).get("operation") != "lookup":
        errors.append("filtered lookup cache fixture should preserve lookup provenance")
    if not lookup_replay_records or lookup_replay_records[0].title != "Release Cache Replay Fixture":
        errors.append("filtered lookup cache fixture replay did not load the exported record")
    if lookup_inspect.get("entries") != 2:
        errors.append("filtered lookup cache inspect should preserve total cache entry count")
    if lookup_inspect.get("selected_entries") != 1:
        errors.append("filtered lookup cache inspect should report one selected entry")
    if lookup_inspect.get("selected_entry_prefixes", {}).get("lookup") != 1:
        errors.append("filtered lookup cache inspect should report selected lookup prefix count")
    if lookup_inspect.get("selected_entry_prefixes", {}).get("search") != 0:
        errors.append("filtered lookup cache inspect should exclude search prefix count")
    if lookup_inspect.get("inspect_filters", {}).get("operation") != "lookup":
        errors.append("filtered lookup cache inspect should report inspect_filters.operation=lookup")
    if "Release Cache Replay Fixture" in json.dumps(lookup_inspect, sort_keys=True):
        errors.append("filtered lookup cache inspect should not expose raw query text")
    if missing_source_clear_payload.get("cleared_entries") != 0:
        errors.append("nonmatching source cache clear should not clear entries")
    if missing_source_clear_payload.get("remaining_entries") != 2:
        errors.append("nonmatching source cache clear should preserve both entries")
    if missing_source_clear_payload.get("clear_filters", {}).get("source") != "openalex":
        errors.append("nonmatching source cache clear should report clear_filters.source=openalex")
    if missing_source_clear_payload.get("selected_entry_prefixes", {}).get("search") != 0:
        errors.append("nonmatching source cache clear should report no selected search rows")
    if missing_source_clear_payload.get("selected_entry_prefixes", {}).get("lookup") != 0:
        errors.append("nonmatching source cache clear should report no selected lookup rows")
    if lookup_clear_payload.get("cleared_entries") != 1:
        errors.append("filtered lookup cache clear should report one cleared entry")
    if lookup_clear_payload.get("remaining_entries") != 1:
        errors.append("filtered lookup cache clear should preserve one remaining entry")
    if lookup_clear_payload.get("clear_filters", {}).get("operation") != "lookup":
        errors.append("filtered lookup cache clear should report clear_filters.operation=lookup")
    if lookup_clear_payload.get("selected_entry_prefixes", {}).get("lookup") != 1:
        errors.append("filtered lookup cache clear should report selected lookup prefix count")
    if lookup_clear_payload.get("selected_entry_prefixes", {}).get("search") != 0:
        errors.append("filtered lookup cache clear should exclude search prefix count")
    if inspect_after_lookup_clear.get("entries") != 1:
        errors.append("cache inspect after filtered clear should report one remaining entry")
    if inspect_after_lookup_clear.get("entry_prefixes", {}).get("search") != 1:
        errors.append("cache inspect after filtered clear should preserve search row")
    if inspect_after_lookup_clear.get("entry_prefixes", {}).get("lookup") != 0:
        errors.append("cache inspect after filtered clear should remove lookup row")
    if inspect_before.get("entries") != 1:
        errors.append("cache inspect before clear should report one cached entry")
    if inspect_before.get("entry_prefixes", {}).get("search") != 1:
        errors.append("cache inspect before clear should count one search entry")
    if "Release Cache Replay Fixture" in json.dumps(inspect_before, sort_keys=True):
        errors.append("cache inspect should not expose raw query text")
    if clear_payload.get("cleared_entries") != 1:
        errors.append("cache clear should report one remaining cleared entry after filtered clear")
    if clear_payload.get("remaining_entries") != 0:
        errors.append("cache clear should report zero remaining entries")
    if clear_payload.get("schema_version") != inspect_before.get("schema_version"):
        errors.append("cache clear should preserve cache schema metadata")
    if inspect_after.get("entries") != 0:
        errors.append("cache inspect after clear should report zero entries")
    if inspect_after.get("schema_version") != inspect_before.get("schema_version"):
        errors.append("cache inspect after clear should preserve schema_version")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "commands": [
            inspect_before_cmd,
            *commands,
            manifest_cmd,
            lookup_cmd,
            lookup_inspect_cmd,
            missing_source_clear_cmd,
            lookup_clear_cmd,
            inspect_after_lookup_clear_cmd,
            clear_cmd,
            inspect_after_cmd,
        ],
        "record_count": manifests[0].get("record_count"),
        "deterministic": manifests[0].get("deterministic"),
        "byte_identical": fixture_text_a == fixture_text_b,
        "fixture_record_count": len(fixture_records),
        "replay_record_title": replay_records[0].title if replay_records else "",
        "manifest_fixture_format": manifest_stdout.get("fixture_format"),
        "manifest_fixture_record_count": len(manifest_fixture_payload.get("records", [])),
        "manifest_replay_record_title": manifest_replay_records[0].title if manifest_replay_records else "",
        "filtered_lookup": {
            "record_count": lookup_stdout.get("record_count"),
            "cache_entry_count": lookup_stdout.get("cache_entry_count"),
            "selected_cache_entry_count": lookup_stdout.get("selected_cache_entry_count"),
            "selected_cache_entry_prefixes": lookup_stdout.get("selected_cache_entry_prefixes", {}),
            "export_filters": lookup_stdout.get("export_filters", {}),
            "inspect_selected_entries": lookup_inspect.get("selected_entries"),
            "inspect_selected_entry_prefixes": lookup_inspect.get("selected_entry_prefixes", {}),
            "inspect_filters": lookup_inspect.get("inspect_filters", {}),
            "missing_source_clear_cleared_entries": missing_source_clear_payload.get("cleared_entries"),
            "missing_source_clear_remaining_entries": missing_source_clear_payload.get("remaining_entries"),
            "missing_source_clear_selected_entry_prefixes": missing_source_clear_payload.get("selected_entry_prefixes", {}),
            "missing_source_clear_filters": missing_source_clear_payload.get("clear_filters", {}),
            "clear_cleared_entries": lookup_clear_payload.get("cleared_entries"),
            "clear_remaining_entries": lookup_clear_payload.get("remaining_entries"),
            "clear_selected_entry_prefixes": lookup_clear_payload.get("selected_entry_prefixes", {}),
            "clear_filters": lookup_clear_payload.get("clear_filters", {}),
            "fixture_record_count": len(lookup_fixture_records) if isinstance(lookup_fixture_records, list) else 0,
            "replay_record_title": lookup_replay_records[0].title if lookup_replay_records else "",
            "cache_provenance_operation": (
                lookup_fixture_records[0].get("metadata", {}).get("cache_provenance", {}).get("operation")
                if isinstance(lookup_fixture_records, list) and lookup_fixture_records
                else ""
            ),
        },
        "leaked_timestamp_fields": sorted(set(leaked_timestamp_fields)),
        "cache_provenance": provenance_fields,
        "inspect_before": {
            "schema_version": inspect_before.get("schema_version"),
            "entries": inspect_before.get("entries"),
            "entry_prefixes": inspect_before.get("entry_prefixes", {}),
        },
        "clear": {
            "schema_version": clear_payload.get("schema_version"),
            "cleared_entries": clear_payload.get("cleared_entries"),
            "remaining_entries": clear_payload.get("remaining_entries"),
        },
        "inspect_after_filtered_clear": {
            "schema_version": inspect_after_lookup_clear.get("schema_version"),
            "entries": inspect_after_lookup_clear.get("entries"),
            "entry_prefixes": inspect_after_lookup_clear.get("entry_prefixes", {}),
        },
        "inspect_after": {
            "schema_version": inspect_after.get("schema_version"),
            "entries": inspect_after.get("entries"),
            "entry_prefixes": inspect_after.get("entry_prefixes", {}),
        },
        "policy": "deterministic cache replay fixtures strip timestamps while preserving source, query, and raw match score provenance; operation-filtered, records-only, and manifest-wrapped fixtures replay offline; filtered manifests, inspect output, and clear output keep total and selected cache counts separate; inspect/clear expose non-sensitive counts and preserve schema metadata",
    }


def _record_error_codes_contract_gate(summary: Dict[str, Any], *, project_root: Path) -> None:
    try:
        details = _check_error_codes_contract_gate(project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "error_codes_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "error_codes_contract",
            "status": "passed",
            **details,
        }
    )


def _check_error_codes_contract_gate(*, project_root: Path) -> Dict[str, Any]:
    from citeguard.errors import error_code_registry, error_payload, is_stable_error_code, runtime_config_error_details
    from citeguard.verification import STABLE_NEXT_ACTIONS

    docs = _read_required_text(project_root / "docs" / "error_codes.md")
    stable_codes_section = docs.split("## Stable Codes", 1)[1].split("## Details Contract", 1)[0]
    next_action_section = docs.split("## Stable next_action Values", 1)[1].split("## Stable Codes", 1)[0]
    documented_codes = set(re.findall(r"\| `([^`]+)` \|", stable_codes_section))
    documented_next_actions = set(re.findall(r"\| `([^`]+)` \|", next_action_section))
    documented_code_rows = _error_code_doc_rows(stable_codes_section)
    registry_snapshot = error_code_registry()
    registry_codes = set(STABLE_ERROR_CODES)
    registry_next_actions = set(ERROR_CODE_NEXT_ACTION.values())

    probe = error_payload(
        "missing_citation_input",
        "Provide citation input.",
        details={"command": "verify"},
        exit_code=2,
    )
    config_probe = runtime_config_error_details(
        "Unknown CITEGUARD_SOURCES value(s): bad. Valid values: arxiv, openalex.",
        base={"tool": "verify_citation_tool"},
    )
    numeric_config_probe = runtime_config_error_details(
        "CITEGUARD_HTTP_TIMEOUT must be a positive integer.",
        base={"command": "verify"},
        env={"CITEGUARD_HTTP_TIMEOUT": "0"},
    )

    errors = []
    if registry_codes != set(ERROR_CODE_RECOVERY):
        errors.append("STABLE_ERROR_CODES must match ERROR_CODE_RECOVERY keys")
    if registry_codes != set(ERROR_CODE_NEXT_ACTION):
        errors.append("STABLE_ERROR_CODES must match ERROR_CODE_NEXT_ACTION keys")
    if registry_codes != set(ERROR_CODE_RETRYABLE):
        errors.append("STABLE_ERROR_CODES must match ERROR_CODE_RETRYABLE keys")
    if registry_codes != set(ERROR_CODE_CATEGORY):
        errors.append("STABLE_ERROR_CODES must match ERROR_CODE_CATEGORY keys")
    if registry_snapshot.get("schema_version") != ERROR_SCHEMA_VERSION:
        errors.append("error_code_registry schema_version mismatch")
    snapshot_codes = set((registry_snapshot.get("codes") or {}))
    if snapshot_codes != registry_codes:
        errors.append(
            "error_code_registry code mismatch: "
            f"missing={sorted(registry_codes - snapshot_codes)} extra={sorted(snapshot_codes - registry_codes)}"
        )
    for code in registry_codes:
        snapshot_item = (registry_snapshot.get("codes") or {}).get(code, {})
        if snapshot_item.get("recovery") != ERROR_CODE_RECOVERY.get(code):
            errors.append(f"error_code_registry[{code}].recovery mismatch")
        if snapshot_item.get("next_action") != ERROR_CODE_NEXT_ACTION.get(code):
            errors.append(f"error_code_registry[{code}].next_action mismatch")
        if snapshot_item.get("retryable") != ERROR_CODE_RETRYABLE.get(code):
            errors.append(f"error_code_registry[{code}].retryable mismatch")
        if snapshot_item.get("category") != ERROR_CODE_CATEGORY.get(code):
            errors.append(f"error_code_registry[{code}].category mismatch")
    if documented_codes != registry_codes:
        errors.append(
            "docs/error_codes.md stable code table mismatch: "
            f"missing={sorted(registry_codes - documented_codes)} extra={sorted(documented_codes - registry_codes)}"
        )
    for code in registry_codes:
        doc_row = documented_code_rows.get(code, {})
        if doc_row.get("category") != ERROR_CODE_CATEGORY[code]:
            errors.append(f"docs/error_codes.md {code} category mismatch")
        if doc_row.get("retryable") != str(ERROR_CODE_RETRYABLE[code]).lower():
            errors.append(f"docs/error_codes.md {code} retryable mismatch")
        if doc_row.get("recovery") != ERROR_CODE_RECOVERY[code]:
            errors.append(f"docs/error_codes.md {code} recovery mismatch")
    if documented_next_actions != STABLE_NEXT_ACTIONS:
        errors.append(
            "docs/error_codes.md next_action table mismatch: "
            f"missing={sorted(STABLE_NEXT_ACTIONS - documented_next_actions)} "
            f"extra={sorted(documented_next_actions - STABLE_NEXT_ACTIONS)}"
        )
    if not registry_next_actions.issubset(STABLE_NEXT_ACTIONS):
        errors.append(
            "ERROR_CODE_NEXT_ACTION values must be stable next actions: "
            + ", ".join(sorted(registry_next_actions - STABLE_NEXT_ACTIONS))
        )
    for code in registry_codes:
        if not is_stable_error_code(code):
            errors.append(f"is_stable_error_code rejected documented code {code}")
        if not ERROR_CODE_RECOVERY.get(code):
            errors.append(f"ERROR_CODE_RECOVERY[{code}] must be non-empty")
        if not ERROR_CODE_NEXT_ACTION.get(code):
            errors.append(f"ERROR_CODE_NEXT_ACTION[{code}] must be non-empty")
    required_phrases = [
        "ERROR_SCHEMA_VERSION",
        "ERROR_CODE_RECOVERY",
        "ERROR_CODE_NEXT_ACTION",
        "ERROR_CODE_RETRYABLE",
        "ERROR_CODE_CATEGORY",
        "error_code_registry",
        "runtime_config_error_details",
        "`error.recovery` is present on every error payload",
        "`error.next_action` is present on every error payload",
        "`error.retryable` is true",
        "`error.category` gives a compact stable class",
        "`error.retryable` is present on every error payload",
        "`error.category` is present on every error payload",
        "Prefer `error.retryable` and `error.category`",
        "MCP tools return the same shape as the tool result",
        "Prefer `error.next_action` for workflow branching",
    ]
    normalized_docs = _normalize_markdown_text(docs)
    for phrase in required_phrases:
        if _normalize_markdown_text(phrase) not in normalized_docs:
            errors.append(f"docs/error_codes.md missing required phrase: {phrase}")
    if probe.get("ok") is not False:
        errors.append("error_payload must set ok=false")
    if probe.get("schema_version") != ERROR_SCHEMA_VERSION:
        errors.append("error_payload schema_version mismatch")
    if probe.get("exit_code") != 2:
        errors.append("error_payload exit_code mismatch")
    probe_error = probe.get("error", {})
    if probe_error.get("code") != "missing_citation_input":
        errors.append("error_payload did not preserve code")
    if probe_error.get("details") != {"command": "verify"}:
        errors.append("error_payload did not preserve details")
    if probe_error.get("recovery") != ERROR_CODE_RECOVERY["missing_citation_input"]:
        errors.append("error_payload recovery mismatch")
    if probe_error.get("next_action") != ERROR_CODE_NEXT_ACTION["missing_citation_input"]:
        errors.append("error_payload next_action mismatch")
    if probe_error.get("retryable") != ERROR_CODE_RETRYABLE["missing_citation_input"]:
        errors.append("error_payload retryable mismatch")
    if probe_error.get("category") != ERROR_CODE_CATEGORY["missing_citation_input"]:
        errors.append("error_payload category mismatch")
    if config_probe.get("tool") != "verify_citation_tool":
        errors.append("runtime_config_error_details did not preserve base details")
    if config_probe.get("field") != "CITEGUARD_SOURCES":
        errors.append("runtime_config_error_details did not parse environment field")
    if config_probe.get("source") != "environment":
        errors.append("runtime_config_error_details did not mark environment source")
    if config_probe.get("invalid_values") != ["bad"]:
        errors.append("runtime_config_error_details did not parse invalid values")
    if config_probe.get("valid_values") != ["arxiv", "openalex"]:
        errors.append("runtime_config_error_details did not parse valid values")
    if numeric_config_probe.get("field") != "CITEGUARD_HTTP_TIMEOUT":
        errors.append("runtime_config_error_details did not parse numeric environment field")
    if numeric_config_probe.get("source") != "environment":
        errors.append("runtime_config_error_details did not mark numeric environment source")
    if numeric_config_probe.get("expected") != "positive integer":
        errors.append("runtime_config_error_details did not parse numeric expectation")
    if numeric_config_probe.get("received") != "0":
        errors.append("runtime_config_error_details did not preserve numeric received value")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "schema_version": ERROR_SCHEMA_VERSION,
        "documented_code_count": len(documented_codes),
        "stable_code_count": len(registry_codes),
        "registry_code_count": len(snapshot_codes),
        "documented_next_action_count": len(documented_next_actions),
        "error_codes": sorted(registry_codes),
        "error_next_actions": {code: ERROR_CODE_NEXT_ACTION[code] for code in sorted(registry_codes)},
        "documented_error_recovery": {code: documented_code_rows.get(code, {}).get("recovery", "") for code in sorted(registry_codes)},
        "error_retryable": {code: ERROR_CODE_RETRYABLE[code] for code in sorted(registry_codes)},
        "error_categories": {code: ERROR_CODE_CATEGORY[code] for code in sorted(registry_codes)},
        "error_registry_sample": {
            "code": "missing_citation_input",
            "next_action": registry_snapshot["codes"]["missing_citation_input"]["next_action"],
            "recovery": registry_snapshot["codes"]["missing_citation_input"]["recovery"],
            "retryable": registry_snapshot["codes"]["missing_citation_input"]["retryable"],
            "category": registry_snapshot["codes"]["missing_citation_input"]["category"],
        },
        "docs_file": "docs/error_codes.md",
        "sample_error": {
            "code": probe_error.get("code"),
            "next_action": probe_error.get("next_action"),
            "recovery": probe_error.get("recovery"),
            "retryable": probe_error.get("retryable"),
            "category": probe_error.get("category"),
            "details_keys": sorted(probe_error.get("details", {})),
        },
        "runtime_config_error_details": {
            "field": config_probe.get("field"),
            "source": config_probe.get("source"),
            "invalid_values": config_probe.get("invalid_values", []),
            "valid_values": config_probe.get("valid_values", []),
            "base_keys": sorted(set(config_probe) & {"command", "tool"}),
        },
        "numeric_runtime_config_error_details": {
            "field": numeric_config_probe.get("field"),
            "source": numeric_config_probe.get("source"),
            "expected": numeric_config_probe.get("expected"),
            "received": numeric_config_probe.get("received"),
            "base_keys": sorted(set(numeric_config_probe) & {"command", "tool"}),
        },
        "policy": "stable error codes, recovery guidance, next_action mappings, and docs stay synchronized for agents",
    }


def _error_code_doc_rows(stable_codes_section: str) -> Dict[str, Dict[str, str]]:
    rows: Dict[str, Dict[str, str]] = {}
    for line in stable_codes_section.splitlines():
        stripped = line.strip()
        if not stripped.startswith("| `"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 5:
            continue
        code = cells[0].strip("`")
        rows[code] = {
            "category": cells[1],
            "retryable": cells[2].lower(),
            "meaning": cells[3],
            "recovery": cells[4].replace("\\|", "|"),
        }
    return rows


def _record_configuration_contract_gate(summary: Dict[str, Any], *, project_root: Path) -> None:
    try:
        details = _check_configuration_contract_gate(project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "configuration_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "configuration_contract",
            "status": "passed",
            **details,
        }
    )


def _check_configuration_contract_gate(*, project_root: Path) -> Dict[str, Any]:
    from citeguard.runtime import environment_status

    docs = {
        "README.md": _read_required_text(project_root / "README.md"),
        "docs/configuration.md": _read_required_text(project_root / "docs" / "configuration.md"),
        "docs/release_checklist.md": _read_required_text(project_root / "docs" / "release_checklist.md"),
    }
    combined_docs = "\n".join(docs.values())
    required_env_vars = [
        "CITEGUARD_SOURCES",
        "CITEGUARD_CACHE",
        "CITEGUARD_FIXTURE_CITATIONS",
        "CITEGUARD_MAILTO",
        "CITEGUARD_HTTP_TIMEOUT",
        "CITEGUARD_HTTP_RETRIES",
        "CITEGUARD_HTTP_RETRY_BACKOFF",
        "CITEGUARD_HTTP_MIN_INTERVAL",
        "CITEGUARD_REMOTE_EVIDENCE",
        "CITEGUARD_EVIDENCE_TIMEOUT",
        "SEMANTIC_SCHOLAR_API_KEY",
        "CITEGUARD_RERANKER_MODEL",
        "CITEGUARD_NLI_MODEL",
    ]
    required_status_fields = [
        "configured_sources",
        "requested_sources",
        "source_health",
        "cache_status",
        "polite_access",
        "remote_evidence_policy",
        "support_models",
    ]
    required_safety_phrases = [
        "not evidence that a citation is fabricated",
        "Disabled by default",
        "full_text_file",
        "fix_configuration",
        "retry_after_seconds",
        "schema_version",
        "entry_prefixes",
        "heuristic_fallback",
        "install_or_configure_dependency",
        "deep_models_available",
        "support_models.install_hint",
        "citeguard[models]",
    ]

    errors = []
    config_doc = docs["docs/configuration.md"]
    normalized_combined_docs = _normalize_markdown_text(combined_docs)
    for variable in required_env_vars:
        if variable not in config_doc:
            errors.append(f"docs/configuration.md missing environment variable {variable}")
    for field in required_status_fields:
        if field not in config_doc:
            errors.append(f"docs/configuration.md missing status field {field}")
    for phrase in required_safety_phrases:
        if _normalize_markdown_text(phrase) not in normalized_combined_docs:
            errors.append(f"configuration docs missing required phrase: {phrase}")
    if "docs/configuration.md" not in docs["README.md"]:
        errors.append("README should link to docs/configuration.md")
    readme_setup_reference = docs["README.md"].split("- Setup/reference:", 1)[-1].split("\n", 1)[0]
    if "docs/configuration.md" not in readme_setup_reference:
        errors.append("README Setup/reference documents should list docs/configuration.md")
    if "configuration_contract" not in docs["docs/release_checklist.md"]:
        errors.append("release checklist should mention configuration_contract")
    release_checklist = docs["docs/release_checklist.md"]
    if "docs/configuration.md" not in release_checklist:
        errors.append("release checklist should include docs/configuration.md in documentation checks")
    if "current CLI, runtime, and MCP behavior" not in release_checklist:
        errors.append("release checklist should verify configuration docs against CLI, runtime, and MCP behavior")

    status = environment_status(
        env={
            "CITEGUARD_FIXTURE_CITATIONS": "examples/citations.jsonl",
            "CITEGUARD_CACHE": ":memory:",
            "CITEGUARD_HTTP_TIMEOUT": "7",
            "CITEGUARD_HTTP_RETRIES": "2",
            "CITEGUARD_HTTP_RETRY_BACKOFF": "0.5",
            "CITEGUARD_HTTP_MIN_INTERVAL": "0.25",
            "CITEGUARD_REMOTE_EVIDENCE": "1",
            "CITEGUARD_EVIDENCE_TIMEOUT": "3",
            "CITEGUARD_RERANKER_MODEL": "release-reranker",
            "CITEGUARD_NLI_MODEL": "release-nli",
            "SEMANTIC_SCHOLAR_API_KEY": "release-key",
        },
        mcp_sdk_available=False,
        module_checker=lambda name: False,
    )
    for field in required_status_fields:
        if field not in status:
            errors.append(f"environment_status missing field {field}")
    if status.get("fixture_citations_path") != "examples/citations.jsonl":
        errors.append("fixture citation path should be visible in status")
    if status.get("cache_path") != ":memory:":
        errors.append("cache path should be visible in status")
    if status.get("http_timeout_seconds") != 7:
        errors.append("HTTP timeout environment override should be visible in status")
    if status.get("http_retries") != 2:
        errors.append("HTTP retries environment override should be visible in status")
    if status.get("http_retry_backoff_seconds") != 0.5:
        errors.append("HTTP retry backoff environment override should be visible in status")
    if status.get("http_min_interval_seconds") != 0.25:
        errors.append("HTTP minimum interval environment override should be visible in status")
    if status.get("evidence_timeout_seconds") != 3:
        errors.append("evidence timeout environment override should be visible in status")
    if status.get("remote_evidence_policy", {}).get("enabled") is not True:
        errors.append("remote evidence environment override should be visible in status")
    if status.get("source_health", {}).get("mode") != "fixture":
        errors.append("fixture mode should be reflected in source_health")
    if status.get("source_health", {}).get("summary", {}).get("next_action") != "continue":
        errors.append("fixture source health should route to continue")
    if status.get("polite_access", {}).get("status") != "fixture_bypasses_live_sources":
        errors.append("fixture mode should bypass live-source polite access warnings")
    support_models = status.get("support_models", {})
    if support_models.get("reranker_model") != "release-reranker":
        errors.append("reranker model environment override should be visible in status")
    if support_models.get("nli_model") != "release-nli":
        errors.append("NLI model environment override should be visible in status")
    if support_models.get("engine") != "heuristic_fallback":
        errors.append("missing model dependencies should report support_models.engine=heuristic_fallback")
    if support_models.get("deep_models_available") is not False:
        errors.append("missing model dependencies should report deep_models_available=false")
    if support_models.get("next_action") != "install_or_configure_dependency":
        errors.append("missing model dependencies should route agents to install_or_configure_dependency")
    if "model_dependencies" not in support_models:
        errors.append("support_models should expose dependency availability")
    if "missing_dependencies" not in support_models:
        errors.append("support_models should expose missing dependency names")
    install_hint = str(support_models.get("install_hint", ""))
    if 'python -m pip install "citeguard[models]"' not in install_hint:
        errors.append("support_models.install_hint should prefer the published citeguard[models] extra")
    if 'python -m pip install -e ".[models]"' not in install_hint:
        errors.append("support_models.install_hint should still document the source-checkout models fallback")
    if (
        'python -m pip install "citeguard[models]"' in install_hint
        and 'python -m pip install -e ".[models]"' in install_hint
        and install_hint.index('python -m pip install "citeguard[models]"')
        > install_hint.index('python -m pip install -e ".[models]"')
    ):
        errors.append("support_models.install_hint should put the published package command before editable fallback")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "docs_checked": sorted(docs),
        "environment_variables": required_env_vars,
        "status_fields": required_status_fields,
        "fixture_mode": status.get("source_health", {}).get("mode"),
        "cache_path": status.get("cache_path"),
        "http": {
            "timeout_seconds": status.get("http_timeout_seconds"),
            "retries": status.get("http_retries"),
            "retry_backoff_seconds": status.get("http_retry_backoff_seconds"),
            "min_interval_seconds": status.get("http_min_interval_seconds"),
        },
        "remote_evidence_enabled": status.get("remote_evidence_policy", {}).get("enabled"),
        "doc_discoverability": {
            "readme_setup_reference": "docs/configuration.md" in readme_setup_reference,
            "release_checklist_documentation": "docs/configuration.md" in release_checklist,
        },
        "support_models": {
            "reranker_model": support_models.get("reranker_model"),
            "nli_model": support_models.get("nli_model"),
            "engine": support_models.get("engine"),
            "deep_models_available": support_models.get("deep_models_available"),
            "next_action": support_models.get("next_action"),
            "missing_dependencies": support_models.get("missing_dependencies"),
            "install_hint": support_models.get("install_hint"),
        },
        "policy": "runtime configuration docs, status payload fields, and environment-variable overrides stay synchronized for agents",
    }


def _record_mcp_stdio_smoke_contract_gate(summary: Dict[str, Any], *, project_root: Path) -> None:
    try:
        details = _check_mcp_stdio_smoke_contract_gate(project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "mcp_stdio_smoke_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "mcp_stdio_smoke_contract",
            "status": "passed",
            **details,
        }
    )


def _check_mcp_stdio_smoke_contract_gate(*, project_root: Path) -> Dict[str, Any]:
    script = _read_required_text(project_root / "scripts" / "smoke_mcp.py")
    docs = _read_required_text(project_root / "docs" / "mcp_setup.md")
    checklist = _read_required_text(project_root / "docs" / "release_checklist.md")
    readme = _read_required_text(project_root / "README.md")
    mcp_server = _read_required_text(project_root / "citeguard" / "mcp" / "server.py")
    normalized_script = _normalize_markdown_text(script)
    normalized_docs = _normalize_markdown_text("\n".join([docs, checklist, readme]))
    normalized_mcp_server = _normalize_markdown_text(mcp_server)

    required_tools = [
        "citeguard_status_tool",
        "verify_citation_tool",
        "audit_citations_tool",
        "check_claim_support_tool",
        "check_claim_support_set_tool",
        "search_counterevidence_tool",
        "audit_claim_support_tool",
    ]
    required_script_phrases = {
        "initialize": "await session.initialize()",
        "list_tools": "await session.list_tools()",
        "tool_presence_helper": "_require_tool(tool_names,",
        "tool_metadata_index": "tools_by_name",
        "tool_metadata_helper": "_require_tool_description",
        "batch_tool_metadata": "suggested_fix.requires_user_confirmation",
        "batch_suggested_fix_summary_metadata": "review_summary.suggested_fix_summary",
        "batch_suggested_fix_no_auto_apply": "auto_apply_allowed=false",
        "support_tool_metadata_full_text_file": "will not fetch gated",
        "support_set_tool_metadata": "no_unstated_multi_hop_or_full_text_support",
        "offline_fixture_env": "CITEGUARD_FIXTURE_CITATIONS",
        "memory_cache": '"CITEGUARD_CACHE": ":memory:"',
        "status_call": 'session.call_tool("citeguard_status_tool"',
        "status_payload": "_require_status_payload(status, fixture_path)",
        "status_source_items": 'source_health.get("sources")',
        "status_source_item_next_action": "_require_stable_next_action(source_item, expected=\"continue\")",
        "status_source_item_retry_guidance": 'source_item.get("retry_guidance")',
        "status_source_item_retry_delay": 'source_item.get("retry_delay_seconds")',
        "status_summary_retry_delay": 'summary.get("retry_delay_seconds")',
        "status_summary_retry_delay_sources": 'summary.get("retry_delay_sources")',
        "status_support_models": 'payload.get("support_models")',
        "status_support_models_engine": 'support_models.get("engine")',
        "status_support_models_next_action": "_require_stable_next_action(support_models)",
        "fixture_verify_call": 'session.call_tool(\n                        "verify_citation_tool"',
        "verified_verdict": 'verify.get("verdict") != "verified"',
        "audit_payload": "_require_audit_citations_payload(audit)",
        "audit_high_risk": "_require_high_risk_filtered_payload(audit_high_risk, total=2, returned_indexes=[1])",
        "claim_support": "_require_support_payload(support)",
        "full_text_support": "_require_full_text_support_payload(full_text_support)",
        "full_text_file_support": "_require_full_text_file_support_payload(full_text_file_support)",
        "full_text_file_argument": '"full_text_file"',
        "full_text_source_field": "user_full_text_excerpt_1",
        "full_text_file_source_field": "user_full_text_file_1",
        "support_set_full_text_file": "_require_support_set_full_text_file_payload(support_set_full_text_file)",
        "support_set_full_text_file_payload": "support_set_full_text_file",
        "support_audit_full_text": "_require_support_audit_full_text_payload(support_audit_full_text)",
        "support_audit_full_text_payload": "support_audit_full_text",
        "support_set": '"check_claim_support_set_tool"',
        "support_set_counterevidence": "_require_support_set_counterevidence_payload(support_set_counterevidence)",
        "support_set_counterevidence_payload": "support_set_counterevidence",
        "support_audit_set": "_require_support_audit_set_payload(support_audit)",
        "support_audit_nested_full_text_file": "_require_support_audit_nested_full_text_file_payload",
        "support_audit_nested_full_text_file_payload": "support_audit_nested_full_text_file",
        "support_mode_details_helper": "_require_support_mode_details",
        "support_mode_details_decision": "support_mode_details.decision",
        "support_mode_details_policy": "no_unstated_multi_hop_or_full_text_support",
        "support_audit_high_risk": "_require_high_risk_filtered_payload(support_audit_high_risk, total=2, returned_indexes=[1])",
        "support_audit_high_risk_counterevidence": "_require_support_audit_high_risk_counterevidence_payload",
        "support_audit_high_risk_counterevidence_payload": "support_audit_high_risk_counterevidence",
        "counterevidence": "_require_counterevidence_payload(counterevidence)",
        "source_outage_counterevidence": "_require_source_outage_counterevidence_payload(source_outage_counterevidence)",
        "zh_source_outage_counterevidence": "zh_source_outage_counterevidence",
        "structured_error_helper": "_require_error_payload",
        "structured_error_retryable": "ERROR_CODE_RETRYABLE",
        "structured_error_category": "ERROR_CODE_CATEGORY",
        "shape_error_helper": "_require_shape_error_payload",
        "file_error_helper": "_require_file_error_payload",
        "support_set_full_text_file_missing": "missing_support_set_full_text_file",
        "full_text_file_error_details": "full-text-file error details",
        "stable_next_actions": "STABLE_NEXT_ACTIONS",
        "require_sdk_flag": "--require-sdk",
        "missing_sdk_message": "MCP SDK is not installed",
        "missing_sdk_skip": 'print(f"SKIP: {message}")',
        "missing_sdk_fail": 'print(f"FAIL: {message}")',
        "success_coverage": "OK: MCP stdio smoke passed",
    }
    structured_error_codes = [
        "missing_citation_input",
        "missing_claim",
        "invalid_input",
        "file_error",
    ]
    shape_error_fields = [
        "field=\"citations\"",
        "field=\"items\"",
        "expected=\"non_empty_list\"",
        "details.expected",
        "details.received",
    ]
    success_terms = [
        "initialize",
        "list_tools",
        "status",
        "status source-health item contract",
        "offline verify",
        "offline audit",
        "offline support",
        "offline full-text support",
        "offline full-text-file support",
        "offline support-set full-text-file support",
        "offline full-text support-audit",
        "offline support-set counter-evidence leads",
        "offline support-audit citation set",
        "offline support-audit nested full-text-file support",
        "offline counter-evidence leads",
        "support-audit high-risk counter-evidence filtering",
        "source-outage safety counter-evidence leads",
        "Chinese source-outage safety leads",
        "support-mode aggregation details",
        "high-risk-only batch filtering",
        "tool metadata descriptions",
        "source-health next_action",
        "source-health retry delay provenance",
        "support-model status next_action",
        "structured errors",
        "batch shape error details",
        "full-text-file error details",
    ]
    docs_phrases = [
        "python scripts/smoke_mcp.py --require-sdk",
        "mcp_stdio_smoke",
        "MCP stdio smoke",
        "caller-provided full-text support evidence",
        "evidence_scope=full_text",
        "review_summary.triage_plan",
        "review_summary.suggested_fix_summary",
        "risk_reason",
        "suggested_fix.kind",
        "suggested_fix.requires_user_confirmation",
        "auto_apply_allowed=false",
        "retry_delay_seconds",
    ]
    tool_metadata_phrases = [
        "audit_citations_tool",
        "audit_claim_support_tool",
        "risk_ranking",
        "review_summary.triage_plan",
        "review_summary.suggested_fix_summary",
        "risk_reason",
        "suggested_fix.kind",
        "suggested_fix.requires_user_confirmation",
        "auto_apply_allowed=false",
        "full_text_file",
        "evidence_scope=full_text",
        "support_mode_details",
        "no_unstated_multi_hop_or_full_text_support",
        "will not fetch gated",
        "silently editing citations",
    ]

    errors = []
    for tool in required_tools:
        if script.count(f'"{tool}"') < 1:
            errors.append(f"scripts/smoke_mcp.py missing required tool coverage: {tool}")
    for label, phrase in required_script_phrases.items():
        if _normalize_markdown_text(phrase) not in normalized_script:
            errors.append(f"scripts/smoke_mcp.py missing required {label} coverage: {phrase}")
    for code in structured_error_codes:
        if code not in script:
            errors.append(f"scripts/smoke_mcp.py missing structured error code coverage: {code}")
    for phrase in shape_error_fields:
        if phrase not in script:
            errors.append(f"scripts/smoke_mcp.py missing batch shape error detail coverage: {phrase}")
    for term in success_terms:
        if term not in script:
            errors.append(f"scripts/smoke_mcp.py success message missing coverage term: {term}")
    for phrase in docs_phrases:
        if _normalize_markdown_text(phrase) not in normalized_docs:
            errors.append(f"MCP stdio release docs missing required phrase: {phrase}")
    for phrase in tool_metadata_phrases:
        if _normalize_markdown_text(phrase) not in normalized_mcp_server:
            errors.append(f"MCP tool metadata missing required phrase: {phrase}")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "script": "scripts/smoke_mcp.py",
        "docs_checked": ["README.md", "docs/mcp_setup.md", "docs/release_checklist.md"],
        "tool_metadata_checked": "citeguard/mcp/server.py",
        "required_tools": required_tools,
        "checked_behaviors": {
            "initialize": True,
            "list_tools": True,
            "tool_metadata_descriptions": True,
            "offline_fixture": True,
            "status_payload": True,
            "status_source_health_items": True,
            "status_source_health_retry_delay": True,
            "status_support_models": True,
            "fixture_verify": True,
            "audit_batch": True,
            "audit_high_risk_filter": True,
            "claim_support": True,
            "full_text_support": True,
            "full_text_file_support": True,
            "support_set_full_text_file": True,
            "support_audit_full_text": True,
            "claim_support_set": True,
            "claim_support_set_counterevidence": True,
            "support_audit_citation_set": True,
            "support_audit_nested_full_text_file": True,
            "support_mode_details": True,
            "support_audit_high_risk_filter": True,
            "support_audit_high_risk_counterevidence": True,
            "counterevidence": True,
            "source_outage_safety": True,
            "zh_source_outage_safety": True,
            "structured_errors": True,
            "batch_shape_errors": True,
            "full_text_file_errors": True,
            "missing_sdk_skip": True,
            "require_sdk_fail": True,
        },
        "structured_error_codes": structured_error_codes,
        "shape_error_fields": ["citations", "items", "citations"],
        "success_terms": success_terms,
        "policy": "MCP stdio smoke must cover initialize, list_tools, batch tool metadata descriptions, fixture-backed verification, full-text support, full-text-file support, support-set full-text-file support, nested support-audit full-text-file support, full-text support-audit, status, per-source health item contracts, support-model readiness, high-risk filtering, and structured errors",
    }


def _record_ci_mcp_smoke_contract_gate(summary: Dict[str, Any], *, project_root: Path) -> None:
    try:
        details = _check_ci_mcp_smoke_contract_gate(project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "ci_mcp_smoke_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "ci_mcp_smoke_contract",
            "status": "passed",
            **details,
        }
    )


def _check_ci_mcp_smoke_contract_gate(*, project_root: Path) -> Dict[str, Any]:
    workflow = _read_required_text(project_root / ".github" / "workflows" / "ci.yml")
    readme = _read_required_text(project_root / "README.md")
    checklist = _read_required_text(project_root / "docs" / "release_checklist.md")
    mcp_job = _extract_github_actions_job(workflow, "mcp-smoke")
    required_job_phrases = {
        "python_310": 'python-version: "3.10"',
        "mcp_extra_install": 'python -m pip install -e ".[mcp]"',
        "mcp_extra_gate": "python scripts/release_package_gate.py --skip-install-smoke --include-mcp-extra-smoke --require-mcp-extra-smoke",
        "mcp_stdio_gate": "python scripts/release_package_gate.py --skip-install-smoke --include-mcp-stdio-smoke --require-mcp-stdio-smoke",
        "stdio_smoke": "python scripts/smoke_mcp.py --require-sdk",
    }
    required_docs_phrases = [
        "python scripts/smoke_mcp.py --require-sdk",
        "Python 3.10+",
        "--require-mcp-stdio-smoke",
    ]

    errors = []
    if not mcp_job:
        errors.append(".github/workflows/ci.yml missing mcp-smoke job")
    for label, phrase in required_job_phrases.items():
        if phrase not in mcp_job:
            errors.append(f"mcp-smoke job missing {label}: {phrase}")
    normalized_docs = _normalize_markdown_text(f"{readme}\n{checklist}")
    for phrase in required_docs_phrases:
        if _normalize_markdown_text(phrase) not in normalized_docs:
            errors.append(f"MCP CI/release docs missing required phrase: {phrase}")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "workflow": ".github/workflows/ci.yml",
        "job": "mcp-smoke",
        "python_version": "3.10",
        "required_commands": list(required_job_phrases.values()),
        "docs_checked": ["README.md", "docs/release_checklist.md"],
        "policy": "CI must run Python 3.10+ MCP extra and stdio smoke gates with required SDK coverage",
    }


def _extract_github_actions_job(workflow: str, job_name: str) -> str:
    pattern = re.compile(
        rf"^  {re.escape(job_name)}:\n(?P<body>.*?)(?=^  [A-Za-z0-9_-]+:|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(workflow)
    return match.group(0) if match else ""


def _record_mcp_error_contract_gate(summary: Dict[str, Any]) -> None:
    try:
        details = _check_mcp_error_contract_gate()
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "mcp_error_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "mcp_error_contract",
            "status": "passed",
            **details,
        }
    )


def _check_mcp_error_contract_gate() -> Dict[str, Any]:
    from citeguard.mcp import server as mcp_server

    def call_with_env(call, env):
        previous = {key: os.environ.get(key) for key in env}
        try:
            os.environ.update(env)
            mcp_server._SOURCE = None
            mcp_server._SUPPORT_BACKEND = None
            return call()
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            mcp_server._SOURCE = None
            mcp_server._SUPPORT_BACKEND = None

    missing_full_text_path = str(Path(tempfile.gettempdir()) / f"citeguard-mcp-missing-full-text-{os.getpid()}.txt")
    Path(missing_full_text_path).unlink(missing_ok=True)

    cases = [
        {
            "name": "verify_missing_citation",
            "tool": "verify_citation_tool",
            "call": lambda: mcp_server.verify_citation_tool(),
            "expected_code": "missing_citation_input",
            "expected_details": {"tool": "verify_citation_tool"},
        },
        {
            "name": "audit_invalid_shape",
            "tool": "audit_citations_tool",
            "call": lambda: mcp_server.audit_citations_tool(citations="not a list"),
            "expected_code": "invalid_input",
            "expected_details": {
                "tool": "audit_citations_tool",
                "field": "citations",
                "expected": "list",
                "received": "str",
            },
        },
        {
            "name": "support_missing_claim",
            "tool": "check_claim_support_tool",
            "call": lambda: mcp_server.check_claim_support_tool(claim="", title="GhostCite"),
            "expected_code": "missing_claim",
            "expected_details": {"tool": "check_claim_support_tool"},
        },
        {
            "name": "support_full_text_file_missing",
            "tool": "check_claim_support_tool",
            "call": lambda: mcp_server.check_claim_support_tool(
                claim="A claim.",
                title="GhostCite",
                full_text_file=missing_full_text_path,
            ),
            "expected_code": "file_error",
            "expected_details": {
                "tool": "check_claim_support_tool",
                "field": "full_text_file",
                "filename": missing_full_text_path,
                "errno": errno.ENOENT,
            },
        },
        {
            "name": "support_set_empty_citations",
            "tool": "check_claim_support_set_tool",
            "call": lambda: mcp_server.check_claim_support_set_tool("A claim.", []),
            "expected_code": "missing_citation_input",
            "expected_details": {
                "tool": "check_claim_support_set_tool",
                "field": "citations",
                "expected": "non_empty_list",
            },
        },
        {
            "name": "counterevidence_missing_claim",
            "tool": "search_counterevidence_tool",
            "call": lambda: mcp_server.search_counterevidence_tool(claim=""),
            "expected_code": "missing_claim",
            "expected_details": {"tool": "search_counterevidence_tool"},
        },
        {
            "name": "counterevidence_invalid_top_k",
            "tool": "search_counterevidence_tool",
            "call": lambda: mcp_server.search_counterevidence_tool(claim="A claim.", top_k="many"),
            "expected_code": "invalid_input",
            "expected_details": {"tool": "search_counterevidence_tool", "field": "top_k"},
        },
        {
            "name": "support_audit_invalid_shape",
            "tool": "audit_claim_support_tool",
            "call": lambda: mcp_server.audit_claim_support_tool("not a list"),
            "expected_code": "invalid_input",
            "expected_details": {
                "tool": "audit_claim_support_tool",
                "field": "items",
                "expected": "list",
                "received": "str",
            },
        },
        {
            "name": "support_audit_nested_invalid_field",
            "tool": "audit_claim_support_tool",
            "call": lambda: mcp_server.audit_claim_support_tool(
                [{"claim": "A claim.", "citations": [{"title": "GhostCite"}, {"title": 42}]}]
            ),
            "expected_code": "invalid_input",
            "expected_details": {
                "tool": "audit_claim_support_tool",
                "index": 1,
                "citation_index": 2,
                "field": "title",
            },
        },
        {
            "name": "support_audit_nested_full_text_file_missing",
            "tool": "audit_claim_support_tool",
            "call": lambda: mcp_server.audit_claim_support_tool(
                [
                    {
                        "claim": "A claim.",
                        "citations": [
                            {"title": "GhostCite"},
                            {
                                "title": "Sparse Retrieval for Citation Auditing",
                                "full_text_file": missing_full_text_path,
                            },
                        ],
                    }
                ]
            ),
            "expected_code": "file_error",
            "expected_details": {
                "tool": "audit_claim_support_tool",
                "index": 1,
                "citation_index": 2,
                "field": "full_text_file",
                "filename": missing_full_text_path,
                "errno": errno.ENOENT,
            },
        },
        {
            "name": "verify_invalid_source_configuration",
            "tool": "verify_citation_tool",
            "call": lambda: call_with_env(
                lambda: mcp_server.verify_citation_tool(title="Release Error Contract"),
                {"CITEGUARD_SOURCES": "bad"},
            ),
            "expected_code": "invalid_input",
            "expected_details": {
                "tool": "verify_citation_tool",
                "field": "CITEGUARD_SOURCES",
                "source": "environment",
                "invalid_values": ["bad"],
                "valid_values": ["arxiv", "crossref", "openalex", "s2", "semantic-scholar", "semantic_scholar", "semanticscholar"],
            },
        },
    ]

    checked_cases = []
    for case in cases:
        payload = case["call"]()
        _validate_mcp_error_payload(
            case_name=case["name"],
            payload=payload,
            expected_code=case["expected_code"],
            expected_details=case["expected_details"],
        )
        error = payload["error"]
        checked_cases.append(
            {
                "name": case["name"],
                "tool": case["tool"],
                "expected_code": case["expected_code"],
                "actual_code": error["code"],
                "next_action": error["next_action"],
                "retryable": error["retryable"],
                "category": error["category"],
                "details_keys": sorted(error["details"]),
            }
        )

    return {
        "schema_version": ERROR_SCHEMA_VERSION,
        "cases": checked_cases,
        "tools": sorted({case["tool"] for case in cases}),
        "error_codes": sorted({case["expected_code"] for case in cases}),
        "policy": "MCP direct tool errors must use the shared ok=false schema with stable recovery and next_action fields",
    }


def _validate_mcp_error_payload(
    *,
    case_name: str,
    payload: Dict[str, Any],
    expected_code: str,
    expected_details: Dict[str, Any],
) -> None:
    errors = []
    if payload.get("ok") is not False:
        errors.append("ok must be false")
    if payload.get("schema_version") != ERROR_SCHEMA_VERSION:
        errors.append(f"schema_version must be {ERROR_SCHEMA_VERSION}")
    if payload.get("exit_code") != 2:
        errors.append("exit_code must be 2")
    error = payload.get("error")
    if not isinstance(error, dict):
        errors.append("error must be an object")
        error = {}
    details = error.get("details")
    if not isinstance(details, dict):
        errors.append("error.details must be an object")
        details = {}
    if error.get("code") != expected_code:
        errors.append(f"error.code must be {expected_code}")
    if not isinstance(error.get("message"), str) or not error.get("message"):
        errors.append("error.message must be nonempty")
    if error.get("recovery") != ERROR_CODE_RECOVERY.get(expected_code):
        errors.append("error.recovery must match public registry")
    if error.get("next_action") != ERROR_CODE_NEXT_ACTION.get(expected_code):
        errors.append("error.next_action must match public registry")
    if error.get("retryable") != ERROR_CODE_RETRYABLE.get(expected_code):
        errors.append("error.retryable must match public registry")
    if error.get("category") != ERROR_CODE_CATEGORY.get(expected_code):
        errors.append("error.category must match public registry")
    for key, expected_value in expected_details.items():
        if details.get(key) != expected_value:
            errors.append(f"details.{key} must be {expected_value!r}")
    if errors:
        raise RuntimeError(f"{case_name} MCP error contract failed: {'; '.join(errors)}")


def _record_cli_error_contract_gate(summary: Dict[str, Any], *, python: str, project_root: Path) -> None:
    try:
        details = _check_cli_error_contract_gate(python=python, project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "cli_error_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "cli_error_contract",
            "status": "passed",
            **details,
        }
    )


def _check_cli_error_contract_gate(*, python: str, project_root: Path) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="citeguard-cli-errors-") as tmpdir:
        tmp = Path(tmpdir)
        missing_audit_path = tmp / "missing-citations.json"
        invalid_support_jsonl = tmp / "invalid-support.jsonl"
        malformed_docx = tmp / "malformed.docx"
        invalid_support_jsonl.write_text('{"claim": ', encoding="utf-8")
        malformed_docx.write_bytes(b"not a zip")

        cases = [
            {
                "name": "verify_missing_citation",
                "command": [python, "-m", "citeguard", "verify"],
                "expected_code": "missing_citation_input",
                "expected_next_action": "provide_missing_input",
                "expected_details": {"command": "verify"},
            },
            {
                "name": "audit_missing_file",
                "command": [python, "-m", "citeguard", "audit", str(missing_audit_path)],
                "expected_code": "file_error",
                "expected_next_action": "repair_input",
                "expected_details": {
                    "command": "audit",
                    "field": "path",
                    "filename": str(missing_audit_path),
                },
                "required_detail_keys": ["errno"],
            },
            {
                "name": "extract_malformed_docx",
                "command": [python, "-m", "citeguard", "extract", str(malformed_docx)],
                "expected_code": "file_error",
                "expected_next_action": "repair_input",
                "expected_details": {
                    "command": "extract",
                    "field": "path",
                    "filename": str(malformed_docx),
                },
            },
            {
                "name": "audit_malformed_docx",
                "command": [python, "-m", "citeguard", "audit", str(malformed_docx)],
                "expected_code": "file_error",
                "expected_next_action": "repair_input",
                "expected_details": {
                    "command": "audit",
                    "field": "path",
                    "filename": str(malformed_docx),
                },
            },
            {
                "name": "support_audit_malformed_docx",
                "command": [
                    python,
                    "-m",
                    "citeguard",
                    "support-audit",
                    str(malformed_docx),
                    "--claim",
                    "Release Error Contract",
                ],
                "expected_code": "file_error",
                "expected_next_action": "repair_input",
                "expected_details": {
                    "command": "support-audit",
                    "field": "path",
                    "filename": str(malformed_docx),
                },
            },
            {
                "name": "support_audit_invalid_jsonl",
                "command": [python, "-m", "citeguard", "support-audit", str(invalid_support_jsonl)],
                "expected_code": "invalid_json",
                "expected_next_action": "repair_input",
                "expected_details": {
                    "command": "support-audit",
                    "line": 1,
                    "column": 11,
                },
            },
            {
                "name": "support_missing_required_claim_arg",
                "command": [python, "-m", "citeguard", "support", "--title", "Release Error Contract"],
                "expected_code": "argument_parse_error",
                "expected_next_action": "repair_input",
                "expected_details": {
                    "prog": "citeguard support",
                    "command": "support",
                    "arguments": ["--claim"],
                },
            },
            {
                "name": "verify_invalid_source_configuration",
                "command": [python, "-m", "citeguard", "verify", "--title", "Release Error Contract"],
                "env": {"CITEGUARD_SOURCES": "bad"},
                "expected_code": "invalid_input",
                "expected_next_action": "repair_input",
                "expected_details": {
                    "command": "verify",
                    "field": "CITEGUARD_SOURCES",
                    "source": "environment",
                    "invalid_values": ["bad"],
                },
                "required_detail_keys": ["valid_values"],
            },
        ]

        checked_cases = [
            _run_expected_cli_error(case, cwd=project_root)
            for case in cases
        ]

    return {
        "schema_version": ERROR_SCHEMA_VERSION,
        "cases": checked_cases,
    }


def _run_expected_cli_error(case: Dict[str, Any], *, cwd: Path) -> Dict[str, Any]:
    command = case["command"]
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, **case.get("env", {})},
    )
    if completed.returncode == 0:
        raise RuntimeError(f"{case['name']} unexpectedly succeeded")
    if completed.stdout.strip():
        raise RuntimeError(f"{case['name']} wrote unexpected stdout: {completed.stdout.strip()}")

    try:
        payload = json.loads(completed.stderr)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{case['name']} did not write JSON error payload to stderr: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{case['name']} wrote a non-object JSON error payload")

    _validate_cli_error_payload(
        case_name=case["name"],
        payload=payload,
        returncode=completed.returncode,
        expected_code=case["expected_code"],
        expected_next_action=case["expected_next_action"],
        expected_details=case.get("expected_details", {}),
        required_detail_keys=case.get("required_detail_keys", []),
    )
    error = payload["error"]
    details = error["details"]
    return {
        "name": case["name"],
        "command": command,
        "exit_code": completed.returncode,
        "expected_code": case["expected_code"],
        "actual_code": error["code"],
        "next_action": error["next_action"],
        "retryable": error["retryable"],
        "category": error["category"],
        "details_keys": sorted(details),
    }


def _validate_cli_error_payload(
    *,
    case_name: str,
    payload: Dict[str, Any],
    returncode: int,
    expected_code: str,
    expected_next_action: str,
    expected_details: Dict[str, Any],
    required_detail_keys: List[str],
) -> None:
    errors = []
    if payload.get("ok") is not False:
        errors.append("ok must be false")
    if payload.get("schema_version") != ERROR_SCHEMA_VERSION:
        errors.append(f"schema_version must be {ERROR_SCHEMA_VERSION}")
    if payload.get("exit_code") != returncode:
        errors.append("exit_code must match process return code")
    error = payload.get("error")
    if not isinstance(error, dict):
        errors.append("error must be an object")
        error = {}
    details = error.get("details")
    if not isinstance(details, dict):
        errors.append("error.details must be an object")
        details = {}
    if error.get("code") != expected_code:
        errors.append(f"error.code must be {expected_code}")
    if not isinstance(error.get("message"), str) or not error.get("message"):
        errors.append("error.message must be nonempty")
    if error.get("recovery") != ERROR_CODE_RECOVERY.get(expected_code):
        errors.append("error.recovery must match public registry")
    if error.get("next_action") != expected_next_action:
        errors.append(f"error.next_action must be {expected_next_action}")
    if error.get("next_action") != ERROR_CODE_NEXT_ACTION.get(expected_code):
        errors.append("error.next_action must match public registry")
    if error.get("retryable") != ERROR_CODE_RETRYABLE.get(expected_code):
        errors.append("error.retryable must match public registry")
    if error.get("category") != ERROR_CODE_CATEGORY.get(expected_code):
        errors.append("error.category must match public registry")
    for key, expected_value in expected_details.items():
        if details.get(key) != expected_value:
            errors.append(f"details.{key} must be {expected_value!r}")
    for key in required_detail_keys:
        if key not in details:
            errors.append(f"details.{key} is required")
    if errors:
        raise RuntimeError(f"{case_name} CLI error contract failed: {'; '.join(errors)}")


def _record_source_outage_safety_gate(summary: Dict[str, Any], *, project_root: Path) -> None:
    try:
        details = _check_source_outage_safety_gate(project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "source_outage_safety",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "source_outage_safety",
            "status": "passed",
            **details,
        }
    )


def _check_source_outage_safety_gate(*, project_root: Path) -> Dict[str, Any]:
    from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
    from citeguard.retrieval.scholarly_clients.multi_source import MultiSourceMetadataSource
    from citeguard.runtime import SOURCE_HEALTH_SCHEMA_VERSION, source_health_status
    from citeguard.verification import CitationRecord, parse_citation, verify_citation

    del project_root

    candidate = parse_citation(title="Release Gate Source Outage Safety Probe")
    failed_source = _ReleaseGateTimeoutSource("release_timeout_source")
    all_failed = MultiSourceMetadataSource([failed_source])
    outage_result = verify_citation(candidate, all_failed).to_dict()
    rate_limited_result = verify_citation(
        parse_citation(title="Release Gate Rate Limited Source Probe"),
        _ReleaseGateDiagnosticSource(
            "release_rate_limited_source",
            code="source_unavailable",
            kind="rate_limited",
            status_code=429,
            url="https://api.example.test/search",
            error="HTTP Error 429: Too Many Requests",
            attempt_count=2,
            retry_count=1,
            retry_after_seconds=2.0,
        ),
    ).to_dict()

    healthy_record = CitationRecord(
        citation_id="source-health-1",
        title="Release Gate Source Health Control",
        authors=["CiteGuard Maintainer"],
        year=2026,
        venue="Release Gate",
        source="release_fixture",
    )

    def source_factory(names: List[str], **_: Any) -> object:
        name = names[0]
        if name == "openalex":
            return _ReleaseGateTimeoutSource("openalex")
        if name == "crossref":
            return InMemoryMetadataSource([healthy_record])
        raise RuntimeError(f"unexpected source: {name}")

    health = source_health_status(
        env={
            "CITEGUARD_SOURCES": "openalex,crossref",
            "CITEGUARD_MAILTO": "release-gate@example.com",
            "CITEGUARD_HTTP_TIMEOUT": "1",
            "CITEGUARD_HTTP_RETRIES": "0",
        },
        check_live=True,
        health_query="Release Gate Source Health Control",
        source_factory=source_factory,
    )
    health_summary = health.get("summary", {})

    errors = []
    if outage_result.get("verdict") != "not_found":
        errors.append("all-source outage verification should remain not_found")
    if outage_result.get("confidence", 1.0) > 0.35:
        errors.append("all-source outage not_found confidence should be capped at 0.35")
    if outage_result.get("source_failure_mode") != "all_sources_failed":
        errors.append("all-source outage should set source_failure_mode=all_sources_failed")
    if outage_result.get("sources_failed") != ["release_timeout_source"]:
        errors.append("all-source outage should identify the failed source")
    if outage_result.get("sources_available") != []:
        errors.append("all-source outage should not report available sources")
    if outage_result.get("outage_limited") is not True:
        errors.append("all-source outage should set outage_limited=true")
    if outage_result.get("next_action") != "retry_or_check_source_health":
        errors.append("all-source outage should route agents to retry_or_check_source_health")
    if outage_result.get("recovery_code") != "timeout":
        errors.append("all-source outage recovery_code should preserve timeout")
    if "not evidence of fabrication" not in outage_result.get("explanation", ""):
        errors.append("all-source outage explanation should avoid fabrication overclaiming")
    if not outage_result.get("source_failure_details"):
        errors.append("all-source outage should expose source_failure_details")
    elif outage_result["source_failure_details"][0].get("code") != "timeout":
        errors.append("all-source outage source_failure_details should preserve timeout code")
    rate_limited_details = rate_limited_result.get("source_failure_details") or [{}]
    if rate_limited_details[0].get("kind") != "rate_limited":
        errors.append("direct HTTP source failure should preserve rate_limited kind")
    if rate_limited_details[0].get("retry_after_seconds") != 2.0:
        errors.append("direct HTTP source failure should preserve Retry-After seconds")
    if rate_limited_result.get("next_action") != "retry_or_check_source_health":
        errors.append("direct HTTP rate-limit failure should route agents to retry_or_check_source_health")

    if health.get("schema_version") != SOURCE_HEALTH_SCHEMA_VERSION:
        errors.append("source health schema_version mismatch")
    if health.get("mode") != "live" or health.get("live_check_performed") is not True:
        errors.append("source health gate should exercise live-check summary mode with fake sources")
    if health_summary.get("sources_checked") != ["openalex", "crossref"]:
        errors.append("source health should report checked sources separately")
    if health_summary.get("sources_failed") != ["openalex"]:
        errors.append("source health should report failed sources separately")
    if health_summary.get("sources_responded") != ["crossref"]:
        errors.append("source health should report responded sources separately")
    if health_summary.get("sources_available") != ["crossref"]:
        errors.append("source health should preserve available source names")
    if health_summary.get("failure_kind_counts") != {"timeout": 1}:
        errors.append("source health should summarize timeout failure kind")
    if health_summary.get("failure_kind_sources") != {"timeout": ["openalex"]}:
        errors.append("source health should map timeout kind to source")
    if health_summary.get("next_action") != "retry_or_check_source_health":
        errors.append("source health should route agents to retry_or_check_source_health")
    if health_summary.get("all_checked_sources_failed") is not False:
        errors.append("partial source outage should not set all_checked_sources_failed")
    if health_summary.get("confidence_effect") != "partial_source_limited":
        errors.append("partial source outage should report confidence_effect=partial_source_limited")
    if health_summary.get("interpretation") != "source_outage_lowers_confidence_not_fabrication_evidence":
        errors.append("source health should state outage lowers confidence without proving fabrication")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "verification": {
            "verdict": outage_result.get("verdict"),
            "confidence": outage_result.get("confidence"),
            "source_failure_mode": outage_result.get("source_failure_mode"),
            "outage_limited": outage_result.get("outage_limited"),
            "sources_failed": outage_result.get("sources_failed"),
            "sources_available": outage_result.get("sources_available"),
            "recovery_code": outage_result.get("recovery_code"),
            "next_action": outage_result.get("next_action"),
        },
        "rate_limited_verification": {
            "verdict": rate_limited_result.get("verdict"),
            "source_failure_mode": rate_limited_result.get("source_failure_mode"),
            "sources_failed": rate_limited_result.get("sources_failed"),
            "retry_after_seconds": rate_limited_details[0].get("retry_after_seconds"),
            "next_action": rate_limited_result.get("next_action"),
        },
        "source_health": {
            "schema_version": health.get("schema_version"),
            "sources_checked": health_summary.get("sources_checked"),
            "sources_responded": health_summary.get("sources_responded"),
            "sources_failed": health_summary.get("sources_failed"),
            "failure_kind_counts": health_summary.get("failure_kind_counts"),
            "failure_kind_sources": health_summary.get("failure_kind_sources"),
            "next_action": health_summary.get("next_action"),
            "all_checked_sources_failed": health_summary.get("all_checked_sources_failed"),
            "confidence_effect": health_summary.get("confidence_effect"),
            "interpretation": health_summary.get("interpretation"),
        },
    }


def _record_counterevidence_safety_contract_gate(summary: Dict[str, Any], *, project_root: Path) -> None:
    try:
        details = _check_counterevidence_safety_contract_gate(project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "counterevidence_safety_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "counterevidence_safety_contract",
            "status": "passed",
            **details,
        }
    )


def _check_counterevidence_safety_contract_gate(*, project_root: Path) -> Dict[str, Any]:
    from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
    from citeguard.verification import CitationRecord, search_counterevidence_candidates
    from citeguard.verification.models import STABLE_NEXT_ACTIONS

    readme = _read_required_text(project_root / "README.md")
    cli_reference = _read_required_text(project_root / "docs" / "cli_reference.md")
    mcp_setup = _read_required_text(project_root / "docs" / "mcp_setup.md")
    skill = _read_required_text(project_root / "skills" / "citeguard-verify" / "SKILL.md")
    examples = _read_required_text(project_root / "skills" / "citeguard-verify" / "references" / "examples.md")

    docs_requirements = {
        "README.md": {
            "tool_name": "search_counterevidence_tool",
            "not_yet_done": "counter-evidence verdicting",
        },
        "docs/agent_output_contract.md": {
            "leads_only": "leads to inspect, not contradiction verdicts",
            "review_summary": "review_summary",
            "recommended_next_steps": "recommended_next_steps",
            "next_action": "review_counterevidence_leads",
        },
        "docs/cli_reference.md": {
            "leads_only": "Candidates are review leads only",
            "not_proof": "they are not proof of contradiction",
            "empty_not_proof": "empty result is not proof that no counter-evidence exists",
            "review_summary": "review_summary",
            "explicit_queue": "explicit_contradiction_candidate_indexes",
            "source_outage_queue": "source_outage_safety_candidate_indexes",
            "next_action": "next_action=review_counterevidence_leads",
        },
        "docs/mcp_setup.md": {
            "not_prove_contradicted": "It does not prove a claim is contradicted",
            "empty_not_proof": "empty candidate list does not prove that no counter-evidence exists",
            "review_summary": "review_summary",
            "related_queue": "related_candidate_indexes",
            "next_action": "next_action=review_counterevidence_leads",
        },
        "skills/citeguard-verify/SKILL.md": {
            "leads_only": "Treat returned candidates as leads only",
            "not_proof": "not as proof of contradiction",
            "separate_verdict": "show candidates separately from the support verdict",
            "review_summary": "review_summary",
            "recommended_first_queue": "review_summary.recommended_next_steps.first_queue",
            "next_action": "next_action=review_counterevidence_leads",
        },
        "skills/citeguard-verify/references/examples.md": {
            "tool_example": '"tool": "search_counterevidence_tool"',
            "review_leads": "review_counterevidence_leads",
        },
    }
    docs = {
        "README.md": readme,
        "docs/agent_output_contract.md": _read_required_text(project_root / "docs" / "agent_output_contract.md"),
        "docs/cli_reference.md": cli_reference,
        "docs/mcp_setup.md": mcp_setup,
        "skills/citeguard-verify/SKILL.md": skill,
        "skills/citeguard-verify/references/examples.md": examples,
    }
    errors: List[str] = []
    for label, requirements in docs_requirements.items():
        normalized_doc = _normalize_markdown_text(docs[label])
        for name, phrase in requirements.items():
            if _normalize_markdown_text(phrase) not in normalized_doc:
                errors.append(f"{label} missing {name}: {phrase}")
    if "review_counterevidence_leads" not in STABLE_NEXT_ACTIONS:
        errors.append("STABLE_NEXT_ACTIONS missing review_counterevidence_leads")

    source = InMemoryMetadataSource(
        [
            CitationRecord(
                citation_id="counterevidence-safety-1",
                title="Method M does not improve task T",
                abstract="A controlled replication found that Method M does not improve task T.",
                authors=["CiteGuard Maintainer"],
                year=2026,
                venue="Release Gate",
                source="release_fixture",
            )
        ]
    )
    report = search_counterevidence_candidates("Method M improves task T.", source, top_k=1).to_dict()
    interpretation = str(report.get("interpretation", ""))
    if report.get("candidate_count") != 1:
        errors.append("counterevidence release probe should return one candidate lead")
    if report.get("next_action") != "review_counterevidence_leads":
        errors.append("counterevidence candidate lead should route to review_counterevidence_leads")
    if "review leads, not a contradiction verdict" not in interpretation:
        errors.append("counterevidence interpretation should preserve leads-only wording")
    if "verdict" in report:
        errors.append("counterevidence report should not expose a verdict field")
    review_summary = report.get("review_summary", {})
    if not isinstance(review_summary, dict):
        errors.append("counterevidence report should expose review_summary")
    else:
        if review_summary.get("policy") != "review_leads_not_contradiction_verdicts":
            errors.append("counterevidence review_summary should preserve leads-only policy")
        if review_summary.get("signal_counts", {}).get("explicit_contradiction_cue") != 1:
            errors.append("counterevidence review_summary should count explicit_contradiction_cue")
        if review_summary.get("top_candidate", {}).get("signal") != "explicit_contradiction_cue":
            errors.append("counterevidence review_summary should summarize top candidate signal")
        recommended_next_steps = review_summary.get("recommended_next_steps", {})
        if not isinstance(recommended_next_steps, dict):
            errors.append("counterevidence review_summary should expose recommended_next_steps")
        else:
            if recommended_next_steps.get("first_queue") != "explicit_contradiction_candidate_indexes":
                errors.append("counterevidence review queue should prioritize explicit contradiction cues")
            if recommended_next_steps.get("explicit_contradiction_candidate_indexes") != [0]:
                errors.append("counterevidence review queue should expose explicit contradiction candidate indexes")
            if recommended_next_steps.get("policy") != (
                "prioritize_explicit_contradiction_cues_but_treat_all_candidates_as_review_leads"
            ):
                errors.append("counterevidence recommended_next_steps should preserve leads-only queue policy")
    candidates = report.get("candidates", [])
    first_candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    if first_candidate.get("signal") != "explicit_contradiction_cue":
        errors.append("counterevidence release probe should expose an explicit_contradiction_cue signal")
    if "improvement_negation" not in first_candidate.get("matched_query_roles", []):
        errors.append("counterevidence release probe should expose the improvement_negation query role")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "docs_checked": sorted(docs),
        "next_action": report.get("next_action"),
        "candidate_count": report.get("candidate_count"),
        "candidate_signal": first_candidate.get("signal"),
        "candidate_query_roles": first_candidate.get("matched_query_roles", []),
        "review_summary": review_summary,
        "interpretation": interpretation,
        "policy": "counter-evidence search returns review leads only, not contradiction verdicts",
    }


def _record_full_text_evidence_boundary_contract_gate(summary: Dict[str, Any], *, project_root: Path) -> None:
    try:
        details = _check_full_text_evidence_boundary_contract_gate(project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "full_text_evidence_boundary_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "full_text_evidence_boundary_contract",
            "status": "passed",
            **details,
        }
    )


def _check_full_text_evidence_boundary_contract_gate(*, project_root: Path) -> Dict[str, Any]:
    from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
    from citeguard.verification import CitationRecord, check_claim_support

    readme = _read_required_text(project_root / "README.md")
    cli_reference = _read_required_text(project_root / "docs" / "cli_reference.md")
    mcp_setup = _read_required_text(project_root / "docs" / "mcp_setup.md")
    security = _read_required_text(project_root / "docs" / "security_compliance.md")
    skill = _read_required_text(project_root / "skills" / "citeguard-verify" / "SKILL.md")
    examples = _read_required_text(project_root / "skills" / "citeguard-verify" / "references" / "examples.md")

    docs_requirements = {
        "README.md": {
            "no_scraping": "does not scrape gated sources",
            "no_remote_full_text": "download remote full text",
            "no_paywall": "bypass paywalls",
            "abstract_boundary": "abstract-level unless you provide full-text evidence",
        },
        "docs/agent_output_contract.md": {
            "lawful_inputs": "lawful excerpts via CLI/MCP/JSON inputs or local text/PDF",
        },
        "docs/cli_reference.md": {
            "local_file": "`--full-text-file`",
            "full_text_file_contract": "`full_text_file`",
            "error_contract": "details.field=full_text_file",
        },
        "docs/mcp_setup.md": {
            "full_text_inputs": "`full_text`",
            "full_text_file_inputs": "`full_text_file`",
            "no_upgrade": "Do not claim full-text support from an abstract-level support result",
        },
        "docs/security_compliance.md": {
            "no_gated_scrape": "does not scrape CNKI, Wanfang, or other gated scholarly platforms",
            "no_paywall_bypass": "must not bypass paywalls",
            "local_readers": "local user-provided text/PDF readers, not crawlers",
        },
        "skills/citeguard-verify/SKILL.md": {
            "lawful_local": "local lawful text/PDF file",
            "no_gated_download": "Never ask CiteGuard to download gated full text",
            "no_full_text_upgrade": "Do not claim full-text support from an abstract-level support result",
        },
        "skills/citeguard-verify/references/examples.md": {
            "full_text_payload": '"full_text": [',
            "full_text_scope": "evidence_scope=full_text",
            "full_text_source_field": "evidence.source_field=user_full_text_excerpt_1",
            "lawful_excerpt_only": "caller-provided lawful excerpts",
            "no_paywall_bypass": "Do not fetch gated full text, bypass paywalls",
            "boundary_packet": "support-label-packet-full-text-required-unreviewed",
            "safe_wording": "full-text boundary review is complete",
        },
    }
    docs = {
        "README.md": readme,
        "docs/agent_output_contract.md": _read_required_text(project_root / "docs" / "agent_output_contract.md"),
        "docs/cli_reference.md": cli_reference,
        "docs/mcp_setup.md": mcp_setup,
        "docs/security_compliance.md": security,
        "skills/citeguard-verify/SKILL.md": skill,
        "skills/citeguard-verify/references/examples.md": examples,
    }
    errors: List[str] = []
    for label, requirements in docs_requirements.items():
        normalized_doc = _normalize_markdown_text(docs[label])
        for name, phrase in requirements.items():
            if _normalize_markdown_text(phrase) not in normalized_doc:
                errors.append(f"{label} missing {name}: {phrase}")

    claim = "Sparse retrieval improves citation audit recall."
    full_text_record = CitationRecord(
        citation_id="full-text-boundary-local",
        title="Sparse retrieval study",
        abstract="This paper introduces a benchmark for citation audit systems.",
        authors=["CiteGuard Maintainer"],
        year=2026,
        venue="Release Gate",
        doi="10.0000/citeguard-full-text-boundary",
        metadata={
            "evidence_chunks": [
                {
                    "text": "Sparse retrieval improves citation audit recall in controlled benchmarks.",
                    "source_field": "user_full_text_excerpt_1",
                    "source_url": "",
                    "evidence_scope": "full_text",
                }
            ]
        },
    )
    abstract_record = CitationRecord(
        citation_id="full-text-boundary-abstract",
        title="Sparse retrieval improves citation audit recall",
        abstract="Sparse retrieval improves citation audit recall in controlled benchmarks.",
        authors=["CiteGuard Maintainer"],
        year=2026,
        venue="Release Gate",
        doi="10.0000/citeguard-abstract-boundary",
    )
    full_text_report = check_claim_support(
        claim,
        full_text_record,
        InMemoryMetadataSource([full_text_record]),
    ).to_dict()
    abstract_report = check_claim_support(
        claim,
        abstract_record,
        InMemoryMetadataSource([abstract_record]),
    ).to_dict()
    if full_text_report.get("evidence_scope") != "full_text":
        errors.append("local lawful full-text evidence should be labelled evidence_scope=full_text")
    full_text_evidence = full_text_report.get("evidence", {})
    if not isinstance(full_text_evidence, dict) or full_text_evidence.get("source_field") != "user_full_text_excerpt_1":
        errors.append("local lawful full-text evidence should preserve the user_full_text source_field")
    if abstract_report.get("evidence_scope") == "full_text":
        errors.append("abstract-only support should not be upgraded to evidence_scope=full_text")
    if abstract_report.get("evidence_scope") not in {"abstract", "title", "none"}:
        errors.append("abstract-only release probe should stay in a non-full-text evidence scope")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "docs_checked": sorted(docs),
        "full_text_probe": {
            "verdict": full_text_report.get("verdict"),
            "evidence_scope": full_text_report.get("evidence_scope"),
            "source_field": full_text_evidence.get("source_field") if isinstance(full_text_evidence, dict) else "",
            "next_action": full_text_report.get("next_action"),
        },
        "abstract_probe": {
            "verdict": abstract_report.get("verdict"),
            "evidence_scope": abstract_report.get("evidence_scope"),
            "next_action": abstract_report.get("next_action"),
        },
        "policy": "full-text evidence is opt-in, local/user-provided, and must not be inferred from abstract-only support",
    }


def _record_support_set_aggregation_contract_gate(summary: Dict[str, Any], *, project_root: Path) -> None:
    try:
        details = _check_support_set_aggregation_contract_gate(project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "support_set_aggregation_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "support_set_aggregation_contract",
            "status": "passed",
            **details,
        }
    )


def _check_support_set_aggregation_contract_gate(*, project_root: Path) -> Dict[str, Any]:
    from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
    from citeguard.verification import CitationRecord, check_claim_support_set, parse_citation
    from citeguard.verifiers import SupportAssessment, SupportBackend

    class WeakOnlyReleaseGateBackend(SupportBackend):
        backend_name = "release_gate_weak_support"

        def assess(self, claim_text: str, evidence_text: str) -> SupportAssessment:
            return SupportAssessment(
                backend_name=self.backend_name,
                score=0.50,
                passed=True,
                rationale="Release-gate fixture marks evidence as related but not entailing.",
            )

    readme = _read_required_text(project_root / "README.md")
    cli_reference = _read_required_text(project_root / "docs" / "cli_reference.md")
    mcp_setup = _read_required_text(project_root / "docs" / "mcp_setup.md")
    skill = _read_required_text(project_root / "skills" / "citeguard-verify" / "SKILL.md")
    examples = _read_required_text(project_root / "skills" / "citeguard-verify" / "references" / "examples.md")

    docs_requirements = {
        "docs/agent_output_contract.md": {
            "support_mode": "Support-set reports include `support_mode`",
            "support_mode_details": "`support_mode_details`",
            "support_mode_policy": "no_unstated_multi_hop_or_full_text_support",
            "evidence_provenance": "`evidence_scopes`, `evidence_source_names`, and `evidence_source_fields`",
        },
        "docs/support_eval.md": {
            "weak_boundary": "multiple weak citations remaining",
        },
        "docs/cli_reference.md": {
            "support_mode_values": "`multiple_weak_support`",
            "support_mode_details": "`support_mode_details`",
            "support_mode_indexes": "`weakly_supported_indexes`",
            "support_mode_policy": "no_unstated_multi_hop_or_full_text_support",
            "evidence_provenance": "`evidence_scopes`, `evidence_source_names`, and `evidence_source_fields`",
            "tentative": "tentative corroboration, not as a strong-support upgrade",
        },
        "docs/mcp_setup.md": {
            "citation_set": "`input_mode=citation_set`",
            "support_mode": "`support_mode`",
            "support_mode_details": "`support_mode_details`",
            "support_mode_policy": "no_unstated_multi_hop_or_full_text_support",
        },
        "skills/citeguard-verify/SKILL.md": {
            "mention_support_mode": "mention `support_mode` when it is not",
            "support_mode_details_decision": "`support_mode_details.decision`",
            "support_mode_details_policy": "`support_mode_details.policy`",
            "support_mode_details_indexes": "`support_mode_details.weakly_supported_indexes`",
            "weak_tentative": "multiple_weak_support` means several",
            "evidence_provenance": "`evidence_scopes`, `evidence_source_names`, and",
            "not_full_support": "it is still tentative, not full support",
        },
        "skills/citeguard-verify/references/examples.md": {
            "support_set_tool": '"tool": "check_claim_support_set_tool"',
            "policy_boundary": "policy-boundary review before claiming multi-citation support readiness",
            "support_mode_details": '"support_mode_details"',
            "support_mode_decision": "multiple_weak_citations_remain_tentative",
            "support_mode_policy": "no_unstated_multi_hop_or_full_text_support",
        },
    }
    docs = {
        "README.md": readme,
        "docs/agent_output_contract.md": _read_required_text(project_root / "docs" / "agent_output_contract.md"),
        "docs/support_eval.md": _read_required_text(project_root / "docs" / "support_eval.md"),
        "docs/cli_reference.md": cli_reference,
        "docs/mcp_setup.md": mcp_setup,
        "skills/citeguard-verify/SKILL.md": skill,
        "skills/citeguard-verify/references/examples.md": examples,
    }
    errors: List[str] = []
    for label, requirements in docs_requirements.items():
        normalized_doc = _normalize_markdown_text(docs[label])
        for name, phrase in requirements.items():
            if _normalize_markdown_text(phrase) not in normalized_doc:
                errors.append(f"{label} missing {name}: {phrase}")

    source = InMemoryMetadataSource(
        [
            CitationRecord(
                citation_id="weak-set-1",
                title="Method M for Task T",
                abstract="Method M and task T are evaluated.",
                authors=["CiteGuard Maintainer"],
                year=2024,
                venue="Release Gate",
                source="release_fixture",
            ),
            CitationRecord(
                citation_id="weak-set-2",
                title="Task T Evaluation with Method M",
                abstract="Task T evaluation includes method M.",
                authors=["CiteGuard Maintainer"],
                year=2025,
                venue="Release Gate",
                source="release_fixture",
            ),
        ]
    )
    report = check_claim_support_set(
        "Method M improves task T.",
        [
            parse_citation(title="Method M for Task T", year=2024),
            parse_citation(title="Task T Evaluation with Method M", year=2025),
        ],
        source,
        backend=WeakOnlyReleaseGateBackend(),
    ).to_dict()
    if report.get("verdict") != "weakly_supported":
        errors.append("multiple weak support-set probe should remain weakly_supported")
    if report.get("support_mode") != "multiple_weak_support":
        errors.append("multiple weak support-set probe should expose support_mode=multiple_weak_support")
    if report.get("next_action") != "tighten_claim_or_inspect_full_text":
        errors.append("multiple weak support-set probe should route to tighten_claim_or_inspect_full_text")
    if report.get("risk") != "medium":
        errors.append("multiple weak support-set probe should remain medium risk")
    if report.get("counterevidence_review") is not True:
        errors.append("multiple weak support-set probe should request counterevidence review")
    if report.get("evidence_scope") != "abstract":
        errors.append("multiple weak support-set probe should not infer full-text evidence")
    if report.get("evidence_scopes") != ["abstract"]:
        errors.append("multiple weak support-set probe should expose aggregate evidence_scopes")
    if report.get("evidence_source_names") != ["release_fixture"]:
        errors.append("multiple weak support-set probe should expose aggregate evidence_source_names")
    if report.get("evidence_source_fields") != ["abstract_sentence_1"]:
        errors.append("multiple weak support-set probe should expose aggregate evidence_source_fields")
    if report.get("supporting_citation_count") != 2:
        errors.append("multiple weak support-set probe should preserve supporting_citation_count=2")
    if report.get("contradicting_citation_count") != 0:
        errors.append("multiple weak support-set probe should preserve contradicting_citation_count=0")
    support_mode_details = report.get("support_mode_details", {})
    if not isinstance(support_mode_details, dict):
        support_mode_details = {}
        errors.append("multiple weak support-set probe should expose support_mode_details")
    if support_mode_details.get("schema_version") != 1:
        errors.append("multiple weak support-set probe should expose support_mode_details.schema_version=1")
    if support_mode_details.get("decision") != "multiple_weak_citations_remain_tentative":
        errors.append("multiple weak support-set probe should expose tentative support_mode_details.decision")
    if "no_unstated_multi_hop_or_full_text_support" not in str(support_mode_details.get("policy", "")):
        errors.append("multiple weak support-set probe should expose conservative support_mode_details.policy")
    if support_mode_details.get("weakly_supported_indexes") != [0, 1]:
        errors.append("multiple weak support-set probe should expose weakly_supported_indexes=[0, 1]")
    if support_mode_details.get("supported_indexes") != []:
        errors.append("multiple weak support-set probe should expose empty supported_indexes")
    if support_mode_details.get("contradicted_indexes") != []:
        errors.append("multiple weak support-set probe should expose empty contradicted_indexes")
    if support_mode_details.get("full_text_evidence_present") is not False:
        errors.append("multiple weak support-set probe should expose full_text_evidence_present=false")
    evidence = report.get("evidence", [])
    evidence_indexes = [item.get("index") for item in evidence if isinstance(item, dict)]
    if evidence_indexes != [0, 1]:
        errors.append("multiple weak support-set probe should preserve per-citation evidence indexes")
    if report.get("summary", {}).get("supported") != 0:
        errors.append("multiple weak support-set probe must not upgrade weak citations to supported")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "docs_checked": sorted(docs),
        "verdict": report.get("verdict"),
        "support_mode": report.get("support_mode"),
        "next_action": report.get("next_action"),
        "risk": report.get("risk"),
        "evidence_scope": report.get("evidence_scope"),
        "evidence_scopes": report.get("evidence_scopes", []),
        "evidence_source_names": report.get("evidence_source_names", []),
        "evidence_source_fields": report.get("evidence_source_fields", []),
        "evidence_indexes": evidence_indexes,
        "supporting_citation_count": report.get("supporting_citation_count"),
        "contradicting_citation_count": report.get("contradicting_citation_count"),
        "support_mode_details": {
            "decision": support_mode_details.get("decision"),
            "policy": support_mode_details.get("policy"),
            "weakly_supported_indexes": support_mode_details.get("weakly_supported_indexes"),
            "supported_indexes": support_mode_details.get("supported_indexes"),
            "contradicted_indexes": support_mode_details.get("contradicted_indexes"),
            "full_text_evidence_present": support_mode_details.get("full_text_evidence_present"),
        },
        "policy": "multiple weak citation-set evidence remains tentative and must not be upgraded to supported",
    }


def _record_live_source_health_contract_gate(summary: Dict[str, Any], *, project_root: Path) -> None:
    try:
        details = _check_live_source_health_contract_gate(project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "live_source_health_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "live_source_health_contract",
            "status": "passed",
            **details,
        }
    )


def _check_live_source_health_contract_gate(*, project_root: Path) -> Dict[str, Any]:
    from citeguard.retrieval.scholarly_clients import (
        ArxivMetadataSource,
        CrossrefMetadataSource,
        InMemoryMetadataSource,
        OpenAlexMetadataSource,
        SemanticScholarMetadataSource,
    )
    from citeguard.runtime import SOURCE_HEALTH_SCHEMA_VERSION, canonical_source_names, source_health_status

    docs = {
        "README.md": _read_required_text(project_root / "README.md"),
        "docs/cli_reference.md": _read_required_text(project_root / "docs" / "cli_reference.md"),
        "docs/release_checklist.md": _read_required_text(project_root / "docs" / "release_checklist.md"),
        "docs/security_compliance.md": _read_required_text(project_root / "docs" / "security_compliance.md"),
    }
    combined_docs = "\n".join(docs.values())
    required_doc_phrases = {
        "openalex": "OpenAlex",
        "crossref": "Crossref",
        "arxiv": "arXiv",
        "semantic_scholar": "Semantic Scholar",
        "source_health_summary": "sources_checked",
        "source_health_failures": "sources_failed",
        "source_health_attempts": "attempt_count",
        "source_health_retries": "retry_count",
        "source_health_final_url": "final_url",
        "source_health_redirected": "redirected",
        "source_health_retry_after": "retry_after_seconds",
        "source_health_retry_after_sources": "retry_after_sources",
        "source_health_retry_delay": "retry_delay_seconds",
        "source_health_retry_delay_sources": "retry_delay_sources",
        "source_health_retry_guidance": "retry_guidance",
        "source_health_wait_before_retry": "wait_before_retry",
        "source_health_zero_retry_after": "retry_after_seconds=0.0",
        "source_health_per_source": "source_health.sources[]",
        "source_health_invalid_json": "malformed JSON",
        "source_health_confidence_effect": "confidence_effect",
        "source_health_interpretation": "source_outage_lowers_confidence_not_fabrication_evidence",
        "metadata_quality": "metadata.metadata_quality",
        "missing_metadata_policy": "missing fields as incomplete metadata",
        "api_key": "SEMANTIC_SCHOLAR_API_KEY",
    }

    errors = []
    for name, phrase in required_doc_phrases.items():
        if phrase not in combined_docs:
            errors.append(f"live-source health docs missing {name}: {phrase}")

    canonical = canonical_source_names(["OpenAlex", "crossref", "arxiv", "semantic-scholar", "s2"])
    if canonical != ["openalex", "crossref", "arxiv", "semantic_scholar"]:
        errors.append("source aliases should canonicalize and deduplicate four live source families")


    def source_factory(names: List[str], **_: Any) -> object:
        name = names[0]
        if name == "openalex":
            raise TimeoutError("openalex timed out during release gate source-health probe")
        if name == "crossref":
            return _ReleaseGateDiagnosticSource(
                "crossref",
                code="source_unavailable",
                kind="invalid_json",
                status_code=200,
                url="https://api.crossref.org/works?query.title=broken",
                error="JSONDecodeError",
                attempt_count=1,
            )
        if name == "arxiv":
            return InMemoryMetadataSource([])
        if name == "semantic_scholar":
            return _ReleaseGateDiagnosticSource(
                "semantic_scholar",
                code="source_unavailable",
                kind="rate_limited",
                status_code=429,
                url="https://api.semanticscholar.org/graph/v1/paper/search",
                final_url="https://api.semanticscholar.org/graph/v1/paper/search?offset=0",
                redirected=True,
                error="HTTP Error 429: Too Many Requests",
                attempt_count=2,
                retry_count=1,
                retry_after_seconds=2.0,
                retry_delay_seconds=1.5,
            )
        raise RuntimeError(f"unexpected source: {name}")

    health = source_health_status(
        env={
            "CITEGUARD_SOURCES": "openalex,crossref,arxiv,semantic-scholar",
            "CITEGUARD_MAILTO": "release-gate@example.com",
            "SEMANTIC_SCHOLAR_API_KEY": "release-gate-key",
            "CITEGUARD_HTTP_TIMEOUT": "1",
            "CITEGUARD_HTTP_RETRIES": "0",
        },
        check_live=True,
        health_query="Release Gate Live Source Health Control",
        source_factory=source_factory,
    )
    summary = health.get("summary", {})
    sources = {source.get("name"): source for source in health.get("sources", [])}

    if health.get("schema_version") != SOURCE_HEALTH_SCHEMA_VERSION:
        errors.append("live source health schema_version mismatch")
    if health.get("mode") != "live" or health.get("live_check_performed") is not True:
        errors.append("live source health contract should exercise live check mode")
    if summary.get("sources_configured") != ["openalex", "crossref", "arxiv", "semantic_scholar"]:
        errors.append("source health should report all four configured live source families")
    if summary.get("sources_checked") != ["openalex", "crossref", "arxiv", "semantic_scholar"]:
        errors.append("source health should check all four live source families")
    if summary.get("sources_responded") != ["arxiv"]:
        errors.append("source health should distinguish responded sources from failed sources")
    if summary.get("sources_available") != ["arxiv"]:
        errors.append("source health should treat empty arxiv responses as available source responses")
    if summary.get("sources_failed") != ["openalex", "crossref", "semantic_scholar"]:
        errors.append("source health should report failed sources separately")
    if summary.get("failure_kind_counts") != {"timeout": 1, "invalid_json": 1, "rate_limited": 1}:
        errors.append("source health should summarize timeout, malformed-JSON, and rate-limit failure kinds")
    if summary.get("failure_kind_sources") != {
        "timeout": ["openalex"],
        "invalid_json": ["crossref"],
        "rate_limited": ["semantic_scholar"],
    }:
        errors.append("source health should map each failure kind to its source")
    if summary.get("retry_after_seconds") != 2.0:
        errors.append("source health should aggregate Retry-After seconds at summary level")
    if summary.get("retry_after_sources") != ["semantic_scholar"]:
        errors.append("source health should list sources that provided Retry-After at summary level")
    if summary.get("retry_delay_seconds") != 1.5:
        errors.append("source health should aggregate actual retry delay seconds at summary level")
    if summary.get("retry_delay_sources") != ["semantic_scholar"]:
        errors.append("source health should list sources that performed retry delay at summary level")
    if summary.get("retry_guidance") != "wait_before_retry":
        errors.append("source health should route rate-limited probes to retry_guidance=wait_before_retry")
    failure_details = {
        detail.get("source"): detail
        for detail in summary.get("failure_details", [])
        if isinstance(detail, dict)
    }
    if failure_details.get("semantic_scholar", {}).get("attempt_count") != 2:
        errors.append("source health should expose HTTP attempt_count in failure details")
    if failure_details.get("semantic_scholar", {}).get("retry_count") != 1:
        errors.append("source health should expose HTTP retry_count in failure details")
    if failure_details.get("semantic_scholar", {}).get("final_url") != "https://api.semanticscholar.org/graph/v1/paper/search?offset=0":
        errors.append("source health should expose final_url in failure details")
    if failure_details.get("semantic_scholar", {}).get("redirected") is not True:
        errors.append("source health should expose redirected=true in failure details")
    if failure_details.get("semantic_scholar", {}).get("retry_after_seconds") != 2.0:
        errors.append("source health should expose Retry-After seconds in failure details")
    if failure_details.get("semantic_scholar", {}).get("retry_delay_seconds") != 1.5:
        errors.append("source health should expose actual retry delay seconds in failure details")
    if failure_details.get("crossref", {}).get("kind") != "invalid_json":
        errors.append("source health should expose malformed source JSON as kind=invalid_json")
    if failure_details.get("crossref", {}).get("code") != "source_unavailable":
        errors.append("malformed source JSON should use source_unavailable recovery semantics")
    if failure_details.get("crossref", {}).get("status_code") != 200:
        errors.append("malformed source JSON should preserve the HTTP status code")
    if summary.get("next_action") != "retry_or_check_source_health":
        errors.append("source health should route degraded live checks to retry_or_check_source_health")
    if summary.get("all_checked_sources_failed") is not False:
        errors.append("partial live-source outage should not set all_checked_sources_failed")
    if summary.get("confidence_effect") != "partial_source_limited":
        errors.append("partial live-source outage should report confidence_effect=partial_source_limited")
    if summary.get("interpretation") != "source_outage_lowers_confidence_not_fabrication_evidence":
        errors.append("live source health should state outage lowers confidence without proving fabrication")
    if sources.get("semantic_scholar", {}).get("api_key_configured") is not True:
        errors.append("semantic_scholar source health should expose api_key_configured")
    if sources.get("semantic_scholar", {}).get("polite_access", {}).get("status") != "not_required":
        errors.append("semantic_scholar polite access should not require CITEGUARD_MAILTO")
    if sources.get("openalex", {}).get("mailto_configured") is not True:
        errors.append("openalex source health should expose configured mailto")
    if sources.get("crossref", {}).get("mailto_configured") is not True:
        errors.append("crossref source health should expose configured mailto")
    if sources.get("arxiv", {}).get("next_action") != "continue":
        errors.append("available source item should expose next_action=continue")
    if sources.get("arxiv", {}).get("confidence_effect") != "none":
        errors.append("available source item should expose confidence_effect=none")
    if sources.get("openalex", {}).get("next_action") != "retry_or_check_source_health":
        errors.append("failed source item should expose next_action=retry_or_check_source_health")
    if sources.get("openalex", {}).get("confidence_effect") != "source_unavailable":
        errors.append("failed source item should expose confidence_effect=source_unavailable")
    if sources.get("openalex", {}).get("recovery_code") != "timeout":
        errors.append("timeout source item should expose recovery_code=timeout")
    if sources.get("crossref", {}).get("recovery_code") != "source_unavailable":
        errors.append("malformed JSON source item should expose source_unavailable recovery_code")
    if sources.get("semantic_scholar", {}).get("retry_after_seconds") != 2.0:
        errors.append("rate-limited source item should expose retry_after_seconds")
    if sources.get("semantic_scholar", {}).get("retry_delay_seconds") != 1.5:
        errors.append("rate-limited source item should expose retry_delay_seconds")
    if sources.get("semantic_scholar", {}).get("retry_guidance") != "wait_before_retry":
        errors.append("rate-limited source item should expose retry_guidance=wait_before_retry")

    def zero_retry_source_factory(names: List[str], **_: Any) -> object:
        return _ReleaseGateDiagnosticSource(
            names[0],
            code="source_unavailable",
            kind="rate_limited",
            status_code=429,
            url="https://api.semanticscholar.org/graph/v1/paper/search",
            error="HTTP Error 429: Too Many Requests",
            attempt_count=1,
        retry_after_seconds=0.0,
        retry_delay_seconds=None,
        )

    zero_retry_health = source_health_status(
        env={"CITEGUARD_SOURCES": "semantic_scholar"},
        check_live=True,
        health_query="Release Gate Expired Retry After",
        source_factory=zero_retry_source_factory,
    )
    zero_retry_summary = zero_retry_health.get("summary", {})
    zero_retry_source = (zero_retry_health.get("sources") or [{}])[0]
    if zero_retry_summary.get("retry_after_seconds") != 0.0:
        errors.append("source health should preserve zero-second Retry-After hints")
    if zero_retry_summary.get("retry_after_sources") != ["semantic_scholar"]:
        errors.append("source health should preserve Retry-After source for zero-second hints")
    if zero_retry_summary.get("retry_delay_seconds") is not None:
        errors.append("zero-second Retry-After without retry should not invent retry_delay_seconds")
    if zero_retry_summary.get("retry_delay_sources") != []:
        errors.append("zero-second Retry-After without retry should not report retry_delay_sources")
    if zero_retry_summary.get("retry_guidance") == "wait_before_retry":
        errors.append("zero-second Retry-After should not require wait_before_retry")
    if zero_retry_source.get("retry_after_seconds") != 0.0:
        errors.append("source item should preserve zero-second Retry-After hints")
    if zero_retry_source.get("retry_delay_seconds") is not None:
        errors.append("source item should not invent retry_delay_seconds for zero-second no-retry hints")
    if zero_retry_source.get("retry_guidance") == "wait_before_retry":
        errors.append("source item zero-second Retry-After should not require wait_before_retry")

    class _SparseCrossrefHTTP:
        def get_json(self, *_: Any, **__: Any) -> Dict[str, Any]:
            return {
                "message": {
                    "items": [
                        {
                            "title": "Release Gate Sparse Crossref Metadata",
                            "author": [{"given": "Ada", "family": "Lovelace"}],
                            "issued": {"date-parts": [[None]]},
                            "DOI": "10.5555/release-crossref",
                        }
                    ]
                }
            }

        def get_text(self, *_: Any, **__: Any) -> str:
            return ""

    class _SparseOpenAlexHTTP:
        def get_json(self, *_: Any, **__: Any) -> Dict[str, Any]:
            return {
                "results": [
                    {
                        "id": "https://openalex.org/WCG",
                        "display_name": "Release Gate Sparse OpenAlex Metadata",
                        "authorships": [{"author": {"display_name": "Grace Hopper"}}],
                        "publication_year": 2026,
                        "primary_location": None,
                        "best_oa_location": None,
                        "abstract_inverted_index": {},
                    }
                ]
            }

        def get_text(self, *_: Any, **__: Any) -> str:
            return ""

    class _SparseSemanticScholarHTTP:
        def get_json(self, *_: Any, **__: Any) -> Dict[str, Any]:
            return {
                "data": [
                    {
                        "paperId": None,
                        "title": "Release Gate Sparse Semantic Scholar Metadata",
                        "authors": [{"name": "Katherine Johnson"}],
                        "year": "2026",
                        "venue": None,
                        "abstract": None,
                        "externalIds": ["not-a-dict"],
                        "url": None,
                    }
                ]
            }

    class _SparseArxivHTTP:
        def get_text(self, *_: Any, **__: Any) -> str:
            return """<?xml version="1.0" encoding="UTF-8"?>
            <feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
              <entry>
                <id>https://arxiv.org/abs/2601.00001v1</id>
                <title>Release Gate Sparse arXiv Metadata</title>
                <summary>Release gate arXiv abstract.</summary>
                <author><name>Ada Lovelace</name></author>
                <published>not-a-date</published>
              </entry>
            </feed>
            """

    quality_records = {
        "crossref": CrossrefMetadataSource(http_client=_SparseCrossrefHTTP(), harvest_evidence=False).search(
            "release gate sparse crossref",
            top_k=1,
        )[0],
        "openalex": OpenAlexMetadataSource(http_client=_SparseOpenAlexHTTP(), harvest_evidence=False).search(
            "release gate sparse openalex",
            top_k=1,
        )[0],
        "semantic_scholar": SemanticScholarMetadataSource(http_client=_SparseSemanticScholarHTTP()).search(
            "release gate sparse semantic scholar",
            top_k=1,
        )[0],
        "arxiv": ArxivMetadataSource(http_client=_SparseArxivHTTP(), harvest_evidence=False).search(
            "release gate sparse arxiv",
            top_k=1,
        )[0],
    }
    metadata_quality = {
        name: record.metadata.get("metadata_quality", {})
        for name, record in quality_records.items()
    }
    for source_name, quality in metadata_quality.items():
        if quality.get("schema_version") != 1:
            errors.append(f"{source_name} metadata_quality should expose schema_version=1")
        if not isinstance(quality.get("missing_fields"), list):
            errors.append(f"{source_name} metadata_quality should expose missing_fields")
        if not isinstance(quality.get("present_fields"), list):
            errors.append(f"{source_name} metadata_quality should expose present_fields")
        if "completeness" not in quality:
            errors.append(f"{source_name} metadata_quality should expose completeness")
        if "identifiers" not in quality:
            errors.append(f"{source_name} metadata_quality should expose identifier provenance")
        if quality.get("confidence_effect") != "missing_metadata_lowers_confidence_not_fabrication_evidence":
            errors.append(f"{source_name} sparse metadata should lower confidence without fabrication evidence")
    if "identifier" not in metadata_quality.get("crossref", {}).get("present_fields", []):
        errors.append("Crossref DOI should satisfy metadata_quality identifier")
    if "identifier" not in metadata_quality.get("arxiv", {}).get("present_fields", []):
        errors.append("arXiv id should satisfy metadata_quality identifier")
    for source_name in ["openalex", "semantic_scholar"]:
        if "identifier" not in metadata_quality.get(source_name, {}).get("missing_fields", []):
            errors.append(f"{source_name} missing DOI/arXiv id should report missing identifier")

    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "docs_checked": sorted(docs),
        "schema_version": health.get("schema_version"),
        "aliases_checked": ["OpenAlex", "crossref", "arxiv", "semantic-scholar", "s2"],
        "canonical_sources": canonical,
        "sources_checked": summary.get("sources_checked"),
        "sources_responded": summary.get("sources_responded"),
        "sources_failed": summary.get("sources_failed"),
        "failure_details": summary.get("failure_details"),
        "failure_kind_counts": summary.get("failure_kind_counts"),
        "failure_kind_sources": summary.get("failure_kind_sources"),
        "retry_after_seconds": summary.get("retry_after_seconds"),
        "retry_after_sources": summary.get("retry_after_sources"),
        "retry_delay_seconds": summary.get("retry_delay_seconds"),
        "retry_delay_sources": summary.get("retry_delay_sources"),
        "retry_guidance": summary.get("retry_guidance"),
        "confidence_effect": summary.get("confidence_effect"),
        "interpretation": summary.get("interpretation"),
        "semantic_scholar": {
            "api_key_configured": sources.get("semantic_scholar", {}).get("api_key_configured"),
            "polite_access": sources.get("semantic_scholar", {}).get("polite_access", {}),
            "next_action": sources.get("semantic_scholar", {}).get("next_action"),
            "retry_after_seconds": sources.get("semantic_scholar", {}).get("retry_after_seconds"),
            "retry_delay_seconds": sources.get("semantic_scholar", {}).get("retry_delay_seconds"),
            "retry_guidance": sources.get("semantic_scholar", {}).get("retry_guidance"),
        },
        "zero_retry_after": {
            "retry_after_seconds": zero_retry_summary.get("retry_after_seconds"),
            "retry_after_sources": zero_retry_summary.get("retry_after_sources"),
            "retry_delay_seconds": zero_retry_summary.get("retry_delay_seconds"),
            "retry_delay_sources": zero_retry_summary.get("retry_delay_sources"),
            "summary_retry_guidance": zero_retry_summary.get("retry_guidance"),
            "source_retry_delay_seconds": zero_retry_source.get("retry_delay_seconds"),
            "source_retry_guidance": zero_retry_source.get("retry_guidance"),
        },
        "source_item_contract": {
            name: {
                "status": item.get("status"),
                "next_action": item.get("next_action"),
                "confidence_effect": item.get("confidence_effect"),
                "recovery_code": item.get("recovery_code"),
                "retry_delay_seconds": item.get("retry_delay_seconds"),
                "retry_guidance": item.get("retry_guidance"),
            }
            for name, item in sorted(sources.items())
        },
        "metadata_quality_contract": {
            name: {
                "missing_fields": quality.get("missing_fields", []),
                "present_fields": quality.get("present_fields", []),
                "identifiers": quality.get("identifiers", {}),
                "confidence_effect": quality.get("confidence_effect"),
            }
            for name, quality in sorted(metadata_quality.items())
        },
        "policy": "release gate enforces source-level health for OpenAlex, Crossref, arXiv, and Semantic Scholar",
    }


class _ReleaseGateTimeoutSource:
    def __init__(self, name: str) -> None:
        self.name = name

    def all_records(self) -> List[Any]:
        return []

    def search(self, query: str, top_k: int = 5) -> List[Any]:
        raise TimeoutError(f"{self.name} timed out during release gate probe")

    def lookup(self, candidate: Any) -> Any:
        raise TimeoutError(f"{self.name} timed out during release gate lookup")


class _ReleaseGateHTTPDiagnostics:
    def __init__(
        self,
        *,
        code: str,
        kind: str,
        status_code: Optional[int],
        url: str,
        error: str,
        final_url: str = "",
        redirected: bool = False,
        cache_hit: bool = False,
        attempt_count: int = 0,
        retry_count: int = 0,
        retry_after_seconds: Optional[float] = None,
        retry_delay_seconds: Optional[float] = None,
    ) -> None:
        self.last_error_code = code
        self.last_error_kind = kind
        self.last_status_code = status_code
        self.last_url = url
        self.last_final_url = final_url or url
        self.last_redirected = redirected
        self.last_error = error
        self.last_cache_hit = cache_hit
        self.last_attempt_count = attempt_count
        self.last_retry_count = retry_count
        self.last_retry_after_seconds = retry_after_seconds
        self.last_retry_delay_seconds = retry_delay_seconds


class _ReleaseGateDiagnosticSource:
    def __init__(
        self,
        name: str,
        *,
        code: str,
        kind: str,
        status_code: Optional[int],
        url: str,
        error: str,
        final_url: str = "",
        redirected: bool = False,
        attempt_count: int = 0,
        retry_count: int = 0,
        retry_after_seconds: Optional[float] = None,
        retry_delay_seconds: Optional[float] = None,
    ) -> None:
        self.name = name
        self.http_client = _ReleaseGateHTTPDiagnostics(
            code=code,
            kind=kind,
            status_code=status_code,
            url=url,
            final_url=final_url,
            redirected=redirected,
            error=error,
            attempt_count=attempt_count,
            retry_count=retry_count,
            retry_after_seconds=retry_after_seconds,
            retry_delay_seconds=retry_delay_seconds,
        )

    def all_records(self) -> List[Any]:
        return []

    def search(self, query: str, top_k: int = 5) -> List[Any]:
        return []

    def lookup(self, candidate: Any) -> Any:
        return None


def _record_security_compliance_contract_gate(summary: Dict[str, Any], *, project_root: Path) -> None:
    try:
        details = _check_security_compliance_contract_gate(project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "security_compliance_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "security_compliance_contract",
            "status": "passed",
            **details,
        }
    )


def _check_security_compliance_contract_gate(*, project_root: Path) -> Dict[str, Any]:
    from citeguard.retrieval.scholarly_clients.evidence import (
        BLOCKED_EVIDENCE_HOST_SUFFIXES,
        harvest_remote_evidence_report,
        is_allowed_remote_evidence_url,
    )
    from citeguard.retrieval.scholarly_clients.factory import build_live_metadata_source
    from citeguard.runtime import environment_status, polite_access_status, source_health_status

    docs = {
        "README.md": _read_required_text(project_root / "README.md"),
        "docs/chinaxiv_spike.md": _read_required_text(project_root / "docs" / "chinaxiv_spike.md"),
        "docs/security_compliance.md": _read_required_text(project_root / "docs" / "security_compliance.md"),
        "docs/release_checklist.md": _read_required_text(project_root / "docs" / "release_checklist.md"),
    }
    combined_docs = "\n".join(docs.values())
    required_doc_phrases = {
        "cnki_boundary": "does not scrape CNKI",
        "wanfang_boundary": "Wanfang",
        "paywall_boundary": "must not bypass paywalls",
        "robots_boundary": "robots.txt",
        "mailto_config": "CITEGUARD_MAILTO",
        "not_legal_authority": "not a legal authority",
        "human_integrity_decisions": "Final decisions about research integrity",
        "not_fake_overclaim": "not proof that a citation is fake",
        "chinaxiv_no_go": "We will **not** integrate ChinaXiv as a metadata source",
        "chinaxiv_no_scrape": "We will **not** scrape login-gated, paywalled, or otherwise restricted ChinaXiv content",
    }

    missing = []
    for name, phrase in required_doc_phrases.items():
        if phrase not in combined_docs:
            missing.append(f"compliance docs missing {name}: {phrase}")

    missing_contact = polite_access_status(
        env={
            "CITEGUARD_SOURCES": "openalex,crossref",
        }
    )
    configured_contact = polite_access_status(
        env={
            "CITEGUARD_SOURCES": "openalex,arxiv",
            "CITEGUARD_MAILTO": "release-gate@example.com",
        }
    )
    fixture_mode = polite_access_status(
        env={
            "CITEGUARD_FIXTURE_CITATIONS": "examples/citations.json",
        }
    )
    health = source_health_status(
        env={
            "CITEGUARD_SOURCES": "openalex,crossref,arxiv,semantic-scholar",
        },
        check_live=False,
    )
    env_status = environment_status(
        env={
            "CITEGUARD_SOURCES": "openalex,crossref",
            "CITEGUARD_REMOTE_EVIDENCE": "0",
        },
        check_sources=False,
    )
    default_mailto_source = build_live_metadata_source(
        ["openalex", "crossref"],
        harvest_remote_evidence=False,
    )
    configured_mailto_source = build_live_metadata_source(
        ["openalex", "crossref"],
        mailto="release-gate@example.com",
        harvest_remote_evidence=False,
    )

    if missing_contact.get("status") != "missing_contact_email":
        missing.append("polite_access_status should flag missing OpenAlex/Crossref contact email")
    if missing_contact.get("compliant") is not False:
        missing.append("missing CITEGUARD_MAILTO should be non-compliant for OpenAlex/Crossref")
    if missing_contact.get("configured_contact_required_sources") != ["openalex", "crossref"]:
        missing.append("missing-contact summary should identify OpenAlex and Crossref")
    if missing_contact.get("next_action") != "fix_configuration":
        missing.append("missing-contact next_action should be fix_configuration")

    if configured_contact.get("status") != "configured":
        missing.append("configured CITEGUARD_MAILTO should report status=configured")
    if configured_contact.get("compliant") is not True:
        missing.append("configured CITEGUARD_MAILTO should be compliant")
    if configured_contact.get("configured_contact_required_sources") != ["openalex"]:
        missing.append("configured-contact summary should identify configured contact-required sources")
    if configured_contact.get("next_action") != "continue":
        missing.append("configured-contact next_action should be continue")

    if fixture_mode.get("status") != "fixture_bypasses_live_sources":
        missing.append("fixture mode should report fixture_bypasses_live_sources")
    if fixture_mode.get("compliant") is not True:
        missing.append("fixture mode should be compliant without live-source contact email")
    if fixture_mode.get("next_action") != "continue":
        missing.append("fixture-mode next_action should be continue")

    default_mailto_sources = getattr(default_mailto_source, "sources", [default_mailto_source])
    configured_mailto_sources = getattr(configured_mailto_source, "sources", [configured_mailto_source])
    default_mailto_by_name = {source.name: getattr(source, "mailto", "") for source in default_mailto_sources}
    configured_mailto_by_name = {source.name: getattr(source, "mailto", "") for source in configured_mailto_sources}
    default_user_agents = {source.name: source.http_client.user_agent for source in default_mailto_sources}
    configured_user_agents = {source.name: source.http_client.user_agent for source in configured_mailto_sources}
    placeholder_contact = "research@example.com"
    if any(value for value in default_mailto_by_name.values()):
        missing.append("default OpenAlex/Crossref adapters should not send placeholder mailto params")
    if any(placeholder_contact in value for value in default_user_agents.values()):
        missing.append("default OpenAlex/Crossref User-Agent should not include placeholder contact email")
    if configured_mailto_by_name != {"openalex": "release-gate@example.com", "crossref": "release-gate@example.com"}:
        missing.append("configured OpenAlex/Crossref adapters should preserve real mailto params")
    if not all("mailto:release-gate@example.com" in value for value in configured_user_agents.values()):
        missing.append("configured OpenAlex/Crossref User-Agent should include real contact email")

    sources = {source.get("name"): source for source in health.get("sources", [])}
    for source_name in ["openalex", "crossref"]:
        polite = sources.get(source_name, {}).get("polite_access", {})
        if polite.get("status") != "missing_contact_email":
            missing.append(f"{source_name} source health should expose missing_contact_email polite access")
        if polite.get("next_action") != "fix_configuration":
            missing.append(f"{source_name} source health should expose fix_configuration next_action")
    for source_name in ["arxiv", "semantic_scholar"]:
        polite = sources.get(source_name, {}).get("polite_access", {})
        if polite.get("status") != "not_required":
            missing.append(f"{source_name} source health should expose not_required polite access")
        if polite.get("next_action") != "continue":
            missing.append(f"{source_name} source health should expose continue next_action")

    remote_policy = env_status.get("remote_evidence_policy", {})
    blocked_suffixes = list(BLOCKED_EVIDENCE_HOST_SUFFIXES)
    for suffix in ["cnki.net", "wanfangdata.com", "cqvip.com"]:
        if suffix not in blocked_suffixes:
            missing.append(f"blocked gated source suffix missing: {suffix}")
        if suffix not in remote_policy.get("blocked_host_suffixes", []):
            missing.append(f"environment_status remote policy missing blocked suffix: {suffix}")
    if remote_policy.get("default_enabled") is not False:
        missing.append("remote evidence policy should remain disabled by default")
    if remote_policy.get("non_http_urls_allowed") is not False:
        missing.append("remote evidence policy should reject non-HTTP URLs")

    class _ReleaseEvidenceHTTPClient:
        def __init__(self) -> None:
            self.requested_urls: List[str] = []
            self.last_error_code = ""
            self.last_error_kind = ""
            self.last_status_code = None
            self.last_url = ""
            self.last_error = ""
            self.last_cache_hit = False
            self.last_attempt_count = 0
            self.last_retry_count = 0
            self.last_retry_after_seconds = None
            self.last_retry_delay_seconds = None

        def get_text(self, url: str, **_: Any) -> str:
            self.requested_urls.append(url)
            return """
            <html>
              <head><meta name="description" content="A lawful open landing-page snippet." /></head>
              <body><p>This open page is safe to inspect for a release gate.</p></body>
            </html>
            """

    class _ReleaseRateLimitedEvidenceHTTPClient:
        def __init__(self) -> None:
            self.requested_urls: List[str] = []
            self.last_error_code = ""
            self.last_error_kind = ""
            self.last_status_code = None
            self.last_url = ""
            self.last_error = ""
            self.last_cache_hit = False
            self.last_attempt_count = 0
            self.last_retry_count = 0
            self.last_retry_after_seconds = None
            self.last_retry_delay_seconds = None

        def get_text(self, url: str, **_: Any) -> str:
            self.requested_urls.append(url)
            self.last_error_code = "source_unavailable"
            self.last_error_kind = "rate_limited"
            self.last_status_code = 429
            self.last_url = url
            self.last_error = "http_429"
            self.last_attempt_count = 1
            self.last_retry_count = 0
            self.last_retry_after_seconds = 2.0
            self.last_retry_delay_seconds = None
            return ""

    class _ReleaseNonHtmlEvidenceHTTPClient:
        def __init__(self) -> None:
            self.requested_urls: List[str] = []
            self.last_error_code = ""
            self.last_error_kind = ""
            self.last_status_code = None
            self.last_url = ""
            self.last_error = ""
            self.last_cache_hit = False
            self.last_attempt_count = 0
            self.last_retry_count = 0
            self.last_retry_after_seconds = None
            self.last_retry_delay_seconds = None
            self.last_retry_delay_seconds = None

        def get_text(self, url: str, **_: Any) -> str:
            self.requested_urls.append(url)
            self.last_status_code = 200
            self.last_url = url
            self.last_attempt_count = 1
            return "%PDF-1.7 release gate publisher page"

    class _ReleaseNoExtractableEvidenceHTTPClient:
        def __init__(self) -> None:
            self.requested_urls: List[str] = []
            self.last_error_code = ""
            self.last_error_kind = ""
            self.last_status_code = None
            self.last_url = ""
            self.last_error = ""
            self.last_cache_hit = False
            self.last_attempt_count = 0
            self.last_retry_count = 0
            self.last_retry_after_seconds = None
            self.last_retry_delay_seconds = None

        def get_text(self, url: str, **_: Any) -> str:
            self.requested_urls.append(url)
            self.last_status_code = 200
            self.last_url = url
            self.last_attempt_count = 1
            return "<html><head><title>Publisher</title></head><body><div></div></body></html>"

    evidence_http = _ReleaseEvidenceHTTPClient()
    evidence_report = harvest_remote_evidence_report(
        evidence_http,
        urls=[
            "https://kns.cnki.net/kcms/detail/example",
            "https://www.wanfangdata.com.cn/details/detail.do",
            "file:///tmp/local.html",
            "https://example.org/open-paper",
        ],
        source_name="release_gate",
        timeout=1,
    )
    rate_limited_evidence_http = _ReleaseRateLimitedEvidenceHTTPClient()
    rate_limited_evidence_report = harvest_remote_evidence_report(
        rate_limited_evidence_http,
        urls=["https://example.org/rate-limited-paper"],
        source_name="release_gate",
        timeout=1,
    )
    non_html_evidence_http = _ReleaseNonHtmlEvidenceHTTPClient()
    non_html_evidence_report = harvest_remote_evidence_report(
        non_html_evidence_http,
        urls=["https://example.org/publisher.pdf"],
        source_name="release_gate",
        timeout=1,
    )
    no_extractable_evidence_http = _ReleaseNoExtractableEvidenceHTTPClient()
    no_extractable_evidence_report = harvest_remote_evidence_report(
        no_extractable_evidence_http,
        urls=["https://example.org/empty-publisher-page"],
        source_name="release_gate",
        timeout=1,
    )
    blocked_url_checks = {
        "cnki": is_allowed_remote_evidence_url("https://kns.cnki.net/kcms/detail/example"),
        "wanfang": is_allowed_remote_evidence_url("https://www.wanfangdata.com.cn/details/detail.do"),
        "file": is_allowed_remote_evidence_url("file:///tmp/local.html"),
        "open_http": is_allowed_remote_evidence_url("https://example.org/open-paper"),
    }
    if evidence_http.requested_urls != ["https://example.org/open-paper"]:
        missing.append("remote evidence harvester should skip gated-source and non-HTTP URLs before fetching")
    if blocked_url_checks != {"cnki": False, "wanfang": False, "file": False, "open_http": True}:
        missing.append("remote evidence URL allowlist checks should reject gated/non-HTTP and allow open HTTP URLs")
    if not evidence_report.get("chunks"):
        missing.append("remote evidence release smoke should harvest the allowed open HTTP URL")
    if evidence_report.get("failures"):
        missing.append("remote evidence release smoke should not record failures for skipped blocked URLs")
    rate_limited_failures = rate_limited_evidence_report.get("failures", [])
    if len(rate_limited_failures) != 1:
        missing.append("remote evidence rate-limit smoke should record one nonfatal evidence failure")
        rate_limited_failure = {}
    else:
        rate_limited_failure = rate_limited_failures[0]
    if rate_limited_failure.get("code") != "source_unavailable":
        missing.append("remote evidence rate-limit smoke should expose code=source_unavailable")
    if rate_limited_failure.get("kind") != "rate_limited":
        missing.append("remote evidence rate-limit smoke should expose kind=rate_limited")
    if rate_limited_failure.get("status_code") != 429:
        missing.append("remote evidence rate-limit smoke should expose status_code=429")
    if rate_limited_failure.get("attempt_count") != 1:
        missing.append("remote evidence rate-limit smoke should expose attempt_count")
    if rate_limited_failure.get("retry_count") != 0:
        missing.append("remote evidence rate-limit smoke should expose retry_count")
    if rate_limited_failure.get("retry_after_seconds") != 2.0:
        missing.append("remote evidence rate-limit smoke should preserve retry_after_seconds")
    if rate_limited_failure.get("retry_delay_seconds") is not None:
        missing.append("remote evidence rate-limit smoke should not invent retry_delay_seconds without retry")
    non_html_failures = non_html_evidence_report.get("failures", [])
    non_html_failure = non_html_failures[0] if non_html_failures else {}
    if non_html_failure.get("kind") != "non_html_response":
        missing.append("remote evidence smoke should record non_html_response landing pages")
    if non_html_failure.get("code") != "source_unavailable":
        missing.append("remote evidence non_html_response should use code=source_unavailable")
    no_extractable_failures = no_extractable_evidence_report.get("failures", [])
    no_extractable_failure = no_extractable_failures[0] if no_extractable_failures else {}
    if no_extractable_failure.get("kind") != "no_extractable_evidence":
        missing.append("remote evidence smoke should record no_extractable_evidence landing pages")
    if no_extractable_failure.get("code") != "source_unavailable":
        missing.append("remote evidence no_extractable_evidence should use code=source_unavailable")

    if missing:
        raise RuntimeError("; ".join(missing))

    return {
        "docs_checked": sorted(docs),
        "blocked_gated_source_suffixes": blocked_suffixes,
        "missing_contact": {
            "status": missing_contact.get("status"),
            "compliant": missing_contact.get("compliant"),
            "configured_contact_required_sources": missing_contact.get("configured_contact_required_sources"),
            "next_action": missing_contact.get("next_action"),
        },
        "configured_contact": {
            "status": configured_contact.get("status"),
            "compliant": configured_contact.get("compliant"),
            "configured_contact_required_sources": configured_contact.get("configured_contact_required_sources"),
            "next_action": configured_contact.get("next_action"),
        },
        "fixture_mode": {
            "status": fixture_mode.get("status"),
            "compliant": fixture_mode.get("compliant"),
            "next_action": fixture_mode.get("next_action"),
        },
        "mailto_parameter_policy": {
            "placeholder_contact": placeholder_contact,
            "default_mailto_by_source": default_mailto_by_name,
            "default_user_agents": default_user_agents,
            "configured_mailto_by_source": configured_mailto_by_name,
            "configured_user_agents": configured_user_agents,
            "policy": "placeholder contact emails are treated as unconfigured and are not sent as source mailto params",
        },
        "source_health_polite_access": {
            name: sources.get(name, {}).get("polite_access", {})
            for name in ["openalex", "crossref", "arxiv", "semantic_scholar"]
        },
        "remote_evidence_policy": {
            "enabled": remote_policy.get("enabled"),
            "default_enabled": remote_policy.get("default_enabled"),
            "non_http_urls_allowed": remote_policy.get("non_http_urls_allowed"),
        },
        "remote_evidence_fetch_smoke": {
            "requested_urls": evidence_http.requested_urls,
            "blocked_url_checks": blocked_url_checks,
            "chunk_count": len(evidence_report.get("chunks", [])),
            "failure_count": len(evidence_report.get("failures", [])),
            "rate_limited_failure": {
                "requested_urls": rate_limited_evidence_http.requested_urls,
                "code": rate_limited_failure.get("code"),
                "kind": rate_limited_failure.get("kind"),
                "status_code": rate_limited_failure.get("status_code"),
                "attempt_count": rate_limited_failure.get("attempt_count"),
                "retry_count": rate_limited_failure.get("retry_count"),
                "retry_after_seconds": rate_limited_failure.get("retry_after_seconds"),
                "retry_delay_seconds": rate_limited_failure.get("retry_delay_seconds"),
            },
            "non_html_failure": {
                "requested_urls": non_html_evidence_http.requested_urls,
                "code": non_html_failure.get("code"),
                "kind": non_html_failure.get("kind"),
                "status_code": non_html_failure.get("status_code"),
                "attempt_count": non_html_failure.get("attempt_count"),
                "retry_count": non_html_failure.get("retry_count"),
                "retry_delay_seconds": non_html_failure.get("retry_delay_seconds"),
            },
            "no_extractable_failure": {
                "requested_urls": no_extractable_evidence_http.requested_urls,
                "code": no_extractable_failure.get("code"),
                "kind": no_extractable_failure.get("kind"),
                "status_code": no_extractable_failure.get("status_code"),
                "attempt_count": no_extractable_failure.get("attempt_count"),
                "retry_count": no_extractable_failure.get("retry_count"),
                "retry_delay_seconds": no_extractable_failure.get("retry_delay_seconds"),
            },
        },
        "policy": "release gate enforces polite live-source access and no gated-source/paywall bypass boundaries",
    }


def _record_agent_skill_contract_gate(summary: Dict[str, Any], *, project_root: Path) -> None:
    try:
        details = _check_agent_skill_contract_gate(project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "agent_skill_contract",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "agent_skill_contract",
            "status": "passed",
            **details,
        }
    )


def _check_agent_skill_contract_gate(*, project_root: Path) -> Dict[str, Any]:
    from citeguard.verification.support_eval import load_support_eval, run_support_eval_report
    from citeguard.verifiers import HeuristicSupportBackend

    skill_path = project_root / "skills" / "citeguard-verify" / "SKILL.md"
    examples_path = project_root / "skills" / "citeguard-verify" / "references" / "examples.md"
    openai_agent_path = project_root / "skills" / "citeguard-verify" / "agents" / "openai.yaml"
    skill = _read_required_text(skill_path)
    examples = _read_required_text(examples_path)
    openai_agent = _read_required_text(openai_agent_path)
    support_cases = [
        case for case in load_support_eval(str(project_root / "data" / "eval" / "support_eval.json")) if case.split == "test"
    ]
    support_report = run_support_eval_report(support_cases, HeuristicSupportBackend())
    support_overall = support_report["overall"]
    support_review_plan = support_report["false_support_analysis"]["review_plan"]

    required_skill_phrases = {
        "trigger_related_work": "related work",
        "trigger_bibliography": "pasted citations / a bibliography",
        "trigger_generated_citations": "about to present citations you generated yourself",
        "forbid_silent_edits": "Do not silently change the user's references.",
        "forbid_not_found_fake": "Do not translate `not_found`, `source_unavailable`, or `timeout` into \"fake\".",
        "forbid_full_text_upgrade": "Do not claim full-text support from an abstract-level support result.",
        "codex_install_note": "Codex:",
        "claude_code_install_note": "Claude Code:",
        "cursor_install_note": "Cursor:",
        "status_first": "call `citeguard_status_tool`",
        "source_health_confidence_effect": "`source_health.summary.confidence_effect`",
        "source_health_interpretation": "`source_health.summary.interpretation`",
        "source_health_outage_interpretation": "source_outage_lowers_confidence_not_fabrication_evidence",
        "support_models_engine": "`support_models.engine`",
        "support_models_next_action": "`support_models.next_action`",
        "heuristic_fallback_wording": "`heuristic_fallback` mode",
        "support_model_warmup": "python3 scripts/warmup_support_models.py",
        "batch_review_summary": "`review_summary` first",
        "batch_triage_plan": "`review_summary.triage_plan.status`",
        "batch_triage_policy": "source retry inconclusive",
        "batch_risk_reason": "`risk_reason` for the compact",
        "batch_suggested_fix": "`suggested_fix.kind`",
        "batch_suggested_fix_confirmation": "`suggested_fix.requires_user_confirmation`",
        "evidence_source_name": "`evidence_source_name`",
        "source_metadata_missing_fields": "`source_metadata_missing_fields`",
        "source_metadata_confidence_effect": "`source_metadata_confidence_effect`",
        "input_source_line_start": "`input_source_line_start`",
        "input_source_line_end": "`input_source_line_end`",
        "source_item_column": "`source item`",
        "path_line_display": "`path:line`",
        "high_risk_filtering": "`filtered.returned_indexes`",
        "policy_boundary_packet": "`--case-type weak_set_boundary --unreviewed-only`",
        "support_benchmark_macro_f1": "`overall.macro_f1`",
        "support_benchmark_weighted_f1": "`overall.weighted_f1`",
        "support_benchmark_false_support_rate": "`overall.false_support_rate`",
        "support_benchmark_abstention_rate": "`overall.abstention_rate`",
        "false_support_review_plan": "`false_support_analysis.review_plan`",
        "false_support_review_plan_status": "`review_plan.status`",
        "supported_overcall_blockers_phase": "`supported_overcall_blockers`",
        "weak_support_overcall_review_phase": "`weak_support_overcall_review`",
        "highest_risk_slice_review_phase": "`highest_risk_slice_review`",
        "scope_assessed_annotation": "`annotation.evidence_scope_assessed`",
        "full_text_needed_annotation": "`annotation.full_text_needed`",
        "scope_provenance_auditable": "judgments remain auditable after merge",
        "pre_response_safety_checklist": "## Pre-response Safety Checklist",
        "pre_response_no_silent_edits": "No silent edits:",
        "pre_response_no_fabrication_overclaim": "No fabrication overclaim:",
        "pre_response_scope_explicit": "Scope is explicit:",
        "pre_response_traceability": "Traceability is preserved:",
        "pre_response_machine_readable_next_action": "Next action is machine-readable:",
        "pre_response_machine_readable_error_next_action": "`error.next_action`",
        "pre_response_machine_readable_error_retryable": "`error.retryable`",
        "pre_response_machine_readable_error_category": "`error.category`",
        "response_template": "## Response template",
        "scenario_routing": "## Scenario routing",
        "scenario_full_text_evidence": "User supplies a lawful excerpt or local full-text file",
        "scenario_support_audit_reference_file": "citeguard support-audit refs.md --claim",
        "scenario_latex_external_bib": "local `\\bibliography{refs}` / `\\addbibresource{refs.bib}`",
        "scenario_compiled_bbl": "compiled `.bbl`",
        "detailed_examples_reference": "references/examples.md",
    }
    required_example_phrases = {
        "single_citation_example": '"tool": "verify_citation_tool"',
        "source_health_confidence_contract_example": "Source-health confidence contract:",
        "source_health_confidence_effect_payload": '"confidence_effect": "partial_source_limited"',
        "source_health_interpretation_payload": '"interpretation": "source_outage_lowers_confidence_not_fabrication_evidence"',
        "source_health_confidence_safe_wording": "limits confidence and should trigger retry or source-health inspection",
        "support_model_status_example": "Support model status:",
        "support_model_next_action_example": '"next_action": "install_or_configure_dependency"',
        "support_model_degraded_wording": "Claim-support checks are degraded",
        "batch_audit_example": '"tool": "audit_citations_tool"',
        "high_risk_only_example": '"high_risk_only": true',
        "filtered_indexes_wording": "filtered.returned_indexes",
        "claim_support_example": '"tool": "check_claim_support_tool"',
        "full_text_support_payload": '"full_text": [',
        "full_text_support_scope_wording": "evidence_scope=full_text",
        "full_text_support_source_field": "evidence.source_field=user_full_text_excerpt_1",
        "full_text_support_safe_input": "caller-provided lawful excerpts",
        "full_text_support_no_paywall": "Do not fetch gated full text, bypass paywalls",
        "full_text_file_support_example": "Claim support with a user-provided lawful local file:",
        "full_text_file_argument": '"full_text_file": "/path/to/lawful-full-text-excerpt.txt"',
        "full_text_file_source_field": "evidence.source_field=user_full_text_file_1",
        "full_text_file_error_code": "error.code=file_error",
        "full_text_file_error_field": "error.details.field=full_text_file",
        "full_text_file_error_filename": "error.details.filename",
        "full_text_file_error_next_action": "error.next_action=repair_input",
        "structured_error_retryable_false": "error.retryable=false",
        "structured_error_category_input_repair": "error.category=input_repair",
        "structured_error_retryable_field": '"retryable": false',
        "structured_error_category_field": '"category": "input_repair"',
        "structured_error_retry_grouping": "Prefer `error.retryable` and `error.category`",
        "structured_error_source_limited_category": "`source_limited` is the category",
        "support_set_example": '"tool": "check_claim_support_set_tool"',
        "support_set_full_text_file_example": "One claim, multiple citations with one user-provided full-text file:",
        "support_set_full_text_file_provenance": "`support_mode_details.full_text_evidence_present`",
        "support_set_full_text_file_scope_warning": "Do not imply that every cited",
        "nested_support_audit_full_text_file_example": "Nested claim-support audit with a full-text file:",
        "nested_support_audit_citation_index": "`error.details.citation_index`",
        "support_audit_reference_file_example": "citeguard support-audit examples/references.md",
        "support_audit_reference_file_bbl_shape": "Markdown/LaTeX/BibTeX/BBL/DOCX",
        "support_audit_reference_file_claim": "same claim to every extracted",
        "latex_external_bib_example": "citeguard extract paper.tex",
        "latex_external_bib_locator": "referenced `.bib` citation item",
        "latex_bbl_example": "citeguard extract paper.bbl",
        "latex_bbl_source_format": "source_format=bbl",
        "latex_bbl_no_existence_proof": "do not treat the `.bbl` as proof",
        "claim_batch_example": '"tool": "audit_claim_support_tool"',
        "claim_batch_counterevidence_high_risk_example": "High-risk claim-support audit with counter-evidence leads:",
        "claim_batch_counterevidence_flag": '"include_counterevidence": true',
        "claim_batch_counterevidence_top_k": '"counterevidence_top_k": 1',
        "claim_batch_counterevidence_high_risk_flag": '"high_risk_only": true',
        "claim_batch_counterevidence_safe_wording": "review lead to inspect, not a contradiction verdict",
        "shape_error_repair_example": "Malformed batch shape repair",
        "structured_shape_error_details": "error.details.expected=list",
        "file_error_repair_example": "Full-text file error repair:",
        "file_error_payload_code": '"code": "file_error"',
        "file_error_payload_filename": '"filename": "/path/to/missing.txt"',
        "file_error_payload_errno": '"errno": 2',
        "file_error_errno_wording": "`errno=2`",
        "file_error_safe_wording": "fetch gated full text or infer full-text",
        "counterevidence_example": '"tool": "search_counterevidence_tool"',
        "ambiguous_wording": "do not choose one match",
        "metadata_mismatch_wording": "ask before editing the user's bibliography",
        "not_found_wording": "not proof that the paper is fabricated",
        "source_outage_wording": "not treat source failure as evidence",
        "review_plan_audit_example": "Review-plan audit for benchmark labeling:",
        "review_plan_next_phase_example": "review_plan.next_phase=first_review_high_risk",
        "review_plan_no_human_benchmark_wording": "Do not describe this seed set as a human-reviewed benchmark.",
        "annotation_scope_payload": '"evidence_scope_assessed": "abstract"',
        "annotation_full_text_needed_payload": '"full_text_needed": "yes"',
        "annotation_scope_safe_wording": "not a final full-text conclusion",
        "support_benchmark_metric_snapshot": "compact metric snapshot",
        "support_benchmark_macro_f1_example": f'"macro_f1": {support_overall["macro_f1"]}',
        "support_benchmark_weighted_f1_example": f'"weighted_f1": {support_overall["weighted_f1"]}',
        "support_benchmark_accuracy_warning": "do not use accuracy alone",
        "false_support_review_plan_status_example": (
            f'`false_support_analysis.review_plan.status={support_review_plan["status"]}`'
        ),
        "false_support_review_plan_phase_example": "`supported_overcall_blockers`",
        "false_support_recommended_packets_example": "recommended_annotation_packets",
        "false_support_annotation_packet_command_example": "annotation_packet.command_template",
        "false_support_top_overcall_review_plan_status_example": (
            "`false_support_top_overcall_review_plan_status`"
        ),
        "false_support_review_plan_flat_status": (
            f'"false_support_review_plan_status": "{support_review_plan["status"]}"'
        ),
        "full_text_boundary_example": "support-label-packet-full-text-required-unreviewed",
        "full_text_boundary_safe_wording": "full-text boundary review is complete",
        "policy_boundary_example": "support-label-packet-policy-boundary-unreviewed",
        "policy_boundary_safe_wording": "policy-boundary review before claiming multi-citation support readiness",
        "compact_table": "Suggested compact result table",
        "compact_table_source_metadata": "source metadata",
        "sparse_metadata_row": "Sparse live-source record",
        "filtered_response_example": "Filtered high-risk response example:",
        "filtered_response_bottom_line": "Bottom line: CiteGuard found 1 high-risk item.",
        "filtered_response_review_queues": "Review queues:",
        "filtered_response_omitted_summary": "filtered.omitted_review_summary",
        "filtered_response_triage_plan": "review_summary.triage_plan.status=review_required",
        "filtered_response_triage_policy": "source_retry_is_inconclusive_not_fabrication",
        "filtered_response_risk_reason": "risk_reason=no_strong_match",
        "filtered_response_suggested_fix": "suggested_fix.kind=add_identifier_or_replace",
        "filtered_response_columns": (
            "| index | source item | citation/claim | verdict | risk | next_action | evidence source | why | next step |"
        ),
        "filtered_response_source_item": "`examples/references.md:6`",
        "filtered_response_line_range_source": "`input_source_line_start` / `input_source_line_end`",
        "filtered_response_scope_note": "It is high-risk, not proof of fabrication.",
        "ambiguous_compact_response_example": "Ambiguous compact response example:",
        "ambiguous_response_next_action": "`disambiguate_identifier`",
        "ambiguous_response_no_silent_choice": "Do not choose one match without",
        "metadata_mismatch_compact_response_example": "Metadata mismatch compact response example:",
        "metadata_mismatch_response_next_action": "`review_metadata`",
        "metadata_mismatch_response_field_diffs": "`field_diffs=year,venue`",
        "metadata_mismatch_requires_confirmation": "`suggested_fix.requires_user_confirmation=true`",
    }
    required_agent_phrases = {
        "display_name": 'display_name: "CiteGuard Verify"',
        "default_prompt": "default_prompt:",
        "mcp_dependency": 'type: "mcp"',
        "stdio_transport": 'transport: "stdio"',
        "implicit_invocation": "allow_implicit_invocation: true",
    }

    missing = []
    missing.extend(_missing_contract_phrases(skill, required_skill_phrases, "SKILL.md"))
    missing.extend(_missing_contract_phrases(examples, required_example_phrases, "references/examples.md"))
    missing.extend(_missing_contract_phrases(openai_agent, required_agent_phrases, "agents/openai.yaml"))
    if missing:
        raise RuntimeError("; ".join(missing))

    return {
        "skill_file": "skills/citeguard-verify/SKILL.md",
        "examples_file": "skills/citeguard-verify/references/examples.md",
        "agent_metadata_file": "skills/citeguard-verify/agents/openai.yaml",
        "checked_contracts": {
            "trigger_count": 3,
            "forbidden_behavior_count": 3,
            "client_setup_count": 3,
            "tool_example_count": 10,
            "support_audit_reference_file_example_count": 1,
            "structured_error_example_count": 1,
            "file_error_example_count": 1,
            "safe_wording_example_count": 7,
            "full_text_support_payload_example_count": 1,
            "full_text_file_support_payload_example_count": 3,
            "full_text_boundary_example_count": 1,
            "policy_boundary_example_count": 1,
            "source_health_confidence_contract_count": 1,
            "review_plan_example_count": 1,
            "annotation_scope_provenance_example_count": 1,
            "pre_response_safety_check_count": 5,
            "presentation_example_count": 1,
            "scenario_response_example_count": 2,
            "line_range_traceability_count": 1,
        },
        "policy": "agent skill must proactively audit citations without silent edits or source-outage fabrication overclaims",
    }


def _missing_contract_phrases(text: str, required: Dict[str, str], label: str) -> List[str]:
    return [
        f"{label} missing {name}: {phrase}"
        for name, phrase in required.items()
        if phrase not in text
    ]


def _record_batch_workflow_examples_gate(summary: Dict[str, Any], *, python: str, project_root: Path) -> None:
    try:
        details = _check_batch_workflow_examples_gate(python=python, project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "batch_workflow_examples",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "batch_workflow_examples",
            "status": "passed",
            **details,
        }
    )


def _check_batch_workflow_examples_gate(*, python: str, project_root: Path) -> Dict[str, Any]:
    fixture_path = project_root / "examples" / "citations.json"
    with open(fixture_path, encoding="utf-8") as fixture_handle:
        combined_fixture_records = json.load(fixture_handle)
    combined_fixture_records.append(
        {
            "title": "Release Gate Sparse Source Metadata",
            "authors": ["Ada Lovelace"],
            "year": 2026,
            "doi": "10.5555/release-sparse",
            "source": "release_sparse_fixture",
            "metadata": {
                "metadata_quality": {
                    "schema_version": 1,
                    "present_fields": ["title", "authors", "year", "identifier"],
                    "missing_fields": ["venue", "abstract", "url"],
                    "identifiers": {"doi": True, "arxiv_id": False},
                    "completeness": 0.5714,
                    "confidence_effect": "missing_metadata_lowers_confidence_not_fabrication_evidence",
                }
            },
        }
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(combined_fixture_records, handle)
        combined_fixture_path = handle.name
    env = {
        "CITEGUARD_FIXTURE_CITATIONS": combined_fixture_path,
        "CITEGUARD_RERANKER_MODEL": "",
        "CITEGUARD_NLI_MODEL": "",
        "TOKENIZERS_PARALLELISM": "false",
    }
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(
            [
                {
                    "title": "Attention Is All You Need",
                    "authors": ["Ashish Vaswani"],
                    "year": 2020,
                    "venue": "Journal of Imaginary Methods",
                    "arxiv_id": "1706.03762",
                }
            ],
            handle,
        )
        mismatch_path = handle.name
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(
            [
                {
                    "title": "Release Gate Sparse Source Metadata",
                    "authors": ["Ada Lovelace"],
                    "year": 2026,
                    "doi": "10.5555/release-sparse",
                }
            ],
            handle,
        )
        sparse_metadata_path = handle.name
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(
            [
                {
                    "claim": "Sparse source metadata improves audits.",
                    "title": "Release Gate Sparse Source Metadata",
                    "authors": ["Ada Lovelace"],
                    "year": 2026,
                    "doi": "10.5555/release-sparse",
                }
            ],
            handle,
        )
        support_sparse_metadata_path = handle.name
    latex_bib_dir = tempfile.TemporaryDirectory()
    latex_bib_root = Path(latex_bib_dir.name)
    latex_bib_tex_path = latex_bib_root / "paper.tex"
    latex_refs_tex_path = latex_bib_root / "references.tex"
    latex_bib_path = latex_bib_root / "refs.bib"
    latex_bbl_path = latex_bib_root / "paper.bbl"
    pasted_refs_path = latex_bib_root / "pasted-refs.txt"
    unnumbered_refs_path = latex_bib_root / "unnumbered-refs.txt"
    docx_refs_path = latex_bib_root / "references.docx"
    latex_bib_tex_path.write_text(
        r"""
        \documentclass{article}
        \begin{document}
        Attention mechanisms are cited here \cite{vaswani2017}.
        \input{references}
        \end{document}
        """,
        encoding="utf-8",
    )
    latex_refs_tex_path.write_text(r"\bibliography{refs}", encoding="utf-8")
    latex_bib_path.write_text(
        r"""
        @string(nipsconf = {NeurIPS})

        @article(vaswani2017,
          title={Attention} # {{Is} All You Need},
          author={Vaswani, Ashish and Shazeer, Noam},
          journal=nipsconf,
          year={2017},
          eprint={1706.03762}
        )
        """,
        encoding="utf-8",
    )
    latex_bbl_path.write_text(
        r"""
        \begin{thebibliography}{1}
        \bibitem{vaswani2017} Vaswani, A. et al. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.
        \end{thebibliography}
        """,
        encoding="utf-8",
    )
    pasted_refs_path.write_text(
        "\n".join(
            [
                "1. Vaswani, A. et al. Attention Is All You Need.",
                "   Advances in Neural Information Processing Systems, 2017. arXiv:1706.03762.",
                "2. Xu, Zhe and Wang, Lin. GhostCite: A Large-Scale Analysis of Citation Validity.",
                "   arXiv, 2026. DOI: 10.48550/arxiv.2602.06718.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    unnumbered_refs_path.write_text(
        "\n".join(
            [
                "Vaswani, A. et al. Attention Is All You Need. Advances in Neural Information Processing Systems, 2017. arXiv:1706.03762.",
                "Xu, Zhe and Wang, Lin. GhostCite: A Large-Scale Analysis of Citation Validity. arXiv, 2026. DOI: 10.48550/arxiv.2602.06718.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    with zipfile.ZipFile(docx_refs_path, "w") as archive:
        archive.writestr(
            "word/document.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body>
                <w:p><w:r><w:t>References</w:t></w:r></w:p>
                <w:p><w:r><w:t>1. Vaswani, A. et al. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.</w:t></w:r></w:p>
                <w:p><w:r><w:t>2. Quantum Teleportation of Citation Hallucinations in Synthetic Benchmarks. Journal of Imaginary Methods, 2024.</w:t></w:r></w:p>
              </w:body>
            </w:document>
            """,
        )

    try:
        commands = {
            "extract_references": [python, "-m", "citeguard", "extract", "examples/references.md", "--compact"],
            "extract_latex_bibliography": [
                python,
                "-m",
                "citeguard",
                "extract",
                str(latex_bib_tex_path),
                "--compact",
            ],
            "extract_latex_bbl": [
                python,
                "-m",
                "citeguard",
                "extract",
                str(latex_bbl_path),
                "--compact",
            ],
            "extract_pasted_reference_list": [
                python,
                "-m",
                "citeguard",
                "extract",
                str(pasted_refs_path),
                "--compact",
            ],
            "extract_unnumbered_reference_list": [
                python,
                "-m",
                "citeguard",
                "extract",
                str(unnumbered_refs_path),
                "--compact",
            ],
            "extract_docx_reference_list": [
                python,
                "-m",
                "citeguard",
                "extract",
                str(docx_refs_path),
                "--compact",
            ],
            "audit_json": [python, "-m", "citeguard", "audit", "examples/citations.json", "--compact"],
            "audit_latex_bibliography": [
                python,
                "-m",
                "citeguard",
                "audit",
                str(latex_bib_tex_path),
                "--compact",
            ],
            "audit_jsonl_high_risk": [
                python,
                "-m",
                "citeguard",
                "audit",
                "examples/citations.jsonl",
                "--high-risk-only",
                "--compact",
            ],
            "audit_metadata_mismatch": [python, "-m", "citeguard", "audit", mismatch_path, "--compact"],
            "audit_sparse_metadata_quality": [
                python,
                "-m",
                "citeguard",
                "audit",
                sparse_metadata_path,
                "--compact",
            ],
            "audit_markdown_high_risk": [
                python,
                "-m",
                "citeguard",
                "audit",
                "examples/references.md",
                "--high-risk-only",
                "--compact",
            ],
            "audit_docx_high_risk": [
                python,
                "-m",
                "citeguard",
                "audit",
                str(docx_refs_path),
                "--high-risk-only",
                "--compact",
            ],
            "support_audit_json": [
                python,
                "-m",
                "citeguard",
                "support-audit",
                "examples/claim_citations.json",
                "--compact",
            ],
            "support_audit_jsonl_high_risk": [
                python,
                "-m",
                "citeguard",
                "support-audit",
                "examples/claim_citations.jsonl",
                "--high-risk-only",
                "--compact",
            ],
            "support_audit_full_text_json": [
                python,
                "-m",
                "citeguard",
                "support-audit",
                "examples/claim_citations_full_text.json",
                "--compact",
            ],
            "support_audit_full_text_file_json": [
                python,
                "-m",
                "citeguard",
                "support-audit",
                "examples/claim_citations_full_text_file.json",
                "--compact",
            ],
            "support_audit_markdown": [
                python,
                "-m",
                "citeguard",
                "support-audit",
                "examples/references.md",
                "--claim",
                "The Transformer relies entirely on attention mechanisms.",
                "--compact",
            ],
            "support_audit_markdown_high_risk": [
                python,
                "-m",
                "citeguard",
                "support-audit",
                "examples/references.md",
                "--claim",
                "The Transformer relies entirely on attention mechanisms.",
                "--high-risk-only",
                "--compact",
            ],
            "support_audit_markdown_counterevidence": [
                python,
                "-m",
                "citeguard",
                "support-audit",
                "examples/references.md",
                "--claim",
                "The Transformer relies entirely on attention mechanisms.",
                "--with-counterevidence",
                "--compact",
            ],
            "support_audit_docx_high_risk": [
                python,
                "-m",
                "citeguard",
                "support-audit",
                str(docx_refs_path),
                "--claim",
                "The Transformer relies entirely on attention mechanisms.",
                "--high-risk-only",
                "--compact",
            ],
            "support_audit_counterevidence": [
                python,
                "-m",
                "citeguard",
                "support-audit",
                "examples/claim_citations.json",
                "--with-counterevidence",
                "--compact",
            ],
            "support_audit_sparse_metadata_quality": [
                python,
                "-m",
                "citeguard",
                "support-audit",
                support_sparse_metadata_path,
                "--compact",
            ],
            "support_set": [
                python,
                "-m",
                "citeguard",
                "support-set",
                "examples/citations.json",
                "--claim",
                "The Transformer relies entirely on attention mechanisms.",
                "--compact",
            ],
            "support_set_counterevidence": [
                python,
                "-m",
                "citeguard",
                "support-set",
                "examples/citations.json",
                "--claim",
                "The Transformer relies entirely on attention mechanisms.",
                "--with-counterevidence",
                "--compact",
            ],
            "support_set_markdown": [
                python,
                "-m",
                "citeguard",
                "support-set",
                "examples/references.md",
                "--claim",
                "The Transformer relies entirely on attention mechanisms.",
                "--compact",
            ],
            "support_set_docx": [
                python,
                "-m",
                "citeguard",
                "support-set",
                str(docx_refs_path),
                "--claim",
                "The Transformer relies entirely on attention mechanisms.",
                "--compact",
            ],
        }
        help_commands = {
            "audit_help": [python, "-m", "citeguard", "audit", "--help"],
            "support_set_help": [python, "-m", "citeguard", "support-set", "--help"],
            "support_audit_help": [python, "-m", "citeguard", "support-audit", "--help"],
        }
        payloads = {
            name: _run_json_command(command, cwd=project_root, env_overrides=env)
            for name, command in commands.items()
        }
        help_texts = {
            name: _run_text_command(command, cwd=project_root, env_overrides=env)
            for name, command in help_commands.items()
        }
    finally:
        Path(combined_fixture_path).unlink(missing_ok=True)
        Path(mismatch_path).unlink(missing_ok=True)
        Path(sparse_metadata_path).unlink(missing_ok=True)
        Path(support_sparse_metadata_path).unlink(missing_ok=True)
        latex_bib_dir.cleanup()

    extract_payload = payloads["extract_references"]
    latex_bib_extract = payloads["extract_latex_bibliography"]
    latex_bbl_extract = payloads["extract_latex_bbl"]
    pasted_reference_extract = payloads["extract_pasted_reference_list"]
    unnumbered_reference_extract = payloads["extract_unnumbered_reference_list"]
    docx_reference_extract = payloads["extract_docx_reference_list"]
    audit_payload = payloads["audit_json"]
    audit_latex_bibliography = payloads["audit_latex_bibliography"]
    audit_jsonl_filtered = payloads["audit_jsonl_high_risk"]
    audit_mismatch = payloads["audit_metadata_mismatch"]
    audit_sparse_metadata_quality = payloads["audit_sparse_metadata_quality"]
    audit_filtered = payloads["audit_markdown_high_risk"]
    audit_docx_filtered = payloads["audit_docx_high_risk"]
    support_payload = payloads["support_audit_json"]
    support_filtered = payloads["support_audit_jsonl_high_risk"]
    support_full_text = payloads["support_audit_full_text_json"]
    support_full_text_file = payloads["support_audit_full_text_file_json"]
    support_markdown = payloads["support_audit_markdown"]
    support_markdown_filtered = payloads["support_audit_markdown_high_risk"]
    support_markdown_counterevidence = payloads["support_audit_markdown_counterevidence"]
    support_docx_filtered = payloads["support_audit_docx_high_risk"]
    support_counterevidence = payloads["support_audit_counterevidence"]
    support_sparse_metadata_quality = payloads["support_audit_sparse_metadata_quality"]
    support_set = payloads["support_set"]
    support_set_counterevidence = payloads["support_set_counterevidence"]
    support_set_markdown = payloads["support_set_markdown"]
    support_set_docx = payloads["support_set_docx"]

    errors = []

    def require_suggested_fix_summary(
        summary_payload: Dict[str, Any],
        *,
        label: str,
        confirmation_required_indexes: List[int],
        no_confirmation_required_indexes: List[int],
        fix_kind_indexes: Dict[str, List[int]],
    ) -> Dict[str, Any]:
        fix_summary = summary_payload.get("suggested_fix_summary", {})
        if fix_summary.get("schema_version") != 1:
            errors.append(f"{label} should expose review_summary.suggested_fix_summary schema_version=1")
        if fix_summary.get("auto_apply_allowed") is not False:
            errors.append(f"{label} should set suggested_fix_summary.auto_apply_allowed=false")
        if "must_not_silently_apply" not in str(fix_summary.get("policy", "")):
            errors.append(f"{label} should preserve no-silent-apply suggested fix policy")
        if fix_summary.get("confirmation_required_indexes") != confirmation_required_indexes:
            errors.append(
                f"{label} should preserve confirmation_required_indexes={confirmation_required_indexes}"
            )
        if fix_summary.get("confirmation_required_count") != len(confirmation_required_indexes):
            errors.append(f"{label} should preserve confirmation_required_count")
        if fix_summary.get("no_confirmation_required_indexes") != no_confirmation_required_indexes:
            errors.append(
                f"{label} should preserve no_confirmation_required_indexes={no_confirmation_required_indexes}"
            )
        if fix_summary.get("missing_suggested_fix_indexes") != []:
            errors.append(f"{label} should report no missing suggested fixes in release fixtures")
        observed_kind_indexes = fix_summary.get("fix_kind_indexes", {})
        observed_kind_counts = fix_summary.get("fix_kind_counts", {})
        for kind, indexes in fix_kind_indexes.items():
            if observed_kind_indexes.get(kind) != indexes:
                errors.append(f"{label} should preserve suggested fix indexes for {kind}")
            if observed_kind_counts.get(kind) != len(indexes):
                errors.append(f"{label} should preserve suggested fix count for {kind}")
        return fix_summary

    for name, help_text in help_texts.items():
        if "JSON/JSONL" not in help_text:
            errors.append(f"{name} should document JSONL batch input")
        if "Markdown/LaTeX/BibTeX/BBL/DOCX/plain-text" not in help_text:
            errors.append(f"{name} should document extracted reference-file input")
    if not isinstance(extract_payload, list) or len(extract_payload) != 2:
        errors.append("extract examples/references.md should return two citation candidates")
    elif extract_payload[0].get("arxiv_id") != "1706.03762":
        errors.append("extract examples/references.md should preserve the arXiv id")
    else:
        if extract_payload[0].get("source_path") != "examples/references.md":
            errors.append("extract examples/references.md should expose source_path")
        if extract_payload[0].get("source_format") != "markdown":
            errors.append("extract examples/references.md should expose source_format=markdown")
        if extract_payload[0].get("source_index") != 1:
            errors.append("extract examples/references.md should expose one-based source_index")
        if extract_payload[0].get("source_locator") != "examples/references.md#citation-1":
            errors.append("extract examples/references.md should expose source_locator")
        if extract_payload[0].get("source_line_start") != 5 or extract_payload[0].get("source_line_end") != 5:
            errors.append("extract examples/references.md should expose source_line_start/source_line_end")

    if not isinstance(latex_bib_extract, list) or len(latex_bib_extract) != 1:
        errors.append("extract LaTeX bibliography fixture should return one BibTeX candidate")
    else:
        latex_bib_item = latex_bib_extract[0]
        if latex_bib_item.get("source_path") != str(latex_bib_path):
            errors.append("extract LaTeX bibliography should expose the referenced .bib source_path")
        if latex_bib_item.get("source_format") != "bibtex":
            errors.append("extract LaTeX bibliography should expose source_format=bibtex")
        if latex_bib_item.get("source_locator") != f"{latex_bib_path}#citation-1":
            errors.append("extract LaTeX bibliography should expose the referenced .bib source_locator")
        if latex_bib_item.get("source_id") != "vaswani2017":
            errors.append("extract LaTeX bibliography should preserve the BibTeX key as source_id")
        if latex_bib_item.get("title") != "Attention Is All You Need":
            errors.append("extract LaTeX bibliography should parse parenthesized concatenated nested-brace BibTeX titles")
        if "NeurIPS" not in str(latex_bib_item.get("raw_text", "")) or "nipsconf" in str(
            latex_bib_item.get("raw_text", "")
        ):
            errors.append("extract LaTeX bibliography should expand BibTeX @string macros in raw_text")
        if latex_bib_item.get("year") != 2017:
            errors.append("extract LaTeX bibliography should preserve the BibTeX year")

    if not isinstance(latex_bbl_extract, list) or len(latex_bbl_extract) != 1:
        errors.append("extract LaTeX BBL fixture should return one bibitem candidate")
    else:
        latex_bbl_item = latex_bbl_extract[0]
        if latex_bbl_item.get("source_path") != str(latex_bbl_path):
            errors.append("extract LaTeX BBL should expose the .bbl source_path")
        if latex_bbl_item.get("source_format") != "bbl":
            errors.append("extract LaTeX BBL should expose source_format=bbl")
        if latex_bbl_item.get("source_locator") != f"{latex_bbl_path}#citation-1":
            errors.append("extract LaTeX BBL should expose source_locator")
        if latex_bbl_item.get("source_id") != "vaswani2017":
            errors.append("extract LaTeX BBL should preserve the bibitem key as source_id")
        if latex_bbl_item.get("arxiv_id") != "1706.03762":
            errors.append("extract LaTeX BBL should parse arXiv id from bibitem")

    if not isinstance(pasted_reference_extract, list) or len(pasted_reference_extract) != 2:
        errors.append("extract pasted reference list should return two citation candidates without a References heading")
    else:
        pasted_item = pasted_reference_extract[0]
        if pasted_item.get("source_type") != "reference_list":
            errors.append("extract pasted reference list should expose source_type=reference_list")
        if pasted_item.get("source_format") != "text":
            errors.append("extract pasted reference list should expose source_format=text")
        if pasted_item.get("source_path") != str(pasted_refs_path):
            errors.append("extract pasted reference list should expose source_path")
        if pasted_item.get("source_locator") != f"{pasted_refs_path}#citation-1":
            errors.append("extract pasted reference list should expose source_locator")
        if pasted_item.get("source_line_start") != 1 or pasted_item.get("source_line_end") != 2:
            errors.append("extract pasted reference list should expose wrapped source line range")
        if pasted_item.get("arxiv_id") != "1706.03762":
            errors.append("extract pasted reference list should preserve arXiv identifiers")
        if "Advances in Neural Information Processing Systems" not in str(pasted_item.get("raw_text", "")):
            errors.append("extract pasted reference list should merge indented continuation lines")

    if not isinstance(unnumbered_reference_extract, list) or len(unnumbered_reference_extract) != 2:
        errors.append("extract unnumbered pasted reference list should return two citation candidates")
    else:
        unnumbered_item = unnumbered_reference_extract[0]
        if unnumbered_item.get("source_type") != "reference_list":
            errors.append("extract unnumbered pasted reference list should expose source_type=reference_list")
        if unnumbered_item.get("source_format") != "text":
            errors.append("extract unnumbered pasted reference list should expose source_format=text")
        if unnumbered_item.get("source_path") != str(unnumbered_refs_path):
            errors.append("extract unnumbered pasted reference list should expose source_path")
        if unnumbered_item.get("source_locator") != f"{unnumbered_refs_path}#citation-1":
            errors.append("extract unnumbered pasted reference list should expose source_locator")
        if unnumbered_item.get("source_line_start") != 1 or unnumbered_item.get("source_line_end") != 1:
            errors.append("extract unnumbered pasted reference list should expose source line range")
        if unnumbered_item.get("arxiv_id") != "1706.03762":
            errors.append("extract unnumbered pasted reference list should preserve arXiv identifiers")

    if not isinstance(docx_reference_extract, list) or len(docx_reference_extract) != 2:
        errors.append("extract DOCX reference list should return two citation candidates")
    else:
        docx_item = docx_reference_extract[0]
        if docx_item.get("source_type") != "reference_section":
            errors.append("extract DOCX reference list should expose source_type=reference_section")
        if docx_item.get("source_format") != "docx":
            errors.append("extract DOCX reference list should expose source_format=docx")
        if docx_item.get("source_path") != str(docx_refs_path):
            errors.append("extract DOCX reference list should expose source_path")
        if docx_item.get("source_locator") != f"{docx_refs_path}#citation-1":
            errors.append("extract DOCX reference list should expose source_locator")
        if docx_item.get("source_line_start") != 2 or docx_item.get("source_line_end") != 2:
            errors.append("extract DOCX reference list should expose paragraph-derived source line range")
        if docx_item.get("arxiv_id") != "1706.03762":
            errors.append("extract DOCX reference list should preserve arXiv identifiers")

    if audit_payload.get("summary", {}).get("verified") != 1 or audit_payload.get("summary", {}).get("not_found") != 1:
        errors.append("audit examples/citations.json should produce one verified and one not_found item")
    if audit_latex_bibliography.get("summary", {}).get("verified") != 1:
        errors.append("audit LaTeX bibliography fixture should verify the referenced .bib citation")
    audit_latex_risk = audit_latex_bibliography.get("risk_ranking", [{}])[0]
    if audit_latex_risk.get("input_source_path") != str(latex_bib_path):
        errors.append("audit LaTeX bibliography risk ranking should expose the referenced .bib source_path")
    if audit_latex_risk.get("input_source_format") != "bibtex":
        errors.append("audit LaTeX bibliography risk ranking should expose input_source_format=bibtex")
    if audit_latex_risk.get("input_source_locator") != f"{latex_bib_path}#citation-1":
        errors.append("audit LaTeX bibliography risk ranking should expose the referenced .bib source_locator")
    audit_review = audit_payload.get("review_summary", {})
    audit_source_traceability = audit_review.get("source_traceability", {})
    if audit_review.get("high_risk_count") != 1:
        errors.append("audit examples/citations.json should expose one high-risk item")
    if audit_source_traceability.get("schema_version") != 1:
        errors.append("audit examples/citations.json should expose review_summary.source_traceability schema_version=1")
    if audit_source_traceability.get("has_source_backed_items") is not False:
        errors.append("audit examples/citations.json should report no source-backed review_summary rows")
    if audit_source_traceability.get("source_indexes") != []:
        errors.append("audit examples/citations.json should expose empty source_indexes for JSON batch input")
    if audit_review.get("action_queues", {}).get("identity_resolution_indexes") != [1]:
        errors.append("audit examples/citations.json should queue the unresolved citation for identity resolution")
    if audit_review.get("recommended_next_steps", {}).get("first_queue") != "identity_resolution_indexes":
        errors.append("audit examples/citations.json should expose identity resolution as the first recommended next step")
    audit_suggested_fix_summary = require_suggested_fix_summary(
        audit_review,
        label="audit examples/citations.json",
        confirmation_required_indexes=[1],
        no_confirmation_required_indexes=[0],
        fix_kind_indexes={
            "add_identifier_or_replace": [1],
            "keep": [0],
        },
    )
    audit_triage_plan = audit_review.get("triage_plan", {})
    if audit_triage_plan.get("schema_version") != 1:
        errors.append("audit examples/citations.json should expose review_summary.triage_plan schema_version=1")
    if audit_triage_plan.get("status") != "review_required":
        errors.append("audit examples/citations.json should mark triage_plan.status=review_required")
    if audit_triage_plan.get("first_queue") != "identity_resolution_indexes":
        errors.append("audit examples/citations.json should expose identity resolution as triage_plan.first_queue")
    if audit_triage_plan.get("review_required_indexes") != [1]:
        errors.append("audit examples/citations.json triage_plan should preserve review-required index 1")
    if audit_triage_plan.get("high_risk_indexes") != [1]:
        errors.append("audit examples/citations.json triage_plan should preserve high-risk index 1")
    if "source_retry_is_inconclusive_not_fabrication" not in str(audit_triage_plan.get("policy", "")):
        errors.append("audit triage_plan should preserve source-retry safety policy")
    if audit_payload.get("risk_ranking", [{}])[0].get("next_action") != "resolve_identifier_or_replace":
        errors.append("audit risk ranking should expose resolve_identifier_or_replace")
    if audit_payload.get("risk_ranking", [{}])[0].get("risk_reason") != "no_strong_match":
        errors.append("audit risk ranking should expose risk_reason=no_strong_match")
    audit_top_fix = audit_payload.get("risk_ranking", [{}])[0].get("suggested_fix", {})
    if audit_top_fix.get("kind") != "add_identifier_or_replace":
        errors.append("audit risk ranking should expose suggested_fix.kind=add_identifier_or_replace")
    if audit_top_fix.get("requires_user_confirmation") is not True:
        errors.append("audit not_found suggested_fix should require user confirmation")
    if audit_top_fix.get("policy") != "not_found_is_high_risk_not_fabrication_proof":
        errors.append("audit not_found suggested_fix should preserve no-fabrication policy")
    if audit_jsonl_filtered.get("filtered", {}).get("high_risk_only") is not True:
        errors.append("audit JSONL high-risk run should include filtered.high_risk_only=true")
    if audit_jsonl_filtered.get("filtered", {}).get("returned_indexes") != [1]:
        errors.append("audit JSONL high-risk run should preserve returned index 1")
    audit_jsonl_omitted = audit_jsonl_filtered.get("filtered", {}).get("omitted_review_summary", {})
    if audit_jsonl_omitted.get("low_risk_count") != 1:
        errors.append("audit JSONL high-risk run should summarize one omitted low-risk row")
    if audit_jsonl_omitted.get("action_queues", {}).get("safe_to_keep_indexes") != [0]:
        errors.append("audit JSONL high-risk run should preserve omitted safe-to-keep index")
    if audit_jsonl_omitted.get("recommended_next_steps", {}).get("safe_to_keep_indexes") != [0]:
        errors.append("audit JSONL high-risk run should preserve omitted safe-to-keep recommended step")
    require_suggested_fix_summary(
        audit_jsonl_omitted,
        label="audit JSONL high-risk omitted rows",
        confirmation_required_indexes=[],
        no_confirmation_required_indexes=[0],
        fix_kind_indexes={"keep": [0]},
    )
    if len(audit_jsonl_filtered.get("results", [])) != 1:
        errors.append("audit JSONL high-risk run should return one high-risk result")
    mismatch_risk = audit_mismatch.get("risk_ranking", [{}])[0]
    if mismatch_risk.get("verdict") != "metadata_mismatch":
        errors.append("audit metadata mismatch fixture should produce metadata_mismatch")
    if mismatch_risk.get("next_action") != "review_metadata":
        errors.append("audit metadata mismatch risk ranking should expose review_metadata")
    if mismatch_risk.get("risk_reason") != "metadata_fields_mismatch":
        errors.append("audit metadata mismatch risk ranking should expose risk_reason=metadata_fields_mismatch")
    if mismatch_risk.get("suggested_fix", {}).get("kind") != "review_metadata_correction":
        errors.append("audit metadata mismatch risk ranking should expose suggested_fix.kind=review_metadata_correction")
    if mismatch_risk.get("suggested_fix", {}).get("mismatched_fields") != ["year", "venue"]:
        errors.append("audit metadata mismatch suggested_fix should expose mismatched_fields")
    if mismatch_risk.get("mismatched_fields") != ["year", "venue"]:
        errors.append("audit metadata mismatch risk ranking should expose mismatched_fields")
    if not mismatch_risk.get("suggested_citation"):
        errors.append("audit metadata mismatch risk ranking should expose suggested_citation")
    if mismatch_risk.get("canonical_year") != 2017 or mismatch_risk.get("canonical_arxiv_id") != "1706.03762":
        errors.append("audit metadata mismatch risk ranking should expose canonical identifiers")
    sparse_quality_risk = audit_sparse_metadata_quality.get("risk_ranking", [{}])[0]
    if sparse_quality_risk.get("source_metadata_missing_fields") != ["venue", "abstract", "url"]:
        errors.append("audit risk ranking should flatten source_metadata_missing_fields")
    if (
        sparse_quality_risk.get("source_metadata_confidence_effect")
        != "missing_metadata_lowers_confidence_not_fabrication_evidence"
    ):
        errors.append("audit risk ranking should expose source_metadata_confidence_effect")
    if sparse_quality_risk.get("canonical_metadata_quality", {}).get("identifiers", {}).get("doi") is not True:
        errors.append("audit risk ranking should preserve canonical_metadata_quality identifier provenance")

    if audit_filtered.get("filtered", {}).get("high_risk_only") is not True:
        errors.append("audit markdown high-risk run should include filtered.high_risk_only=true")
    if audit_filtered.get("filtered", {}).get("returned_indexes") != [1]:
        errors.append("audit markdown high-risk run should preserve returned index 1")
    if len(audit_filtered.get("results", [])) != 1:
        errors.append("audit markdown high-risk run should return one result")
    audit_filtered_risk = audit_filtered.get("risk_ranking", [{}])[0]
    audit_markdown_source_traceability = audit_filtered.get("review_summary", {}).get("source_traceability", {})
    if audit_filtered_risk.get("input_source_path") != "examples/references.md":
        errors.append("audit markdown risk ranking should expose input_source_path")
    if audit_filtered_risk.get("input_source_locator") != "examples/references.md#citation-2":
        errors.append("audit markdown risk ranking should expose extracted input_source_locator")
    if audit_filtered_risk.get("input_source_line_start") != 6 or audit_filtered_risk.get("input_source_line_end") != 6:
        errors.append("audit markdown risk ranking should expose extracted input source line range")
    if audit_markdown_source_traceability.get("has_source_backed_items") is not True:
        errors.append("audit markdown high-risk run should expose source-backed review_summary traceability")
    if audit_markdown_source_traceability.get("source_paths") != ["examples/references.md"]:
        errors.append("audit markdown high-risk run should summarize source_paths")
    if audit_markdown_source_traceability.get("source_formats") != ["markdown"]:
        errors.append("audit markdown high-risk run should summarize source_formats")
    if audit_markdown_source_traceability.get("source_indexes") != [1, 2]:
        errors.append("audit markdown high-risk run should preserve sorted extracted source indexes")
    if audit_markdown_source_traceability.get("high_risk_source_indexes") != [2]:
        errors.append("audit markdown high-risk run should summarize high-risk source indexes")
    if audit_markdown_source_traceability.get("review_required_source_indexes") != [2]:
        errors.append("audit markdown high-risk run should summarize review-required source indexes")
    if "examples/references.md#citation-2" not in audit_markdown_source_traceability.get(
        "review_required_source_locators", []
    ):
        errors.append("audit markdown high-risk run should summarize review-required source locators")
    if audit_docx_filtered.get("filtered", {}).get("high_risk_only") is not True:
        errors.append("audit DOCX high-risk run should include filtered.high_risk_only=true")
    if audit_docx_filtered.get("summary", {}).get("verified") != 1:
        errors.append("audit DOCX high-risk run should verify the fixture-backed first citation")
    if audit_docx_filtered.get("filtered", {}).get("returned_indexes") != [1]:
        errors.append("audit DOCX high-risk run should preserve returned index 1")
    audit_docx_risk = audit_docx_filtered.get("risk_ranking", [{}])[0]
    audit_docx_source_traceability = audit_docx_filtered.get("review_summary", {}).get("source_traceability", {})
    audit_docx_omitted_source_traceability = (
        audit_docx_filtered.get("filtered", {}).get("omitted_review_summary", {}).get("source_traceability", {})
    )
    if audit_docx_risk.get("input_source_format") != "docx":
        errors.append("audit DOCX risk ranking should expose input_source_format=docx")
    if audit_docx_risk.get("input_source_locator") != f"{docx_refs_path}#citation-2":
        errors.append("audit DOCX risk ranking should expose extracted input_source_locator")
    if audit_docx_risk.get("input_source_line_start") != 3 or audit_docx_risk.get("input_source_line_end") != 3:
        errors.append("audit DOCX risk ranking should expose paragraph-derived line range")
    if audit_docx_source_traceability.get("source_paths") != [str(docx_refs_path)]:
        errors.append("audit DOCX high-risk run should summarize source_paths")
    if audit_docx_source_traceability.get("source_formats") != ["docx"]:
        errors.append("audit DOCX high-risk run should summarize source_formats")
    if audit_docx_source_traceability.get("source_indexes") != [1, 2]:
        errors.append("audit DOCX high-risk run should preserve sorted extracted source indexes")
    if audit_docx_source_traceability.get("high_risk_source_indexes") != [2]:
        errors.append("audit DOCX high-risk run should summarize high-risk source indexes")
    if audit_docx_omitted_source_traceability.get("source_indexes") != [1]:
        errors.append("audit DOCX high-risk run should preserve omitted safe source indexes")

    if support_payload.get("summary", {}).get("insufficient_evidence") != 3:
        errors.append("support-audit examples/claim_citations.json should report three insufficient_evidence items")
    support_review = support_payload.get("review_summary", {})
    support_source_traceability = support_review.get("source_traceability", {})
    if support_review.get("high_risk_count") != 1 or support_review.get("medium_risk_count") != 2:
        errors.append("support-audit examples/claim_citations.json should expose one high and two medium risk items")
    if support_source_traceability.get("schema_version") != 1:
        errors.append("support-audit examples/claim_citations.json should expose source_traceability schema_version=1")
    if support_source_traceability.get("has_source_backed_items") is not False:
        errors.append("support-audit examples/claim_citations.json should report no source-backed rows")
    if support_review.get("action_queues", {}).get("identity_resolution_indexes") != [1]:
        errors.append("support-audit should queue unresolved citations for identity resolution")
    if support_review.get("recommended_next_steps", {}).get("first_queue") != "identity_resolution_indexes":
        errors.append("support-audit should expose identity resolution as the first recommended next step")
    support_suggested_fix_summary = require_suggested_fix_summary(
        support_review,
        label="support-audit examples/claim_citations.json",
        confirmation_required_indexes=[1, 2, 0],
        no_confirmation_required_indexes=[],
        fix_kind_indexes={
            "resolve_citation_identity": [1],
            "inspect_full_text_or_find_stronger_citation": [2, 0],
        },
    )
    support_triage_plan = support_review.get("triage_plan", {})
    if support_triage_plan.get("schema_version") != 1:
        errors.append("support-audit should expose review_summary.triage_plan schema_version=1")
    if support_triage_plan.get("status") != "review_required":
        errors.append("support-audit should mark triage_plan.status=review_required")
    if support_triage_plan.get("first_queue") != "identity_resolution_indexes":
        errors.append("support-audit should expose identity resolution as triage_plan.first_queue")
    if support_triage_plan.get("review_required_indexes") != [1, 2, 0]:
        errors.append("support-audit triage_plan should preserve priority-ordered review-required indexes")
    if support_triage_plan.get("high_risk_indexes") != [1]:
        errors.append("support-audit triage_plan should preserve high-risk index 1")
    support_results = support_payload.get("results", [])
    if len(support_results) != 3 or support_results[2].get("input_mode") != "citation_set":
        errors.append("support-audit should preserve citation_set batch item shape")
    support_risk = support_payload.get("risk_ranking", [{}])[0]
    if support_risk.get("support_confidence") != 0.0:
        errors.append("support-audit risk ranking should expose support_confidence")
    if support_risk.get("support_engine") != "none":
        errors.append("support-audit risk ranking should expose support_engine")
    if support_risk.get("resolution_verdict") != "not_found":
        errors.append("support-audit risk ranking should expose resolution_verdict")
    if support_risk.get("risk_reason") != "citation_identity_unresolved":
        errors.append("support-audit risk ranking should expose risk_reason=citation_identity_unresolved")
    if support_risk.get("suggested_fix", {}).get("kind") != "resolve_citation_identity":
        errors.append("support-audit risk ranking should expose suggested_fix.kind=resolve_citation_identity")
    if support_risk.get("suggested_fix", {}).get("policy") != "resolve_identity_before_judging_support":
        errors.append("support-audit unresolved citation suggested_fix should preserve identity-first policy")
    if support_risk.get("evidence_source_field") != "none":
        errors.append("support-audit risk ranking should expose evidence_source_field")
    if support_risk.get("evidence_source_name") != "none":
        errors.append("support-audit risk ranking should expose evidence_source_name")
    support_supported_reason = ""
    for row in support_payload.get("risk_ranking", []):
        if isinstance(row, dict) and row.get("verdict") == "supported":
            support_supported_reason = str(row.get("risk_reason", ""))
            break
    if support_supported_reason and support_supported_reason != "available_evidence_supports_claim":
        errors.append("support-audit supported risk rows should expose risk_reason=available_evidence_supports_claim")
    support_citation_set_reason = ""
    for row in support_payload.get("risk_ranking", []):
        if isinstance(row, dict) and row.get("input_mode") == "citation_set":
            support_citation_set_reason = str(row.get("risk_reason", ""))
            break
    if support_citation_set_reason != "citation_set_evidence_does_not_confirm_claim":
        errors.append("support-audit citation-set risk rows should expose citation-set risk_reason")
    support_citation_set_fix = {}
    for row in support_payload.get("risk_ranking", []):
        if isinstance(row, dict) and row.get("input_mode") == "citation_set":
            support_citation_set_fix = row.get("suggested_fix", {})
            break
    if support_citation_set_fix.get("kind") != "inspect_full_text_or_find_stronger_citation":
        errors.append("support-audit citation-set risk rows should expose actionable suggested_fix")
    require_suggested_fix_summary(
        support_filtered.get("filtered", {}).get("omitted_review_summary", {}),
        label="support-audit JSONL high-risk omitted rows",
        confirmation_required_indexes=[2, 0],
        no_confirmation_required_indexes=[],
        fix_kind_indexes={"inspect_full_text_or_find_stronger_citation": [2, 0]},
    )
    support_sparse_result = support_sparse_metadata_quality.get("results", [{}])[0]
    support_sparse_risk = support_sparse_metadata_quality.get("risk_ranking", [{}])[0]
    if (
        support_sparse_result.get("resolution", {}).get("source_metadata_missing_fields")
        != ["venue", "abstract", "url"]
    ):
        errors.append("support-audit result resolution should expose source_metadata_missing_fields")
    if (
        support_sparse_result.get("source_metadata_confidence_effect")
        != "missing_metadata_lowers_confidence_not_fabrication_evidence"
    ):
        errors.append("support-audit result should expose source_metadata_confidence_effect")
    if support_sparse_risk.get("source_metadata_missing_fields") != ["venue", "abstract", "url"]:
        errors.append("support-audit risk ranking should flatten source_metadata_missing_fields")
    if (
        support_sparse_risk.get("source_metadata_confidence_effect")
        != "missing_metadata_lowers_confidence_not_fabrication_evidence"
    ):
        errors.append("support-audit risk ranking should expose source_metadata_confidence_effect")

    if support_filtered.get("filtered", {}).get("high_risk_only") is not True:
        errors.append("support-audit JSONL high-risk run should include filtered.high_risk_only=true")
    if support_filtered.get("filtered", {}).get("returned_indexes") != [1]:
        errors.append("support-audit JSONL high-risk run should preserve returned index 1")
    if support_filtered.get("filtered", {}).get("omitted_review_summary", {}).get("medium_risk_count") != 2:
        errors.append("support-audit JSONL high-risk run should summarize omitted medium-risk rows")
    support_filtered_omitted_steps = (
        support_filtered.get("filtered", {}).get("omitted_review_summary", {}).get("recommended_next_steps", {})
    )
    if support_filtered_omitted_steps.get("first_queue") != "evidence_review_indexes":
        errors.append("support-audit JSONL high-risk run should preserve omitted evidence review recommended steps")
    full_text_results = support_full_text.get("results", [])
    full_text_risk = support_full_text.get("risk_ranking", [{}])[0] if support_full_text.get("risk_ranking") else {}
    full_text_first = full_text_results[0] if full_text_results else {}
    full_text_file_results = support_full_text_file.get("results", [])
    full_text_file_risk = (
        support_full_text_file.get("risk_ranking", [{}])[0] if support_full_text_file.get("risk_ranking") else {}
    )
    full_text_file_first = full_text_file_results[0] if full_text_file_results else {}
    if support_full_text.get("summary", {}).get("weakly_supported") != 1:
        errors.append("support-audit full-text example should report one weakly_supported item")
    if full_text_first.get("evidence_scope") != "full_text":
        errors.append("support-audit full-text example should preserve evidence_scope=full_text")
    if full_text_first.get("evidence", {}).get("source_field") != "user_full_text_excerpt_1":
        errors.append("support-audit full-text example should preserve user_full_text source_field")
    if full_text_first.get("evidence", {}).get("source_name") != "user_provided":
        errors.append("support-audit full-text example should preserve user_provided source_name")
    if full_text_first.get("resolution", {}).get("verdict") != "matched":
        errors.append("support-audit full-text example should resolve the fixture citation")
    if full_text_risk.get("evidence_scope") != "full_text":
        errors.append("support-audit full-text risk ranking should expose evidence_scope=full_text")
    if full_text_risk.get("evidence_source_field") != "user_full_text_excerpt_1":
        errors.append("support-audit full-text risk ranking should expose evidence_source_field")
    if full_text_risk.get("evidence_source_name") != "user_provided":
        errors.append("support-audit full-text risk ranking should expose evidence_source_name")
    if full_text_risk.get("next_action") != "tighten_claim_or_inspect_full_text":
        errors.append("support-audit full-text risk ranking should expose tighten_claim_or_inspect_full_text")
    if support_full_text_file.get("summary", {}).get("weakly_supported") != 1:
        errors.append("support-audit full-text-file example should report one weakly_supported item")
    if full_text_file_first.get("evidence_scope") != "full_text":
        errors.append("support-audit full-text-file example should preserve evidence_scope=full_text")
    if full_text_file_first.get("evidence", {}).get("source_field") != "user_full_text_file_1":
        errors.append("support-audit full-text-file example should preserve user_full_text_file source_field")
    if full_text_file_first.get("evidence", {}).get("source_name") != "user_provided":
        errors.append("support-audit full-text-file example should preserve user_provided source_name")
    if full_text_file_first.get("resolution", {}).get("verdict") != "matched":
        errors.append("support-audit full-text-file example should resolve the fixture citation")
    if full_text_file_risk.get("evidence_scope") != "full_text":
        errors.append("support-audit full-text-file risk ranking should expose evidence_scope=full_text")
    if full_text_file_risk.get("evidence_source_field") != "user_full_text_file_1":
        errors.append("support-audit full-text-file risk ranking should expose evidence_source_field")
    if full_text_file_risk.get("evidence_source_name") != "user_provided":
        errors.append("support-audit full-text-file risk ranking should expose evidence_source_name")
    if full_text_file_risk.get("next_action") != "tighten_claim_or_inspect_full_text":
        errors.append("support-audit full-text-file risk ranking should expose tighten_claim_or_inspect_full_text")
    if support_markdown.get("summary", {}).get("insufficient_evidence") != 2:
        errors.append("support-audit markdown example should report two insufficient_evidence items")
    if len(support_markdown.get("results", [])) != 2:
        errors.append("support-audit markdown example should return extracted per-citation results")
    if support_markdown.get("review_summary", {}).get("total") != 2:
        errors.append("support-audit markdown example should preserve review_summary total")
    if support_markdown.get("results", [{}])[0].get("claim") != "The Transformer relies entirely on attention mechanisms.":
        errors.append("support-audit markdown example should apply the provided claim to extracted citations")
    support_markdown_first = support_markdown.get("results", [{}])[0]
    support_markdown_risk = support_markdown.get("risk_ranking", [{}])[0]
    support_markdown_source_traceability = support_markdown.get("review_summary", {}).get("source_traceability", {})
    if support_markdown_first.get("resolution", {}).get("input_source_path") != "examples/references.md":
        errors.append("support-audit markdown result should expose input_source_path")
    if support_markdown_first.get("resolution", {}).get("input_source_locator") != "examples/references.md#citation-1":
        errors.append("support-audit markdown result should expose input_source_locator")
    if (
        support_markdown_first.get("resolution", {}).get("input_source_line_start") != 5
        or support_markdown_first.get("resolution", {}).get("input_source_line_end") != 5
    ):
        errors.append("support-audit markdown result should expose input source line range")
    if support_markdown_risk.get("input_source_path") != "examples/references.md":
        errors.append("support-audit markdown risk ranking should expose input_source_path")
    if not str(support_markdown_risk.get("input_source_locator", "")).startswith("examples/references.md#citation-"):
        errors.append("support-audit markdown risk ranking should expose extracted input_source_locator")
    if support_markdown_risk.get("input_source_line_start") not in {5, 6}:
        errors.append("support-audit markdown risk ranking should expose extracted input source line start")
    if support_markdown_source_traceability.get("has_source_backed_items") is not True:
        errors.append("support-audit markdown example should expose source-backed review_summary traceability")
    if support_markdown_source_traceability.get("source_paths") != ["examples/references.md"]:
        errors.append("support-audit markdown example should summarize source_paths")
    if support_markdown_source_traceability.get("source_indexes") != [1, 2]:
        errors.append("support-audit markdown example should preserve sorted extracted source indexes")
    if support_markdown_source_traceability.get("high_risk_source_indexes") != [2]:
        errors.append("support-audit markdown example should summarize high-risk source indexes")
    if support_markdown_source_traceability.get("review_required_source_indexes") != [1, 2]:
        errors.append("support-audit markdown example should summarize review-required source indexes")
    if "examples/references.md#citation-1" not in support_markdown_source_traceability.get(
        "review_required_source_locators", []
    ) or "examples/references.md#citation-2" not in support_markdown_source_traceability.get(
        "review_required_source_locators", []
    ):
        errors.append("support-audit markdown example should summarize review-required source locators")
    if support_markdown_filtered.get("filtered", {}).get("high_risk_only") is not True:
        errors.append("support-audit markdown high-risk run should include filtered.high_risk_only=true")
    if support_markdown_filtered.get("filtered", {}).get("original_results") != 2:
        errors.append("support-audit markdown high-risk run should preserve original_results=2")
    if support_markdown_filtered.get("filtered", {}).get("returned_indexes") != [1]:
        errors.append("support-audit markdown high-risk run should preserve returned index 1")
    if len(support_markdown_filtered.get("results", [])) != 1:
        errors.append("support-audit markdown high-risk run should return one high-risk result")
    support_markdown_omitted = support_markdown_filtered.get("filtered", {}).get("omitted_review_summary", {})
    support_markdown_omitted_source_traceability = support_markdown_omitted.get("source_traceability", {})
    if support_markdown_omitted.get("medium_risk_count") != 1:
        errors.append("support-audit markdown high-risk run should summarize omitted medium-risk rows")
    if support_markdown_omitted_source_traceability.get("has_source_backed_items") is not True:
        errors.append("support-audit markdown high-risk run should preserve omitted source traceability")
    if support_markdown_omitted_source_traceability.get("source_indexes") != [1]:
        errors.append("support-audit markdown high-risk run should preserve omitted source indexes")
    if support_markdown_omitted_source_traceability.get("review_required_source_locators") != [
        "examples/references.md#citation-1"
    ]:
        errors.append("support-audit markdown high-risk run should preserve omitted review-required source locator")
    require_suggested_fix_summary(
        support_markdown_filtered.get("filtered", {}).get("omitted_review_summary", {}),
        label="support-audit markdown high-risk omitted rows",
        confirmation_required_indexes=[0],
        no_confirmation_required_indexes=[],
        fix_kind_indexes={"inspect_full_text_or_find_stronger_citation": [0]},
    )
    if support_docx_filtered.get("filtered", {}).get("high_risk_only") is not True:
        errors.append("support-audit DOCX high-risk run should include filtered.high_risk_only=true")
    if support_docx_filtered.get("filtered", {}).get("returned_indexes") != [1]:
        errors.append("support-audit DOCX high-risk run should preserve returned index 1")
    if support_docx_filtered.get("filtered", {}).get("omitted_indexes") != [0]:
        errors.append("support-audit DOCX high-risk run should preserve omitted index 0")
    support_docx_risk = support_docx_filtered.get("risk_ranking", [{}])[0]
    support_docx_source_traceability = support_docx_filtered.get("review_summary", {}).get("source_traceability", {})
    support_docx_omitted_source_traceability = (
        support_docx_filtered.get("filtered", {}).get("omitted_review_summary", {}).get("source_traceability", {})
    )
    if support_docx_risk.get("input_source_format") != "docx":
        errors.append("support-audit DOCX risk ranking should expose input_source_format=docx")
    if support_docx_risk.get("input_source_locator") != f"{docx_refs_path}#citation-2":
        errors.append("support-audit DOCX risk ranking should expose extracted input_source_locator")
    if support_docx_source_traceability.get("source_paths") != [str(docx_refs_path)]:
        errors.append("support-audit DOCX high-risk run should summarize source_paths")
    if support_docx_source_traceability.get("source_indexes") != [1, 2]:
        errors.append("support-audit DOCX high-risk run should preserve sorted extracted source indexes")
    if support_docx_source_traceability.get("high_risk_source_indexes") != [2]:
        errors.append("support-audit DOCX high-risk run should summarize high-risk source indexes")
    if support_docx_omitted_source_traceability.get("source_indexes") != [1]:
        errors.append("support-audit DOCX high-risk run should preserve omitted source indexes")
    if support_docx_omitted_source_traceability.get("review_required_source_locators") != [
        f"{docx_refs_path}#citation-1"
    ]:
        errors.append("support-audit DOCX high-risk run should preserve omitted review-required source locator")

    markdown_counterevidence_results = support_markdown_counterevidence.get("results", [])
    markdown_counterevidence_risk_rows = support_markdown_counterevidence.get("risk_ranking", [])
    markdown_counterevidence_first = (
        markdown_counterevidence_results[0].get("counterevidence", {}) if markdown_counterevidence_results else {}
    )
    if support_markdown_counterevidence.get("counterevidence_included") is not True:
        errors.append("support-audit markdown --with-counterevidence should report counterevidence_included=true")
    if support_markdown_counterevidence.get("counterevidence_top_k") != 3:
        errors.append("support-audit markdown --with-counterevidence should preserve the default counterevidence_top_k")
    if len(markdown_counterevidence_results) != 2:
        errors.append("support-audit markdown --with-counterevidence should preserve extracted result count")
    if not markdown_counterevidence_results or not all(
        item.get("counterevidence_review") for item in markdown_counterevidence_results
    ):
        errors.append("support-audit markdown --with-counterevidence should mark extracted rows for review")
    if not markdown_counterevidence_first.get("query_plan") or not markdown_counterevidence_first.get("query_results"):
        errors.append("support-audit markdown --with-counterevidence should attach query_plan and query_results")
    if not markdown_counterevidence_risk_rows or [row.get("index") for row in markdown_counterevidence_risk_rows] != [1, 0]:
        errors.append("support-audit markdown --with-counterevidence should preserve risk-sorted extracted indexes")

    counterevidence_results = support_counterevidence.get("results", [])
    counterevidence_risk_rows = support_counterevidence.get("risk_ranking", [])
    counterevidence_first = counterevidence_results[0].get("counterevidence", {}) if counterevidence_results else {}
    counterevidence_risk_first = counterevidence_risk_rows[0].get("counterevidence", {}) if counterevidence_risk_rows else {}
    if support_counterevidence.get("counterevidence_included") is not True:
        errors.append("support-audit --with-counterevidence should report counterevidence_included=true")
    if support_counterevidence.get("counterevidence_top_k") != 3:
        errors.append("support-audit --with-counterevidence should preserve the default counterevidence_top_k")
    if not counterevidence_results or not all(item.get("counterevidence_review") for item in counterevidence_results):
        errors.append("support-audit --with-counterevidence should mark review-worthy rows for counterevidence review")
    if not counterevidence_first.get("query_plan") or not counterevidence_first.get("query_results"):
        errors.append("support-audit --with-counterevidence should expose counterevidence query_plan and query_results")
    if "review leads, not a contradiction verdict" not in counterevidence_first.get("interpretation", ""):
        errors.append("support-audit counterevidence interpretation should preserve review-lead safety wording")
    if not counterevidence_risk_rows or counterevidence_risk_first.get("next_action") not in {"continue", "review_counterevidence_leads"}:
        errors.append("support-audit risk rows should include counterevidence next_action")
    if not any(
        "source_outage_safety" in [
            item.get("role")
            for item in (risk_row.get("counterevidence", {}).get("query_plan", []) if isinstance(risk_row, dict) else [])
            if isinstance(item, dict)
        ]
        for risk_row in counterevidence_risk_rows
    ):
        errors.append("support-audit --with-counterevidence should keep source_outage_safety probes in batch output")

    if support_set.get("support_mode") != "insufficient_evidence":
        errors.append("support-set example should report insufficient_evidence support_mode")
    if support_set.get("summary", {}).get("insufficient_evidence") != 2:
        errors.append("support-set example should preserve per-citation summary counts")
    if len(support_set.get("results", [])) != 2:
        errors.append("support-set example should return per-citation results")
    if support_set.get("next_action") != "inspect_full_text_or_find_stronger_citation":
        errors.append("support-set example should expose stable next_action")
    support_set_counterevidence_report = support_set_counterevidence.get("counterevidence", {})
    if support_set_counterevidence.get("counterevidence_included") is not True:
        errors.append("support-set --with-counterevidence should report counterevidence_included=true")
    if support_set_counterevidence.get("counterevidence_review") is not True:
        errors.append("support-set --with-counterevidence should keep the aggregate review flag")
    if support_set_counterevidence_report.get("candidate_count") != 1:
        errors.append("support-set --with-counterevidence should attach one fixture-backed review lead")
    if support_set_counterevidence_report.get("next_action") != "review_counterevidence_leads":
        errors.append("support-set --with-counterevidence should route leads to review_counterevidence_leads")
    if [item.get("role") for item in support_set_counterevidence_report.get("query_plan", [])] != ["claim_similarity"]:
        errors.append("support-set --with-counterevidence should preserve deterministic fixture query roles")
    if "review leads, not a contradiction verdict" not in support_set_counterevidence_report.get("interpretation", ""):
        errors.append("support-set --with-counterevidence should preserve review-lead safety wording")
    if support_set_markdown.get("support_mode") != "insufficient_evidence":
        errors.append("support-set markdown example should report insufficient_evidence support_mode")
    if support_set_markdown.get("summary", {}).get("insufficient_evidence") != 2:
        errors.append("support-set markdown example should preserve per-citation summary counts")
    if len(support_set_markdown.get("results", [])) != 2:
        errors.append("support-set markdown example should return extracted per-citation results")
    if support_set_markdown.get("input_source_paths") != ["examples/references.md"]:
        errors.append("support-set markdown should expose aggregate input_source_paths")
    if support_set_markdown.get("input_source_locators") != [
        "examples/references.md#citation-1",
        "examples/references.md#citation-2",
    ]:
        errors.append("support-set markdown should expose aggregate input_source_locators")
    if support_set_markdown.get("input_source_line_starts") != [5, 6]:
        errors.append("support-set markdown should expose aggregate input_source_line_starts")
    if support_set_markdown.get("input_source_line_ends") != [5, 6]:
        errors.append("support-set markdown should expose aggregate input_source_line_ends")
    if support_set_docx.get("support_mode") != "insufficient_evidence":
        errors.append("support-set DOCX example should report insufficient_evidence support_mode")
    if support_set_docx.get("summary", {}).get("insufficient_evidence") != 2:
        errors.append("support-set DOCX example should preserve per-citation summary counts")
    if len(support_set_docx.get("results", [])) != 2:
        errors.append("support-set DOCX example should return extracted per-citation results")
    if support_set_docx.get("input_source_paths") != [str(docx_refs_path)]:
        errors.append("support-set DOCX should expose aggregate input_source_paths")
    if support_set_docx.get("input_source_locators") != [
        f"{docx_refs_path}#citation-1",
        f"{docx_refs_path}#citation-2",
    ]:
        errors.append("support-set DOCX should expose aggregate input_source_locators")
    if support_set_docx.get("input_source_line_starts") != [2, 3]:
        errors.append("support-set DOCX should expose paragraph-derived input_source_line_starts")
    if support_set_docx.get("input_source_line_ends") != [2, 3]:
        errors.append("support-set DOCX should expose paragraph-derived input_source_line_ends")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "commands": commands,
        "help_commands": help_commands,
        "help_contracts": {
            name: {
                "documents_jsonl": "JSON/JSONL" in help_text,
                "documents_reference_files": "Markdown/LaTeX/BibTeX/BBL/DOCX/plain-text" in help_text,
                "documents_bibtex_bbl": "BibTeX/BBL" in help_text,
            }
            for name, help_text in help_texts.items()
        },
        "fixture": "examples/citations.json",
        "jsonl_fixture": "examples/citations.jsonl",
        "extract_count": len(extract_payload),
        "extract_line_range": {
            "source_line_start": (
                extract_payload[0].get("source_line_start")
                if isinstance(extract_payload, list) and extract_payload
                else None
            ),
            "source_line_end": (
                extract_payload[0].get("source_line_end")
                if isinstance(extract_payload, list) and extract_payload
                else None
            ),
        },
        "extract_latex_bibliography": {
            "count": len(latex_bib_extract) if isinstance(latex_bib_extract, list) else 0,
            "source_path": (
                latex_bib_extract[0].get("source_path", "")
                if isinstance(latex_bib_extract, list) and latex_bib_extract
                else ""
            ),
            "source_format": (
                latex_bib_extract[0].get("source_format", "")
                if isinstance(latex_bib_extract, list) and latex_bib_extract
                else ""
            ),
            "source_id": (
                latex_bib_extract[0].get("source_id", "")
                if isinstance(latex_bib_extract, list) and latex_bib_extract
                else ""
            ),
            "title": (
                latex_bib_extract[0].get("title", "")
                if isinstance(latex_bib_extract, list) and latex_bib_extract
                else ""
            ),
            "expanded_macro_venue": (
                "NeurIPS" in str(latex_bib_extract[0].get("raw_text", ""))
                and "nipsconf" not in str(latex_bib_extract[0].get("raw_text", ""))
                if isinstance(latex_bib_extract, list) and latex_bib_extract
                else False
            ),
        },
        "extract_latex_bbl": {
            "count": len(latex_bbl_extract) if isinstance(latex_bbl_extract, list) else 0,
            "source_path": (
                latex_bbl_extract[0].get("source_path", "")
                if isinstance(latex_bbl_extract, list) and latex_bbl_extract
                else ""
            ),
            "source_format": (
                latex_bbl_extract[0].get("source_format", "")
                if isinstance(latex_bbl_extract, list) and latex_bbl_extract
                else ""
            ),
            "source_id": (
                latex_bbl_extract[0].get("source_id", "")
                if isinstance(latex_bbl_extract, list) and latex_bbl_extract
                else ""
            ),
            "source_locator": (
                latex_bbl_extract[0].get("source_locator", "")
                if isinstance(latex_bbl_extract, list) and latex_bbl_extract
                else ""
            ),
            "arxiv_id": (
                latex_bbl_extract[0].get("arxiv_id", "")
                if isinstance(latex_bbl_extract, list) and latex_bbl_extract
                else ""
            ),
        },
        "extract_pasted_reference_list": {
            "count": len(pasted_reference_extract) if isinstance(pasted_reference_extract, list) else 0,
            "source_type": (
                pasted_reference_extract[0].get("source_type", "")
                if isinstance(pasted_reference_extract, list) and pasted_reference_extract
                else ""
            ),
            "source_format": (
                pasted_reference_extract[0].get("source_format", "")
                if isinstance(pasted_reference_extract, list) and pasted_reference_extract
                else ""
            ),
            "wrapped_continuation": (
                "Advances in Neural Information Processing Systems"
                in str(pasted_reference_extract[0].get("raw_text", ""))
                if isinstance(pasted_reference_extract, list) and pasted_reference_extract
                else False
            ),
            "line_range": {
                "source_line_start": (
                    pasted_reference_extract[0].get("source_line_start")
                    if isinstance(pasted_reference_extract, list) and pasted_reference_extract
                    else None
                ),
                "source_line_end": (
                    pasted_reference_extract[0].get("source_line_end")
                    if isinstance(pasted_reference_extract, list) and pasted_reference_extract
                    else None
                ),
            },
        },
        "extract_unnumbered_reference_list": {
            "count": len(unnumbered_reference_extract) if isinstance(unnumbered_reference_extract, list) else 0,
            "source_type": (
                unnumbered_reference_extract[0].get("source_type", "")
                if isinstance(unnumbered_reference_extract, list) and unnumbered_reference_extract
                else ""
            ),
            "source_format": (
                unnumbered_reference_extract[0].get("source_format", "")
                if isinstance(unnumbered_reference_extract, list) and unnumbered_reference_extract
                else ""
            ),
            "line_range": {
                "source_line_start": (
                    unnumbered_reference_extract[0].get("source_line_start")
                    if isinstance(unnumbered_reference_extract, list) and unnumbered_reference_extract
                    else None
                ),
                "source_line_end": (
                    unnumbered_reference_extract[0].get("source_line_end")
                    if isinstance(unnumbered_reference_extract, list) and unnumbered_reference_extract
                    else None
                ),
            },
        },
        "extract_docx_reference_list": {
            "count": len(docx_reference_extract) if isinstance(docx_reference_extract, list) else 0,
            "source_path": (
                docx_reference_extract[0].get("source_path", "")
                if isinstance(docx_reference_extract, list) and docx_reference_extract
                else ""
            ),
            "source_format": (
                docx_reference_extract[0].get("source_format", "")
                if isinstance(docx_reference_extract, list) and docx_reference_extract
                else ""
            ),
            "source_locator": (
                docx_reference_extract[0].get("source_locator", "")
                if isinstance(docx_reference_extract, list) and docx_reference_extract
                else ""
            ),
            "line_range": {
                "source_line_start": (
                    docx_reference_extract[0].get("source_line_start")
                    if isinstance(docx_reference_extract, list) and docx_reference_extract
                    else None
                ),
                "source_line_end": (
                    docx_reference_extract[0].get("source_line_end")
                    if isinstance(docx_reference_extract, list) and docx_reference_extract
                    else None
                ),
            },
        },
        "audit_summary": audit_payload.get("summary", {}),
        "audit_review_summary_source_traceability": audit_source_traceability,
        "audit_top_risk_reason": audit_payload.get("risk_ranking", [{}])[0].get("risk_reason"),
        "audit_top_suggested_fix": audit_top_fix,
        "audit_suggested_fix_summary": audit_suggested_fix_summary,
        "audit_latex_bibliography": {
            "summary": audit_latex_bibliography.get("summary", {}),
            "input_source_path": audit_latex_risk.get("input_source_path", ""),
            "input_source_format": audit_latex_risk.get("input_source_format", ""),
        },
        "audit_jsonl_returned_indexes": audit_jsonl_filtered.get("filtered", {}).get("returned_indexes", []),
        "audit_jsonl_omitted_review_summary": audit_jsonl_omitted,
        "audit_metadata_mismatch_fields": mismatch_risk.get("mismatched_fields", []),
        "audit_metadata_mismatch_risk_reason": mismatch_risk.get("risk_reason", ""),
        "audit_metadata_mismatch_suggested_fix": mismatch_risk.get("suggested_fix", {}),
        "audit_metadata_suggested_citation_present": bool(mismatch_risk.get("suggested_citation")),
        "audit_sparse_metadata_quality": {
            "missing_fields": sparse_quality_risk.get("source_metadata_missing_fields", []),
            "confidence_effect": sparse_quality_risk.get("source_metadata_confidence_effect", ""),
            "identifier_provenance": (
                sparse_quality_risk.get("canonical_metadata_quality", {}).get("identifiers", {})
                if isinstance(sparse_quality_risk.get("canonical_metadata_quality"), dict)
                else {}
            ),
        },
        "audit_returned_indexes": audit_filtered.get("filtered", {}).get("returned_indexes", []),
        "audit_markdown_source_traceability": audit_markdown_source_traceability,
        "audit_markdown_line_range": {
            "input_source_line_start": audit_filtered_risk.get("input_source_line_start"),
            "input_source_line_end": audit_filtered_risk.get("input_source_line_end"),
        },
        "audit_docx_returned_indexes": audit_docx_filtered.get("filtered", {}).get("returned_indexes", []),
        "audit_docx_source_traceability": audit_docx_source_traceability,
        "audit_docx_omitted_source_traceability": audit_docx_omitted_source_traceability,
        "audit_docx_line_range": {
            "input_source_line_start": audit_docx_risk.get("input_source_line_start"),
            "input_source_line_end": audit_docx_risk.get("input_source_line_end"),
        },
        "audit_triage_plan": audit_triage_plan,
        "support_summary": support_payload.get("summary", {}),
        "support_review_summary_source_traceability": support_source_traceability,
        "support_triage_plan": support_triage_plan,
        "support_suggested_fix_summary": support_suggested_fix_summary,
        "support_risk_provenance": {
            "risk_reason": support_risk.get("risk_reason"),
            "suggested_fix": support_risk.get("suggested_fix", {}),
            "support_confidence": support_risk.get("support_confidence"),
            "support_engine": support_risk.get("support_engine"),
            "resolution_verdict": support_risk.get("resolution_verdict"),
            "evidence_source_name": support_risk.get("evidence_source_name"),
            "evidence_source_field": support_risk.get("evidence_source_field"),
        },
        "support_sparse_metadata_quality": {
            "result_missing_fields": (
                support_sparse_result.get("resolution", {}).get("source_metadata_missing_fields", [])
            ),
            "result_confidence_effect": support_sparse_result.get("source_metadata_confidence_effect", ""),
            "risk_missing_fields": support_sparse_risk.get("source_metadata_missing_fields", []),
            "risk_confidence_effect": support_sparse_risk.get("source_metadata_confidence_effect", ""),
        },
        "support_input_modes": [item.get("input_mode") for item in support_results],
        "support_returned_indexes": support_filtered.get("filtered", {}).get("returned_indexes", []),
        "support_omitted_review_summary": support_filtered.get("filtered", {}).get("omitted_review_summary", {}),
        "support_full_text_summary": support_full_text.get("summary", {}),
        "support_full_text_evidence_scope": full_text_first.get("evidence_scope"),
        "support_full_text_source_field": (
            full_text_first.get("evidence", {}).get("source_field") if isinstance(full_text_first.get("evidence"), dict) else ""
        ),
        "support_full_text_source_name": (
            full_text_first.get("evidence", {}).get("source_name") if isinstance(full_text_first.get("evidence"), dict) else ""
        ),
        "support_full_text_resolution_verdict": full_text_first.get("resolution", {}).get("verdict")
        if isinstance(full_text_first.get("resolution"), dict)
        else "",
        "support_full_text_risk": {
            "evidence_scope": full_text_risk.get("evidence_scope"),
            "evidence_source_name": full_text_risk.get("evidence_source_name"),
            "evidence_source_field": full_text_risk.get("evidence_source_field"),
            "next_action": full_text_risk.get("next_action"),
        },
        "support_full_text_file_summary": support_full_text_file.get("summary", {}),
        "support_full_text_file_evidence_scope": full_text_file_first.get("evidence_scope"),
        "support_full_text_file_source_field": (
            full_text_file_first.get("evidence", {}).get("source_field")
            if isinstance(full_text_file_first.get("evidence"), dict)
            else ""
        ),
        "support_full_text_file_source_name": (
            full_text_file_first.get("evidence", {}).get("source_name")
            if isinstance(full_text_file_first.get("evidence"), dict)
            else ""
        ),
        "support_full_text_file_resolution_verdict": full_text_file_first.get("resolution", {}).get("verdict")
        if isinstance(full_text_file_first.get("resolution"), dict)
        else "",
        "support_full_text_file_risk": {
            "evidence_scope": full_text_file_risk.get("evidence_scope"),
            "evidence_source_name": full_text_file_risk.get("evidence_source_name"),
            "evidence_source_field": full_text_file_risk.get("evidence_source_field"),
            "next_action": full_text_file_risk.get("next_action"),
        },
        "support_markdown_summary": support_markdown.get("summary", {}),
        "support_markdown_result_count": len(support_markdown.get("results", [])),
        "support_markdown_source_traceability": support_markdown_source_traceability,
        "support_markdown_line_range": {
            "result_line_start": support_markdown_first.get("resolution", {}).get("input_source_line_start"),
            "result_line_end": support_markdown_first.get("resolution", {}).get("input_source_line_end"),
            "risk_line_start": support_markdown_risk.get("input_source_line_start"),
        },
        "support_markdown_returned_indexes": support_markdown_filtered.get("filtered", {}).get("returned_indexes", []),
        "support_markdown_original_results": support_markdown_filtered.get("filtered", {}).get("original_results"),
        "support_markdown_omitted_review_summary": support_markdown_omitted,
        "support_markdown_omitted_source_traceability": support_markdown_omitted_source_traceability,
        "support_docx_returned_indexes": support_docx_filtered.get("filtered", {}).get("returned_indexes", []),
        "support_docx_source_traceability": support_docx_source_traceability,
        "support_docx_omitted_source_traceability": support_docx_omitted_source_traceability,
        "support_markdown_counterevidence_included": support_markdown_counterevidence.get("counterevidence_included"),
        "support_markdown_counterevidence_review_count": sum(
            1 for item in markdown_counterevidence_results if item.get("counterevidence_review")
        ),
        "support_markdown_counterevidence_query_roles": [
            item.get("role")
            for item in markdown_counterevidence_first.get("query_plan", [])
            if isinstance(item, dict)
        ],
        "support_markdown_counterevidence_risk_indexes": [
            row.get("index") for row in markdown_counterevidence_risk_rows
        ],
        "support_counterevidence_included": support_counterevidence.get("counterevidence_included"),
        "support_counterevidence_review_count": sum(
            1 for item in counterevidence_results if item.get("counterevidence_review")
        ),
        "support_counterevidence_first_next_action": counterevidence_first.get("next_action"),
        "support_counterevidence_query_roles": [
            item.get("role")
            for item in counterevidence_first.get("query_plan", [])
            if isinstance(item, dict)
        ],
        "support_counterevidence_source_outage_probe": any(
            "source_outage_safety" in [
                item.get("role")
                for item in (risk_row.get("counterevidence", {}).get("query_plan", []) if isinstance(risk_row, dict) else [])
                if isinstance(item, dict)
            ]
            for risk_row in counterevidence_risk_rows
        ),
        "support_set_mode": support_set.get("support_mode"),
        "support_citation_set_risk_reason": support_citation_set_reason,
        "support_citation_set_suggested_fix": support_citation_set_fix,
        "support_set_summary": support_set.get("summary", {}),
        "support_set_result_count": len(support_set.get("results", [])),
        "support_set_counterevidence_included": support_set_counterevidence.get("counterevidence_included"),
        "support_set_counterevidence_next_action": support_set_counterevidence_report.get("next_action"),
        "support_set_counterevidence_candidate_count": support_set_counterevidence_report.get("candidate_count"),
        "support_set_counterevidence_query_roles": [
            item.get("role")
            for item in support_set_counterevidence_report.get("query_plan", [])
            if isinstance(item, dict)
        ],
        "support_set_markdown_mode": support_set_markdown.get("support_mode"),
        "support_set_markdown_summary": support_set_markdown.get("summary", {}),
        "support_set_markdown_result_count": len(support_set_markdown.get("results", [])),
        "support_set_markdown_line_starts": support_set_markdown.get("input_source_line_starts", []),
        "support_set_markdown_line_ends": support_set_markdown.get("input_source_line_ends", []),
        "support_set_docx_mode": support_set_docx.get("support_mode"),
        "support_set_docx_summary": support_set_docx.get("summary", {}),
        "support_set_docx_result_count": len(support_set_docx.get("results", [])),
        "support_set_docx_line_starts": support_set_docx.get("input_source_line_starts", []),
        "support_set_docx_line_ends": support_set_docx.get("input_source_line_ends", []),
    }


def _run_text_command(cmd: List[str], *, cwd: Path, env_overrides: Dict[str, str]) -> str:
    env = dict(os.environ)
    env.update(env_overrides)
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"command failed ({completed.returncode}): {' '.join(cmd)}\nSTDOUT:\n{completed.stdout}\nSTDERR:\n{completed.stderr}"
        )
    return completed.stdout


def _run_json_command(cmd: List[str], *, cwd: Path, env_overrides: Dict[str, str]) -> Any:
    env = dict(os.environ)
    env.update(env_overrides)
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, completed.args, completed.stdout, completed.stderr)
    if completed.stderr.strip():
        raise RuntimeError(f"{cmd} wrote unexpected stderr: {completed.stderr.strip()}")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{cmd} did not write valid JSON to stdout: {exc}") from exc


def _check_project_metadata_contract(project_root: Path) -> Dict[str, Any]:
    pyproject = _read_required_text(project_root / "pyproject.toml")
    setup = _read_required_text(project_root / "setup.py")
    readme = _read_required_text(project_root / "README.md")
    changelog = _read_required_text(project_root / "CHANGELOG.md")
    citation = _read_required_text(project_root / "CITATION.cff")
    github_launch = _read_required_text(project_root / "docs" / "github_launch.md")
    license_text = _read_required_text(project_root / "LICENSE")

    errors = []
    pyproject_description = _extract_toml_string(pyproject, "description")
    setup_description = _extract_python_string_kwarg(setup, "description")
    if pyproject_description != setup_description:
        errors.append("pyproject.toml and setup.py descriptions must match")
    if not pyproject_description or _has_placeholder_text(pyproject_description):
        errors.append("project description is missing or placeholder-like")
    if "prototype" in pyproject_description.lower():
        errors.append("project description should describe the product, not a prototype")
    for required_description_phrase in ("skeptical citation auditor", "agent writing workflows"):
        if required_description_phrase not in pyproject_description:
            errors.append(f"project description should include {required_description_phrase!r}")

    required_snippets = {
        "pyproject project name": 'name = "citeguard"',
        "pyproject version": f'version = "{__version__}"',
        "pyproject readme": 'readme = "README.md"',
        "pyproject requires-python": 'requires-python = ">=3.9"',
        "pyproject license file": 'license = { file = "LICENSE" }',
        "pyproject homepage": 'Homepage = "https://github.com/xiaweiyi713/citeguard"',
        "pyproject repository": 'Repository = "https://github.com/xiaweiyi713/citeguard"',
        "pyproject issues": 'Issues = "https://github.com/xiaweiyi713/citeguard/issues"',
        "pyproject changelog": 'Changelog = "https://github.com/xiaweiyi713/citeguard/blob/main/CHANGELOG.md"',
        "pyproject documentation": 'Documentation = "https://github.com/xiaweiyi713/citeguard#readme"',
        "setup name": 'name="citeguard"',
        "setup version": f'version="{__version__}"',
        "setup readme content type": 'long_description_content_type="text/markdown"',
        "setup python requires": 'python_requires=">=3.9"',
        "setup license file": 'license_files=["LICENSE"]',
        "setup homepage": '"Homepage": "https://github.com/xiaweiyi713/citeguard"',
        "setup repository": '"Repository": "https://github.com/xiaweiyi713/citeguard"',
        "setup issues": '"Issues": "https://github.com/xiaweiyi713/citeguard/issues"',
        "setup changelog": '"Changelog": "https://github.com/xiaweiyi713/citeguard/blob/main/CHANGELOG.md"',
        "setup documentation": '"Documentation": "https://github.com/xiaweiyi713/citeguard#readme"',
        "citeguard script": 'citeguard = "citeguard.cli:main"',
        "citeguard-mcp script": 'citeguard-mcp = "citeguard.mcp.server:main"',
    }
    combined_metadata_files = f"{pyproject}\n{setup}"
    for label, snippet in required_snippets.items():
        if snippet not in combined_metadata_files:
            errors.append(f"missing {label}")

    public_package_discovery = {
        "pyproject_include": ["citeguard", "citeguard.*"],
        "setup_find_packages_include": ["citeguard", "citeguard.*"],
        "legacy_namespace_included": False,
        "published_artifacts_exclude_legacy_src": True,
    }
    if 'include = ["citeguard", "citeguard.*"]' not in pyproject:
        errors.append("pyproject.toml package discovery must include only citeguard and citeguard.*")
    if 'find_packages(include=["citeguard", "citeguard.*"])' not in setup:
        errors.append("setup.py package discovery must include only citeguard and citeguard.*")
    legacy_namespace = "s" + "rc"
    for legacy_snippet in (f'"{legacy_namespace}"', f'"{legacy_namespace}.*"'):
        if legacy_snippet in pyproject:
            errors.append(f"pyproject.toml package discovery includes legacy namespace {legacy_snippet}")
        if legacy_snippet in setup:
            errors.append(f"setup.py package discovery includes legacy namespace {legacy_snippet}")

    required_classifiers = [
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Scientific/Engineering :: Information Analysis",
        "Topic :: Text Processing :: Linguistic",
        "Typing :: Typed",
    ]
    for classifier in required_classifiers:
        if classifier not in pyproject or classifier not in setup:
            errors.append(f"classifier not mirrored in pyproject.toml and setup.py: {classifier}")

    required_extras = ['"api"', '"mcp"', '"models"', '"pdf"', "api = [", "mcp = [", "models = [", "pdf = ["]
    for extra in required_extras:
        if extra not in combined_metadata_files:
            errors.append(f"missing optional dependency metadata: {extra}")

    required_keywords = [
        "citation-verification",
        "skeptical-citation-auditor",
        "agent-tools",
        "mcp",
        "scientific-writing",
        "claim-support",
        "research-integrity",
        "hallucination-mitigation",
        "evidence-attribution",
    ]
    for keyword in required_keywords:
        quoted = f'"{keyword}"'
        if quoted not in pyproject or quoted not in setup:
            errors.append(f"keyword not mirrored in pyproject.toml and setup.py: {keyword}")
    if '"research-agents"' in pyproject or '"research-agents"' in setup:
        errors.append("package keywords should use agent-tools, not research-agents")

    for path_label, text in (("pyproject.toml", pyproject), ("setup.py", setup)):
        metadata_lines = "\n".join(line for line in text.splitlines() if "github.com" in line or "description" in line)
        if _has_placeholder_text(metadata_lines):
            errors.append(f"{path_label} contains placeholder release metadata")

    if "CiteGuard" not in readme:
        errors.append("README.md should name CiteGuard")
    required_readme_snippets = [
        "`citeguard.*` auditor package",
        "CLI, MCP server, batch workflows, cache replay, and release gates",
        "not part of the published package surface",
        "source-checkout experiments and benchmark/API utilities",
    ]
    for snippet in required_readme_snippets:
        if snippet not in readme:
            errors.append(f"README.md missing current package-surface wording: {snippet}")
    migration_doc = _read_required_text(project_root / "docs" / "public_api_migration.md")
    required_experimental_boundary_snippets = [
        "## Experimental Source-Checkout Modules",
        "`citeguard.orchestrator`",
        "`citeguard.planner`",
        "`citeguard.writer`",
        "not the stable v0.1 product contract",
        "`citeguard.verification`",
        "`citeguard.retrieval`",
        "`citeguard.mcp`",
        "`citeguard.cli`",
        "`citeguard.runtime`",
    ]
    for snippet in required_experimental_boundary_snippets:
        if snippet not in migration_doc:
            errors.append(f"docs/public_api_migration.md missing experimental-module boundary: {snippet}")
    stale_readme_snippets = [
        "writing agent\" prototype",
        "writing-agent and benchmark surfaces",
        "research agent prototype",
        "falsification-first research agent",
    ]
    for snippet in stale_readme_snippets:
        if snippet in readme:
            errors.append(f"README.md contains stale prototype wording: {snippet}")
    if "##" not in changelog and "# " not in changelog:
        errors.append("CHANGELOG.md should contain release headings")
    required_citation_snippets = [
        'title: "CiteGuard"',
        'type: software',
        'version: "0.1.0"',
        "skeptical citation auditor for agent writing workflows",
        'repository-code: "https://github.com/xiaweiyi713/citeguard"',
        'url: "https://github.com/xiaweiyi713/citeguard#readme"',
        "citation verification",
        "skeptical citation auditor",
        "agent tools",
        "research integrity",
    ]
    for snippet in required_citation_snippets:
        if snippet not in citation:
            errors.append(f"CITATION.cff missing release metadata: {snippet}")
    stale_citation_snippets = [
        "research agent prototype",
        "research agents",
        "falsification-first research agent",
    ]
    for snippet in stale_citation_snippets:
        if snippet in citation:
            errors.append(f"CITATION.cff contains stale prototype metadata: {snippet}")
    required_launch_snippets = [
        "agent-facing skeptical citation auditor",
        "Skeptical citation auditing for agent writing workflows",
        "public `citeguard.*` Python package",
        "`citeguard` CLI",
        "`citeguard-mcp` stdio server",
        "JSON/JSONL batch audits",
        "not proof that a citation is fabricated",
        "source-health aware outputs",
        "不可达来源视为不确定性而不是伪造证据",
    ]
    for snippet in required_launch_snippets:
        if snippet not in github_launch:
            errors.append(f"docs/github_launch.md missing current launch copy: {snippet}")
    stale_launch_snippets = [
        "research prototype",
        "research agent prototype",
        "First public research prototype",
        "Agent 原型",
        "Falsification-first research agent",
    ]
    for snippet in stale_launch_snippets:
        if snippet in github_launch:
            errors.append(f"docs/github_launch.md contains stale prototype launch copy: {snippet}")
    if "MIT License" not in license_text:
        errors.append("LICENSE should contain the MIT license text")

    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "version": __version__,
        "description": pyproject_description,
        "checked_files": [
            "pyproject.toml",
            "setup.py",
            "README.md",
            "CHANGELOG.md",
            "CITATION.cff",
            "docs/github_launch.md",
            "LICENSE",
        ],
        "citation_metadata": {
            "required_phrase_count": len(required_citation_snippets),
            "stale_phrase_count": len(stale_citation_snippets),
            "policy": "CITATION.cff describes CiteGuard as a skeptical citation auditor, not a research prototype",
        },
        "readme_package_surface": {
            "required_phrase_count": len(required_readme_snippets),
            "stale_phrase_count": len(stale_readme_snippets),
            "policy": "README presents citeguard.* auditor package/CLI/MCP as the published product surface",
        },
        "experimental_module_boundary": {
            "required_phrase_count": len(required_experimental_boundary_snippets),
            "policy": "historical writing-agent modules remain source-checkout experiments, not the stable v0.1 product contract",
        },
        "github_launch_copy": {
            "required_phrase_count": len(required_launch_snippets),
            "stale_phrase_count": len(stale_launch_snippets),
            "policy": "launch copy presents CiteGuard as an agent-facing skeptical citation auditor, not a research prototype",
        },
        "package_keywords": required_keywords,
        "public_package_discovery": public_package_discovery,
        "typed_package": True,
    }


def _read_required_text(path: Path) -> str:
    if not path.exists():
        raise RuntimeError(f"missing required release file: {path.name}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise RuntimeError(f"required release file is empty: {path.name}")
    return text


def _extract_toml_string(text: str, key: str) -> str:
    match = re.search(rf"^{re.escape(key)}\s*=\s*\"([^\"]*)\"", text, flags=re.MULTILINE)
    return match.group(1) if match else ""


def _extract_python_string_kwarg(text: str, key: str) -> str:
    match = re.search(rf"\b{re.escape(key)}\s*=\s*\"([^\"]*)\"", text)
    return match.group(1) if match else ""


def _has_placeholder_text(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("todo", "tbd", "example.com", "your-name", "your-org"))


def _record_official_build_and_twine_check(
    summary: Dict[str, Any],
    *,
    python: str,
    project_root: Path,
    require_build_tools: bool,
) -> None:
    missing = [module for module in ("build", "twine") if not _module_available(python, module)]
    if missing:
        status = "failed" if require_build_tools else "skipped"
        summary["steps"].append(
            {
                "name": "pep517_build_and_twine_check",
                "status": status,
                "missing_modules": missing,
                "message": "Install release tools with `python -m pip install build twine`.",
            }
        )
        if require_build_tools:
            summary["ok"] = False
        return

    with tempfile.TemporaryDirectory(prefix="citeguard-release-dist-") as tmpdir:
        dist_dir = Path(tmpdir) / "dist"
        build_cmd = [python, "-m", "build", "--outdir", str(dist_dir), str(project_root)]
        build = _run(build_cmd, cwd=project_root)
        artifacts = sorted(dist_dir.glob("citeguard-*"))
        wheels = [path for path in artifacts if path.suffix == ".whl"]
        sdists = [path for path in artifacts if path.name.endswith(".tar.gz")]
        if len(wheels) != 1 or len(sdists) != 1:
            summary["steps"].append(
                {
                    "name": "pep517_build_and_twine_check",
                    "status": "failed",
                    "command": build_cmd,
                    "artifacts": [path.name for path in artifacts],
                    "message": "Expected exactly one wheel and one source distribution.",
                }
            )
            summary["ok"] = False
            return

        _assert_wheel_contains_core_files(wheels[0])
        _assert_sdist_contains_release_files(sdists[0])
        twine_cmd = [python, "-m", "twine", "check", *[str(path) for path in artifacts]]
        twine = _run(twine_cmd, cwd=project_root)
        summary["steps"].append(
            {
                "name": "pep517_build_and_twine_check",
                "status": "passed",
                "commands": [build_cmd, twine_cmd],
                "artifacts": [path.name for path in artifacts],
                "stdout_tail": _tail(build.stdout + "\n" + twine.stdout),
            }
        )


def _record_support_label_sidecar_gate(
    summary: Dict[str, Any],
    *,
    python: str,
    project_root: Path,
    dataset: str,
    label_sidecar: str,
    min_sidecar_coverage: float,
    min_human_reviewed: int,
    min_high_risk_reviewed: int,
    min_high_risk_reviewed_by_language: List[str],
    min_dual_annotated: int,
    max_unresolved_disagreements: int,
    min_raw_dual_agreement_rate: Optional[float],
    max_supported_disagreements: Optional[int],
) -> None:
    cmd = [
        python,
        "scripts/eval_support.py",
        "--validate-only",
        "--dataset",
        dataset,
        "--label-sidecar",
        label_sidecar,
        "--min-sidecar-coverage",
        str(min_sidecar_coverage),
        "--min-human-reviewed",
        str(min_human_reviewed),
        "--min-high-risk-reviewed",
        str(min_high_risk_reviewed),
        "--min-dual-annotated",
        str(min_dual_annotated),
        "--max-unresolved-disagreements",
        str(max_unresolved_disagreements),
    ]
    for threshold in min_high_risk_reviewed_by_language:
        cmd.extend(["--min-high-risk-reviewed-by-language", threshold])
    if min_raw_dual_agreement_rate is not None:
        cmd.extend(["--min-raw-dual-agreement-rate", str(min_raw_dual_agreement_rate)])
    if max_supported_disagreements is not None:
        cmd.extend(["--max-supported-disagreements", str(max_supported_disagreements)])
    try:
        completed = _run(cmd, cwd=project_root)
        payload = json.loads(completed.stdout)
    except subprocess.CalledProcessError as exc:
        payload = _json_payload_or_empty(exc.stdout or "")
        gate = payload.get("label_sidecar_gate", {}) if isinstance(payload, dict) else {}
        summary["steps"].append(
            {
                "name": "support_label_sidecar_gate",
                "status": "failed",
                "command": cmd,
                "thresholds": gate.get("thresholds", {}),
                "metrics": gate.get("metrics", {}),
                "failures": gate.get("failures", []),
                "stdout_tail": _tail(exc.stdout or ""),
                "stderr_tail": _tail(exc.stderr or ""),
            }
        )
        summary["ok"] = False
        return
    except json.JSONDecodeError as exc:
        summary["steps"].append(
            {
                "name": "support_label_sidecar_gate",
                "status": "failed",
                "command": cmd,
                "message": f"Could not parse eval_support.py JSON output: {exc}",
                "stdout_tail": _tail(completed.stdout),
            }
        )
        summary["ok"] = False
        return

    gate = payload.get("label_sidecar_gate", {}) if isinstance(payload, dict) else {}
    audit_fail_flag_smokes, audit_fail_flag_errors = _smoke_support_label_audit_fail_flags(
        python=python,
        project_root=project_root,
        dataset=dataset,
        label_sidecar=label_sidecar,
    )
    review_plan_smoke, review_plan_errors = _smoke_support_label_review_plan(
        python=python,
        project_root=project_root,
        dataset=dataset,
        label_sidecar=label_sidecar,
    )
    metrics = gate.get("metrics", {}) if isinstance(gate, dict) else {}
    if not isinstance(metrics, dict):
        metrics = {}
    label_provenance_errors = _support_label_provenance_contract_errors(metrics)
    passed = (
        bool(gate.get("ok"))
        and not audit_fail_flag_errors
        and not review_plan_errors
        and not label_provenance_errors
    )
    summary["steps"].append(
        {
            "name": "support_label_sidecar_gate",
            "status": "passed" if passed else "failed",
            "command": cmd,
            "thresholds": gate.get("thresholds", {}),
            "metrics": gate.get("metrics", {}),
            "failures": gate.get("failures", []),
            "audit_fail_flag_smokes": audit_fail_flag_smokes,
            "audit_fail_flag_errors": audit_fail_flag_errors,
            "review_plan_smoke": review_plan_smoke,
            "review_plan_errors": review_plan_errors,
            "label_provenance_errors": label_provenance_errors,
            "stdout_tail": _tail(completed.stdout),
        }
    )
    if not passed:
        summary["ok"] = False


def _safe_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _int_mapping(value: Any) -> Dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {str(key): _safe_int(count) for key, count in value.items()}


def _support_label_provenance_contract_errors(metrics: Dict[str, Any]) -> List[str]:
    """Keep the default seed sidecar provenance explicit in release summaries."""

    errors: List[str] = []
    label_source_counts = _int_mapping(metrics.get("label_source_counts", {}))
    reviewed_by_label_source = _int_mapping(metrics.get("reviewed_by_label_source", {}))
    unreviewed_by_label_source = _int_mapping(metrics.get("unreviewed_by_label_source", {}))
    dataset_cases = _safe_int(metrics.get("dataset_cases", 0))
    sidecar_cases = _safe_int(metrics.get("sidecar_cases", 0))
    human_reviewed = _safe_int(metrics.get("human_reviewed", 0))
    reviewed_source_locator_count = _safe_int(metrics.get("reviewed_source_locator_count", 0))
    reviewed_missing_source_locator_count = _safe_int(metrics.get("reviewed_missing_source_locator_count", 0))
    published_benchmark_source_locator_count = _safe_int(metrics.get("published_benchmark_source_locator_count", 0))
    published_benchmark = _safe_int(metrics.get("published_benchmark", 0))
    total_cases = dataset_cases or sidecar_cases or max(
        sum(label_source_counts.values()),
        sum(reviewed_by_label_source.values()) + sum(unreviewed_by_label_source.values()),
    )

    if dataset_cases and sidecar_cases and dataset_cases != sidecar_cases:
        errors.append(f"dataset_cases/sidecar_cases mismatch: {dataset_cases}!={sidecar_cases}")
    if total_cases and sum(label_source_counts.values()) != total_cases:
        errors.append(
            f"label_source_counts: expected total {total_cases}, got {sum(label_source_counts.values())}"
        )
    if total_cases and sum(reviewed_by_label_source.values()) + sum(unreviewed_by_label_source.values()) != total_cases:
        errors.append(
            "reviewed/unreviewed label-source totals: "
            f"expected {total_cases}, got {sum(reviewed_by_label_source.values()) + sum(unreviewed_by_label_source.values())}"
        )
    if human_reviewed == 0:
        expected_default = {"maintainer_synthetic": total_cases} if total_cases else {"maintainer_synthetic": 0}
        if label_source_counts != expected_default:
            errors.append(f"label_source_counts: expected {expected_default!r}, got {label_source_counts!r}")
        if reviewed_by_label_source:
            errors.append(f"reviewed_by_label_source: expected {{}}, got {reviewed_by_label_source!r}")
        if unreviewed_by_label_source != expected_default:
            errors.append(
                f"unreviewed_by_label_source: expected {expected_default!r}, got {unreviewed_by_label_source!r}"
            )
        if reviewed_source_locator_count != 0:
            errors.append(f"reviewed_source_locator_count: expected 0, got {reviewed_source_locator_count}")
        if reviewed_missing_source_locator_count != 0:
            errors.append(
                f"reviewed_missing_source_locator_count: expected 0, got {reviewed_missing_source_locator_count}"
            )
        if published_benchmark_source_locator_count != 0:
            errors.append(
                "published_benchmark_source_locator_count: "
                f"expected 0, got {published_benchmark_source_locator_count}"
            )
        if published_benchmark != 0:
            errors.append(f"published_benchmark: expected 0 when human_reviewed=0, got {published_benchmark}")
    else:
        if sum(reviewed_by_label_source.values()) != human_reviewed:
            errors.append(
                f"reviewed_by_label_source: expected total {human_reviewed}, "
                f"got {sum(reviewed_by_label_source.values())}"
            )
        if total_cases and sum(unreviewed_by_label_source.values()) != total_cases - human_reviewed:
            errors.append(
                f"unreviewed_by_label_source: expected total {total_cases - human_reviewed}, "
                f"got {sum(unreviewed_by_label_source.values())}"
            )
        if published_benchmark > human_reviewed:
            errors.append(f"published_benchmark cannot exceed human_reviewed: {published_benchmark}>{human_reviewed}")
        if published_benchmark_source_locator_count > published_benchmark:
            errors.append(
                "published_benchmark_source_locator_count cannot exceed published_benchmark: "
                f"{published_benchmark_source_locator_count}>{published_benchmark}"
            )
    return errors


def _smoke_support_label_audit_fail_flags(
    *,
    python: str,
    project_root: Path,
    dataset: str,
    label_sidecar: str,
) -> tuple[List[Dict[str, Any]], List[str]]:
    smoke_specs = [
        {
            "flag": "--fail-on-full-text-required-unreviewed",
            "expected_code": "full_text_required_unreviewed",
            "expected_case_ids": ["s17", "s30", "s43", "s13", "s38", "s20", "s33"],
            "expected_metric": "full_text_required_unreviewed_count",
        },
        {
            "flag": "--fail-on-policy-boundary-unreviewed",
            "expected_code": "policy_boundary_unreviewed",
            "expected_case_ids": ["ss02", "ss05"],
            "expected_metric": "policy_boundary_unreviewed_count",
        },
    ]
    smokes: List[Dict[str, Any]] = []
    errors: List[str] = []
    for spec in smoke_specs:
        cmd = [
            python,
            "scripts/prepare_support_label_sidecar.py",
            "--dataset",
            dataset,
            "--existing-sidecar",
            label_sidecar,
            "--audit",
            spec["flag"],
        ]
        completed = _run_no_check(cmd, cwd=project_root)
        if completed.returncode != 0:
            payload = _json_payload_or_empty(completed.stdout or "")
            audit_gate = payload.get("audit_gate", {}) if isinstance(payload, dict) else {}
            failures = audit_gate.get("failures", []) if isinstance(audit_gate, dict) else []
            failure_by_code = {
                str(failure.get("code", "")): failure
                for failure in failures
                if isinstance(failure, dict)
            }
            failure = failure_by_code.get(str(spec["expected_code"]), {})
            actual_case_ids = list(failure.get("case_ids", []) or []) if isinstance(failure, dict) else []
            metric_value = None
            metrics = audit_gate.get("metrics", {}) if isinstance(audit_gate, dict) else {}
            if isinstance(metrics, dict):
                metric_value = metrics.get(str(spec["expected_metric"]))
            passed = (
                completed.returncode == 1
                and isinstance(audit_gate, dict)
                and audit_gate.get("ok") is False
                and actual_case_ids == spec["expected_case_ids"]
                and metric_value == len(spec["expected_case_ids"])
            )
            if not passed:
                errors.append(f"audit_fail_flag_smoke_failed:{spec['flag']}")
            smokes.append(
                {
                    "flag": spec["flag"],
                    "command": cmd,
                    "exit_code": completed.returncode,
                    "expected_code": spec["expected_code"],
                    "actual_codes": [str(failure.get("code", "")) for failure in failures if isinstance(failure, dict)],
                    "case_ids": actual_case_ids,
                    "metric": spec["expected_metric"],
                    "metric_value": metric_value,
                    "status": "passed" if passed else "failed",
                    "stdout_tail": _tail(completed.stdout or ""),
                    "stderr_tail": _tail(completed.stderr or ""),
                }
            )
        else:
            errors.append(f"audit_fail_flag_did_not_fail:{spec['flag']}")
            payload = _json_payload_or_empty(completed.stdout or "")
            audit_gate = payload.get("audit_gate", {}) if isinstance(payload, dict) else {}
            smokes.append(
                {
                    "flag": spec["flag"],
                    "command": cmd,
                    "exit_code": completed.returncode,
                    "expected_code": spec["expected_code"],
                    "actual_codes": [
                        str(failure.get("code", ""))
                        for failure in audit_gate.get("failures", [])
                        if isinstance(failure, dict)
                    ]
                    if isinstance(audit_gate, dict)
                    else [],
                    "case_ids": [],
                    "metric": spec["expected_metric"],
                    "metric_value": None,
                    "status": "failed",
                    "stdout_tail": _tail(completed.stdout),
                    "stderr_tail": _tail(completed.stderr),
                }
            )
    return smokes, errors


def _smoke_support_label_review_plan(
    *,
    python: str,
    project_root: Path,
    dataset: str,
    label_sidecar: str,
) -> tuple[Dict[str, Any], List[str]]:
    cmd = [
        python,
        "scripts/prepare_support_label_sidecar.py",
        "--dataset",
        dataset,
        "--existing-sidecar",
        label_sidecar,
        "--audit",
    ]
    completed = _run_no_check(cmd, cwd=project_root)
    payload = _json_payload_or_empty(completed.stdout or "")
    review_plan = payload.get("review_plan", {}) if isinstance(payload, dict) else {}
    recommended_packets = payload.get("recommended_packets", []) if isinstance(payload, dict) else []
    recommended_by_id = {
        str(packet.get("id", "")): packet
        for packet in recommended_packets
        if isinstance(packet, dict) and packet.get("id")
    }
    phases = review_plan.get("phases", []) if isinstance(review_plan, dict) else []
    phase_by_id = {
        str(phase.get("id", "")): phase
        for phase in phases
        if isinstance(phase, dict) and phase.get("id")
    }
    first_review = phase_by_id.get("first_review_high_risk", {})
    second_review = phase_by_id.get("second_review", {})
    adjudication = phase_by_id.get("adjudication", {})
    release_gates = phase_by_id.get("raise_release_gates", {})
    first_packet_ids = list(first_review.get("recommended_packet_ids", []) or []) if isinstance(first_review, dict) else []
    first_case_ids = list(first_review.get("candidate_case_ids", []) or []) if isinstance(first_review, dict) else []
    audit_language_case_type = (
        payload.get("high_risk_unreviewed_by_language_case_type", {})
        if isinstance(payload, dict)
        else {}
    )
    plan_language_case_type = (
        review_plan.get("high_risk_unreviewed_by_language_case_type", {})
        if isinstance(review_plan, dict)
        else {}
    )
    first_review_language_case_type = (
        first_review.get("candidate_case_count_by_language_case_type", {})
        if isinstance(first_review, dict)
        else {}
    )
    language_case_type_packet_ids = _expected_high_risk_language_case_type_packet_ids(audit_language_case_type)
    high_risk_count = _safe_int(review_plan.get("high_risk_unreviewed")) if isinstance(review_plan, dict) else 0
    full_text_count = _safe_int(review_plan.get("full_text_required_unreviewed")) if isinstance(review_plan, dict) else 0
    policy_boundary_count = _safe_int(review_plan.get("policy_boundary_unreviewed")) if isinstance(review_plan, dict) else 0
    first_review_count = _safe_int(first_review.get("candidate_case_count")) if isinstance(first_review, dict) else 0
    high_risk_packet = recommended_by_id.get("high_risk_unreviewed_balanced", {})
    full_text_packet = recommended_by_id.get("full_text_required_unreviewed", {})
    policy_boundary_packet = recommended_by_id.get("policy_boundary_unreviewed", {})
    policy_boundary_case_ids = list(policy_boundary_packet.get("candidate_case_ids", []) or [])
    errors: List[str] = []
    if completed.returncode != 0:
        errors.append("review_plan_audit_failed")
    if not isinstance(review_plan, dict) or review_plan.get("schema_version") != 1:
        errors.append("review_plan_schema_missing")
    if review_plan.get("next_phase") != "first_review_high_risk":
        errors.append("review_plan_next_phase_mismatch")
    if high_risk_count <= 0:
        errors.append("review_plan_high_risk_count_missing")
    if high_risk_count != _safe_int(high_risk_packet.get("candidate_case_count")):
        errors.append("review_plan_high_risk_packet_count_mismatch")
    if full_text_count != _safe_int(full_text_packet.get("candidate_case_count")):
        errors.append("review_plan_full_text_packet_count_mismatch")
    if policy_boundary_count != _safe_int(policy_boundary_packet.get("candidate_case_count")):
        errors.append("review_plan_policy_boundary_packet_count_mismatch")
    if first_review.get("status") != "ready":
        errors.append("review_plan_first_review_not_ready")
    if first_review_count != high_risk_count + policy_boundary_count:
        errors.append("review_plan_first_review_count_mismatch")
    if not isinstance(audit_language_case_type, dict) or not audit_language_case_type:
        errors.append("review_plan_language_case_type_audit_missing")
    if plan_language_case_type != audit_language_case_type:
        errors.append("review_plan_language_case_type_mismatch")
    if first_review_language_case_type != audit_language_case_type:
        errors.append("review_plan_phase_language_case_type_mismatch")
    if len(first_packet_ids) != len(set(first_packet_ids)):
        errors.append("review_plan_duplicate_packet_ids")
    for packet_id in (
        "high_risk_unreviewed_balanced",
        "full_text_required_unreviewed",
        "policy_boundary_unreviewed",
    ):
        if packet_id not in first_packet_ids:
            errors.append(f"review_plan_missing_packet:{packet_id}")
        if packet_id not in recommended_by_id:
            errors.append(f"review_plan_missing_recommended_packet:{packet_id}")
    recommended_packet_errors = _support_label_recommended_packet_contract_errors(
        first_packet_ids,
        recommended_by_id,
        audit_language_case_type,
    )
    errors.extend(recommended_packet_errors)
    recommended_packet_smoke = _smoke_support_label_recommended_packet(
        python=python,
        project_root=project_root,
        packet=recommended_by_id.get("high_risk_unreviewed_balanced", {}),
    )
    errors.extend(recommended_packet_smoke.get("errors", []))
    language_case_type_smoke_spec = _first_high_risk_language_case_type_packet_spec(audit_language_case_type)
    language_case_type_packet_smoke = _smoke_support_label_language_case_type_packet(
        python=python,
        project_root=project_root,
        packet=recommended_by_id.get(str(language_case_type_smoke_spec.get("packet_id", "")), {}),
        expected=language_case_type_smoke_spec,
    )
    errors.extend(language_case_type_packet_smoke.get("errors", []))
    if policy_boundary_case_ids and not set(policy_boundary_case_ids).issubset(set(first_case_ids)):
        errors.append("review_plan_missing_policy_boundary_cases")
    if second_review.get("status") != "waiting_for_first_review":
        errors.append("review_plan_second_review_status_mismatch")
    if adjudication.get("status") != "waiting_for_dual_annotation":
        errors.append("review_plan_adjudication_status_mismatch")
    if "--apply-adjudications" not in list(adjudication.get("command_template", []) or []):
        errors.append("review_plan_adjudication_command_missing")
    if release_gates.get("status") != "blocked":
        errors.append("review_plan_release_gate_status_mismatch")
    if "--max-supported-disagreements" not in list(release_gates.get("command_template", []) or []):
        errors.append("review_plan_release_command_missing_supported_disagreement_gate")

    return (
        {
            "command": cmd,
            "exit_code": completed.returncode,
            "status": "passed" if not errors else "failed",
            "next_phase": review_plan.get("next_phase") if isinstance(review_plan, dict) else None,
            "high_risk_unreviewed": high_risk_count,
            "full_text_required_unreviewed": full_text_count,
            "policy_boundary_unreviewed": policy_boundary_count,
            "high_risk_unreviewed_by_language_case_type": audit_language_case_type
            if isinstance(audit_language_case_type, dict)
            else {},
            "first_review_candidate_count": first_review_count,
            "first_review_candidate_count_by_language_case_type": first_review_language_case_type
            if isinstance(first_review_language_case_type, dict)
            else {},
            "first_review_packet_ids": first_packet_ids,
            "language_case_type_packet_ids": language_case_type_packet_ids,
            "policy_boundary_case_ids": policy_boundary_case_ids,
            "recommended_packet_ids": sorted(recommended_by_id),
            "recommended_packet_errors": recommended_packet_errors,
            "recommended_packet_smoke": recommended_packet_smoke,
            "language_case_type_packet_smoke": language_case_type_packet_smoke,
            "release_gate_status": release_gates.get("status") if isinstance(release_gates, dict) else None,
            "stdout_tail": _tail(completed.stdout or ""),
            "stderr_tail": _tail(completed.stderr or ""),
        },
        errors,
    )


def _support_label_recommended_packet_contract_errors(
    first_packet_ids: List[str],
    recommended_by_id: Dict[str, Dict[str, Any]],
    high_risk_by_language_case_type: Any,
) -> List[str]:
    errors: List[str] = []
    for packet_id in first_packet_ids:
        packet = recommended_by_id.get(packet_id)
        if not isinstance(packet, dict):
            continue
        command = list(packet.get("command", []) or [])
        output = str(packet.get("output", ""))
        instructions_output = str(packet.get("instructions_output", ""))
        if "--annotation-packet" not in command:
            errors.append(f"review_plan_packet_missing_annotation_flag:{packet_id}")
        if "--review-phase" not in command:
            errors.append(f"review_plan_packet_missing_review_phase:{packet_id}")
        if "--packet-purpose" not in command:
            errors.append(f"review_plan_packet_missing_purpose:{packet_id}")
        if "--unreviewed-only" not in command:
            errors.append(f"review_plan_packet_missing_unreviewed_only:{packet_id}")
        if not output.startswith("experiments/") or "--output" not in command or output not in command:
            errors.append(f"review_plan_packet_output_contract:{packet_id}")
        if (
            not instructions_output.startswith("experiments/")
            or "--instructions-output" not in command
            or instructions_output not in command
        ):
            errors.append(f"review_plan_packet_instructions_contract:{packet_id}")
    balanced = recommended_by_id.get("high_risk_unreviewed_balanced", {})
    balanced_command = list(balanced.get("command", []) or []) if isinstance(balanced, dict) else []
    for flag in ("--limit-per-language", "--limit-per-case-type", "--limit-per-evidence-scope"):
        if flag not in balanced_command:
            errors.append(f"review_plan_balanced_packet_missing:{flag}")
    errors.extend(
        _support_label_language_case_type_packet_errors(
            first_packet_ids,
            recommended_by_id,
            high_risk_by_language_case_type,
        )
    )
    return errors


def _support_label_language_case_type_packet_errors(
    first_packet_ids: List[str],
    recommended_by_id: Dict[str, Dict[str, Any]],
    high_risk_by_language_case_type: Any,
) -> List[str]:
    errors: List[str] = []
    if not isinstance(high_risk_by_language_case_type, dict) or not high_risk_by_language_case_type:
        return errors
    for language, by_case_type in sorted(high_risk_by_language_case_type.items()):
        if not isinstance(by_case_type, dict):
            errors.append(f"review_plan_language_case_type_table_invalid:{language}")
            continue
        language = str(language)
        for case_type, count_value in sorted(by_case_type.items()):
            count = _safe_int(count_value)
            if count <= 0:
                continue
            case_type = str(case_type)
            packet_id = _high_risk_language_case_type_packet_id(language, case_type)
            if packet_id not in first_packet_ids:
                errors.append(f"review_plan_missing_language_case_type_packet:{packet_id}")
            packet = recommended_by_id.get(packet_id)
            if not isinstance(packet, dict):
                errors.append(f"review_plan_missing_recommended_packet:{packet_id}")
                continue
            command = list(packet.get("command", []) or [])
            if _safe_int(packet.get("candidate_case_count")) != count:
                errors.append(f"review_plan_language_case_type_packet_count_mismatch:{packet_id}")
            for expected in ("--priority", "high", "--lang", language, "--case-type", case_type, "--unreviewed-only"):
                if expected not in command:
                    errors.append(f"review_plan_language_case_type_packet_command_missing:{packet_id}:{expected}")
    return errors


def _expected_high_risk_language_case_type_packet_ids(high_risk_by_language_case_type: Any) -> List[str]:
    if not isinstance(high_risk_by_language_case_type, dict):
        return []
    packet_ids: List[str] = []
    for language, by_case_type in sorted(high_risk_by_language_case_type.items()):
        if not isinstance(by_case_type, dict):
            continue
        for case_type, count_value in sorted(by_case_type.items()):
            if _safe_int(count_value) > 0:
                packet_ids.append(_high_risk_language_case_type_packet_id(str(language), str(case_type)))
    return packet_ids


def _first_high_risk_language_case_type_packet_spec(high_risk_by_language_case_type: Any) -> Dict[str, Any]:
    if not isinstance(high_risk_by_language_case_type, dict):
        return {}
    for language, by_case_type in sorted(high_risk_by_language_case_type.items()):
        if not isinstance(by_case_type, dict):
            continue
        for case_type, count_value in sorted(by_case_type.items()):
            count = _safe_int(count_value)
            if count > 0:
                language = str(language)
                case_type = str(case_type)
                return {
                    "packet_id": _high_risk_language_case_type_packet_id(language, case_type),
                    "language": language,
                    "case_type": case_type,
                    "expected_count": count,
                }
    return {}


def _high_risk_language_case_type_packet_id(language: str, case_type: str) -> str:
    return f"high_risk_unreviewed_{_packet_slug(language)}_{_packet_slug(case_type)}"


def _packet_slug(value: str) -> str:
    slug = []
    for character in str(value).strip().lower():
        if character.isalnum():
            slug.append(character)
        elif slug and slug[-1] != "_":
            slug.append("_")
    return "".join(slug).strip("_") or "unknown"


def _smoke_support_label_recommended_packet(
    *,
    python: str,
    project_root: Path,
    packet: Dict[str, Any],
) -> Dict[str, Any]:
    packet_id = str(packet.get("id", "")) if isinstance(packet, dict) else ""
    command = list(packet.get("command", []) or []) if isinstance(packet, dict) else []
    if not packet_id or not command:
        return {
            "status": "failed",
            "packet_id": packet_id,
            "errors": ["review_plan_recommended_packet_smoke_missing"],
        }

    with tempfile.TemporaryDirectory(prefix="citeguard-review-plan-packet-") as tmpdir:
        packet_path = Path(tmpdir) / "recommended-packet.json"
        instructions_path = Path(tmpdir) / "recommended-packet-instructions.md"
        smoke_cmd = _rewrite_support_label_packet_command(
            command,
            python=python,
            output_path=packet_path,
            instructions_path=instructions_path,
        )
        completed = _run_no_check(smoke_cmd, cwd=project_root)
        packet_text = _read_text_if_exists(packet_path)
        instructions_text = _read_text_if_exists(instructions_path)
        if not packet_text:
            packet_text = completed.stdout or ""
        try:
            payload = json.loads(packet_text)
        except json.JSONDecodeError:
            payload = {}

    errors: List[str] = []
    if completed.returncode != 0:
        errors.append("review_plan_recommended_packet_smoke_failed")
    if not isinstance(payload, dict) or not payload.get("ok"):
        errors.append("review_plan_recommended_packet_payload_not_ok")
    if payload.get("packet_type") != "support_label_annotation_packet":
        errors.append("review_plan_recommended_packet_type_mismatch")
    packet_summary = payload.get("packet_summary", {}) if isinstance(payload, dict) else {}
    cases = payload.get("cases", []) if isinstance(payload, dict) else []
    review_status_counts = (
        packet_summary.get("case_count_by_review_status", {}) if isinstance(packet_summary, dict) else {}
    )
    review_phase = str(payload.get("review_phase", "")) if isinstance(payload, dict) else ""
    packet_purpose = str(payload.get("packet_purpose", "")) if isinstance(payload, dict) else ""
    if not isinstance(cases, list) or not cases:
        errors.append("review_plan_recommended_packet_empty")
    if review_phase != "first_review_high_risk":
        errors.append("review_plan_recommended_packet_phase_missing")
    if not packet_purpose:
        errors.append("review_plan_recommended_packet_purpose_missing")
    if any(
        isinstance(item, dict) and item.get("review_phase") != review_phase
        for item in cases
    ):
        errors.append("review_plan_recommended_packet_case_phase_mismatch")
    if not review_status_counts:
        errors.append("review_plan_recommended_packet_missing_review_status_counts")
    if "not_human_reviewed" not in review_status_counts:
        errors.append("review_plan_recommended_packet_missing_unreviewed_cases")
    forbidden_keys = ("gold", "predicted", "adjudicated_label", "annotator_labels", "label_notes", "dataset_gold")
    hidden_fields = payload.get("hidden_fields", []) if isinstance(payload, dict) else []
    leaked_fields = _hidden_annotation_packet_key_leaks(cases, forbidden_keys)
    if not set(hidden_fields) >= {"gold", "predicted", "adjudicated_label", "annotator_labels", "label_notes"}:
        errors.append("review_plan_recommended_packet_missing_hidden_fields")
    if leaked_fields:
        errors.append("review_plan_recommended_packet_hidden_field_leak")
    if "Packet summary" not in instructions_text:
        errors.append("review_plan_recommended_packet_instructions_missing_summary")
    scope_annotation_fields_present = bool(cases) and all(
        isinstance(item, dict)
        and isinstance(item.get("annotation"), dict)
        and "evidence_scope_assessed" in item["annotation"]
        and "full_text_needed" in item["annotation"]
        for item in cases
    )
    if not scope_annotation_fields_present:
        errors.append("review_plan_recommended_packet_missing_scope_annotation_fields")
    if "evidence_scope_assessed" not in instructions_text or "full_text_needed" not in instructions_text:
        errors.append("review_plan_recommended_packet_instructions_missing_scope_fields")

    return {
        "status": "passed" if not errors else "failed",
        "packet_id": packet_id,
        "command": smoke_cmd,
        "exit_code": completed.returncode,
        "case_count": payload.get("n") if isinstance(payload, dict) else None,
        "review_phase": review_phase,
        "packet_purpose": packet_purpose,
        "case_count_by_review_status": review_status_counts,
        "case_count_by_language": packet_summary.get("case_count_by_language", {})
        if isinstance(packet_summary, dict)
        else {},
        "case_count_by_case_type": packet_summary.get("case_count_by_case_type", {})
        if isinstance(packet_summary, dict)
        else {},
        "case_ids": packet_summary.get("case_ids", []) if isinstance(packet_summary, dict) else [],
        "hidden_fields": hidden_fields,
        "leaked_hidden_fields": leaked_fields,
        "scope_annotation_fields_present": scope_annotation_fields_present,
        "errors": errors,
        "stdout_tail": _tail(completed.stdout or ""),
        "stderr_tail": _tail(completed.stderr or ""),
    }


def _smoke_support_label_language_case_type_packet(
    *,
    python: str,
    project_root: Path,
    packet: Dict[str, Any],
    expected: Dict[str, Any],
) -> Dict[str, Any]:
    if not expected:
        return {
            "status": "skipped",
            "errors": [],
            "message": "No high-risk language/case-type slice packet expected.",
        }
    smoke = _smoke_support_label_recommended_packet(
        python=python,
        project_root=project_root,
        packet=packet,
    )
    errors = list(smoke.get("errors", []) or [])
    expected_count = _safe_int(expected.get("expected_count"))
    expected_language_counts = {str(expected.get("language")): expected_count}
    expected_case_type_counts = {str(expected.get("case_type")): expected_count}
    if smoke.get("packet_id") != expected.get("packet_id"):
        errors.append("review_plan_language_case_type_packet_smoke_id_mismatch")
    if _safe_int(smoke.get("case_count")) != expected_count:
        errors.append("review_plan_language_case_type_packet_smoke_count_mismatch")
    if smoke.get("case_count_by_language") != expected_language_counts:
        errors.append("review_plan_language_case_type_packet_smoke_language_mismatch")
    if smoke.get("case_count_by_case_type") != expected_case_type_counts:
        errors.append("review_plan_language_case_type_packet_smoke_case_type_mismatch")
    return {
        **smoke,
        "status": "passed" if not errors else "failed",
        "expected": dict(expected),
        "expected_case_count_by_language": expected_language_counts,
        "expected_case_count_by_case_type": expected_case_type_counts,
        "errors": errors,
    }


def _rewrite_support_label_packet_command(
    command: List[str],
    *,
    python: str,
    output_path: Path,
    instructions_path: Path,
) -> List[str]:
    rewritten = list(command)
    if rewritten:
        rewritten[0] = python
    for flag, path in (("--output", output_path), ("--instructions-output", instructions_path)):
        if flag in rewritten:
            rewritten[rewritten.index(flag) + 1] = str(path)
        else:
            rewritten.extend([flag, str(path)])
    return rewritten


def _read_text_if_exists(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _record_benchmark_claim_safety_gate(
    summary: Dict[str, Any],
    *,
    project_root: Path,
    dataset: str,
    label_sidecar: str,
) -> None:
    try:
        details = _check_benchmark_claim_safety_gate(
            project_root=project_root,
            dataset=dataset,
            label_sidecar=label_sidecar,
        )
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "benchmark_claim_safety",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append(
        {
            "name": "benchmark_claim_safety",
            "status": "passed",
            **details,
        }
    )


def _check_benchmark_claim_safety_gate(*, project_root: Path, dataset: str, label_sidecar: str) -> Dict[str, Any]:
    from citeguard.verification.support_eval import (
        load_support_label_cases,
        load_support_label_sidecar,
        validate_support_label_sidecar,
    )

    dataset_path = project_root / dataset
    raw_dataset = json.loads(_read_required_text(dataset_path))
    evidence_case_count = len(raw_dataset.get("cases", []))
    citation_set_case_count = len(raw_dataset.get("set_cases", []))
    cases = load_support_label_cases(str(project_root / dataset))
    sidecar = load_support_label_sidecar(str(project_root / label_sidecar), cases)
    raw_sidecar = json.loads(_read_required_text(project_root / label_sidecar))
    sidecar_summary = validate_support_label_sidecar(raw_sidecar, cases)
    sidecar_case_provenance = sidecar_summary.get("sidecar_case_provenance", {})
    human_reviewed = sum(1 for item in sidecar if item.adjudication_status != "not_human_reviewed")
    dual_annotated = sum(1 for item in sidecar if item.annotator_count >= 2)
    published_benchmark = sum(1 for item in sidecar if item.adjudication_status == "published_benchmark")

    release_docs = {
        "README.md": project_root / "README.md",
        "CHANGELOG.md": project_root / "CHANGELOG.md",
        "ROADMAP.md": project_root / "ROADMAP.md",
        "docs/benchmark_design.md": project_root / "docs" / "benchmark_design.md",
        "docs/benchmark_todo.md": project_root / "docs" / "benchmark_todo.md",
        "docs/github_launch.md": project_root / "docs" / "github_launch.md",
        "docs/release_checklist.md": project_root / "docs" / "release_checklist.md",
        "docs/support_eval.md": project_root / "docs" / "support_eval.md",
        "docs/support_labeling_guidelines.md": project_root / "docs" / "support_labeling_guidelines.md",
        "scripts/eval_support.py": project_root / "scripts" / "eval_support.py",
        "skills/citeguard-verify/references/examples.md": (
            project_root / "skills" / "citeguard-verify" / "references" / "examples.md"
        ),
    }
    releases_dir = project_root / "docs" / "releases"
    if releases_dir.exists():
        for path in sorted(releases_dir.glob("*.md")):
            release_docs[str(path.relative_to(project_root))] = path

    occurrences = []
    unsafe_occurrences = []
    for label, path in release_docs.items():
        for occurrence in _human_reviewed_benchmark_occurrences(_read_required_text(path), label):
            occurrences.append(occurrence)
            if human_reviewed == 0 and not occurrence["qualified_as_not_ready"]:
                unsafe_occurrences.append(occurrence)

    required_guard_docs = {
        "README.md": "not a final human-reviewed benchmark",
        "docs/release_checklist.md": "should not call it a human-reviewed benchmark",
        "docs/benchmark_todo.md": "not a human-reviewed benchmark",
    }
    required_count_docs = {
        "docs/support_eval.md": f"{evidence_case_count} evidence-level cases plus {citation_set_case_count} citation-set",
        "CHANGELOG.md": f"{evidence_case_count} evidence-level cases",
    }
    errors = [
        f"{label} missing guard phrase: {phrase}"
        for label, phrase in required_guard_docs.items()
        if _normalize_markdown_text(phrase) not in _normalize_markdown_text(_read_required_text(project_root / label))
    ]
    errors.extend(
        f"{label} missing current seed-count phrase: {phrase}"
        for label, phrase in required_count_docs.items()
        if _normalize_markdown_text(phrase) not in _normalize_markdown_text(_read_required_text(project_root / label))
    )
    if evidence_case_count + citation_set_case_count != len(cases):
        errors.append(
            "support seed raw counts do not match loaded support cases: "
            f"{evidence_case_count}+{citation_set_case_count}!={len(cases)}"
        )
    if sidecar_case_provenance.get("complete_count") != len(cases):
        errors.append("support label sidecar should copy label_source, case_type, evidence_scope, split, and lang for every case")
    if sidecar_case_provenance.get("missing_count") != 0 or sidecar_case_provenance.get("missing_case_ids"):
        errors.append("support label sidecar should include every dataset case_id exactly once before benchmark claims")
    if unsafe_occurrences:
        errors.append(
            "release-facing docs contain unqualified human-reviewed benchmark claims while human_reviewed=0: "
            + ", ".join(f"{item['path']}:{item['line']}" for item in unsafe_occurrences)
        )
    if human_reviewed == 0 and published_benchmark:
        errors.append("published_benchmark sidecar status cannot appear when human_reviewed=0")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "dataset": dataset,
        "label_sidecar": label_sidecar,
        "case_count": len(cases),
        "evidence_case_count": evidence_case_count,
        "citation_set_case_count": citation_set_case_count,
        "sidecar_case_count": len(sidecar),
        "sidecar_case_provenance": sidecar_case_provenance,
        "human_reviewed": human_reviewed,
        "dual_annotated": dual_annotated,
        "published_benchmark": published_benchmark,
        "release_docs_checked": sorted(release_docs),
        "human_reviewed_benchmark_occurrences": occurrences,
        "unsafe_human_reviewed_benchmark_claims": unsafe_occurrences,
        "policy": "do not describe the synthetic seed set as a human-reviewed benchmark until sidecar maturity proves it",
    }


def _human_reviewed_benchmark_occurrences(text: str, path_label: str) -> List[Dict[str, Any]]:
    pattern = re.compile(r"\bhuman[- ]reviewed\s+(?:support\s+)?benchmarks?\b", re.IGNORECASE)
    qualifier_pattern = re.compile(
        r"\b(not|not yet|not a|not final|should not|until|before|cannot|can't|synthetic|future|when|after|exists)\b",
        re.IGNORECASE,
    )
    occurrences: List[Dict[str, Any]] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if not pattern.search(line):
            continue
        context = " ".join(lines[max(0, index - 2) : min(len(lines), index + 3)])
        occurrences.append(
            {
                "path": path_label,
                "line": index + 1,
                "text": line.strip(),
                "qualified_as_not_ready": bool(qualifier_pattern.search(context)),
            }
        )
    return occurrences


def _normalize_markdown_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _record_support_review_queue_gate(
    summary: Dict[str, Any],
    *,
    python: str,
    project_root: Path,
    dataset: str,
    label_sidecar: str,
) -> None:
    cmd = [
        python,
        "scripts/eval_support.py",
        "--dataset",
        dataset,
        "--split",
        "test",
        "--backend",
        "fixture",
        "--quality-gate",
        "--label-sidecar",
        label_sidecar,
        "--review-queue-only",
    ]
    artifact_manifest: Dict[str, Any] = {}
    manifest_errors: List[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="citeguard-support-review-") as tmpdir:
            cmd.extend(
                [
                    "--output-dir",
                    tmpdir,
                    "--run-id",
                    "release-support-review-queue",
                ]
            )
            completed = _run(cmd, cwd=project_root)
            payload = json.loads(completed.stdout)
            artifact_manifest, manifest_errors = _load_experiment_artifact_manifest(payload)
    except subprocess.CalledProcessError as exc:
        payload = _json_payload_or_empty(exc.stdout or "")
        quality_gate = payload.get("quality_gate", {}) if isinstance(payload, dict) else {}
        summary["steps"].append(
            {
                "name": "support_review_queue",
                "status": "failed",
                "command": cmd,
                "review_queue_case_ids": quality_gate.get("review_queue_case_ids", []),
                "critical_review_case_ids": quality_gate.get("critical_review_case_ids", []),
                "failures": quality_gate.get("failures", []),
                "stdout_tail": _tail(exc.stdout or ""),
                "stderr_tail": _tail(exc.stderr or ""),
            }
        )
        summary["ok"] = False
        return
    except json.JSONDecodeError as exc:
        summary["steps"].append(
            {
                "name": "support_review_queue",
                "status": "failed",
                "command": cmd,
                "message": f"Could not parse eval_support.py review queue JSON output or artifact manifest: {exc}",
                "stdout_tail": _tail(completed.stdout) if "completed" in locals() else [],
            }
        )
        summary["ok"] = False
        return
    except (OSError, KeyError, TypeError) as exc:
        summary["steps"].append(
            {
                "name": "support_review_queue",
                "status": "failed",
                "command": cmd,
                "message": f"Could not read support review queue experiment artifact manifest: {exc}",
                "stdout_tail": _tail(completed.stdout) if "completed" in locals() else [],
            }
        )
        summary["ok"] = False
        return

    quality_gate = payload.get("quality_gate", {}) if isinstance(payload, dict) else {}
    review_queue = payload.get("review_queue", []) if isinstance(payload, dict) else []
    review_queue_summary = payload.get("review_queue_summary", {}) if isinstance(payload, dict) else {}
    release_blocker_summary = payload.get("release_blocker_summary", {}) if isinstance(payload, dict) else {}
    false_support_analysis = payload.get("false_support_analysis", {}) if isinstance(payload, dict) else {}
    acceptance_guard = payload.get("acceptance_guard", {}) if isinstance(payload, dict) else {}
    if (not isinstance(acceptance_guard, dict) or not acceptance_guard) and isinstance(false_support_analysis, dict):
        acceptance_guard = false_support_analysis.get("acceptance_guard", {})
    acceptance_slices = payload.get("acceptance_slices", []) if isinstance(payload, dict) else []
    abstention_analysis = payload.get("abstention_analysis", {}) if isinstance(payload, dict) else {}
    label_sidecar_gate = payload.get("label_sidecar_gate", {}) if isinstance(payload, dict) else {}
    label_maturity = payload.get("label_maturity", {}) if isinstance(payload, dict) else {}
    support_set_policy = payload.get("support_set_policy", {}) if isinstance(payload, dict) else {}
    release_summary = payload.get("release_summary", {}) if isinstance(payload, dict) else {}
    limited_review_queue: Dict[str, Any] = {}
    limited_review_queue_errors: List[str] = []
    limited_cmd = [
        python,
        "scripts/eval_support.py",
        "--dataset",
        dataset,
        "--split",
        "test",
        "--backend",
        "heuristic",
        "--review-queue-only",
        "--review-queue-limit",
        "2",
    ]
    try:
        limited_completed = _run(limited_cmd, cwd=project_root)
        limited_payload = json.loads(limited_completed.stdout)
        limited_review_queue = (
            limited_payload.get("review_queue_filtered", {})
            if isinstance(limited_payload, dict)
            else {}
        )
        limited_summary = (
            limited_payload.get("review_queue_summary", {})
            if isinstance(limited_payload, dict)
            else {}
        )
        limited_rows = limited_payload.get("review_queue", []) if isinstance(limited_payload, dict) else []
        if limited_payload.get("review_queue_limit") != 2:
            limited_review_queue_errors.append("limit_payload_missing_requested_limit")
        if not isinstance(limited_rows, list) or len(limited_rows) != 2:
            limited_review_queue_errors.append("limited_review_queue_should_return_two_rows")
        if not isinstance(limited_summary, dict) or limited_review_queue.get("original_count") != limited_summary.get("count"):
            limited_review_queue_errors.append("limited_review_queue_original_count_mismatch")
        if limited_review_queue.get("returned") != 2:
            limited_review_queue_errors.append("limited_review_queue_returned_count_mismatch")
        if int(limited_review_queue.get("omitted", 0) or 0) <= 0:
            limited_review_queue_errors.append("limited_review_queue_should_report_omitted_rows")
        if limited_review_queue.get("policy") != "review_queue_summary_and_quality_gate_counts_remain_full_queue":
            limited_review_queue_errors.append("limited_review_queue_policy_missing")
    except (subprocess.CalledProcessError, json.JSONDecodeError, TypeError, ValueError) as exc:
        limited_review_queue_errors.append(f"limited_review_queue_probe_failed:{exc}")
    manifest_result_summary = _artifact_manifest_result_summary(artifact_manifest, manifest_errors)
    has_false_support_triage = (
        isinstance(false_support_analysis, dict)
        and isinstance(false_support_analysis.get("risk_slices"), list)
        and "top_risk_slice" in false_support_analysis
        and _has_false_support_review_plan(false_support_analysis.get("review_plan"))
    )
    has_acceptance_guard = (
        isinstance(acceptance_guard, dict)
        and isinstance(acceptance_guard.get("ok_to_accept_supported"), bool)
        and isinstance(acceptance_guard.get("block_acceptance_case_ids"), list)
        and isinstance(acceptance_guard.get("review_before_accepting_case_ids"), list)
        and acceptance_guard.get("policy")
    )
    has_acceptance_slices = _has_support_acceptance_slices(acceptance_slices)
    has_abstention_analysis = (
        isinstance(abstention_analysis, dict)
        and "incorrect_abstention_count" in abstention_analysis
        and "correct_abstention_count" in abstention_analysis
        and isinstance(abstention_analysis.get("review_case_ids"), list)
    )
    has_release_blocker_summary = (
        isinstance(release_blocker_summary, dict)
        and isinstance(release_blocker_summary.get("release_blocked"), bool)
        and isinstance(release_blocker_summary.get("benchmark_claim_safe"), bool)
        and isinstance(release_blocker_summary.get("blocking_case_ids"), list)
        and isinstance(release_blocker_summary.get("review_required_case_ids"), list)
        and release_blocker_summary.get("next_action")
    )
    has_label_maturity = (
        isinstance(label_maturity, dict)
        and "human_reviewed" in label_maturity
        and "dual_annotated" in label_maturity
        and isinstance(label_maturity.get("supported_disagreement_case_ids"), list)
    )
    manifest_false_support_triage_present, review_manifest_errors = _validate_support_review_manifest_summary(
        manifest_result_summary,
        false_support_analysis,
        acceptance_slices,
        abstention_analysis,
        release_blocker_summary,
    )
    manifest_errors.extend(review_manifest_errors)
    manifest_support_release_summary_present, support_release_manifest_errors = _validate_support_release_manifest_summary(
        manifest_result_summary,
        release_summary,
    )
    manifest_errors.extend(support_release_manifest_errors)
    support_set_policy_present, support_set_policy_errors = _validate_support_set_policy_contract(
        support_set_policy,
        manifest_result_summary,
    )
    manifest_errors.extend(support_set_policy_errors)
    support_label_manifest_present, support_label_manifest_errors = _validate_support_label_manifest_summary(
        manifest_result_summary,
        label_sidecar_gate,
    )
    manifest_errors.extend(support_label_manifest_errors)
    passed = (
        isinstance(review_queue, list)
        and bool(quality_gate.get("ok"))
        and has_false_support_triage
        and has_acceptance_guard
        and has_acceptance_slices
        and has_abstention_analysis
        and has_release_blocker_summary
        and has_label_maturity
        and manifest_false_support_triage_present
        and manifest_support_release_summary_present
        and support_set_policy_present
        and support_label_manifest_present
        and not limited_review_queue_errors
        and not manifest_errors
    )
    summary["steps"].append(
        {
            "name": "support_review_queue",
            "status": "passed" if passed else "failed",
            "command": cmd,
            "case_count": payload.get("case_count") if isinstance(payload, dict) else None,
            "review_queue_count": len(review_queue) if isinstance(review_queue, list) else None,
            "review_queue_summary": review_queue_summary,
            "release_blocker_summary": release_blocker_summary,
            "review_queue_case_ids": quality_gate.get("review_queue_case_ids", []),
            "critical_review_case_ids": quality_gate.get("critical_review_case_ids", []),
            "false_support_analysis": false_support_analysis,
            "acceptance_guard": acceptance_guard,
            "acceptance_slices": acceptance_slices,
            "abstention_analysis": abstention_analysis,
            "label_maturity": label_maturity,
            "release_summary": release_summary,
            "false_support_triage_present": has_false_support_triage,
            "acceptance_guard_present": has_acceptance_guard,
            "acceptance_slices_present": has_acceptance_slices,
            "abstention_analysis_present": has_abstention_analysis,
            "release_blocker_summary_present": has_release_blocker_summary,
            "label_maturity_present": has_label_maturity,
            "manifest_false_support_triage_present": manifest_false_support_triage_present,
            "manifest_support_release_summary_present": manifest_support_release_summary_present,
            "support_set_policy_present": support_set_policy_present,
            "support_label_manifest_present": support_label_manifest_present,
            "limited_review_queue": limited_review_queue,
            "limited_review_queue_errors": limited_review_queue_errors,
            "manifest_result_summary": manifest_result_summary,
            "manifest_errors": manifest_errors,
            "failures": quality_gate.get("failures", []),
            "support_set_policy": support_set_policy,
            "stdout_tail": _tail(completed.stdout),
        }
    )
    if not passed:
        summary["ok"] = False


def _load_experiment_artifact_manifest(payload: Dict[str, Any]) -> tuple[Dict[str, Any], List[str]]:
    if not isinstance(payload, dict):
        return {}, ["missing_payload"]
    artifact = payload.get("experiment_artifact")
    if not isinstance(artifact, dict):
        return {}, ["missing_experiment_artifact"]
    files = artifact.get("files")
    if not isinstance(files, dict) or not files.get("manifest"):
        return {}, ["missing_manifest_file"]
    manifest_path = Path(str(files["manifest"]))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        return {}, ["invalid_manifest_payload"]
    return manifest, []


def _artifact_manifest_result_summary(
    artifact_manifest: Dict[str, Any],
    manifest_errors: List[str],
) -> Dict[str, Any]:
    manifest_result_summary = (
        artifact_manifest.get("result_summary", {}) if isinstance(artifact_manifest, dict) else {}
    )
    if not isinstance(manifest_result_summary, dict):
        manifest_errors.append("manifest_result_summary_not_object")
        return {}
    return manifest_result_summary


def _validate_support_review_manifest_summary(
    manifest_result_summary: Dict[str, Any],
    false_support_analysis: Dict[str, Any],
    acceptance_slices: List[Dict[str, Any]],
    abstention_analysis: Dict[str, Any],
    release_blocker_summary: Dict[str, Any],
) -> tuple[bool, List[str]]:
    errors: List[str] = []
    acceptance_guard = false_support_analysis.get("acceptance_guard", {})
    if not isinstance(acceptance_guard, dict):
        acceptance_guard = {}
    review_plan = false_support_analysis.get("review_plan", {})
    if not isinstance(review_plan, dict):
        review_plan = {}
    if manifest_result_summary.get("false_support_total_overcall_count") != int(
        false_support_analysis.get("total_overcall_count", 0) or 0
    ):
        errors.append("manifest_total_overcall_count_mismatch")
    if manifest_result_summary.get("false_support_risk_slice_count") != len(
        false_support_analysis.get("risk_slices", []) or []
    ):
        errors.append("manifest_risk_slice_count_mismatch")
    if "support_overcall_count" not in manifest_result_summary:
        errors.append("manifest_support_overcall_count_missing")
    if "support_overcall_rate" not in manifest_result_summary:
        errors.append("manifest_support_overcall_rate_missing")
    for metric_name in (
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "weighted_precision",
        "weighted_recall",
        "weighted_f1",
    ):
        if metric_name not in manifest_result_summary:
            errors.append(f"manifest_{metric_name}_missing")
    if manifest_result_summary.get("false_support_ok_to_accept_supported") != bool(
        acceptance_guard.get("ok_to_accept_supported", False)
    ):
        errors.append("manifest_ok_to_accept_supported_mismatch")
    if manifest_result_summary.get("false_support_block_acceptance_count") != int(
        acceptance_guard.get("block_acceptance_count", 0) or 0
    ):
        errors.append("manifest_block_acceptance_count_mismatch")
    if manifest_result_summary.get("false_support_block_acceptance_case_ids") != list(
        acceptance_guard.get("block_acceptance_case_ids", []) or []
    ):
        errors.append("manifest_block_acceptance_case_ids_mismatch")
    if manifest_result_summary.get("false_support_review_before_accepting_case_ids") != list(
        acceptance_guard.get("review_before_accepting_case_ids", []) or []
    ):
        errors.append("manifest_review_before_accepting_case_ids_mismatch")
    acceptance_slice_ids = [
        str(item.get("id"))
        for item in acceptance_slices
        if isinstance(item, dict) and item.get("id")
    ]
    blocked_slice_ids = [
        str(item.get("id"))
        for item in acceptance_slices
        if isinstance(item, dict) and item.get("id") and item.get("status") == "blocked"
    ]
    review_required_slice_ids = [
        str(item.get("id"))
        for item in acceptance_slices
        if isinstance(item, dict) and item.get("id") and item.get("status") == "review_required"
    ]
    slice_case_counts = {
        str(item.get("id")): int(item.get("case_count", 0) or 0)
        for item in acceptance_slices
        if isinstance(item, dict) and item.get("id")
    }
    if manifest_result_summary.get("support_acceptance_slice_ids") != acceptance_slice_ids:
        errors.append("manifest_support_acceptance_slice_ids_mismatch")
    if manifest_result_summary.get("support_acceptance_blocked_slice_ids") != blocked_slice_ids:
        errors.append("manifest_support_acceptance_blocked_slice_ids_mismatch")
    if manifest_result_summary.get("support_acceptance_review_required_slice_ids") != review_required_slice_ids:
        errors.append("manifest_support_acceptance_review_required_slice_ids_mismatch")
    if manifest_result_summary.get("support_acceptance_slice_case_counts") != slice_case_counts:
        errors.append("manifest_support_acceptance_slice_case_counts_mismatch")
    if manifest_result_summary.get("false_support_review_plan_status") != review_plan.get("status"):
        errors.append("manifest_false_support_review_plan_status_mismatch")
    if manifest_result_summary.get("false_support_review_plan_next_action") != review_plan.get("next_action"):
        errors.append("manifest_false_support_review_plan_next_action_mismatch")
    phases = review_plan.get("phases", []) if isinstance(review_plan, dict) else []
    if not isinstance(phases, list):
        phases = []
    phase_ids = [phase.get("id") for phase in phases if isinstance(phase, dict) and phase.get("id")]
    if manifest_result_summary.get("false_support_review_plan_phase_ids") != phase_ids:
        errors.append("manifest_false_support_review_plan_phase_ids_mismatch")
    if manifest_result_summary.get("false_support_review_plan_top_risk_slice_id") != review_plan.get(
        "top_risk_slice_id"
    ):
        errors.append("manifest_false_support_review_plan_top_risk_slice_id_mismatch")
    if manifest_result_summary.get("false_support_review_plan_block_case_ids") != list(
        review_plan.get("block_acceptance_case_ids", []) or []
    ):
        errors.append("manifest_false_support_review_plan_block_case_ids_mismatch")
    if manifest_result_summary.get("false_support_review_plan_review_case_ids") != list(
        review_plan.get("review_before_accepting_case_ids", []) or []
    ):
        errors.append("manifest_false_support_review_plan_review_case_ids_mismatch")
    recommended_packets = review_plan.get("recommended_annotation_packets", []) if isinstance(review_plan, dict) else []
    if not isinstance(recommended_packets, list):
        recommended_packets = []
    packet_ids = [
        packet.get("packet_id")
        for packet in recommended_packets
        if isinstance(packet, dict) and packet.get("packet_id")
    ]
    if manifest_result_summary.get("false_support_review_plan_packet_ids") != packet_ids:
        errors.append("manifest_false_support_review_plan_packet_ids_mismatch")
    if manifest_result_summary.get("false_support_review_plan_packet_count") != len(packet_ids):
        errors.append("manifest_false_support_review_plan_packet_count_mismatch")
    if manifest_result_summary.get("false_support_review_plan_packet_case_ids") != list(
        review_plan.get("recommended_annotation_case_ids", []) or []
    ):
        errors.append("manifest_false_support_review_plan_packet_case_ids_mismatch")
    if manifest_result_summary.get("abstention_total_count") != int(
        abstention_analysis.get("total_abstention_count", 0) or 0
    ):
        errors.append("manifest_abstention_total_count_mismatch")
    if manifest_result_summary.get("abstention_incorrect_count") != int(
        abstention_analysis.get("incorrect_abstention_count", 0) or 0
    ):
        errors.append("manifest_abstention_incorrect_count_mismatch")
    if manifest_result_summary.get("abstention_correct_count") != int(
        abstention_analysis.get("correct_abstention_count", 0) or 0
    ):
        errors.append("manifest_abstention_correct_count_mismatch")
    if manifest_result_summary.get("abstention_review_case_ids") != list(
        abstention_analysis.get("review_case_ids", []) or []
    ):
        errors.append("manifest_abstention_review_case_ids_mismatch")
    if manifest_result_summary.get("release_blocked") != bool(
        release_blocker_summary.get("release_blocked", False)
    ):
        errors.append("manifest_release_blocked_mismatch")
    if manifest_result_summary.get("benchmark_claim_safe") != bool(
        release_blocker_summary.get("benchmark_claim_safe", False)
    ):
        errors.append("manifest_benchmark_claim_safe_mismatch")
    if manifest_result_summary.get("release_blocking_count") != int(
        release_blocker_summary.get("blocking_count", 0) or 0
    ):
        errors.append("manifest_release_blocking_count_mismatch")
    if manifest_result_summary.get("release_blocking_case_ids") != list(
        release_blocker_summary.get("blocking_case_ids", []) or []
    ):
        errors.append("manifest_release_blocking_case_ids_mismatch")
    if manifest_result_summary.get("release_review_required_count") != int(
        release_blocker_summary.get("review_required_count", 0) or 0
    ):
        errors.append("manifest_release_review_required_count_mismatch")
    if manifest_result_summary.get("release_review_required_case_ids") != list(
        release_blocker_summary.get("review_required_case_ids", []) or []
    ):
        errors.append("manifest_release_review_required_case_ids_mismatch")
    if manifest_result_summary.get("release_next_action") != release_blocker_summary.get("next_action"):
        errors.append("manifest_release_next_action_mismatch")
    top_risk_slice = false_support_analysis.get("top_risk_slice")
    if isinstance(top_risk_slice, dict):
        if manifest_result_summary.get("false_support_top_risk_slice_id") != top_risk_slice.get("id"):
            errors.append("manifest_top_risk_slice_id_mismatch")
        if manifest_result_summary.get("false_support_top_risk_slice_case_ids") != list(
            top_risk_slice.get("case_ids", []) or []
        ):
            errors.append("manifest_top_risk_slice_case_ids_mismatch")
    else:
        if manifest_result_summary.get("false_support_top_risk_slice_id") is not None:
            errors.append("manifest_top_risk_slice_id_mismatch")
        if manifest_result_summary.get("false_support_top_risk_slice_case_ids") != []:
            errors.append("manifest_top_risk_slice_case_ids_mismatch")
    present = (
        "false_support_total_overcall_count" in manifest_result_summary
        and "false_support_risk_slice_count" in manifest_result_summary
        and "support_overcall_count" in manifest_result_summary
        and "support_overcall_rate" in manifest_result_summary
        and "macro_precision" in manifest_result_summary
        and "macro_recall" in manifest_result_summary
        and "macro_f1" in manifest_result_summary
        and "weighted_precision" in manifest_result_summary
        and "weighted_recall" in manifest_result_summary
        and "weighted_f1" in manifest_result_summary
        and isinstance(manifest_result_summary.get("false_support_ok_to_accept_supported"), bool)
        and "false_support_block_acceptance_count" in manifest_result_summary
        and isinstance(manifest_result_summary.get("false_support_block_acceptance_case_ids"), list)
        and isinstance(manifest_result_summary.get("false_support_review_before_accepting_case_ids"), list)
        and isinstance(manifest_result_summary.get("support_acceptance_slice_ids"), list)
        and isinstance(manifest_result_summary.get("support_acceptance_blocked_slice_ids"), list)
        and isinstance(manifest_result_summary.get("support_acceptance_review_required_slice_ids"), list)
        and isinstance(manifest_result_summary.get("support_acceptance_slice_case_counts"), dict)
        and "false_support_review_plan_status" in manifest_result_summary
        and "false_support_review_plan_next_action" in manifest_result_summary
        and isinstance(manifest_result_summary.get("false_support_review_plan_phase_ids"), list)
        and "false_support_review_plan_top_risk_slice_id" in manifest_result_summary
        and isinstance(manifest_result_summary.get("false_support_review_plan_block_case_ids"), list)
        and isinstance(manifest_result_summary.get("false_support_review_plan_review_case_ids"), list)
        and isinstance(manifest_result_summary.get("false_support_review_plan_packet_ids"), list)
        and "false_support_review_plan_packet_count" in manifest_result_summary
        and isinstance(manifest_result_summary.get("false_support_review_plan_packet_case_ids"), list)
        and "abstention_total_count" in manifest_result_summary
        and "abstention_incorrect_count" in manifest_result_summary
        and "abstention_correct_count" in manifest_result_summary
        and isinstance(manifest_result_summary.get("abstention_review_case_ids"), list)
        and isinstance(manifest_result_summary.get("release_blocked"), bool)
        and isinstance(manifest_result_summary.get("benchmark_claim_safe"), bool)
        and "release_blocking_count" in manifest_result_summary
        and isinstance(manifest_result_summary.get("release_blocking_case_ids"), list)
        and "release_review_required_count" in manifest_result_summary
        and isinstance(manifest_result_summary.get("release_review_required_case_ids"), list)
        and "release_next_action" in manifest_result_summary
        and "false_support_top_risk_slice_id" in manifest_result_summary
        and isinstance(manifest_result_summary.get("false_support_top_risk_slice_case_ids"), list)
    )
    return present, errors


def _validate_support_release_manifest_summary(
    manifest_result_summary: Dict[str, Any],
    release_summary: Dict[str, Any],
) -> tuple[bool, List[str]]:
    errors: List[str] = []
    if not isinstance(release_summary, dict):
        return False, ["support_release_summary_missing"]
    metrics = release_summary.get("metrics")
    risk_counts = release_summary.get("risk_counts")
    review_queue = release_summary.get("review_queue")
    acceptance = release_summary.get("acceptance")
    abstention = release_summary.get("abstention")
    label_maturity = release_summary.get("label_maturity")
    metrics = metrics if isinstance(metrics, dict) else {}
    risk_counts = risk_counts if isinstance(risk_counts, dict) else {}
    review_queue = review_queue if isinstance(review_queue, dict) else {}
    acceptance = acceptance if isinstance(acceptance, dict) else {}
    abstention = abstention if isinstance(abstention, dict) else {}
    label_maturity = label_maturity if isinstance(label_maturity, dict) else {}

    expectations: Dict[str, Any] = {
        "support_release_status": release_summary.get("status"),
        "support_release_next_action": release_summary.get("next_action"),
        "support_release_quality_gate_ok": release_summary.get("quality_gate_ok"),
        "support_release_label_sidecar_gate_ok": release_summary.get("label_sidecar_gate_ok"),
        "support_release_benchmark_claim_safe": bool(release_summary.get("benchmark_claim_safe")),
        "support_release_ok_to_accept_supported": bool(release_summary.get("ok_to_accept_supported")),
        "support_release_case_count": int(metrics.get("case_count", 0) or 0),
        "support_release_supported_precision": metrics.get("supported_precision"),
        "support_release_supported_recall": metrics.get("supported_recall"),
        "support_release_supported_f1": metrics.get("supported_f1"),
        "support_release_macro_f1": metrics.get("macro_f1"),
        "support_release_weighted_f1": metrics.get("weighted_f1"),
        "support_release_false_support_rate": metrics.get("false_support_rate"),
        "support_release_abstention_rate": metrics.get("abstention_rate"),
        "support_release_contradiction_recall": metrics.get("contradiction_recall"),
        "support_release_false_support_count": int(risk_counts.get("false_support", 0) or 0),
        "support_release_weak_false_support_count": int(risk_counts.get("weak_false_support", 0) or 0),
        "support_release_missed_contradiction_count": int(risk_counts.get("missed_contradiction", 0) or 0),
        "support_release_incorrect_abstention_count": int(risk_counts.get("incorrect_abstention", 0) or 0),
        "support_release_review_queue_count": int(review_queue.get("count", 0) or 0),
        "support_release_review_top_case_ids": list(review_queue.get("top_case_ids", []) or []),
        "support_release_blocking_case_ids": list(review_queue.get("blocking_case_ids", []) or []),
        "support_release_review_required_case_ids": list(review_queue.get("review_required_case_ids", []) or []),
        "support_release_block_acceptance_case_ids": list(acceptance.get("block_acceptance_case_ids", []) or []),
        "support_release_review_before_accepting_case_ids": list(
            acceptance.get("review_before_accepting_case_ids", []) or []
        ),
        "support_release_top_risk_slice_id": acceptance.get("top_risk_slice_id"),
        "support_release_top_risk_slice_case_ids": list(acceptance.get("top_risk_slice_case_ids", []) or []),
        "support_release_abstention_review_case_ids": list(abstention.get("review_case_ids", []) or []),
        "support_release_label_human_reviewed": int(label_maturity.get("human_reviewed", 0) or 0),
        "support_release_label_dual_annotated": int(label_maturity.get("dual_annotated", 0) or 0),
        "support_release_label_published_benchmark": int(label_maturity.get("published_benchmark", 0) or 0),
        "support_release_label_high_risk_unreviewed": int(label_maturity.get("high_risk_unreviewed", 0) or 0),
    }
    for key, expected in expectations.items():
        if manifest_result_summary.get(key) != expected:
            errors.append(f"manifest_{key}_mismatch")
    present = (
        all(key in manifest_result_summary for key in expectations)
        and release_summary.get("schema_version") == 1
        and release_summary.get("status") in {"clear", "review_required", "blocked"}
        and bool(release_summary.get("next_action"))
        and isinstance(review_queue.get("top_case_ids", []), list)
        and isinstance(acceptance.get("review_before_accepting_case_ids", []), list)
        and isinstance(abstention.get("review_case_ids", []), list)
    )
    return present and not errors, errors


def _has_support_acceptance_slices(acceptance_slices: Any) -> bool:
    if not isinstance(acceptance_slices, list):
        return False
    by_id = {
        str(item.get("id")): item
        for item in acceptance_slices
        if isinstance(item, dict) and item.get("id")
    }
    for slice_id in SUPPORT_ACCEPTANCE_SLICE_IDS:
        item = by_id.get(slice_id)
        if not isinstance(item, dict):
            return False
        if item.get("status") not in {"clear", "review_required", "blocked"}:
            return False
        if not isinstance(item.get("case_count"), int):
            return False
        if not isinstance(item.get("case_ids"), list):
            return False
        if not isinstance(item.get("false_support_case_ids"), list):
            return False
        if not isinstance(item.get("weak_false_support_case_ids"), list):
            return False
        if not item.get("policy") or not item.get("recommended_action"):
            return False
    return True


def _has_false_support_review_plan(review_plan: Any) -> bool:
    if not isinstance(review_plan, dict):
        return False
    phases = review_plan.get("phases")
    recommended_packets = review_plan.get("recommended_annotation_packets")
    return (
        review_plan.get("schema_version") == 1
        and review_plan.get("status") in {"clear", "review_required", "blocked"}
        and bool(review_plan.get("next_action"))
        and isinstance(review_plan.get("block_acceptance_case_ids"), list)
        and isinstance(review_plan.get("review_before_accepting_case_ids"), list)
        and isinstance(phases, list)
        and all(
            isinstance(phase, dict)
            and phase.get("id")
            and isinstance(phase.get("annotation_packet"), dict)
            and isinstance(phase.get("command_template"), list)
            for phase in phases
        )
        and isinstance(recommended_packets, list)
        and "recommended_annotation_packet_count" in review_plan
        and isinstance(review_plan.get("recommended_annotation_case_ids"), list)
    )


def _validate_support_set_policy_contract(
    support_set_policy: Dict[str, Any],
    manifest_result_summary: Dict[str, Any],
) -> tuple[bool, List[str]]:
    errors: List[str] = []
    if not isinstance(support_set_policy, dict):
        return False, ["support_set_policy_missing"]
    compact_policy = _compact_support_set_policy_contract(support_set_policy)
    case_types = compact_policy.get("case_types", {})
    languages = compact_policy.get("languages", {})
    splits = compact_policy.get("splits", {})
    case_ids = compact_policy.get("case_ids", [])
    if not isinstance(case_types, dict):
        case_types = {}
        errors.append("support_set_policy_case_types_missing")
    if not isinstance(languages, dict):
        languages = {}
        errors.append("support_set_policy_languages_missing")
    if not isinstance(splits, dict):
        splits = {}
        errors.append("support_set_policy_splits_missing")
    if not isinstance(case_ids, list):
        case_ids = []
        errors.append("support_set_policy_case_ids_missing")
    if int(compact_policy.get("case_count", 0) or 0) < 3:
        errors.append("support_set_policy_test_case_count_too_low")
    if int(case_types.get("weak_set_boundary", 0) or 0) < 1:
        errors.append("support_set_policy_missing_weak_set_boundary")
    if int(case_types.get("contradiction_set", 0) or 0) < 1:
        errors.append("support_set_policy_missing_contradiction_set")
    if int(languages.get("zh", 0) or 0) < 1:
        errors.append("support_set_policy_missing_zh_case")
    for expected_case_id in ("ss02", "ss03", "ss05"):
        if expected_case_id not in case_ids:
            errors.append(f"support_set_policy_missing_case_{expected_case_id}")

    if manifest_result_summary.get("support_set_policy_case_count") != compact_policy.get("case_count"):
        errors.append("manifest_support_set_policy_case_count_mismatch")
    if manifest_result_summary.get("support_set_policy_case_types") != case_types:
        errors.append("manifest_support_set_policy_case_types_mismatch")
    if manifest_result_summary.get("support_set_policy_languages") != languages:
        errors.append("manifest_support_set_policy_languages_mismatch")
    if manifest_result_summary.get("support_set_policy_splits") != splits:
        errors.append("manifest_support_set_policy_splits_mismatch")
    if manifest_result_summary.get("support_set_policy_case_ids") != case_ids:
        errors.append("manifest_support_set_policy_case_ids_mismatch")

    present = (
        "support_set_policy_case_count" in manifest_result_summary
        and isinstance(manifest_result_summary.get("support_set_policy_case_types"), dict)
        and isinstance(manifest_result_summary.get("support_set_policy_languages"), dict)
        and isinstance(manifest_result_summary.get("support_set_policy_splits"), dict)
        and isinstance(manifest_result_summary.get("support_set_policy_case_ids"), list)
    )
    return present and not errors, errors


def _compact_support_set_policy_contract(support_set_policy: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize full and compact support-set policy payloads to release-gate fields."""

    dataset = support_set_policy.get("dataset")
    overall = support_set_policy.get("overall")
    cases = support_set_policy.get("cases")
    if isinstance(dataset, dict):
        if not isinstance(cases, list):
            cases = []
        case_ids = [
            case.get("case_id")
            for case in cases
            if isinstance(case, dict) and case.get("case_id")
        ]
        return {
            "accuracy": overall.get("accuracy") if isinstance(overall, dict) else None,
            "macro_f1": overall.get("macro_f1") if isinstance(overall, dict) else None,
            "weighted_f1": overall.get("weighted_f1") if isinstance(overall, dict) else None,
            "contradiction_recall": overall.get("contradiction_recall") if isinstance(overall, dict) else None,
            "false_support_rate": overall.get("false_support_rate") if isinstance(overall, dict) else None,
            "case_count": dataset.get("n"),
            "case_types": dataset.get("case_types", {}),
            "languages": dataset.get("languages", {}),
            "splits": dataset.get("splits", {}),
            "case_ids": case_ids,
        }
    return support_set_policy


def _validate_support_baseline_manifest_summary(
    manifest_result_summary: Dict[str, Any],
    rows: List[Dict[str, Any]],
    heuristic_row: Dict[str, Any],
) -> tuple[bool, List[str]]:
    errors: List[str] = []
    metric_fields = [
        "accuracy",
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "weighted_precision",
        "weighted_recall",
        "weighted_f1",
        "false_support_rate",
        "abstention_rate",
        "supported_precision",
        "contradiction_recall",
    ]
    expected_metrics = {
        str(row.get("backend", "")): {field: row.get(field) for field in metric_fields}
        for row in rows
        if row.get("backend")
    }
    if manifest_result_summary.get("support_baseline_metric_fields") != metric_fields:
        errors.append("manifest_support_baseline_metric_fields_mismatch")
    if manifest_result_summary.get("support_baseline_metrics") != expected_metrics:
        errors.append("manifest_support_baseline_metrics_mismatch")
    overcall_backends = [
        str(row.get("backend", ""))
        for row in rows
        if int(row.get("total_overcall_count", 0) or 0) > 0
    ]
    if manifest_result_summary.get("false_support_overcall_backends") != overcall_backends:
        errors.append("manifest_overcall_backends_mismatch")
    heuristic_top_slice = heuristic_row.get("top_false_support_risk_slice")
    if isinstance(heuristic_top_slice, dict):
        if manifest_result_summary.get("false_support_top_overcall_backend") != "heuristic":
            errors.append("manifest_top_overcall_backend_mismatch")
        if manifest_result_summary.get("false_support_top_risk_slice_id") != heuristic_top_slice.get("id"):
            errors.append("manifest_top_risk_slice_id_mismatch")
        if manifest_result_summary.get("false_support_top_risk_slice_case_ids") != list(
            heuristic_top_slice.get("case_ids", []) or []
        ):
            errors.append("manifest_top_risk_slice_case_ids_mismatch")
        if manifest_result_summary.get("false_support_top_overcall_review_plan_status") != heuristic_row.get(
            "false_support_review_plan_status"
        ):
            errors.append("manifest_top_overcall_review_plan_status_mismatch")
        if manifest_result_summary.get("false_support_top_overcall_review_plan_next_action") != heuristic_row.get(
            "false_support_review_plan_next_action"
        ):
            errors.append("manifest_top_overcall_review_plan_next_action_mismatch")
        if manifest_result_summary.get("false_support_top_overcall_review_plan_phase_ids") != list(
            heuristic_row.get("false_support_review_plan_phase_ids", []) or []
        ):
            errors.append("manifest_top_overcall_review_plan_phase_ids_mismatch")
        if manifest_result_summary.get("false_support_top_overcall_review_plan_block_case_ids") != list(
            heuristic_row.get("false_support_review_plan_block_case_ids", []) or []
        ):
            errors.append("manifest_top_overcall_review_plan_block_case_ids_mismatch")
        if manifest_result_summary.get("false_support_top_overcall_review_plan_review_case_ids") != list(
            heuristic_row.get("false_support_review_plan_review_case_ids", []) or []
        ):
            errors.append("manifest_top_overcall_review_plan_review_case_ids_mismatch")
        if manifest_result_summary.get("false_support_top_overcall_review_plan_packet_ids") != list(
            heuristic_row.get("false_support_review_plan_packet_ids", []) or []
        ):
            errors.append("manifest_top_overcall_review_plan_packet_ids_mismatch")
        if manifest_result_summary.get("false_support_top_overcall_review_plan_packet_count") != int(
            heuristic_row.get("false_support_review_plan_packet_count", 0) or 0
        ):
            errors.append("manifest_top_overcall_review_plan_packet_count_mismatch")
        if manifest_result_summary.get("false_support_top_overcall_review_plan_packet_case_ids") != list(
            heuristic_row.get("false_support_review_plan_packet_case_ids", []) or []
        ):
            errors.append("manifest_top_overcall_review_plan_packet_case_ids_mismatch")
    present = (
        isinstance(manifest_result_summary.get("false_support_overcall_backends"), list)
        and "false_support_top_overcall_backend" in manifest_result_summary
        and "false_support_top_risk_slice_id" in manifest_result_summary
        and isinstance(manifest_result_summary.get("false_support_top_risk_slice_case_ids"), list)
        and "false_support_top_overcall_review_plan_status" in manifest_result_summary
        and "false_support_top_overcall_review_plan_next_action" in manifest_result_summary
        and isinstance(manifest_result_summary.get("false_support_top_overcall_review_plan_phase_ids"), list)
        and isinstance(manifest_result_summary.get("false_support_top_overcall_review_plan_block_case_ids"), list)
        and isinstance(manifest_result_summary.get("false_support_top_overcall_review_plan_review_case_ids"), list)
        and isinstance(manifest_result_summary.get("false_support_top_overcall_review_plan_packet_ids"), list)
        and "false_support_top_overcall_review_plan_packet_count" in manifest_result_summary
        and isinstance(
            manifest_result_summary.get("false_support_top_overcall_review_plan_packet_case_ids"), list
        )
        and manifest_result_summary.get("support_baseline_metric_fields") == metric_fields
        and manifest_result_summary.get("support_baseline_metrics") == expected_metrics
    )
    return present, errors


def _validate_support_label_manifest_summary(
    manifest_result_summary: Dict[str, Any],
    label_sidecar_gate: Dict[str, Any],
) -> tuple[bool, List[str]]:
    errors: List[str] = []
    if not isinstance(label_sidecar_gate, dict):
        return False, ["support_label_gate_missing"]
    metrics = label_sidecar_gate.get("metrics")
    if not isinstance(metrics, dict):
        return False, ["support_label_gate_metrics_missing"]

    expectations: Dict[str, Any] = {
        "support_label_gate_ok": bool(label_sidecar_gate.get("ok")),
        "support_label_sidecar_coverage": metrics.get("coverage"),
        "support_label_human_reviewed": int(metrics.get("human_reviewed", 0) or 0),
        "support_label_high_risk_unreviewed": int(metrics.get("high_risk_unreviewed", 0) or 0),
        "support_label_full_text_required_unreviewed": int(
            metrics.get("full_text_required_unreviewed", 0) or 0
        ),
        "support_label_policy_boundary_unreviewed": int(metrics.get("policy_boundary_unreviewed", 0) or 0),
        "support_label_dual_annotated": int(metrics.get("dual_annotated", 0) or 0),
        "support_label_unresolved_disagreements": int(metrics.get("unresolved_disagreements", 0) or 0),
        "support_label_supported_disagreements": int(metrics.get("supported_disagreements", 0) or 0),
        "support_label_raw_dual_agreement_rate": metrics.get("raw_dual_agreement_rate"),
        "support_label_unresolved_disagreement_case_ids": list(
            metrics.get("unresolved_disagreement_case_ids", []) or []
        ),
        "support_label_supported_disagreement_case_ids": list(
            metrics.get("supported_disagreement_case_ids", []) or []
        ),
        "support_label_high_risk_case_count_by_language_case_type": dict(
            metrics.get("high_risk_case_count_by_language_case_type", {})
        )
        if isinstance(metrics.get("high_risk_case_count_by_language_case_type"), dict)
        else {},
        "support_label_high_risk_reviewed_by_language_case_type": dict(
            metrics.get("high_risk_reviewed_by_language_case_type", {})
        )
        if isinstance(metrics.get("high_risk_reviewed_by_language_case_type"), dict)
        else {},
        "support_label_high_risk_unreviewed_by_language_case_type": dict(
            metrics.get("high_risk_unreviewed_by_language_case_type", {})
        )
        if isinstance(metrics.get("high_risk_unreviewed_by_language_case_type"), dict)
        else {},
        "support_label_label_source_counts": dict(metrics.get("label_source_counts", {}))
        if isinstance(metrics.get("label_source_counts"), dict)
        else {},
        "support_label_reviewed_by_label_source": dict(metrics.get("reviewed_by_label_source", {}))
        if isinstance(metrics.get("reviewed_by_label_source"), dict)
        else {},
        "support_label_unreviewed_by_label_source": dict(metrics.get("unreviewed_by_label_source", {}))
        if isinstance(metrics.get("unreviewed_by_label_source"), dict)
        else {},
        "support_label_reviewed_source_locator_count": int(
            metrics.get("reviewed_source_locator_count", 0) or 0
        ),
        "support_label_published_benchmark_source_locator_count": int(
            metrics.get("published_benchmark_source_locator_count", 0) or 0
        ),
        "support_label_sidecar_provenance_complete_count": int(
            metrics.get("sidecar_provenance_complete_count", 0) or 0
        ),
        "support_label_sidecar_provenance_complete_fraction": metrics.get(
            "sidecar_provenance_complete_fraction"
        ),
        "support_label_sidecar_provenance_missing_count": int(
            metrics.get("sidecar_provenance_missing_count", 0) or 0
        ),
        "support_label_sidecar_provenance_missing_case_ids": list(
            metrics.get("sidecar_provenance_missing_case_ids", []) or []
        ),
        "support_label_sidecar_provenance_missing_case_ids_by_field": dict(
            metrics.get("sidecar_provenance_missing_case_ids_by_field", {})
        )
        if isinstance(metrics.get("sidecar_provenance_missing_case_ids_by_field"), dict)
        else {},
        "support_label_sidecar_provenance_field_present_counts": dict(
            metrics.get("sidecar_provenance_field_present_counts", {})
        )
        if isinstance(metrics.get("sidecar_provenance_field_present_counts"), dict)
        else {},
        "support_label_dataset_cases": int(metrics.get("dataset_cases", 0) or 0),
        "support_label_sidecar_cases": int(metrics.get("sidecar_cases", 0) or 0),
    }
    for key, expected in expectations.items():
        if manifest_result_summary.get(key) != expected:
            errors.append(f"manifest_{key}_mismatch")
    present = all(key in manifest_result_summary for key in expectations)
    return present and not errors, errors


def _record_support_baseline_comparison_gate(
    summary: Dict[str, Any],
    *,
    python: str,
    project_root: Path,
    dataset: str,
    label_sidecar: str,
    min_sidecar_coverage: float,
    min_human_reviewed: int,
    min_high_risk_reviewed: int,
    min_high_risk_reviewed_by_language: List[str],
    min_dual_annotated: int,
    max_unresolved_disagreements: int,
    min_raw_dual_agreement_rate: Optional[float],
    max_supported_disagreements: Optional[int],
) -> None:
    cmd = [
        python,
        "scripts/compare_support_baselines.py",
        "--dataset",
        dataset,
        "--split",
        "test",
        "--label-sidecar",
        label_sidecar,
        "--min-sidecar-coverage",
        str(min_sidecar_coverage),
        "--min-human-reviewed",
        str(min_human_reviewed),
        "--min-high-risk-reviewed",
        str(min_high_risk_reviewed),
        "--min-dual-annotated",
        str(min_dual_annotated),
        "--max-unresolved-disagreements",
        str(max_unresolved_disagreements),
    ]
    for threshold in min_high_risk_reviewed_by_language:
        cmd.extend(["--min-high-risk-reviewed-by-language", threshold])
    if min_raw_dual_agreement_rate is not None:
        cmd.extend(["--min-raw-dual-agreement-rate", str(min_raw_dual_agreement_rate)])
    if max_supported_disagreements is not None:
        cmd.extend(["--max-supported-disagreements", str(max_supported_disagreements)])

    artifact_manifest: Dict[str, Any] = {}
    manifest_errors: List[str] = []
    with tempfile.TemporaryDirectory(prefix="citeguard-support-baselines-") as tmpdir:
        cmd.extend(
            [
                "--output-dir",
                tmpdir,
                "--run-id",
                "release-support-baseline-comparison",
            ]
        )
        try:
            completed = _run(cmd, cwd=project_root)
            payload = json.loads(completed.stdout)
            artifact_manifest, manifest_errors = _load_experiment_artifact_manifest(payload)
        except subprocess.CalledProcessError as exc:
            summary["steps"].append(
                {
                    "name": "support_baseline_comparison",
                    "status": "failed",
                    "command": cmd,
                    "stdout_tail": _tail(exc.stdout or ""),
                    "stderr_tail": _tail(exc.stderr or ""),
                }
            )
            summary["ok"] = False
            return
        except json.JSONDecodeError as exc:
            summary["steps"].append(
                {
                    "name": "support_baseline_comparison",
                    "status": "failed",
                    "command": cmd,
                    "message": f"Could not parse support baseline JSON or artifact manifest: {exc}",
                    "stdout_tail": _tail(completed.stdout) if "completed" in locals() else [],
                }
            )
            summary["ok"] = False
            return
        except (OSError, KeyError, TypeError) as exc:
            summary["steps"].append(
                {
                    "name": "support_baseline_comparison",
                    "status": "failed",
                    "command": cmd,
                    "message": f"Could not read support baseline experiment artifact manifest: {exc}",
                    "stdout_tail": _tail(completed.stdout) if "completed" in locals() else [],
                }
            )
            summary["ok"] = False
            return

    comparison = payload.get("comparison", []) if isinstance(payload, dict) else []
    rows = [row for row in comparison if isinstance(row, dict)] if isinstance(comparison, list) else []
    row_by_backend = {str(row.get("backend", "")): row for row in rows}
    rows_missing_risk_fields = [
        str(row.get("backend", ""))
        for row in rows
        if (
            "false_support_risk_slices" not in row
            or "top_false_support_risk_slice" not in row
            or "support_overcall_count" not in row
            or "support_overcall_rate" not in row
            or "ok_to_accept_supported" not in row
            or not isinstance(row.get("block_acceptance_case_ids"), list)
            or not isinstance(row.get("review_before_accepting_case_ids"), list)
            or "false_support_review_plan_status" not in row
            or "false_support_review_plan_next_action" not in row
            or not isinstance(row.get("false_support_review_plan_phase_ids"), list)
            or not isinstance(row.get("false_support_review_plan_block_case_ids"), list)
            or not isinstance(row.get("false_support_review_plan_review_case_ids"), list)
            or not isinstance(row.get("false_support_review_plan_packet_ids"), list)
            or "false_support_review_plan_packet_count" not in row
            or not isinstance(row.get("false_support_review_plan_packet_case_ids"), list)
        )
    ]
    rows_missing_active_risk_slices = [
        str(row.get("backend", ""))
        for row in rows
        if int(row.get("total_overcall_count", 0) or 0) > 0
        and (
            not isinstance(row.get("false_support_risk_slices"), list)
            or not row.get("false_support_risk_slices")
            or not isinstance(row.get("top_false_support_risk_slice"), dict)
        )
    ]
    required_metric_fields = [
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "weighted_precision",
        "weighted_recall",
        "weighted_f1",
    ]
    rows_missing_metric_fields = [
        str(row.get("backend", ""))
        for row in rows
        if any(field not in row for field in required_metric_fields)
    ]
    fixture_row = row_by_backend.get("fixture", {})
    heuristic_row = row_by_backend.get("heuristic", {})
    sidecar_gate = payload.get("label_sidecar_gate", {}) if isinstance(payload, dict) else {}
    support_set_policy = payload.get("support_set_policy", {}) if isinstance(payload, dict) else {}
    manifest_result_summary = _artifact_manifest_result_summary(artifact_manifest, manifest_errors)
    manifest_false_support_triage_present, baseline_manifest_errors = _validate_support_baseline_manifest_summary(
        manifest_result_summary,
        rows,
        heuristic_row,
    )
    manifest_errors.extend(baseline_manifest_errors)
    support_set_policy_compact = _compact_support_set_policy_contract(support_set_policy)
    support_set_policy_present, support_set_policy_errors = _validate_support_set_policy_contract(
        support_set_policy,
        manifest_result_summary,
    )
    manifest_errors.extend(support_set_policy_errors)
    support_label_manifest_present, support_label_manifest_errors = _validate_support_label_manifest_summary(
        manifest_result_summary,
        sidecar_gate,
    )
    manifest_errors.extend(support_label_manifest_errors)
    passed = (
        bool(rows)
        and "fixture" in row_by_backend
        and "heuristic" in row_by_backend
        and bool(fixture_row.get("quality_gate_ok"))
        and bool(sidecar_gate.get("ok", True))
        and not rows_missing_risk_fields
        and not rows_missing_active_risk_slices
        and not rows_missing_metric_fields
        and manifest_false_support_triage_present
        and support_set_policy_present
        and support_label_manifest_present
        and not manifest_errors
    )
    summary["steps"].append(
        {
            "name": "support_baseline_comparison",
            "status": "passed" if passed else "failed",
            "command": cmd,
            "case_count": payload.get("case_count") if isinstance(payload, dict) else None,
            "quality_gates_ok": payload.get("quality_gates_ok") if isinstance(payload, dict) else None,
            "backends": [str(row.get("backend", "")) for row in rows],
            "fixture_quality_gate_ok": fixture_row.get("quality_gate_ok"),
            "heuristic_quality_gate_ok": heuristic_row.get("quality_gate_ok"),
            "heuristic_limited": heuristic_row.get("heuristic_limited"),
            "heuristic_total_overcall_count": heuristic_row.get("total_overcall_count"),
            "heuristic_top_false_support_risk_slice": heuristic_row.get("top_false_support_risk_slice"),
            "rows_missing_risk_fields": rows_missing_risk_fields,
            "rows_missing_active_risk_slices": rows_missing_active_risk_slices,
            "rows_missing_metric_fields": rows_missing_metric_fields,
            "manifest_false_support_triage_present": manifest_false_support_triage_present,
            "support_set_policy_present": support_set_policy_present,
            "support_label_manifest_present": support_label_manifest_present,
            "support_set_policy": support_set_policy_compact,
            "manifest_result_summary": manifest_result_summary,
            "manifest_errors": manifest_errors,
            "label_sidecar_gate_ok": sidecar_gate.get("ok") if isinstance(sidecar_gate, dict) else None,
            "stdout_tail": _tail(completed.stdout),
        }
    )
    if not passed:
        summary["ok"] = False


def _record_support_calibration_artifact_gate(summary: Dict[str, Any], *, python: str, project_root: Path) -> None:
    try:
        details = _check_support_calibration_artifact_gate(python=python, project_root=project_root)
    except Exception as exc:
        summary["steps"].append(
            {
                "name": "support_calibration_artifact",
                "status": "failed",
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    summary["steps"].append({"name": "support_calibration_artifact", "status": "passed", **details})


def _check_support_calibration_artifact_gate(*, python: str, project_root: Path) -> Dict[str, Any]:
    from citeguard.benchmark import load_support_eval_calibration_examples

    docs = {
        "docs/release_checklist.md": _read_required_text(project_root / "docs" / "release_checklist.md"),
        "docs/benchmark_todo.md": _read_required_text(project_root / "docs" / "benchmark_todo.md"),
    }
    combined_docs = _normalize_markdown_text("\n".join(docs.values()))
    required_phrases = [
        "scripts/calibrate_support.py",
        "--scored-dataset",
        "support_calibration",
        "result.json",
        "config.json",
        "manifest.json",
        "support_calibration_top_false_support_rate",
        "support_calibration_top_false_positive_case_ids",
        "support_calibration_top_false_negative_case_ids",
        "support_calibration_top_false_positive_decision_paths",
        "support_calibration_top_false_positive_score_summary",
        "--support-eval-dataset",
        "--split dev",
        "gold=supported",
    ]

    errors = []
    for phrase in required_phrases:
        if _normalize_markdown_text(phrase) not in combined_docs:
            errors.append(f"support calibration docs missing required phrase: {phrase}")

    dev_examples = load_support_eval_calibration_examples(
        str(project_root / "data" / "eval" / "support_eval.json"),
        split="dev",
    )
    if not dev_examples:
        errors.append("support_eval dev split should produce calibration examples")
    if not any(example.supported for example in dev_examples):
        errors.append("support_eval dev calibration examples should include strong-support positives")
    if not any(not example.supported for example in dev_examples):
        errors.append("support_eval dev calibration examples should include false-support-sensitive negatives")
    if any("split=test" in example.note for example in dev_examples):
        errors.append("support_eval dev calibration examples should not include held-out test cases")
    if any("gold=weakly_supported" in example.note and example.supported for example in dev_examples):
        errors.append("weakly_supported cases should not become strong-support calibration positives")

    scored_rows = [
        {
            "example": {
                "example_id": "release-calibration-positive",
                "claim_text": "The paper studies citation hallucinations.",
                "evidence_text": "The paper studies citation hallucinations in academic writing.",
                "supported": True,
            },
            "heuristic_score": 0.24,
            "heuristic_details": {"overlap_terms": ["paper", "studies", "citation", "hallucinations"]},
            "reranker_score": 0.82,
            "reranker_details": {},
            "nli_probabilities": {"entailment": 0.76, "contradiction": 0.03, "neutral": 0.21},
            "nli_details": {"model_name": "release-fixture"},
        },
        {
            "example": {
                "example_id": "release-calibration-negative",
                "claim_text": "The paper proves tokenizer bugs cause citation hallucinations.",
                "evidence_text": "The paper studies citation hallucinations in academic writing.",
                "supported": False,
            },
            "heuristic_score": 0.12,
            "heuristic_details": {"overlap_terms": ["paper", "citation", "hallucinations"]},
            "reranker_score": 0.41,
            "reranker_details": {},
            "nli_probabilities": {"entailment": 0.12, "contradiction": 0.08, "neutral": 0.80},
            "nli_details": {"model_name": "release-fixture"},
        },
    ]

    with tempfile.TemporaryDirectory(prefix="citeguard-support-calibration-") as tmpdir:
        tmp_path = Path(tmpdir)
        scored_path = tmp_path / "release-scored-support.json"
        scored_path.write_text(json.dumps(scored_rows, ensure_ascii=False, indent=2), encoding="utf-8")
        cmd = [
            python,
            "scripts/calibrate_support.py",
            "--scored-dataset",
            str(scored_path),
            "--profile",
            "quick",
            "--top-k",
            "2",
            "--output-dir",
            tmpdir,
            "--run-id",
            "release-support-calibration",
        ]
        completed = _run(cmd, cwd=project_root)
        payload = json.loads(completed.stdout)
        artifact = payload.get("experiment_artifact", {})
        run_path = Path(artifact.get("path", ""))
        manifest = json.loads((run_path / "manifest.json").read_text(encoding="utf-8"))
        result = json.loads((run_path / "result.json").read_text(encoding="utf-8"))
        config = json.loads((run_path / "config.json").read_text(encoding="utf-8"))

    manifest_summary = manifest.get("result_summary", {})
    if payload.get("input_mode") != "scored_dataset":
        errors.append("calibrate_support --scored-dataset should report input_mode=scored_dataset")
    if len(payload.get("top_results", [])) != 2:
        errors.append("calibrate_support release smoke should return two top results")
    top_result = payload.get("top_results", [{}])[0] if payload.get("top_results") else {}
    top_diagnostics = top_result.get("diagnostics") if isinstance(top_result, dict) else {}
    if not isinstance(top_diagnostics, dict):
        errors.append("calibrate_support top result should include diagnostics")
        top_diagnostics = {}
    if "false_positive_case_ids" not in top_diagnostics:
        errors.append("calibrate_support diagnostics should include false_positive_case_ids")
    if "false_negative_case_ids" not in top_diagnostics:
        errors.append("calibrate_support diagnostics should include false_negative_case_ids")
    if "bucket_summaries" not in top_diagnostics:
        errors.append("calibrate_support diagnostics should include bucket_summaries")
    if "decision_path_counts" not in top_diagnostics:
        errors.append("calibrate_support diagnostics should include decision_path_counts")
    if artifact.get("run_id") != "release-support-calibration":
        errors.append("support calibration artifact should preserve run_id")
    if manifest.get("experiment_name") != "support_calibration":
        errors.append("support calibration manifest should use experiment_name=support_calibration")
    if result.get("input_mode") != "scored_dataset":
        errors.append("support calibration result.json should preserve input_mode")
    if config.get("script") != "scripts/calibrate_support.py":
        errors.append("support calibration config.json should preserve script name")
    if config.get("profile") != "quick" or config.get("top_k") != 2:
        errors.append("support calibration config.json should preserve profile/top_k")
    if manifest_summary.get("support_calibration_input_mode") != "scored_dataset":
        errors.append("support calibration manifest summary should expose input mode")
    if manifest_summary.get("support_calibration_profile") != "quick":
        errors.append("support calibration manifest summary should expose profile")
    if manifest_summary.get("support_calibration_top_result_count") != 2:
        errors.append("support calibration manifest summary should expose top result count")
    if "support_calibration_top_false_support_rate" not in manifest_summary:
        errors.append("support calibration manifest summary should expose top false support rate")
    if "support_calibration_top_false_positive_case_ids" not in manifest_summary:
        errors.append("support calibration manifest summary should expose top false-positive case ids")
    if "support_calibration_top_false_negative_case_ids" not in manifest_summary:
        errors.append("support calibration manifest summary should expose top false-negative case ids")
    if "support_calibration_top_false_positive_decision_paths" not in manifest_summary:
        errors.append("support calibration manifest summary should expose top false-positive decision paths")
    if "support_calibration_top_false_positive_score_summary" not in manifest_summary:
        errors.append("support calibration manifest summary should expose top false-positive score summary")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "command": cmd,
        "docs_checked": sorted(docs),
        "input_mode": payload.get("input_mode"),
        "dataset_size": payload.get("dataset_size"),
        "support_eval_split": "dev",
        "support_eval_example_count": len(dev_examples),
        "support_eval_positive_count": sum(1 for example in dev_examples if example.supported),
        "support_eval_negative_count": sum(1 for example in dev_examples if not example.supported),
        "top_result_count": len(payload.get("top_results", [])),
        "manifest_summary": {
            "support_calibration_input_mode": manifest_summary.get("support_calibration_input_mode"),
            "support_calibration_profile": manifest_summary.get("support_calibration_profile"),
            "support_calibration_top_result_count": manifest_summary.get("support_calibration_top_result_count"),
            "support_calibration_top_f1": manifest_summary.get("support_calibration_top_f1"),
            "support_calibration_top_precision": manifest_summary.get("support_calibration_top_precision"),
            "support_calibration_top_recall": manifest_summary.get("support_calibration_top_recall"),
            "support_calibration_top_false_support_rate": manifest_summary.get(
                "support_calibration_top_false_support_rate"
            ),
            "support_calibration_top_false_positive_case_ids": manifest_summary.get(
                "support_calibration_top_false_positive_case_ids"
            ),
            "support_calibration_top_false_negative_case_ids": manifest_summary.get(
                "support_calibration_top_false_negative_case_ids"
            ),
            "support_calibration_top_false_positive_decision_paths": manifest_summary.get(
                "support_calibration_top_false_positive_decision_paths"
            ),
            "support_calibration_top_false_positive_score_summary": manifest_summary.get(
                "support_calibration_top_false_positive_score_summary"
            ),
        },
        "policy": "support calibration can run from deterministic scored fixtures and emits standardized experiment artifacts",
    }


def _record_support_review_queue_annotation_packet_gate(
    summary: Dict[str, Any],
    *,
    python: str,
    project_root: Path,
    dataset: str,
    label_sidecar: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="citeguard-review-queue-packet-") as tmpdir:
        packet_path = Path(tmpdir) / "support-label-packet-review-queue-test.json"
        instructions_path = Path(tmpdir) / "support-label-packet-review-queue-test-instructions.md"
        full_text_packet_path = Path(tmpdir) / "support-label-packet-full-text-required.json"
        full_text_instructions_path = Path(tmpdir) / "support-label-packet-full-text-required-instructions.md"
        policy_packet_path = Path(tmpdir) / "support-label-packet-policy-boundary.json"
        policy_instructions_path = Path(tmpdir) / "support-label-packet-policy-boundary-instructions.md"
        cmd = [
            python,
            "scripts/prepare_support_label_sidecar.py",
            "--dataset",
            dataset,
            "--existing-sidecar",
            label_sidecar,
            "--annotation-packet",
            "--from-review-queue",
            "--review-backend",
            "heuristic",
            "--split",
            "test",
            "--limit",
            "2",
            "--output",
            str(packet_path),
            "--instructions-output",
            str(instructions_path),
        ]
        full_text_cmd = [
            python,
            "scripts/prepare_support_label_sidecar.py",
            "--dataset",
            dataset,
            "--existing-sidecar",
            label_sidecar,
            "--annotation-packet",
            "--case-type",
            "full_text_required",
            "--unreviewed-only",
            "--limit",
            "10",
            "--output",
            str(full_text_packet_path),
            "--instructions-output",
            str(full_text_instructions_path),
        ]
        policy_cmd = [
            python,
            "scripts/prepare_support_label_sidecar.py",
            "--dataset",
            dataset,
            "--existing-sidecar",
            label_sidecar,
            "--annotation-packet",
            "--case-type",
            "weak_set_boundary",
            "--unreviewed-only",
            "--limit",
            "10",
            "--output",
            str(policy_packet_path),
            "--instructions-output",
            str(policy_instructions_path),
        ]
        try:
            completed = _run(cmd, cwd=project_root)
            packet_text = packet_path.read_text(encoding="utf-8")
            instructions_text = instructions_path.read_text(encoding="utf-8")
            payload = json.loads(packet_text)
            full_text_completed = _run(full_text_cmd, cwd=project_root)
            full_text_packet_text = full_text_packet_path.read_text(encoding="utf-8")
            full_text_instructions_text = full_text_instructions_path.read_text(encoding="utf-8")
            full_text_payload = json.loads(full_text_packet_text)
            policy_completed = _run(policy_cmd, cwd=project_root)
            policy_packet_text = policy_packet_path.read_text(encoding="utf-8")
            policy_instructions_text = policy_instructions_path.read_text(encoding="utf-8")
            policy_payload = json.loads(policy_packet_text)
            merge_probe = _run_annotation_conflict_merge_probe(
                python=python,
                project_root=project_root,
                dataset=dataset,
                label_sidecar=label_sidecar,
                tmpdir=Path(tmpdir),
            )
        except subprocess.CalledProcessError as exc:
            summary["steps"].append(
                {
                    "name": "support_review_queue_annotation_packet",
                    "status": "failed",
                    "command": cmd,
                    "stdout_tail": _tail(exc.stdout or ""),
                    "stderr_tail": _tail(exc.stderr or ""),
                }
            )
            summary["ok"] = False
            return
        except (OSError, json.JSONDecodeError, RuntimeError) as exc:
            summary["steps"].append(
                {
                    "name": "support_review_queue_annotation_packet",
                    "status": "failed",
                    "command": locals().get("policy_cmd", cmd),
                    "message": f"Could not read, parse, or probe review-queue annotation packet workflow: {exc}",
                    "stdout_tail": _tail(locals().get("completed", subprocess.CompletedProcess(cmd, 0, "")).stdout or ""),
                }
            )
            summary["ok"] = False
            return

    filters = payload.get("filters", {}) if isinstance(payload, dict) else {}
    cases = payload.get("cases", []) if isinstance(payload, dict) else []
    packet_summary = payload.get("packet_summary", {}) if isinstance(payload, dict) else {}
    full_text_cases = full_text_payload.get("cases", []) if isinstance(full_text_payload, dict) else []
    full_text_packet_summary = (
        full_text_payload.get("packet_summary", {}) if isinstance(full_text_payload, dict) else {}
    )
    policy_cases = policy_payload.get("cases", []) if isinstance(policy_payload, dict) else []
    policy_packet_summary = policy_payload.get("packet_summary", {}) if isinstance(policy_payload, dict) else {}
    forbidden_keys = ("gold", "predicted", "adjudicated_label", "annotator_labels", "label_notes")
    leaked_fields = _hidden_annotation_packet_key_leaks(cases, forbidden_keys)
    full_text_leaked_fields = _hidden_annotation_packet_key_leaks(full_text_cases, forbidden_keys)
    policy_leaked_fields = _hidden_annotation_packet_key_leaks(policy_cases, forbidden_keys)
    scope_annotation_fields_present = _annotation_packet_scope_fields_present(cases)
    full_text_scope_annotation_fields_present = _annotation_packet_scope_fields_present(full_text_cases)
    policy_scope_annotation_fields_present = _annotation_packet_scope_fields_present(policy_cases)
    packet_digest_present = _annotation_packet_digest_present(payload, cases)
    full_text_packet_digest_present = _annotation_packet_digest_present(full_text_payload, full_text_cases)
    policy_packet_digest_present = _annotation_packet_digest_present(policy_payload, policy_cases)
    review_protocol = payload.get("review_protocol", {}) if isinstance(payload, dict) else {}
    full_text_review_protocol = (
        full_text_payload.get("review_protocol", {}) if isinstance(full_text_payload, dict) else {}
    )
    policy_review_protocol = policy_payload.get("review_protocol", {}) if isinstance(policy_payload, dict) else {}
    review_protocol_contract = _annotation_packet_review_protocol_contract(payload, cases)
    full_text_review_protocol_contract = _annotation_packet_review_protocol_contract(
        full_text_payload,
        full_text_cases,
    )
    policy_review_protocol_contract = _annotation_packet_review_protocol_contract(policy_payload, policy_cases)
    instructions_review_protocol_present = _annotation_packet_instructions_review_protocol_present(instructions_text)
    full_text_instructions_review_protocol_present = _annotation_packet_instructions_review_protocol_present(
        full_text_instructions_text,
    )
    policy_instructions_review_protocol_present = _annotation_packet_instructions_review_protocol_present(
        policy_instructions_text,
    )
    hidden_fields = payload.get("hidden_fields", []) if isinstance(payload, dict) else []
    full_text_hidden_fields = full_text_payload.get("hidden_fields", []) if isinstance(full_text_payload, dict) else []
    policy_hidden_fields = policy_payload.get("hidden_fields", []) if isinstance(policy_payload, dict) else []
    ranks = [
        item.get("review_queue_rank")
        for item in cases
        if isinstance(item, dict) and "review_queue_rank" in item
    ]
    policy_case_ids = policy_packet_summary.get("case_ids", []) if isinstance(policy_packet_summary, dict) else []
    full_text_case_ids = (
        full_text_packet_summary.get("case_ids", []) if isinstance(full_text_packet_summary, dict) else []
    )
    full_text_case_types = [
        item.get("case_type")
        for item in full_text_cases
        if isinstance(item, dict)
    ]
    policy_case_types = [
        item.get("case_type")
        for item in policy_cases
        if isinstance(item, dict)
    ]
    passed = (
        bool(payload.get("ok"))
        and payload.get("packet_type") == "support_label_annotation_packet"
        and bool(filters.get("from_review_queue"))
        and bool(filters.get("review_queue_case_ids"))
        and isinstance(cases, list)
        and bool(cases)
        and len(ranks) == len(cases)
        and set(hidden_fields) >= set(forbidden_keys)
        and not leaked_fields
        and scope_annotation_fields_present
        and packet_digest_present
        and review_protocol_contract.get("ok") is True
        and instructions_review_protocol_present
        and "review_queue_rank" in instructions_text
        and "packet_digest" in instructions_text
        and "evidence_scope_assessed" in instructions_text
        and "full_text_needed" in instructions_text
        and bool(full_text_payload.get("ok"))
        and full_text_payload.get("packet_type") == "support_label_annotation_packet"
        and full_text_case_ids == ["s17", "s30", "s43", "s13", "s38", "s20", "s33"]
        and full_text_case_types == ["full_text_required"] * 7
        and set(full_text_hidden_fields) >= set(forbidden_keys)
        and not full_text_leaked_fields
        and full_text_scope_annotation_fields_present
        and full_text_packet_digest_present
        and full_text_review_protocol_contract.get("ok") is True
        and full_text_instructions_review_protocol_present
        and "Claims needing unavailable full text are labeled `insufficient_evidence`, not guessed." in full_text_instructions_text
        and "evidence_scope_assessed" in full_text_instructions_text
        and "full_text_needed" in full_text_instructions_text
        and "packet_digest" in full_text_instructions_text
        and bool(policy_payload.get("ok"))
        and policy_payload.get("packet_type") == "support_label_annotation_packet"
        and policy_case_ids == ["ss02", "ss05"]
        and policy_case_types == ["weak_set_boundary", "weak_set_boundary"]
        and set(policy_hidden_fields) >= set(forbidden_keys)
        and not policy_leaked_fields
        and policy_scope_annotation_fields_present
        and policy_packet_digest_present
        and policy_review_protocol_contract.get("ok") is True
        and policy_instructions_review_protocol_present
        and "Do not edit `case_id`" in policy_instructions_text
        and "do not edit `packet_id`" in policy_instructions_text
        and "packet_digest" in policy_instructions_text
        and "evidence_scope_assessed" in policy_instructions_text
        and "full_text_needed" in policy_instructions_text
        and merge_probe.get("ok") is True
    )
    summary["steps"].append(
        {
            "name": "support_review_queue_annotation_packet",
            "status": "passed" if passed else "failed",
            "command": cmd,
            "packet_id": payload.get("packet_id") if isinstance(payload, dict) else "",
            "packet_digest": payload.get("packet_digest") if isinstance(payload, dict) else "",
            "case_count": payload.get("n") if isinstance(payload, dict) else None,
            "packet_case_ids": packet_summary.get("case_ids", []) if isinstance(packet_summary, dict) else [],
            "review_queue_case_ids": filters.get("review_queue_case_ids", []) if isinstance(filters, dict) else [],
            "review_queue_ranks": ranks,
            "hidden_fields": hidden_fields,
            "leaked_hidden_fields": leaked_fields,
            "scope_annotation_fields_present": scope_annotation_fields_present,
            "packet_digest_present": packet_digest_present,
            "review_protocol": review_protocol,
            "review_protocol_present": review_protocol_contract.get("present", False),
            "review_protocol_contract": review_protocol_contract,
            "instructions_review_protocol_present": instructions_review_protocol_present,
            "full_text_boundary_command": full_text_cmd,
            "full_text_boundary_packet_digest": full_text_payload.get("packet_digest") if isinstance(full_text_payload, dict) else "",
            "full_text_boundary_packet_case_ids": full_text_case_ids,
            "full_text_boundary_case_types": full_text_case_types,
            "full_text_boundary_hidden_fields": full_text_hidden_fields,
            "full_text_boundary_leaked_hidden_fields": full_text_leaked_fields,
            "full_text_boundary_scope_annotation_fields_present": full_text_scope_annotation_fields_present,
            "full_text_boundary_packet_digest_present": full_text_packet_digest_present,
            "full_text_boundary_review_protocol": full_text_review_protocol,
            "full_text_boundary_review_protocol_present": full_text_review_protocol_contract.get("present", False),
            "full_text_boundary_review_protocol_contract": full_text_review_protocol_contract,
            "full_text_boundary_instructions_review_protocol_present": full_text_instructions_review_protocol_present,
            "policy_boundary_command": policy_cmd,
            "policy_boundary_packet_digest": policy_payload.get("packet_digest") if isinstance(policy_payload, dict) else "",
            "policy_boundary_packet_case_ids": policy_case_ids,
            "policy_boundary_case_types": policy_case_types,
            "policy_boundary_hidden_fields": policy_hidden_fields,
            "policy_boundary_leaked_hidden_fields": policy_leaked_fields,
            "policy_boundary_scope_annotation_fields_present": policy_scope_annotation_fields_present,
            "policy_boundary_packet_digest_present": policy_packet_digest_present,
            "policy_boundary_review_protocol": policy_review_protocol,
            "policy_boundary_review_protocol_present": policy_review_protocol_contract.get("present", False),
            "policy_boundary_review_protocol_contract": policy_review_protocol_contract,
            "policy_boundary_instructions_review_protocol_present": policy_instructions_review_protocol_present,
            "merge_conflict_probe": merge_probe,
            "stdout_tail": _tail(completed.stdout),
            "full_text_stdout_tail": _tail(full_text_completed.stdout),
            "policy_stdout_tail": _tail(policy_completed.stdout),
        }
    )
    if not passed:
        summary["ok"] = False


def _hidden_annotation_packet_key_leaks(value: Any, forbidden_keys: tuple[str, ...]) -> List[str]:
    if isinstance(value, dict):
        leaks = [key for key in value if key in forbidden_keys]
        for nested in value.values():
            leaks.extend(_hidden_annotation_packet_key_leaks(nested, forbidden_keys))
        return sorted(set(leaks))
    if isinstance(value, list):
        leaks: List[str] = []
        for item in value:
            leaks.extend(_hidden_annotation_packet_key_leaks(item, forbidden_keys))
        return sorted(set(leaks))
    return []


def _annotation_packet_scope_fields_present(cases: Any) -> bool:
    return bool(cases) and all(
        isinstance(item, dict)
        and isinstance(item.get("annotation"), dict)
        and "evidence_scope_assessed" in item["annotation"]
        and "full_text_needed" in item["annotation"]
        for item in cases
    )


def _annotation_packet_digest_present(payload: Any, cases: Any) -> bool:
    if not isinstance(payload, dict) or not isinstance(cases, list) or not cases:
        return False
    digest = str(payload.get("packet_digest", "")).strip()
    if not digest.startswith("sha256:") or len(digest) != len("sha256:") + 64:
        return False
    return all(isinstance(item, dict) and item.get("packet_digest") == digest for item in cases)


def _annotation_packet_review_protocol_contract(payload: Any, cases: Any) -> Dict[str, Any]:
    required_fields = [
        "schema_version",
        "packet_role",
        "independent_labeling_required",
        "reviewer_must_not_see_hidden_labels",
        "packet_target_annotator_count",
        "benchmark_target_annotator_count",
        "cases_already_single_annotated",
        "second_review_required_after_first_review",
        "adjudication_required_on_disagreement",
        "merge_policy",
    ]
    required_values = {
        "independent_labeling_required": True,
        "reviewer_must_not_see_hidden_labels": True,
        "packet_target_annotator_count": 1,
        "benchmark_target_annotator_count": 2,
        "adjudication_required_on_disagreement": True,
    }
    protocol = payload.get("review_protocol", {}) if isinstance(payload, dict) else {}
    present = isinstance(protocol, dict) and bool(protocol)
    missing_fields = [field for field in required_fields if not present or field not in protocol]
    value_mismatches = {
        field: protocol.get(field) if present else None
        for field, expected in required_values.items()
        if not present or protocol.get(field) != expected
    }
    packet_role = protocol.get("packet_role") if present else ""
    packet_role_valid = packet_role in {"first_review", "second_review"}
    case_protocol_mismatch_ids = [
        str(item.get("case_id", ""))
        for item in cases
        if not isinstance(item, dict) or item.get("review_protocol") != protocol
    ] if isinstance(cases, list) else []
    cases_present = isinstance(cases, list) and bool(cases)
    case_protocols_match = cases_present and not case_protocol_mismatch_ids
    ok = (
        present
        and cases_present
        and not missing_fields
        and not value_mismatches
        and packet_role_valid
        and case_protocols_match
    )
    return {
        "ok": ok,
        "present": present,
        "packet_role": packet_role,
        "packet_role_valid": packet_role_valid,
        "missing_fields": missing_fields,
        "value_mismatches": value_mismatches,
        "case_protocols_match": case_protocols_match,
        "case_protocol_mismatch_case_ids": case_protocol_mismatch_ids,
    }


def _annotation_packet_instructions_review_protocol_present(text: str) -> bool:
    lowered = str(text or "").lower()
    return (
        "review protocol" in lowered
        and "review_protocol" in str(text or "")
        and "independent" in lowered
    )


def _run_annotation_conflict_merge_probe(
    *,
    python: str,
    project_root: Path,
    dataset: str,
    label_sidecar: str,
    tmpdir: Path,
) -> Dict[str, Any]:
    probe_case_id, probe_label = _annotation_conflict_probe_case(project_root / dataset)
    conflict_packet = tmpdir / "completed-support-label-conflict.jsonl"
    conflict_packet.write_text(
        json.dumps(
            {
                "packet_id": "support-packet-release-gate-conflict",
                "packet_digest": "sha256:" + "e" * 64,
                "packet_case_index": 1,
                "case_id": probe_case_id,
                "review_phase": "first_review_high_risk",
                "packet_purpose": "Release-gate conflict provenance probe.",
                "annotation": {
                    "annotator_id": "release-gate-reviewer",
                    "annotator_label": probe_label,
                    "rationale": "Release gate deliberately checks adjudication_queue conflict provenance.",
                    "confidence": "low",
                    "evidence_scope_assessed": "abstract",
                    "full_text_needed": "unclear",
                },
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    cmd = [
        python,
        "scripts/prepare_support_label_sidecar.py",
        "--dataset",
        dataset,
        "--existing-sidecar",
        label_sidecar,
        "--merge-annotation-packet",
        str(conflict_packet),
    ]
    completed = subprocess.run(
        cmd,
        cwd=str(project_root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode == 0:
        raise RuntimeError("annotation conflict merge probe unexpectedly succeeded")
    if completed.stderr.strip():
        raise RuntimeError(f"annotation conflict merge probe wrote unexpected stderr: {completed.stderr.strip()}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"annotation conflict merge probe did not return JSON stdout: {exc}") from exc
    merge_report = payload.get("merge_report", {}) if isinstance(payload, dict) else {}
    conflicts = merge_report.get("conflicts", []) if isinstance(merge_report, dict) else []
    adjudication_queue = merge_report.get("adjudication_queue", []) if isinstance(merge_report, dict) else []
    first_conflict = conflicts[0] if conflicts and isinstance(conflicts[0], dict) else {}
    first_queue_item = adjudication_queue[0] if adjudication_queue and isinstance(adjudication_queue[0], dict) else {}
    template = first_queue_item.get("adjudication_template", {}) if isinstance(first_queue_item, dict) else {}
    examples = first_conflict.get("annotation_examples", []) if isinstance(first_conflict, dict) else []
    ok = (
        merge_report.get("ok") is False
        and first_conflict.get("code") == "label_mismatch"
        and first_queue_item.get("conflict_code") == "label_mismatch"
        and template.get("case_id") == probe_case_id
        and template.get("adjudicated_label") == ""
        and template.get("source_packet_metadata") == [
            {
                "packet_id": "support-packet-release-gate-conflict",
                "packet_digest": "sha256:" + "e" * 64,
                "review_phase": "first_review_high_risk",
                "packet_purpose": "Release-gate conflict provenance probe.",
            }
        ]
        and bool(examples)
        and examples[0].get("packet_id") == "support-packet-release-gate-conflict"
        and examples[0].get("packet_digest") == "sha256:" + "e" * 64
        and examples[0].get("packet_case_index") == 1
        and examples[0].get("annotator_id") == "release-gate-reviewer"
        and examples[0].get("label") == probe_label
        and examples[0].get("evidence_scope_assessed") == "abstract"
        and examples[0].get("full_text_needed") == "unclear"
        and examples[0].get("review_phase") == "first_review_high_risk"
        and examples[0].get("packet_purpose") == "Release-gate conflict provenance probe."
    )
    if not ok:
        raise RuntimeError("annotation conflict merge probe did not expose adjudication_queue provenance")
    return {
        "ok": True,
        "command": cmd,
        "exit_code": completed.returncode,
        "case_id": probe_case_id,
        "probe_label": probe_label,
        "conflict_code": first_conflict.get("code"),
        "adjudication_queue_count": len(adjudication_queue),
        "adjudication_template_fields": sorted(template),
        "annotation_example_fields": sorted(examples[0]) if examples and isinstance(examples[0], dict) else [],
    }


def _annotation_conflict_probe_case(dataset_path: Path) -> tuple[str, str]:
    from citeguard.verification.support_eval import ALLOWED_SUPPORT_LABELS

    data = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases = data.get("cases", []) if isinstance(data, dict) else []
    for case in cases:
        if not isinstance(case, dict):
            continue
        case_id = str(case.get("id", "")).strip()
        gold = str(case.get("gold", "")).strip()
        if not case_id or gold not in ALLOWED_SUPPORT_LABELS:
            continue
        probe_label = next(label for label in sorted(ALLOWED_SUPPORT_LABELS) if label != gold)
        return case_id, probe_label
    raise RuntimeError("annotation conflict merge probe could not find a labeled support eval case")


def _record_mcp_extra_smoke(
    summary: Dict[str, Any],
    *,
    python: str,
    project_root: Path,
    require: bool,
) -> None:
    python_version = _python_version_tuple(python)
    if python_version < (3, 10):
        status = "failed" if require else "skipped"
        summary["steps"].append(
            {
                "name": "mcp_extra_wheel_install_smoke",
                "status": status,
                "python_version": ".".join(str(part) for part in python_version),
                "message": "MCP extra install smoke requires Python 3.10+ because the upstream MCP SDK does.",
            }
        )
        if require:
            summary["ok"] = False
        return

    _record_subprocess_step(
        summary,
        "mcp_extra_wheel_install_smoke",
        [
            python,
            "scripts/smoke_package.py",
            "--install-mode",
            "wheel",
            "--extra",
            "mcp",
            "--with-deps",
            "--mcp-stdio-smoke",
        ],
        cwd=project_root,
    )


def _record_mcp_stdio_smoke(
    summary: Dict[str, Any],
    *,
    python: str,
    project_root: Path,
    require: bool,
) -> None:
    python_version = _python_version_tuple(python)
    if python_version < (3, 10):
        status = "failed" if require else "skipped"
        summary["steps"].append(
            {
                "name": "mcp_stdio_smoke",
                "status": status,
                "python_version": ".".join(str(part) for part in python_version),
                "message": "MCP stdio smoke requires Python 3.10+ because the upstream MCP SDK does.",
            }
        )
        if require:
            summary["ok"] = False
        return

    if not _module_available(python, "mcp"):
        status = "failed" if require else "skipped"
        summary["steps"].append(
            {
                "name": "mcp_stdio_smoke",
                "status": status,
                "message": (
                    'MCP SDK is not installed. Install published packages with '
                    '`python -m pip install "citeguard[mcp]"`, or use '
                    '`python -m pip install -e ".[mcp]"` from a source checkout.'
                ),
            }
        )
        if require:
            summary["ok"] = False
        return

    cmd = [python, "scripts/smoke_mcp.py"]
    if require:
        cmd.append("--require-sdk")
    _record_subprocess_step(
        summary,
        "mcp_stdio_smoke",
        cmd,
        cwd=project_root,
    )


def _record_published_smoke_plan(
    summary: Dict[str, Any],
    *,
    python: str,
    project_root: Path,
    extra: str,
    require_extra_import: str,
    mcp_stdio_smoke: bool = False,
    index_label: str = "pypi",
    index_url: str = "",
    extra_index_urls: Optional[List[str]] = None,
    run: bool = False,
) -> None:
    cmd = [
        python,
        "scripts/smoke_published_package.py",
        "--version",
        __version__,
    ]
    if run:
        cmd.append("--run")
    if index_url:
        cmd.extend(["--index-url", index_url])
    for extra_index_url in extra_index_urls or []:
        if extra_index_url:
            cmd.extend(["--extra-index-url", extra_index_url])
    if extra:
        cmd.extend(["--extra", extra])
    if require_extra_import:
        cmd.extend(["--require-extra-import", require_extra_import])
    if mcp_stdio_smoke:
        cmd.append("--mcp-stdio-smoke")
    try:
        completed = _run(cmd, cwd=project_root)
        payload = json.loads(completed.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        summary["steps"].append(
            {
                "name": "published_package_smoke_plan",
                "status": "failed",
                "command": cmd,
                "message": str(exc),
            }
        )
        summary["ok"] = False
        return

    config_errors = payload.get("config_errors", [])
    checks_ok = _published_plan_checks_ok(
        payload,
        require_extra_import,
        mcp_stdio_smoke=mcp_stdio_smoke,
    )
    planned_checks = payload.get("planned_checks", [])
    run_checks = payload.get("checks", [])
    failed_checks = [
        item.get("name")
        for item in run_checks
        if isinstance(item, dict) and item.get("status") != "passed"
    ] if isinstance(run_checks, list) else ["checks_not_list"]
    run_checks_ok = (
        isinstance(run_checks, list)
        and isinstance(planned_checks, list)
        and len(run_checks) >= len(planned_checks)
        and not failed_checks
    )
    expected_dry_run = not run
    passed = bool(
        payload.get("ok")
        and payload.get("dry_run") is expected_dry_run
        and checks_ok
        and (run_checks_ok if run else True)
    )
    step_prefix = "published" if index_label == "pypi" else index_label
    step_kind = "run" if run else "plan"
    step_name = (
        f"{step_prefix}_package_smoke_{step_kind}"
        if not extra
        else f"{step_prefix}_{extra}_smoke_{step_kind}"
    )
    summary["steps"].append(
        {
            "name": step_name,
            "status": "passed" if passed else "failed",
            "command": cmd,
            "index_label": index_label,
            "index_url": index_url,
            "extra_index_urls": [url for url in (extra_index_urls or []) if url],
            "package_spec": payload.get("package_spec"),
            "install_command": payload.get("install_command"),
            "planned_checks": planned_checks if isinstance(planned_checks, list) else [],
            "config_errors": config_errors if isinstance(config_errors, list) else [],
            "dry_run": payload.get("dry_run"),
            "run": run,
            "check_count": len(run_checks) if isinstance(run_checks, list) else None,
            "failed_checks": failed_checks,
            "venv_dir": payload.get("venv_dir"),
            "smoke_cwd": payload.get("smoke_cwd"),
        }
    )
    if not passed:
        summary["ok"] = False


def _published_plan_checks_ok(payload: Dict[str, Any], require_extra_import: str = "", *, mcp_stdio_smoke: bool = False) -> bool:
    config_errors = payload.get("config_errors", [])
    if config_errors not in (None, []):
        return False
    planned_checks = payload.get("planned_checks")
    if not isinstance(planned_checks, list):
        return False
    required = {
        "pip_install",
        "import_citeguard",
        "version_contract",
        "import_console_modules",
        "public_package_files",
        "public_api_contract",
        "distribution_metadata",
        "legacy_src_namespace_absent",
        "entry_points",
        "citeguard_cli_help",
        "python_m_citeguard_cli_help",
        "citeguard_cli_fixture_verify",
        "python_m_citeguard_cli_fixture_verify",
        "citeguard_cli_fixture_support",
        "python_m_citeguard_cli_fixture_support",
        "citeguard_cli_fixture_batch",
        "python_m_citeguard_cli_fixture_batch",
        "citeguard_cli_fixture_extract",
        "python_m_citeguard_cli_fixture_extract",
        "citeguard_cli_error_contract",
        "python_m_citeguard_cli_error_contract",
        "citeguard_status",
        "python_m_citeguard_status",
    }
    if require_extra_import:
        required.add(f"import_{require_extra_import}")
    if mcp_stdio_smoke:
        required.add("mcp_stdio_smoke")
    return required.issubset(set(planned_checks))


def _record_subprocess_step(
    summary: Dict[str, Any],
    name: str,
    cmd: List[str],
    *,
    cwd: Path,
) -> None:
    try:
        completed = _run(cmd, cwd=cwd)
    except subprocess.CalledProcessError as exc:
        summary["steps"].append(
            {
                "name": name,
                "status": "failed",
                "command": cmd,
                "stdout_tail": _tail(exc.stdout or ""),
                "stderr_tail": _tail(exc.stderr or ""),
            }
        )
        summary["ok"] = False
        return
    summary["steps"].append(
        {
            "name": name,
            "status": "passed",
            "command": cmd,
            "stdout_tail": _tail(completed.stdout),
        }
    )


def _python_version_tuple(python: str) -> tuple[int, int]:
    completed = subprocess.run(
        [
            python,
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise subprocess.CalledProcessError(completed.returncode, completed.args, completed.stdout, completed.stderr)
    major, minor = completed.stdout.strip().split(".", 1)
    return int(major), int(minor)


def _module_available(python: str, module_name: str) -> bool:
    completed = subprocess.run(
        [python, "-c", f"import {module_name}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.returncode == 0


def _run(cmd: List[str], *, cwd: Path) -> subprocess.CompletedProcess:
    completed = subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        if completed.stdout:
            sys.stderr.write(completed.stdout)
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        raise subprocess.CalledProcessError(completed.returncode, completed.args, completed.stdout, completed.stderr)
    return completed


def _run_no_check(cmd: List[str], *, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _json_payload_or_empty(text: str) -> Dict[str, Any]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _tail(text: str, max_lines: int = 12) -> List[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-max_lines:]


if __name__ == "__main__":
    raise SystemExit(main())
