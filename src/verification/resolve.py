"""Resolve a candidate citation to a canonical record across metadata sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.citation import author_coverage, sequence_similarity, year_matches
from src.graph import CitationRecord
from src.retrieval.scholarly_clients.base import MetadataSource
from src.retrieval.scholarly_clients.multi_source import MultiSourceMetadataSource
from src.retrieval.scholarly_clients.utils import normalize_arxiv_id, normalize_doi

STRONG_MATCH = 0.70
AMBIGUOUS_MARGIN = 0.05


@dataclass(frozen=True)
class ResolveOutcome:
    best: Optional[CitationRecord]
    score: float
    alternatives: List[CitationRecord]
    sources_checked: List[str]
    sources_responded: List[str]
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

    results: List[CitationRecord] = []
    if candidate.doi or candidate.arxiv_id:
        match = source.lookup(candidate)
        if match is not None:
            results.append(match)
    if query:
        results.extend(source.search(query, top_k=5))

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
        return ResolveOutcome(None, 0.0, [], checked, responded, False)

    best_score, best = scored[0]
    alternatives = [record for _, record in scored[1:4]]
    ambiguous = (
        best_score >= STRONG_MATCH
        and len(scored) > 1
        and (best_score - scored[1][0]) < AMBIGUOUS_MARGIN
        and not (candidate.doi or candidate.arxiv_id)
    )
    return ResolveOutcome(best, best_score, alternatives, checked, responded, ambiguous)
