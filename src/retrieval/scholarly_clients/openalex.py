"""OpenAlex adapter."""

from __future__ import annotations

from typing import List, Optional

from src.graph import CitationRecord

from .base import MetadataSource
from .evidence import attach_evidence_chunks, harvest_remote_evidence
from .http import HTTPClient
from .utils import find_local_match, normalize_doi, openalex_abstract_to_text, record_match_score


class OpenAlexMetadataSource(MetadataSource):
    """Metadata source backed by the OpenAlex works API."""

    name = "openalex"
    BASE_URL = "https://api.openalex.org/works"

    def __init__(self, http_client: Optional[HTTPClient] = None) -> None:
        self.http_client = http_client or HTTPClient()
        self._records: List[CitationRecord] = []

    def all_records(self) -> List[CitationRecord]:
        return list(self._records)

    def search(self, query: str, top_k: int = 5) -> List[CitationRecord]:
        payload = self.http_client.get_json(
            self.BASE_URL,
            params={"search": query, "per-page": top_k},
        )
        records = [self._to_record(item) for item in payload.get("results", [])[:top_k]]
        self._remember(records)
        return records

    def lookup(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        local_match = find_local_match(candidate, self._records)
        if local_match is not None:
            return local_match

        if candidate.doi:
            payload = self.http_client.get_json(
                self.BASE_URL,
                params={"filter": f"doi:{normalize_doi(candidate.doi)}", "per-page": 1},
            )
            results = payload.get("results", [])
            if results:
                record = self._to_record(results[0])
                self._remember([record])
                return record

        candidates = self.search(candidate.title, top_k=3)
        best = max(candidates, key=lambda record: record_match_score(candidate, record), default=None)
        return best if best and record_match_score(candidate, best) >= 0.70 else None

    def _remember(self, records: List[CitationRecord]) -> None:
        self._records.extend(record for record in records if record.citation_id not in {item.citation_id for item in self._records})

    def _to_record(self, item: dict) -> CitationRecord:
        authors = [
            authorship.get("author", {}).get("display_name", "")
            for authorship in item.get("authorships", [])
            if authorship.get("author", {}).get("display_name")
        ]
        venue = (
            item.get("primary_location", {}).get("source", {}).get("display_name")
            or item.get("host_venue", {}).get("display_name", "")
        )
        doi = normalize_doi(item.get("doi", "") or item.get("ids", {}).get("doi", ""))
        evidence_chunks = harvest_remote_evidence(
            self.http_client,
            urls=[
                item.get("primary_location", {}).get("landing_page_url", ""),
                item.get("best_oa_location", {}).get("landing_page_url", ""),
            ],
            source_name=self.name,
        )
        record = CitationRecord(
            citation_id=item.get("id", "").replace("https://openalex.org/", "openalex:"),
            title=item.get("display_name", "") or item.get("title", ""),
            authors=authors,
            year=item.get("publication_year"),
            venue=venue,
            abstract=openalex_abstract_to_text(item.get("abstract_inverted_index", {})),
            doi=doi,
            url=item.get("primary_location", {}).get("landing_page_url", "") or item.get("id", ""),
            source=self.name,
            metadata=attach_evidence_chunks(
                {
                    "openalex_id": item.get("id", ""),
                    "source_score": float(item.get("relevance_score", 0.0)),
                    "cited_by_count": item.get("cited_by_count", 0),
                },
                evidence_chunks,
            ),
        )
        return record
