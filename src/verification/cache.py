"""A MetadataSource decorator that persists search/lookup results in SQLite."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from typing import List, Optional

from src.citation import normalize_text
from src.graph import CitationRecord
from src.retrieval.scholarly_clients.base import MetadataSource
from src.retrieval.scholarly_clients.utils import canonical_record_key


class CachingMetadataSource(MetadataSource):
    """Wraps another source and memoizes results to a SQLite database."""

    name = "cached"

    def __init__(self, inner: MetadataSource, db_path: str = ":memory:") -> None:
        self.inner = inner
        self._conn = sqlite3.connect(db_path)
        self._conn.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT)")
        self._conn.commit()

    def all_records(self) -> List[CitationRecord]:
        return self.inner.all_records()

    def search(self, query: str, top_k: int = 5) -> List[CitationRecord]:
        key = f"search:{normalize_text(query)}:{top_k}"
        cached = self._get(key)
        if cached is not None:
            return [CitationRecord(**item) for item in json.loads(cached)]
        records = self.inner.search(query, top_k=top_k)
        self._set(key, json.dumps([asdict(record) for record in records]))
        return records

    def lookup(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        key = f"lookup:{canonical_record_key(candidate)}"
        cached = self._get(key)
        if cached is not None:
            payload = json.loads(cached)
            return CitationRecord(**payload) if payload else None
        match = self.inner.lookup(candidate)
        self._set(key, json.dumps(asdict(match) if match else None))
        return match

    def _get(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _set(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO cache (key, value) VALUES (?, ?)", (key, value))
        self._conn.commit()
