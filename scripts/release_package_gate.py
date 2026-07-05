#!/usr/bin/env python3
"""Run package release gates with machine-readable output."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.errors import ERROR_CODE_NEXT_ACTION, ERROR_CODE_RECOVERY, ERROR_SCHEMA_VERSION, STABLE_ERROR_CODES
from citeguard.version import __version__
from scripts.smoke_package import _assert_sdist_contains_release_files, _assert_wheel_contains_core_files


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
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    summary: Dict[str, Any] = {
        "ok": True,
        "project_root": str(project_root),
        "python": args.python,
        "steps": [],
    }

    _record_project_metadata_contract(summary, project_root)
    _record_legacy_src_shim_contract(summary, project_root)
    _record_public_api_contract_gate(summary, project_root)
    _record_cache_replay_fixture_gate(summary, python=args.python, project_root=project_root)
    _record_error_codes_contract_gate(summary, project_root=project_root)
    _record_mcp_stdio_smoke_contract_gate(summary, project_root=project_root)
    _record_cli_error_contract_gate(summary, python=args.python, project_root=project_root)
    _record_source_outage_safety_gate(summary, project_root=project_root)
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
        )

    if args.include_published_mcp_smoke_plan:
        _record_published_smoke_plan(
            summary,
            python=args.python,
            project_root=project_root,
            extra="mcp",
            require_extra_import="mcp",
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
    errors = []
    if public_offenders:
        errors.append("public docs/tests/scripts reference legacy src namespace: " + ", ".join(public_offenders))
    if package_offenders:
        errors.append("citeguard package references legacy src namespace: " + ", ".join(package_offenders))
    if missing_migration_targets:
        errors.append("docs/public_api_migration.md missing public packages: " + ", ".join(missing_migration_targets))
    if "temporary compatibility bridge" not in migration or "DeprecationWarning" not in migration:
        errors.append("public API migration doc must describe legacy src as a temporary compatibility bridge")
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
        "policy": "README, tests, scripts, user-facing docs, and citeguard.* code stay on public citeguard.* imports",
    }


def _public_api_contract_paths(project_root: Path) -> List[Path]:
    paths = [
        project_root / "README.md",
        project_root / "CHANGELOG.md",
        project_root / "docs" / "benchmark_design.md",
        project_root / "docs" / "cli_reference.md",
        project_root / "docs" / "mcp_setup.md",
        project_root / "docs" / "error_codes.md",
        project_root / "docs" / "release_checklist.md",
        project_root / "docs" / "security_compliance.md",
        project_root / "docs" / "support_labeling_guidelines.md",
        project_root / "skills" / "citeguard-verify" / "SKILL.md",
    ]
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

    leaked_timestamp_fields = []
    for item in fixture_records if isinstance(fixture_records, list) else []:
        metadata = item.get("metadata", {}) if isinstance(item, dict) else {}
        provenance = metadata.get("cache_provenance", {}) if isinstance(metadata, dict) else {}
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
    if not replay_records or replay_records[0].title != "Release Cache Replay Fixture":
        errors.append("offline fixture replay did not load the exported record")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "commands": commands,
        "record_count": manifests[0].get("record_count"),
        "deterministic": manifests[0].get("deterministic"),
        "byte_identical": fixture_text_a == fixture_text_b,
        "fixture_record_count": len(fixture_records),
        "replay_record_title": replay_records[0].title if replay_records else "",
        "leaked_timestamp_fields": sorted(set(leaked_timestamp_fields)),
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
    from citeguard.errors import error_payload, is_stable_error_code
    from citeguard.verification import STABLE_NEXT_ACTIONS

    docs = _read_required_text(project_root / "docs" / "error_codes.md")
    stable_codes_section = docs.split("## Stable Codes", 1)[1].split("## Details Contract", 1)[0]
    next_action_section = docs.split("## Stable next_action Values", 1)[1].split("## Stable Codes", 1)[0]
    documented_codes = set(re.findall(r"\| `([^`]+)` \|", stable_codes_section))
    documented_next_actions = set(re.findall(r"\| `([^`]+)` \|", next_action_section))
    registry_codes = set(STABLE_ERROR_CODES)
    registry_next_actions = set(ERROR_CODE_NEXT_ACTION.values())

    probe = error_payload(
        "missing_citation_input",
        "Provide citation input.",
        details={"command": "verify"},
        exit_code=2,
    )

    errors = []
    if registry_codes != set(ERROR_CODE_RECOVERY):
        errors.append("STABLE_ERROR_CODES must match ERROR_CODE_RECOVERY keys")
    if registry_codes != set(ERROR_CODE_NEXT_ACTION):
        errors.append("STABLE_ERROR_CODES must match ERROR_CODE_NEXT_ACTION keys")
    if documented_codes != registry_codes:
        errors.append(
            "docs/error_codes.md stable code table mismatch: "
            f"missing={sorted(registry_codes - documented_codes)} extra={sorted(documented_codes - registry_codes)}"
        )
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
        "`error.recovery` is present on every error payload",
        "`error.next_action` is present on every error payload",
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
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "schema_version": ERROR_SCHEMA_VERSION,
        "documented_code_count": len(documented_codes),
        "stable_code_count": len(registry_codes),
        "documented_next_action_count": len(documented_next_actions),
        "error_codes": sorted(registry_codes),
        "error_next_actions": {code: ERROR_CODE_NEXT_ACTION[code] for code in sorted(registry_codes)},
        "docs_file": "docs/error_codes.md",
        "sample_error": {
            "code": probe_error.get("code"),
            "next_action": probe_error.get("next_action"),
            "recovery": probe_error.get("recovery"),
            "details_keys": sorted(probe_error.get("details", {})),
        },
        "policy": "stable error codes, recovery guidance, next_action mappings, and docs stay synchronized for agents",
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
    normalized_script = _normalize_markdown_text(script)
    normalized_docs = _normalize_markdown_text("\n".join([docs, checklist, readme]))

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
        "offline_fixture_env": "CITEGUARD_FIXTURE_CITATIONS",
        "memory_cache": '"CITEGUARD_CACHE": ":memory:"',
        "status_call": 'session.call_tool("citeguard_status_tool"',
        "status_payload": "_require_status_payload(status, fixture_path)",
        "fixture_verify_call": 'session.call_tool(\n                        "verify_citation_tool"',
        "verified_verdict": 'verify.get("verdict") != "verified"',
        "audit_payload": "_require_audit_citations_payload(audit)",
        "audit_high_risk": "_require_high_risk_filtered_payload(audit_high_risk, total=2, returned_indexes=[1])",
        "claim_support": "_require_support_payload(support)",
        "support_set": '"check_claim_support_set_tool"',
        "support_audit_set": "_require_support_audit_set_payload(support_audit)",
        "support_audit_high_risk": "_require_high_risk_filtered_payload(support_audit_high_risk, total=2, returned_indexes=[1])",
        "counterevidence": "_require_counterevidence_payload(counterevidence)",
        "source_outage_counterevidence": "_require_source_outage_counterevidence_payload(source_outage_counterevidence)",
        "zh_source_outage_counterevidence": "zh_source_outage_counterevidence",
        "structured_error_helper": "_require_error_payload",
        "shape_error_helper": "_require_shape_error_payload",
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
        "offline verify",
        "offline audit",
        "offline support",
        "offline support-audit citation set",
        "offline counter-evidence leads",
        "source-outage safety counter-evidence leads",
        "Chinese source-outage safety leads",
        "high-risk-only batch filtering",
        "source-health next_action",
        "structured errors",
        "batch shape error details",
    ]
    docs_phrases = [
        "python scripts/smoke_mcp.py --require-sdk",
        "mcp_stdio_smoke",
        "MCP stdio smoke",
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
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "script": "scripts/smoke_mcp.py",
        "docs_checked": ["README.md", "docs/mcp_setup.md", "docs/release_checklist.md"],
        "required_tools": required_tools,
        "checked_behaviors": {
            "initialize": True,
            "list_tools": True,
            "offline_fixture": True,
            "status_payload": True,
            "fixture_verify": True,
            "audit_batch": True,
            "audit_high_risk_filter": True,
            "claim_support": True,
            "claim_support_set": True,
            "support_audit_citation_set": True,
            "support_audit_high_risk_filter": True,
            "counterevidence": True,
            "source_outage_safety": True,
            "zh_source_outage_safety": True,
            "structured_errors": True,
            "batch_shape_errors": True,
            "missing_sdk_skip": True,
            "require_sdk_fail": True,
        },
        "structured_error_codes": structured_error_codes,
        "shape_error_fields": ["citations", "items", "citations"],
        "success_terms": success_terms,
        "policy": "MCP stdio smoke must cover initialize, list_tools, fixture-backed verification, status, high-risk filtering, and structured errors",
    }


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
        invalid_support_jsonl.write_text('{"claim": ', encoding="utf-8")

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
        "source_health": {
            "schema_version": health.get("schema_version"),
            "sources_checked": health_summary.get("sources_checked"),
            "sources_responded": health_summary.get("sources_responded"),
            "sources_failed": health_summary.get("sources_failed"),
            "failure_kind_counts": health_summary.get("failure_kind_counts"),
            "failure_kind_sources": health_summary.get("failure_kind_sources"),
            "next_action": health_summary.get("next_action"),
            "all_checked_sources_failed": health_summary.get("all_checked_sources_failed"),
        },
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
    from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
    from citeguard.runtime import SOURCE_HEALTH_SCHEMA_VERSION, canonical_source_names, source_health_status
    from citeguard.verification import CitationRecord

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
        "api_key": "SEMANTIC_SCHOLAR_API_KEY",
    }

    errors = []
    for name, phrase in required_doc_phrases.items():
        if phrase not in combined_docs:
            errors.append(f"live-source health docs missing {name}: {phrase}")

    canonical = canonical_source_names(["OpenAlex", "crossref", "arxiv", "semantic-scholar", "s2"])
    if canonical != ["openalex", "crossref", "arxiv", "semantic_scholar"]:
        errors.append("source aliases should canonicalize and deduplicate four live source families")

    healthy_record = CitationRecord(
        citation_id="live-source-health-1",
        title="Release Gate Live Source Health Control",
        authors=["CiteGuard Maintainer"],
        year=2026,
        venue="Release Gate",
        source="release_fixture",
    )

    def source_factory(names: List[str], **_: Any) -> object:
        name = names[0]
        if name == "openalex":
            raise TimeoutError("openalex timed out during release gate source-health probe")
        if name == "crossref":
            return InMemoryMetadataSource([healthy_record])
        if name == "arxiv":
            return InMemoryMetadataSource([])
        if name == "semantic_scholar":
            return _ReleaseGateDiagnosticSource(
                "semantic_scholar",
                code="source_unavailable",
                kind="rate_limited",
                status_code=429,
                url="https://api.semanticscholar.org/graph/v1/paper/search",
                error="HTTP Error 429: Too Many Requests",
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
    if summary.get("sources_responded") != ["crossref", "arxiv"]:
        errors.append("source health should distinguish responded sources from failed sources")
    if summary.get("sources_available") != ["crossref", "arxiv"]:
        errors.append("source health should treat empty arxiv responses as available source responses")
    if summary.get("sources_failed") != ["openalex", "semantic_scholar"]:
        errors.append("source health should report failed sources separately")
    if summary.get("failure_kind_counts") != {"timeout": 1, "rate_limited": 1}:
        errors.append("source health should summarize timeout and rate-limit failure kinds")
    if summary.get("failure_kind_sources") != {"timeout": ["openalex"], "rate_limited": ["semantic_scholar"]}:
        errors.append("source health should map each failure kind to its source")
    if summary.get("next_action") != "retry_or_check_source_health":
        errors.append("source health should route degraded live checks to retry_or_check_source_health")
    if summary.get("all_checked_sources_failed") is not False:
        errors.append("partial live-source outage should not set all_checked_sources_failed")
    if sources.get("semantic_scholar", {}).get("api_key_configured") is not True:
        errors.append("semantic_scholar source health should expose api_key_configured")
    if sources.get("semantic_scholar", {}).get("polite_access", {}).get("status") != "not_required":
        errors.append("semantic_scholar polite access should not require CITEGUARD_MAILTO")
    if sources.get("openalex", {}).get("mailto_configured") is not True:
        errors.append("openalex source health should expose configured mailto")
    if sources.get("crossref", {}).get("mailto_configured") is not True:
        errors.append("crossref source health should expose configured mailto")

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
        "failure_kind_counts": summary.get("failure_kind_counts"),
        "failure_kind_sources": summary.get("failure_kind_sources"),
        "semantic_scholar": {
            "api_key_configured": sources.get("semantic_scholar", {}).get("api_key_configured"),
            "polite_access": sources.get("semantic_scholar", {}).get("polite_access", {}),
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
        cache_hit: bool = False,
    ) -> None:
        self.last_error_code = code
        self.last_error_kind = kind
        self.last_status_code = status_code
        self.last_url = url
        self.last_error = error
        self.last_cache_hit = cache_hit


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
    ) -> None:
        self.name = name
        self.http_client = _ReleaseGateHTTPDiagnostics(
            code=code,
            kind=kind,
            status_code=status_code,
            url=url,
            error=error,
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
    from citeguard.retrieval.scholarly_clients.evidence import BLOCKED_EVIDENCE_HOST_SUFFIXES
    from citeguard.runtime import environment_status, polite_access_status, source_health_status

    docs = {
        "README.md": _read_required_text(project_root / "README.md"),
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
        "source_health_polite_access": {
            name: sources.get(name, {}).get("polite_access", {})
            for name in ["openalex", "crossref", "arxiv", "semantic_scholar"]
        },
        "remote_evidence_policy": {
            "enabled": remote_policy.get("enabled"),
            "default_enabled": remote_policy.get("default_enabled"),
            "non_http_urls_allowed": remote_policy.get("non_http_urls_allowed"),
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
    skill_path = project_root / "skills" / "citeguard-verify" / "SKILL.md"
    examples_path = project_root / "skills" / "citeguard-verify" / "references" / "examples.md"
    openai_agent_path = project_root / "skills" / "citeguard-verify" / "agents" / "openai.yaml"
    skill = _read_required_text(skill_path)
    examples = _read_required_text(examples_path)
    openai_agent = _read_required_text(openai_agent_path)

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
        "batch_review_summary": "`review_summary` first",
        "high_risk_filtering": "`filtered.returned_indexes`",
        "response_template": "## Response template",
        "scenario_routing": "## Scenario routing",
        "detailed_examples_reference": "references/examples.md",
    }
    required_example_phrases = {
        "single_citation_example": '"tool": "verify_citation_tool"',
        "batch_audit_example": '"tool": "audit_citations_tool"',
        "high_risk_only_example": '"high_risk_only": true',
        "filtered_indexes_wording": "filtered.returned_indexes",
        "claim_support_example": '"tool": "check_claim_support_tool"',
        "support_set_example": '"tool": "check_claim_support_set_tool"',
        "claim_batch_example": '"tool": "audit_claim_support_tool"',
        "shape_error_repair_example": "Malformed batch shape repair",
        "structured_shape_error_details": "error.details.expected=list",
        "counterevidence_example": '"tool": "search_counterevidence_tool"',
        "ambiguous_wording": "do not choose one match",
        "metadata_mismatch_wording": "ask before editing the user's bibliography",
        "not_found_wording": "not proof that the paper is fabricated",
        "source_outage_wording": "not treat source failure as evidence",
        "compact_table": "Suggested compact result table",
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
            "tool_example_count": 8,
            "structured_error_example_count": 1,
            "safe_wording_example_count": 4,
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
    env = {
        "CITEGUARD_FIXTURE_CITATIONS": str(fixture_path),
        "CITEGUARD_RERANKER_MODEL": "",
        "CITEGUARD_NLI_MODEL": "",
        "TOKENIZERS_PARALLELISM": "false",
    }
    commands = {
        "extract_references": [python, "-m", "citeguard", "extract", "examples/references.md", "--compact"],
        "audit_json": [python, "-m", "citeguard", "audit", "examples/citations.json", "--compact"],
        "audit_markdown_high_risk": [
            python,
            "-m",
            "citeguard",
            "audit",
            "examples/references.md",
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
    }
    payloads = {
        name: _run_json_command(command, cwd=project_root, env_overrides=env)
        for name, command in commands.items()
    }

    extract_payload = payloads["extract_references"]
    audit_payload = payloads["audit_json"]
    audit_filtered = payloads["audit_markdown_high_risk"]
    support_payload = payloads["support_audit_json"]
    support_filtered = payloads["support_audit_jsonl_high_risk"]
    support_set = payloads["support_set"]

    errors = []
    if not isinstance(extract_payload, list) or len(extract_payload) != 2:
        errors.append("extract examples/references.md should return two citation candidates")
    elif extract_payload[0].get("arxiv_id") != "1706.03762":
        errors.append("extract examples/references.md should preserve the arXiv id")

    if audit_payload.get("summary", {}).get("verified") != 1 or audit_payload.get("summary", {}).get("not_found") != 1:
        errors.append("audit examples/citations.json should produce one verified and one not_found item")
    audit_review = audit_payload.get("review_summary", {})
    if audit_review.get("high_risk_count") != 1:
        errors.append("audit examples/citations.json should expose one high-risk item")
    if audit_review.get("action_queues", {}).get("identity_resolution_indexes") != [1]:
        errors.append("audit examples/citations.json should queue the unresolved citation for identity resolution")
    if audit_payload.get("risk_ranking", [{}])[0].get("next_action") != "resolve_identifier_or_replace":
        errors.append("audit risk ranking should expose resolve_identifier_or_replace")

    if audit_filtered.get("filtered", {}).get("high_risk_only") is not True:
        errors.append("audit markdown high-risk run should include filtered.high_risk_only=true")
    if audit_filtered.get("filtered", {}).get("returned_indexes") != [1]:
        errors.append("audit markdown high-risk run should preserve returned index 1")
    if len(audit_filtered.get("results", [])) != 1:
        errors.append("audit markdown high-risk run should return one result")

    if support_payload.get("summary", {}).get("insufficient_evidence") != 3:
        errors.append("support-audit examples/claim_citations.json should report three insufficient_evidence items")
    support_review = support_payload.get("review_summary", {})
    if support_review.get("high_risk_count") != 1 or support_review.get("medium_risk_count") != 2:
        errors.append("support-audit examples/claim_citations.json should expose one high and two medium risk items")
    if support_review.get("action_queues", {}).get("identity_resolution_indexes") != [1]:
        errors.append("support-audit should queue unresolved citations for identity resolution")
    support_results = support_payload.get("results", [])
    if len(support_results) != 3 or support_results[2].get("input_mode") != "citation_set":
        errors.append("support-audit should preserve citation_set batch item shape")

    if support_filtered.get("filtered", {}).get("high_risk_only") is not True:
        errors.append("support-audit JSONL high-risk run should include filtered.high_risk_only=true")
    if support_filtered.get("filtered", {}).get("returned_indexes") != [1]:
        errors.append("support-audit JSONL high-risk run should preserve returned index 1")
    if support_filtered.get("filtered", {}).get("omitted_review_summary", {}).get("medium_risk_count") != 2:
        errors.append("support-audit JSONL high-risk run should summarize omitted medium-risk rows")
    if support_set.get("support_mode") != "insufficient_evidence":
        errors.append("support-set example should report insufficient_evidence support_mode")
    if support_set.get("summary", {}).get("insufficient_evidence") != 2:
        errors.append("support-set example should preserve per-citation summary counts")
    if len(support_set.get("results", [])) != 2:
        errors.append("support-set example should return per-citation results")
    if support_set.get("next_action") != "inspect_full_text_or_find_stronger_citation":
        errors.append("support-set example should expose stable next_action")
    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "commands": commands,
        "fixture": "examples/citations.json",
        "extract_count": len(extract_payload),
        "audit_summary": audit_payload.get("summary", {}),
        "audit_returned_indexes": audit_filtered.get("filtered", {}).get("returned_indexes", []),
        "support_summary": support_payload.get("summary", {}),
        "support_input_modes": [item.get("input_mode") for item in support_results],
        "support_returned_indexes": support_filtered.get("filtered", {}).get("returned_indexes", []),
        "support_omitted_review_summary": support_filtered.get("filtered", {}).get("omitted_review_summary", {}),
        "support_set_mode": support_set.get("support_mode"),
        "support_set_summary": support_set.get("summary", {}),
        "support_set_result_count": len(support_set.get("results", [])),
    }


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
        "setup name": 'name="citeguard"',
        "setup version": f'version="{__version__}"',
        "setup readme content type": 'long_description_content_type="text/markdown"',
        "setup python requires": 'python_requires=">=3.9"',
        "setup license file": 'license_files=["LICENSE"]',
        "setup homepage": '"Homepage": "https://github.com/xiaweiyi713/citeguard"',
        "setup repository": '"Repository": "https://github.com/xiaweiyi713/citeguard"',
        "setup issues": '"Issues": "https://github.com/xiaweiyi713/citeguard/issues"',
        "setup changelog": '"Changelog": "https://github.com/xiaweiyi713/citeguard/blob/main/CHANGELOG.md"',
        "citeguard script": 'citeguard = "citeguard.cli:main"',
        "citeguard-mcp script": 'citeguard-mcp = "citeguard.mcp.server:main"',
    }
    combined_metadata_files = f"{pyproject}\n{setup}"
    for label, snippet in required_snippets.items():
        if snippet not in combined_metadata_files:
            errors.append(f"missing {label}")

    required_classifiers = [
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Scientific/Engineering :: Information Analysis",
    ]
    for classifier in required_classifiers:
        if classifier not in pyproject or classifier not in setup:
            errors.append(f"classifier not mirrored in pyproject.toml and setup.py: {classifier}")

    required_extras = ['"api"', '"mcp"', '"models"', '"pdf"', "api = [", "mcp = [", "models = [", "pdf = ["]
    for extra in required_extras:
        if extra not in combined_metadata_files:
            errors.append(f"missing optional dependency metadata: {extra}")

    for path_label, text in (("pyproject.toml", pyproject), ("setup.py", setup)):
        metadata_lines = "\n".join(line for line in text.splitlines() if "github.com" in line or "description" in line)
        if _has_placeholder_text(metadata_lines):
            errors.append(f"{path_label} contains placeholder release metadata")

    if "CiteGuard" not in readme:
        errors.append("README.md should name CiteGuard")
    if "##" not in changelog and "# " not in changelog:
        errors.append("CHANGELOG.md should contain release headings")
    if "MIT License" not in license_text:
        errors.append("LICENSE should contain the MIT license text")

    if errors:
        raise RuntimeError("; ".join(errors))

    return {
        "version": __version__,
        "description": pyproject_description,
        "checked_files": ["pyproject.toml", "setup.py", "README.md", "CHANGELOG.md", "LICENSE"],
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
    passed = bool(gate.get("ok"))
    summary["steps"].append(
        {
            "name": "support_label_sidecar_gate",
            "status": "passed" if passed else "failed",
            "command": cmd,
            "thresholds": gate.get("thresholds", {}),
            "metrics": gate.get("metrics", {}),
            "failures": gate.get("failures", []),
            "stdout_tail": _tail(completed.stdout),
        }
    )
    if not passed:
        summary["ok"] = False


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
    from citeguard.verification.support_eval import load_support_label_cases, load_support_label_sidecar

    cases = load_support_label_cases(str(project_root / dataset))
    sidecar = load_support_label_sidecar(str(project_root / label_sidecar), cases)
    human_reviewed = sum(1 for item in sidecar if item.adjudication_status != "not_human_reviewed")
    dual_annotated = sum(1 for item in sidecar if item.annotator_count >= 2)
    published_benchmark = sum(1 for item in sidecar if item.adjudication_status == "published_benchmark")

    release_docs = {
        "README.md": project_root / "README.md",
        "CHANGELOG.md": project_root / "CHANGELOG.md",
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
    errors = [
        f"{label} missing guard phrase: {phrase}"
        for label, phrase in required_guard_docs.items()
        if _normalize_markdown_text(phrase) not in _normalize_markdown_text(_read_required_text(project_root / label))
    ]
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
        "sidecar_case_count": len(sidecar),
        "human_reviewed": human_reviewed,
        "dual_annotated": dual_annotated,
        "published_benchmark": published_benchmark,
        "release_docs_checked": sorted(release_docs),
        "human_reviewed_benchmark_occurrences": occurrences,
        "unsafe_human_reviewed_benchmark_claims": unsafe_occurrences,
        "policy": "do not describe the synthetic seed set as a human-reviewed benchmark until sidecar maturity proves it",
    }


def _human_reviewed_benchmark_occurrences(text: str, path_label: str) -> List[Dict[str, Any]]:
    pattern = re.compile(r"\bhuman[- ]reviewed\s+(?:support\s+)?benchmark\b", re.IGNORECASE)
    qualifier_pattern = re.compile(
        r"\b(not|not yet|not a|not final|should not|until|before|cannot|can't|large|synthetic)\b",
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
        "--review-queue-only",
    ]
    try:
        completed = _run(cmd, cwd=project_root)
        payload = json.loads(completed.stdout)
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
                "message": f"Could not parse eval_support.py review queue JSON output: {exc}",
                "stdout_tail": _tail(completed.stdout),
            }
        )
        summary["ok"] = False
        return

    quality_gate = payload.get("quality_gate", {}) if isinstance(payload, dict) else {}
    review_queue = payload.get("review_queue", []) if isinstance(payload, dict) else []
    review_queue_summary = payload.get("review_queue_summary", {}) if isinstance(payload, dict) else {}
    passed = isinstance(review_queue, list) and bool(quality_gate.get("ok"))
    summary["steps"].append(
        {
            "name": "support_review_queue",
            "status": "passed" if passed else "failed",
            "command": cmd,
            "case_count": payload.get("case_count") if isinstance(payload, dict) else None,
            "review_queue_count": len(review_queue) if isinstance(review_queue, list) else None,
            "review_queue_summary": review_queue_summary,
            "review_queue_case_ids": quality_gate.get("review_queue_case_ids", []),
            "critical_review_case_ids": quality_gate.get("critical_review_case_ids", []),
            "failures": quality_gate.get("failures", []),
            "support_set_policy": payload.get("support_set_policy", {}) if isinstance(payload, dict) else {},
            "stdout_tail": _tail(completed.stdout),
        }
    )
    if not passed:
        summary["ok"] = False


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
        try:
            completed = _run(cmd, cwd=project_root)
            packet_text = packet_path.read_text(encoding="utf-8")
            instructions_text = instructions_path.read_text(encoding="utf-8")
            payload = json.loads(packet_text)
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
        except (OSError, json.JSONDecodeError) as exc:
            summary["steps"].append(
                {
                    "name": "support_review_queue_annotation_packet",
                    "status": "failed",
                    "command": cmd,
                    "message": f"Could not read or parse review-queue annotation packet: {exc}",
                    "stdout_tail": _tail(locals().get("completed", subprocess.CompletedProcess(cmd, 0, "")).stdout or ""),
                }
            )
            summary["ok"] = False
            return

    filters = payload.get("filters", {}) if isinstance(payload, dict) else {}
    cases = payload.get("cases", []) if isinstance(payload, dict) else []
    packet_summary = payload.get("packet_summary", {}) if isinstance(payload, dict) else {}
    forbidden_fields = ('"gold"', '"predicted"', '"adjudicated_label"', '"annotator_labels"')
    leaked_fields = [field for field in forbidden_fields if field in packet_text]
    ranks = [
        item.get("review_queue_rank")
        for item in cases
        if isinstance(item, dict) and "review_queue_rank" in item
    ]
    passed = (
        bool(payload.get("ok"))
        and payload.get("packet_type") == "support_label_annotation_packet"
        and bool(filters.get("from_review_queue"))
        and bool(filters.get("review_queue_case_ids"))
        and isinstance(cases, list)
        and bool(cases)
        and len(ranks) == len(cases)
        and not leaked_fields
        and "review_queue_rank" in instructions_text
    )
    summary["steps"].append(
        {
            "name": "support_review_queue_annotation_packet",
            "status": "passed" if passed else "failed",
            "command": cmd,
            "packet_id": payload.get("packet_id") if isinstance(payload, dict) else "",
            "case_count": payload.get("n") if isinstance(payload, dict) else None,
            "packet_case_ids": packet_summary.get("case_ids", []) if isinstance(packet_summary, dict) else [],
            "review_queue_case_ids": filters.get("review_queue_case_ids", []) if isinstance(filters, dict) else [],
            "review_queue_ranks": ranks,
            "leaked_hidden_fields": leaked_fields,
            "stdout_tail": _tail(completed.stdout),
        }
    )
    if not passed:
        summary["ok"] = False


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
                "message": "MCP SDK is not installed. Install with `python -m pip install -e \".[mcp]\"`.",
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
) -> None:
    cmd = [
        python,
        "scripts/smoke_published_package.py",
        "--version",
        __version__,
    ]
    if extra:
        cmd.extend(["--extra", extra])
    if require_extra_import:
        cmd.extend(["--require-extra-import", require_extra_import])
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

    summary["steps"].append(
        {
            "name": "published_package_smoke_plan" if not extra else f"published_{extra}_smoke_plan",
            "status": "passed" if payload.get("ok") and payload.get("dry_run") else "failed",
            "command": cmd,
            "package_spec": payload.get("package_spec"),
            "install_command": payload.get("install_command"),
            "dry_run": payload.get("dry_run"),
        }
    )
    if not payload.get("ok") or not payload.get("dry_run"):
        summary["ok"] = False


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
