"""Hybrid retrieval that combines sparse and dense scores."""

from __future__ import annotations

from typing import Dict, List

from src.graph import CitationRecord

from .bm25_retriever import BM25LikeRetriever
from .dense_retriever import DenseLikeRetriever
from .types import RetrievedCitation


class HybridRetriever:
    """Weighted fusion over lexical and semantic-ish retrievers."""

    def __init__(
        self,
        corpus: List[CitationRecord],
        bm25_weight: float = 0.55,
        dense_weight: float = 0.45,
    ) -> None:
        if bm25_weight <= 0 or dense_weight <= 0:
            raise ValueError("retriever weights must be positive")
        self.bm25 = BM25LikeRetriever(corpus)
        self.dense = DenseLikeRetriever(corpus)
        self.bm25_weight = bm25_weight
        self.dense_weight = dense_weight

    def search(self, query: str, top_k: int = 5) -> List[RetrievedCitation]:
        bm25_results = self.bm25.search(query, top_k=top_k * 2)
        dense_results = self.dense.search(query, top_k=top_k * 2)

        merged: Dict[str, RetrievedCitation] = {}
        for result in bm25_results:
            merged[result.citation.citation_id] = RetrievedCitation(
                citation=result.citation,
                score=result.score * self.bm25_weight,
                retriever_name=self.__class__.__name__,
            )
        for result in dense_results:
            if result.citation.citation_id in merged:
                previous = merged[result.citation.citation_id]
                merged[result.citation.citation_id] = RetrievedCitation(
                    citation=result.citation,
                    score=previous.score + result.score * self.dense_weight,
                    retriever_name=self.__class__.__name__,
                )
            else:
                merged[result.citation.citation_id] = RetrievedCitation(
                    citation=result.citation,
                    score=result.score * self.dense_weight,
                    retriever_name=self.__class__.__name__,
                )

        results = list(merged.values())
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:top_k]
