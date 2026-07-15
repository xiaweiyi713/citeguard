"""Validated environment configuration primitives for CiteGuard runtimes."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Mapping, Optional

DEFAULT_SOURCES = "openalex,crossref,arxiv"
DEFAULT_MAILTO = "research@example.com"
STATUS_SCHEMA_VERSION = 1
SOURCE_HEALTH_SCHEMA_VERSION = 8
POLITE_ACCESS_SCHEMA_VERSION = 1
CONTACT_REQUIRED_SOURCES = {"openalex", "crossref"}
SOURCE_ALIASES = {
    "openalex": "openalex",
    "crossref": "crossref",
    "arxiv": "arxiv",
    "semantic-scholar": "semantic_scholar",
    "semantic_scholar": "semantic_scholar",
    "semanticscholar": "semantic_scholar",
    "s2": "semantic_scholar",
}


def configured_source_names(env: Optional[Mapping[str, str]] = None) -> List[str]:
    """Return source names requested by the environment."""

    active_env = env or os.environ
    raw = active_env.get("CITEGUARD_SOURCES", DEFAULT_SOURCES)
    return [name.strip().lower() for name in raw.split(",") if name.strip()]


def canonical_source_names(names: List[str]) -> List[str]:
    """Validate, canonicalize, and deduplicate scholarly source names."""

    canonical = []
    unknown = []
    for name in names:
        normalized = SOURCE_ALIASES.get(name.strip().lower())
        if normalized is None:
            unknown.append(name)
        elif normalized not in canonical:
            canonical.append(normalized)
    if unknown:
        valid = ", ".join(sorted(SOURCE_ALIASES))
        raise ValueError(f"Unknown CITEGUARD_SOURCES value(s): {', '.join(unknown)}. Valid values: {valid}.")
    if not canonical:
        raise ValueError("CITEGUARD_SOURCES did not contain any valid source names.")
    return canonical


def cache_path(env: Optional[Mapping[str, str]] = None) -> str:
    """Return the SQLite cache path configured for live verification."""

    active_env = env or os.environ
    configured = str(active_env.get("CITEGUARD_CACHE", "")).strip()
    if configured:
        return configured
    if str(active_env.get("XDG_CACHE_HOME", "")).strip():
        root = Path(str(active_env["XDG_CACHE_HOME"])).expanduser()
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Caches"
    elif os.name == "nt" and str(active_env.get("LOCALAPPDATA", "")).strip():
        root = Path(str(active_env["LOCALAPPDATA"])).expanduser()
    else:
        root = Path.home() / ".cache"
    return str(root / "citeguard" / "verification_cache.sqlite")


def cache_ttl(env: Optional[Mapping[str, str]] = None) -> float:
    """Return the positive-result cache TTL in seconds."""

    active_env = env or os.environ
    return _positive_float(active_env.get("CITEGUARD_CACHE_TTL", ""), default=86400.0, name="CITEGUARD_CACHE_TTL")


def negative_cache_ttl(env: Optional[Mapping[str, str]] = None) -> float:
    """Return the shorter empty-result cache TTL in seconds."""

    active_env = env or os.environ
    return _positive_float(
        active_env.get("CITEGUARD_NEGATIVE_CACHE_TTL", ""),
        default=900.0,
        name="CITEGUARD_NEGATIVE_CACHE_TTL",
    )


def fixture_citations_path(env: Optional[Mapping[str, str]] = None) -> str:
    """Return an optional JSON/JSONL citation fixture path for offline runs."""

    active_env = env or os.environ
    return active_env.get("CITEGUARD_FIXTURE_CITATIONS", "")


def http_timeout(env: Optional[Mapping[str, str]] = None) -> int:
    """Return the live-source HTTP timeout in seconds."""

    active_env = env or os.environ
    return _positive_int(active_env.get("CITEGUARD_HTTP_TIMEOUT", ""), default=10, name="CITEGUARD_HTTP_TIMEOUT")


def http_retries(env: Optional[Mapping[str, str]] = None) -> int:
    """Return the number of short retries for transient live-source HTTP failures."""

    active_env = env or os.environ
    return _non_negative_int(active_env.get("CITEGUARD_HTTP_RETRIES", ""), default=1, name="CITEGUARD_HTTP_RETRIES")


def http_retry_backoff(env: Optional[Mapping[str, str]] = None) -> float:
    """Return the base retry backoff in seconds for transient live-source HTTP failures."""

    active_env = env or os.environ
    return _non_negative_float(
        active_env.get("CITEGUARD_HTTP_RETRY_BACKOFF", ""),
        default=0.2,
        name="CITEGUARD_HTTP_RETRY_BACKOFF",
    )


def http_min_interval(env: Optional[Mapping[str, str]] = None) -> float:
    """Return the minimum interval between live-source HTTP requests."""

    active_env = env or os.environ
    return _non_negative_float(
        active_env.get("CITEGUARD_HTTP_MIN_INTERVAL", ""),
        default=0.0,
        name="CITEGUARD_HTTP_MIN_INTERVAL",
    )


def evidence_timeout(env: Optional[Mapping[str, str]] = None) -> int:
    """Return the remote evidence landing-page timeout in seconds."""

    active_env = env or os.environ
    return _positive_int(active_env.get("CITEGUARD_EVIDENCE_TIMEOUT", ""), default=2, name="CITEGUARD_EVIDENCE_TIMEOUT")


def remote_evidence_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Whether live source adapters should fetch remote landing-page evidence."""

    active_env = env or os.environ
    raw = active_env.get("CITEGUARD_REMOTE_EVIDENCE", "0")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def source_budget(env: Optional[Mapping[str, str]] = None) -> float:
    """Total fan-out budget (seconds) for multi-source queries."""

    active_env = env or os.environ
    return _positive_float(
        active_env.get("CITEGUARD_SOURCE_BUDGET", ""),
        default=8.0,
        name="CITEGUARD_SOURCE_BUDGET",
    )


def contact_email_configured(env: Optional[Mapping[str, str]] = None) -> bool:
    """Whether live scholarly-source requests have a non-default contact email."""

    active_env = env or os.environ
    mailto = str(active_env.get("CITEGUARD_MAILTO", DEFAULT_MAILTO)).strip()
    return bool(mailto and mailto != DEFAULT_MAILTO)


def _positive_int(raw: str, default: int, name: str) -> int:
    if raw in {"", None}:
        return default
    try:
        value = int(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer.")
    return value


def _non_negative_int(raw: str, default: int, name: str) -> int:
    if raw in {"", None}:
        return default
    try:
        value = int(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative integer.") from exc
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer.")
    return value


def _non_negative_float(raw: str, default: float, name: str) -> float:
    if raw in {"", None}:
        return default
    try:
        value = float(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a non-negative number.") from exc
    if value < 0:
        raise ValueError(f"{name} must be a non-negative number.")
    return value


def _positive_float(raw: str, default: float, name: str) -> float:
    if raw in {"", None}:
        return default
    try:
        value = float(str(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive number.") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive number.")
    return value
