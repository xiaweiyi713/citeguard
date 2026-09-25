#!/usr/bin/env python3
"""Generate a deterministic CycloneDX SBOM from CiteGuard's declared metadata."""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


SBOM_SCHEMA_VERSION = 1
_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


class SbomError(ValueError):
    """Raised when the project metadata cannot form a trustworthy SBOM."""


def build_sbom(project_root: Path, *, include_dev: bool = False) -> Dict[str, Any]:
    """Build a deterministic CycloneDX 1.5 document from declared dependencies."""

    project_root = project_root.resolve()
    project = _project_metadata(project_root)
    package_name = str(project.get("name", "")).strip()
    if not package_name:
        raise SbomError("pyproject.toml project.name is required")
    version = _version_from_source(project_root / "citeguard" / "version.py")
    root_component = _component(package_name, version, component_type="application")

    grouped_requirements: Dict[str, List[str]] = {"runtime": _string_list(project.get("dependencies", []))}
    optional = project.get("optional-dependencies", {})
    if not isinstance(optional, dict):
        raise SbomError("pyproject.toml optional-dependencies must be an object")
    for group, requirements in sorted(optional.items()):
        if group == "dev" and not include_dev:
            continue
        grouped_requirements[f"optional:{group}"] = _string_list(requirements)

    dependencies = _dependency_components(grouped_requirements)
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "component": root_component,
            "properties": [
                {"name": "citeguard:sbom_schema_version", "value": str(SBOM_SCHEMA_VERSION)},
                {"name": "citeguard:dependency_source", "value": "pyproject_declared_dependencies"},
                {"name": "citeguard:include_dev", "value": str(bool(include_dev)).lower()},
            ],
        },
        "components": dependencies,
        "dependencies": [
            {
                "ref": root_component["bom-ref"],
                "dependsOn": [component["bom-ref"] for component in dependencies],
            }
        ],
    }


def write_sbom(sbom: Dict[str, Any], output: str = "") -> str:
    """Write one deterministic JSON document to a file or stdout."""

    serialized = json.dumps(sbom, indent=2, sort_keys=True) + "\n"
    if output:
        Path(output).write_text(serialized, encoding="utf-8")
        return output
    sys.stdout.write(serialized)
    return ""


def _project_metadata(project_root: Path) -> Dict[str, Any]:
    try:
        from setuptools.config.pyprojecttoml import read_configuration
    except ImportError as exc:
        raise SbomError("setuptools>=68 is required to read pyproject.toml") from exc
    try:
        configuration = read_configuration(str(project_root / "pyproject.toml"), expand=False)
    except Exception as exc:
        raise SbomError(f"could not read pyproject.toml: {exc}") from exc
    project = configuration.get("project")
    if not isinstance(project, dict):
        raise SbomError("pyproject.toml must contain a project table")
    return project


def _version_from_source(path: Path) -> str:
    try:
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except OSError as exc:
        raise SbomError(f"could not read version source: {exc}") from exc
    except SyntaxError as exc:
        raise SbomError(f"could not parse version source: {exc}") from exc
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(isinstance(target, ast.Name) and target.id == "__version__" for target in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    raise SbomError("citeguard/version.py must assign a string __version__")


def _string_list(value: Any) -> List[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise SbomError("dependency declarations must be lists of strings")
    return list(value)


def _dependency_components(grouped_requirements: Dict[str, Iterable[str]]) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {}
    for group, requirements in grouped_requirements.items():
        for requirement in requirements:
            match = _REQUIREMENT_NAME.match(requirement)
            if not match:
                raise SbomError(f"could not parse dependency name from {requirement!r}")
            name = _canonical_name(match.group(1))
            entry = merged.setdefault(name, {"requirements": [], "groups": []})
            if requirement not in entry["requirements"]:
                entry["requirements"].append(requirement)
            if group not in entry["groups"]:
                entry["groups"].append(group)

    components = []
    for name in sorted(merged):
        entry = merged[name]
        properties = [
            {"name": "citeguard:declared_requirement", "value": requirement}
            for requirement in sorted(entry["requirements"])
        ]
        properties.extend(
            {"name": "citeguard:dependency_group", "value": group} for group in sorted(entry["groups"])
        )
        components.append(
            {
                **_component(name, "unresolved", component_type="library", include_version_in_purl=False),
                "properties": properties,
            }
        )
    return components


def _component(
    name: str,
    version: str,
    *,
    component_type: str,
    include_version_in_purl: bool = True,
) -> Dict[str, str]:
    canonical = _canonical_name(name)
    purl = f"pkg:pypi/{canonical}"
    if include_version_in_purl:
        purl += f"@{version}"
    return {
        "type": component_type,
        "name": canonical,
        "version": version,
        "purl": purl,
        "bom-ref": purl,
    }


def _canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a deterministic CycloneDX SBOM from pyproject.toml.")
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--output", default="", help="Optional SBOM JSON destination; stdout when omitted.")
    parser.add_argument("--include-dev", action="store_true", help="Include the optional development dependency group.")
    args = parser.parse_args(argv)
    try:
        sbom = build_sbom(Path(args.project_root), include_dev=args.include_dev)
        write_sbom(sbom, output=args.output)
        return 0
    except SbomError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
