"""Factory helpers for scholarly metadata sources."""

from __future__ import annotations

from typing import Iterable, List

from citeguard.version import __version__

from .arxiv import ArxivMetadataSource
from .base import MetadataSource
from .crossref import CrossrefMetadataSource
from .http import HTTPClient
from .multi_source import MultiSourceMetadataSource
from .openalex import OpenAlexMetadataSource
from .semantic_scholar import SemanticScholarMetadataSource
from .utils import configured_contact_email

DEFAULT_CONTACT_EMAIL = "research@example.com"
DEFAULT_USER_AGENT = f"CiteGuard/{__version__}"


def build_live_metadata_source(
    source_names: Iterable[str],
    mailto: str = DEFAULT_CONTACT_EMAIL,
    semantic_scholar_api_key: str = "",
    http_timeout: int = 15,
    http_retries: int = 1,
    http_retry_backoff: float = 0.2,
    http_min_interval: float = 0.0,
    harvest_remote_evidence: bool = False,
    evidence_timeout: int = 4,
    source_budget: float = 8.0,
) -> MetadataSource:
    """Create a multi-source metadata adapter from a list of source names."""

    sources: List[MetadataSource] = []
    contact_email = configured_contact_email(mailto)
    for name in source_names:
        normalized = name.strip().lower()
        http_client = HTTPClient(
            timeout=http_timeout,
            user_agent=polite_user_agent(mailto),
            retries=http_retries,
            retry_backoff=http_retry_backoff,
            min_interval=http_min_interval,
        )
        if normalized == "openalex":
            sources.append(
                OpenAlexMetadataSource(
                    mailto=contact_email,
                    http_client=http_client,
                    harvest_evidence=harvest_remote_evidence,
                    evidence_timeout=evidence_timeout,
                )
            )
        elif normalized == "crossref":
            sources.append(
                CrossrefMetadataSource(
                    mailto=contact_email,
                    http_client=http_client,
                    harvest_evidence=harvest_remote_evidence,
                    evidence_timeout=evidence_timeout,
                )
            )
        elif normalized == "arxiv":
            sources.append(
                ArxivMetadataSource(
                    http_client=http_client,
                    harvest_evidence=harvest_remote_evidence,
                    evidence_timeout=evidence_timeout,
                )
            )
        elif normalized in {"semantic-scholar", "semantic_scholar", "semanticscholar", "s2"}:
            sources.append(
                SemanticScholarMetadataSource(
                    api_key=semantic_scholar_api_key,
                    http_client=http_client,
                )
            )

    if not sources:
        raise ValueError("No valid scholarly sources were selected.")
    if len(sources) == 1:
        return sources[0]
    return MultiSourceMetadataSource(sources, budget_seconds=source_budget)


def polite_user_agent(mailto: str = DEFAULT_CONTACT_EMAIL) -> str:
    """Return a polite scholarly-source User-Agent with contact info when configured."""

    contact = configured_contact_email(mailto)
    if contact:
        return f"{DEFAULT_USER_AGENT} (mailto:{contact})"
    return DEFAULT_USER_AGENT
