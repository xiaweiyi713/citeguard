"""Scholarly metadata source adapters."""

from .base import MetadataSource
from .factory import build_live_metadata_source
from .http import HTTPClient
from .in_memory import InMemoryMetadataSource
from .multi_source import MultiSourceMetadataSource


def __getattr__(name: str):
    if name == "ArxivMetadataSource":
        from .arxiv import ArxivMetadataSource

        return ArxivMetadataSource
    if name == "CrossrefMetadataSource":
        from .crossref import CrossrefMetadataSource

        return CrossrefMetadataSource
    if name == "OpenAlexMetadataSource":
        from .openalex import OpenAlexMetadataSource

        return OpenAlexMetadataSource
    if name == "SemanticScholarMetadataSource":
        from .semantic_scholar import SemanticScholarMetadataSource

        return SemanticScholarMetadataSource
    raise AttributeError(f"module 'citeguard.retrieval.scholarly_clients' has no attribute {name!r}")

__all__ = [
    "ArxivMetadataSource",
    "CrossrefMetadataSource",
    "HTTPClient",
    "InMemoryMetadataSource",
    "MetadataSource",
    "MultiSourceMetadataSource",
    "OpenAlexMetadataSource",
    "SemanticScholarMetadataSource",
    "build_live_metadata_source",
]
