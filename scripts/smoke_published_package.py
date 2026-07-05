#!/usr/bin/env python3
"""Smoke-test CiteGuard after installing it from a package index."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install CiteGuard from PyPI/TestPyPI in a fresh venv and run post-publish smoke checks."
    )
    parser.add_argument("--python", default=sys.executable, help="Python executable used to create the smoke venv.")
    parser.add_argument("--venv-dir", default="", help="Optional venv directory; defaults to a temporary directory.")
    parser.add_argument("--keep-venv", action="store_true", help="Do not delete the smoke venv after the run.")
    parser.add_argument("--package", default="citeguard", help="Published package name to install.")
    parser.add_argument("--version", default="", help="Exact package version to install, for example 0.1.0.")
    parser.add_argument("--extra", action="append", default=[], help="Optional extra to install; can be repeated.")
    parser.add_argument("--index-url", default="", help="Optional package index URL, e.g. TestPyPI.")
    parser.add_argument("--extra-index-url", action="append", default=[], help="Additional package index URL.")
    parser.add_argument(
        "--require-extra-import",
        action="append",
        default=[],
        help="Import that must succeed after install, e.g. mcp. Can be repeated.",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Actually create a venv, install from the package index, and run smoke checks. Default is dry-run.",
    )
    args = parser.parse_args(argv)

    package_spec = _package_spec(args.package, version=args.version, extras=args.extra)
    install_cmd = _pip_install_command(
        package_spec,
        index_url=args.index_url,
        extra_index_urls=args.extra_index_url,
    )
    summary: Dict[str, Any] = {
        "ok": True,
        "dry_run": not args.run,
        "package_spec": package_spec,
        "python": args.python,
        "install_command": install_cmd,
        "checks": [],
    }

    if not args.run:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0

    venv_dir = Path(args.venv_dir).resolve() if args.venv_dir else Path(tempfile.mkdtemp(prefix="citeguard-published-smoke-"))
    created_temp = not args.venv_dir
    summary["venv_dir"] = str(venv_dir)
    try:
        _create_venv(args.python, venv_dir)
        python = _venv_python(venv_dir)
        bin_dir = python.parent
        resolved_install_cmd = [str(python), "-m", "pip", "install", *install_cmd[3:]]
        _record_subprocess(summary, "pip_install", resolved_install_cmd)
        _record_subprocess(summary, "import_citeguard", [str(python), "-c", _IMPORT_CITEGUARD])
        _record_subprocess(summary, "import_console_modules", [str(python), "-c", _IMPORT_CONSOLE_MODULES])
        for module_name in args.require_extra_import:
            _record_subprocess(summary, f"import_{module_name}", [str(python), "-c", f"import {module_name}"])
        _record_json_command(summary, "citeguard_status", [str(bin_dir / "citeguard"), "status", "--compact"])
        _record_json_command(summary, "python_m_citeguard_status", [str(python), "-m", "citeguard", "status", "--compact"])
    finally:
        if created_temp and not args.keep_venv:
            shutil.rmtree(venv_dir, ignore_errors=True)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary["ok"] else 1


def _package_spec(package: str, *, version: str = "", extras: Optional[List[str]] = None) -> str:
    extras = [extra.strip() for extra in (extras or []) if extra.strip()]
    extra_suffix = f"[{','.join(extras)}]" if extras else ""
    version_suffix = f"=={version.strip()}" if version.strip() else ""
    return f"{package.strip()}{extra_suffix}{version_suffix}"


def _pip_install_command(package_spec: str, *, index_url: str = "", extra_index_urls: Optional[List[str]] = None) -> List[str]:
    cmd = ["python", "-m", "pip", "install"]
    if index_url:
        cmd.extend(["--index-url", index_url])
    for url in extra_index_urls or []:
        if url:
            cmd.extend(["--extra-index-url", url])
    cmd.append(package_spec)
    return cmd


def _create_venv(python: str, venv_dir: Path) -> None:
    subprocess.run([python, "-m", "venv", str(venv_dir)], check=True)


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _record_subprocess(summary: Dict[str, Any], name: str, cmd: List[str]) -> None:
    completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    item = {
        "name": name,
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": cmd,
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
    }
    summary["checks"].append(item)
    if completed.returncode != 0:
        summary["ok"] = False


def _record_json_command(summary: Dict[str, Any], name: str, cmd: List[str]) -> None:
    completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    item = {
        "name": name,
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": cmd,
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
    }
    if completed.returncode == 0:
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            item["status"] = "failed"
            item["message"] = f"stdout was not JSON: {exc.msg}"
        else:
            item["service"] = payload.get("service")
            if payload.get("service") != "CiteGuard":
                item["status"] = "failed"
                item["message"] = "status payload did not identify CiteGuard"
    summary["checks"].append(item)
    if item["status"] != "passed":
        summary["ok"] = False


def _tail(text: str, max_lines: int = 12) -> List[str]:
    lines = [line for line in text.splitlines() if line.strip()]
    return lines[-max_lines:]


_IMPORT_CITEGUARD = """
import citeguard
from citeguard.version import __version__
assert isinstance(__version__, str) and __version__
"""

_IMPORT_CONSOLE_MODULES = """
import citeguard.cli
import citeguard.mcp.server
"""


if __name__ == "__main__":
    raise SystemExit(main())
