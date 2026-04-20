"""Metadata source interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from src.graph import CitationRecord


class MetadataSource(ABC):
    """Interface used by verifiers to resolve canonical citation records."""

    name = "metadata_source"

    @abstractmethod
    def all_records(self) -> List[CitationRecord]:
        """Return all local records."""

    @abstractmethod
    def search(self, query: str, top_k: int = 5) -> List[CitationRecord]:
        """Search for records by free text query."""

    @abstractmethod
    def lookup(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        """Find the canonical record that best matches the candidate."""
