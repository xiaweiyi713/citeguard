"""Aggregator over multiple scholarly metadata sources."""

from __future__ import annotations

import socket
import queue
import threading
from concurrent.futures import Future, wait
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from citeguard.citation import sequence_similarity, tokenize_text
from citeguard.graph import CitationRecord

from .base import MetadataSource
from .utils import merge_record_list, record_match_score


class _SourceWorker:
    """One daemon worker per adapter with a bounded request queue."""

    def __init__(self, source: MetadataSource) -> None:
        self.source = source
        self._queue: queue.Queue[Tuple[Callable[[MetadataSource], Any], Future]] = queue.Queue(maxsize=100)
        self._thread = threading.Thread(
            target=self._run,
            name=f"citeguard-source-{getattr(source, 'name', 'unknown')}",
            daemon=True,
        )
        self._thread.start()

    def submit(self, call: Callable[[MetadataSource], Any]) -> Optional[Future]:
        future: Future = Future()
        try:
            self._queue.put_nowait((call, future))
        except queue.Full:
            return None
        return future

    def _run(self) -> None:
        while True:
            call, future = self._queue.get()
            if future.set_running_or_notify_cancel():
                try:
                    future.set_result(MultiSourceMetadataSource._probe(self.source, call))
                except BaseException as exc:  # pragma: no cover - _probe normally contains adapter errors
                    future.set_exception(exc)
            self._queue.task_done()


class MultiSourceMetadataSource(MetadataSource):
    """Aggregates several scholarly sources and deduplicates their outputs."""

    name = "multi_source"

    def __init__(self, sources: Iterable[MetadataSource], budget_seconds: float = 8.0) -> None:
        self.sources = list(sources)
        self.budget_seconds = max(0.1, float(budget_seconds))
        self._local = threading.local()
        self._workers = [_SourceWorker(source) for source in self.sources]

    @property
    def last_failures(self) -> List[str]:
        return getattr(self._local, "last_failures", [])

    @last_failures.setter
    def last_failures(self, value: List[str]) -> None:
        self._local.last_failures = value

    @property
    def last_failure_details(self) -> List[Dict[str, Any]]:
        return getattr(self._local, "last_failure_details", [])

    @last_failure_details.setter
    def last_failure_details(self, value: List[Dict[str, Any]]) -> None:
        self._local.last_failure_details = value

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

    def lookup_identifier(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        authority = "arxiv" if candidate.arxiv_id else "crossref" if candidate.doi else ""
        pair = next(
            ((worker, item) for worker, item in zip(self._workers, self.sources) if item.name == authority),
            None,
        )
        self.last_failures = []
        self.last_failure_details = []
        if pair is None:
            return None
        worker, source = pair
        values = self._collect_workers(
            [(worker, source)],
            lambda item: item.lookup_identifier(candidate),
        )
        return values[0] if values else None

    def _fan_out(self, call: Callable[[MetadataSource], Any]) -> List[Any]:
        """Run `call(source)` across all sources concurrently within the budget.

        Each adapter owns one persistent daemon worker. Calls from concurrent
        batch items queue behind that worker, so adapters are never overlapped.
        """
        self.last_failures = []
        self.last_failure_details = []
        return self._collect_workers(list(zip(self._workers, self.sources)), call)

    def _collect_workers(
        self,
        workers: List[Tuple[_SourceWorker, MetadataSource]],
        call: Callable[[MetadataSource], Any],
    ) -> List[Any]:
        futures: List[Tuple[Future, MetadataSource]] = []
        values: List[Any] = []
        for worker, source in workers:
            future = worker.submit(call)
            if future is None:
                self._append_failure_detail({
                    "source": source.name,
                    "code": "budget_exceeded",
                    "kind": "source_busy",
                    "status_code": None,
                    "url": "",
                    "error": "source request queue is full",
                })
            else:
                futures.append((future, source))
        done, _ = wait([future for future, _ in futures], timeout=self.budget_seconds)
        for future, source in futures:
            if future in done:
                value, detail = future.result()
                if detail is not None:
                    self._append_failure_detail(detail)
                values.append(value)
            else:
                future.cancel()
                self._append_failure_detail({
                    "source": source.name,
                    "code": "budget_exceeded",
                    "kind": "timeout",
                    "status_code": None,
                    "url": "",
                    "error": f"source exceeded fan-out budget of {self.budget_seconds}s",
                })
        return values

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
