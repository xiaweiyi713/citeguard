"""CLI input loading, normalization, and bounded evidence-file handling."""

from __future__ import annotations

import importlib
import json
import os
from typing import Any, Dict, List, Optional

from citeguard.errors import runtime_config_error_details
from citeguard.graph import CitationRecord
from citeguard.verification import (
    ClaimSupportAuditItem,
    ClaimSupportRequest,
    load_citation_candidates,
    parse_citation,
)


class CLIUsageError(ValueError):
    """Argument parsing or validation error with a stable machine-readable code."""

    def __init__(self, code: str, message: str, details: Optional[dict] = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


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
        return [item if str(item.get("claim", "")).strip() else {**item, "claim": default_claim} for item in items]
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
    details: Dict[str, Any] = {"field": field}
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
    details: Dict[str, Any] = {"command": "support-audit"}
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
        parsed: List[CitationRecord] = []
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
    details: Dict[str, Any] = {}
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
