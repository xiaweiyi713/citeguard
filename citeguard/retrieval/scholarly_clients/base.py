"""Metadata source interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from citeguard.graph import CitationRecord


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

    def lookup_identifier(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        """Resolve strictly by persistent identifier (DOI/arXiv id).

        Returns None when this source does not support the candidate's
        identifier or the identifier has no record. Implementations must NOT
        fall back to title search here; that separation lets callers detect
        identifier-path failures reliably.
        """
        return None
