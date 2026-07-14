"""Aggregator over multiple scholarly metadata sources."""

from __future__ import annotations

import socket
from concurrent.futures import Future, ThreadPoolExecutor, wait
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from citeguard.citation import sequence_similarity, tokenize_text
from citeguard.graph import CitationRecord

from .base import MetadataSource
from .utils import merge_record_list, record_match_score


class MultiSourceMetadataSource(MetadataSource):
    """Aggregates several scholarly sources and deduplicates their outputs."""

    name = "multi_source"

    def __init__(self, sources: Iterable[MetadataSource], budget_seconds: float = 8.0) -> None:
        self.sources = list(sources)
        self.budget_seconds = max(0.1, float(budget_seconds))
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
        values = self._fan_out(lambda item: item.search(query, top_k=per_source))
        merged = [record for value in values if value for record in value]
        ranked = self._rank(query, merge_record_list(merged))
        return ranked[:top_k]

    def lookup(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        values = self._fan_out(lambda item: item.lookup(candidate))
        matches = [value for value in values if value is not None]
        if not matches:
            return None
        ranked = sorted(
            merge_record_list(matches),
            key=lambda record: record_match_score(candidate, record),
            reverse=True,
        )
        best = ranked[0]
        return best if record_match_score(candidate, best) >= 0.70 else None

    def _fan_out(self, call: Callable[[MetadataSource], Any]) -> List[Any]:
        """Run `call(source)` across all sources concurrently within the budget.

        Thread-safety contract: each source runs in exactly one worker thread and
        owns its HTTPClient, so per-source `last_*` state is single-threaded; the
        worker snapshots any failure detail immediately after the call, and all
        shared-state appends happen on the main thread afterwards. Sources that
        exceed the budget are recorded as `budget_exceeded` failures; their
        threads finish in the background (never joined) - acceptable for a
        long-lived server, and at worst one HTTP timeout for a CLI exit.
        """

        self.last_failures = []
        self.last_failure_details = []
        pool = ThreadPoolExecutor(max_workers=max(1, len(self.sources)))
        futures: List[Tuple[Future, MetadataSource]] = []
        values: List[Any] = []
        try:
            for source in self.sources:
                futures.append((pool.submit(self._probe, source, call), source))
            done, _ = wait([future for future, _ in futures], timeout=self.budget_seconds)
            for future, source in futures:
                if future in done:
                    value, detail = future.result()
                    if detail is not None:
                        self._append_failure_detail(detail)
                    values.append(value)
                else:
                    self._append_failure_detail({
                        "source": source.name,
                        "code": "budget_exceeded",
                        "kind": "timeout",
                        "status_code": None,
                        "url": "",
                        "error": f"source exceeded fan-out budget of {self.budget_seconds}s",
                    })
            return values
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _probe(
        source: MetadataSource, call: Callable[[MetadataSource], Any]
    ) -> Tuple[Any, Optional[Dict[str, Any]]]:
        try:
            value = call(source)
        except Exception as exc:
            return None, _source_failure_detail(source, exc)
        detail = _source_failure_detail(source)
        empty = value is None or value == []
        return value, (detail if (empty and detail.get("code")) else None)

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
