#!/usr/bin/env python3
"""Capture one timestamped, region-labelled observation of real scholarly sources."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.benchmark.experiments import write_experiment_artifacts
from citeguard.benchmark.live_retrieval import (
    LIVE_RETRIEVAL_BENCHMARK_SCHEMA_VERSION,
    LIVE_RETRIEVAL_SOURCE_NAMES,
    LiveRetrievalBenchmarkError,
    audit_live_retrieval_collection,
    load_live_retrieval_cases,
    observe_live_retrieval,
)
from citeguard.retrieval.scholarly_clients.factory import build_live_metadata_source


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


def _parse_source_versions(values: List[str]) -> Dict[str, Dict[str, str]]:
    versions: Dict[str, Dict[str, str]] = {}
    for value in values:
        source, separator, version = value.partition("=")
        source = source.strip()
        version = version.strip()
        if not separator or source not in LIVE_RETRIEVAL_SOURCE_NAMES or not version:
            raise LiveRetrievalBenchmarkError("--source-api-version must use SOURCE=VERSION for a configured source")
        versions[source] = {"source_api_version": version}
    return versions


def _build_sources(args, names: List[str]):
    sources = {}
    for name in names:
        sources[name] = build_live_metadata_source(
            [name],
            mailto=args.mailto,
            semantic_scholar_api_key=args.semantic_scholar_api_key,
            http_timeout=args.http_timeout,
            http_retries=args.http_retries,
            http_retry_backoff=args.http_retry_backoff,
            http_min_interval=args.http_min_interval,
            harvest_remote_evidence=False,
            source_budget=args.source_budget,
        )
    return sources


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Observe known real citations against live scholarly sources without creating permanent source rankings."
    )
    parser.add_argument("--dataset", default="data/eval/live_retrieval_benchmark.json")
    parser.add_argument("--campaign", default="data/eval/live_retrieval_benchmark_campaign.json")
    parser.add_argument("--source", action="append", choices=list(LIVE_RETRIEVAL_SOURCE_NAMES))
    parser.add_argument("--observer-region", help="Operator-supplied region label, for example CN-Shanghai or us-east-1.")
    parser.add_argument("--source-api-version", action="append", default=[], metavar="SOURCE=VERSION")
    parser.add_argument("--mailto", default=os.environ.get("CITEGUARD_MAILTO", ""))
    parser.add_argument("--semantic-scholar-api-key", default=os.environ.get("SEMANTIC_SCHOLAR_API_KEY", ""))
    parser.add_argument("--http-timeout", type=int, default=10)
    parser.add_argument("--http-retries", type=int, default=1)
    parser.add_argument("--http-retry-backoff", type=float, default=0.2)
    parser.add_argument("--http-min-interval", type=float, default=0.0)
    parser.add_argument("--source-budget", type=float, default=8.0)
    parser.add_argument("--output-dir", help="Required for a live observation so result/config/manifest artifacts are archived.")
    parser.add_argument("--run-id", help="Optional stable artifact directory name.")
    parser.add_argument("--fail-on-source-limited", action="store_true")
    parser.add_argument("--strict", action="store_true", help="Require a ready collection and no source-limited attempts.")
    args = parser.parse_args(argv)

    try:
        dataset = _load_json(args.dataset)
        campaign = _load_json(args.campaign)
        collection = audit_live_retrieval_collection(dataset, campaign)
        cases = load_live_retrieval_cases(dataset, campaign)
        if not cases:
            print(json.dumps({"collection": collection, "observation": None}, ensure_ascii=False, indent=2))
            return 1 if args.strict else 0
        if not args.observer_region:
            raise LiveRetrievalBenchmarkError("--observer-region is required once the collection contains real cases")
        if not args.output_dir:
            raise LiveRetrievalBenchmarkError("--output-dir is required to archive a live observation")
        names = args.source or list(LIVE_RETRIEVAL_SOURCE_NAMES)
        if any(name in {"openalex", "crossref"} for name in names) and not str(args.mailto).strip():
            raise LiveRetrievalBenchmarkError("OpenAlex/Crossref observation requires --mailto for polite API access")
        observation = observe_live_retrieval(
            cases,
            _build_sources(args, names),
            observer_region=args.observer_region,
            source_versions=_parse_source_versions(args.source_api_version),
        )
    except LiveRetrievalBenchmarkError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    result = {
        "schema_version": LIVE_RETRIEVAL_BENCHMARK_SCHEMA_VERSION,
        "collection": collection,
        "observation": observation,
        "benchmark_claim_safe": False,
        "policy": "one observation is not a permanent source ranking or a fabrication decision",
    }
    config = {
        "script": "scripts/observe_live_retrieval_benchmark.py",
        "dataset": args.dataset,
        "campaign": args.campaign,
        "sources": names,
        "observer_region": args.observer_region,
        "source_api_versions": _parse_source_versions(args.source_api_version),
        "http": {
            "timeout": args.http_timeout,
            "retries": args.http_retries,
            "retry_backoff": args.http_retry_backoff,
            "min_interval": args.http_min_interval,
            "source_budget": args.source_budget,
            "mailto_configured": bool(args.mailto),
            "semantic_scholar_api_key_configured": bool(args.semantic_scholar_api_key),
        },
    }
    result["experiment_artifact"] = write_experiment_artifacts(
        "live_retrieval_observation",
        result,
        config,
        output_dir=args.output_dir,
        run_id=args.run_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    source_limited = int(observation["summary"]["source_limited_count"]) > 0
    return 1 if args.strict and (collection["status"] != "ready" or source_limited) else int(
        bool(args.fail_on_source_limited and source_limited)
    )


if __name__ == "__main__":
    raise SystemExit(main())
