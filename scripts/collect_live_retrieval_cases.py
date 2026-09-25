#!/usr/bin/env python3
"""Curate real public-metadata cases for the live retrieval benchmark."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Optional

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.benchmark.live_case_collection import (
    LiveCaseCollectionError,
    LiveCaseRequest,
    collect_live_retrieval_dataset,
    load_collection_requests,
    merge_collected_cases,
)
from citeguard.retrieval.scholarly_clients.factory import build_live_metadata_source


SOURCE_NAMES = ("openalex", "crossref", "arxiv", "semantic_scholar")


def _load_json(path: str) -> Dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise LiveCaseCollectionError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LiveCaseCollectionError(f"invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise LiveCaseCollectionError(f"{path} must contain a JSON object")
    return payload


def _request_manifest_from_args(args: argparse.Namespace) -> Dict[str, Any]:
    if args.requests:
        return _load_json(args.requests)
    rows: List[Dict[str, Any]] = []
    for index, value in enumerate(args.doi, start=1):
        rows.append(
            {
                "id": f"doi-{index:03d}",
                "query_kind": "doi",
                "query": value,
                "lang": args.lang,
                "domain": args.domain,
                "rights_basis": args.rights_basis,
                "source": "crossref",
            }
        )
    for index, value in enumerate(args.arxiv_id, start=1):
        rows.append(
            {
                "id": f"arxiv-{index:03d}",
                "query_kind": "arxiv_id",
                "query": value,
                "lang": args.lang,
                "domain": args.domain,
                "rights_basis": "public_metadata",
                "source": "arxiv",
            }
        )
    for index, value in enumerate(args.title, start=1):
        rows.append(
            {
                "id": f"title-{index:03d}",
                "query_kind": "title",
                "query": value,
                "lang": args.lang,
                "domain": args.domain,
                "rights_basis": args.rights_basis,
                "source": args.title_source,
            }
        )
    if not rows:
        raise LiveCaseCollectionError("provide --requests or at least one of --doi, --arxiv-id, and --title")
    return {"requests": rows}


def _source_names(requests: Iterable[LiveCaseRequest], explicit: List[str]) -> List[str]:
    names = {str(name).strip().lower() for name in explicit if str(name).strip()}
    for request in requests:
        if request.source:
            names.add(request.source)
        elif request.query_kind == "doi":
            names.add("crossref")
        elif request.query_kind == "arxiv_id":
            names.add("arxiv")
        else:
            names.add("openalex")
    invalid = sorted(names - set(SOURCE_NAMES))
    if invalid:
        raise LiveCaseCollectionError("unsupported source name(s): " + ", ".join(invalid))
    return sorted(names)


def _build_sources(args: argparse.Namespace, names: List[str]):
    if any(name in {"openalex", "crossref"} for name in names) and not str(args.mailto).strip():
        raise LiveCaseCollectionError(
            "OpenAlex/Crossref curation requires --mailto; use an operator-controlled contact address"
        )
    return {
        name: build_live_metadata_source(
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
        for name in names
    }


def _write_json(path: str, payload: Dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Curate known real scholarly records using public metadata. "
            "Rejected or ambiguous search results are retained in the report, never promoted to benchmark cases."
        )
    )
    parser.add_argument("--requests", help="JSON manifest containing a requests list; preferred for stable case IDs and labels.")
    parser.add_argument("--doi", action="append", default=[], help="DOI shorthand request; may be repeated.")
    parser.add_argument("--arxiv-id", action="append", default=[], help="arXiv ID shorthand request; may be repeated.")
    parser.add_argument("--title", action="append", default=[], help="Title-query shorthand request; may be repeated.")
    parser.add_argument("--title-source", choices=["openalex", "crossref", "arxiv"], default="openalex")
    parser.add_argument("--source", action="append", choices=list(SOURCE_NAMES), default=[])
    parser.add_argument("--mailto", default=os.environ.get("CITEGUARD_MAILTO", ""))
    parser.add_argument("--semantic-scholar-api-key", default=os.environ.get("SEMANTIC_SCHOLAR_API_KEY", ""))
    parser.add_argument("--http-timeout", type=int, default=12)
    parser.add_argument("--http-retries", type=int, default=1)
    parser.add_argument("--http-retry-backoff", type=float, default=0.2)
    parser.add_argument("--http-min-interval", type=float, default=0.2)
    parser.add_argument("--source-budget", type=float, default=8.0)
    parser.add_argument("--min-title-similarity", type=float, default=0.98)
    parser.add_argument("--collected-at", default="", help="ISO-8601 timestamp; defaults to the current UTC time.")
    parser.add_argument("--output", help="Output JSON dataset containing accepted cases.")
    parser.add_argument("--report", help="Optional JSON report containing accepted and rejected requests.")
    parser.add_argument("--merge-into", help="Existing live benchmark dataset to merge into.")
    parser.add_argument("--replace", action="store_true", help="Replace duplicate case IDs when merging.")
    parser.add_argument("--dry-run", action="store_true", help="Print the collector payload without writing files.")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when any request is rejected.")
    parser.add_argument("--lang", default="en", help="Language for shorthand requests.")
    parser.add_argument("--domain", default="other", help="Domain for shorthand requests.")
    parser.add_argument("--rights-basis", default="public_metadata")
    args = parser.parse_args(argv)

    try:
        manifest = _request_manifest_from_args(args)
        requests = load_collection_requests(manifest)
        names = _source_names(requests, args.source)
        sources = _build_sources(args, names)
        collected = collect_live_retrieval_dataset(
            requests,
            sources,
            collected_at=args.collected_at or None,
            min_title_similarity=args.min_title_similarity,
        )
        output_payload = collected
        if args.merge_into:
            output_payload = merge_collected_cases(
                _load_json(args.merge_into),
                collected,
                replace=args.replace,
            )
        if args.report:
            _write_json(args.report, collected["report"])
        if args.output and not args.dry_run:
            _write_json(args.output, output_payload)
        rendered = json.dumps(output_payload, ensure_ascii=False, indent=2, sort_keys=True)
        print(rendered)
        rejected = int(collected["report"]["rejected_count"])
        if args.strict and rejected:
            return 1
        return 0
    except (LiveCaseCollectionError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
