"""arXiv adapter."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import List, Optional

from src.graph import CitationRecord

from .base import MetadataSource
from .evidence import attach_evidence_chunks, harvest_remote_evidence
from .http import HTTPClient
from .utils import find_local_match, normalize_arxiv_id, normalize_doi, record_match_score, stable_record_id


ATOM_NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


class ArxivMetadataSource(MetadataSource):
    """Metadata source backed by the arXiv API."""

    name = "arxiv"
    BASE_URL = "http://export.arxiv.org/api/query"

    def __init__(self, http_client: Optional[HTTPClient] = None) -> None:
        self.http_client = http_client or HTTPClient()
        self._records: List[CitationRecord] = []

    def all_records(self) -> List[CitationRecord]:
        return list(self._records)

    def search(self, query: str, top_k: int = 5) -> List[CitationRecord]:
        payload = self.http_client.get_text(
            self.BASE_URL,
            params={"search_query": f"all:{query}", "start": 0, "max_results": top_k},
        )
        records = self._parse_entries(payload)[:top_k]
        self._remember(records)
        return records

    def lookup(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        local_match = find_local_match(candidate, self._records)
        if local_match is not None:
            return local_match

        if candidate.arxiv_id:
            payload = self.http_client.get_text(
                self.BASE_URL,
                params={"id_list": normalize_arxiv_id(candidate.arxiv_id)},
            )
            records = self._parse_entries(payload)
            if records:
                self._remember(records[:1])
                return records[0]

        candidates = self.search(candidate.title, top_k=3)
        best = max(candidates, key=lambda record: record_match_score(candidate, record), default=None)
        return best if best and record_match_score(candidate, best) >= 0.70 else None

    def _remember(self, records: List[CitationRecord]) -> None:
        existing = {item.citation_id for item in self._records}
        self._records.extend(record for record in records if record.citation_id not in existing)

    def _parse_entries(self, payload: str) -> List[CitationRecord]:
        if not payload:
            return []
        try:
            root = ET.fromstring(payload)
        except ET.ParseError:
            return []

        records: List[CitationRecord] = []
        for entry in root.findall("a:entry", ATOM_NS):
            title = (entry.findtext("a:title", default="", namespaces=ATOM_NS) or "").strip()
            summary = (entry.findtext("a:summary", default="", namespaces=ATOM_NS) or "").strip()
            entry_id = entry.findtext("a:id", default="", namespaces=ATOM_NS) or ""
            arxiv_id = normalize_arxiv_id(entry_id)
            authors = [
                author.findtext("a:name", default="", namespaces=ATOM_NS).strip()
                for author in entry.findall("a:author", ATOM_NS)
                if author.findtext("a:name", default="", namespaces=ATOM_NS).strip()
            ]
            published = entry.findtext("a:published", default="", namespaces=ATOM_NS) or ""
            doi = normalize_doi(entry.findtext("arxiv:doi", default="", namespaces=ATOM_NS) or "")
            evidence_chunks = harvest_remote_evidence(
                self.http_client,
                urls=[
                    f"https://arxiv.org/html/{arxiv_id}" if arxiv_id else "",
                    f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
                    entry_id,
                ],
                source_name=self.name,
            )
            records.append(
                CitationRecord(
                    citation_id=stable_record_id("arxiv", arxiv_id or title),
                    title=title,
                    authors=authors,
                    year=int(published[:4]) if len(published) >= 4 and published[:4].isdigit() else None,
                    venue="arXiv",
                    abstract=" ".join(summary.split()),
                    doi=doi,
                    arxiv_id=arxiv_id,
                    url=entry_id,
                    source=self.name,
                    metadata=attach_evidence_chunks({"source_score": 0.0}, evidence_chunks),
                )
            )
        return records
