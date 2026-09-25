#!/usr/bin/env python3
"""Run deterministic snapshot or timestamped live retrieval-source ablations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Dict, List, Optional

from _bootstrap import ensure_project_root

ensure_project_root()

from citeguard.benchmark.experiments import write_experiment_artifacts
from citeguard.benchmark.retrieval_ablations import (
    RETRIEVAL_ABLATION_SOURCE_NAMES,
    build_offline_snapshot_sources,
    load_retrieval_ablation_dataset,
    run_retrieval_source_ablation,
)
from citeguard.retrieval.scholarly_clients import MetadataSource
from citeguard.retrieval.scholarly_clients.factory import build_live_metadata_source


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare retrieval adapters using deterministic snapshots or an explicitly live observation."
    )
    parser.add_argument("--dataset", default="data/eval/retrieval_source_eval.json")
    parser.add_argument("--mode", choices=["offline_snapshot", "live"], default="offline_snapshot")
    parser.add_argument(
        "--source",
        action="append",
        choices=list(RETRIEVAL_ABLATION_SOURCE_NAMES),
        help="Source row to run; repeat for multiple. Defaults to all six rows.",
    )
    parser.add_argument("--mailto", default=os.environ.get("CITEGUARD_MAILTO", ""))
    parser.add_argument("--semantic-scholar-api-key", default=os.environ.get("SEMANTIC_SCHOLAR_API_KEY", ""))
    parser.add_argument("--http-timeout", type=int, default=10)
    parser.add_argument("--http-retries", type=int, default=1)
    parser.add_argument("--http-retry-backoff", type=float, default=0.2)
    parser.add_argument("--http-min-interval", type=float, default=0.0)
    parser.add_argument("--source-budget", type=float, default=8.0)
    parser.add_argument(
        "--fail-on-source-limited",
        action="store_true",
        help="Exit non-zero if any requested source is unavailable, timed out, or otherwise source-limited.",
    )
    parser.add_argument("--output-dir", help="Optional directory for standardized experiment artifacts.")
    parser.add_argument("--run-id", help="Optional stable run id for the experiment artifact folder.")
    args = parser.parse_args(argv)

    requested = args.source or list(RETRIEVAL_ABLATION_SOURCE_NAMES)
    polite_contact_required = any(
        name in {"openalex", "crossref", "multi_source"}
        for name in requested
    )
    if args.mode == "live" and polite_contact_required and not str(args.mailto).strip():
        parser.error("--mode live with OpenAlex/Crossref requires --mailto for polite API access")

    dataset = load_retrieval_ablation_dataset(args.dataset)
    names = requested
    sources = (
        build_offline_snapshot_sources(dataset)
        if args.mode == "offline_snapshot"
        else _build_live_sources(names, dataset, args)
    )
    result = run_retrieval_source_ablation(dataset, sources, names, mode=args.mode)
    result.update(
        {
            "dataset": args.dataset,
            "case_count": len(dataset.cases),
            "record_count": len(dataset.records),
        }
    )
    config = {
        "script": "scripts/run_retrieval_ablations.py",
        "dataset": args.dataset,
        "mode": args.mode,
        "sources": names,
        "http": {
            "timeout": args.http_timeout,
            "retries": args.http_retries,
            "retry_backoff": args.http_retry_backoff,
            "min_interval": args.http_min_interval,
            "source_budget": args.source_budget,
            "mailto_configured": bool(args.mailto),
            "semantic_scholar_api_key_configured": bool(args.semantic_scholar_api_key),
        },
        "case_count": len(dataset.cases),
        "record_count": len(dataset.records),
    }
    if args.output_dir:
        result["experiment_artifact"] = write_experiment_artifacts(
            "retrieval_source_ablation",
            result,
            config,
            output_dir=args.output_dir,
            run_id=args.run_id,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    limited = bool(result["source_limited_sources"] or result["unavailable_sources"])
    return 1 if args.fail_on_source_limited and limited else 0


def _build_live_sources(names, dataset, args) -> Dict[str, MetadataSource]:
    snapshot_sources = build_offline_snapshot_sources(dataset)
    sources: Dict[str, MetadataSource] = {}
    for name in names:
        if name == "in_memory":
            sources[name] = snapshot_sources[name]
            continue
        members = list(dataset.multi_source_members) if name == "multi_source" else [name]
        sources[name] = build_live_metadata_source(
            members,
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


if __name__ == "__main__":
    sys.exit(main())
