"""Open-access full-text fetching for claim-support evidence.

Fetches the body text of a resolved paper ONLY when the source marks it as
open access (OpenAlex `best_oa_location`). Gated hosts stay blocked, paywalls
are never bypassed, and the fetcher is disabled by default — the runtime only
builds it when `CITEGUARD_OA_FULLTEXT` is enabled. Fetched text is attached to
the record as `full_text`-scoped evidence chunks so the existing support
pipeline can judge claims against the paper body instead of the abstract only.
"""

from __future__ import annotations

import io
import urllib.request
from dataclasses import replace
from typing import Any, Dict, Optional, Tuple

from citeguard.graph import CitationRecord

from .evidence import (
    attach_evidence_chunks,
    build_text_evidence_chunks,
    extract_html_evidence_chunks,
    is_allowed_remote_evidence_url,
)
from .http import DEFAULT_HTTP_USER_AGENT

FETCHED = "fetched"
SKIPPED_NOT_OA = "skipped_not_open_access"
SKIPPED_NO_URL = "skipped_no_oa_url"
SKIPPED_BLOCKED_URL = "skipped_blocked_url"
PDF_DEPENDENCY_MISSING = "pdf_dependency_missing"
UNAVAILABLE = "unavailable"

_MAX_PDF_PAGES = 80


class OaFulltextFetcher:
    """Attach open-access full-text evidence chunks to a resolved record."""

    source_name = "openalex_oa"

    def __init__(
        self,
        timeout: int = 10,
        max_bytes: int = 10 * 1024 * 1024,
        max_chunks: int = 60,
        user_agent: str = "",
    ) -> None:
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.max_chunks = max_chunks
        self.user_agent = user_agent or DEFAULT_HTTP_USER_AGENT

    def attach(self, record: CitationRecord) -> CitationRecord:
        """Return the record, with OA full-text chunks attached when possible.

        Never raises: any failure is recorded as `metadata.oa_fulltext` with a
        conservative status so a fetch problem can not change a verdict.
        """

        report = self._fetch_report(record)
        metadata = dict(record.metadata)
        metadata["oa_fulltext"] = {
            key: value for key, value in report.items() if key != "chunks"
        }
        chunks = report.get("chunks") or []
        if chunks:
            metadata = attach_evidence_chunks(metadata, chunks)
        return replace(record, metadata=metadata)

    def _fetch_report(self, record: CitationRecord) -> Dict[str, Any]:
        open_access = record.metadata.get("open_access")
        if not isinstance(open_access, dict) or not open_access.get("is_oa"):
            return {"status": SKIPPED_NOT_OA}
        pdf_urls = [str(open_access.get("pdf_url") or "")]
        # arXiv papers are always open access; the official PDF is a reliable
        # fallback when a source's best_oa_location points at a flaky mirror.
        if record.arxiv_id:
            pdf_urls.append(f"https://arxiv.org/pdf/{record.arxiv_id}")
        pdf_urls = [url for url in dict.fromkeys(pdf_urls) if url]
        landing_url = str(open_access.get("landing_page_url") or "")
        if not pdf_urls and not landing_url:
            return {"status": SKIPPED_NO_URL}

        detail = ""
        for pdf_url in pdf_urls:
            if not is_allowed_remote_evidence_url(pdf_url):
                detail = detail or "blocked_url"
                continue
            payload, fetch_detail = self._fetch_bytes(pdf_url)
            if payload is None:
                detail = detail or fetch_detail
                continue
            text = _extract_pdf_text(payload)
            if text is None:
                detail = "pypdf_not_installed"
                break
            if text.strip():
                return self._chunk_report(text, pdf_url, content_type="pdf")
            detail = detail or "pdf_had_no_extractable_text"

        if landing_url:
            if not is_allowed_remote_evidence_url(landing_url):
                return {"status": SKIPPED_BLOCKED_URL, "source_url": landing_url, "detail": detail}
            payload, fetch_detail = self._fetch_bytes(landing_url)
            if payload is not None:
                html_text = payload.decode("utf-8", errors="replace")
                chunks = extract_html_evidence_chunks(
                    html_text,
                    "oa_full_text",
                    source_url=landing_url,
                    source_name=self.source_name,
                    max_chunks=self.max_chunks,
                )
                if chunks:
                    return {
                        "status": FETCHED,
                        "source_url": landing_url,
                        "content_type": "html",
                        "chunk_count": len(chunks),
                        "chunks": chunks,
                    }
                detail = detail or "no_extractable_text"
            else:
                detail = detail or fetch_detail

        if detail == "blocked_url":
            return {
                "status": SKIPPED_BLOCKED_URL,
                "source_url": pdf_urls[0] if pdf_urls else landing_url,
            }
        if detail == "pypdf_not_installed":
            return {
                "status": PDF_DEPENDENCY_MISSING,
                "source_url": pdf_urls[0] if pdf_urls else "",
                "detail": 'install the optional [pdf] extra: pip install "citationguard[pdf]"',
            }
        return {
            "status": UNAVAILABLE,
            "source_url": (pdf_urls[0] if pdf_urls else landing_url),
            "detail": detail or "fetch_failed",
        }

    def _chunk_report(self, text: str, source_url: str, content_type: str) -> Dict[str, Any]:
        chunks = build_text_evidence_chunks(
            text,
            "oa_full_text",
            source_url=source_url,
            source_name=self.source_name,
            max_chunks=self.max_chunks,
            max_words=90,
        )
        if not chunks:
            return {"status": UNAVAILABLE, "source_url": source_url, "detail": "no_extractable_text"}
        return {
            "status": FETCHED,
            "source_url": source_url,
            "content_type": content_type,
            "chunk_count": len(chunks),
            "chunks": chunks,
        }

    def _fetch_bytes(self, url: str) -> Tuple[Optional[bytes], str]:
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # nosec B310
                payload = response.read(self.max_bytes + 1)
        except Exception as exc:
            return None, exc.__class__.__name__
        if len(payload) > self.max_bytes:
            payload = payload[: self.max_bytes]
        return payload, ""


def _extract_pdf_text(payload: bytes) -> Optional[str]:
    """Extract text from PDF bytes; None when no PDF dependency is installed."""

    reader_cls = None
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = __import__(module_name)
        except ImportError:
            continue
        reader_cls = getattr(module, "PdfReader", None)
        if reader_cls is not None:
            break
    if reader_cls is None:
        return None
    try:
        reader = reader_cls(io.BytesIO(payload))
        pages = list(getattr(reader, "pages", []))[:_MAX_PDF_PAGES]
        return "\n".join((page.extract_text() or "") for page in pages)
    except Exception:
        return ""
