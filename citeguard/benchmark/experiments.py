"""Helpers for writing reproducible benchmark experiment artifacts."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


EXPERIMENT_ARTIFACT_SCHEMA_VERSION = 1


def write_experiment_artifacts(
    experiment_name: str,
    result: Dict[str, Any],
    config: Dict[str, Any],
    output_dir: str = "experiments",
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write a result, config snapshot, and manifest under a versioned run folder."""

    clean_name = _slug(experiment_name) or "experiment"
    clean_run_id = _slug(run_id or _timestamp_run_id())
    run_path = Path(output_dir) / clean_run_id
    run_path.mkdir(parents=True, exist_ok=True)

    result_path = run_path / "result.json"
    config_path = run_path / "config.json"
    manifest_path = run_path / "manifest.json"
    _write_json(result_path, result)
    _write_json(config_path, config)

    manifest = {
        "schema_version": EXPERIMENT_ARTIFACT_SCHEMA_VERSION,
        "experiment_name": clean_name,
        "run_id": clean_run_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": {
            "result": result_path.name,
            "config": config_path.name,
            "manifest": manifest_path.name,
        },
        "result_summary": _result_summary(result),
    }
    _write_json(manifest_path, manifest)
    return {
        "schema_version": EXPERIMENT_ARTIFACT_SCHEMA_VERSION,
        "experiment_name": clean_name,
        "run_id": clean_run_id,
        "path": str(run_path),
        "files": {
            "result": str(result_path),
            "config": str(config_path),
            "manifest": str(manifest_path),
        },
    }


def _timestamp_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-._")
    return slug[:120]


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def _result_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    if "overall" in result and isinstance(result["overall"], dict):
        summary = dict(result["overall"])
    else:
        summary = {key: value for key, value in result.items() if isinstance(value, (int, float, str, bool))}
    if "quality_gate" in result and isinstance(result["quality_gate"], dict):
        summary["quality_gate_ok"] = bool(result["quality_gate"].get("ok"))
    return summary
