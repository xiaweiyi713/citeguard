#!/usr/bin/env python3
"""Run package release gates with machine-readable output."""

from __future__ import annotations

import argparse
import json
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
    _record_cache_replay_fixture_gate(summary, python=args.python, project_root=project_root)

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
