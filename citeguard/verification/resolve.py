"""Resolve a candidate citation to a canonical record across metadata sources."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional

from citeguard.citation import author_coverage, sequence_similarity, year_matches
from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients.base import MetadataSource
from citeguard.retrieval.scholarly_clients.multi_source import MultiSourceMetadataSource
from citeguard.retrieval.scholarly_clients.utils import base_arxiv_id, normalize_arxiv_id, normalize_doi

STRONG_MATCH = 0.70
AMBIGUOUS_MARGIN = 0.05

DEFAULT_SUSPECT_DOI_PREFIXES = ("10.65215",)


def _suspect_doi_prefixes() -> tuple:
    extra = os.environ.get("CITEGUARD_SUSPECT_DOI_PREFIXES", "")
    return DEFAULT_SUSPECT_DOI_PREFIXES + tuple(p.strip() for p in extra.split(",") if p.strip())


def is_suspect_record(record: CitationRecord, now_year: Optional[int] = None) -> bool:
    """Heuristic for hijacked/mirror records.

    Only ever used to DOWNGRADE a verdict to ambiguous - never to accuse.
    Signals: a greylisted DOI prefix, or an implausible citation count for a
    brand-new publication year (e.g. thousands of citations on a paper dated
    this year - the signature of a hijacked duplicate of a classic paper).
    """

    doi = normalize_doi(record.doi)
    if doi and any(doi.startswith(prefix) for prefix in _suspect_doi_prefixes()):
        return True
    cited = int(record.metadata.get("cited_by_count") or 0)
    year = record.year
    current = now_year if now_year is not None else date.today().year
    return bool(cited >= 1000 and year is not None and year >= current - 1)


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
    identifier_lookup: Optional[Dict[str, Any]] = None
    ambiguity_reason: str = ""


def verification_match_score(candidate: CitationRecord, record: CitationRecord) -> float:
    """Title-dominant match score suited to verification (DOI/arXiv are definitive)."""

    if candidate.doi and record.doi and normalize_doi(candidate.doi) == normalize_doi(record.doi):
        return 1.0
    if (
        candidate.arxiv_id
        and record.arxiv_id
        and base_arxiv_id(candidate.arxiv_id) == base_arxiv_id(record.arxiv_id)
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


IDENTIFIER_AUTHORITY = {"arxiv_id": "arxiv", "doi": "crossref"}


def _child_sources(source: MetadataSource) -> List[MetadataSource]:
    inner = getattr(source, "inner", source)
    if isinstance(inner, MultiSourceMetadataSource):
        return list(inner.sources)
    return [inner]


def _identifier_authority(candidate: CitationRecord, source: MetadataSource):
    """Strictly resolve the caller-provided identifier at its home source.

    Returns (info, record_or_None) where info["status"] is one of
    "hit" | "miss" | "failed" | "unavailable"; returns None when the candidate
    carries no identifier. Never falls back to title search: a reliable
    hit/miss/failed signal is the whole point.
    """

    if candidate.arxiv_id:
        id_kind, value = "arxiv_id", normalize_arxiv_id(candidate.arxiv_id)
    elif candidate.doi:
        id_kind, value = "doi", normalize_doi(candidate.doi)
    else:
        return None
    authority_name = IDENTIFIER_AUTHORITY[id_kind]
    info: Dict[str, Any] = {"kind": id_kind, "value": value, "source": authority_name}
    child = next(
        (item for item in _child_sources(source) if getattr(item, "name", "") == authority_name),
        None,
    )
    if child is None:
        info["status"] = "unavailable"
        return info, None

    last_detail: Optional[Dict[str, Any]] = None
    for _attempt in range(2):  # one explicit retry: the authority path deserves a second chance
        try:
            record = child.lookup_identifier(candidate)
        except Exception as exc:
            code, kind = _classify_source_exception(exc)
            last_detail = {
                "source": authority_name, "code": code, "kind": kind,
                "status_code": None, "url": "", "error": exc.__class__.__name__,
            }
            continue
        http_client = getattr(child, "http_client", None)
        error_code = getattr(http_client, "last_error_code", "") if http_client is not None else ""
        if record is not None:
            info["status"] = "hit"
            return info, record
        if not error_code:
            info["status"] = "miss"
            return info, None
        last_detail = {
            "source": authority_name,
            "code": error_code,
            "kind": getattr(http_client, "last_error_kind", ""),
            "status_code": getattr(http_client, "last_status_code", None),
            "url": getattr(http_client, "last_url", ""),
            "error": getattr(http_client, "last_error", ""),
        }
    info["status"] = "failed"
    if last_detail is not None:
        info["failure_detail"] = last_detail
    return info, None


def resolve_citation(candidate: CitationRecord, source: MetadataSource) -> ResolveOutcome:
    checked = source_names(source)
    query = candidate.title or candidate.metadata.get("raw_text", "")
    failed = []
    failure_details: List[Dict[str, Any]] = []

    results: List[CitationRecord] = []
    identifier_info: Optional[Dict[str, Any]] = None
    authority = _identifier_authority(candidate, source)
    if authority is not None:
        identifier_info, authority_record = authority
        if identifier_info.get("status") == "hit" and authority_record is not None:
            results.append(authority_record)
        elif identifier_info.get("status") == "failed":
            detail = identifier_info.get("failure_detail")
            if detail:
                failure_details.append(dict(detail))
                failed.append(str(detail.get("source", "")))

    identifier_hit = bool(identifier_info and identifier_info.get("status") == "hit")
    if (candidate.doi or candidate.arxiv_id) and not identifier_hit:
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
    scored.sort(key=lambda item: (item[0], 0 if is_suspect_record(item[1]) else 1), reverse=True)

    if not scored:
        return ResolveOutcome(
            best=None,
            score=0.0,
            alternatives=[],
            sources_checked=checked,
            sources_responded=responded,
            sources_failed=failed,
            source_failure_details=failure_details,
            ambiguous=False,
            identifier_lookup=identifier_info,
            ambiguity_reason="",
        )

    best_score, best = scored[0]
    alternatives = [record for _, record in scored[1:4]]
    ambiguous = (
        best_score >= STRONG_MATCH
        and len(scored) > 1
        and (best_score - scored[1][0]) < AMBIGUOUS_MARGIN
        and not (candidate.doi or candidate.arxiv_id)
    )
    ambiguity_reason = "near_duplicate" if ambiguous else ""
    if not identifier_hit and scored:
        strong_records = [record for score, record in scored if score >= STRONG_MATCH]
        years = {record.year for record in strong_records if record.year is not None}
        if len(years) >= 2 and (max(years) - min(years) > 1):
            ambiguous, ambiguity_reason = True, "year_conflict"
        elif best is not None and is_suspect_record(best):
            ambiguous, ambiguity_reason = True, (ambiguity_reason or "suspect_record")
    return ResolveOutcome(
        best=best,
        score=best_score,
        alternatives=alternatives,
        sources_checked=checked,
        sources_responded=responded,
        sources_failed=failed,
        source_failure_details=failure_details,
        ambiguous=ambiguous,
        identifier_lookup=identifier_info,
        ambiguity_reason=ambiguity_reason,
    )


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
