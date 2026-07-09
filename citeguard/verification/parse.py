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
ARXIV_NEW_ID_PATTERN = r"\d{4}\.\d{4,5}"
ARXIV_OLD_ID_PATTERN = r"[a-z][a-z-]*(?:\.[a-z]{2})?/\d{7}"
ARXIV_ID_PATTERN = rf"(?:{ARXIV_NEW_ID_PATTERN}|{ARXIV_OLD_ID_PATTERN})(?:v\d+)?"
ARXIV_LABELLED_RE = re.compile(rf"arxiv:\s*({ARXIV_ID_PATTERN})", re.IGNORECASE)
ARXIV_URL_RE = re.compile(
    rf"https?://arxiv\.org/(?:abs|pdf|html)/({ARXIV_ID_PATTERN})(?:\.pdf)?",
    re.IGNORECASE,
)
ARXIV_BARE_URL_RE = re.compile(
    rf"\barxiv\.org/(?:abs|pdf|html)/({ARXIV_ID_PATTERN})(?:\.pdf)?",
    re.IGNORECASE,
)
ARXIV_BARE_RE = re.compile(rf"\b({ARXIV_ID_PATTERN})\b", re.IGNORECASE)
YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")

# GB/T 7714 (Chinese national standard) document-type markers such as
# [J] journal, [M] monograph, [C] proceedings, [D] thesis, [R] report,
# [S] standard, [P] patent, [N] newspaper, plus /OL-style carrier suffixes.
GBT7714_TYPE_RE = re.compile(r"\[(?P<type>EB|DB|CP|CM|DS|[JMCDRSPNAZG])(?:/(?:OL|CD|DK|MT))?\]")
_GBT7714_AUTHOR_SPLIT_RE = re.compile(r"[,,、;;]")
_GBT7714_ET_AL = {"等", "et al", "et al."}


def extract_doi(text: str) -> str:
    match = DOI_RE.search(text or "")
    return normalize_doi(match.group(0)) if match else ""


def extract_arxiv_id(text: str) -> str:
    match = ARXIV_LABELLED_RE.search(text or "")
    if match:
        return normalize_arxiv_id(match.group(1))
    match = ARXIV_URL_RE.search(text or "")
    if match:
        return normalize_arxiv_id(match.group(1))
    match = ARXIV_BARE_URL_RE.search(text or "")
    if match:
        return normalize_arxiv_id(match.group(1))
    match = ARXIV_BARE_RE.search(text or "")
    return normalize_arxiv_id(match.group(1)) if match else ""


def extract_year(text: str) -> Optional[int]:
    match = YEAR_RE.search(text or "")
    return int(match.group(0)) if match else None


def parse_gbt7714_reference(text: str) -> Optional[Dict[str, Any]]:
    """Parse one GB/T 7714 style reference (the Chinese national standard).

    Handles Chinese and English variants such as
    ``作者1, 作者2. 标题[J]. 期刊名, 年, 卷(期): 页.`` and
    ``CHEN X, LI Y. Some title[C]//Proceedings. City: Publisher, 2020.``.
    Returns None when the text does not look like a GB/T 7714 reference, so
    other free-text parsing stays untouched.
    """

    cleaned = (text or "").strip()
    match = GBT7714_TYPE_RE.search(cleaned)
    if not match:
        return None
    head = cleaned[: match.start()].strip()
    tail = cleaned[match.end() :].strip()
    type_code = match.group("type")

    authors_part, separator, title_part = head.partition(". ")
    if not separator:
        authors_part, separator, title_part = head.partition(".")
    if not separator:
        return None
    title = title_part.strip().rstrip(".").strip()
    authors_raw = authors_part.strip()
    if not title or not authors_raw:
        return None

    authors = [
        author.strip()
        for author in _GBT7714_AUTHOR_SPLIT_RE.split(authors_raw)
        if author.strip() and author.strip().lower() not in _GBT7714_ET_AL
    ]
    if not authors:
        return None

    venue = ""
    extra: Dict[str, Any] = {"type_code": type_code}
    tail = tail.lstrip(".").strip()
    if tail.startswith("//"):
        tail = tail[2:].strip()
    if type_code in {"J", "N", "C"} and tail:
        pieces = re.split(r"[,,]", tail, maxsplit=1)
        venue = pieces[0].strip().rstrip(".").strip()
        if type_code == "C":
            venue = venue.split(". ", 1)[0].strip()
        if len(pieces) > 1 and pieces[1].strip():
            extra["publication_info"] = pieces[1].strip().rstrip(".")
    elif tail:
        extra["publication_info"] = tail.rstrip(".")

    return {"title": title, "authors": authors, "venue": venue, "gbt7714": extra}


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

    record_metadata = dict(metadata or {})
    if raw_text and not title:
        parsed_gbt = parse_gbt7714_reference(raw_text)
        if parsed_gbt:
            title = parsed_gbt["title"]
            if not authors:
                authors = list(parsed_gbt["authors"])
            if not venue:
                venue = parsed_gbt["venue"]
            record_metadata.setdefault("reference_format", "gbt7714")
            record_metadata.setdefault("gbt7714", parsed_gbt["gbt7714"])

    title_explicit = bool(title)
    search_title = title or raw_text
    seed = doi or arxiv_id or search_title or "citation"
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
