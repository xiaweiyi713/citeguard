#!/usr/bin/env python3
"""Smoke-test CiteGuard after installing it from a package index."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

_MODULE_IMPORT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Install CiteGuard from PyPI/TestPyPI in a fresh venv and run post-publish smoke checks."
    )
    parser.add_argument("--python", default=sys.executable, help="Python executable used to create the smoke venv.")
    parser.add_argument("--venv-dir", default="", help="Optional venv directory; defaults to a temporary directory.")
    parser.add_argument("--keep-venv", action="store_true", help="Do not delete the smoke venv after the run.")
    parser.add_argument("--package", default="citationguard", help="Published package name to install.")
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
        "--mcp-stdio-smoke",
        action="store_true",
        help="After install, launch the installed citeguard-mcp entry point and run an offline stdio smoke.",
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
    planned_checks = _planned_checks(
        args.require_extra_import,
        expected_version=args.version,
        mcp_stdio_smoke=args.mcp_stdio_smoke,
    )
    config_errors = _config_errors(
        args.extra,
        required_extra_imports=args.require_extra_import,
        mcp_stdio_smoke=args.mcp_stdio_smoke,
    )
    summary: Dict[str, Any] = {
        "ok": not config_errors,
        "dry_run": not args.run,
        "package_spec": package_spec,
        "python": args.python,
        "install_command": install_cmd,
        "planned_checks": planned_checks,
        "config_errors": config_errors,
        "checks": [],
    }

    if not args.run or config_errors:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 0 if summary["ok"] else 1

    venv_dir = Path(args.venv_dir).resolve() if args.venv_dir else Path(tempfile.mkdtemp(prefix="citeguard-published-smoke-"))
    created_temp = not args.venv_dir
    summary["venv_dir"] = str(venv_dir)
    try:
        try:
            _create_venv(args.python, venv_dir)
        except (OSError, subprocess.CalledProcessError) as exc:
            _record_setup_failure(summary, "venv_create", [args.python, "-m", "venv", str(venv_dir)], exc)
            print(json.dumps(summary, indent=2, ensure_ascii=False))
            return 1
        python = _venv_python(venv_dir)
        bin_dir = python.parent
        smoke_cwd = venv_dir / "smoke-cwd"
        smoke_cwd.mkdir(parents=True, exist_ok=True)
        summary["smoke_cwd"] = str(smoke_cwd)
        resolved_install_cmd = [str(python), "-m", "pip", "install", *install_cmd[3:]]
        _record_subprocess(summary, "pip_install", resolved_install_cmd, cwd=smoke_cwd)
        _record_subprocess(summary, "import_citeguard", [str(python), "-c", _IMPORT_CITEGUARD], cwd=smoke_cwd)
        if args.version:
            _record_subprocess(
                summary,
                "version_contract",
                [str(python), "-c", _VERSION_CONTRACT_SMOKE, args.version],
                cwd=smoke_cwd,
            )
        _record_subprocess(summary, "import_console_modules", [str(python), "-c", _IMPORT_CONSOLE_MODULES], cwd=smoke_cwd)
        _record_subprocess(summary, "public_package_files", [str(python), "-c", _PUBLIC_PACKAGE_FILES_SMOKE], cwd=smoke_cwd)
        _record_subprocess(summary, "public_api_contract", [str(python), "-c", _PUBLIC_API_CONTRACT_SMOKE], cwd=smoke_cwd)
        _record_subprocess(summary, "distribution_metadata", [str(python), "-c", _DISTRIBUTION_METADATA_SMOKE], cwd=smoke_cwd)
        _record_subprocess(
            summary,
            "legacy_src_namespace_absent",
            [str(python), "-c", _LEGACY_NAMESPACE_ABSENT_SMOKE],
            cwd=smoke_cwd,
        )
        _record_subprocess(summary, "entry_points", [str(python), "-c", _ENTRY_POINT_SMOKE], cwd=smoke_cwd)
        for module_name in args.require_extra_import:
            _record_subprocess(summary, f"import_{module_name}", [str(python), "-c", f"import {module_name}"], cwd=smoke_cwd)
        _record_subprocess(
            summary,
            "citeguard_cli_help",
            [str(python), "-c", _CLI_HELP_SMOKE, str(_console_script(bin_dir, "citeguard"))],
            cwd=smoke_cwd,
        )
        _record_subprocess(
            summary,
            "python_m_citeguard_cli_help",
            [str(python), "-c", _CLI_HELP_SMOKE, str(python), "-m", "citeguard"],
            cwd=smoke_cwd,
        )
        _record_subprocess(
            summary,
            "citeguard_cli_fixture_verify",
            [str(python), "-c", _CLI_FIXTURE_VERIFY_SMOKE, str(_console_script(bin_dir, "citeguard"))],
            cwd=smoke_cwd,
        )
        _record_subprocess(
            summary,
            "python_m_citeguard_cli_fixture_verify",
            [str(python), "-c", _CLI_FIXTURE_VERIFY_SMOKE, str(python), "-m", "citeguard"],
            cwd=smoke_cwd,
        )
        _record_subprocess(
            summary,
            "citeguard_cli_fixture_support",
            [str(python), "-c", _CLI_FIXTURE_SUPPORT_SMOKE, str(_console_script(bin_dir, "citeguard"))],
            cwd=smoke_cwd,
        )
        _record_subprocess(
            summary,
            "python_m_citeguard_cli_fixture_support",
            [str(python), "-c", _CLI_FIXTURE_SUPPORT_SMOKE, str(python), "-m", "citeguard"],
            cwd=smoke_cwd,
        )
        _record_subprocess(
            summary,
            "citeguard_cli_fixture_batch",
            [str(python), "-c", _CLI_FIXTURE_BATCH_SMOKE, str(_console_script(bin_dir, "citeguard"))],
            cwd=smoke_cwd,
        )
        _record_subprocess(
            summary,
            "python_m_citeguard_cli_fixture_batch",
            [str(python), "-c", _CLI_FIXTURE_BATCH_SMOKE, str(python), "-m", "citeguard"],
            cwd=smoke_cwd,
        )
        _record_subprocess(
            summary,
            "citeguard_cli_fixture_extract",
            [str(python), "-c", _CLI_FIXTURE_EXTRACT_SMOKE, str(_console_script(bin_dir, "citeguard"))],
            cwd=smoke_cwd,
        )
        _record_subprocess(
            summary,
            "python_m_citeguard_cli_fixture_extract",
            [str(python), "-c", _CLI_FIXTURE_EXTRACT_SMOKE, str(python), "-m", "citeguard"],
            cwd=smoke_cwd,
        )
        _record_subprocess(
            summary,
            "citeguard_cli_error_contract",
            [str(python), "-c", _CLI_ERROR_CONTRACT_SMOKE, str(_console_script(bin_dir, "citeguard"))],
            cwd=smoke_cwd,
        )
        _record_subprocess(
            summary,
            "python_m_citeguard_cli_error_contract",
            [str(python), "-c", _CLI_ERROR_CONTRACT_SMOKE, str(python), "-m", "citeguard"],
            cwd=smoke_cwd,
        )
        _record_json_command(summary, "citeguard_status", [str(bin_dir / "citeguard"), "status", "--compact"], cwd=smoke_cwd)
        _record_json_command(summary, "python_m_citeguard_status", [str(python), "-m", "citeguard", "status", "--compact"], cwd=smoke_cwd)
        if args.mcp_stdio_smoke:
            _record_subprocess(
                summary,
                "mcp_stdio_smoke",
                [str(python), "-c", _PUBLISHED_MCP_STDIO_SMOKE, str(_console_script(bin_dir, "citeguard-mcp"))],
                cwd=smoke_cwd,
            )
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


def _config_errors(
    extras: Optional[List[str]] = None,
    *,
    required_extra_imports: Optional[List[str]] = None,
    mcp_stdio_smoke: bool = False,
) -> List[Dict[str, Any]]:
    normalized_extras = {extra.strip() for extra in (extras or []) if extra.strip()}
    errors: List[Dict[str, Any]] = []
    if mcp_stdio_smoke and "mcp" not in normalized_extras:
        errors.append(
            {
                "code": "mcp_stdio_smoke_requires_mcp_extra",
                "message": "--mcp-stdio-smoke requires --extra mcp for a fresh post-publish venv.",
                "details": {
                    "flag": "--mcp-stdio-smoke",
                    "required_extra": "mcp",
                    "provided_extras": sorted(normalized_extras),
                },
            }
        )
    invalid_imports = [
        module_name
        for module_name in (required_extra_imports or [])
        if not _valid_module_import_name(module_name)
    ]
    if invalid_imports:
        errors.append(
            {
                "code": "invalid_required_extra_import",
                "message": "--require-extra-import values must be dotted Python module names.",
                "details": {
                    "field": "require_extra_import",
                    "invalid_values": invalid_imports,
                    "expected": "dotted_module_name",
                },
            }
        )
    return errors


def _valid_module_import_name(module_name: str) -> bool:
    return bool(_MODULE_IMPORT_RE.fullmatch(module_name.strip()))


def _pip_install_command(package_spec: str, *, index_url: str = "", extra_index_urls: Optional[List[str]] = None) -> List[str]:
    cmd = ["python", "-m", "pip", "install"]
    if index_url:
        cmd.extend(["--index-url", index_url])
    for url in extra_index_urls or []:
        if url:
            cmd.extend(["--extra-index-url", url])
    cmd.append(package_spec)
    return cmd


def _planned_checks(
    required_extra_imports: Optional[List[str]] = None,
    *,
    expected_version: str = "",
    mcp_stdio_smoke: bool = False,
) -> List[str]:
    checks = [
        "pip_install",
        "import_citeguard",
    ]
    if expected_version.strip():
        checks.append("version_contract")
    checks.extend(
        [
            "import_console_modules",
            "public_package_files",
            "public_api_contract",
            "distribution_metadata",
            "legacy_src_namespace_absent",
            "entry_points",
        ]
    )
    checks.extend(f"import_{module_name}" for module_name in required_extra_imports or [])
    checks.extend(
        [
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
        ]
    )
    if mcp_stdio_smoke:
        checks.append("mcp_stdio_smoke")
    return checks


def _create_venv(python: str, venv_dir: Path) -> None:
    subprocess.run([python, "-m", "venv", str(venv_dir)], check=True)


def _venv_python(venv_dir: Path) -> Path:
    if sys.platform == "win32":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _console_script(bin_dir: Path, name: str) -> Path:
    if sys.platform == "win32":
        return bin_dir / f"{name}.exe"
    return bin_dir / name


def _record_setup_failure(
    summary: Dict[str, Any],
    name: str,
    cmd: List[str],
    exc: BaseException,
) -> None:
    item = {
        "name": name,
        "status": "failed",
        "command": cmd,
        "message": str(exc),
        "stdout_tail": [],
        "stderr_tail": [],
    }
    if isinstance(exc, subprocess.CalledProcessError):
        item["stdout_tail"] = _tail(exc.stdout or "")
        item["stderr_tail"] = _tail(exc.stderr or "")
    summary["checks"].append(item)
    summary["ok"] = False


def _record_subprocess(summary: Dict[str, Any], name: str, cmd: List[str], *, cwd: Optional[Path] = None) -> None:
    env = dict(os.environ)
    env.setdefault("TOKENIZERS_PARALLELISM", "false")
    env.pop("PYTHONPATH", None)
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except OSError as exc:
        summary["checks"].append(
            {
                "name": name,
                "status": "failed",
                "command": cmd,
                "cwd": str(cwd) if cwd is not None else "",
                "message": str(exc),
                "stdout_tail": [],
                "stderr_tail": [],
            }
        )
        summary["ok"] = False
        return
    item = {
        "name": name,
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": cmd,
        "cwd": str(cwd) if cwd is not None else "",
        "stdout_tail": _tail(completed.stdout),
        "stderr_tail": _tail(completed.stderr),
    }
    summary["checks"].append(item)
    if completed.returncode != 0:
        summary["ok"] = False


def _record_json_command(summary: Dict[str, Any], name: str, cmd: List[str], *, cwd: Optional[Path] = None) -> None:
    try:
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        completed = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except OSError as exc:
        summary["checks"].append(
            {
                "name": name,
                "status": "failed",
                "command": cmd,
                "cwd": str(cwd) if cwd is not None else "",
                "message": str(exc),
                "stdout_tail": [],
                "stderr_tail": [],
            }
        )
        summary["ok"] = False
        return
    item = {
        "name": name,
        "status": "passed" if completed.returncode == 0 else "failed",
        "command": cmd,
        "cwd": str(cwd) if cwd is not None else "",
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


_VERSION_CONTRACT_SMOKE = """
import sys
from importlib.metadata import version

import citeguard
from citeguard.version import __version__

expected = sys.argv[1]
installed = version("citeguard")
assert installed == expected, (installed, expected)
assert __version__ == expected, (__version__, expected)
assert citeguard.__version__ == expected, (citeguard.__version__, expected)
"""

_IMPORT_CONSOLE_MODULES = """
import citeguard.cli
import citeguard.mcp.server
"""


_PUBLIC_PACKAGE_FILES_SMOKE = """
from importlib.metadata import distribution

files = [str(path) for path in (distribution("citeguard").files or [])]
legacy_files = [path for path in files if path == "src/__init__.py" or path.startswith("src/")]
assert not legacy_files, legacy_files
assert any(path == "citeguard/__init__.py" for path in files)
assert any(path == "citeguard/cli.py" for path in files)
assert any(path == "citeguard/mcp/server.py" for path in files)
"""


_PUBLIC_API_CONTRACT_SMOKE = """
import citeguard
from citeguard.errors import ERROR_SCHEMA_VERSION, STABLE_ERROR_CODES

registry = citeguard.error_code_registry()
assert registry["schema_version"] == ERROR_SCHEMA_VERSION
assert set(registry["codes"]) == STABLE_ERROR_CODES
assert registry["codes"]["missing_citation_input"]["next_action"] == "provide_missing_input"
assert "DOI" in registry["codes"]["missing_citation_input"]["recovery"]
assert citeguard.error_payload("timeout", "Timed out")["error"]["next_action"] == "retry_or_check_source_health"
assert callable(citeguard.verify_citation)
assert callable(citeguard.check_claim_support_set)
experimental_exports = {"api", "benchmark", "orchestrator", "planner", "writer"} & set(citeguard.__all__)
assert not experimental_exports, sorted(experimental_exports)
"""


_DISTRIBUTION_METADATA_SMOKE = """
from importlib.metadata import distribution

metadata = distribution("citeguard").metadata
summary = metadata.get("Summary", "")
assert "skeptical citation auditor" in summary, summary
assert "agent writing workflows" in summary, summary
assert "prototype" not in summary.lower(), summary
keywords = {
    item.strip()
    for value in (metadata.get_all("Keywords") or [])
    for item in value.replace(",", " ").split()
    if item.strip()
}
required_keywords = {
    "citation-verification",
    "skeptical-citation-auditor",
    "agent-tools",
    "mcp",
    "scientific-writing",
    "claim-support",
    "research-integrity",
}
assert required_keywords.issubset(keywords), sorted(required_keywords - keywords)
assert "research-agents" not in keywords, keywords
classifiers = set(metadata.get_all("Classifier") or [])
for required in (
    "Intended Audience :: Science/Research",
    "Topic :: Scientific/Engineering :: Artificial Intelligence",
    "Topic :: Scientific/Engineering :: Information Analysis",
    "Topic :: Text Processing :: Linguistic",
    "Typing :: Typed",
):
    assert required in classifiers, required
extras = set(metadata.get_all("Provides-Extra") or [])
assert {"mcp", "models", "api", "pdf"}.issubset(extras), extras
project_urls = metadata.get_all("Project-URL") or []
url_labels = {item.split(",", 1)[0].strip() for item in project_urls if "," in item}
assert {"Homepage", "Repository", "Issues", "Changelog", "Documentation"}.issubset(url_labels), url_labels
license_files = set(metadata.get_all("License-File") or [])
assert "LICENSE" in license_files, license_files
"""


_LEGACY_NAMESPACE_ABSENT_SMOKE = """
import importlib

try:
    importlib.import_module("src")
except ModuleNotFoundError:
    pass
else:
    raise AssertionError("published package must not expose legacy src namespace")
"""


_ENTRY_POINT_SMOKE = """
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
"""


_CLI_HELP_SMOKE = """
import subprocess
import sys

cmd = sys.argv[1:] + ["--help"]
completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
assert completed.returncode == 0, (cmd, completed.returncode, completed.stderr)
stdout = completed.stdout
for expected in (
    "verify",
    "audit",
    "support-audit",
    "extract",
    "cache",
    "status",
):
    assert expected in stdout, (expected, stdout)
assert "citation" in stdout.lower(), stdout
"""


_CLI_FIXTURE_VERIFY_SMOKE = """
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

fixture_records = [
    {
        "citation_id": "published-cli-fixture-attention",
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
        "year": 2017,
        "venue": "NeurIPS",
        "doi": "",
        "arxiv_id": "1706.03762",
        "source": "fixture",
        "abstract": "The Transformer is a model architecture relying entirely on attention mechanisms.",
    }
]

with tempfile.TemporaryDirectory() as tmpdir:
    fixture_path = Path(tmpdir) / "citations.json"
    fixture_path.write_text(json.dumps(fixture_records), encoding="utf-8")
    env = dict(os.environ)
    env.update(
        {
            "CITEGUARD_FIXTURE_CITATIONS": str(fixture_path),
            "CITEGUARD_CACHE": ":memory:",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    cmd = sys.argv[1:] + [
        "verify",
        "--title",
        "Attention Is All You Need",
        "--author",
        "Ashish Vaswani",
        "--year",
        "2017",
        "--arxiv-id",
        "1706.03762",
        "--compact",
    ]
    completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    assert completed.returncode == 0, (cmd, completed.returncode, completed.stdout, completed.stderr)
    payload = json.loads(completed.stdout)
    assert payload["verdict"] == "verified", payload
    assert payload["next_action"] == "keep", payload
    assert payload["canonical_record"]["title"] == "Attention Is All You Need", payload
    assert payload["canonical_record"]["arxiv_id"] == "1706.03762", payload
    assert payload["sources_checked"] == ["metadata_source"], payload
    assert payload["sources_responded"] == ["fixture"], payload
"""


_CLI_FIXTURE_SUPPORT_SMOKE = """
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

fixture_records = [
    {
        "citation_id": "published-cli-fixture-attention",
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
        "year": 2017,
        "venue": "NeurIPS",
        "doi": "",
        "arxiv_id": "1706.03762",
        "source": "fixture",
        "abstract": "The Transformer is a model architecture relying entirely on attention mechanisms.",
    }
]

with tempfile.TemporaryDirectory() as tmpdir:
    fixture_path = Path(tmpdir) / "citations.json"
    fixture_path.write_text(json.dumps(fixture_records), encoding="utf-8")
    env = dict(os.environ)
    env.update(
        {
            "CITEGUARD_FIXTURE_CITATIONS": str(fixture_path),
            "CITEGUARD_CACHE": ":memory:",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )
    cmd = sys.argv[1:] + [
        "support",
        "--claim",
        "The Transformer relies entirely on attention mechanisms.",
        "--title",
        "Attention Is All You Need",
        "--author",
        "Ashish Vaswani",
        "--year",
        "2017",
        "--arxiv-id",
        "1706.03762",
        "--compact",
    ]
    completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    assert completed.returncode == 0, (cmd, completed.returncode, completed.stdout, completed.stderr)
    payload = json.loads(completed.stdout)
    assert payload["verdict"] in {"supported", "weakly_supported"}, payload
    assert payload["next_action"] in {"keep_claim", "tighten_claim_or_inspect_full_text"}, payload
    assert payload["resolution"]["verdict"] == "matched", payload
    assert payload["resolution"]["sources_checked"] == ["metadata_source"], payload
    assert payload["resolution"]["sources_responded"] == ["fixture"], payload
    assert payload["evidence_scope"] == "abstract", payload
    assert payload["evidence"]["source_name"] == "fixture", payload
    assert payload["evidence"]["source_field"].startswith("abstract"), payload
    assert "attention mechanisms" in payload["evidence"]["text"].lower(), payload
"""


_CLI_FIXTURE_BATCH_SMOKE = """
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

fixture_records = [
    {
        "citation_id": "published-cli-fixture-attention",
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
        "year": 2017,
        "venue": "NeurIPS",
        "doi": "",
        "arxiv_id": "1706.03762",
        "source": "fixture",
        "abstract": "The Transformer is a model architecture relying entirely on attention mechanisms.",
    }
]


def write_jsonl(path, rows):
    path.write_text("\\n".join(json.dumps(row) for row in rows) + "\\n", encoding="utf-8")


def run_json(cmd, env):
    completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    assert completed.returncode == 0, (cmd, completed.returncode, completed.stdout, completed.stderr)
    return json.loads(completed.stdout)


with tempfile.TemporaryDirectory() as tmpdir:
    base = Path(tmpdir)
    fixture_path = base / "citations.json"
    fixture_path.write_text(json.dumps(fixture_records), encoding="utf-8")
    citations_jsonl = base / "citations.jsonl"
    write_jsonl(
        citations_jsonl,
        [
            {
                "title": "Attention Is All You Need",
                "authors": ["Ashish Vaswani"],
                "year": 2017,
                "arxiv_id": "1706.03762",
            },
            {
                "title": "Definitely Missing Citation",
            },
        ],
    )
    claim_citations_jsonl = base / "claim_citations.jsonl"
    write_jsonl(
        claim_citations_jsonl,
        [
            {
                "claim": "The Transformer relies entirely on attention mechanisms.",
                "title": "Attention Is All You Need",
                "authors": ["Ashish Vaswani"],
                "year": 2017,
                "arxiv_id": "1706.03762",
            },
            {
                "claim": "A missing citation supports this claim.",
                "title": "Definitely Missing Citation",
            },
        ],
    )
    env = dict(os.environ)
    env.update(
        {
            "CITEGUARD_FIXTURE_CITATIONS": str(fixture_path),
            "CITEGUARD_CACHE": ":memory:",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )

    audit = run_json(
        sys.argv[1:] + ["audit", str(citations_jsonl), "--high-risk-only", "--compact"],
        env,
    )
    assert audit["summary"]["verified"] == 1, audit
    assert audit["summary"]["not_found"] == 1, audit
    assert audit["filtered"]["returned_indexes"] == [1], audit
    assert audit["filtered"]["omitted_indexes"] == [0], audit
    assert audit["review_summary"]["top_high_risk_indexes"] == [1], audit
    assert audit["review_summary"]["recommended_next_steps"]["first_queue"] == "identity_resolution_indexes", audit
    assert len(audit["results"]) == 1, audit
    assert audit["results"][0]["verdict"] == "not_found", audit
    assert audit["risk_ranking"][0]["risk_reason"] == "no_strong_match", audit
    assert audit["risk_ranking"][0]["suggested_fix"]["requires_user_confirmation"] is True, audit

    support_audit = run_json(
        sys.argv[1:] + ["support-audit", str(claim_citations_jsonl), "--high-risk-only", "--compact"],
        env,
    )
    assert support_audit["summary"]["insufficient_evidence"] == 1, support_audit
    assert support_audit["summary"].get("supported", 0) + support_audit["summary"].get("weakly_supported", 0) >= 1, support_audit
    assert support_audit["filtered"]["returned_indexes"] == [1], support_audit
    assert support_audit["filtered"]["omitted_indexes"] == [0], support_audit
    assert support_audit["review_summary"]["top_high_risk_indexes"] == [1], support_audit
    assert support_audit["review_summary"]["recommended_next_steps"]["first_queue"] == "identity_resolution_indexes", support_audit
    assert len(support_audit["results"]) == 1, support_audit
    assert support_audit["results"][0]["verdict"] == "insufficient_evidence", support_audit
    assert support_audit["results"][0]["resolution"]["verdict"] == "not_found", support_audit
    assert support_audit["risk_ranking"][0]["risk_reason"] == "citation_identity_unresolved", support_audit
    assert support_audit["risk_ranking"][0]["suggested_fix"]["requires_user_confirmation"] is True, support_audit
"""


_CLI_FIXTURE_EXTRACT_SMOKE = """
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

fixture_records = [
    {
        "citation_id": "published-cli-fixture-attention",
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
        "year": 2017,
        "venue": "NeurIPS",
        "doi": "",
        "arxiv_id": "1706.03762",
        "source": "fixture",
        "abstract": "The Transformer is a model architecture relying entirely on attention mechanisms.",
    }
]


def run_json(cmd, env):
    completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    assert completed.returncode == 0, (cmd, completed.returncode, completed.stdout, completed.stderr)
    return json.loads(completed.stdout)


with tempfile.TemporaryDirectory() as tmpdir:
    base = Path(tmpdir)
    fixture_path = base / "citations.json"
    fixture_path.write_text(json.dumps(fixture_records), encoding="utf-8")
    references_md = base / "references.md"
    references_md.write_text(
        "# References\\n\\n"
        "- Vaswani, Ashish, Noam Shazeer, Niki Parmar. Attention Is All You Need. "
        "NeurIPS, 2017. arXiv:1706.03762.\\n"
        "- Example, Ada. Citation Auditing with Metadata Checks. CiteGuard Fixtures, 2026.\\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env.update(
        {
            "CITEGUARD_FIXTURE_CITATIONS": str(fixture_path),
            "CITEGUARD_CACHE": ":memory:",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )

    extracted = run_json(sys.argv[1:] + ["extract", str(references_md), "--compact"], env)
    assert len(extracted) == 2, extracted
    assert extracted[0]["source_format"] == "markdown", extracted
    assert extracted[0]["source_index"] == 1, extracted
    assert extracted[0]["source_line_start"] == 3, extracted
    assert extracted[0]["source_line_end"] == 3, extracted
    assert extracted[0]["source_locator"].endswith("references.md#citation-1"), extracted
    assert extracted[0]["arxiv_id"] == "1706.03762", extracted
    assert extracted[1]["source_index"] == 2, extracted
    assert extracted[1]["source_line_start"] == 4, extracted
    assert extracted[1]["source_locator"].endswith("references.md#citation-2"), extracted

    audit = run_json(
        sys.argv[1:] + ["audit", str(references_md), "--high-risk-only", "--compact"],
        env,
    )
    assert audit["summary"]["verified"] == 1, audit
    assert audit["summary"]["not_found"] == 1, audit
    assert audit["filtered"]["returned_indexes"] == [1], audit
    assert audit["review_summary"]["source_traceability"]["has_source_backed_items"] is True, audit
    assert audit["review_summary"]["source_traceability"]["high_risk_source_indexes"] == [2], audit
    assert audit["review_summary"]["source_traceability"]["review_required_source_indexes"] == [2], audit
    assert audit["results"][0]["input"]["metadata"]["input_source_line_start"] == 4, audit
    assert audit["results"][0]["input"]["metadata"]["input_source_locator"].endswith("references.md#citation-2"), audit
    assert audit["risk_ranking"][0]["input_source_line_start"] == 4, audit
    assert audit["risk_ranking"][0]["input_source_locator"].endswith("references.md#citation-2"), audit
"""


_CLI_ERROR_CONTRACT_SMOKE = """
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def run_expect_error(cmd, env):
    completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    assert completed.returncode == 2, (cmd, completed.returncode, completed.stdout, completed.stderr)
    assert completed.stdout == "", (cmd, completed.stdout)
    payload = json.loads(completed.stderr)
    assert payload["ok"] is False, payload
    assert payload["schema_version"] == 1, payload
    assert payload["exit_code"] == 2, payload
    return payload


with tempfile.TemporaryDirectory() as tmpdir:
    base = Path(tmpdir)
    env = dict(os.environ)
    env.update(
        {
            "CITEGUARD_CACHE": ":memory:",
            "TOKENIZERS_PARALLELISM": "false",
        }
    )

    missing_input = run_expect_error(sys.argv[1:] + ["verify", "--compact"], env)
    error = missing_input["error"]
    assert error["code"] == "missing_citation_input", missing_input
    assert error["details"]["command"] == "verify", missing_input
    assert error["next_action"] == "provide_missing_input", missing_input
    assert error["retryable"] is False, missing_input
    assert error["category"] == "missing_input", missing_input

    bad_jsonl = base / "bad.jsonl"
    bad_jsonl.write_text("{bad json}\\n", encoding="utf-8")
    invalid_json = run_expect_error(sys.argv[1:] + ["support-audit", str(bad_jsonl), "--compact"], env)
    error = invalid_json["error"]
    assert error["code"] == "invalid_json", invalid_json
    assert error["details"]["command"] == "support-audit", invalid_json
    assert error["details"]["line"] == 1, invalid_json
    assert error["details"]["column"] == 2, invalid_json
    assert error["next_action"] == "repair_input", invalid_json
    assert error["retryable"] is False, invalid_json
    assert error["category"] == "input_repair", invalid_json
"""


_PUBLISHED_MCP_STDIO_SMOKE = r"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


FIXTURE_RECORDS = [
    {
        "citation_id": "published-fixture-attention",
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
        "year": 2017,
        "venue": "NeurIPS",
        "doi": "",
        "arxiv_id": "1706.03762",
        "source": "fixture",
        "abstract": "The Transformer is a model architecture relying entirely on attention mechanisms.",
    },
    {
        "citation_id": "published-fixture-auditing",
        "title": "Citation Auditing with Metadata Checks",
        "authors": ["Ada Example"],
        "year": 2026,
        "venue": "CiteGuard Fixtures",
        "doi": "",
        "arxiv_id": "",
        "source": "fixture",
        "abstract": "Citation auditing checks metadata and evidence before accepting references.",
    }
]


def coerce_tool_payload(result):
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    content = getattr(result, "content", None)
    if isinstance(content, list):
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
    raise RuntimeError(f"Could not decode MCP result: {result!r}")


def require_support_mode_details(payload):
    details = payload.get("support_mode_details")
    if not isinstance(details, dict):
        raise RuntimeError(f"Expected support_mode_details: {payload!r}")
    if details.get("schema_version") != 1:
        raise RuntimeError(f"Expected support_mode_details.schema_version=1: {payload!r}")
    if not isinstance(details.get("decision"), str) or not details.get("decision"):
        raise RuntimeError(f"Expected support_mode_details.decision: {payload!r}")
    policy = str(details.get("policy", ""))
    for required in (
        "contradictions_dominate",
        "multiple_weak_citations_remain_tentative",
        "no_unstated_multi_hop_or_full_text_support",
    ):
        if required not in policy:
            raise RuntimeError(f"Expected support_mode_details.policy to include {required!r}: {payload!r}")
    for key in (
        "supported_indexes",
        "weakly_supported_indexes",
        "contradicted_indexes",
        "insufficient_evidence_indexes",
    ):
        if not isinstance(details.get(key), list):
            raise RuntimeError(f"Expected support_mode_details.{key} list: {payload!r}")
    if not isinstance(details.get("full_text_evidence_present"), bool):
        raise RuntimeError(f"Expected support_mode_details.full_text_evidence_present bool: {payload!r}")


async def main():
    command = sys.argv[1]
    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_path = Path(tmpdir) / "citations.json"
        fixture_path.write_text(json.dumps(FIXTURE_RECORDS), encoding="utf-8")
        env = dict(os.environ)
        env.update(
            {
                "CITEGUARD_FIXTURE_CITATIONS": str(fixture_path),
                "CITEGUARD_CACHE": ":memory:",
                "TOKENIZERS_PARALLELISM": "false",
            }
        )
        params = StdioServerParameters(command=command, args=[], env=env)
        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                tool_names = {tool.name for tool in tools_result.tools}
                required_tools = {
                    "citeguard_status_tool",
                    "verify_citation_tool",
                    "check_claim_support_tool",
                    "check_claim_support_set_tool",
                }
                missing = sorted(required_tools - tool_names)
                if missing:
                    raise RuntimeError(f"Missing published MCP tools: {missing}")

                status = coerce_tool_payload(await session.call_tool("citeguard_status_tool", {}))
                if status.get("service") != "CiteGuard":
                    raise RuntimeError(f"Unexpected status payload: {status!r}")
                if status.get("fixture_citations_path") != str(fixture_path):
                    raise RuntimeError(f"Status did not report fixture path: {status!r}")
                source_health = status.get("source_health", {})
                if source_health.get("mode") != "fixture":
                    raise RuntimeError(f"Expected fixture source health: {status!r}")

                verify = coerce_tool_payload(
                    await session.call_tool(
                        "verify_citation_tool",
                        {
                            "title": "Attention Is All You Need",
                            "authors": ["Ashish Vaswani"],
                            "year": 2017,
                            "arxiv_id": "1706.03762",
                        },
                    )
                )
                if verify.get("verdict") != "verified" or verify.get("next_action") != "keep":
                    raise RuntimeError(f"Expected verified fixture result: {verify!r}")

                support_set = coerce_tool_payload(
                    await session.call_tool(
                        "check_claim_support_set_tool",
                        {
                            "claim": "The Transformer relies entirely on attention mechanisms.",
                            "citations": [
                                {
                                    "title": "Attention Is All You Need",
                                    "arxiv_id": "1706.03762",
                                },
                                {
                                    "title": "Citation Auditing with Metadata Checks",
                                },
                            ],
                        },
                    )
                )
                if support_set.get("support_mode") in {"", None}:
                    raise RuntimeError(f"Expected support_set.support_mode: {support_set!r}")
                results = support_set.get("results")
                if not isinstance(results, list) or len(results) != 2:
                    raise RuntimeError(f"Expected two support-set child results: {support_set!r}")
                require_support_mode_details(support_set)

                missing_input = coerce_tool_payload(await session.call_tool("verify_citation_tool", {}))
                error = missing_input.get("error", {})
                if missing_input.get("ok") is not False or error.get("code") != "missing_citation_input":
                    raise RuntimeError(f"Expected structured missing-input error: {missing_input!r}")


asyncio.run(main())
"""


if __name__ == "__main__":
    raise SystemExit(main())
