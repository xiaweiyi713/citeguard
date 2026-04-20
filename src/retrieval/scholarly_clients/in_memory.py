"""In-memory scholarly metadata source used by the first prototype."""

from __future__ import annotations

from typing import List, Optional

from src.citation import normalize_text, sequence_similarity, tokenize_text
from src.graph import CitationRecord

from .base import MetadataSource


class InMemoryMetadataSource(MetadataSource):
    """Metadata source backed by an in-memory list of citation records."""

    def __init__(self, records: List[CitationRecord]) -> None:
        self._records = list(records)

    def all_records(self) -> List[CitationRecord]:
        return list(self._records)

    def search(self, query: str, top_k: int = 5) -> List[CitationRecord]:
        query_tokens = set(tokenize_text(query))
        scored = []
        for record in self._records:
            haystack_tokens = set(tokenize_text(f"{record.title} {record.abstract}"))
            overlap = len(query_tokens & haystack_tokens)
            normalized_overlap = overlap / max(len(query_tokens), 1)
            title_similarity = sequence_similarity(query, record.title)
            score = 0.6 * normalized_overlap + 0.4 * title_similarity
            scored.append((score, record))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for score, record in scored[:top_k] if score > 0]

    def lookup(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        normalized_title = normalize_text(candidate.title)
        if candidate.doi:
            for record in self._records:
                if record.doi and record.doi.lower() == candidate.doi.lower():
                    return record
        if candidate.arxiv_id:
            for record in self._records:
                if record.arxiv_id and record.arxiv_id.lower() == candidate.arxiv_id.lower():
                    return record
        for record in self._records:
            if normalize_text(record.title) == normalized_title:
                return record

        best_match: Optional[CitationRecord] = None
        best_score = 0.0
        for record in self._records:
            score = sequence_similarity(candidate.title, record.title)
            if score > best_score:
                best_score = score
                best_match = record
        return best_match if best_score >= 0.85 else None
