"""Sparse lexical retrieval."""

from __future__ import annotations

import math
from collections import Counter
from typing import Dict, List

from src.citation import tokenize_text
from src.graph import CitationRecord

from .types import RetrievedCitation


class BM25LikeRetriever:
    """A dependency-free BM25-inspired retriever for local experiments."""

    def __init__(self, corpus: List[CitationRecord], k1: float = 1.2, b: float = 0.75) -> None:
        self.corpus = list(corpus)
        self.k1 = k1
        self.b = b
        self._documents = [tokenize_text(f"{record.title} {record.abstract}") for record in self.corpus]
        self._lengths = [len(document) for document in self._documents]
        self._average_length = sum(self._lengths) / max(len(self._lengths), 1)
        self._doc_frequencies = self._build_doc_frequencies()

    def _build_doc_frequencies(self) -> Dict[str, int]:
        frequencies: Dict[str, int] = {}
        for document in self._documents:
            for token in set(document):
                frequencies[token] = frequencies.get(token, 0) + 1
        return frequencies

    def search(self, query: str, top_k: int = 5) -> List[RetrievedCitation]:
        query_tokens = tokenize_text(query)
        scored = []
        num_docs = max(len(self.corpus), 1)
        for record, document_tokens, doc_len in zip(self.corpus, self._documents, self._lengths):
            tf = Counter(document_tokens)
            score = 0.0
            for token in query_tokens:
                df = self._doc_frequencies.get(token, 0)
                if df == 0:
                    continue
                idf = math.log(1 + ((num_docs - df + 0.5) / (df + 0.5)))
                numerator = tf[token] * (self.k1 + 1)
                denominator = tf[token] + self.k1 * (
                    1 - self.b + self.b * (doc_len / max(self._average_length, 1))
                )
                score += idf * (numerator / max(denominator, 1e-9))
            scored.append(
                RetrievedCitation(
                    citation=record,
                    score=score,
                    retriever_name=self.__class__.__name__,
                )
            )
        scored.sort(key=lambda item: item.score, reverse=True)
        return [item for item in scored[:top_k] if item.score > 0]
