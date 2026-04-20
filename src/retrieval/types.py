"""Shared retrieval types."""

from __future__ import annotations

from dataclasses import dataclass

from src.graph import CitationRecord


@dataclass(frozen=True)
class RetrievedCitation:
    """Citation candidate emitted by a retriever."""

    citation: CitationRecord
    score: float
    retriever_name: str
