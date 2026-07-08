"""Resolve a candidate citation to a canonical record across metadata sources."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from citeguard.citation import author_coverage, sequence_similarity, year_matches
from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients.base import MetadataSource
from citeguard.retrieval.scholarly_clients.multi_source import MultiSourceMetadataSource
from citeguard.retrieval.scholarly_clients.utils import normalize_arxiv_id, normalize_doi

STRONG_MATCH = 0.70
AMBIGUOUS_MARGIN = 0.05


@dataclass(frozen=True)
class ResolveOutcome:
    best: Optional[CitationRecord]
    score: float
    alternatives: List[CitationRecord]
    sources_checked: List[str]
    sources_responded: List[str]
    sources_failed: List[str]
    source_failure_details: List[Dict[str, Any]]
    ambiguous: bool


def verification_match_score(candidate: CitationRecord, record: CitationRecord) -> float:
    """Title-dominant match score suited to verification (DOI/arXiv are definitive)."""

    if candidate.doi and record.doi and normalize_doi(candidate.doi) == normalize_doi(record.doi):
        return 1.0
    if (
        candidate.arxiv_id
        and record.arxiv_id
        and normalize_arxiv_id(candidate.arxiv_id) == normalize_arxiv_id(record.arxiv_id)
    ):
        return 1.0
    title = sequence_similarity(candidate.title, record.title)
    author = author_coverage(candidate.authors, record.authors)
    year = 1.0 if year_matches(candidate.year, record.year) else 0.0
    return 0.70 * title + 0.18 * author + 0.12 * year


def source_names(source: MetadataSource) -> List[str]:
    """Human-readable list of the underlying source names (unwraps wrappers)."""

    inner = getattr(source, "inner", source)
    if isinstance(inner, MultiSourceMetadataSource):
        return [child.name for child in inner.sources]
    return [inner.name]


def resolve_citation(candidate: CitationRecord, source: MetadataSource) -> ResolveOutcome:
    checked = source_names(source)
    query = candidate.title or candidate.metadata.get("raw_text", "")
    failed = []
    failure_details: List[Dict[str, Any]] = []

    results: List[CitationRecord] = []
    if candidate.doi or candidate.arxiv_id:
        try:
            match = source.lookup(candidate)
        except Exception as exc:
            match = None
            failed.extend(checked)
            failure_details.extend(_exception_failure_details(checked, exc))
        failure_details.extend(_source_failure_details(source))
        if match is not None:
            results.append(match)
    if query:
        try:
            results.extend(source.search(query, top_k=5))
        except Exception as exc:
            failed.extend(checked)
            failure_details.extend(_exception_failure_details(checked, exc))
        failure_details.extend(_source_failure_details(source))

    inner = getattr(source, "inner", source)
    failed.extend(getattr(inner, "last_failures", []))
    failure_details.extend(getattr(inner, "last_failure_details", []))
    failure_details = _dedupe_failure_details(failure_details)
    failed.extend(
        str(detail.get("source", ""))
        for detail in failure_details
        if detail.get("source") and detail.get("code")
    )
    failed = sorted(set(failed))

    responded = sorted({record.source for record in results if record.source})

    seen = set()
    scored = []
    for record in results:
        if record.citation_id in seen:
            continue
        seen.add(record.citation_id)
        scored.append((verification_match_score(candidate, record), record))
    scored.sort(key=lambda item: item[0], reverse=True)

    if not scored:
        return ResolveOutcome(None, 0.0, [], checked, responded, failed, failure_details, False)

    best_score, best = scored[0]
    alternatives = [record for _, record in scored[1:4]]
    ambiguous = (
        best_score >= STRONG_MATCH
        and len(scored) > 1
        and (best_score - scored[1][0]) < AMBIGUOUS_MARGIN
        and not (candidate.doi or candidate.arxiv_id)
    )
    return ResolveOutcome(best, best_score, alternatives, checked, responded, failed, failure_details, ambiguous)


def _exception_failure_details(source_names: List[str], exc: Exception) -> List[Dict[str, Any]]:
    code, kind = _classify_source_exception(exc)
    return [
        {
            "source": name,
            "code": code,
            "kind": kind,
            "status_code": None,
            "url": "",
            "error": exc.__class__.__name__,
        }
        for name in source_names
    ]


def _source_failure_details(source: MetadataSource) -> List[Dict[str, Any]]:
    inner = getattr(source, "inner", source)
    if isinstance(inner, MultiSourceMetadataSource):
        return [dict(item) for item in getattr(inner, "last_failure_details", [])]

    http_client = getattr(inner, "http_client", None)
    code = getattr(http_client, "last_error_code", "") if http_client is not None else ""
    if not code:
        return []
    return [
        {
            "source": getattr(inner, "name", "metadata_source"),
            "code": code,
            "kind": getattr(http_client, "last_error_kind", ""),
            "status_code": getattr(http_client, "last_status_code", None),
            "url": getattr(http_client, "last_url", ""),
            "final_url": getattr(http_client, "last_final_url", ""),
            "redirected": bool(getattr(http_client, "last_redirected", False)),
            "error": getattr(http_client, "last_error", ""),
            "cache_hit": bool(getattr(http_client, "last_cache_hit", False)),
            "attempt_count": int(getattr(http_client, "last_attempt_count", 0) or 0),
            "retry_count": int(getattr(http_client, "last_retry_count", 0) or 0),
            "retry_after_seconds": getattr(http_client, "last_retry_after_seconds", None),
            "retry_delay_seconds": getattr(http_client, "last_retry_delay_seconds", None),
        }
    ]


def _classify_source_exception(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout", "timeout"
    return "source_unavailable", "exception"


def _dedupe_failure_details(details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    for detail in details:
        if detail not in deduped:
            deduped.append(detail)
    return deduped
