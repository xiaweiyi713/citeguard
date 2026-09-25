"""Canonical, traceable evidence objects for public support results."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional


EVIDENCE_OBJECT_SCHEMA_VERSION = 1


def utc_now_iso() -> str:
    """Return a compact UTC timestamp for a CiteGuard retrieval event."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def local_file_evidence_provenance(path: str, text: str) -> Dict[str, Any]:
    """Return honest, local-file provenance for one extracted text fragment.

    Plain-text locators use the complete extracted line/character range. PDF
    extraction has no reliable source-page mapping in the standard-library path,
    so it is labelled as extracted text instead of manufacturing page numbers.
    """

    resolved_path = str(Path(path).expanduser().resolve(strict=False))
    if Path(resolved_path).suffix.lower() == ".pdf":
        return {
            "source_path": resolved_path,
            "source_locator": f"{resolved_path}#extracted-text",
            "char_start": 0,
            "char_end": len(text),
        }
    line_end = max(1, text.count("\n") + 1)
    locator = f"{resolved_path}#line-1" if line_end == 1 else f"{resolved_path}#lines-1-{line_end}"
    return {
        "source_path": resolved_path,
        "source_locator": locator,
        "source_line_start": 1,
        "source_line_end": line_end,
        "char_start": 0,
        "char_end": len(text),
    }


def build_evidence_object(span: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a versioned provenance object without altering legacy span fields.

    The hash covers the exact text returned in ``fragment.text``. Missing
    retrieval or rights metadata stays explicit as ``null``/``unknown`` rather
    than being inferred from the text or a source name.
    """

    text = str(span.get("text", ""))
    source_name = str(span.get("source_name", "") or _infer_source_name(span))
    source_url = str(span.get("source_url", "") or "")
    source_field = str(span.get("source_field", "") or "")
    source_path = str(span.get("source_path", "") or "")
    locator = _build_locator(span, source_url=source_url, source_field=source_field, source_path=source_path)
    retrieval_method = str(span.get("retrieval_method", span.get("retrieval_source", "")) or "")
    license_value = str(span.get("license", span.get("license_value", "")) or "")
    license_status = str(span.get("license_status", "") or "")
    rights_basis = str(span.get("rights_basis", "") or "")

    if not retrieval_method:
        retrieval_method = _infer_retrieval_method(source_name, source_field, source_url)
    if not license_status:
        license_status = _infer_license_status(source_name, source_field)
    if not rights_basis:
        rights_basis = _infer_rights_basis(source_name, source_field)

    return {
        "schema_version": EVIDENCE_OBJECT_SCHEMA_VERSION,
        "source": {
            "name": source_name,
            "url": source_url,
            "field": source_field,
            "path": source_path or None,
        },
        "fragment": {
            "text": text,
            "sha256": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
        },
        "locator": locator,
        "retrieval": {
            "method": retrieval_method,
            "retrieved_at": _optional_text(span.get("retrieved_at")),
        },
        "license": {
            "status": license_status,
            "value": license_value or None,
            "rights_basis": rights_basis,
        },
    }


def _build_locator(
    span: Mapping[str, Any],
    *,
    source_url: str,
    source_field: str,
    source_path: str,
) -> Dict[str, Any]:
    line_start = _optional_int(span.get("source_line_start", span.get("line_start")))
    line_end = _optional_int(span.get("source_line_end", span.get("line_end")))
    paragraph_start = _optional_int(span.get("source_paragraph_start", span.get("paragraph_start")))
    paragraph_end = _optional_int(span.get("source_paragraph_end", span.get("paragraph_end")))
    char_start = _optional_int(span.get("char_start"))
    char_end = _optional_int(span.get("char_end"))
    value = str(span.get("source_locator", span.get("locator", "")) or "")
    if not value:
        if source_path:
            value = _path_locator(source_path, line_start, line_end, paragraph_start, paragraph_end)
        elif source_url:
            value = f"{source_url}#{source_field}" if source_field else source_url
        else:
            value = source_field or "none"

    if paragraph_start is not None:
        kind = "paragraph_range"
    elif line_start is not None:
        kind = "line_range"
    elif char_start is not None:
        kind = "character_range"
    elif value == "none":
        kind = "none"
    elif source_path:
        kind = "file_fragment"
    elif source_url:
        kind = "url_fragment"
    else:
        kind = "source_field"
    return {
        "kind": kind,
        "value": value,
        "line_start": line_start,
        "line_end": line_end,
        "paragraph_start": paragraph_start,
        "paragraph_end": paragraph_end,
        "char_start": char_start,
        "char_end": char_end,
    }


def _path_locator(
    path: str,
    line_start: Optional[int],
    line_end: Optional[int],
    paragraph_start: Optional[int],
    paragraph_end: Optional[int],
) -> str:
    if paragraph_start is not None:
        if paragraph_end is not None and paragraph_end != paragraph_start:
            return f"{path}#paragraphs-{paragraph_start}-{paragraph_end}"
        return f"{path}#paragraph-{paragraph_start}"
    if line_start is not None:
        if line_end is not None and line_end != line_start:
            return f"{path}#lines-{line_start}-{line_end}"
        return f"{path}#line-{line_start}"
    return path


def _infer_source_name(span: Mapping[str, Any]) -> str:
    field = str(span.get("source_field", "") or "").lower()
    if not field or field == "none":
        return "none"
    if "user_" in field or field.startswith("user-provided"):
        return "user_provided"
    if field.startswith("oa_full_text"):
        return "open_access_full_text"
    if field.startswith("abstract") or field == "title":
        return "citation_metadata"
    return "unknown"


def _infer_retrieval_method(source_name: str, source_field: str, source_url: str) -> str:
    lowered = f"{source_name} {source_field}".lower()
    if source_name == "none":
        return "not_applicable"
    if "user" in lowered:
        return "user_provided"
    if "oa_full_text" in lowered or "open_access_full_text" in lowered:
        return "oa_fulltext_fetch"
    if source_url:
        return "remote_metadata"
    return "citation_metadata"


def _infer_license_status(source_name: str, source_field: str) -> str:
    lowered = f"{source_name} {source_field}".lower()
    if source_name == "none":
        return "not_applicable"
    if "user" in lowered:
        return "user_provided_not_verified"
    if "oa_full_text" in lowered or "open_access_full_text" in lowered:
        return "open_access_license_unknown"
    return "unknown"


def _infer_rights_basis(source_name: str, source_field: str) -> str:
    lowered = f"{source_name} {source_field}".lower()
    if source_name == "none":
        return "not_applicable"
    if "user" in lowered:
        return "user_provided"
    if "oa_full_text" in lowered or "open_access_full_text" in lowered:
        return "source_marked_open_access"
    return "unknown"


def _optional_int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_text(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


__all__ = [
    "EVIDENCE_OBJECT_SCHEMA_VERSION",
    "build_evidence_object",
    "local_file_evidence_provenance",
    "utc_now_iso",
]
