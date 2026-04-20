"""Semantic Scholar adapter."""

from __future__ import annotations

import os
from typing import List, Optional
from urllib.parse import quote

from src.graph import CitationRecord

from .base import MetadataSource
from .http import HTTPClient
from .utils import find_local_match, normalize_arxiv_id, normalize_doi, record_match_score, stable_record_id


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
        records = [self._to_record(item) for item in items[:top_k]]
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
            if payload.get("title"):
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
        authors = [
            author.get("name", "")
            for author in item.get("authors", [])
            if author.get("name")
        ]
        external_ids = item.get("externalIds", {}) or {}
        doi = normalize_doi(external_ids.get("DOI", ""))
        arxiv_id = normalize_arxiv_id(external_ids.get("ArXiv", "") or external_ids.get("ARXIV", ""))
        identifier = item.get("paperId", "") or doi or arxiv_id or item.get("title", "")
        return CitationRecord(
            citation_id=stable_record_id("s2", identifier),
            title=item.get("title", ""),
            authors=authors,
            year=item.get("year"),
            venue=item.get("venue", ""),
            abstract=item.get("abstract", "") or "",
            doi=doi,
            arxiv_id=arxiv_id,
            url=item.get("url", ""),
            source=self.name,
            metadata={"source_score": 0.0, "paper_id": item.get("paperId", "")},
        )
