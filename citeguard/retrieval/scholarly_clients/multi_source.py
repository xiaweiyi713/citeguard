"""Aggregator over multiple scholarly metadata sources."""

from __future__ import annotations

import socket
from typing import Any, Dict, Iterable, List, Optional

from citeguard.citation import sequence_similarity, tokenize_text
from citeguard.graph import CitationRecord

from .base import MetadataSource
from .utils import merge_record_list, record_match_score


class MultiSourceMetadataSource(MetadataSource):
    """Aggregates several scholarly sources and deduplicates their outputs."""

    name = "multi_source"

    def __init__(self, sources: Iterable[MetadataSource]) -> None:
        self.sources = list(sources)
        self.last_failures: List[str] = []
        self.last_failure_details: List[Dict[str, Any]] = []

    def all_records(self) -> List[CitationRecord]:
        return merge_record_list(
            record
            for source in self.sources
            for record in source.all_records()
        )

    def search(self, query: str, top_k: int = 5) -> List[CitationRecord]:
        per_source = max(top_k, 3)
        merged: List[CitationRecord] = []
        self.last_failures = []
        self.last_failure_details = []
        for source in self.sources:
            try:
                records = source.search(query, top_k=per_source)
            except Exception as exc:
                self._record_failure(source, exc)
                continue
            if not records:
                self._record_http_failure_if_present(source)
            merged.extend(records)
        ranked = self._rank(query, merge_record_list(merged))
        return ranked[:top_k]

    def lookup(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        matches = []
        self.last_failures = []
        self.last_failure_details = []
        for source in self.sources:
            try:
                match = source.lookup(candidate)
            except Exception as exc:
                self._record_failure(source, exc)
                continue
            if match is not None:
                matches.append(match)
            else:
                self._record_http_failure_if_present(source)
        if not matches:
            return None
        ranked = sorted(
            merge_record_list(matches),
            key=lambda record: record_match_score(candidate, record),
            reverse=True,
        )
        best = ranked[0]
        return best if record_match_score(candidate, best) >= 0.70 else None

    def _record_failure(self, source: MetadataSource, exc: Exception) -> None:
        detail = _source_failure_detail(source, exc)
        self._append_failure_detail(detail)

    def _record_http_failure_if_present(self, source: MetadataSource) -> None:
        detail = _source_failure_detail(source)
        if detail.get("code"):
            self._append_failure_detail(detail)

    def _append_failure_detail(self, detail: Dict[str, Any]) -> None:
        source_name = str(detail.get("source", ""))
        if source_name and source_name not in self.last_failures:
            self.last_failures.append(source_name)
        if detail not in self.last_failure_details:
            self.last_failure_details.append(detail)

    def _rank(self, query: str, records: List[CitationRecord]) -> List[CitationRecord]:
        query_tokens = set(tokenize_text(query))

        def score(record: CitationRecord) -> float:
            title_similarity = sequence_similarity(query, record.title)
            overlap = len(query_tokens & set(tokenize_text(f"{record.title} {record.abstract}")))
            normalized_overlap = overlap / max(len(query_tokens), 1)
            raw_source_score = float(record.metadata.get("source_score", 0.0))
            # Raw relevance scores are source-specific and unbounded (OpenAlex
            # returns values in the thousands); squash to 0-1 so this term
            # cannot dominate title similarity and completeness.
            source_score = raw_source_score / (raw_source_score + 50.0) if raw_source_score > 0 else 0.0
            completeness = min(1.0, sum(bool(value) for value in [
                record.authors,
                record.year,
                record.venue,
                record.abstract,
                record.doi,
                record.url,
            ]) / 6.0)
            return 0.35 * normalized_overlap + 0.30 * title_similarity + 0.20 * source_score + 0.15 * completeness

        return sorted(records, key=score, reverse=True)


def _source_failure_detail(source: MetadataSource, exc: Optional[Exception] = None) -> Dict[str, Any]:
    http_client = getattr(source, "http_client", None)
    code = getattr(http_client, "last_error_code", "") if http_client is not None else ""
    kind = getattr(http_client, "last_error_kind", "") if http_client is not None else ""
    error = getattr(http_client, "last_error", "") if http_client is not None else ""
    status_code = getattr(http_client, "last_status_code", None) if http_client is not None else None
    url = getattr(http_client, "last_url", "") if http_client is not None else ""
    final_url = getattr(http_client, "last_final_url", "") if http_client is not None else ""
    redirected = bool(getattr(http_client, "last_redirected", False)) if http_client is not None else False
    cache_hit = bool(getattr(http_client, "last_cache_hit", False)) if http_client is not None else False
    attempt_count = int(getattr(http_client, "last_attempt_count", 0) or 0) if http_client is not None else 0
    retry_count = int(getattr(http_client, "last_retry_count", 0) or 0) if http_client is not None else 0
    retry_after_seconds = getattr(http_client, "last_retry_after_seconds", None) if http_client is not None else None
    retry_delay_seconds = getattr(http_client, "last_retry_delay_seconds", None) if http_client is not None else None

    if exc is not None and not code:
        code, kind = _classify_source_exception(exc)
        error = exc.__class__.__name__

    return {
        "source": source.name,
        "code": code,
        "kind": kind,
        "status_code": status_code,
        "url": url,
        "final_url": final_url,
        "redirected": redirected,
        "error": error,
        "cache_hit": cache_hit,
        "attempt_count": attempt_count,
        "retry_count": retry_count,
        "retry_after_seconds": retry_after_seconds,
        "retry_delay_seconds": retry_delay_seconds,
    }


def _classify_source_exception(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout", "timeout"
    return "source_unavailable", "exception"
