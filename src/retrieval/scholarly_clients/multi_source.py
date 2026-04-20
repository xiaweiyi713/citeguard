"""Aggregator over multiple scholarly metadata sources."""

from __future__ import annotations

from typing import Iterable, List, Optional

from src.citation import sequence_similarity, tokenize_text
from src.graph import CitationRecord

from .base import MetadataSource
from .utils import merge_record_list, record_match_score


class MultiSourceMetadataSource(MetadataSource):
    """Aggregates several scholarly sources and deduplicates their outputs."""

    name = "multi_source"

    def __init__(self, sources: Iterable[MetadataSource]) -> None:
        self.sources = list(sources)

    def all_records(self) -> List[CitationRecord]:
        return merge_record_list(
            record
            for source in self.sources
            for record in source.all_records()
        )

    def search(self, query: str, top_k: int = 5) -> List[CitationRecord]:
        per_source = max(top_k, 3)
        merged: List[CitationRecord] = []
        for source in self.sources:
            merged.extend(source.search(query, top_k=per_source))
        ranked = self._rank(query, merge_record_list(merged))
        return ranked[:top_k]

    def lookup(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        matches = []
        for source in self.sources:
            match = source.lookup(candidate)
            if match is not None:
                matches.append(match)
        if not matches:
            return None
        ranked = sorted(
            merge_record_list(matches),
            key=lambda record: record_match_score(candidate, record),
            reverse=True,
        )
        best = ranked[0]
        return best if record_match_score(candidate, best) >= 0.70 else None

    def _rank(self, query: str, records: List[CitationRecord]) -> List[CitationRecord]:
        query_tokens = set(tokenize_text(query))

        def score(record: CitationRecord) -> float:
            title_similarity = sequence_similarity(query, record.title)
            overlap = len(query_tokens & set(tokenize_text(f"{record.title} {record.abstract}")))
            normalized_overlap = overlap / max(len(query_tokens), 1)
            source_score = float(record.metadata.get("source_score", 0.0))
            completeness = min(1.0, sum(bool(value) for value in [
                record.authors,
                record.year,
                record.venue,
                record.abstract,
                record.doi,
                record.url,
            ]) / 6.0)
            return 0.35 * normalized_overlap + 0.30 * title_similarity + 0.20 * source_score + 0.15 * completeness

        return sorted(records, key=score, reverse=True)
