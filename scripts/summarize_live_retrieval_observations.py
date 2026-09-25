#!/usr/bin/env python3
"""Aggregate archived live-retrieval observations without issuing live requests."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.benchmark.experiments import write_experiment_artifacts
from citeguard.benchmark.live_retrieval import (
    LIVE_RETRIEVAL_OBSERVATION_EXPERIMENT_NAME,
    LiveRetrievalBenchmarkError,
    audit_live_retrieval_observations,
    load_live_retrieval_observation_artifact,
)


def _load_json(path: str) -> Dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise LiveRetrievalBenchmarkError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LiveRetrievalBenchmarkError(f"invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise LiveRetrievalBenchmarkError(f"{path} must contain a JSON object")
    return payload


def _artifact_paths(artifact_dirs: Iterable[str], artifact_roots: Iterable[str]) -> List[str]:
    paths = {str(Path(path).expanduser()) for path in artifact_dirs if str(path).strip()}
    for root_value in artifact_roots:
        root = Path(root_value).expanduser()
        if not root.exists() or not root.is_dir():
            raise LiveRetrievalBenchmarkError(f"--artifact-root must be an existing directory: {root}")
        for manifest_path in root.rglob("manifest.json"):
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(manifest, dict) and manifest.get("experiment_name") == LIVE_RETRIEVAL_OBSERVATION_EXPERIMENT_NAME:
                paths.add(str(manifest_path.parent))
    return sorted(paths)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize archived live-source observations without contacting scholarly APIs."
    )
    parser.add_argument("--dataset", default="data/eval/live_retrieval_benchmark.json")
    parser.add_argument("--campaign", default="data/eval/live_retrieval_benchmark_campaign.json")
    parser.add_argument(
        "--artifact-dir",
        action="append",
        default=[],
        help="Observation run directory (or its result/config/manifest file). Repeat for multiple observations.",
    )
    parser.add_argument(
        "--artifact-root",
        action="append",
        default=[],
        help="Recursively discover only live_retrieval_observation artifacts below this directory.",
    )
    parser.add_argument("--output-dir", help="Optional directory for the aggregate result/config/manifest artifact.")
    parser.add_argument("--run-id", help="Optional stable aggregate artifact directory name.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero until collection and observation coverage are ready.")
    args = parser.parse_args(argv)

    try:
        artifact_paths = _artifact_paths(args.artifact_dir, args.artifact_root)
        artifacts = []
        for artifact_path in artifact_paths:
            try:
                artifacts.append(load_live_retrieval_observation_artifact(artifact_path))
            except LiveRetrievalBenchmarkError as exc:
                artifacts.append({"artifact_path": artifact_path, "load_error": str(exc)})
        report = audit_live_retrieval_observations(
            _load_json(args.dataset),
            _load_json(args.campaign),
            artifacts,
        )
    except LiveRetrievalBenchmarkError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    if args.output_dir:
        result = dict(report)
        result["experiment_artifact"] = write_experiment_artifacts(
            "live_retrieval_observation_summary",
            result,
            {
                "script": "scripts/summarize_live_retrieval_observations.py",
                "dataset": args.dataset,
                "campaign": args.campaign,
                "artifact_paths": artifact_paths,
                "artifact_roots": list(args.artifact_root),
            },
            output_dir=args.output_dir,
            run_id=args.run_id,
        )
        report = result
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ready" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
