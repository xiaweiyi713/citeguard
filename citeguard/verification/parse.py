"""Parse free-text or structured citation input into a candidate record."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients.utils import (
    normalize_arxiv_id,
    normalize_doi,
    stable_record_id,
)

DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:a-z0-9]+", re.IGNORECASE)
ARXIV_LABELLED_RE = re.compile(r"arxiv:\s*(\d{4}\.\d{4,5})", re.IGNORECASE)
ARXIV_BARE_RE = re.compile(r"\b(\d{4}\.\d{4,5})\b")
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")


def extract_doi(text: str) -> str:
    match = DOI_RE.search(text or "")
    return normalize_doi(match.group(0)) if match else ""


def extract_arxiv_id(text: str) -> str:
    match = ARXIV_LABELLED_RE.search(text or "")
    if match:
        return normalize_arxiv_id(match.group(1))
    match = ARXIV_BARE_RE.search(text or "")
    return normalize_arxiv_id(match.group(1)) if match else ""


def extract_year(text: str) -> Optional[int]:
    match = YEAR_RE.search(text or "")
    return int(match.group(0)) if match else None


def parse_citation(
    raw_text: str = "",
    title: str = "",
    authors: Optional[List[str]] = None,
    year: Optional[int] = None,
    venue: str = "",
    abstract: str = "",
    doi: str = "",
    arxiv_id: str = "",
    evidence_chunks: Optional[List[Any]] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> CitationRecord:
    """Build a candidate CitationRecord from whatever the caller provides.

    `title` is treated as an explicit, comparable title only when passed in.
    When only `raw_text` is given it is used as the search query (stored in
    metadata['raw_text']) and NOT treated as an explicit title.
    """

    authors = list(authors or [])
    doi = normalize_doi(doi) or extract_doi(raw_text)
    arxiv_id = normalize_arxiv_id(arxiv_id) or extract_arxiv_id(raw_text)
    if year is None:
        year = extract_year(raw_text)

    title_explicit = bool(title)
    search_title = title or raw_text
    seed = doi or arxiv_id or search_title or "citation"
    record_metadata = dict(metadata or {})
    record_metadata.update({"raw_text": raw_text, "title_explicit": title_explicit})
    if evidence_chunks:
        record_metadata["evidence_chunks"] = list(evidence_chunks)

    return CitationRecord(
        citation_id=stable_record_id("input", seed),
        title=search_title,
        authors=authors,
        year=year,
        venue=venue,
        abstract=abstract,
        doi=doi,
        arxiv_id=arxiv_id,
        source="input",
        metadata=record_metadata,
    )
