"""Semantic Scholar adapter."""

from __future__ import annotations

import os
from typing import List, Optional
from urllib.parse import quote

from citeguard.graph import CitationRecord

from .base import MetadataSource
from .http import HTTPClient
from .utils import (
    find_local_match,
    metadata_quality,
    normalize_arxiv_id,
    normalize_doi,
    record_match_score,
    stable_record_id,
)


class SemanticScholarMetadataSource(MetadataSource):
    """Metadata source backed by the Semantic Scholar Graph API."""

    name = "semantic_scholar"
    BASE_URL = "https://api.semanticscholar.org/graph/v1"
    FIELDS = "title,authors,year,venue,abstract,externalIds,url"

    def __init__(
        self,
        api_key: str = "",
        http_client: Optional[HTTPClient] = None,
    ) -> None:
        self.api_key = api_key or os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
        self.http_client = http_client or HTTPClient()
        self._records: List[CitationRecord] = []

    def all_records(self) -> List[CitationRecord]:
        return list(self._records)

    def search(self, query: str, top_k: int = 5) -> List[CitationRecord]:
        payload = self.http_client.get_json(
            f"{self.BASE_URL}/paper/search",
            params={"query": query, "limit": top_k, "fields": self.FIELDS},
            headers=self._headers(),
        )
        items = payload.get("data", [])
        if not isinstance(items, list):
            items = []
        records = [self._to_record(item) for item in items[:top_k] if isinstance(item, dict)]
        self._remember(records)
        return records

    def lookup(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        local_match = find_local_match(candidate, self._records)
        if local_match is not None:
            return local_match

        identifiers = []
        if candidate.doi:
            identifiers.append(f"DOI:{normalize_doi(candidate.doi)}")
        if candidate.arxiv_id:
            identifiers.append(f"ARXIV:{normalize_arxiv_id(candidate.arxiv_id)}")

        for identifier in identifiers:
            payload = self.http_client.get_json(
                f"{self.BASE_URL}/paper/{quote(identifier, safe='')}",
                params={"fields": self.FIELDS},
                headers=self._headers(),
            )
            if isinstance(payload, dict) and payload.get("title"):
                record = self._to_record(payload)
                self._remember([record])
                return record

        candidates = self.search(candidate.title, top_k=3)
        best = max(candidates, key=lambda record: record_match_score(candidate, record), default=None)
        return best if best and record_match_score(candidate, best) >= 0.70 else None

    def _headers(self) -> dict:
        headers = {}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    def _remember(self, records: List[CitationRecord]) -> None:
        existing = {item.citation_id for item in self._records}
        self._records.extend(record for record in records if record.citation_id not in existing)

    def _to_record(self, item: dict) -> CitationRecord:
        authors = []
        raw_authors = item.get("authors", [])
        if isinstance(raw_authors, dict):
            raw_authors = [raw_authors]
        if not isinstance(raw_authors, list):
            raw_authors = []
        for author in raw_authors:
            name = ""
            if isinstance(author, dict):
                name = _safe_text(author.get("name", ""))
            elif isinstance(author, str):
                name = author.strip()
            if name:
                authors.append(name)

        external_ids = item.get("externalIds", {})
        if not isinstance(external_ids, dict):
            external_ids = {}
        doi = normalize_doi(_safe_text(external_ids.get("DOI", "")))
        arxiv_id = normalize_arxiv_id(
            _safe_text(external_ids.get("ArXiv", "")) or _safe_text(external_ids.get("ARXIV", ""))
        )
        title = _safe_text(item.get("title", ""))
        year = _safe_year(item.get("year"))
        venue = _safe_text(item.get("venue", ""))
        abstract = _safe_text(item.get("abstract", ""))
        url = _safe_text(item.get("url", ""))
        identifier = _safe_text(item.get("paperId", "")) or doi or arxiv_id or title
        return CitationRecord(
            citation_id=stable_record_id("s2", identifier),
            title=title,
            authors=authors,
            year=year,
            venue=venue,
            abstract=abstract,
            doi=doi,
            arxiv_id=arxiv_id,
            url=url,
            source=self.name,
            metadata={
                "source_score": 0.0,
                "paper_id": _safe_text(item.get("paperId", "")),
                "metadata_quality": metadata_quality(
                    title=title,
                    authors=authors,
                    year=year,
                    venue=venue,
                    abstract=abstract,
                    doi=doi,
                    arxiv_id=arxiv_id,
                    url=url,
                ),
            },
        )


def _safe_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _safe_year(value: object) -> Optional[int]:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None
