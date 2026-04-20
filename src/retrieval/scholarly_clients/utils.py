"""Utilities shared across scholarly metadata adapters."""

from __future__ import annotations

import hashlib
import html
import re
from typing import Dict, Iterable, List, Optional

from src.citation import author_coverage, normalize_text, sequence_similarity, year_matches
from src.graph import CitationRecord

from .evidence import merge_evidence_chunks


def stable_record_id(prefix: str, value: str) -> str:
    """Build a deterministic record id when a source lacks a clean local identifier."""

    digest = hashlib.md5(value.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}:{digest}"


def strip_tags(value: str) -> str:
    """Remove simple XML or HTML tags from text."""

    if not value:
        return ""
    text = html.unescape(value)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_doi(doi: str) -> str:
    """Normalize DOI values from URLs or raw identifiers."""

    if not doi:
        return ""
    value = doi.strip()
    value = value.replace("https://doi.org/", "").replace("http://doi.org/", "")
    value = value.replace("doi:", "")
    return value.strip().lower()


def normalize_arxiv_id(arxiv_id: str) -> str:
    """Normalize arXiv ids from URLs or raw identifiers."""

    if not arxiv_id:
        return ""
    value = arxiv_id.strip()
    value = value.replace("https://arxiv.org/abs/", "").replace("http://arxiv.org/abs/", "")
    value = value.replace("arXiv:", "").replace("arxiv:", "")
    return value.strip()


def openalex_abstract_to_text(abstract_index: Dict[str, List[int]]) -> str:
    """Reconstruct an OpenAlex abstract from its inverted index representation."""

    if not abstract_index:
        return ""
    tokens_by_position: Dict[int, str] = {}
    for token, positions in abstract_index.items():
        for position in positions:
            tokens_by_position[position] = token
    return " ".join(tokens_by_position[index] for index in sorted(tokens_by_position))


def record_match_score(candidate: CitationRecord, record: CitationRecord) -> float:
    """Score how well a record matches a candidate citation."""

    score = 0.0
    if candidate.doi and record.doi and normalize_doi(candidate.doi) == normalize_doi(record.doi):
        score += 0.6
    if candidate.arxiv_id and record.arxiv_id and normalize_arxiv_id(candidate.arxiv_id) == normalize_arxiv_id(record.arxiv_id):
        score += 0.6
    score += 0.25 * sequence_similarity(candidate.title, record.title)
    score += 0.10 * author_coverage(candidate.authors, record.authors)
    score += 0.05 if year_matches(candidate.year, record.year) else 0.0
    return min(score, 1.0)


def record_completeness(record: CitationRecord) -> int:
    """Estimate how informative a record is."""

    fields = [
        bool(record.title),
        bool(record.authors),
        bool(record.year),
        bool(record.venue),
        bool(record.abstract),
        bool(record.doi),
        bool(record.arxiv_id),
        bool(record.url),
    ]
    return sum(fields)


def merge_two_records(left: CitationRecord, right: CitationRecord) -> CitationRecord:
    """Merge two records, keeping the richer metadata and tracking provenance."""

    if record_completeness(right) > record_completeness(left):
        preferred, other = right, left
    else:
        preferred, other = left, right

    metadata = dict(other.metadata)
    metadata.update(preferred.metadata)
    sources = set(metadata.get("merged_sources", []))
    sources.add(preferred.source)
    sources.add(other.source)
    metadata["merged_sources"] = sorted(source for source in sources if source)
    metadata["source_score"] = max(
        float(left.metadata.get("source_score", 0.0)),
        float(right.metadata.get("source_score", 0.0)),
    )

    merged_chunks = merge_evidence_chunks(
        preferred.metadata.get("evidence_chunks", []),
        other.metadata.get("evidence_chunks", []),
    )
    if merged_chunks:
        metadata["evidence_chunks"] = merged_chunks
        metadata["evidence_spans"] = [chunk["text"] for chunk in merged_chunks]
    elif preferred.metadata.get("evidence_spans") or other.metadata.get("evidence_spans"):
        text_only_chunks = merge_evidence_chunks(
            preferred.metadata.get("evidence_spans", []),
            other.metadata.get("evidence_spans", []),
        )
        metadata["evidence_chunks"] = text_only_chunks
        metadata["evidence_spans"] = [chunk["text"] for chunk in text_only_chunks]

    return CitationRecord(
        citation_id=preferred.citation_id,
        title=preferred.title or other.title,
        authors=preferred.authors or other.authors,
        year=preferred.year or other.year,
        venue=preferred.venue or other.venue,
        abstract=preferred.abstract or other.abstract,
        doi=normalize_doi(preferred.doi or other.doi),
        arxiv_id=normalize_arxiv_id(preferred.arxiv_id or other.arxiv_id),
        url=preferred.url or other.url,
        source=preferred.source,
        metadata=metadata,
    )


def merge_record_list(records: Iterable[CitationRecord]) -> List[CitationRecord]:
    """Deduplicate records across sources."""

    merged: Dict[str, CitationRecord] = {}
    for record in records:
        key = canonical_record_key(record)
        if key in merged:
            merged[key] = merge_two_records(merged[key], record)
        else:
            merged[key] = record
    return list(merged.values())


def canonical_record_key(record: CitationRecord) -> str:
    """Prefer DOI, then arXiv id, then normalized title for deduplication."""

    if record.doi:
        return f"doi:{normalize_doi(record.doi)}"
    if record.arxiv_id:
        return f"arxiv:{normalize_arxiv_id(record.arxiv_id)}"
    return f"title:{normalize_text(record.title)}"


def find_local_match(
    candidate: CitationRecord,
    records: Iterable[CitationRecord],
    min_score: float = 0.70,
) -> Optional[CitationRecord]:
    """Find the best matching record in a local cache."""

    best_record: Optional[CitationRecord] = None
    best_score = 0.0
    for record in records:
        score = record_match_score(candidate, record)
        if score > best_score:
            best_score = score
            best_record = record
    return best_record if best_score >= min_score else None
