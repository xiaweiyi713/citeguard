"""Input validation and bounded evidence-file handling for the MCP surface."""

from __future__ import annotations

import errno
import importlib
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from citeguard.errors import error_payload, runtime_config_error_details
from citeguard.verification import parse_citation


class MCPInputError(ValueError):
    """Expected MCP tool input error that should be returned as a tool result."""

    def __init__(self, message: str, details: dict) -> None:
        super().__init__(message)
        self.details = details

    def to_payload(self) -> dict:
        return error_payload("invalid_input", str(self), details=self.details)


class MCPFileError(OSError):
    """Expected MCP filesystem error that should be returned as a tool result."""

    def __init__(self, message: str, details: dict) -> None:
        super().__init__(message)
        self.details = details

    def to_payload(self) -> dict:
        return error_payload("file_error", str(self), details=self.details)


MAX_BATCH_ITEMS = 100
MAX_EVIDENCE_CHUNKS = 200
MAX_INLINE_EVIDENCE_CHARS = 2_000_000
MAX_EVIDENCE_FILE_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 80
ALLOWED_EVIDENCE_SUFFIXES = {"", ".txt", ".md", ".markdown", ".tex", ".html", ".htm", ".pdf"}


def _parse_counterevidence_top_k(top_k: Any, tool: str) -> Union[int, Dict[str, Any]]:
    try:
        parsed = int(top_k)
    except (TypeError, ValueError):
        return error_payload(
            "invalid_input",
            "counterevidence_top_k must be an integer.",
            details={"tool": tool, "field": "counterevidence_top_k"},
        )
    if parsed < 0:
        return error_payload(
            "invalid_input",
            "counterevidence_top_k must be non-negative.",
            details={"tool": tool, "field": "counterevidence_top_k"},
        )
    return parsed


def _parse_max_workers(value: Any, tool: str) -> Union[int, Dict[str, Any]]:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return error_payload(
            "invalid_input",
            "max_workers must be an integer from 1 to 16.",
            details={"tool": tool, "field": "max_workers", "expected": "integer_1_to_16"},
        )
    if not 1 <= parsed <= 16:
        return error_payload(
            "invalid_input",
            "max_workers must be an integer from 1 to 16.",
            details={"tool": tool, "field": "max_workers", "expected": "integer_1_to_16"},
        )
    return parsed


def _has_citation_input(raw_text: str = "", title: str = "", doi: str = "", arxiv_id: str = "") -> bool:
    return bool(raw_text or title or doi or arxiv_id)


def _parse_citation_item(
    item: Dict[str, Any],
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
):
    return _parse_citation_fields(
        raw_text=item.get("raw_text", ""),
        title=item.get("title", ""),
        authors=item.get("authors"),
        year=item.get("year"),
        venue=item.get("venue", ""),
        abstract=item.get("abstract", ""),
        doi=item.get("doi", ""),
        arxiv_id=item.get("arxiv_id", ""),
        evidence_chunks=item.get("evidence_chunks"),
        evidence_text=item.get("evidence_text", item.get("evidence")),
        full_text=item.get("full_text", item.get("full_text_excerpt", item.get("full_text_excerpts"))),
        full_text_file=item.get(
            "full_text_file",
            item.get("full_text_files", item.get("full_text_excerpt_file", item.get("full_text_excerpt_files"))),
        ),
        tool=tool,
        index=index,
        citation_index=citation_index,
    )


def _parse_citation_fields(
    raw_text: str = "",
    title: str = "",
    authors: Optional[List[str]] = None,
    year: Optional[int] = None,
    venue: str = "",
    abstract: str = "",
    doi: str = "",
    arxiv_id: str = "",
    evidence_chunks: Any = None,
    evidence_text: Any = None,
    full_text: Any = None,
    full_text_file: Any = None,
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
):
    _validate_citation_scalar_fields(
        {
            "raw_text": raw_text,
            "title": title,
            "venue": venue,
            "abstract": abstract,
            "doi": doi,
            "arxiv_id": arxiv_id,
        },
        tool=tool,
        index=index,
        citation_index=citation_index,
    )
    return parse_citation(
        raw_text=raw_text,
        title=title,
        authors=_normalize_authors(authors, tool=tool, index=index, citation_index=citation_index),
        year=_normalize_year(year, tool=tool, index=index, citation_index=citation_index),
        venue=venue,
        abstract=abstract,
        doi=doi,
        arxiv_id=arxiv_id,
        evidence_chunks=_normalize_evidence_chunks(
            {
                "evidence_chunks": evidence_chunks,
                "evidence_text": evidence_text,
                "full_text": full_text,
                "full_text_file": full_text_file,
            },
            tool=tool,
            index=index,
            citation_index=citation_index,
        ),
    )


def _validate_citation_scalar_fields(
    item: Dict[str, Any],
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> None:
    for field in ["raw_text", "title", "venue", "abstract", "doi", "arxiv_id"]:
        value = item.get(field)
        if value is not None and not isinstance(value, str):
            raise MCPInputError(
                f"citation field {field!r} must be a string.",
                _input_details(tool=tool, index=index, field=field, citation_index=citation_index),
            )
        if isinstance(value, str) and len(value) > MAX_INLINE_EVIDENCE_CHARS:
            details = _input_details(tool=tool, index=index, field=field, citation_index=citation_index)
            details.update({"max_chars": MAX_INLINE_EVIDENCE_CHARS, "received_chars": len(value)})
            raise MCPInputError(f"citation field {field!r} exceeds the input size limit.", details)


def _normalize_authors(
    value: Any,
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> Optional[List[str]]:
    if value is None or value == "":
        return None
    if not isinstance(value, list) or any(not isinstance(author, str) for author in value):
        raise MCPInputError(
            "citation field 'authors' must be a list of strings.",
            _input_details(tool=tool, index=index, field="authors", citation_index=citation_index),
        )
    return value


def _normalize_year(
    value: Any,
    tool: str = "",
    index: Optional[int] = None,
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
        raise MCPInputError(
            "citation field 'year' must be an integer year.",
            _input_details(tool=tool, index=index, field="year", citation_index=citation_index),
        )
    return None


def _input_details(
    tool: str = "",
    index: Optional[int] = None,
    field: str = "",
    citation_index: Optional[int] = None,
) -> dict:
    details: Dict[str, Any] = {}
    if tool:
        details["tool"] = tool
    if index is not None:
        details["index"] = index
    if citation_index is not None:
        details["citation_index"] = citation_index
    if field:
        details["field"] = field
    return details


def _value_error_details(tool: str, exc: ValueError) -> dict:
    return runtime_config_error_details(str(exc), base={"tool": tool}, env=os.environ)


def _shape_details(
    tool: str,
    field: str,
    expected: str,
    received: Any,
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> dict:
    details = _input_details(tool=tool, index=index, field=field, citation_index=citation_index)
    details["expected"] = expected
    details["received"] = type(received).__name__
    return details


def _as_list(value: Any) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def _batch_limit_error(tool: str, field: str, received: int, index: Optional[int] = None) -> dict:
    details = _input_details(tool=tool, field=field, index=index)
    details.update({"max_items": MAX_BATCH_ITEMS, "received_items": received})
    return error_payload(
        "invalid_input",
        f"{field} exceeds the maximum batch size of {MAX_BATCH_ITEMS}.",
        details=details,
    )


def _chunk(text: str, source_field: str, evidence_scope: str, source_url: str = "") -> dict:
    return {
        "text": text,
        "source_field": source_field,
        "source_url": source_url,
        "evidence_scope": evidence_scope,
    }


def _normalize_evidence_chunks(
    item: Dict[str, Any],
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> list:
    chunks = []
    for chunk_index, value in enumerate(_as_list(item.get("evidence_chunks")), start=1):
        if isinstance(value, dict):
            chunks.append(dict(value))
        elif str(value).strip():
            chunks.append(_chunk(str(value), f"user_evidence_chunk_{chunk_index}", "metadata"))

    for chunk_index, value in enumerate(_as_list(item.get("evidence_text")), start=1):
        if isinstance(value, dict):
            chunk = dict(value)
            chunk.setdefault("source_field", f"user_evidence_text_{chunk_index}")
            chunk.setdefault("evidence_scope", "metadata")
            chunks.append(chunk)
        elif str(value).strip():
            chunks.append(_chunk(str(value), f"user_evidence_text_{chunk_index}", "metadata"))

    for chunk_index, value in enumerate(_as_list(item.get("full_text")), start=1):
        if isinstance(value, dict):
            chunk = dict(value)
            chunk.setdefault("source_field", f"user_full_text_excerpt_{chunk_index}")
            chunk["evidence_scope"] = "full_text"
            chunks.append(chunk)
        elif str(value).strip():
            chunks.append(_chunk(str(value), f"user_full_text_excerpt_{chunk_index}", "full_text"))
    for file_index, path in enumerate(_as_list(item.get("full_text_file")), start=1):
        if not isinstance(path, str):
            raise MCPInputError(
                "full-text excerpt file paths must be strings.",
                _input_details(tool=tool, index=index, field="full_text_file", citation_index=citation_index),
            )
        text = _read_evidence_file(path, tool=tool, index=index, citation_index=citation_index)
        if text.strip():
            chunks.append(_chunk(text, f"user_full_text_file_{file_index}", "full_text"))
    if len(chunks) > MAX_EVIDENCE_CHUNKS:
        details = _input_details(tool=tool, index=index, field="evidence_chunks", citation_index=citation_index)
        details.update({"max_items": MAX_EVIDENCE_CHUNKS, "received_items": len(chunks)})
        raise MCPInputError("evidence chunks exceed the input limit.", details)
    total_chars = sum(len(str(chunk.get("text", ""))) for chunk in chunks if isinstance(chunk, dict))
    if total_chars > MAX_INLINE_EVIDENCE_CHARS:
        details = _input_details(tool=tool, index=index, field="evidence_chunks", citation_index=citation_index)
        details.update({"max_chars": MAX_INLINE_EVIDENCE_CHARS, "received_chars": total_chars})
        raise MCPInputError("evidence text exceeds the input size limit.", details)
    return chunks


def _read_evidence_file(
    path: str,
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> str:
    safe_path = _validated_evidence_path(path, tool=tool, index=index, citation_index=citation_index)
    try:
        if safe_path.suffix.lower() == ".pdf":
            return _read_pdf_text(str(safe_path), tool=tool, index=index, citation_index=citation_index)
        return _read_text_file(str(safe_path), tool=tool, index=index, citation_index=citation_index)
    except MCPFileError as exc:
        exc.details["resolved_filename"] = str(safe_path)
        exc.details["filename"] = path
        raise


def _validated_evidence_path(
    path: str,
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> Path:
    candidate = Path(path).expanduser().resolve(strict=False)
    raw_roots = str(os.environ.get("CITEGUARD_ALLOWED_FILE_ROOTS", "")).strip()
    roots = [Path(item).expanduser().resolve() for item in raw_roots.split(os.pathsep) if item.strip()]
    if not roots:
        roots = [Path.cwd().resolve()]
    allowed = False
    for root in roots:
        try:
            if os.path.commonpath([str(candidate), str(root)]) == str(root):
                allowed = True
                break
        except ValueError:
            continue
    details = _input_details(tool=tool, index=index, field="full_text_file", citation_index=citation_index)
    details["filename"] = path
    details["allowed_roots"] = [str(root) for root in roots]
    if not allowed:
        details["errno"] = errno.EACCES
        raise MCPFileError(
            "Full-text evidence files must be inside CITEGUARD_ALLOWED_FILE_ROOTS or the server working directory.",
            details,
        )
    if candidate.suffix.lower() not in ALLOWED_EVIDENCE_SUFFIXES:
        details["allowed_suffixes"] = sorted(ALLOWED_EVIDENCE_SUFFIXES)
        raise MCPInputError("Unsupported full-text evidence file type.", details)
    try:
        size = candidate.stat().st_size
    except OSError:
        return candidate
    if size > MAX_EVIDENCE_FILE_BYTES:
        details.update({"errno": errno.EFBIG, "max_bytes": MAX_EVIDENCE_FILE_BYTES, "received_bytes": size})
        raise MCPFileError("Full-text evidence file exceeds the size limit.", details)
    return candidate


def _read_text_file(
    path: str,
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read(MAX_INLINE_EVIDENCE_CHARS + 1)
    except OSError as exc:
        details = _input_details(tool=tool, index=index, field="full_text_file", citation_index=citation_index)
        details["filename"] = path
        if getattr(exc, "errno", None) is not None:
            details["errno"] = getattr(exc, "errno")
        raise MCPFileError(f"Could not read full-text evidence file {path!r}: {exc}", details) from exc


def _read_pdf_text(
    path: str,
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> str:
    reader_cls = _load_pdf_reader(tool=tool, index=index, citation_index=citation_index)
    try:
        reader = reader_cls(path)
        pages = list(reader.pages)[:MAX_PDF_PAGES]
        text = "\n\n".join(page.extract_text() or "" for page in pages)
        return text[:MAX_INLINE_EVIDENCE_CHARS]
    except Exception as exc:
        details = _input_details(tool=tool, index=index, field="full_text_file", citation_index=citation_index)
        details.update({"filename": path, "format": "pdf"})
        raise MCPFileError(f"Could not extract text from PDF full-text file {path!r}: {exc}", details) from exc


def _load_pdf_reader(tool: str = "", index: Optional[int] = None, citation_index: Optional[int] = None):
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        reader = getattr(module, "PdfReader", None)
        if reader is not None:
            return reader
    details = _input_details(tool=tool, index=index, field="full_text_file", citation_index=citation_index)
    details.update({"format": "pdf", "dependency": "pypdf"})
    raise MCPInputError(
        "PDF full-text files require the optional pypdf package; install pypdf or provide a UTF-8 text excerpt file.",
        details,
    )
