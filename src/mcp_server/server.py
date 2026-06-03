"""FastMCP server: expose verify_citation and audit_citations to MCP clients."""

from __future__ import annotations

import os
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from src.retrieval.scholarly_clients import build_live_metadata_source
from src.verification import (
    CachingMetadataSource,
    audit_citations,
    parse_citation,
    verify_citation,
)

mcp = FastMCP("CiteGuard")


def _build_source():
    names = [n for n in os.environ.get("CITEGUARD_SOURCES", "openalex,crossref,arxiv").split(",") if n.strip()]
    mailto = os.environ.get("CITEGUARD_MAILTO", "research@example.com")
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    live = build_live_metadata_source(names, mailto=mailto, semantic_scholar_api_key=api_key)
    db_path = os.environ.get("CITEGUARD_CACHE", os.path.join("data", "logs", "verification_cache.sqlite"))
    return CachingMetadataSource(live, db_path=db_path)


# Build lazily so that import never triggers network or filesystem work.
_SOURCE = None


def _source():
    global _SOURCE
    if _SOURCE is None:
        _SOURCE = _build_source()
    return _SOURCE


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
    not a definitive proof of fabrication.
    """
    candidate = parse_citation(
        raw_text=raw_text,
        title=title,
        authors=authors,
        year=year,
        venue=venue,
        doi=doi,
        arxiv_id=arxiv_id,
    )
    return verify_citation(candidate, _source()).to_dict()


@mcp.tool()
def audit_citations_tool(citations: List[dict]) -> dict:
    """Verify MANY citations at once.

    `citations` is a list of objects, each with any of:
    `raw_text`, `title`, `authors`, `year`, `venue`, `doi`, `arxiv_id`.
    Returns a per-citation report plus a summary counting each verdict.
    """
    candidates = [
        parse_citation(
            raw_text=item.get("raw_text", ""),
            title=item.get("title", ""),
            authors=item.get("authors"),
            year=item.get("year"),
            venue=item.get("venue", ""),
            doi=item.get("doi", ""),
            arxiv_id=item.get("arxiv_id", ""),
        )
        for item in citations
    ]
    return audit_citations(candidates, _source()).to_dict()


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
