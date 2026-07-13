"""Crossref adapter."""

from __future__ import annotations

import re
from typing import Any, List, Optional
from urllib.parse import quote

from citeguard.graph import CitationRecord

from .base import MetadataSource
from .evidence import attach_evidence_chunks, harvest_remote_evidence_report
from .http import HTTPClient
from .utils import (
    configured_contact_email,
    find_local_match,
    metadata_quality,
    normalize_doi,
    record_match_score,
    stable_record_id,
    strip_tags,
)


# Crossref's bibliographic search does not tokenize CJK text, so
# predominantly-CJK queries return unrelated results; skip the wasted call.
# DOI lookups are unaffected and remain the reliable path for Chinese papers.
_CJK_CHAR_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def _mostly_cjk(query: str) -> bool:
    chars = [char for char in (query or "") if not char.isspace()]
    if not chars:
        return False
    cjk = sum(1 for char in chars if _CJK_CHAR_RE.match(char))
    return cjk / len(chars) >= 0.5


class CrossrefMetadataSource(MetadataSource):
    """Metadata source backed by the Crossref works API."""

    name = "crossref"
    BASE_URL = "https://api.crossref.org/works"

    def __init__(
        self,
        mailto: str = "",
        http_client: Optional[HTTPClient] = None,
        harvest_evidence: bool = True,
        evidence_timeout: int = 4,
    ) -> None:
        self.mailto = configured_contact_email(mailto)
        self.http_client = http_client or HTTPClient()
        self.harvest_evidence = harvest_evidence
        self.evidence_timeout = evidence_timeout
        self._records: List[CitationRecord] = []

    def all_records(self) -> List[CitationRecord]:
        return list(self._records)

    def search(self, query: str, top_k: int = 5) -> List[CitationRecord]:
        if _mostly_cjk(query):
            return []
        params = {"query.bibliographic": query, "rows": top_k}
        if self.mailto:
            params["mailto"] = self.mailto
        payload = self.http_client.get_json(
            self.BASE_URL,
            params=params,
        )
        items = payload.get("message", {}).get("items", [])
        records = [self._to_record(item) for item in items[:top_k]]
        self._remember(records)
        return records

    def lookup_identifier(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        if not candidate.doi:
            return None
        params = {}
        if self.mailto:
            params["mailto"] = self.mailto
        payload = self.http_client.get_json(
            f"{self.BASE_URL}/{quote(normalize_doi(candidate.doi), safe='')}",
            params=params,
        )
        message = payload.get("message")
        if message:
            record = self._to_record(message)
            self._remember([record])
            return record
        return None

    def lookup(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        local_match = find_local_match(candidate, self._records)
        if local_match is not None:
            return local_match

        identified = self.lookup_identifier(candidate)
        if identified is not None:
            return identified

        candidates = self.search(candidate.title, top_k=3)
        best = max(candidates, key=lambda record: record_match_score(candidate, record), default=None)
        return best if best and record_match_score(candidate, best) >= 0.70 else None

    def _remember(self, records: List[CitationRecord]) -> None:
        existing = {item.citation_id for item in self._records}
        self._records.extend(record for record in records if record.citation_id not in existing)

    def _to_record(self, item: dict) -> CitationRecord:
        authors = []
        for author in _as_list(item.get("author")):
            if not isinstance(author, dict):
                continue
            given = _text(author.get("given", ""))
            family = _text(author.get("family", ""))
            full_name = " ".join(part for part in [given, family] if part).strip()
            if full_name:
                authors.append(full_name)

        title = _first_text(item.get("title"))
        venue = _first_text(item.get("container-title"))
        year = _issued_year(item.get("issued"))
        doi = normalize_doi(_text(item.get("DOI", "")))
        url = str(item.get("URL") or "")
        abstract = strip_tags(_text(item.get("abstract", "")))
        identifier = doi or url or title or "crossref"
        evidence_chunks = []
        evidence_failures = []
        if self.harvest_evidence:
            evidence_report = harvest_remote_evidence_report(
                self.http_client,
                urls=[
                    url,
                    *(_link_url(link) for link in _as_list(item.get("link"))),
                    f"https://doi.org/{doi}" if doi else "",
                ],
                source_name=self.name,
                timeout=self.evidence_timeout,
            )
            evidence_chunks = evidence_report["chunks"]
            evidence_failures = evidence_report["failures"]
        metadata = {
            "source_score": 0.0,
            "type": item.get("type", ""),
            "is_referenced_by_count": item.get("is-referenced-by-count", 0),
            "metadata_quality": metadata_quality(
                title=title,
                authors=authors,
                year=year,
                venue=venue,
                abstract=abstract,
                doi=doi,
                url=url,
            ),
        }
        if evidence_failures:
            metadata["evidence_harvest_failures"] = evidence_failures
        return CitationRecord(
            citation_id=stable_record_id("crossref", identifier),
            title=title,
            authors=authors,
            year=year,
            venue=venue,
            abstract=abstract,
            doi=doi,
            url=url,
            source=self.name,
            metadata=attach_evidence_chunks(metadata, evidence_chunks),
        )


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _first_text(value: Any) -> str:
    for item in _as_list(value):
        text = _text(item)
        if text:
            return text
    return ""


def _text(value: Any) -> str:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return ""
    return str(value).strip()


def _issued_year(value: Any) -> Optional[int]:
    if not isinstance(value, dict):
        return None
    date_parts = value.get("date-parts")
    if not isinstance(date_parts, list):
        return None
    for part in date_parts:
        if not isinstance(part, list) or not part:
            continue
        try:
            return int(part[0])
        except (TypeError, ValueError):
            continue
    return None


def _link_url(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    return str(value.get("URL") or "")
