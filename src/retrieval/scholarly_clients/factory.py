"""Factory helpers for scholarly metadata sources."""

from __future__ import annotations

from typing import Iterable, List

from .arxiv import ArxivMetadataSource
from .base import MetadataSource
from .crossref import CrossrefMetadataSource
from .multi_source import MultiSourceMetadataSource
from .openalex import OpenAlexMetadataSource
from .semantic_scholar import SemanticScholarMetadataSource


def build_live_metadata_source(
    source_names: Iterable[str],
    mailto: str = "research@example.com",
    semantic_scholar_api_key: str = "",
) -> MetadataSource:
    """Create a multi-source metadata adapter from a list of source names."""

    sources: List[MetadataSource] = []
    for name in source_names:
        normalized = name.strip().lower()
        if normalized == "openalex":
            sources.append(OpenAlexMetadataSource())
        elif normalized == "crossref":
            sources.append(CrossrefMetadataSource(mailto=mailto))
        elif normalized == "arxiv":
            sources.append(ArxivMetadataSource())
        elif normalized in {"semantic-scholar", "semantic_scholar", "semanticscholar", "s2"}:
            sources.append(SemanticScholarMetadataSource(api_key=semantic_scholar_api_key))

    if not sources:
        raise ValueError("No valid scholarly sources were selected.")
    if len(sources) == 1:
        return sources[0]
    return MultiSourceMetadataSource(sources)
