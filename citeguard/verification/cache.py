"""A MetadataSource decorator that persists search/lookup results in SQLite."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from citeguard.citation import normalize_text
from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients.base import MetadataSource
from citeguard.retrieval.scholarly_clients.utils import canonical_record_key, record_match_score

CACHE_SCHEMA_VERSION = 2


class CachingMetadataSource(MetadataSource):
    """Wraps another source and memoizes results to a SQLite database."""

    name = "cached"

    def __init__(self, inner: MetadataSource, db_path: str = ":memory:") -> None:
        self.inner = inner
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        initialize_cache_schema(self._conn)

    def all_records(self) -> List[CitationRecord]:
        return self.inner.all_records()

    def search(self, query: str, top_k: int = 5) -> List[CitationRecord]:
        key = f"search:{normalize_text(query)}:{top_k}"
        cached = self._get(key)
        if cached is not None:
            return [CitationRecord(**item) for item in json.loads(cached)]
        records = self.inner.search(query, top_k=top_k)
        if _source_has_failure(self.inner):
            return records
        self._set(
            key,
            json.dumps([asdict(record) for record in records]),
            metadata=_search_cache_metadata(query, top_k, records, self.inner),
        )
        return records

    def lookup(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        key = f"lookup:{canonical_record_key(candidate)}"
        cached = self._get(key)
        if cached is not None:
            payload = json.loads(cached)
            return CitationRecord(**payload) if payload else None
        match = self.inner.lookup(candidate)
        if _source_has_failure(self.inner):
            return match
        self._set(
            key,
            json.dumps(asdict(match) if match else None),
            metadata=_lookup_cache_metadata(candidate, match, self.inner),
        )
        return match

    def _get(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def _set(self, key: str, value: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        now = time.time()
        row = self._conn.execute("SELECT created_at FROM cache WHERE key = ?", (key,)).fetchone()
        created_at = row[0] if row else now
        entry_metadata = dict(metadata or {})
        entry_metadata.setdefault("timestamp", now)
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (key, value, json.dumps(entry_metadata, sort_keys=True), created_at, now),
        )
        self._conn.commit()


def _source_has_failure(source: MetadataSource) -> bool:
    if getattr(source, "last_failures", []):
        return True
    http_client = getattr(source, "http_client", None)
    return bool(getattr(http_client, "last_error_code", ""))


def initialize_cache_schema(conn: sqlite3.Connection) -> None:
    """Create or upgrade the SQLite cache schema in-place."""

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS cache (
            key TEXT PRIMARY KEY,
            value TEXT,
            metadata TEXT,
            created_at REAL NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL DEFAULT 0
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(cache)").fetchall()}
    if "created_at" not in columns:
        conn.execute("ALTER TABLE cache ADD COLUMN created_at REAL NOT NULL DEFAULT 0")
    if "updated_at" not in columns:
        conn.execute("ALTER TABLE cache ADD COLUMN updated_at REAL NOT NULL DEFAULT 0")
    if "metadata" not in columns:
        conn.execute("ALTER TABLE cache ADD COLUMN metadata TEXT")
    conn.execute("CREATE TABLE IF NOT EXISTS cache_metadata (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT OR REPLACE INTO cache_metadata (key, value) VALUES (?, ?)",
        ("schema_version", str(CACHE_SCHEMA_VERSION)),
    )
    conn.commit()


def inspect_cache(db_path: str) -> dict:
    """Return non-sensitive cache statistics for CLI/status surfaces."""

    if db_path == ":memory:":
        return _empty_cache_info(db_path, exists=True)

    path = Path(db_path)
    if not path.exists():
        info = _empty_cache_info(db_path, exists=False)
        info["size_bytes"] = 0
        return info

    conn = sqlite3.connect(db_path)
    try:
        initialize_cache_schema(conn)
        total_entries = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        prefix_counts = {
            "search": conn.execute("SELECT COUNT(*) FROM cache WHERE key LIKE 'search:%'").fetchone()[0],
            "lookup": conn.execute("SELECT COUNT(*) FROM cache WHERE key LIKE 'lookup:%'").fetchone()[0],
            "other": conn.execute(
                "SELECT COUNT(*) FROM cache WHERE key NOT LIKE 'search:%' AND key NOT LIKE 'lookup:%'"
            ).fetchone()[0],
        }
        row = conn.execute("SELECT MIN(created_at), MAX(updated_at) FROM cache").fetchone()
        version_row = conn.execute("SELECT value FROM cache_metadata WHERE key = 'schema_version'").fetchone()
    finally:
        conn.close()

    return {
        "path": db_path,
        "exists": True,
        "schema_version": int(version_row[0]) if version_row else CACHE_SCHEMA_VERSION,
        "entries": total_entries,
        "entry_prefixes": prefix_counts,
        "oldest_entry_timestamp": row[0] or None,
        "newest_entry_timestamp": row[1] or None,
        "size_bytes": path.stat().st_size,
    }


def clear_cache(db_path: str) -> dict:
    """Delete cached lookup/search rows while preserving schema metadata."""

    if db_path == ":memory:":
        return {"path": db_path, "exists": True, "cleared_entries": 0, "schema_version": CACHE_SCHEMA_VERSION}

    path = Path(db_path)
    if not path.exists():
        return {"path": db_path, "exists": False, "cleared_entries": 0, "schema_version": CACHE_SCHEMA_VERSION}

    conn = sqlite3.connect(db_path)
    try:
        initialize_cache_schema(conn)
        cleared = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        conn.execute("DELETE FROM cache")
        conn.commit()
        conn.execute("VACUUM")
        version_row = conn.execute("SELECT value FROM cache_metadata WHERE key = 'schema_version'").fetchone()
    finally:
        conn.close()

    return {
        "path": db_path,
        "exists": True,
        "cleared_entries": cleared,
        "schema_version": int(version_row[0]) if version_row else CACHE_SCHEMA_VERSION,
    }


def export_cache_records(db_path: str, deterministic: bool = False) -> dict:
    """Export cached CitationRecord payloads as a deterministic offline fixture."""

    if db_path == ":memory:" or not Path(db_path).exists():
        return {
            **_empty_cache_export_info(db_path, exists=db_path == ":memory:", deterministic=deterministic),
            "deterministic": deterministic,
            "records": [],
            "record_count": 0,
        }

    conn = sqlite3.connect(db_path)
    try:
        initialize_cache_schema(conn)
        rows = conn.execute("SELECT key, value, metadata, updated_at FROM cache ORDER BY key").fetchall()
    finally:
        conn.close()

    records = _dedupe_records(
        record
        for key, value, metadata, updated_at in rows
        for record in _records_from_cache_value(value, key=key, metadata=metadata, updated_at=updated_at)
    )
    cache_info = inspect_cache(db_path)
    return {
        "path": db_path,
        "exists": True,
        "schema_version": cache_info["schema_version"],
        "cache_entry_count": cache_info["entries"],
        "cache_entry_prefixes": cache_info["entry_prefixes"],
        "cache_oldest_entry_timestamp": None if deterministic else cache_info["oldest_entry_timestamp"],
        "cache_newest_entry_timestamp": None if deterministic else cache_info["newest_entry_timestamp"],
        "exported_at": None if deterministic else time.time(),
        "deterministic": deterministic,
        "record_count": len(records),
        "records": [_record_to_export_dict(record, deterministic=deterministic) for record in records],
    }


def _records_from_cache_value(value: str, key: str, metadata: Optional[str], updated_at: float) -> List[CitationRecord]:
    try:
        payload = json.loads(value)
    except json.JSONDecodeError:
        return []
    entry_metadata = _parse_entry_metadata(metadata)
    records_by_key = {
        item.get("record_key"): item
        for item in entry_metadata.get("records", [])
        if isinstance(item, dict) and item.get("record_key")
    }
    items = payload if isinstance(payload, list) else [payload]
    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            record = CitationRecord(**item)
        except TypeError:
            continue
        metadata = dict(record.metadata)
        metadata.setdefault("cache_key", key)
        if updated_at:
            metadata.setdefault("cache_updated_at", updated_at)
        record_provenance = records_by_key.get(canonical_record_key(record), {})
        _apply_cache_provenance(metadata, entry_metadata, record_provenance, key, updated_at)
        records.append(
            CitationRecord(
                citation_id=record.citation_id,
                title=record.title,
                authors=list(record.authors),
                year=record.year,
                venue=record.venue,
                abstract=record.abstract,
                doi=record.doi,
                arxiv_id=record.arxiv_id,
                url=record.url,
                source=record.source or "cache",
                metadata=metadata,
            )
        )
    return records


def _search_cache_metadata(
    query: str,
    top_k: int,
    records: List[CitationRecord],
    source: MetadataSource,
) -> Dict[str, Any]:
    candidate = CitationRecord(citation_id="cache-query", title=query, source="cache")
    return {
        "operation": "search",
        "source": getattr(source, "name", source.__class__.__name__),
        "query": query,
        "normalized_query": normalize_text(query),
        "top_k": top_k,
        "record_count": len(records),
        "records": [_record_cache_metadata(candidate, record) for record in records],
    }


def _lookup_cache_metadata(
    candidate: CitationRecord,
    match: Optional[CitationRecord],
    source: MetadataSource,
) -> Dict[str, Any]:
    records = [_record_cache_metadata(candidate, match)] if match else []
    return {
        "operation": "lookup",
        "source": getattr(source, "name", source.__class__.__name__),
        "query": canonical_record_key(candidate),
        "candidate": {
            "title": candidate.title,
            "doi": candidate.doi,
            "arxiv_id": candidate.arxiv_id,
            "year": candidate.year,
        },
        "record_count": len(records),
        "records": records,
    }


def _record_cache_metadata(candidate: CitationRecord, record: CitationRecord) -> Dict[str, Any]:
    return {
        "citation_id": record.citation_id,
        "record_key": canonical_record_key(record),
        "source": record.source,
        "raw_match_score": round(record_match_score(candidate, record), 4),
    }


def _parse_entry_metadata(metadata: Optional[str]) -> Dict[str, Any]:
    if not metadata:
        return {}
    try:
        payload = json.loads(metadata)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _apply_cache_provenance(
    metadata: Dict[str, Any],
    entry_metadata: Dict[str, Any],
    record_provenance: Dict[str, Any],
    key: str,
    updated_at: float,
) -> None:
    provenance = {
        "cache_key": key,
        "operation": entry_metadata.get("operation", ""),
        "source": entry_metadata.get("source", ""),
        "query": entry_metadata.get("query", ""),
        "timestamp": updated_at or entry_metadata.get("timestamp"),
        "raw_match_score": record_provenance.get("raw_match_score"),
        "record_source": record_provenance.get("source", ""),
    }
    if "normalized_query" in entry_metadata:
        provenance["normalized_query"] = entry_metadata.get("normalized_query", "")
    if "top_k" in entry_metadata:
        provenance["top_k"] = entry_metadata.get("top_k")
    metadata.setdefault("cache_provenance", provenance)
    metadata.setdefault("cache_operation", provenance["operation"])
    metadata.setdefault("cache_source", provenance["source"])
    metadata.setdefault("cache_query", provenance["query"])
    if provenance["raw_match_score"] is not None:
        metadata.setdefault("cache_raw_match_score", provenance["raw_match_score"])


def _record_to_export_dict(record: CitationRecord, deterministic: bool = False) -> Dict[str, Any]:
    payload = asdict(record)
    if not deterministic:
        return payload
    metadata = dict(payload.get("metadata") or {})
    metadata.pop("cache_updated_at", None)
    provenance = metadata.get("cache_provenance")
    if isinstance(provenance, dict):
        provenance = dict(provenance)
        provenance.pop("timestamp", None)
        metadata["cache_provenance"] = provenance
    payload["metadata"] = metadata
    return payload


def _dedupe_records(records: Iterable[CitationRecord]) -> List[CitationRecord]:
    deduped = []
    seen = set()
    for record in records:
        key = (
            record.doi.lower()
            or record.arxiv_id.lower()
            or f"{record.title.lower()}::{record.source.lower()}"
            or record.citation_id
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return sorted(deduped, key=lambda item: (item.title.lower(), item.year or 0, item.source.lower()))


def _empty_cache_info(db_path: str, exists: bool) -> dict:
    return {
        "path": db_path,
        "exists": exists,
        "schema_version": CACHE_SCHEMA_VERSION,
        "entries": 0,
        "entry_prefixes": {"search": 0, "lookup": 0, "other": 0},
        "oldest_entry_timestamp": None,
        "newest_entry_timestamp": None,
        "size_bytes": 0,
    }


def _empty_cache_export_info(db_path: str, exists: bool, deterministic: bool = False) -> dict:
    return {
        "path": db_path,
        "exists": exists,
        "schema_version": CACHE_SCHEMA_VERSION,
        "cache_entry_count": 0,
        "cache_entry_prefixes": {"search": 0, "lookup": 0, "other": 0},
        "cache_oldest_entry_timestamp": None,
        "cache_newest_entry_timestamp": None,
        "exported_at": None if deterministic else time.time(),
    }
