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
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    summary: Dict[str, Any] = {
        "ok": True,
        "project_root": str(project_root),
        "python": args.python,
        "steps": [],
    }

    _record_project_metadata_contract(summary, project_root)

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


def _tail(text: str, max_lines: int = 12) -> List[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-max_lines:]


if __name__ == "__main__":
    raise SystemExit(main())
