"""Command line interface for CiteGuard."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
from typing import Any, Iterable, Optional, TextIO

from citeguard.errors import error_payload, runtime_config_error_details
from citeguard.runtime import build_configured_source, build_configured_support_backend, build_doi_registry_probe, cache_path, environment_status
from citeguard.verification import (
    ClaimSupportAuditItem,
    ClaimSupportRequest,
    audit_citations,
    audit_claim_support,
    check_claim_support,
    check_claim_support_set,
    clear_cache,
    enrich_support_payload_with_counterevidence,
    export_cache_records,
    filter_high_risk_payload,
    inspect_cache,
    load_citation_candidates,
    parse_citation,
    search_counterevidence_candidates,
    verify_citation,
)


class CLIUsageError(ValueError):
    """Argument parsing or validation error with a stable machine-readable code."""

    def __init__(self, code: str, message: str, details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class CiteGuardArgumentParser(argparse.ArgumentParser):
    """argparse parser that lets us return JSON errors instead of plain text."""

    def error(self, message: str) -> None:
        raise CLIUsageError(
            "argument_parse_error",
            message,
            details=_argument_parse_error_details(self.prog, message),
        )


def _argument_parse_error_details(prog: str, message: str) -> dict:
    details = {"prog": prog}
    command = _command_from_prog(prog)
    if command:
        details["command"] = command
    argument_names = _argument_names_from_error_message(message)
    if argument_names:
        details["arguments"] = argument_names
    return details


def _command_from_prog(prog: str) -> str:
    parts = str(prog or "").split()
    if parts and parts[0] == "citeguard":
        return " ".join(parts[1:])
    return ""


def _argument_names_from_error_message(message: str) -> list:
    names = re.findall(r"(?<!\w)-{1,2}[A-Za-z0-9][A-Za-z0-9_-]*", message)
    return list(dict.fromkeys(names))


def build_parser() -> argparse.ArgumentParser:
    parser = CiteGuardArgumentParser(
        prog="citeguard",
        description="Verify scientific citations against live scholarly metadata sources.",
    )
    parser.add_argument("--compact", action="store_true", help="Print compact JSON instead of indented JSON.")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=CiteGuardArgumentParser)

    status_parser = subparsers.add_parser("status", help="Show configuration and dependency status.")
    _add_output_args(status_parser)
    status_parser.add_argument(
        "--check-sources",
        action="store_true",
        help="Probe each configured scholarly source with a lightweight live query.",
    )
    status_parser.add_argument(
        "--health-query",
        default="Attention Is All You Need",
        help="Query used by --check-sources; defaults to a well-known paper title.",
    )

    cache_parser = subparsers.add_parser("cache", help="Inspect or clear the local SQLite cache.")
    _add_output_args(cache_parser)
    cache_subparsers = cache_parser.add_subparsers(dest="cache_command", required=True, parser_class=CiteGuardArgumentParser)
    cache_inspect_parser = cache_subparsers.add_parser("inspect", help="Print cache schema and entry counts.")
    cache_inspect_parser.add_argument("--path", default="", help="Cache path; defaults to CITEGUARD_CACHE.")
    cache_inspect_parser.add_argument(
        "--operation",
        choices=["search", "lookup"],
        default="",
        help="Only count cache rows produced by cached search or lookup operations in selected_* fields.",
    )
    cache_inspect_parser.add_argument(
        "--source",
        default="",
        help="Only count cache rows produced by this source name in selected_* fields.",
    )
    cache_clear_parser = cache_subparsers.add_parser("clear", help="Delete cached search and lookup rows.")
    cache_clear_parser.add_argument("--path", default="", help="Cache path; defaults to CITEGUARD_CACHE.")
    cache_clear_parser.add_argument(
        "--operation",
        choices=["search", "lookup"],
        default="",
        help="Only delete cache rows produced by cached search or lookup operations.",
    )
    cache_clear_parser.add_argument(
        "--source",
        default="",
        help="Only delete cache rows produced by this source name.",
    )
    cache_export_parser = cache_subparsers.add_parser(
        "export",
        help="Export cached citation records as an offline replay fixture.",
    )
    cache_export_parser.add_argument("--path", default="", help="Cache path; defaults to CITEGUARD_CACHE.")
    cache_export_parser.add_argument(
        "--output",
        default="",
        help="Optional JSON file to write records only; stdout includes metadata when omitted.",
    )
    cache_export_parser.add_argument(
        "--deterministic",
        action="store_true",
        help="Strip timestamp-only cache provenance from exported records for reproducible fixture files.",
    )
    cache_export_parser.add_argument(
        "--include-manifest",
        action="store_true",
        help="Write a fixture object with fixture_manifest plus records instead of the legacy records-only list.",
    )
    cache_export_parser.add_argument(
        "--operation",
        choices=["search", "lookup"],
        default="",
        help="Only export records produced by cached search or lookup rows.",
    )
    cache_export_parser.add_argument(
        "--source",
        default="",
        help="Only export records from cache rows produced by this source name, such as openalex or crossref.",
    )

    verify_parser = subparsers.add_parser("verify", help="Verify one citation.")
    _add_output_args(verify_parser)
    _add_citation_args(verify_parser)

    support_parser = subparsers.add_parser("support", help="Check whether a cited paper supports a claim.")
    _add_output_args(support_parser)
    support_parser.add_argument("--claim", required=True, help="Claim sentence to check against the cited paper.")
    support_parser.add_argument("--lang", default="", help="Optional language hint for the claim.")
    _add_citation_args(support_parser)

    counterevidence_parser = subparsers.add_parser(
        "counterevidence",
        help="Search for scholarly records that may contain counter-evidence for a claim.",
    )
    _add_output_args(counterevidence_parser)
    counterevidence_parser.add_argument("--claim", required=True, help="Claim sentence to investigate.")
    counterevidence_parser.add_argument("--top-k", type=int, default=5, help="Maximum number of candidate records.")

    support_set_parser = subparsers.add_parser(
        "support-set",
        help="Check whether a claim is supported by a set of citations.",
    )
    _add_output_args(support_set_parser)
    support_set_parser.add_argument(
        "path",
        help="Path to a JSON/JSONL list of citation objects or a Markdown/LaTeX/BibTeX/BBL/DOCX/plain-text reference file.",
    )
    support_set_parser.add_argument("--claim", required=True, help="Claim sentence to check against the citation set.")
    support_set_parser.add_argument("--lang", default="", help="Optional language hint for the claim.")
    support_set_parser.add_argument(
        "--with-counterevidence",
        action="store_true",
        help="Attach possible counter-evidence candidates when the aggregate needs review.",
    )
    support_set_parser.add_argument("--counterevidence-top-k", type=int, default=3, help="Counter-evidence candidates per claim.")

    extract_parser = subparsers.add_parser(
        "extract",
        help="Extract citation candidates from Markdown, LaTeX, BibTeX, BBL, DOCX, or plain text.",
    )
    _add_output_args(extract_parser)
    extract_parser.add_argument("path", help="Manuscript or bibliography file to scan.")
    extract_parser.add_argument(
        "--format",
        choices=["auto", "markdown", "md", "latex", "tex", "bibtex", "bbl", "docx", "text", "txt"],
        default="auto",
        help="Input format; defaults to extension-based auto detection.",
    )

    support_audit_parser = subparsers.add_parser(
        "support-audit",
        help="Check claim-support pairs from JSON/JSONL or one claim against extracted reference candidates.",
    )
    _add_output_args(support_audit_parser)
    support_audit_parser.add_argument(
        "path",
        help="Path to JSON/JSONL claim-citation objects, or a Markdown/LaTeX/BibTeX/BBL/DOCX/plain-text reference file when --claim is provided.",
    )
    support_audit_parser.add_argument(
        "--claim",
        default="",
        help="Default claim for citation rows that do not include claim, and required for non-JSON reference files.",
    )
    support_audit_parser.add_argument("--lang", default="", help="Default language hint for claim items.")
    support_audit_parser.add_argument("--high-risk-only", action="store_true", help="Only return high-risk items in results.")
    support_audit_parser.add_argument(
        "--with-counterevidence",
        action="store_true",
        help="Attach possible counter-evidence candidates to review-worthy support results.",
    )
    support_audit_parser.add_argument("--counterevidence-top-k", type=int, default=3, help="Counter-evidence candidates per claim.")

    audit_parser = subparsers.add_parser(
        "audit",
        help="Verify citations from JSON/JSONL or extracted reference candidates.",
    )
    _add_output_args(audit_parser)
    audit_parser.add_argument(
        "path",
        help="Path to a JSON/JSONL list of citation objects or a Markdown/LaTeX/BibTeX/BBL/DOCX/plain-text reference file.",
    )
    audit_parser.add_argument("--high-risk-only", action="store_true", help="Only return high-risk items in results.")
    return parser


def _add_output_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--compact", action="store_true", default=argparse.SUPPRESS, help="Print compact JSON.")


def _add_citation_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--raw-text", default="", help="Free-text citation to parse and verify.")
    parser.add_argument("--title", default="", help="Citation title.")
    parser.add_argument("--author", action="append", default=None, help="Citation author; repeat for multiple authors.")
    parser.add_argument("--year", type=int, default=None, help="Publication year.")
    parser.add_argument("--venue", default="", help="Venue, journal, conference, or repository.")
    parser.add_argument("--abstract", default="", help="Known abstract text to use as support evidence.")
    parser.add_argument(
        "--evidence",
        action="append",
        default=None,
        help="User-provided evidence snippet; repeat for multiple snippets.",
    )
    parser.add_argument(
        "--full-text",
        action="append",
        default=None,
        help="Lawfully available full-text excerpt to use as support evidence; repeat for multiple excerpts.",
    )
    parser.add_argument(
        "--full-text-file",
        action="append",
        default=None,
        help="Path to a lawfully available full-text excerpt file; repeat for multiple files.",
    )
    parser.add_argument("--doi", default="", help="DOI.")
    parser.add_argument("--arxiv-id", default="", help="arXiv identifier.")


def _cache_fixture_with_manifest(payload: dict) -> dict:
    manifest_keys = [
        "schema_version",
        "cache_entry_count",
        "cache_entry_prefixes",
        "selected_cache_entry_count",
        "selected_cache_entry_prefixes",
        "export_filters",
        "cache_oldest_entry_timestamp",
        "cache_newest_entry_timestamp",
        "exported_at",
        "deterministic",
        "record_count",
        "exists",
    ]
    manifest = {key: payload.get(key) for key in manifest_keys}
    manifest["fixture_format"] = "manifest_records"
    manifest["provenance_policy"] = "cache_export_replay_fixture"
    return {
        "fixture_manifest": manifest,
        "records": payload["records"],
    }


def run(
    argv: Optional[Iterable[str]] = None,
    source=None,
    support_backend=None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Run the CLI and return a process-style exit code."""

    out = stdout or sys.stdout
    err = stderr or sys.stderr
    parser = build_parser()
    raw_argv = list(argv) if argv is not None else None
    compact_hint = bool(raw_argv and "--compact" in raw_argv)

    try:
        args = parser.parse_args(raw_argv)
        if args.command == "status":
            _print_json(
                environment_status(check_sources=args.check_sources, health_query=args.health_query),
                out,
                compact=args.compact,
            )
            return 0
        if args.command == "cache":
            active_cache_path = args.path or cache_path()
            if args.cache_command == "inspect":
                _print_json(
                    inspect_cache(
                        active_cache_path,
                        operation=args.operation or None,
                        source=args.source or None,
                    ),
                    out,
                    compact=args.compact,
                )
                return 0
            if args.cache_command == "clear":
                _print_json(
                    clear_cache(
                        active_cache_path,
                        operation=args.operation or None,
                        source=args.source or None,
                    ),
                    out,
                    compact=args.compact,
                )
                return 0
            if args.cache_command == "export":
                payload = export_cache_records(
                    active_cache_path,
                    deterministic=args.deterministic,
                    operation=args.operation or None,
                    source=args.source or None,
                )
                if args.output:
                    fixture_payload: Any = payload["records"]
                    if args.include_manifest:
                        fixture_payload = _cache_fixture_with_manifest(payload)
                    try:
                        with open(args.output, "w", encoding="utf-8") as handle:
                            json.dump(fixture_payload, handle, indent=2, sort_keys=True)
                            handle.write("\n")
                    except OSError as exc:
                        raise _output_file_error(
                            exc,
                            command=args.command,
                            path=args.output,
                            cache_command=args.cache_command,
                        ) from exc
                    _print_json(
                        {
                            "path": active_cache_path,
                            "output": args.output,
                            "schema_version": payload["schema_version"],
                            "cache_entry_count": payload["cache_entry_count"],
                            "cache_entry_prefixes": payload["cache_entry_prefixes"],
                            "selected_cache_entry_count": payload["selected_cache_entry_count"],
                            "selected_cache_entry_prefixes": payload["selected_cache_entry_prefixes"],
                            "export_filters": payload["export_filters"],
                            "cache_oldest_entry_timestamp": payload["cache_oldest_entry_timestamp"],
                            "cache_newest_entry_timestamp": payload["cache_newest_entry_timestamp"],
                            "exported_at": payload["exported_at"],
                            "deterministic": payload["deterministic"],
                            "fixture_format": "manifest_records" if args.include_manifest else "records",
                            "record_count": payload["record_count"],
                            "exists": payload["exists"],
                        },
                        out,
                        compact=args.compact,
                    )
                else:
                    _print_json(payload, out, compact=args.compact)
                return 0
        if args.command == "verify":
            if not _has_citation_input(args):
                return _write_error(
                    err,
                    "missing_citation_input",
                    "Provide --raw-text, --title, --doi, or --arxiv-id.",
                    compact=args.compact,
                    details={"command": args.command},
                )
            candidate = _parse_args_citation(args)
            active_source = source or build_configured_source()
            _print_json(verify_citation(candidate, active_source, doi_registry=build_doi_registry_probe()).to_dict(), out, compact=args.compact)
            return 0
        if args.command == "support":
            if not str(args.claim).strip():
                return _write_error(
                    err,
                    "missing_claim",
                    "Provide a non-empty --claim.",
                    compact=args.compact,
                    details={"command": args.command},
                )
            if not _has_citation_input(args):
                return _write_error(
                    err,
                    "missing_citation_input",
                    "Provide --raw-text, --title, --doi, or --arxiv-id.",
                    compact=args.compact,
                    details={"command": args.command},
                )
            candidate = _parse_args_citation(args)
            active_source = source or build_configured_source()
            active_backend = support_backend or build_configured_support_backend()
            result = check_claim_support(
                args.claim,
                candidate,
                active_source,
                backend=active_backend,
                lang=args.lang,
            )
            _print_json(result.to_dict(), out, compact=args.compact)
            return 0
        if args.command == "counterevidence":
            if not str(args.claim).strip():
                return _write_error(
                    err,
                    "missing_claim",
                    "Provide a non-empty --claim.",
                    compact=args.compact,
                    details={"command": args.command},
                )
            if args.top_k < 0:
                return _write_error(
                    err,
                    "invalid_input",
                    "--top-k must be non-negative.",
                    compact=args.compact,
                    details={"command": args.command, "field": "top_k"},
                )
            active_source = source or build_configured_source()
            report = search_counterevidence_candidates(args.claim, active_source, top_k=args.top_k)
            _print_json(report.to_dict(), out, compact=args.compact)
            return 0
        if args.command == "support-set":
            if not str(args.claim).strip():
                return _write_error(
                    err,
                    "missing_claim",
                    "Provide a non-empty --claim.",
                    compact=args.compact,
                    details={"command": args.command},
                )
            citations = _load_citation_or_reference_input(args.path, command=args.command, label="support-set input")
            if not citations:
                raise CLIUsageError(
                    "missing_citation_input",
                    "support-set input must include at least one citation object",
                    details={"command": args.command},
                )
            for index, item in enumerate(citations, start=1):
                if not _item_has_citation_input(item):
                    raise CLIUsageError(
                        "missing_citation_input",
                        "support-set items must include raw_text, title, doi, or arxiv_id",
                        details={"command": args.command, "index": index},
                    )
            candidates = [
                parse_citation(**_normalize_citation_item(item, index=index, command=args.command))
                for index, item in enumerate(citations, start=1)
            ]
            if args.with_counterevidence:
                _validate_counterevidence_top_k(args.counterevidence_top_k, command=args.command)
            active_source = source or build_configured_source()
            active_backend = support_backend or build_configured_support_backend()
            result = check_claim_support_set(
                args.claim,
                candidates,
                active_source,
                backend=active_backend,
                lang=args.lang,
            )
            payload = result.to_dict()
            if args.with_counterevidence:
                payload = enrich_support_payload_with_counterevidence(
                    payload,
                    active_source,
                    top_k=args.counterevidence_top_k,
                )
            _print_json(payload, out, compact=args.compact)
            return 0
        if args.command == "extract":
            try:
                candidates = load_citation_candidates(args.path, source_format=args.format)
            except OSError as exc:
                raise _input_file_error(exc, command=args.command, path=args.path) from exc
            _print_json(candidates, out, compact=args.compact)
            return 0
        if args.command == "audit":
            citations = _load_audit_input(args.path)
            for index, item in enumerate(citations, start=1):
                if not _item_has_citation_input(item):
                    raise CLIUsageError(
                        "missing_citation_input",
                        "audit items must include raw_text, title, doi, or arxiv_id",
                        details={"command": args.command, "index": index},
                    )
            candidates = [
                parse_citation(**_normalize_citation_item(item, index=index, command=args.command))
                for index, item in enumerate(citations, start=1)
            ]
            active_source = source or build_configured_source()
            payload = audit_citations(candidates, active_source, doi_registry=build_doi_registry_probe()).to_dict()
            if args.high_risk_only:
                payload = filter_high_risk_payload(payload)
            _print_json(payload, out, compact=args.compact)
            return 0
        if args.command == "support-audit":
            items = _load_support_audit_input(args.path, claim=args.claim)
            requests = [
                _normalize_claim_support_audit_item(item, index=index)
                for index, item in enumerate(items, start=1)
            ]
            if args.with_counterevidence:
                _validate_counterevidence_top_k(args.counterevidence_top_k, command=args.command)
            active_source = source or build_configured_source()
            active_backend = support_backend or build_configured_support_backend()
            report = audit_claim_support(
                requests,
                active_source,
                backend=active_backend,
                lang=args.lang,
            )
            payload = report.to_dict()
            if args.with_counterevidence:
                payload = enrich_support_payload_with_counterevidence(
                    payload,
                    active_source,
                    top_k=args.counterevidence_top_k,
                )
            if args.high_risk_only:
                payload = filter_high_risk_payload(payload)
            _print_json(payload, out, compact=args.compact)
            return 0
    except CLIUsageError as exc:
        return _write_error(err, exc.code, str(exc), compact=compact_hint, details=exc.details)
    except json.JSONDecodeError as exc:
        return _write_error(
            err,
            "invalid_json",
            str(exc),
            compact=compact_hint,
            details={"line": exc.lineno, "column": exc.colno},
        )
    except OSError as exc:
        return _write_error(
            err,
            "file_error",
            str(exc),
            compact=compact_hint,
            details={"errno": getattr(exc, "errno", None), "filename": getattr(exc, "filename", None)},
        )
    except ValueError as exc:
        return _write_error(
            err,
            "invalid_input",
            str(exc),
            compact=compact_hint,
            details=_value_error_details(exc, locals().get("args")),
        )

    return _write_error(err, "unsupported_command", f"Unsupported command {args.command!r}.", compact=args.compact)


def _parse_args_citation(args):
    return parse_citation(
        raw_text=args.raw_text,
        title=args.title,
        authors=args.author,
        year=args.year,
        venue=args.venue,
        abstract=args.abstract,
        doi=args.doi,
        arxiv_id=args.arxiv_id,
        evidence_chunks=_chunks_from_cli_args(args),
    )


def _validate_counterevidence_top_k(top_k: int, command: str) -> None:
    if top_k < 0:
        raise CLIUsageError(
            "invalid_input",
            "--counterevidence-top-k must be non-negative.",
            details={"command": command, "field": "counterevidence_top_k"},
        )


def _has_citation_input(args) -> bool:
    return bool(args.raw_text or args.title or args.doi or args.arxiv_id)


def _load_citation_file(path: str, command: str = "audit", label: str = "audit input") -> list:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise _input_file_error(exc, command=command, path=path) from exc
    if not text.strip():
        return []

    is_jsonl = path.lower().endswith(".jsonl")
    if not is_jsonl:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CLIUsageError(
                "invalid_json",
                str(exc),
                details={"command": command, "line": exc.lineno, "column": exc.colno},
            ) from exc
        if not isinstance(payload, list):
            raise CLIUsageError(
                "invalid_input",
                f"{label} must be a JSON list or JSONL stream of citation objects",
                details={
                    "command": command,
                    "expected": "JSON list or JSONL object stream",
                    "received": type(payload).__name__,
                },
            )
    else:
        payload = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                payload.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise CLIUsageError(
                    "invalid_json",
                    f"{label} has invalid JSON on line {line_number}: {exc.msg}.",
                    details={"command": command, "line": line_number, "column": exc.colno},
                ) from exc

    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            raise CLIUsageError(
                "invalid_input",
                f"{label} item {index} must be an object",
                details={
                    "command": command,
                    "index": index,
                    "expected": "object",
                    "received": type(item).__name__,
                },
            )
    return payload


def _load_audit_input(path: str) -> list:
    return _load_citation_or_reference_input(path, command="audit", label="audit input")


def _load_support_audit_input(path: str, claim: str = "") -> list:
    default_claim = str(claim or "").strip()
    if path.lower().endswith((".json", ".jsonl")):
        items = _load_citation_file(path, command="support-audit", label="support-audit input")
        if not default_claim:
            return items
        return [
            item if str(item.get("claim", "")).strip() else {**item, "claim": default_claim}
            for item in items
        ]
    if not default_claim:
        raise CLIUsageError(
            "missing_claim",
            "Provide --claim when support-audit reads a Markdown, LaTeX, BibTeX, BBL, DOCX, or plain-text reference file.",
            details={"command": "support-audit", "field": "claim"},
        )
    try:
        citations = load_citation_candidates(path)
    except OSError as exc:
        raise _input_file_error(exc, command="support-audit", path=path) from exc
    if not citations:
        raise CLIUsageError(
            "missing_citation_input",
            "support-audit input must include at least one extracted citation candidate",
            details={"command": "support-audit"},
        )
    return [{**item, "claim": default_claim} for item in citations]


def _load_citation_or_reference_input(path: str, command: str, label: str) -> list:
    if path.lower().endswith((".json", ".jsonl")):
        return _load_citation_file(path, command=command, label=label)
    try:
        return load_citation_candidates(path)
    except OSError as exc:
        raise _input_file_error(exc, command=command, path=path) from exc


def _normalize_citation_item(
    item: dict,
    index: Optional[int] = None,
    command: str = "",
    citation_index: Optional[int] = None,
) -> dict:
    _validate_citation_scalar_fields(item, index=index, command=command, citation_index=citation_index)
    return {
        "raw_text": item.get("raw_text", ""),
        "title": item.get("title", ""),
        "authors": _normalize_authors(item.get("authors"), index=index, command=command, citation_index=citation_index),
        "year": _normalize_year(item.get("year"), index=index, command=command, citation_index=citation_index),
        "venue": item.get("venue", ""),
        "abstract": item.get("abstract", ""),
        "doi": item.get("doi", ""),
        "arxiv_id": item.get("arxiv_id", ""),
        "metadata": _citation_input_metadata(item),
        "evidence_chunks": _normalize_evidence_chunks(
            item,
            index=index,
            command=command,
            citation_index=citation_index,
        ),
    }


def _citation_input_metadata(item: dict) -> dict:
    metadata = dict(item.get("metadata") or {})
    source_fields = {
        "input_source_path": item.get("source_path", ""),
        "input_source_format": item.get("source_format", ""),
        "input_source_type": item.get("source_type", ""),
        "input_source_id": item.get("source_id", ""),
        "input_source_index": item.get("source_index"),
        "input_source_locator": item.get("source_locator", ""),
        "input_source_line_start": item.get("source_line_start"),
        "input_source_line_end": item.get("source_line_end"),
    }
    for key, value in source_fields.items():
        if value not in (None, ""):
            metadata.setdefault(key, value)
    return metadata


def _chunks_from_cli_args(args) -> list:
    item = {
        "evidence_text": args.evidence or [],
        "full_text": args.full_text or [],
        "full_text_file": args.full_text_file or [],
    }
    return _normalize_evidence_chunks(item, command=getattr(args, "command", ""))


def _as_list(value: Any) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def _chunk(text: str, source_field: str, evidence_scope: str, source_url: str = "") -> dict:
    return {
        "text": text,
        "source_field": source_field,
        "source_url": source_url,
        "evidence_scope": evidence_scope,
    }


def _normalize_evidence_chunks(
    item: dict,
    index: Optional[int] = None,
    command: str = "",
    citation_index: Optional[int] = None,
) -> list:
    chunks = []
    for chunk_index, value in enumerate(_as_list(item.get("evidence_chunks")), start=1):
        if isinstance(value, dict):
            chunks.append(dict(value))
        elif str(value).strip():
            chunks.append(_chunk(str(value), f"user_evidence_chunk_{chunk_index}", "metadata"))

    generic_values = _as_list(item.get("evidence_text")) + _as_list(item.get("evidence"))
    for chunk_index, value in enumerate(generic_values, start=1):
        if isinstance(value, dict):
            chunk = dict(value)
            chunk.setdefault("source_field", f"user_evidence_text_{chunk_index}")
            chunk.setdefault("evidence_scope", "metadata")
            chunks.append(chunk)
        elif str(value).strip():
            chunks.append(_chunk(str(value), f"user_evidence_text_{chunk_index}", "metadata"))

    full_text_values = (
        _as_list(item.get("full_text"))
        + _as_list(item.get("full_text_excerpt"))
        + _as_list(item.get("full_text_excerpts"))
    )
    for full_text_index, value in enumerate(full_text_values, start=1):
        if isinstance(value, dict):
            chunk = dict(value)
            chunk.setdefault("source_field", f"user_full_text_excerpt_{full_text_index}")
            chunk["evidence_scope"] = "full_text"
            chunks.append(chunk)
        elif str(value).strip():
            chunks.append(_chunk(str(value), f"user_full_text_excerpt_{full_text_index}", "full_text"))
    full_text_files = (
        _as_list(item.get("full_text_file"))
        + _as_list(item.get("full_text_files"))
        + _as_list(item.get("full_text_excerpt_file"))
        + _as_list(item.get("full_text_excerpt_files"))
    )
    for file_index, path in enumerate(full_text_files, start=1):
        if not isinstance(path, str):
            raise CLIUsageError(
                "invalid_input",
                "full-text excerpt file paths must be strings.",
                details=_error_details(
                    "full_text_file",
                    index=index,
                    command=command,
                    citation_index=citation_index,
                ),
            )
        text = _read_evidence_file(path, index=index, command=command, citation_index=citation_index)
        if text.strip():
            chunks.append(_chunk(text, f"user_full_text_file_{file_index}", "full_text"))
    return chunks


def _error_details(
    field: str,
    index: Optional[int] = None,
    command: str = "",
    citation_index: Optional[int] = None,
    **extra: Any,
) -> dict:
    details = {"field": field}
    if command:
        details["command"] = command
    if index is not None:
        details["index"] = index
    if citation_index is not None:
        details["citation_index"] = citation_index
    details.update({key: value for key, value in extra.items() if value not in {"", None}})
    return details


def _input_file_error(exc: OSError, command: str, path: str) -> CLIUsageError:
    return CLIUsageError(
        "file_error",
        str(exc),
        details=_error_details(
            "path",
            command=command,
            filename=getattr(exc, "filename", None) or path,
            errno=getattr(exc, "errno", None),
        ),
    )


def _output_file_error(exc: OSError, command: str, path: str, **extra: Any) -> CLIUsageError:
    return CLIUsageError(
        "file_error",
        str(exc),
        details=_error_details(
            "output",
            command=command,
            filename=getattr(exc, "filename", None) or path,
            errno=getattr(exc, "errno", None),
            **extra,
        ),
    )


def _read_evidence_file(
    path: str,
    index: Optional[int] = None,
    command: str = "",
    citation_index: Optional[int] = None,
) -> str:
    if path.lower().endswith(".pdf"):
        return _read_pdf_text(path, index=index, command=command, citation_index=citation_index)
    return _read_text_file(path, index=index, command=command, citation_index=citation_index)


def _read_text_file(
    path: str,
    index: Optional[int] = None,
    command: str = "",
    citation_index: Optional[int] = None,
) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        raise CLIUsageError(
            "file_error",
            f"Could not read full-text evidence file {path!r}: {exc}",
            details=_error_details(
                "full_text_file",
                index=index,
                command=command,
                citation_index=citation_index,
                filename=path,
                errno=getattr(exc, "errno", None),
            ),
        ) from exc


def _read_pdf_text(
    path: str,
    index: Optional[int] = None,
    command: str = "",
    citation_index: Optional[int] = None,
) -> str:
    reader_cls = _load_pdf_reader(index=index, command=command, citation_index=citation_index)
    try:
        reader = reader_cls(path)
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise CLIUsageError(
            "file_error",
            f"Could not extract text from PDF full-text file {path!r}: {exc}",
            details=_error_details(
                "full_text_file",
                index=index,
                command=command,
                citation_index=citation_index,
                filename=path,
                format="pdf",
            ),
        ) from exc


def _load_pdf_reader(index: Optional[int] = None, command: str = "", citation_index: Optional[int] = None):
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        reader = getattr(module, "PdfReader", None)
        if reader is not None:
            return reader
    raise CLIUsageError(
        "invalid_input",
        "PDF full-text files require the optional pypdf package; install pypdf or provide a UTF-8 text excerpt file.",
        details=_error_details(
            "full_text_file",
            index=index,
            command=command,
            citation_index=citation_index,
            format="pdf",
            dependency="pypdf",
        ),
    )


def _normalize_claim_support_item(item: dict, index: Optional[int] = None) -> ClaimSupportRequest:
    audit_item = _normalize_claim_support_audit_item(item, index=index)
    return ClaimSupportRequest(
        claim=audit_item.claim,
        citation=audit_item.citations[0],
        lang=audit_item.lang,
    )


def _normalize_claim_support_audit_item(item: dict, index: Optional[int] = None) -> ClaimSupportAuditItem:
    claim = str(item.get("claim", "")).strip()
    details = {"command": "support-audit"}
    if index is not None:
        details["index"] = index
    if not claim:
        raise CLIUsageError(
            "missing_claim",
            "support-audit items must include a non-empty claim",
            details=details,
        )
    if "citations" in item:
        citations = item.get("citations")
        citation_details = dict(details)
        citation_details["field"] = "citations"
        if not isinstance(citations, list):
            citation_details.update({"expected": "list", "received": type(citations).__name__})
            raise CLIUsageError(
                "invalid_input",
                "support-audit citations must be a non-empty list of citation objects",
                details=citation_details,
            )
        if not citations:
            raise CLIUsageError(
                "missing_citation_input",
                "support-audit citations must include at least one citation object",
                details=citation_details,
            )
        parsed = []
        for citation_index, citation_item in enumerate(citations, start=1):
            nested_details = dict(citation_details)
            nested_details["citation_index"] = citation_index
            if not isinstance(citation_item, dict):
                nested_details.update({"expected": "object", "received": type(citation_item).__name__})
                raise CLIUsageError(
                    "invalid_input",
                    "support-audit citations items must be objects",
                    details=nested_details,
                )
            if not _item_has_citation_input(citation_item):
                raise CLIUsageError(
                    "missing_citation_input",
                    "support-audit citations items must include raw_text, title, doi, or arxiv_id",
                    details=nested_details,
                )
            parsed.append(
                parse_citation(
                    **_normalize_citation_item(
                        citation_item,
                        index=index,
                        citation_index=citation_index,
                        command="support-audit",
                    )
                )
            )
        return ClaimSupportAuditItem(
            claim=claim,
            citations=parsed,
            lang=str(item.get("lang", "")).strip(),
            input_mode="citation_set",
        )
    if not _item_has_citation_input(item):
        raise CLIUsageError(
            "missing_citation_input",
            "support-audit items must include raw_text, title, doi, or arxiv_id",
            details=details,
        )
    lang = str(item.get("lang", "")).strip()
    return ClaimSupportAuditItem(
        claim=claim,
        citations=[parse_citation(**_normalize_citation_item(item, index=index, command="support-audit"))],
        lang=lang,
        input_mode="citation",
    )


def _item_has_citation_input(item: dict) -> bool:
    return bool(item.get("raw_text") or item.get("title") or item.get("doi") or item.get("arxiv_id"))


def _validate_citation_scalar_fields(
    item: dict,
    index: Optional[int] = None,
    command: str = "",
    citation_index: Optional[int] = None,
) -> None:
    for field in ["raw_text", "title", "venue", "abstract", "doi", "arxiv_id"]:
        value = item.get(field)
        if value is not None and not isinstance(value, str):
            raise CLIUsageError(
                "invalid_input",
                f"citation field {field!r} must be a string.",
                details=_input_details(command=command, index=index, field=field, citation_index=citation_index),
            )


def _normalize_authors(
    value: Any,
    index: Optional[int] = None,
    command: str = "",
    citation_index: Optional[int] = None,
) -> Optional[list]:
    if value is None or value == "":
        return None
    if not isinstance(value, list) or any(not isinstance(author, str) for author in value):
        raise CLIUsageError(
            "invalid_input",
            "citation field 'authors' must be a list of strings.",
            details=_input_details(command=command, index=index, field="authors", citation_index=citation_index),
        )
    return value


def _normalize_year(
    value: Any,
    index: Optional[int] = None,
    command: str = "",
    citation_index: Optional[int] = None,
) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        valid = False
    elif isinstance(value, int):
        return value
    elif isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    else:
        valid = False
    if not valid:
        raise CLIUsageError(
            "invalid_input",
            "citation field 'year' must be an integer year.",
            details=_input_details(command=command, index=index, field="year", citation_index=citation_index),
        )
    return None


def _input_details(
    command: str = "",
    index: Optional[int] = None,
    field: str = "",
    citation_index: Optional[int] = None,
) -> dict:
    details = {}
    if command:
        details["command"] = command
    if index is not None:
        details["index"] = index
    if citation_index is not None:
        details["citation_index"] = citation_index
    if field:
        details["field"] = field
    return details


def _value_error_details(exc: ValueError, args: Any = None) -> dict:
    details = {}
    command = getattr(args, "command", "")
    if command:
        details["command"] = command
    return runtime_config_error_details(str(exc), base=details, env=os.environ)


def _write_error(
    err: TextIO,
    code: str,
    message: str,
    compact: bool = False,
    details: Optional[dict] = None,
    exit_code: int = 2,
) -> int:
    _print_json(error_payload(code, message, details=details, exit_code=exit_code), err, compact=compact)
    return exit_code


def _print_json(payload: dict, out: TextIO, compact: bool = False) -> None:
    if compact:
        out.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        out.write(json.dumps(payload, indent=2, sort_keys=True))
    out.write("\n")


def main(argv: Optional[Iterable[str]] = None) -> None:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main()
