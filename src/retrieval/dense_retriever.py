"""Dense-like retrieval using cosine similarity over token frequencies."""

from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List

from src.citation import tokenize_text
from src.graph import CitationRecord

from .types import RetrievedCitation


class DenseLikeRetriever:
    """A lightweight semantic-ish retriever without external dependencies."""

    def __init__(self, corpus: List[CitationRecord]) -> None:
        self.corpus = list(corpus)
        self._vectors = [self._vectorize(f"{record.title} {record.abstract}") for record in self.corpus]

    def _vectorize(self, text: str) -> Dict[str, float]:
        tokens = tokenize_text(text)
        counts = Counter(tokens)
        norm = math.sqrt(sum(value * value for value in counts.values())) or 1.0
        return {token: value / norm for token, value in counts.items()}

    def _cosine(self, left: Dict[str, float], right: Dict[str, float]) -> float:
        if len(left) > len(right):
            left, right = right, left
        return sum(weight * right.get(token, 0.0) for token, weight in left.items())

    def search(self, query: str, top_k: int = 5) -> List[RetrievedCitation]:
        query_vector = self._vectorize(query)
        results = []
        for record, vector in zip(self.corpus, self._vectors):
            score = self._cosine(query_vector, vector)
            results.append(
                RetrievedCitation(
                    citation=record,
                    score=score,
                    retriever_name=self.__class__.__name__,
                )
            )
        results.sort(key=lambda item: item.score, reverse=True)
        return [item for item in results[:top_k] if item.score > 0]
