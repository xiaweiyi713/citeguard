"""Scholarly metadata source adapters."""

from .base import MetadataSource
from .arxiv import ArxivMetadataSource
from .crossref import CrossrefMetadataSource
from .factory import build_live_metadata_source
from .in_memory import InMemoryMetadataSource
from .multi_source import MultiSourceMetadataSource
from .openalex import OpenAlexMetadataSource
from .semantic_scholar import SemanticScholarMetadataSource

__all__ = [
    "ArxivMetadataSource",
    "CrossrefMetadataSource",
    "build_live_metadata_source",
    "InMemoryMetadataSource",
    "MetadataSource",
    "MultiSourceMetadataSource",
    "OpenAlexMetadataSource",
    "SemanticScholarMetadataSource",
]
