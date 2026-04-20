"""Crossref adapter."""

from __future__ import annotations

from typing import List, Optional
from urllib.parse import quote

from src.graph import CitationRecord

from .base import MetadataSource
from .evidence import attach_evidence_chunks, harvest_remote_evidence
from .http import HTTPClient
from .utils import find_local_match, normalize_doi, record_match_score, stable_record_id, strip_tags


class CrossrefMetadataSource(MetadataSource):
    """Metadata source backed by the Crossref works API."""

    name = "crossref"
    BASE_URL = "https://api.crossref.org/works"

    def __init__(
        self,
        mailto: str = "research@example.com",
        http_client: Optional[HTTPClient] = None,
    ) -> None:
        self.mailto = mailto
        self.http_client = http_client or HTTPClient()
        self._records: List[CitationRecord] = []

    def all_records(self) -> List[CitationRecord]:
        return list(self._records)

    def search(self, query: str, top_k: int = 5) -> List[CitationRecord]:
        payload = self.http_client.get_json(
            self.BASE_URL,
            params={"query.bibliographic": query, "rows": top_k, "mailto": self.mailto},
        )
        items = payload.get("message", {}).get("items", [])
        records = [self._to_record(item) for item in items[:top_k]]
        self._remember(records)
        return records

    def lookup(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        local_match = find_local_match(candidate, self._records)
        if local_match is not None:
            return local_match

        if candidate.doi:
            payload = self.http_client.get_json(
                f"{self.BASE_URL}/{quote(normalize_doi(candidate.doi), safe='')}",
                params={"mailto": self.mailto},
            )
            message = payload.get("message")
            if message:
                record = self._to_record(message)
                self._remember([record])
                return record

        candidates = self.search(candidate.title, top_k=3)
        best = max(candidates, key=lambda record: record_match_score(candidate, record), default=None)
        return best if best and record_match_score(candidate, best) >= 0.70 else None

    def _remember(self, records: List[CitationRecord]) -> None:
        existing = {item.citation_id for item in self._records}
        self._records.extend(record for record in records if record.citation_id not in existing)

    def _to_record(self, item: dict) -> CitationRecord:
        authors = []
        for author in item.get("author", []):
            given = author.get("given", "")
            family = author.get("family", "")
            full_name = " ".join(part for part in [given, family] if part).strip()
            if full_name:
                authors.append(full_name)

        title_list = item.get("title", [])
        venue_list = item.get("container-title", [])
        issued = item.get("issued", {}).get("date-parts", [[]])
        year = issued[0][0] if issued and issued[0] else None
        doi = normalize_doi(item.get("DOI", ""))
        identifier = doi or item.get("URL", "") or "crossref"
        evidence_chunks = harvest_remote_evidence(
            self.http_client,
            urls=[
                item.get("URL", ""),
                *(link.get("URL", "") for link in item.get("link", []) if link.get("URL")),
                f"https://doi.org/{doi}" if doi else "",
            ],
            source_name=self.name,
        )
        return CitationRecord(
            citation_id=stable_record_id("crossref", identifier),
            title=title_list[0] if title_list else "",
            authors=authors,
            year=year,
            venue=venue_list[0] if venue_list else "",
            abstract=strip_tags(item.get("abstract", "")),
            doi=doi,
            url=item.get("URL", ""),
            source=self.name,
            metadata=attach_evidence_chunks(
                {
                    "source_score": 0.0,
                    "type": item.get("type", ""),
                    "is_referenced_by_count": item.get("is-referenced-by-count", 0),
                },
                evidence_chunks,
            ),
        )
