"""Retriever that delegates to a metadata source search endpoint."""

from __future__ import annotations

from typing import List

from src.citation import sequence_similarity, tokenize_text
from src.retrieval.scholarly_clients import MetadataSource

from .types import RetrievedCitation


class MetadataSourceRetriever:
    """Uses a metadata source directly when a local corpus is not preloaded."""

    def __init__(self, metadata_source: MetadataSource) -> None:
        self.metadata_source = metadata_source

    def search(self, query: str, top_k: int = 5) -> List[RetrievedCitation]:
        records = self.metadata_source.search(query, top_k=top_k)
        query_tokens = set(tokenize_text(query))
        results = []
        for record in records:
            overlap = len(query_tokens & set(tokenize_text(f"{record.title} {record.abstract}")))
            normalized_overlap = overlap / max(len(query_tokens), 1)
            title_similarity = sequence_similarity(query, record.title)
            source_score = float(record.metadata.get("source_score", 0.0))
            score = 0.45 * normalized_overlap + 0.35 * title_similarity + 0.20 * source_score
            results.append(
                RetrievedCitation(
                    citation=record,
                    score=score,
                    retriever_name=self.__class__.__name__,
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]
