"""Evidence chunk harvesting utilities for live scholarly adapters."""

from __future__ import annotations

import html
import re
import socket
import urllib.error
from html.parser import HTMLParser
from typing import Dict, Iterable, List, Sequence
from urllib.parse import urlparse

from .http import HTTPClient

BLOCKED_EVIDENCE_HOST_SUFFIXES = (
    "cnki.net",
    "cnki.com.cn",
    "wanfangdata.com.cn",
    "wanfangdata.com",
    "cqvip.com",
)


class _HTMLChunkParser(HTMLParser):
    """Minimal HTML parser that collects meta descriptions, headings, and paragraphs."""

    def __init__(self) -> None:
        super().__init__()
        self.meta_texts: List[str] = []
        self.headings: List[str] = []
        self.paragraphs: List[str] = []
        self._ignored_depth = 0
        self._capture_target = ""
        self._buffer: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "svg", "noscript"}:
            self._ignored_depth += 1
            return
        if lowered == "meta":
            values = {key.lower(): value for key, value in attrs if key and value}
            descriptor = " ".join(
                value.lower()
                for value in [values.get("name", ""), values.get("property", "")]
                if value
            )
            content = _clean_text(values.get("content", ""))
            if content and any(
                token in descriptor
                for token in ["description", "abstract", "summary", "citation_", "dc.description"]
            ):
                self.meta_texts.append(content)
            return
        if self._ignored_depth:
            return
        if lowered in {"p", "li", "blockquote"}:
            self._capture_target = "paragraphs"
            self._buffer = []
        elif lowered in {"h1", "h2", "h3"}:
            self._capture_target = "headings"
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        lowered = tag.lower()
        if lowered in {"script", "style", "svg", "noscript"} and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth or not self._capture_target:
            return
        if lowered in {"p", "li", "blockquote", "h1", "h2", "h3"}:
            text = _clean_text("".join(self._buffer))
            if text:
                getattr(self, self._capture_target).append(text)
            self._capture_target = ""
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._ignored_depth or not self._capture_target:
            return
        self._buffer.append(data)


def attach_evidence_chunks(metadata: Dict[str, object], chunks: Iterable[dict]) -> Dict[str, object]:
    """Attach structured evidence chunks and a backward-compatible string list."""

    merged_chunks = merge_evidence_chunks(metadata.get("evidence_chunks", []), chunks)
    if not merged_chunks:
        return metadata
    enriched = dict(metadata)
    enriched["evidence_chunks"] = merged_chunks
    enriched["evidence_spans"] = [chunk["text"] for chunk in merged_chunks]
    return enriched


def build_text_evidence_chunks(
    text: str,
    source_field_prefix: str,
    source_url: str = "",
    max_chunks: int = 4,
    max_words: int = 80,
) -> List[dict]:
    """Split a text block into support-verifier friendly evidence windows."""

    cleaned = _clean_text(text)
    if not cleaned:
        return []

    windows: List[str] = []
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    current: List[str] = []
    current_words = 0
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        words = sentence.split()
        if not words:
            continue
        if len(words) > max_words:
            if current:
                windows.append(" ".join(current))
                current = []
                current_words = 0
            for start in range(0, len(words), max_words):
                windows.append(" ".join(words[start : start + max_words]))
            continue
        if current and current_words + len(words) > max_words:
            windows.append(" ".join(current))
            current = []
            current_words = 0
        current.append(sentence)
        current_words += len(words)
    if current:
        windows.append(" ".join(current))
    if cleaned not in windows:
        windows.append(cleaned)

    chunks = []
    for index, window in enumerate(windows[:max_chunks], start=1):
        chunks.append(
            {
                "text": window,
                "source_field": f"{source_field_prefix}_{index}",
                "source_url": source_url,
            }
        )
    return merge_evidence_chunks(chunks)


def extract_html_evidence_chunks(
    html_text: str,
    source_field_prefix: str,
    source_url: str = "",
    max_chunks: int = 6,
) -> List[dict]:
    """Extract paragraph-level evidence chunks from a landing page HTML payload."""

    parser = _HTMLChunkParser()
    try:
        parser.feed(html_text)
    except Exception:
        return []

    harvested: List[dict] = []
    for index, text in enumerate(parser.meta_texts[:2], start=1):
        harvested.extend(
            build_text_evidence_chunks(
                text,
                source_field_prefix=f"{source_field_prefix}_meta_{index}",
                source_url=source_url,
                max_chunks=1,
            )
        )
    for index, text in enumerate(parser.headings[:2], start=1):
        harvested.extend(
            build_text_evidence_chunks(
                text,
                source_field_prefix=f"{source_field_prefix}_heading_{index}",
                source_url=source_url,
                max_chunks=1,
                max_words=24,
            )
        )
    for index, text in enumerate(parser.paragraphs, start=1):
        if len(harvested) >= max_chunks:
            break
        harvested.extend(
            build_text_evidence_chunks(
                text,
                source_field_prefix=f"{source_field_prefix}_paragraph_{index}",
                source_url=source_url,
                max_chunks=1,
            )
        )
    return merge_evidence_chunks(harvested)[:max_chunks]


def harvest_remote_evidence(
    http_client: HTTPClient,
    urls: Sequence[str],
    source_name: str,
    max_chunks: int = 6,
    timeout: int = 4,
) -> List[dict]:
    """Best-effort fetch of live landing pages to obtain real evidence chunks."""

    return harvest_remote_evidence_report(
        http_client,
        urls=urls,
        source_name=source_name,
        max_chunks=max_chunks,
        timeout=timeout,
    )["chunks"]


def harvest_remote_evidence_report(
    http_client: HTTPClient,
    urls: Sequence[str],
    source_name: str,
    max_chunks: int = 6,
    timeout: int = 4,
) -> Dict[str, List[dict]]:
    """Fetch remote evidence chunks and return non-fatal fetch diagnostics."""

    harvested: List[dict] = []
    failures: List[dict] = []
    for index, url in enumerate(_unique_urls(urls), start=1):
        if len(harvested) >= max_chunks:
            break
        if not is_allowed_remote_evidence_url(url):
            continue
        try:
            payload = http_client.get_text(url, timeout=timeout)
        except Exception as exc:
            failures.append(_remote_evidence_exception_detail(source_name, url, exc))
            continue
        if not payload or "<html" not in payload.lower():
            detail = _remote_evidence_http_detail(http_client, source_name, url)
            if detail:
                failures.append(detail)
            continue
        harvested.extend(
            extract_html_evidence_chunks(
                payload,
                source_field_prefix=f"{source_name}_remote_{index}",
                source_url=url,
                max_chunks=max_chunks - len(harvested),
            )
        )
    return {
        "chunks": merge_evidence_chunks(harvested)[:max_chunks],
        "failures": _dedupe_failure_details(failures),
    }


def is_allowed_remote_evidence_url(url: str) -> bool:
    """Return whether a URL is eligible for best-effort remote evidence fetching."""

    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    hostname = (parsed.hostname or "").lower().strip(".")
    if not hostname:
        return False
    return not any(
        hostname == suffix or hostname.endswith(f".{suffix}")
        for suffix in BLOCKED_EVIDENCE_HOST_SUFFIXES
    )


def merge_evidence_chunks(*collections: Iterable[dict]) -> List[dict]:
    """Merge evidence chunks while deduplicating semantically identical text."""

    merged: List[dict] = []
    text_to_index: Dict[str, int] = {}
    for collection in collections:
        for item in collection or []:
            if not isinstance(item, dict):
                text = _clean_text(str(item))
                candidate = {"text": text, "source_field": "metadata_span", "source_url": ""}
            else:
                text = _clean_text(str(item.get("text", "")))
                candidate = {
                    "text": text,
                    "source_field": str(item.get("source_field", "metadata_span")),
                    "source_url": str(item.get("source_url", "")),
                }
            if not text:
                continue
            key = text.lower()
            if key in text_to_index:
                existing = merged[text_to_index[key]]
                if not existing.get("source_url") and candidate.get("source_url"):
                    merged[text_to_index[key]] = candidate
                continue
            text_to_index[key] = len(merged)
            merged.append(candidate)
    return merged


def _clean_text(text: str) -> str:
    normalized = html.unescape(text or "")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _unique_urls(urls: Sequence[str]) -> List[str]:
    seen = set()
    ordered: List[str] = []
    for url in urls:
        cleaned = _clean_text(url)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _remote_evidence_http_detail(http_client: HTTPClient, source_name: str, url: str) -> dict:
    code = str(getattr(http_client, "last_error_code", "") or "")
    if not code:
        return {}
    return {
        "source": source_name,
        "stage": "remote_evidence",
        "code": code,
        "kind": str(getattr(http_client, "last_error_kind", "") or ""),
        "status_code": getattr(http_client, "last_status_code", None),
        "url": str(getattr(http_client, "last_url", "") or url),
        "error": str(getattr(http_client, "last_error", "") or ""),
        "cache_hit": bool(getattr(http_client, "last_cache_hit", False)),
    }


def _remote_evidence_exception_detail(source_name: str, url: str, exc: Exception) -> dict:
    code = "timeout" if _is_timeout_exception(exc) else "source_unavailable"
    kind = "timeout" if code == "timeout" else "exception"
    return {
        "source": source_name,
        "stage": "remote_evidence",
        "code": code,
        "kind": kind,
        "status_code": None,
        "url": url,
        "error": exc.__class__.__name__,
        "cache_hit": False,
    }


def _is_timeout_exception(exc: Exception) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    if isinstance(exc, urllib.error.URLError):
        return isinstance(getattr(exc, "reason", None), (TimeoutError, socket.timeout))
    return False


def _dedupe_failure_details(failures: Iterable[dict]) -> List[dict]:
    deduped: List[dict] = []
    seen = set()
    for failure in failures:
        key = (
            failure.get("stage"),
            failure.get("code"),
            failure.get("kind"),
            failure.get("status_code"),
            failure.get("url"),
            failure.get("error"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(failure)
    return deduped
