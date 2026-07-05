"""Runtime configuration helpers shared by CLI and MCP surfaces."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import socket
import sys
import time
from typing import Callable, Mapping, List, Optional

from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients import build_live_metadata_source
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.retrieval.scholarly_clients.evidence import BLOCKED_EVIDENCE_HOST_SUFFIXES
from citeguard.retrieval.scholarly_clients.factory import polite_user_agent
from citeguard.verification import CachingMetadataSource, inspect_cache, source_failure_recovery_code, stable_next_action

DEFAULT_SOURCES = "openalex,crossref,arxiv"
DEFAULT_MAILTO = "research@example.com"
STATUS_SCHEMA_VERSION = 1
SOURCE_HEALTH_SCHEMA_VERSION = 2
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
    return active_env.get("CITEGUARD_CACHE", os.path.join("data", "logs", "verification_cache.sqlite"))


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


def evidence_timeout(env: Optional[Mapping[str, str]] = None) -> int:
    """Return the remote evidence landing-page timeout in seconds."""

    active_env = env or os.environ
    return _positive_int(active_env.get("CITEGUARD_EVIDENCE_TIMEOUT", ""), default=2, name="CITEGUARD_EVIDENCE_TIMEOUT")


def remote_evidence_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Whether live source adapters should fetch remote landing-page evidence."""

    active_env = env or os.environ
    raw = active_env.get("CITEGUARD_REMOTE_EVIDENCE", "0")
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def contact_email_configured(env: Optional[Mapping[str, str]] = None) -> bool:
    """Whether live scholarly-source requests have a non-default contact email."""

    active_env = env or os.environ
    mailto = str(active_env.get("CITEGUARD_MAILTO", DEFAULT_MAILTO)).strip()
    return bool(mailto and mailto != DEFAULT_MAILTO)


def polite_access_status(env: Optional[Mapping[str, str]] = None) -> dict:
    """Return a machine-readable compliance hint for polite source access."""

    active_env = env or os.environ
    requested = configured_source_names(active_env)
    fixture_path = fixture_citations_path(active_env)
    contact_configured = contact_email_configured(active_env)
    canonical = []
    for requested_name in requested:
        normalized = SOURCE_ALIASES.get(requested_name.strip().lower())
        if normalized and normalized not in canonical:
            canonical.append(normalized)
    configured_contact_sources = [name for name in canonical if name in CONTACT_REQUIRED_SOURCES]
    fixture_mode = bool(fixture_path)
    compliant = bool(fixture_mode or contact_configured or not configured_contact_sources)
    if fixture_mode:
        status = "fixture_bypasses_live_sources"
    elif not configured_contact_sources:
        status = "not_required"
    elif contact_configured:
        status = "configured"
    else:
        status = "missing_contact_email"

    return {
        "schema_version": POLITE_ACCESS_SCHEMA_VERSION,
        "status": status,
        "compliant": compliant,
        "contact_email_configured": contact_configured,
        "contact_env_var": "CITEGUARD_MAILTO",
        "contact_required_sources": sorted(CONTACT_REQUIRED_SOURCES),
        "configured_contact_required_sources": configured_contact_sources,
        "fixture_mode": fixture_mode,
        "next_action": stable_next_action("continue" if compliant else "fix_configuration"),
        "message": _polite_access_message(status, configured_contact_sources),
    }


def source_health_status(
    env: Optional[Mapping[str, str]] = None,
    check_live: bool = False,
    health_query: str = "Attention Is All You Need",
    source_factory: Optional[Callable[..., object]] = None,
) -> dict:
    """Return source-level readiness, optionally probing each live source."""

    active_env = env or os.environ
    requested = configured_source_names(active_env)
    fixture_path = fixture_citations_path(active_env)
    try:
        configured_http_timeout = http_timeout(active_env)
    except ValueError:
        configured_http_timeout = None
    try:
        configured_http_retries = http_retries(active_env)
    except ValueError:
        configured_http_retries = None
    try:
        configured_http_retry_backoff = http_retry_backoff(active_env)
    except ValueError:
        configured_http_retry_backoff = None
    try:
        configured_evidence_timeout = evidence_timeout(active_env)
    except ValueError:
        configured_evidence_timeout = None

    if fixture_path:
        sources = [
            {
                "name": "fixture",
                "status": "offline_fixture",
                "path": fixture_path,
                "live_sources_bypassed": requested,
                "polite_access": _source_polite_access("fixture", active_env, fixture_mode=True),
            }
        ]
        return {
            "schema_version": SOURCE_HEALTH_SCHEMA_VERSION,
            "mode": "fixture",
            "live_check_performed": False,
            "health_query": "",
            "summary": _source_health_summary(sources, live_check_performed=False, mode="fixture"),
            "sources": sources,
        }

    seen = set()
    sources = []
    for requested_name in requested:
        canonical = SOURCE_ALIASES.get(requested_name.strip().lower())
        if canonical is None:
            sources.append(
                {
                    "name": requested_name,
                    "status": "invalid_config",
                    "message": "Unknown source name.",
                }
            )
            continue
        if canonical in seen:
            continue
        seen.add(canonical)
        item = {
            "name": canonical,
            "status": "configured_not_checked",
            "live_check_performed": False,
            "http_timeout_seconds": configured_http_timeout,
            "http_retries": configured_http_retries,
            "http_retry_backoff_seconds": configured_http_retry_backoff,
            "http_user_agent": polite_user_agent(active_env.get("CITEGUARD_MAILTO", DEFAULT_MAILTO)),
            "remote_evidence_enabled": remote_evidence_enabled(active_env),
            "evidence_timeout_seconds": configured_evidence_timeout,
            "polite_access": _source_polite_access(canonical, active_env),
        }
        if canonical in {"openalex", "crossref"}:
            item["mailto_configured"] = contact_email_configured(active_env)
        if canonical == "semantic_scholar":
            item["api_key_configured"] = bool(active_env.get("SEMANTIC_SCHOLAR_API_KEY"))
        if check_live:
            item.update(
                _probe_source_health(
                    canonical,
                    active_env,
                    health_query=health_query,
                    source_factory=source_factory,
                )
            )
        sources.append(item)

    return {
        "schema_version": SOURCE_HEALTH_SCHEMA_VERSION,
        "mode": "live",
        "live_check_performed": bool(check_live),
        "health_query": health_query if check_live else "",
        "summary": _source_health_summary(sources, live_check_performed=bool(check_live), mode="live"),
        "sources": sources,
    }


def _source_health_summary(sources: List[dict], live_check_performed: bool, mode: str) -> dict:
    status_counts: dict = {}
    for item in sources:
        status = str(item.get("status", "unknown"))
        status_counts[status] = status_counts.get(status, 0) + 1

    available_statuses = {"available", "empty", "offline_fixture"}
    failed_statuses = {"unavailable"}
    sources_available = [
        str(item.get("name", ""))
        for item in sources
        if item.get("name") and item.get("status") in available_statuses
    ]
    sources_configured = [
        str(item.get("name", ""))
        for item in sources
        if item.get("name") and item.get("status") != "invalid_config"
    ]
    sources_checked = [
        str(item.get("name", ""))
        for item in sources
        if item.get("name")
        and (item.get("live_check_performed") or item.get("status") in {"available", "empty", "unavailable"})
    ]
    sources_responded = [
        str(item.get("name", ""))
        for item in sources
        if item.get("name") and item.get("status") in {"available", "empty"}
    ]
    sources_unchecked = [
        str(item.get("name", ""))
        for item in sources
        if item.get("name") and item.get("status") == "configured_not_checked"
    ]
    sources_failed = [
        str(item.get("name", ""))
        for item in sources
        if item.get("name") and item.get("status") in failed_statuses
    ]
    invalid_sources = [
        str(item.get("name", ""))
        for item in sources
        if item.get("name") and item.get("status") == "invalid_config"
    ]
    failure_details = [
        dict(item["failure"])
        for item in sources
        if isinstance(item.get("failure"), dict)
    ]
    recovery_code = source_failure_recovery_code(failure_details)
    if not recovery_code and invalid_sources:
        recovery_code = "invalid_input"

    degraded = bool(sources_failed or invalid_sources)
    all_checked_failed = bool(live_check_performed and sources and len(sources_failed) == len(sources))
    next_action = _source_health_next_action(
        invalid_sources=invalid_sources,
        sources_failed=sources_failed,
        sources_unchecked=sources_unchecked,
        live_check_performed=live_check_performed,
    )
    return {
        "mode": mode,
        "live_check_performed": bool(live_check_performed),
        "total": len(sources),
        "status_counts": status_counts,
        "sources_configured": sources_configured,
        "sources_checked": sources_checked,
        "sources_responded": sources_responded,
        "sources_unchecked": sources_unchecked,
        "sources_available": sources_available,
        "sources_failed": sources_failed,
        "invalid_sources": invalid_sources,
        "failure_details": failure_details,
        "failure_count": len(failure_details),
        "degraded": degraded,
        "all_checked_sources_failed": all_checked_failed,
        "recovery_code": recovery_code,
        "next_action": next_action,
    }


def _source_polite_access(source_name: str, env: Mapping[str, str], fixture_mode: bool = False) -> dict:
    if fixture_mode:
        return {
            "requires_contact_email": False,
            "contact_email_configured": contact_email_configured(env),
            "status": "fixture_bypasses_live_sources",
            "next_action": stable_next_action("continue"),
        }
    requires_contact = source_name in CONTACT_REQUIRED_SOURCES
    contact_configured = contact_email_configured(env)
    status = "configured" if requires_contact and contact_configured else "missing_contact_email" if requires_contact else "not_required"
    return {
        "requires_contact_email": requires_contact,
        "contact_email_configured": contact_configured,
        "status": status,
        "next_action": stable_next_action("continue" if not requires_contact or contact_configured else "fix_configuration"),
    }


def _polite_access_message(status: str, configured_contact_sources: List[str]) -> str:
    if status == "fixture_bypasses_live_sources":
        return "Offline fixture mode bypasses live scholarly-source requests."
    if status == "not_required":
        return "Configured live sources do not require a contact email."
    if status == "configured":
        return "A contact email is configured for polite OpenAlex/Crossref requests."
    sources = ", ".join(configured_contact_sources) if configured_contact_sources else "configured sources"
    return f"Set CITEGUARD_MAILTO before querying {sources} in live runs."


def _source_health_next_action(
    invalid_sources: List[str],
    sources_failed: List[str],
    sources_unchecked: List[str],
    live_check_performed: bool,
) -> str:
    if invalid_sources:
        return stable_next_action("fix_configuration")
    if sources_failed:
        return stable_next_action("retry_or_check_source_health")
    if sources_unchecked and not live_check_performed:
        return stable_next_action("inspect_source_health")
    return stable_next_action("continue")


def _probe_source_health(
    source_name: str,
    env: Mapping[str, str],
    health_query: str,
    source_factory: Optional[Callable[..., object]] = None,
) -> dict:
    started = time.monotonic()
    factory = source_factory or build_live_metadata_source
    try:
        source = factory(
            [source_name],
            mailto=env.get("CITEGUARD_MAILTO", DEFAULT_MAILTO),
            semantic_scholar_api_key=env.get("SEMANTIC_SCHOLAR_API_KEY", ""),
            http_timeout=http_timeout(env),
            http_retries=http_retries(env),
            http_retry_backoff=http_retry_backoff(env),
            harvest_remote_evidence=False,
            evidence_timeout=evidence_timeout(env),
        )
        records = source.search(health_query, top_k=1)
    except Exception as exc:
        return {
            "status": "unavailable",
            "live_check_performed": True,
            "response_count": 0,
            "elapsed_ms": _elapsed_ms(started),
            "failure": _runtime_source_failure_detail(source_name, exc=exc),
        }

    failure = _runtime_source_failure_detail(source)
    status = "available" if records else "empty"
    payload = {
        "status": status,
        "live_check_performed": True,
        "response_count": len(records),
        "elapsed_ms": _elapsed_ms(started),
        "cache_hit": bool(failure.get("cache_hit")),
    }
    if failure.get("code"):
        payload["status"] = "unavailable"
        payload["failure"] = failure
    return payload


def _elapsed_ms(started: float) -> int:
    return int(round((time.monotonic() - started) * 1000))


def _runtime_source_failure_detail(source, exc: Optional[Exception] = None) -> dict:
    if isinstance(source, str):
        source_name = source
        http_client = None
    else:
        source_name = getattr(source, "name", "metadata_source")
        http_client = getattr(source, "http_client", None)

    code = getattr(http_client, "last_error_code", "") if http_client is not None else ""
    kind = getattr(http_client, "last_error_kind", "") if http_client is not None else ""
    error = getattr(http_client, "last_error", "") if http_client is not None else ""
    status_code = getattr(http_client, "last_status_code", None) if http_client is not None else None
    url = getattr(http_client, "last_url", "") if http_client is not None else ""
    cache_hit = bool(getattr(http_client, "last_cache_hit", False)) if http_client is not None else False

    if exc is not None and not code:
        code, kind = _classify_source_exception(exc)
        error = exc.__class__.__name__

    return {
        "source": source_name,
        "code": code,
        "kind": kind,
        "status_code": status_code,
        "url": url,
        "error": error,
        "cache_hit": cache_hit,
    }


def _classify_source_exception(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout", "timeout"
    return "source_unavailable", "exception"


def ensure_cache_parent(db_path: str) -> None:
    """Create the cache parent directory when using a filesystem SQLite cache."""

    if db_path == ":memory:":
        return
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def build_configured_source(env: Optional[Mapping[str, str]] = None):
    """Build the configured live source wrapped in a SQLite cache."""

    active_env = env or os.environ
    fixture_path = fixture_citations_path(active_env)
    if fixture_path:
        return InMemoryMetadataSource(load_fixture_records(fixture_path))

    names = canonical_source_names(configured_source_names(active_env))
    mailto = active_env.get("CITEGUARD_MAILTO", DEFAULT_MAILTO)
    api_key = active_env.get("SEMANTIC_SCHOLAR_API_KEY", "")
    live = build_live_metadata_source(
        names,
        mailto=mailto,
        semantic_scholar_api_key=api_key,
        http_timeout=http_timeout(active_env),
        http_retries=http_retries(active_env),
        http_retry_backoff=http_retry_backoff(active_env),
        harvest_remote_evidence=remote_evidence_enabled(active_env),
        evidence_timeout=evidence_timeout(active_env),
    )
    db_path = cache_path(active_env)
    ensure_cache_parent(db_path)
    return CachingMetadataSource(live, db_path=db_path)


def load_fixture_records(path: str) -> List[CitationRecord]:
    """Load CitationRecord objects from a JSON list or JSONL fixture."""

    records = []
    for index, item in enumerate(_load_json_or_jsonl(path, label="fixture citation"), start=1):
        try:
            records.append(
                CitationRecord(
                    citation_id=str(item.get("citation_id", f"fixture-{index}")),
                    title=str(item.get("title", "")),
                    authors=list(item.get("authors") or []),
                    year=item.get("year"),
                    venue=str(item.get("venue", "")),
                    doi=str(item.get("doi", "")),
                    arxiv_id=str(item.get("arxiv_id", "")),
                    url=str(item.get("url", "")),
                    abstract=str(item.get("abstract", "")),
                    source=str(item.get("source", "fixture")),
                )
            )
        except TypeError as exc:
            raise ValueError(f"fixture citation item {index} is not a valid citation object.") from exc
    return records


def _load_json_or_jsonl(path: str, label: str) -> List[dict]:
    with open(path, "r", encoding="utf-8") as handle:
        text = handle.read()
    if not text.strip():
        return []
    if text.lstrip().startswith("["):
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError(f"{label} fixture must be a JSON list or JSONL object stream.")
        items = payload
    else:
        items = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{label} fixture has invalid JSON on line {line_number}: {exc.msg}.") from exc
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"{label} fixture item {index} must be an object.")
    return items


def build_configured_support_backend(env: Optional[Mapping[str, str]] = None):
    """Build the configured claim-support backend stack."""

    from citeguard.verifiers import (
        DEFAULT_NLI_MODEL,
        DEFAULT_RERANKER_MODEL,
        build_production_support_backend,
    )

    active_env = env or os.environ
    reranker = active_env.get("CITEGUARD_RERANKER_MODEL", DEFAULT_RERANKER_MODEL)
    nli = active_env.get("CITEGUARD_NLI_MODEL", DEFAULT_NLI_MODEL)
    return build_production_support_backend(
        reranker_model_name=reranker,
        nli_model_name=nli,
    )


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


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


def environment_status(
    env: Optional[Mapping[str, str]] = None,
    mcp_sdk_available: Optional[bool] = None,
    check_sources: bool = False,
    health_query: str = "Attention Is All You Need",
    source_factory: Optional[Callable[..., object]] = None,
) -> dict:
    """Return configuration and dependency status, optionally probing sources."""

    active_env = env or os.environ
    requested_sources = configured_source_names(active_env)
    warnings = []
    configured_fixture_path = fixture_citations_path(active_env)
    try:
        canonical_sources = canonical_source_names(requested_sources)
    except ValueError as exc:
        canonical_sources = []
        warnings.append(str(exc))

    mailto = active_env.get("CITEGUARD_MAILTO", "research@example.com")
    cache = cache_path(active_env)
    configured_http_timeout = None
    configured_evidence_timeout = None
    try:
        configured_http_timeout = http_timeout(active_env)
    except ValueError as exc:
        warnings.append(str(exc))
    configured_http_retries = None
    configured_http_retry_backoff = None
    try:
        configured_http_retries = http_retries(active_env)
    except ValueError as exc:
        warnings.append(str(exc))
    try:
        configured_http_retry_backoff = http_retry_backoff(active_env)
    except ValueError as exc:
        warnings.append(str(exc))
    try:
        configured_evidence_timeout = evidence_timeout(active_env)
    except ValueError as exc:
        warnings.append(str(exc))
    configured_remote_evidence = remote_evidence_enabled(active_env)
    cache_parent = "" if cache == ":memory:" else os.path.dirname(os.path.abspath(cache))
    cache_parent_exists = cache == ":memory:" or os.path.isdir(cache_parent)
    cache_parent_writable = cache == ":memory:" or _cache_parent_writable(cache_parent)
    cache_status = _cache_status(cache, parent_exists=cache_parent_exists, parent_writable=cache_parent_writable)

    reranker = active_env.get("CITEGUARD_RERANKER_MODEL", "")
    nli = active_env.get("CITEGUARD_NLI_MODEL", "")
    model_dependencies = {
        "sentence_transformers": has_module("sentence_transformers"),
        "transformers": has_module("transformers"),
        "torch": has_module("torch"),
    }
    sdk_available = has_module("mcp") if mcp_sdk_available is None else mcp_sdk_available
    python_mcp_compatible = sys.version_info >= (3, 10)

    if not python_mcp_compatible:
        warnings.append("The MCP server entry point requires Python 3.10 or newer.")
    if not sdk_available:
        warnings.append('The MCP SDK is not installed; install with `python -m pip install -e ".[mcp]"`.')
    if not contact_email_configured(active_env) and any(name in CONTACT_REQUIRED_SOURCES for name in canonical_sources):
        warnings.append("Set CITEGUARD_MAILTO to your contact email for polite OpenAlex/Crossref usage.")
    if cache != ":memory:" and not cache_parent_exists:
        warnings.append("Cache directory does not exist yet; CiteGuard will create it on first verification.")
    if cache != ":memory:" and cache_parent_exists and not cache_parent_writable:
        warnings.append("Cache directory is not writable; set CITEGUARD_CACHE to a writable path.")
    if not configured_remote_evidence:
        warnings.append("Remote landing-page evidence harvesting is disabled by default; set CITEGUARD_REMOTE_EVIDENCE=1 for deeper support checks.")
    if not all(model_dependencies.values()):
        warnings.append("Deep claim-support models are not fully installed; support checks will fall back to heuristic mode.")
    if configured_fixture_path:
        warnings.append("CITEGUARD_FIXTURE_CITATIONS is set; live scholarly sources are bypassed for offline fixture mode.")

    return {
        "schema_version": STATUS_SCHEMA_VERSION,
        "service": "CiteGuard",
        "transport": "stdio",
        "python_version": platform.python_version(),
        "python_mcp_compatible": python_mcp_compatible,
        "mcp_sdk_available": sdk_available,
        "configured_sources": canonical_sources,
        "requested_sources": requested_sources,
        "source_health": source_health_status(
            active_env,
            check_live=check_sources,
            health_query=health_query,
            source_factory=source_factory,
        ),
        "fixture_citations_path": configured_fixture_path,
        "cache_path": cache,
        "cache_parent_exists": cache_parent_exists,
        "cache_parent_writable": cache_parent_writable,
        "cache_status": cache_status,
        "http_timeout_seconds": configured_http_timeout,
        "http_retries": configured_http_retries,
        "http_retry_backoff_seconds": configured_http_retry_backoff,
        "http_user_agent": polite_user_agent(mailto),
        "polite_access": polite_access_status(active_env),
        "remote_evidence_enabled": configured_remote_evidence,
        "remote_evidence_policy": {
            "enabled": configured_remote_evidence,
            "default_enabled": False,
            "non_http_urls_allowed": False,
            "blocked_host_suffixes": list(BLOCKED_EVIDENCE_HOST_SUFFIXES),
        },
        "evidence_timeout_seconds": configured_evidence_timeout,
        "mailto_configured": contact_email_configured(active_env),
        "semantic_scholar_api_key_configured": bool(active_env.get("SEMANTIC_SCHOLAR_API_KEY")),
        "support_models": {
            "reranker_model": reranker or "default",
            "nli_model": nli or "default",
            "model_dependencies": model_dependencies,
        },
        "warnings": warnings,
    }


def _cache_status(cache: str, parent_exists: bool, parent_writable: bool) -> dict:
    try:
        status = dict(inspect_cache(cache))
    except Exception as exc:
        return {
            "path": cache,
            "exists": os.path.exists(cache) if cache != ":memory:" else True,
            "inspect_ok": False,
            "error_type": exc.__class__.__name__,
            "message": str(exc),
            "parent_exists": parent_exists,
            "parent_writable": parent_writable,
            "next_action": stable_next_action("fix_configuration"),
        }
    status["inspect_ok"] = True
    status["parent_exists"] = parent_exists
    status["parent_writable"] = parent_writable
    status["next_action"] = stable_next_action(
        "continue" if parent_writable else "fix_configuration"
    )
    return status


def _cache_parent_writable(cache_parent: str) -> bool:
    if not cache_parent:
        return True
    if os.path.isdir(cache_parent):
        return os.access(cache_parent, os.W_OK)

    current = os.path.abspath(cache_parent)
    while current and not os.path.exists(current):
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return bool(current and os.path.isdir(current) and os.access(current, os.W_OK))
