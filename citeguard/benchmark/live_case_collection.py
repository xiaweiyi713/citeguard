"""Curate lawful real-record cases for the live retrieval benchmark.

The observation runner measures CiteGuard against this catalog; it must not be
responsible for deciding what the ground truth is.  This module keeps curation
explicit and conservative: identifier requests require an identifier match,
title requests require an exact normalized title (or an explicitly supplied
expected identifier), and rejected candidates are returned with diagnostics for
manual review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from citeguard.citation.normalizer import normalize_text, sequence_similarity
from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients.base import MetadataSource
from citeguard.retrieval.scholarly_clients.utils import base_arxiv_id, normalize_arxiv_id, normalize_doi
from citeguard.version import __version__
from citeguard.verification.parse import parse_citation


LIVE_CASE_COLLECTION_SCHEMA_VERSION = 1
ALLOWED_REQUEST_FIELDS = {
    "id",
    "query_kind",
    "query",
    "lang",
    "domain",
    "rights_basis",
    "ground_truth_locator",
    "source",
    "expected_identity",
}


class LiveCaseCollectionError(ValueError):
    """Raised when a curation request or generated case is malformed."""


@dataclass(frozen=True)
class LiveCaseRequest:
    """One operator-supplied request to curate into a benchmark case."""

    case_id: str
    query_kind: str
    query: str
    lang: str
    domain: str
    rights_basis: str = "public_metadata"
    ground_truth_locator: str = ""
    source: str = ""
    expected_identity: Dict[str, str] = field(default_factory=dict)


def load_collection_requests(payload: Mapping[str, Any]) -> List[LiveCaseRequest]:
    """Parse a request manifest without making network calls."""

    raw_requests = payload.get("requests")
    if not isinstance(raw_requests, list) or not raw_requests:
        raise LiveCaseCollectionError("request manifest must contain a non-empty requests list")
    requests: List[LiveCaseRequest] = []
    seen_ids = set()
    for index, raw in enumerate(raw_requests, start=1):
        if not isinstance(raw, Mapping):
            raise LiveCaseCollectionError(f"requests[{index}] must be an object")
        case_id = str(raw.get("id", "")).strip()
        query_kind = str(raw.get("query_kind", "")).strip()
        query = str(raw.get("query", "")).strip()
        if not case_id or case_id in seen_ids:
            raise LiveCaseCollectionError(f"requests[{index}] requires a unique id")
        if query_kind not in {"doi", "arxiv_id", "title"}:
            raise LiveCaseCollectionError(f"requests[{index}] has unsupported query_kind {query_kind!r}")
        if not query:
            raise LiveCaseCollectionError(f"requests[{index}] query is required")
        lang = str(raw.get("lang", "")).strip()
        domain = str(raw.get("domain", "")).strip()
        if not lang or not domain:
            raise LiveCaseCollectionError(f"requests[{index}] requires lang and domain")
        expected_raw = raw.get("expected_identity", {})
        if expected_raw is None:
            expected_raw = {}
        if not isinstance(expected_raw, Mapping):
            raise LiveCaseCollectionError(f"requests[{index}].expected_identity must be an object")
        expected = {
            key: value
            for key in ("doi", "arxiv_id", "title")
            if (value := _normalize_expected_identity(key, expected_raw.get(key)))
        }
        requests.append(
            LiveCaseRequest(
                case_id=case_id,
                query_kind=query_kind,
                query=_normalize_query(query_kind, query),
                lang=lang,
                domain=domain,
                rights_basis=str(raw.get("rights_basis", "public_metadata")).strip() or "public_metadata",
                ground_truth_locator=str(raw.get("ground_truth_locator", "")).strip(),
                source=str(raw.get("source", "")).strip().lower(),
                expected_identity=expected,
            )
        )
        seen_ids.add(case_id)
    return requests


def collect_live_retrieval_dataset(
    requests: Sequence[LiveCaseRequest],
    sources: Mapping[str, MetadataSource],
    *,
    collected_at: Optional[str] = None,
    min_title_similarity: float = 0.98,
) -> Dict[str, Any]:
    """Resolve curation requests and return a dataset plus an audit report.

    A failed or ambiguous request is never emitted as a benchmark case.  The
    returned report keeps enough information to fix the request or choose a
    different public source without silently dropping it.
    """

    if not requests:
        raise LiveCaseCollectionError("at least one curation request is required")
    if not sources:
        raise LiveCaseCollectionError("at least one metadata source is required")
    timestamp = collected_at or _utc_now()
    if not _is_iso_timestamp(timestamp):
        raise LiveCaseCollectionError("collected_at must be an ISO-8601 timestamp with a timezone")

    cases: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for request in requests:
        source_name = request.source or _default_source(request.query_kind, sources)
        source = sources.get(source_name)
        if source is None:
            rejected.append(
                _rejection(request, source_name, "source_not_configured", {"available_sources": sorted(sources)})
            )
            continue
        record, selection = _resolve_request(request, source, min_title_similarity=min_title_similarity)
        if record is None:
            rejected.append(_rejection(request, source_name, selection["reason"], selection))
            continue
        try:
            case = _case_from_record(request, source_name, record, selection, timestamp)
        except LiveCaseCollectionError as exc:
            rejected.append(_rejection(request, source_name, "generated_case_invalid", {"error": str(exc)}))
            continue
        cases.append(case)

    return {
        "schema_version": LIVE_CASE_COLLECTION_SCHEMA_VERSION,
        "collected_at": timestamp,
        "collector": {"name": "citeguard.live_case_collection", "version": __version__},
        "cases": cases,
        "report": {
            "requested_count": len(requests),
            "accepted_count": len(cases),
            "rejected_count": len(rejected),
            "accepted_case_ids": [case["id"] for case in cases],
            "rejected": rejected,
            "policy": {
                "public_metadata_only": True,
                "identifier_match_required": True,
                "title_match_must_be_exact_or_expected_identifier": True,
                "ambiguous_candidates_are_rejected": True,
                "source_failures_are_not_benchmark_cases": True,
            },
        },
    }


def merge_collected_cases(
    existing_dataset: Mapping[str, Any],
    collected_payload: Mapping[str, Any],
    *,
    replace: bool = False,
    campaign_id: str = "citeguard-live-retrieval-v1",
) -> Dict[str, Any]:
    """Merge accepted cases into the benchmark dataset with duplicate protection."""

    if existing_dataset.get("schema_version") != 1:
        raise LiveCaseCollectionError("existing dataset schema_version must be 1")
    if str(existing_dataset.get("campaign_id", "")).strip() != campaign_id:
        raise LiveCaseCollectionError("existing dataset campaign_id does not match the requested campaign")
    collected_cases = collected_payload.get("cases")
    if not isinstance(collected_cases, list):
        raise LiveCaseCollectionError("collector payload cases must be a list")

    by_id: Dict[str, Dict[str, Any]] = {
        str(row.get("id", "")).strip(): dict(row)
        for row in existing_dataset.get("cases", [])
        if isinstance(row, Mapping) and str(row.get("id", "")).strip()
    }
    conflicts: List[str] = []
    for raw in collected_cases:
        if not isinstance(raw, Mapping) or not str(raw.get("id", "")).strip():
            raise LiveCaseCollectionError("every collected case must be an object with an id")
        case_id = str(raw["id"]).strip()
        if case_id in by_id and not replace:
            conflicts.append(case_id)
            continue
        by_id[case_id] = dict(raw)
    if conflicts:
        raise LiveCaseCollectionError(
            "case ids already exist; use --replace to intentionally refresh them: " + ", ".join(sorted(conflicts))
        )
    return {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "description": str(existing_dataset.get("description", "")),
        "cases": [by_id[key] for key in sorted(by_id)],
        "collection_history": [
            *(
                existing_dataset.get("collection_history", [])
                if isinstance(existing_dataset.get("collection_history"), list)
                else []
            ),
            {
                "collected_at": collected_payload.get("collected_at", ""),
                "accepted_case_ids": [str(row.get("id", "")) for row in collected_cases if isinstance(row, Mapping)],
                "collector": collected_payload.get("collector", {}),
            },
        ],
    }


def _resolve_request(
    request: LiveCaseRequest,
    source: MetadataSource,
    *,
    min_title_similarity: float,
) -> Tuple[Optional[CitationRecord], Dict[str, Any]]:
    candidate = parse_citation(
        doi=request.query if request.query_kind == "doi" else "",
        arxiv_id=request.query if request.query_kind == "arxiv_id" else "",
        title=request.query if request.query_kind == "title" else "",
    )
    diagnostics_before = _source_diagnostics(source)
    try:
        identifier_candidate = _expected_identifier_candidate(request)
        if request.query_kind == "title" and identifier_candidate is not None:
            # A title request may carry an independently curated DOI/arXiv
            # identity. Resolve that identity first, then verify that the
            # returned record is actually the requested title. This avoids
            # promoting a polluted same-title search result.
            record = source.lookup_identifier(identifier_candidate)
            if record is not None:
                if _title_score(request.query, record) < min_title_similarity:
                    record = None
            else:
                records = source.search(request.query, top_k=10)
                record = _select_title_record(request, records, min_title_similarity)
        elif request.query_kind in {"doi", "arxiv_id"}:
            record = source.lookup_identifier(candidate)
            if record is None:
                # Adapters that do not expose identifier lookup can still be
                # asked through lookup, but the returned record must pass the
                # same strict identity check below.
                record = source.lookup(candidate)
        else:
            records = source.search(request.query, top_k=10)
            record = _select_title_record(request, records, min_title_similarity)
    except Exception as exc:
        diagnostics = _source_diagnostics(source)
        return None, {
            "reason": "source_exception",
            "error": f"{exc.__class__.__name__}: {exc}",
            "diagnostics": diagnostics,
        }
    diagnostics = _source_diagnostics(source)
    if record is None:
        return None, {
            "reason": "no_verified_candidate",
            "diagnostics": diagnostics or diagnostics_before,
        }
    identity = _expected_identity(request, record)
    if not _record_matches_identity(record, identity):
        return None, {
            "reason": "identity_mismatch",
            "expected_identity": identity,
            "candidate": _record_summary(record),
            "diagnostics": diagnostics,
        }
    return record, {
        "reason": "accepted",
        "selection_method": (
            "identifier_lookup"
            if request.query_kind != "title"
            else "expected_identifier_then_title_check"
            if request.expected_identity
            else "exact_title_search"
        ),
        "selection_score": _title_score(request.query, record),
        "expected_identity": identity,
        "diagnostics": diagnostics,
    }


def _expected_identifier_candidate(request: LiveCaseRequest) -> Optional[CitationRecord]:
    if request.query_kind != "title":
        return None
    doi = normalize_doi(str(request.expected_identity.get("doi", "")))
    arxiv_id = normalize_arxiv_id(str(request.expected_identity.get("arxiv_id", "")))
    if not doi and not arxiv_id:
        return None
    return parse_citation(doi=doi, arxiv_id=arxiv_id)


def _select_title_record(
    request: LiveCaseRequest,
    records: Sequence[CitationRecord],
    min_title_similarity: float,
) -> Optional[CitationRecord]:
    expected = request.expected_identity
    if expected:
        matching = [record for record in records if _record_matches_identity(record, expected)]
        if matching:
            return max(matching, key=lambda record: _title_score(request.query, record))
        return None
    exact = [record for record in records if normalize_text(record.title) == normalize_text(request.query)]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        # Same title with conflicting identifiers is not safe to promote from
        # a free-text query without an operator-provided expected identity.
        keys = sorted({_record_identity_key(record) for record in exact})
        if len(keys) == 1:
            return exact[0]
        return None
    scored = sorted(records, key=lambda record: _title_score(request.query, record), reverse=True)
    if scored and _title_score(request.query, scored[0]) >= min_title_similarity:
        return scored[0]
    return None


def _case_from_record(
    request: LiveCaseRequest,
    source_name: str,
    record: CitationRecord,
    selection: Mapping[str, Any],
    collected_at: str,
) -> Dict[str, Any]:
    expected_identity = dict(selection.get("expected_identity") or _expected_identity(request, record))
    if not expected_identity:
        raise LiveCaseCollectionError("accepted record has no canonical expected identity")
    fields: Dict[str, Any] = {"title": record.title}
    if record.authors:
        fields["authors"] = list(record.authors)
    if record.year is not None:
        fields["year"] = record.year
    if record.venue:
        fields["venue"] = record.venue
    if request.query_kind == "doi":
        fields["doi"] = request.query
    elif request.query_kind == "arxiv_id":
        fields["arxiv_id"] = request.query
    # Title cases intentionally omit identifiers unless the operator supplied
    # one in expected_identity; this keeps the query path meaningful.
    locator = request.ground_truth_locator or _record_locator(record, expected_identity)
    if not locator:
        raise LiveCaseCollectionError("accepted record has no ground_truth_locator")
    return {
        "id": request.case_id,
        "benchmark_origin": "real_source",
        "query_kind": request.query_kind,
        "fields": fields,
        "expected_identity": expected_identity,
        "ground_truth_locator": locator,
        "rights_basis": request.rights_basis,
        "lang": request.lang,
        "domain": request.domain,
        "metadata_snapshot": {
            "title": record.title,
            "authors": list(record.authors),
            "year": record.year,
            "venue": record.venue,
            "abstract": record.abstract,
            "doi": normalize_doi(record.doi),
            "arxiv_id": normalize_arxiv_id(record.arxiv_id),
            "url": record.url,
            "source": source_name,
            "retrieved_at": collected_at,
            "rights_basis": "public_metadata",
        },
        "curation": {
            "collected_at": collected_at,
            "source": source_name,
            "source_record_id": record.citation_id,
            "source_url": record.url,
            "selection_method": selection.get("selection_method", ""),
            "selection_score": selection.get("selection_score"),
            "adapter_version": __version__,
            "metadata_sha256": "sha256:" + _metadata_digest(record),
            "public_metadata_only": True,
        },
    }


def _expected_identity(request: LiveCaseRequest, record: CitationRecord) -> Dict[str, str]:
    if request.expected_identity:
        return dict(request.expected_identity)
    if request.query_kind == "doi":
        return {"doi": normalize_doi(request.query)}
    if request.query_kind == "arxiv_id":
        return {"arxiv_id": base_arxiv_id(request.query)}
    if record.doi:
        return {"doi": normalize_doi(record.doi)}
    if record.arxiv_id:
        return {"arxiv_id": base_arxiv_id(record.arxiv_id)}
    return {"title": record.title}


def _record_matches_identity(record: CitationRecord, expected: Mapping[str, str]) -> bool:
    expected_doi = normalize_doi(str(expected.get("doi", "")))
    if expected_doi and record.doi and normalize_doi(record.doi) == expected_doi:
        return True
    expected_arxiv = base_arxiv_id(str(expected.get("arxiv_id", "")))
    if expected_arxiv and record.arxiv_id and base_arxiv_id(record.arxiv_id) == expected_arxiv:
        return True
    expected_title = normalize_text(str(expected.get("title", "")))
    return bool(expected_title and normalize_text(record.title) == expected_title)


def _record_locator(record: CitationRecord, expected: Mapping[str, str]) -> str:
    doi = normalize_doi(str(expected.get("doi", "")))
    if doi:
        return f"https://doi.org/{doi}"
    arxiv_id = normalize_arxiv_id(str(expected.get("arxiv_id", "")))
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    return str(record.url or "").strip()


def _record_summary(record: CitationRecord) -> Dict[str, Any]:
    return {
        "citation_id": record.citation_id,
        "title": record.title,
        "doi": normalize_doi(record.doi),
        "arxiv_id": normalize_arxiv_id(record.arxiv_id),
        "year": record.year,
        "url": record.url,
    }


def _source_diagnostics(source: MetadataSource) -> Dict[str, Any]:
    client = getattr(source, "http_client", None)
    if client is None:
        return {}
    keys = (
        "last_error",
        "last_error_code",
        "last_error_kind",
        "last_status_code",
        "last_url",
        "last_final_url",
        "last_redirected",
        "last_cache_hit",
        "last_attempt_count",
        "last_retry_count",
        "last_retry_after_seconds",
    )
    return {key: getattr(client, key, None) for key in keys if getattr(client, key, None) not in (None, "", False, 0)}


def _rejection(request: LiveCaseRequest, source: str, reason: str, details: Mapping[str, Any]) -> Dict[str, Any]:
    return {
        "case_id": request.case_id,
        "query_kind": request.query_kind,
        "query": request.query,
        "source": source,
        "reason": reason,
        "details": dict(details),
    }


def _title_score(query: str, record: CitationRecord) -> float:
    return round(float(sequence_similarity(query, record.title)), 6)


def _record_identity_key(record: CitationRecord) -> str:
    if record.doi:
        return "doi:" + normalize_doi(record.doi)
    if record.arxiv_id:
        return "arxiv:" + base_arxiv_id(record.arxiv_id)
    return "title:" + normalize_text(record.title)


def _metadata_digest(record: CitationRecord) -> str:
    payload = _record_summary(record)
    payload["authors"] = list(record.authors)
    payload["venue"] = record.venue
    payload["abstract"] = record.abstract
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _normalize_expected_identity(key: str, value: Any) -> str:
    text = str(value or "").strip()
    if key == "doi":
        return normalize_doi(text)
    if key == "arxiv_id":
        return base_arxiv_id(text)
    return text


def _normalize_query(query_kind: str, query: str) -> str:
    if query_kind == "doi":
        return normalize_doi(query)
    if query_kind == "arxiv_id":
        return normalize_arxiv_id(query)
    return " ".join(query.split())


def _default_source(query_kind: str, sources: Mapping[str, MetadataSource]) -> str:
    preferred = {"doi": "crossref", "arxiv_id": "arxiv", "title": "openalex"}[query_kind]
    if preferred in sources:
        return preferred
    return sorted(sources)[0]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_iso_timestamp(value: str) -> bool:
    try:
        from datetime import datetime as _datetime

        return _datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except (TypeError, ValueError):
        return False
