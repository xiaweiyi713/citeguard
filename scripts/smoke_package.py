#!/usr/bin/env python3
"""Smoke-test CiteGuard after installing it into a fresh virtual environment."""

from __future__ import annotations

import argparse
from email.parser import Parser
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import List, Optional

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.version import __version__


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Install CiteGuard in a fresh venv and run core package smoke checks.")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--python", default=sys.executable, help="Python executable used to create the smoke venv.")
    parser.add_argument("--venv-dir", default="", help="Optional venv directory; defaults to a temporary directory.")
    parser.add_argument("--keep-venv", action="store_true", help="Do not delete the smoke venv after the run.")
    parser.add_argument(
        "--extra",
        default="",
        help="Optional package extra to install, e.g. mcp. Empty means core package only.",
    )
    parser.add_argument(
        "--with-deps",
        action="store_true",
        help="Install dependencies for the selected package spec. Default uses --no-deps for fast/offline archive checks.",
    )
    parser.add_argument(
        "--install-mode",
        choices=("source", "wheel", "sdist"),
        default="source",
        help="Install the package from the project tree, a freshly built wheel, or a freshly built source distribution.",
    )
    parser.add_argument(
        "--no-build-isolation",
        action="store_true",
        help="Pass --no-build-isolation to pip install/pip wheel for offline release checks with preinstalled build tools.",
    )
    args = parser.parse_args(argv)

    if args.extra == "mcp" and args.with_deps:
        python_version = _python_version_tuple(args.python)
        if python_version < (3, 10):
            raise RuntimeError("MCP extra install smoke requires Python 3.10+ because the upstream MCP SDK does.")

    project_root = Path(args.project_root).resolve()
    venv_dir = Path(args.venv_dir).resolve() if args.venv_dir else Path(tempfile.mkdtemp(prefix="citeguard-package-smoke-"))
    created_temp = not args.venv_dir
    artifact_dir: Optional[Path] = None
    try:
        package_spec = _package_spec_from_source(project_root, args.extra)
        if args.install_mode == "wheel":
            artifact_dir = Path(tempfile.mkdtemp(prefix="citeguard-package-wheel-"))
            wheel_path = _build_wheel(args.python, project_root, artifact_dir, args.no_build_isolation)
            _assert_wheel_contains_core_files(wheel_path)
            package_spec = _package_spec_from_wheel(wheel_path, args.extra)
        elif args.install_mode == "sdist":
            artifact_dir = Path(tempfile.mkdtemp(prefix="citeguard-package-sdist-"))
            sdist_path = _build_sdist(args.python, project_root, artifact_dir)
            _assert_sdist_contains_release_files(sdist_path)
            package_spec = _package_spec_from_sdist(sdist_path, args.extra)

        _create_venv(args.python, venv_dir)
        python = _venv_python(venv_dir)
        bin_dir = python.parent
        install_cmd = [str(python), "-m", "pip", "install"]
        if args.no_build_isolation:
            install_cmd.append("--no-build-isolation")
        if not args.with_deps:
            install_cmd.append("--no-deps")
        install_cmd.append(package_spec)
        _run(install_cmd)
        _run([str(python), "-c", _IMPORT_SMOKE])
        _run([str(python), "-c", _ENTRY_POINT_SMOKE])
        if args.extra == "mcp" and args.with_deps:
            _run([str(python), "-c", _MCP_EXTRA_SMOKE])
        status = _run_json([str(bin_dir / "citeguard"), "status", "--compact"])
        if status.get("service") != "CiteGuard":
            raise RuntimeError(f"unexpected citeguard status payload: {status!r}")
        module_status = _run_json([str(python), "-m", "citeguard.cli", "status", "--compact"])
        if module_status.get("service") != "CiteGuard":
            raise RuntimeError(f"unexpected python -m citeguard.cli payload: {module_status!r}")
        package_status = _run_json([str(python), "-m", "citeguard", "status", "--compact"])
        if package_status.get("service") != "CiteGuard":
            raise RuntimeError(f"unexpected python -m citeguard payload: {package_status!r}")
        extra_label = f" + {args.extra} extra" if args.extra else ""
        deps_label = "with dependencies" if args.with_deps else "without dependencies"
        print(f"OK: package smoke passed in {venv_dir} using {args.install_mode} install{extra_label} {deps_label}")
        return 0
    finally:
        if created_temp and not args.keep_venv:
            shutil.rmtree(venv_dir, ignore_errors=True)
        if artifact_dir is not None:
            shutil.rmtree(artifact_dir, ignore_errors=True)


def _package_spec_from_source(project_root: Path, extra: str) -> str:
    return str(project_root) if not extra else f"{project_root}[{extra}]"


def _package_spec_from_wheel(wheel_path: Path, extra: str) -> str:
    return str(wheel_path) if not extra else f"{wheel_path}[{extra}]"


def _package_spec_from_sdist(sdist_path: Path, extra: str) -> str:
    return str(sdist_path) if not extra else f"{sdist_path}[{extra}]"


def _build_wheel(python: str, project_root: Path, wheel_dir: Path, no_build_isolation: bool) -> Path:
    cmd = [python, "-m", "pip", "wheel", "--no-deps", "--wheel-dir", str(wheel_dir)]
    if no_build_isolation:
        cmd.append("--no-build-isolation")
    cmd.append(str(project_root))
    _run(cmd)

    wheels = sorted(wheel_dir.glob("citeguard-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one CiteGuard wheel in {wheel_dir}, found: {wheels}")
    return wheels[0]


def _build_sdist(python: str, project_root: Path, sdist_dir: Path) -> Path:
    copied_project = sdist_dir / "project"
    dist_dir = sdist_dir / "dist"
    shutil.copytree(
        project_root,
        copied_project,
        ignore=shutil.ignore_patterns(
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
        ),
    )
    dist_dir.mkdir(parents=True, exist_ok=True)
    _run([python, "setup.py", "sdist", "--dist-dir", str(dist_dir)], cwd=copied_project)

    sdists = sorted(dist_dir.glob("citeguard-*.tar.gz"))
    if len(sdists) != 1:
        raise RuntimeError(f"expected exactly one CiteGuard sdist in {dist_dir}, found: {sdists}")
    return sdists[0]


def _assert_wheel_contains_core_files(wheel_path: Path) -> None:
    required = {
        "citeguard/__init__.py",
        "citeguard/__main__.py",
        "citeguard/cli.py",
        "citeguard/runtime.py",
        "citeguard/errors.py",
        "citeguard/py.typed",
        "citeguard/mcp/server.py",
        "citeguard/retrieval/__init__.py",
        "citeguard/verification/__init__.py",
        "citeguard/verification/verify.py",
        "src/__init__.py",
        "src/verification/verify.py",
    }
    with zipfile.ZipFile(wheel_path) as wheel:
        names = set(wheel.namelist())

    _assert_archive_excludes_generated_files(names, archive_label="wheel")
    missing = sorted(required - names)
    if missing:
        raise RuntimeError(f"wheel is missing expected package files: {missing}")
    if not any(name.endswith(".dist-info/entry_points.txt") for name in names):
        raise RuntimeError("wheel is missing console-script entry point metadata")
    _assert_wheel_metadata_contract(wheel_path)


def _assert_sdist_contains_release_files(sdist_path: Path) -> None:
    required = {
        "pyproject.toml",
        "setup.py",
        "MANIFEST.in",
        "README.md",
        "CHANGELOG.md",
        "LICENSE",
        "citeguard/__init__.py",
        "citeguard/__main__.py",
        "citeguard/mcp/server.py",
        "citeguard/retrieval/scholarly_clients/factory.py",
        "citeguard/verification/verify.py",
        "src/__init__.py",
        "src/verification/verify.py",
        "docs/cli_reference.md",
        "docs/mcp_setup.md",
        "docs/error_codes.md",
        "docs/release_checklist.md",
        "docs/security_compliance.md",
        "examples/citations.json",
        "examples/claim_citations.json",
        "examples/claim_citations.jsonl",
        "data/eval/support_eval.json",
        "data/eval/support_eval_label_sidecar.json",
        "skills/citeguard-verify/SKILL.md",
        "scripts/smoke_mcp.py",
        "scripts/smoke_package.py",
        "scripts/smoke_published_package.py",
        "scripts/release_package_gate.py",
        "scripts/prepare_support_label_sidecar.py",
        "scripts/compare_support_baselines.py",
    }
    with tarfile.open(sdist_path, "r:gz") as sdist:
        names = {_strip_archive_root(member.name) for member in sdist.getmembers() if member.isfile()}

    _assert_archive_excludes_generated_files(names, archive_label="sdist")
    missing = sorted(required - names)
    if missing:
        raise RuntimeError(f"sdist is missing expected release files: {missing}")
    _assert_sdist_metadata_contract(sdist_path)


def _assert_wheel_metadata_contract(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as wheel:
        metadata_names = [name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")]
        if len(metadata_names) != 1:
            raise RuntimeError(f"wheel should contain exactly one METADATA file, found: {metadata_names}")
        metadata_text = wheel.read(metadata_names[0]).decode("utf-8")
    _assert_distribution_metadata_contract(metadata_text, archive_label="wheel")


def _assert_sdist_metadata_contract(sdist_path: Path) -> None:
    with tarfile.open(sdist_path, "r:gz") as sdist:
        pkg_info_members = [
            member
            for member in sdist.getmembers()
            if member.isfile()
            and member.name.endswith("/PKG-INFO")
            and len(member.name.split("/")) == 2
        ]
        if len(pkg_info_members) != 1:
            raise RuntimeError(f"sdist should contain exactly one PKG-INFO file, found: {[member.name for member in pkg_info_members]}")
        extracted = sdist.extractfile(pkg_info_members[0])
        if extracted is None:
            raise RuntimeError("sdist PKG-INFO could not be read")
        metadata_text = extracted.read().decode("utf-8")
        requires_members = [
            member
            for member in sdist.getmembers()
            if member.isfile() and member.name.endswith("/citeguard.egg-info/requires.txt")
        ]
        if len(requires_members) != 1:
            raise RuntimeError(f"sdist should contain exactly one egg-info requires.txt file, found: {[member.name for member in requires_members]}")
        requires_file = sdist.extractfile(requires_members[0])
        if requires_file is None:
            raise RuntimeError("sdist egg-info requires.txt could not be read")
        requires_text = requires_file.read().decode("utf-8")
    _assert_distribution_metadata_contract(metadata_text, archive_label="sdist", require_dependency_metadata=False)
    _assert_sdist_requires_contract(requires_text)


def _assert_distribution_metadata_contract(metadata_text: str, archive_label: str, require_dependency_metadata: bool = True) -> None:
    metadata = Parser().parsestr(metadata_text)
    errors = []

    expected_single_values = {
        "Name": "citeguard",
        "Version": __version__,
        "Requires-Python": ">=3.9",
    }
    for key, expected in expected_single_values.items():
        actual = metadata.get(key, "")
        if actual != expected:
            errors.append(f"{key} expected {expected!r}, got {actual!r}")

    summary = metadata.get("Summary", "")
    if not summary or _has_placeholder_text(summary):
        errors.append("Summary is missing or placeholder-like")
    if "prototype" in summary.lower():
        errors.append("Summary should describe the product, not a prototype")

    classifiers = set(metadata.get_all("Classifier") or [])
    required_classifiers = {
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.10",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
        "Topic :: Scientific/Engineering :: Information Analysis",
    }
    missing_classifiers = sorted(required_classifiers - classifiers)
    if missing_classifiers:
        errors.append(f"missing classifiers: {missing_classifiers}")

    extras = set(metadata.get_all("Provides-Extra") or [])
    missing_extras = sorted({"api", "mcp", "models", "pdf"} - extras)
    if missing_extras:
        errors.append(f"missing optional extras: {missing_extras}")

    if require_dependency_metadata:
        requires_dist = metadata.get_all("Requires-Dist") or []
        if not any("pypdf" in item and "extra ==" in item and "pdf" in item for item in requires_dist):
            errors.append("missing pdf extra pypdf dependency in Requires-Dist")
        if not any("mcp" in item and "extra ==" in item and "mcp" in item for item in requires_dist):
            errors.append("missing mcp extra dependency in Requires-Dist")

    project_urls = metadata.get_all("Project-URL") or []
    required_url_labels = {"Homepage", "Repository", "Issues", "Changelog"}
    actual_url_labels = {item.split(",", 1)[0].strip() for item in project_urls if "," in item}
    missing_url_labels = sorted(required_url_labels - actual_url_labels)
    if missing_url_labels:
        errors.append(f"missing project URLs: {missing_url_labels}")
    for item in project_urls:
        if _has_placeholder_text(item):
            errors.append(f"placeholder project URL: {item}")

    license_files = metadata.get_all("License-File") or []
    if "LICENSE" not in license_files:
        errors.append("missing LICENSE in License-File metadata")

    if errors:
        raise RuntimeError(f"{archive_label} metadata contract failed: {'; '.join(errors)}")


def _assert_sdist_requires_contract(requires_text: str) -> None:
    required = {
        "[api]": ["fastapi", "uvicorn"],
        "[mcp]": ["mcp>=1.2"],
        "[models]": ["sentence-transformers", "transformers", "torch", "safetensors"],
        "[pdf]": ["pypdf"],
    }
    errors = []
    for section, packages in required.items():
        if section not in requires_text:
            errors.append(f"missing {section} section")
            continue
        section_text = requires_text.split(section, 1)[1].split("[", 1)[0]
        for package in packages:
            if package not in section_text:
                errors.append(f"missing {package} in {section}")
    if errors:
        raise RuntimeError(f"sdist dependency metadata contract failed: {'; '.join(errors)}")


def _has_placeholder_text(value: str) -> bool:
    lowered = value.lower()
    return any(token in lowered for token in ("todo", "tbd", "example.com", "your-name", "your-org"))


def _assert_archive_excludes_generated_files(names: set[str], archive_label: str) -> None:
    forbidden = []
    for name in sorted(names):
        parts = set(name.split("/"))
        if (
            "__pycache__" in parts
            or ".venv" in parts
            or name.endswith(".pyc")
            or name.endswith(".pyo")
            or name.endswith(".DS_Store")
        ):
            forbidden.append(name)
    if forbidden:
        raise RuntimeError(f"{archive_label} includes generated/local files: {forbidden[:20]}")


def _strip_archive_root(name: str) -> str:
    parts = name.split("/")
    return "/".join(parts[1:]) if len(parts) > 1 else name


def _create_venv(python: str, venv_dir: Path) -> None:
    if venv_dir.exists() and any(venv_dir.iterdir()):
        raise RuntimeError(f"venv directory already exists and is not empty: {venv_dir}")
    _run([python, "-m", "venv", str(venv_dir)])


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _python_version_tuple(python: str) -> tuple[int, int]:
    completed = _run(
        [
            python,
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ]
    )
    major, minor = completed.stdout.strip().split(".", 1)
    return int(major), int(minor)


def _run(cmd: List[str], cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    completed = subprocess.run(cmd, cwd=str(cwd) if cwd is not None else None, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        if completed.stdout:
            sys.stderr.write(completed.stdout)
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        raise subprocess.CalledProcessError(completed.returncode, completed.args, completed.stdout, completed.stderr)
    return completed


def _run_json(cmd: List[str]) -> dict:
    completed = _run(cmd)
    return json.loads(completed.stdout)


_IMPORT_SMOKE = r"""
from citeguard import ERROR_CODE_NEXT_ACTION, STABLE_NEXT_ACTIONS, parse_citation, verify_citation, check_claim_support_set, available_sources, stable_next_action, verification_next_action, verification_recovery_code, Verdict
from citeguard.verification import search_counterevidence_candidates
from citeguard.runtime import environment_status
assert parse_citation(title="A Paper").title == "A Paper"
assert callable(verify_citation)
assert callable(check_claim_support_set)
assert available_sources(["openalex", "arxiv"], ["arxiv"]) == ["openalex"]
assert "rewrite_or_replace_evidence" in STABLE_NEXT_ACTIONS
assert "review_counterevidence_leads" in STABLE_NEXT_ACTIONS
assert ERROR_CODE_NEXT_ACTION["missing_claim"] == "provide_missing_input"
assert stable_next_action("keep") == "keep"
assert stable_next_action("review_counterevidence_leads") == "review_counterevidence_leads"
assert verification_recovery_code(Verdict.AMBIGUOUS, []) == "ambiguous_citation"
assert verification_next_action(Verdict.NOT_FOUND) == "resolve_identifier_or_replace"
assert callable(search_counterevidence_candidates)
status = environment_status()
assert status["service"] == "CiteGuard"
assert status["cache_status"]["inspect_ok"] is True
assert "entry_prefixes" in status["cache_status"]
	"""


_ENTRY_POINT_SMOKE = r"""
from importlib.metadata import distribution, entry_points
eps = entry_points()
console_scripts = eps.select(group="console_scripts") if hasattr(eps, "select") else eps.get("console_scripts", [])
scripts = {
    item.name: item.value
    for item in console_scripts
    if item.name in {"citeguard", "citeguard-mcp"}
}
assert scripts["citeguard"] == "citeguard.cli:main"
assert scripts["citeguard-mcp"] == "citeguard.mcp.server:main"
metadata = distribution("citeguard").metadata
extras = set(metadata.get_all("Provides-Extra") or [])
assert {"mcp", "models", "api", "pdf"}.issubset(extras)
requires_dist = metadata.get_all("Requires-Dist") or []
assert any("pypdf" in item and "extra ==" in item and "pdf" in item for item in requires_dist)
assert any("mcp" in item and "extra ==" in item and "mcp" in item for item in requires_dist)
"""


_MCP_EXTRA_SMOKE = r"""
import importlib.util
from importlib.metadata import distribution

assert importlib.util.find_spec("mcp") is not None
import citeguard.mcp.server as server
assert callable(server.main)
metadata = distribution("citeguard").metadata
requires_dist = metadata.get_all("Requires-Dist") or []
assert any("mcp" in item and "extra ==" in item and "mcp" in item for item in requires_dist)
"""


if __name__ == "__main__":
    raise SystemExit(main())
