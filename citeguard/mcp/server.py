"""FastMCP server exposing CiteGuard citation-verification tools."""

from __future__ import annotations

import importlib
import os
from typing import Any, Dict, List, Optional

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised when the optional extra is missing.
    _MCP_IMPORT_ERROR = exc

    class FastMCP:  # type: ignore[no-redef]
        """Fallback that keeps direct helper imports usable without the mcp extra."""

        def __init__(self, name: str) -> None:
            self.name = name

        def tool(self):
            def decorator(func):
                return func

            return decorator

        def run(self) -> None:
            raise RuntimeError(
                "The MCP server requires the optional MCP dependency. "
                'Install published packages with `python -m pip install "citationguard[mcp]"` '
                'using Python 3.10 or newer. From a source checkout, use '
                '`python -m pip install -e ".[mcp]"`.'
            )
else:
    _MCP_IMPORT_ERROR = None

from citeguard.errors import error_payload, runtime_config_error_details
from citeguard.runtime import build_configured_source, build_configured_support_backend, build_doi_registry_probe, build_oa_fulltext_fetcher, environment_status
from citeguard.verification import (
    ClaimSupportAuditItem,
    audit_citations,
    audit_claim_support,
    check_claim_support,
    check_claim_support_set,
    enrich_support_payload_with_counterevidence,
    filter_high_risk_payload,
    parse_citation,
    search_counterevidence_candidates,
    verify_citation,
)

mcp = FastMCP("CiteGuard")


class MCPInputError(ValueError):
    """Expected MCP tool input error that should be returned as a tool result."""

    def __init__(self, message: str, details: dict) -> None:
        super().__init__(message)
        self.details = details

    def to_payload(self) -> dict:
        return error_payload("invalid_input", str(self), details=self.details)


class MCPFileError(OSError):
    """Expected MCP filesystem error that should be returned as a tool result."""

    def __init__(self, message: str, details: dict) -> None:
        super().__init__(message)
        self.details = details

    def to_payload(self) -> dict:
        return error_payload("file_error", str(self), details=self.details)


def _build_source():
    return build_configured_source()


# Build lazily so that import never triggers network or filesystem work.
_SOURCE = None


def _source():
    global _SOURCE
    if _SOURCE is None:
        _SOURCE = _build_source()
    return _SOURCE


_SUPPORT_BACKEND = None


def _support_backend():
    global _SUPPORT_BACKEND
    if _SUPPORT_BACKEND is None:
        _SUPPORT_BACKEND = build_configured_support_backend()
    return _SUPPORT_BACKEND


def _source_or_error(tool: str) -> Any:
    try:
        return _source()
    except ValueError as exc:
        return _value_error_payload(tool, exc)


def _support_backend_or_error(tool: str) -> Any:
    try:
        return _support_backend()
    except ValueError as exc:
        return _value_error_payload(tool, exc)


def _value_error_payload(tool: str, exc: ValueError) -> dict:
    return error_payload("invalid_input", str(exc), details=_value_error_details(tool, exc))


@mcp.tool()
def citeguard_status_tool(check_sources: bool = False, health_query: str = "Attention Is All You Need") -> dict:
    """Return MCP configuration and dependency status.

    Call this first when setting up CiteGuard or diagnosing surprising results.
    By default it does not contact OpenAlex/Crossref/arXiv/Semantic Scholar and
    does not load model weights. Set `check_sources=true` to run a lightweight
    per-source live probe using `health_query`.
    """
    return environment_status(
        mcp_sdk_available=_MCP_IMPORT_ERROR is None,
        check_sources=bool(check_sources),
        health_query=str(health_query or "Attention Is All You Need"),
    )


@mcp.tool()
def verify_citation_tool(
    raw_text: str = "",
    title: str = "",
    authors: Optional[List[str]] = None,
    year: Optional[int] = None,
    venue: str = "",
    doi: str = "",
    arxiv_id: str = "",
) -> dict:
    """Verify ONE citation against live scholarly sources (OpenAlex/Crossref/arXiv).

    Provide either a free-text citation in `raw_text`, or structured fields
    (`title`, `authors`, `year`, `doi`, `arxiv_id`, `venue`). Returns a verdict
    (verified | metadata_mismatch | not_found | ambiguous), the canonical record,
    per-field diffs, a suggested corrected citation when confident, and which
    sources were checked. A `not_found` verdict means "could not be verified",
    not a definitive proof of fabrication. Evidence and full-text inputs belong
    to the claim-support tools, not to existence/metadata verification.
    """
    if not _has_citation_input(raw_text=raw_text, title=title, doi=doi, arxiv_id=arxiv_id):
        return error_payload(
            "missing_citation_input",
            "Provide raw_text, title, doi, or arxiv_id.",
            details={"tool": "verify_citation_tool"},
        )
    try:
        candidate = _parse_citation_fields(
            raw_text=raw_text,
            title=title,
            authors=authors,
            year=year,
            venue=venue,
            doi=doi,
            arxiv_id=arxiv_id,
            tool="verify_citation_tool",
        )
    except (MCPInputError, MCPFileError) as exc:
        return exc.to_payload()
    active_source = _source_or_error("verify_citation_tool")
    if isinstance(active_source, dict):
        return active_source
    return verify_citation(candidate, active_source, doi_registry=build_doi_registry_probe()).to_dict()


@mcp.tool()
def audit_citations_tool(citations: Any, high_risk_only: bool = False) -> dict:
    """Verify MANY citations at once.

    `citations` is a list of objects, each with any of:
    `raw_text`, `title`, `authors`, `year`, `venue`, `doi`, `arxiv_id`.
    Returns a per-citation report plus `summary`, `risk_ranking`, and
    `review_summary`. Agents should branch on `review_summary.triage_plan`,
    compact `risk_reason`, and `suggested_fix.kind` /
    `suggested_fix.requires_user_confirmation` instead of parsing prose. Set
    `review_summary.suggested_fix_summary.auto_apply_allowed=false` means batch
    repairs must be proposed to the user, not silently applied. Set
    `high_risk_only=true` to return only high-risk result rows while preserving
    full-batch `review_summary` counts and `filtered.returned_indexes` /
    `filtered.omitted_indexes` for original-input traceability.
    """
    if not isinstance(citations, list):
        return error_payload(
            "invalid_input",
            "citations must be a list of citation objects.",
            details=_shape_details(
                tool="audit_citations_tool",
                field="citations",
                expected="list",
                received=citations,
            ),
        )
    for index, item in enumerate(citations, start=1):
        if not isinstance(item, dict):
            return error_payload(
                "invalid_input",
                f"citations item {index} must be an object.",
                details=_shape_details(
                    tool="audit_citations_tool",
                    field="citations",
                    index=index,
                    expected="object",
                    received=item,
                ),
            )
        if not _has_citation_input(
            raw_text=item.get("raw_text", ""),
            title=item.get("title", ""),
            doi=item.get("doi", ""),
            arxiv_id=item.get("arxiv_id", ""),
        ):
            return error_payload(
                "missing_citation_input",
                "Each citation item must include raw_text, title, doi, or arxiv_id.",
                details={"tool": "audit_citations_tool", "index": index},
            )
    candidates = []
    for index, item in enumerate(citations, start=1):
        try:
            candidates.append(_parse_citation_item(item, tool="audit_citations_tool", index=index))
        except (MCPInputError, MCPFileError) as exc:
            return exc.to_payload()
    active_source = _source_or_error("audit_citations_tool")
    if isinstance(active_source, dict):
        return active_source
    result = audit_citations(candidates, active_source, doi_registry=build_doi_registry_probe()).to_dict()
    if high_risk_only:
        result = filter_high_risk_payload(result)
    return result


@mcp.tool()
def check_claim_support_tool(
    claim: str,
    raw_text: str = "",
    title: str = "",
    authors: Optional[List[str]] = None,
    year: Optional[int] = None,
    venue: str = "",
    abstract: str = "",
    evidence_chunks: Optional[List[dict]] = None,
    evidence_text: Any = None,
    full_text: Any = None,
    full_text_file: Any = None,
    doi: str = "",
    arxiv_id: str = "",
    lang: str = "",
) -> dict:
    """Judge whether a cited paper SUPPORTS a claim sentence (abstract-level).

    Resolves the paper (existence), then assesses support with a reranker+NLI
    ensemble. Verdicts: supported | weakly_supported | insufficient_evidence |
    contradicted. `insufficient_evidence` means the abstract does not address the
    claim - NOT that the paper is unsupportive. Agents may pass lawful
    caller-provided `full_text` excerpts or `full_text_file` paths; those are
    tagged as `evidence_scope=full_text`, and CiteGuard will not fetch gated
    full text. Deep models are downloaded on first use; without them the engine
    falls back to "heuristic" (no supported/contradicted verdicts) and says so.
    Set CITEGUARD_RERANKER_MODEL / CITEGUARD_NLI_MODEL to use multilingual
    models for non-English claims.
    """
    if not str(claim).strip():
        return error_payload(
            "missing_claim",
            "Provide a non-empty claim.",
            details={"tool": "check_claim_support_tool"},
        )
    if not _has_citation_input(raw_text=raw_text, title=title, doi=doi, arxiv_id=arxiv_id):
        return error_payload(
            "missing_citation_input",
            "Provide raw_text, title, doi, or arxiv_id.",
            details={"tool": "check_claim_support_tool"},
        )
    try:
        candidate = _parse_citation_fields(
            raw_text=raw_text,
            title=title,
            authors=authors,
            year=year,
            venue=venue,
            abstract=abstract,
            doi=doi,
            arxiv_id=arxiv_id,
            evidence_chunks=evidence_chunks,
            evidence_text=evidence_text,
            full_text=full_text,
            full_text_file=full_text_file,
            tool="check_claim_support_tool",
        )
    except (MCPInputError, MCPFileError) as exc:
        return exc.to_payload()
    active_source = _source_or_error("check_claim_support_tool")
    if isinstance(active_source, dict):
        return active_source
    active_backend = _support_backend_or_error("check_claim_support_tool")
    if isinstance(active_backend, dict):
        return active_backend
    return check_claim_support(claim, candidate, active_source, backend=active_backend, lang=lang, oa_fulltext_fetcher=build_oa_fulltext_fetcher()).to_dict()


@mcp.tool()
def check_claim_support_set_tool(
    claim: str,
    citations: Any,
    lang: str = "",
    include_counterevidence: bool = False,
    counterevidence_top_k: int = 3,
) -> dict:
    """Judge whether a SET of cited papers supports one claim sentence.

    `citations` is a list of citation objects accepted by `verify_citation_tool`.
    Citation objects may include lawful caller-provided `full_text` excerpts or
    `full_text_file` paths; those are tagged as `evidence_scope=full_text`, and
    CiteGuard will not fetch gated full text. The result aggregates
    per-citation support checks and exposes `support_mode_details` with the
    policy `no_unstated_multi_hop_or_full_text_support`. A supported aggregate
    requires at least one resolved citation to strongly support the claim;
    contradictions are surfaced as high-risk.
    """
    if not str(claim).strip():
        return error_payload(
            "missing_claim",
            "Provide a non-empty claim.",
            details={"tool": "check_claim_support_set_tool"},
        )
    if not isinstance(citations, list):
        return error_payload(
            "invalid_input",
            "citations must be a non-empty list of citation objects.",
            details=_shape_details(
                tool="check_claim_support_set_tool",
                field="citations",
                expected="non_empty_list",
                received=citations,
            ),
        )
    if not citations:
        return error_payload(
            "missing_citation_input",
            "Provide a non-empty citations list.",
            details={
                "tool": "check_claim_support_set_tool",
                "field": "citations",
                "expected": "non_empty_list",
                "received": "list",
            },
        )
    parsed_counterevidence_top_k = None
    if include_counterevidence:
        parsed_counterevidence_top_k = _parse_counterevidence_top_k(
            counterevidence_top_k,
            tool="check_claim_support_set_tool",
        )
        if isinstance(parsed_counterevidence_top_k, dict):
            return parsed_counterevidence_top_k
    candidates = []
    for index, item in enumerate(citations, start=1):
        if not isinstance(item, dict):
            return error_payload(
                "invalid_input",
                f"citations item {index} must be an object.",
                details=_shape_details(
                    tool="check_claim_support_set_tool",
                    field="citations",
                    index=index,
                    expected="object",
                    received=item,
                ),
            )
        if not _has_citation_input(
            raw_text=item.get("raw_text", ""),
            title=item.get("title", ""),
            doi=item.get("doi", ""),
            arxiv_id=item.get("arxiv_id", ""),
        ):
            return error_payload(
                "missing_citation_input",
                "Each citation item must include raw_text, title, doi, or arxiv_id.",
                details={"tool": "check_claim_support_set_tool", "index": index},
            )
        try:
            candidates.append(_parse_citation_item(item, tool="check_claim_support_set_tool", index=index))
        except (MCPInputError, MCPFileError) as exc:
            return exc.to_payload()
    active_source = _source_or_error("check_claim_support_set_tool")
    if isinstance(active_source, dict):
        return active_source
    active_backend = _support_backend_or_error("check_claim_support_set_tool")
    if isinstance(active_backend, dict):
        return active_backend
    result = check_claim_support_set(
        claim,
        candidates,
        active_source,
        backend=active_backend,
        lang=lang,
        oa_fulltext_fetcher=build_oa_fulltext_fetcher(),
    ).to_dict()
    if include_counterevidence:
        result = enrich_support_payload_with_counterevidence(result, active_source, top_k=parsed_counterevidence_top_k)
    return result


@mcp.tool()
def search_counterevidence_tool(claim: str, top_k: int = 5) -> dict:
    """Search for scholarly records that may contain counter-evidence.

    This tool returns review candidates only. It does not prove contradiction
    and does not change a support verdict; run claim-support checks on any
    promising candidate before editing text or replacing citations.
    """
    if not str(claim).strip():
        return error_payload(
            "missing_claim",
            "Provide a non-empty claim.",
            details={"tool": "search_counterevidence_tool"},
        )
    try:
        parsed_top_k = int(top_k)
    except (TypeError, ValueError):
        return error_payload(
            "invalid_input",
            "top_k must be an integer.",
            details={"tool": "search_counterevidence_tool", "field": "top_k"},
        )
    if parsed_top_k < 0:
        return error_payload(
            "invalid_input",
            "top_k must be non-negative.",
            details={"tool": "search_counterevidence_tool", "field": "top_k"},
        )
    active_source = _source_or_error("search_counterevidence_tool")
    if isinstance(active_source, dict):
        return active_source
    return search_counterevidence_candidates(claim, active_source, top_k=parsed_top_k).to_dict()


@mcp.tool()
def audit_claim_support_tool(
    items: Any,
    lang: str = "",
    include_counterevidence: bool = False,
    counterevidence_top_k: int = 3,
    high_risk_only: bool = False,
) -> dict:
    """Judge MANY claim-citation support pairs at once.

    `items` is a list of objects with a required `claim` plus any citation
    fields accepted by `verify_citation_tool`: `raw_text`, `title`, `authors`,
    `year`, `venue`, `doi`, `arxiv_id`, `full_text`, `full_text_file`, and
    optional per-item `lang`. An item may
    alternatively provide `citations`, a non-empty list of citation objects, to
    assess whether a claim is supported by the cited set. Returns a per-item
    support report plus `summary`, `risk_ranking`, and `review_summary`. Agents
    should branch on `review_summary.triage_plan`, compact `risk_reason`, and
    `suggested_fix.kind` / `suggested_fix.requires_user_confirmation` instead
    of parsing support prose or silently editing citations.
    `review_summary.suggested_fix_summary.auto_apply_allowed=false` means batch
    repairs must be proposed to the user, not silently applied. Items may include
    lawful caller-provided `full_text` excerpts or `full_text_file` paths; those
    are tagged as `evidence_scope=full_text`, and CiteGuard will not fetch gated
    full text. Set
    `high_risk_only=true` to return only high-risk rows while preserving
    full-batch `review_summary` counts and `filtered.returned_indexes` /
    `filtered.omitted_indexes` for original-input traceability.
    """
    if not isinstance(items, list):
        return error_payload(
            "invalid_input",
            "items must be a list of claim/citation objects.",
            details=_shape_details(
                tool="audit_claim_support_tool",
                field="items",
                expected="list",
                received=items,
            ),
        )
    parsed_counterevidence_top_k = None
    if include_counterevidence:
        parsed_counterevidence_top_k = _parse_counterevidence_top_k(
            counterevidence_top_k,
            tool="audit_claim_support_tool",
        )
        if isinstance(parsed_counterevidence_top_k, dict):
            return parsed_counterevidence_top_k
    requests = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            return error_payload(
                "invalid_input",
                f"items item {index} must be an object.",
                details=_shape_details(
                    tool="audit_claim_support_tool",
                    field="items",
                    index=index,
                    expected="object",
                    received=item,
                ),
            )
        claim = str(item.get("claim", "")).strip()
        if not claim:
            return error_payload(
                "missing_claim",
                "Each support-audit item must include a non-empty claim.",
                details={"tool": "audit_claim_support_tool", "index": index},
            )
        if "citations" in item:
            citations = item.get("citations")
            if not isinstance(citations, list):
                return error_payload(
                    "invalid_input",
                    "Each support-audit citations field must be a non-empty list of citation objects.",
                    details={
                        "tool": "audit_claim_support_tool",
                        "index": index,
                        "field": "citations",
                        "expected": "list",
                        "received": type(citations).__name__,
                    },
                )
            if not citations:
                return error_payload(
                    "missing_citation_input",
                    "Each support-audit citations field must include at least one citation object.",
                    details={"tool": "audit_claim_support_tool", "index": index, "field": "citations"},
                )
            parsed_citations = []
            for citation_index, citation_item in enumerate(citations, start=1):
                if not isinstance(citation_item, dict):
                    return error_payload(
                        "invalid_input",
                        "Each support-audit citations item must be an object.",
                        details={
                            "tool": "audit_claim_support_tool",
                            "index": index,
                            "field": "citations",
                            "citation_index": citation_index,
                            "expected": "object",
                            "received": type(citation_item).__name__,
                        },
                    )
                if not _has_citation_input(
                    raw_text=citation_item.get("raw_text", ""),
                    title=citation_item.get("title", ""),
                    doi=citation_item.get("doi", ""),
                    arxiv_id=citation_item.get("arxiv_id", ""),
                ):
                    return error_payload(
                        "missing_citation_input",
                        "Each support-audit citations item must include raw_text, title, doi, or arxiv_id.",
                        details={
                            "tool": "audit_claim_support_tool",
                            "index": index,
                            "field": "citations",
                            "citation_index": citation_index,
                        },
                    )
                try:
                    parsed_citations.append(
                        _parse_citation_item(
                            citation_item,
                            tool="audit_claim_support_tool",
                            index=index,
                            citation_index=citation_index,
                        )
                    )
                except (MCPInputError, MCPFileError) as exc:
                    return exc.to_payload()
            requests.append(
                ClaimSupportAuditItem(
                    claim=claim,
                    citations=parsed_citations,
                    lang=str(item.get("lang", "")),
                    input_mode="citation_set",
                )
            )
            continue
        if not _has_citation_input(
            raw_text=item.get("raw_text", ""),
            title=item.get("title", ""),
            doi=item.get("doi", ""),
            arxiv_id=item.get("arxiv_id", ""),
        ):
            return error_payload(
                "missing_citation_input",
                "Each support-audit item must include raw_text, title, doi, or arxiv_id.",
                details={"tool": "audit_claim_support_tool", "index": index},
            )
        try:
            parsed_citation = _parse_citation_item(item, tool="audit_claim_support_tool", index=index)
        except (MCPInputError, MCPFileError) as exc:
            return exc.to_payload()
        requests.append(
            ClaimSupportAuditItem(
                claim=claim,
                citations=[parsed_citation],
                lang=str(item.get("lang", "")),
                input_mode="citation",
            )
        )
    active_source = _source_or_error("audit_claim_support_tool")
    if isinstance(active_source, dict):
        return active_source
    active_backend = _support_backend_or_error("audit_claim_support_tool")
    if isinstance(active_backend, dict):
        return active_backend
    result = audit_claim_support(
        requests,
        active_source,
        backend=active_backend,
        lang=lang,
        oa_fulltext_fetcher=build_oa_fulltext_fetcher(),
    ).to_dict()
    if include_counterevidence:
        result = enrich_support_payload_with_counterevidence(result, active_source, top_k=parsed_counterevidence_top_k)
    if high_risk_only:
        result = filter_high_risk_payload(result)
    return result


def _parse_counterevidence_top_k(top_k: Any, tool: str) -> Any:
    try:
        parsed = int(top_k)
    except (TypeError, ValueError):
        return error_payload(
            "invalid_input",
            "counterevidence_top_k must be an integer.",
            details={"tool": tool, "field": "counterevidence_top_k"},
        )
    if parsed < 0:
        return error_payload(
            "invalid_input",
            "counterevidence_top_k must be non-negative.",
            details={"tool": tool, "field": "counterevidence_top_k"},
        )
    return parsed


def _has_citation_input(raw_text: str = "", title: str = "", doi: str = "", arxiv_id: str = "") -> bool:
    return bool(raw_text or title or doi or arxiv_id)


def _parse_citation_item(
    item: Dict[str, Any],
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
):
    return _parse_citation_fields(
        raw_text=item.get("raw_text", ""),
        title=item.get("title", ""),
        authors=item.get("authors"),
        year=item.get("year"),
        venue=item.get("venue", ""),
        abstract=item.get("abstract", ""),
        doi=item.get("doi", ""),
        arxiv_id=item.get("arxiv_id", ""),
        evidence_chunks=item.get("evidence_chunks"),
        evidence_text=item.get("evidence_text", item.get("evidence")),
        full_text=item.get("full_text", item.get("full_text_excerpt", item.get("full_text_excerpts"))),
        full_text_file=item.get(
            "full_text_file",
            item.get("full_text_files", item.get("full_text_excerpt_file", item.get("full_text_excerpt_files"))),
        ),
        tool=tool,
        index=index,
        citation_index=citation_index,
    )


def _parse_citation_fields(
    raw_text: str = "",
    title: str = "",
    authors: Optional[List[str]] = None,
    year: Optional[int] = None,
    venue: str = "",
    abstract: str = "",
    doi: str = "",
    arxiv_id: str = "",
    evidence_chunks: Any = None,
    evidence_text: Any = None,
    full_text: Any = None,
    full_text_file: Any = None,
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
):
    _validate_citation_scalar_fields(
        {
            "raw_text": raw_text,
            "title": title,
            "venue": venue,
            "abstract": abstract,
            "doi": doi,
            "arxiv_id": arxiv_id,
        },
        tool=tool,
        index=index,
        citation_index=citation_index,
    )
    return parse_citation(
        raw_text=raw_text,
        title=title,
        authors=_normalize_authors(authors, tool=tool, index=index, citation_index=citation_index),
        year=_normalize_year(year, tool=tool, index=index, citation_index=citation_index),
        venue=venue,
        abstract=abstract,
        doi=doi,
        arxiv_id=arxiv_id,
        evidence_chunks=_normalize_evidence_chunks(
            {
                "evidence_chunks": evidence_chunks,
                "evidence_text": evidence_text,
                "full_text": full_text,
                "full_text_file": full_text_file,
            },
            tool=tool,
            index=index,
            citation_index=citation_index,
        ),
    )


def _validate_citation_scalar_fields(
    item: Dict[str, Any],
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> None:
    for field in ["raw_text", "title", "venue", "abstract", "doi", "arxiv_id"]:
        value = item.get(field)
        if value is not None and not isinstance(value, str):
            raise MCPInputError(
                f"citation field {field!r} must be a string.",
                _input_details(tool=tool, index=index, field=field, citation_index=citation_index),
            )


def _normalize_authors(
    value: Any,
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> Optional[List[str]]:
    if value is None or value == "":
        return None
    if not isinstance(value, list) or any(not isinstance(author, str) for author in value):
        raise MCPInputError(
            "citation field 'authors' must be a list of strings.",
            _input_details(tool=tool, index=index, field="authors", citation_index=citation_index),
        )
    return value


def _normalize_year(
    value: Any,
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> Optional[int]:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        valid = False
    elif isinstance(value, int):
        return value
    elif isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    else:
        valid = False
    if not valid:
        raise MCPInputError(
            "citation field 'year' must be an integer year.",
            _input_details(tool=tool, index=index, field="year", citation_index=citation_index),
        )
    return None


def _input_details(
    tool: str = "",
    index: Optional[int] = None,
    field: str = "",
    citation_index: Optional[int] = None,
) -> dict:
    details = {}
    if tool:
        details["tool"] = tool
    if index is not None:
        details["index"] = index
    if citation_index is not None:
        details["citation_index"] = citation_index
    if field:
        details["field"] = field
    return details


def _value_error_details(tool: str, exc: ValueError) -> dict:
    return runtime_config_error_details(str(exc), base={"tool": tool}, env=os.environ)


def _shape_details(
    tool: str,
    field: str,
    expected: str,
    received: Any,
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> dict:
    details = _input_details(tool=tool, index=index, field=field, citation_index=citation_index)
    details["expected"] = expected
    details["received"] = type(received).__name__
    return details


def _as_list(value: Any) -> list:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


def _chunk(text: str, source_field: str, evidence_scope: str, source_url: str = "") -> dict:
    return {
        "text": text,
        "source_field": source_field,
        "source_url": source_url,
        "evidence_scope": evidence_scope,
    }


def _normalize_evidence_chunks(
    item: Dict[str, Any],
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> list:
    chunks = []
    for chunk_index, value in enumerate(_as_list(item.get("evidence_chunks")), start=1):
        if isinstance(value, dict):
            chunks.append(dict(value))
        elif str(value).strip():
            chunks.append(_chunk(str(value), f"user_evidence_chunk_{chunk_index}", "metadata"))

    for chunk_index, value in enumerate(_as_list(item.get("evidence_text")), start=1):
        if isinstance(value, dict):
            chunk = dict(value)
            chunk.setdefault("source_field", f"user_evidence_text_{chunk_index}")
            chunk.setdefault("evidence_scope", "metadata")
            chunks.append(chunk)
        elif str(value).strip():
            chunks.append(_chunk(str(value), f"user_evidence_text_{chunk_index}", "metadata"))

    for chunk_index, value in enumerate(_as_list(item.get("full_text")), start=1):
        if isinstance(value, dict):
            chunk = dict(value)
            chunk.setdefault("source_field", f"user_full_text_excerpt_{chunk_index}")
            chunk["evidence_scope"] = "full_text"
            chunks.append(chunk)
        elif str(value).strip():
            chunks.append(_chunk(str(value), f"user_full_text_excerpt_{chunk_index}", "full_text"))
    for file_index, path in enumerate(_as_list(item.get("full_text_file")), start=1):
        if not isinstance(path, str):
            raise MCPInputError(
                "full-text excerpt file paths must be strings.",
                _input_details(tool=tool, index=index, field="full_text_file", citation_index=citation_index),
            )
        text = _read_evidence_file(path, tool=tool, index=index, citation_index=citation_index)
        if text.strip():
            chunks.append(_chunk(text, f"user_full_text_file_{file_index}", "full_text"))
    return chunks


def _read_evidence_file(
    path: str,
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> str:
    if path.lower().endswith(".pdf"):
        return _read_pdf_text(path, tool=tool, index=index, citation_index=citation_index)
    return _read_text_file(path, tool=tool, index=index, citation_index=citation_index)


def _read_text_file(
    path: str,
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError as exc:
        details = _input_details(tool=tool, index=index, field="full_text_file", citation_index=citation_index)
        details["filename"] = path
        if getattr(exc, "errno", None) is not None:
            details["errno"] = getattr(exc, "errno")
        raise MCPFileError(f"Could not read full-text evidence file {path!r}: {exc}", details) from exc


def _read_pdf_text(
    path: str,
    tool: str = "",
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
) -> str:
    reader_cls = _load_pdf_reader(tool=tool, index=index, citation_index=citation_index)
    try:
        reader = reader_cls(path)
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        details = _input_details(tool=tool, index=index, field="full_text_file", citation_index=citation_index)
        details.update({"filename": path, "format": "pdf"})
        raise MCPFileError(f"Could not extract text from PDF full-text file {path!r}: {exc}", details) from exc


def _load_pdf_reader(tool: str = "", index: Optional[int] = None, citation_index: Optional[int] = None):
    for module_name in ("pypdf", "PyPDF2"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        reader = getattr(module, "PdfReader", None)
        if reader is not None:
            return reader
    details = _input_details(tool=tool, index=index, field="full_text_file", citation_index=citation_index)
    details.update({"format": "pdf", "dependency": "pypdf"})
    raise MCPInputError(
        "PDF full-text files require the optional pypdf package; install pypdf or provide a UTF-8 text excerpt file.",
        details,
    )


def main() -> None:
    if _MCP_IMPORT_ERROR is not None:
        raise RuntimeError(
            "The MCP server requires the optional MCP dependency. "
            'Install published packages with `python -m pip install "citationguard[mcp]"` '
            'using Python 3.10 or newer. From a source checkout, use '
            '`python -m pip install -e ".[mcp]"`.'
        ) from _MCP_IMPORT_ERROR
    mcp.run()


if __name__ == "__main__":
    main()
