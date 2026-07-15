"""Command line interface for CiteGuard."""

from __future__ import annotations

import argparse
import json
import re
import sys
from typing import Any, Dict, Iterable, NoReturn, Optional, TextIO

from citeguard import cli_input as _cli_input
from citeguard.cli_input import (
    CLIUsageError,
    _has_citation_input,
    _input_file_error,
    _item_has_citation_input,
    _load_audit_input,
    _load_citation_or_reference_input,
    _load_support_audit_input,
    _normalize_citation_item,
    _normalize_claim_support_audit_item,
    _output_file_error,
    _parse_args_citation,
    _read_pdf_text,
    _validate_counterevidence_top_k,
    _value_error_details,
)
from citeguard.errors import error_payload
from citeguard.model_tools import warmup_support_models
from citeguard.runtime import (
    build_configured_source,
    build_configured_support_backend,
    build_doi_registry_probe,
    build_oa_fulltext_fetcher,
    cache_path,
    environment_status,
)
from citeguard.skill_install import install_skill
from citeguard.verification import (
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

# Compatibility hooks for callers that patched these private CLI helpers before
# input handling moved into ``citeguard.cli_input``.
importlib = _cli_input.importlib


class CiteGuardArgumentParser(argparse.ArgumentParser):
    """argparse parser that lets us return JSON errors instead of plain text."""

    def error(self, message: str) -> NoReturn:
        raise CLIUsageError(
            "argument_parse_error",
            message,
            details=_argument_parse_error_details(self.prog, message),
        )


def _argument_parse_error_details(prog: str, message: str) -> dict:
    details: Dict[str, Any] = {"prog": prog}
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

    skill_parser = subparsers.add_parser("skill", help="Install the bundled agent skill into a supported client.")
    _add_output_args(skill_parser)
    skill_subparsers = skill_parser.add_subparsers(
        dest="skill_command", required=True, parser_class=CiteGuardArgumentParser
    )
    skill_install_parser = skill_subparsers.add_parser("install", help="Install CiteGuard's verification skill.")
    skill_install_parser.add_argument("--client", choices=["codex", "claude", "cursor"], default="codex")
    skill_install_parser.add_argument("--scope", choices=["user", "project"], default="user")
    skill_install_parser.add_argument(
        "--project-dir",
        default="",
        help="Project root for --scope project; defaults to the current directory.",
    )
    skill_install_parser.add_argument(
        "--destination",
        default="",
        help="Explicit destination directory; overrides --client and --scope path selection.",
    )
    skill_install_parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing, different CiteGuard skill directory.",
    )

    models_parser = subparsers.add_parser("models", help="Manage optional claim-support models.")
    _add_output_args(models_parser)
    models_subparsers = models_parser.add_subparsers(
        dest="models_command", required=True, parser_class=CiteGuardArgumentParser
    )
    models_warmup_parser = models_subparsers.add_parser(
        "warmup", help="Download/load the reranker and NLI models and run a probe."
    )
    models_warmup_parser.add_argument("--reranker-model", default="")
    models_warmup_parser.add_argument("--nli-model", default="")

    cache_parser = subparsers.add_parser("cache", help="Inspect or clear the local SQLite cache.")
    _add_output_args(cache_parser)
    cache_subparsers = cache_parser.add_subparsers(
        dest="cache_command", required=True, parser_class=CiteGuardArgumentParser
    )
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
    support_set_parser.add_argument(
        "--counterevidence-top-k", type=int, default=3, help="Counter-evidence candidates per claim."
    )

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
    support_audit_parser.add_argument(
        "--high-risk-only", action="store_true", help="Only return high-risk items in results."
    )
    support_audit_parser.add_argument(
        "--with-counterevidence",
        action="store_true",
        help="Attach possible counter-evidence candidates to review-worthy support results.",
    )
    support_audit_parser.add_argument(
        "--counterevidence-top-k", type=int, default=3, help="Counter-evidence candidates per claim."
    )
    support_audit_parser.add_argument(
        "--jobs",
        type=int,
        choices=range(1, 17),
        default=4,
        help="Concurrent batch items (1-16; each scholarly source remains serialized).",
    )

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
    audit_parser.add_argument(
        "--jobs",
        type=int,
        choices=range(1, 17),
        default=4,
        help="Concurrent batch items (1-16; each scholarly source remains serialized).",
    )
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
    _cli_input._read_pdf_text = _read_pdf_text
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
        if args.command == "skill" and args.skill_command == "install":
            _print_json(
                install_skill(
                    args.client,
                    args.scope,
                    destination=args.destination,
                    project_dir=args.project_dir,
                    force=args.force,
                ),
                out,
                compact=args.compact,
            )
            return 0
        if args.command == "models" and args.models_command == "warmup":
            try:
                payload = warmup_support_models(
                    reranker_model=args.reranker_model or None,
                    nli_model=args.nli_model or None,
                )
            except (ImportError, ModuleNotFoundError, RuntimeError) as exc:
                return _write_error(
                    err,
                    "model_unavailable",
                    str(exc),
                    compact=args.compact,
                    details={
                        "command": "models warmup",
                        "install_hint": 'python -m pip install "citationguard[models]"',
                    },
                )
            _print_json(payload, out, compact=args.compact)
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
            _print_json(
                verify_citation(candidate, active_source, doi_registry=build_doi_registry_probe()).to_dict(),
                out,
                compact=args.compact,
            )
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
                oa_fulltext_fetcher=build_oa_fulltext_fetcher(),
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
            support_set_result = check_claim_support_set(
                args.claim,
                candidates,
                active_source,
                backend=active_backend,
                lang=args.lang,
                oa_fulltext_fetcher=build_oa_fulltext_fetcher(),
            )
            payload = support_set_result.to_dict()
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
                extracted_candidates = load_citation_candidates(args.path, source_format=args.format)
            except OSError as exc:
                raise _input_file_error(exc, command=args.command, path=args.path) from exc
            _print_json(extracted_candidates, out, compact=args.compact)
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
            audit_candidates = [
                parse_citation(**_normalize_citation_item(item, index=index, command=args.command))
                for index, item in enumerate(citations, start=1)
            ]
            active_source = source or build_configured_source()
            payload = audit_citations(
                audit_candidates,
                active_source,
                doi_registry=build_doi_registry_probe(),
                max_workers=args.jobs,
            ).to_dict()
            if args.high_risk_only:
                payload = filter_high_risk_payload(payload)
            _print_json(payload, out, compact=args.compact)
            return 0
        if args.command == "support-audit":
            items = _load_support_audit_input(args.path, claim=args.claim)
            requests = [
                _normalize_claim_support_audit_item(item, index=index) for index, item in enumerate(items, start=1)
            ]
            if args.with_counterevidence:
                _validate_counterevidence_top_k(args.counterevidence_top_k, command=args.command)
            active_source = source or build_configured_source()
            active_backend = support_backend or build_configured_support_backend()
            support_report = audit_claim_support(
                requests,
                active_source,
                backend=active_backend,
                lang=args.lang,
                oa_fulltext_fetcher=build_oa_fulltext_fetcher(),
                max_workers=args.jobs,
            )
            payload = support_report.to_dict()
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


def _print_json(payload: Any, out: TextIO, compact: bool = False) -> None:
    if compact:
        out.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    else:
        out.write(json.dumps(payload, indent=2, sort_keys=True))
    out.write("\n")


def main(argv: Optional[Iterable[str]] = None) -> None:
    raise SystemExit(run(argv))


if __name__ == "__main__":
    main()
