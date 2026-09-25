"""Bounded, suggestion-only citation audits for manuscript files."""

from __future__ import annotations

import hashlib
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, cast

from citeguard.retrieval.scholarly_clients.base import MetadataSource

from .audit import audit_citations
from .document_report import attach_manuscript_audit
from .extract import load_citation_candidates
from .models import (
    STABLE_NEXT_ACTIONS,
    Verdict,
    filter_high_risk_payload,
    review_summary_from_risk_ranking,
)
from .parse import parse_citation


DOCUMENT_AUDIT_SCHEMA_VERSION = 1
DOCUMENT_AUDIT_SNAPSHOT_SCHEMA_VERSION = 1
ALLOWED_DOCUMENT_SUFFIXES = frozenset({".md", ".markdown", ".tex", ".latex", ".bib", ".bbl", ".docx"})
ALLOWED_DOCUMENT_SOURCE_FORMATS = frozenset({"auto", "markdown", "md", "latex", "tex", "bibtex", "bbl", "docx"})
MAX_DOCUMENT_AUDIT_FILE_BYTES = 10 * 1024 * 1024
MAX_DOCUMENT_AUDIT_TOTAL_BYTES = 20 * 1024 * 1024
MAX_DOCUMENT_AUDIT_FILES = 32
MAX_DOCUMENT_AUDIT_CITATIONS = 100
MAX_DOCUMENT_AUDIT_DOCX_XML_BYTES = 5 * 1024 * 1024


class DocumentAuditError(ValueError):
    """A structured document-audit error suitable for CLI and MCP callers."""

    def __init__(self, code: str, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class BoundedDocumentReader:
    """Resolve only regular, supported document files within configured roots."""

    def __init__(
        self,
        allowed_roots: Sequence[str],
        *,
        max_file_bytes: int = MAX_DOCUMENT_AUDIT_FILE_BYTES,
        max_total_bytes: int = MAX_DOCUMENT_AUDIT_TOTAL_BYTES,
        max_files: int = MAX_DOCUMENT_AUDIT_FILES,
    ) -> None:
        self.allowed_roots = [Path(root).expanduser().resolve() for root in allowed_roots]
        self.max_file_bytes = max_file_bytes
        self.max_total_bytes = max_total_bytes
        self.max_files = max_files
        self._files: Dict[str, int] = {}
        self._digests: Dict[str, str] = {}
        self._read_kinds: Dict[str, str] = {}
        self._captured_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    def resolve(self, path: Path, *, require_exists: bool = True) -> Path:
        candidate = Path(path).expanduser().resolve(strict=False)
        details = {
            "field": "path",
            "filename": str(path),
            "resolved_filename": str(candidate),
            "allowed_roots": [str(root) for root in self.allowed_roots],
        }
        if not _is_within_any_root(candidate, self.allowed_roots):
            raise DocumentAuditError(
                "file_error",
                "Document paths must stay inside the configured document-audit roots.",
                details,
            )
        if candidate.suffix.lower() not in ALLOWED_DOCUMENT_SUFFIXES:
            raise DocumentAuditError(
                "invalid_input",
                "Unsupported document type for audit_document.",
                {**details, "allowed_suffixes": sorted(ALLOWED_DOCUMENT_SUFFIXES)},
            )
        if not candidate.exists():
            if not require_exists:
                return candidate
            raise DocumentAuditError("file_error", "Document path does not name a readable file.", details)
        if not candidate.is_file():
            raise DocumentAuditError("file_error", "Document path does not name a readable file.", details)
        try:
            size = candidate.stat().st_size
        except OSError as exc:
            raise DocumentAuditError("file_error", f"Could not inspect document file: {exc}", details) from exc
        key = str(candidate)
        if size > self.max_file_bytes:
            grew_during_audit = key in self._files and self._files[key] <= self.max_file_bytes
            raise DocumentAuditError(
                "file_error",
                (
                    "Document file grew beyond the per-file size limit during the audit."
                    if grew_during_audit
                    else "Document file exceeds the per-file size limit."
                ),
                {
                    **details,
                    "max_bytes": self.max_file_bytes,
                    "received_bytes": size,
                    **({"previous_bytes": self._files[key]} if grew_during_audit else {}),
                },
            )
        if key not in self._files:
            if len(self._files) >= self.max_files:
                raise DocumentAuditError(
                    "file_error",
                    "Document audit reached its included-file limit.",
                    {**details, "max_files": self.max_files},
                )
            total = sum(self._files.values()) + size
            if total > self.max_total_bytes:
                raise DocumentAuditError(
                    "file_error",
                    "Document audit reached its total file-size limit.",
                    {**details, "max_total_bytes": self.max_total_bytes, "received_total_bytes": total},
                )
            self._files[key] = size
        return candidate

    def resolve_dependency(self, path: Path) -> Path:
        """Resolve an in-root include reference while retaining missing-file diagnostics."""

        return self.resolve(path, require_exists=False)

    def read_text(self, path: Path) -> str:
        """Read one bounded UTF-8 file and retain its content fingerprint."""

        candidate = self.resolve(path)
        data = self._read_bytes(candidate)
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentAuditError(
                "file_error",
                "Document text files must be valid UTF-8.",
                {
                    "field": "path",
                    "filename": str(path),
                    "resolved_filename": str(candidate),
                    "encoding": "utf-8",
                    "byte_offset": exc.start,
                },
            ) from exc
        self._record_read(candidate, data, "text_utf8")
        return text

    def read_bytes(self, path: Path) -> bytes:
        """Read one bounded binary file and retain its content fingerprint."""

        candidate = self.resolve(path)
        data = self._read_bytes(candidate)
        self._record_read(candidate, data, "binary")
        return data

    def _read_bytes(self, candidate: Path) -> bytes:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(candidate, flags)
        except OSError as exc:
            raise DocumentAuditError(
                "file_error",
                f"Could not read document file: {exc}",
                {
                    "field": "path",
                    "filename": str(candidate),
                    "resolved_filename": str(candidate),
                },
            ) from exc
        try:
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode):
                raise DocumentAuditError(
                    "file_error",
                    "Document paths must name regular files.",
                    {
                        "field": "path",
                        "filename": str(candidate),
                        "resolved_filename": str(candidate),
                    },
                )
            if before.st_size > self.max_file_bytes:
                key = str(candidate)
                grew_during_audit = key in self._files and self._files[key] <= self.max_file_bytes
                raise DocumentAuditError(
                    "file_error",
                    (
                        "Document file grew beyond the per-file size limit during the audit."
                        if grew_during_audit
                        else "Document file exceeds the per-file size limit."
                    ),
                    {
                        "field": "path",
                        "filename": str(candidate),
                        "resolved_filename": str(candidate),
                        "max_bytes": self.max_file_bytes,
                        "received_bytes": before.st_size,
                        **({"previous_bytes": self._files[key]} if grew_during_audit else {}),
                    },
                )
            data = _read_limited_descriptor(descriptor, self.max_file_bytes + 1)
            after = os.fstat(descriptor)
        except OSError as exc:
            raise DocumentAuditError(
                "file_error",
                f"Could not read document file: {exc}",
                {
                    "field": "path",
                    "filename": str(candidate),
                    "resolved_filename": str(candidate),
                },
            ) from exc
        finally:
            os.close(descriptor)
        if len(data) > self.max_file_bytes:
            raise DocumentAuditError(
                "file_error",
                "Document file grew beyond the per-file size limit while being read.",
                {
                    "field": "path",
                    "filename": str(candidate),
                    "resolved_filename": str(candidate),
                    "max_bytes": self.max_file_bytes,
                    "received_bytes": len(data),
                },
            )
        if (
            after.st_size != len(data)
            or after.st_mtime_ns != before.st_mtime_ns
            or after.st_ctime_ns != before.st_ctime_ns
        ):
            raise DocumentAuditError(
                "file_error",
                "Document file changed while being read; re-run the audit on a stable file.",
                {
                    "field": "path",
                    "filename": str(candidate),
                    "resolved_filename": str(candidate),
                    "read_bytes": len(data),
                    "current_bytes": after.st_size,
                },
            )
        key = str(candidate)
        other_total = sum(size for item_path, size in self._files.items() if item_path != key)
        if other_total + len(data) > self.max_total_bytes:
            raise DocumentAuditError(
                "file_error",
                "Document audit exceeded its total file-size limit while reading.",
                {
                    "field": "path",
                    "filename": str(candidate),
                    "resolved_filename": str(candidate),
                    "max_total_bytes": self.max_total_bytes,
                    "received_total_bytes": other_total + len(data),
                },
            )
        self._files[key] = len(data)
        return data

    def _record_read(self, candidate: Path, data: bytes, kind: str) -> None:
        key = str(candidate)
        self._digests[key] = "sha256:" + hashlib.sha256(data).hexdigest()
        self._read_kinds[key] = kind

    def summary(self) -> Dict[str, Any]:
        return {
            "file_count": len(self._files),
            "total_bytes": sum(self._files.values()),
            "files_read": [
                {
                    "path": path,
                    "bytes": self._files[path],
                    "sha256": self._digests.get(path),
                    "read_kind": self._read_kinds.get(path),
                }
                for path in sorted(self._files)
            ],
            "limits": {
                "max_file_bytes": self.max_file_bytes,
                "max_total_bytes": self.max_total_bytes,
                "max_files": self.max_files,
                "max_docx_xml_bytes": MAX_DOCUMENT_AUDIT_DOCX_XML_BYTES,
            },
        }

    def snapshot(self) -> Dict[str, Any]:
        """Return a content-addressed snapshot of every file actually read."""

        files = []
        digest = hashlib.sha256()
        digest.update(f"citeguard-document-snapshot-v{DOCUMENT_AUDIT_SNAPSHOT_SCHEMA_VERSION}\0".encode("utf-8"))
        for path in sorted(self._files):
            file_digest = self._digests.get(path)
            read_kind = self._read_kinds.get(path)
            digest.update(path.encode("utf-8"))
            digest.update(b"\0")
            digest.update(str(self._files[path]).encode("ascii"))
            digest.update(b"\0")
            digest.update(str(file_digest or "unread").encode("ascii"))
            digest.update(b"\0")
            digest.update(str(read_kind or "unread").encode("ascii"))
            digest.update(b"\n")
            files.append(
                {
                    "path": path,
                    "bytes": self._files[path],
                    "sha256": file_digest,
                    "read_kind": read_kind,
                }
            )
        return {
            "schema_version": DOCUMENT_AUDIT_SNAPSHOT_SCHEMA_VERSION,
            "digest": "sha256:" + digest.hexdigest(),
            "captured_at": self._captured_at,
            "file_count": len(files),
            "files": files,
            "policy": "digest_covers_resolved_file_paths_sizes_content_hashes_and_read_modes",
        }


def configured_document_roots() -> List[str]:
    """Return server-controlled roots for the MCP document audit surface."""

    raw_roots = str(os.environ.get("CITEGUARD_ALLOWED_FILE_ROOTS", "")).strip()
    roots = [item for item in raw_roots.split(os.pathsep) if item.strip()]
    return roots or [str(Path.cwd())]


def audit_document(
    path: str,
    *,
    source: Optional[MetadataSource] = None,
    source_factory: Optional[Callable[[], MetadataSource]] = None,
    doi_registry: Any = None,
    doi_registry_factory: Optional[Callable[[], Any]] = None,
    source_format: str = "auto",
    allowed_roots: Optional[Sequence[str]] = None,
    max_workers: int = 4,
    high_risk_only: bool = False,
    support_backend: Any = None,
) -> Dict[str, Any]:
    """Extract and verify a bounded document without changing any user file."""

    active_format = str(source_format or "auto").lower()
    if active_format not in ALLOWED_DOCUMENT_SOURCE_FORMATS:
        raise DocumentAuditError(
            "invalid_input",
            "Unsupported source_format for audit_document.",
            {"field": "source_format", "allowed_values": sorted(ALLOWED_DOCUMENT_SOURCE_FORMATS)},
        )
    try:
        parsed_max_workers = int(max_workers)
    except (TypeError, ValueError) as exc:
        raise DocumentAuditError(
            "invalid_input",
            "max_workers must be an integer from 1 to 16.",
            {"field": "max_workers", "expected": "integer_1_to_16"},
        ) from exc
    if not 1 <= parsed_max_workers <= 16:
        raise DocumentAuditError(
            "invalid_input",
            "max_workers must be an integer from 1 to 16.",
            {"field": "max_workers", "expected": "integer_1_to_16"},
        )

    try:
        root_candidate = Path(path).expanduser().resolve(strict=False)
        roots = list(allowed_roots) if allowed_roots is not None else [str(root_candidate.parent)]
        reader = BoundedDocumentReader(roots)
        root_path = reader.resolve(root_candidate)
    except DocumentAuditError:
        raise
    except (OSError, RuntimeError) as exc:
        raise DocumentAuditError(
            "file_error",
            f"Could not resolve document path: {exc}",
            {"field": "path", "filename": path},
        ) from exc
    missing_dependencies: List[Dict[str, str]] = []
    seen_missing_dependencies = set()

    def record_missing_dependency(kind: str, dependency_path: Path) -> None:
        resolved = str(dependency_path.expanduser().resolve(strict=False))
        key = (str(kind), resolved)
        if key in seen_missing_dependencies:
            return
        seen_missing_dependencies.add(key)
        missing_dependencies.append({"kind": str(kind), "path": resolved})

    try:
        candidates = load_citation_candidates(
            str(root_path),
            source_format=active_format,
            path_resolver=reader.resolve_dependency,
            max_docx_xml_bytes=MAX_DOCUMENT_AUDIT_DOCX_XML_BYTES,
            text_reader=reader.read_text,
            binary_reader=reader.read_bytes,
            missing_dependency_handler=record_missing_dependency,
        )
    except DocumentAuditError:
        raise
    except (OSError, UnicodeError) as exc:
        raise DocumentAuditError(
            "file_error",
            f"Could not extract citation candidates from document: {exc}",
            {"field": "path", "filename": path, "resolved_filename": str(root_path)},
        ) from exc
    if len(candidates) > MAX_DOCUMENT_AUDIT_CITATIONS:
        raise DocumentAuditError(
            "invalid_input",
            "Document contains more citation candidates than this bounded audit can verify in one call.",
            {
                "field": "path",
                "candidate_count": len(candidates),
                "max_candidates": MAX_DOCUMENT_AUDIT_CITATIONS,
            },
        )

    normalized_candidates = [_document_candidate(candidate) for candidate in candidates]
    if normalized_candidates:
        active_source = source or (source_factory() if source_factory is not None else None)
        if active_source is None:
            raise DocumentAuditError(
                "invalid_input",
                "A metadata source is required when the document contains citation candidates.",
                {"field": "source"},
            )
        active_registry = doi_registry if doi_registry is not None else (
            doi_registry_factory() if doi_registry_factory is not None else None
        )
        full_audit = audit_citations(
            normalized_candidates,
            active_source,
            doi_registry=active_registry,
            max_workers=parsed_max_workers,
        ).to_dict()
    else:
        full_audit = _empty_audit_payload()

    audit_payload = filter_high_risk_payload(full_audit) if high_risk_only else full_audit
    review_queue = _review_queue(full_audit, candidates)
    snapshot = reader.snapshot()
    public_candidates = [_public_candidate(candidate) for candidate in candidates]
    payload = {
        "schema_version": DOCUMENT_AUDIT_SCHEMA_VERSION,
        "ok": True,
        "tool": "audit_document",
        "document": {
            "path": str(root_path),
            "source_format": active_format,
            "allowed_roots": [str(root) for root in reader.allowed_roots],
            "read": reader.summary(),
            "snapshot": snapshot,
            "dependencies": {
                "complete": not missing_dependencies,
                "missing": missing_dependencies,
            },
        },
        "extraction": {
            "candidate_count": len(candidates),
            "candidates": public_candidates,
        },
        "audit": audit_payload,
        "review_queue": review_queue,
        "review_queue_summary": {
            "count": len(review_queue),
            "high_risk_count": sum(item["risk"] == "high" for item in review_queue),
            "medium_risk_count": sum(item["risk"] == "medium" for item in review_queue),
            "requires_user_confirmation_count": len(review_queue),
            "auto_apply_allowed": False,
            "incomplete_dependency_count": len(missing_dependencies),
        },
        "review_status": _review_status(
            full_audit,
            review_queue,
            snapshot["digest"],
            incomplete=bool(missing_dependencies),
        ),
        "edit_policy": {
            "mode": "suggest_only",
            "document_modified": False,
            "automatic_apply_allowed": False,
            "user_confirmation_required_for_any_change": True,
        },
        "policy": (
            "reads_only_allowed_document_paths; verifies_extracted_citations; returns_locators_and_review_suggestions; "
            "does_not_modify_user_documents_or_treat_not_found_as_fabrication_evidence"
        ),
    }
    return attach_manuscript_audit(
        payload,
        _document_texts(reader, active_format),
        public_candidates,
        audit_results=full_audit["results"],
        support_backend=support_backend,
    )


def _document_texts(reader: BoundedDocumentReader, source_format: str) -> List[Dict[str, str]]:
    """Re-read already-captured document files for in-text citation linking."""

    texts: List[Dict[str, str]] = []
    for item in reader.summary().get("files_read", []):
        path = Path(str(item.get("path", "")))
        suffix = path.suffix.lower()
        if suffix == ".docx":
            continue
        if suffix == ".bib":
            fmt = "bibtex"
        elif suffix == ".bbl":
            fmt = "bbl"
        elif suffix in {".md", ".markdown"}:
            fmt = "markdown"
        elif suffix in {".tex", ".latex"}:
            fmt = "latex"
        else:
            fmt = source_format
        try:
            text = reader.read_text(path)
        except DocumentAuditError:
            continue
        texts.append({"path": str(path), "text": text, "source_format": fmt})
    return texts


def _document_candidate(candidate: Mapping[str, Any]):
    metadata = {
        "input_source_path": candidate.get("source_path", ""),
        "input_source_format": candidate.get("source_format", ""),
        "input_source_type": candidate.get("source_type", ""),
        "input_source_id": candidate.get("source_id", ""),
        "input_source_index": candidate.get("source_index"),
        "input_source_locator": candidate.get("source_locator", ""),
        "input_source_line_start": candidate.get("source_line_start"),
        "input_source_line_end": candidate.get("source_line_end"),
        "input_source_paragraph_start": candidate.get("source_paragraph_start"),
        "input_source_paragraph_end": candidate.get("source_paragraph_end"),
        "input_document_locator": _document_locator(candidate),
    }
    return parse_citation(
        raw_text=str(candidate.get("raw_text", "")),
        title=str(candidate.get("title", "")),
        authors=list(candidate.get("authors", []) or []),
        year=candidate.get("year") if isinstance(candidate.get("year"), int) else None,
        venue=str(candidate.get("venue", "")),
        doi=str(candidate.get("doi", "")),
        arxiv_id=str(candidate.get("arxiv_id", "")),
        metadata={key: value for key, value in metadata.items() if value not in (None, "")},
    )


def _public_candidate(candidate: Mapping[str, Any]) -> Dict[str, Any]:
    item = dict(candidate)
    item["document_locator"] = _document_locator(candidate)
    return item


def _document_locator(candidate: Mapping[str, Any]) -> str:
    path = str(candidate.get("source_path", "")).strip()
    paragraph_start = candidate.get("source_paragraph_start")
    paragraph_end = candidate.get("source_paragraph_end")
    line_start = candidate.get("source_line_start")
    line_end = candidate.get("source_line_end")
    if isinstance(paragraph_start, int):
        suffix = _range_suffix("paragraph", paragraph_start, paragraph_end)
    elif isinstance(line_start, int):
        suffix = _range_suffix("line", line_start, line_end)
    else:
        suffix = str(candidate.get("source_locator", "citation")).rsplit("#", 1)[-1]
    return f"{path}#{suffix}" if path else suffix


def _range_suffix(label: str, start: int, end: Any) -> str:
    if isinstance(end, int) and end != start:
        return f"{label}s-{start}-{end}"
    return f"{label}-{start}"


def _review_queue(audit_payload: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    queue: List[Dict[str, Any]] = []
    for item in audit_payload.get("risk_ranking", []):
        if not isinstance(item, Mapping) or item.get("risk") not in {"high", "medium"}:
            continue
        index = item.get("index")
        candidate = candidates[index] if isinstance(index, int) and 0 <= index < len(candidates) else {}
        suggested_fix = item.get("suggested_fix") if isinstance(item.get("suggested_fix"), Mapping) else {}
        queue.append(
            {
                "rank": len(queue) + 1,
                "index": index,
                "risk": item.get("risk"),
                "risk_score": item.get("risk_score"),
                "next_action": item.get("next_action"),
                "locator": _document_locator(candidate),
                "position": {
                    "path": candidate.get("source_path", ""),
                    "line_start": candidate.get("source_line_start"),
                    "line_end": candidate.get("source_line_end"),
                    "paragraph_start": candidate.get("source_paragraph_start"),
                    "paragraph_end": candidate.get("source_paragraph_end"),
                },
                "suggested_fix": dict(cast(Mapping[str, Any], suggested_fix)),
                "requires_user_confirmation": True,
                "automatic_apply_allowed": False,
            }
        )
    return queue


def _review_status(
    audit_payload: Mapping[str, Any],
    review_queue: Sequence[Mapping[str, Any]],
    snapshot_digest: str,
    *,
    incomplete: bool = False,
) -> Dict[str, Any]:
    """Expose one stable branch point for agents consuming a document audit."""

    review_required = bool(review_queue) or incomplete
    next_action = "continue"
    if incomplete:
        next_action = "repair_input"
    review_summary = audit_payload.get("review_summary")
    if not incomplete and isinstance(review_summary, Mapping):
        triage_plan = review_summary.get("triage_plan")
        if isinstance(triage_plan, Mapping):
            candidate_action = str(triage_plan.get("next_action", "")).strip()
            if candidate_action in STABLE_NEXT_ACTIONS:
                next_action = candidate_action
    if review_queue and next_action == "continue":
        candidate_action = str(review_queue[0].get("next_action", "")).strip()
        if candidate_action in STABLE_NEXT_ACTIONS:
            next_action = candidate_action
    return {
        "state": "review_required" if review_required else "clear",
        "review_required": review_required,
        "next_action": next_action,
        "queue_count": len(review_queue),
        "incomplete": incomplete,
        "snapshot_digest": snapshot_digest,
        "policy": "queue_is_derived_from_this_document_snapshot_and_must_be_rechecked_after_file_changes",
    }


def _empty_audit_payload() -> Dict[str, Any]:
    risk_ranking: List[Dict[str, Any]] = []
    return {
        "summary": {verdict.value: 0 for verdict in Verdict},
        "review_summary": review_summary_from_risk_ranking(0, risk_ranking),
        "risk_ranking": risk_ranking,
        "results": [],
        "batch_execution": {
            "schema_version": 1,
            "status": "complete",
            "progress": {"completed_items": 0, "total_items": 0, "fraction": 1.0},
            "max_workers": 0,
            "input_order_preserved": True,
            "source_requests_serialized_per_adapter": True,
            "streaming": False,
            "chunking": {"recommended_chunk_size": 100, "next_offset": None},
        },
    }


def _is_within_any_root(candidate: Path, roots: Iterable[Path]) -> bool:
    for root in roots:
        try:
            if os.path.commonpath([str(candidate), str(root)]) == str(root):
                return True
        except ValueError:
            continue
    return False


def _read_limited_descriptor(descriptor: int, limit: int) -> bytes:
    """Read at most `limit` bytes from one already-validated file descriptor."""

    chunks: List[bytes] = []
    remaining = limit
    while remaining > 0:
        chunk = os.read(descriptor, min(64 * 1024, remaining))
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
