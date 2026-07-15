"""Runtime configuration helpers shared by CLI and MCP surfaces."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import sys
from typing import Callable, Mapping, List, Optional

from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients import build_live_metadata_source
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.retrieval.scholarly_clients.evidence import BLOCKED_EVIDENCE_HOST_SUFFIXES
from citeguard.retrieval.scholarly_clients.factory import polite_user_agent
from citeguard.runtime_health import polite_access_status, source_health_status
from citeguard.runtime_config import (
    CONTACT_REQUIRED_SOURCES,
    DEFAULT_MAILTO,
    SOURCE_HEALTH_SCHEMA_VERSION,
    STATUS_SCHEMA_VERSION,
    cache_path,
    cache_ttl,
    canonical_source_names,
    configured_source_names,
    contact_email_configured,
    evidence_timeout,
    fixture_citations_path,
    http_min_interval,
    http_retries,
    http_retry_backoff,
    http_timeout,
    negative_cache_ttl,
    remote_evidence_enabled,
    source_budget,
)
from citeguard.verification import CachingMetadataSource, inspect_cache, stable_next_action

__all__ = [
    "SOURCE_HEALTH_SCHEMA_VERSION",
    "build_configured_source",
    "cache_path",
    "cache_ttl",
    "environment_status",
    "evidence_timeout",
    "http_min_interval",
    "http_retries",
    "http_retry_backoff",
    "http_timeout",
    "load_fixture_records",
    "negative_cache_ttl",
    "polite_access_status",
    "remote_evidence_enabled",
    "source_budget",
    "source_health_status",
]


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
        http_min_interval=http_min_interval(active_env),
        harvest_remote_evidence=remote_evidence_enabled(active_env),
        evidence_timeout=evidence_timeout(active_env),
        source_budget=source_budget(active_env),
    )
    db_path = cache_path(active_env)
    ensure_cache_parent(db_path)
    cache_namespace = json.dumps(
        {
            "sources": names,
            "http_timeout": http_timeout(active_env),
            "http_retries": http_retries(active_env),
            "http_retry_backoff": http_retry_backoff(active_env),
            "http_min_interval": http_min_interval(active_env),
            "remote_evidence": remote_evidence_enabled(active_env),
            "evidence_timeout": evidence_timeout(active_env),
            "source_budget": source_budget(active_env),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return CachingMetadataSource(
        live,
        db_path=db_path,
        namespace=cache_namespace,
        ttl_seconds=cache_ttl(active_env),
        negative_ttl_seconds=negative_cache_ttl(active_env),
    )


def build_doi_registry_probe(env: Optional[Mapping[str, str]] = None):
    """Build the doi.org handle-registry probe, or None when disabled.

    The probe confirms DOI existence across all registrars (including
    China DOI/ISTIC) for not_found results. It is skipped in offline fixture
    mode and can be disabled with CITEGUARD_DOI_REGISTRY=0.
    """

    from citeguard.retrieval.scholarly_clients.doi_registry import DoiRegistryProbe
    from citeguard.retrieval.scholarly_clients.http import HTTPClient

    active_env = env or os.environ
    if fixture_citations_path(active_env):
        return None
    if str(active_env.get("CITEGUARD_DOI_REGISTRY", "1")).strip().lower() in {"0", "false", "no", "off"}:
        return None
    return DoiRegistryProbe(http_client=HTTPClient(timeout=http_timeout(active_env)))


def oa_fulltext_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Return whether open-access full-text fetching is enabled."""

    active_env = env or os.environ
    return str(active_env.get("CITEGUARD_OA_FULLTEXT", "0")).strip().lower() in {"1", "true", "yes", "on"}


def build_oa_fulltext_fetcher(env: Optional[Mapping[str, str]] = None):
    """Build the open-access full-text fetcher, or None when disabled.

    Fetches paper bodies only from locations the source marks as open access;
    gated hosts remain blocked and paywalls are never bypassed. Disabled by
    default; enable with CITEGUARD_OA_FULLTEXT=1. Skipped in fixture mode.
    """

    from citeguard.retrieval.scholarly_clients.oa_fulltext import OaFulltextFetcher

    active_env = env or os.environ
    if fixture_citations_path(active_env):
        return None
    if not oa_fulltext_enabled(active_env):
        return None
    return OaFulltextFetcher(timeout=http_timeout(active_env))


def load_fixture_records(path: str) -> List[CitationRecord]:
    """Load CitationRecord objects from a JSON list, JSONL, or manifest fixture."""

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
                    metadata=dict(item.get("metadata") or {}),
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
    stripped = text.lstrip()
    items: Optional[List[dict]] = None
    if stripped.startswith("["):
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError(
                f"{label} fixture must be a JSON list, manifest object with records, or JSONL object stream."
            )
        items = payload
    elif stripped.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict) and isinstance(payload.get("records"), list):
            items = payload["records"]
    if items is None:
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


def environment_status(
    env: Optional[Mapping[str, str]] = None,
    mcp_sdk_available: Optional[bool] = None,
    check_sources: bool = False,
    health_query: str = "Attention Is All You Need",
    source_factory: Optional[Callable[..., object]] = None,
    module_checker: Optional[Callable[[str], bool]] = None,
) -> dict:
    """Return configuration and dependency status, optionally probing sources."""

    active_env = env or os.environ
    check_module = module_checker or has_module
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
    configured_source_budget = None
    configured_cache_ttl = None
    configured_negative_cache_ttl = None
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
    configured_http_min_interval = None
    try:
        configured_http_min_interval = http_min_interval(active_env)
    except ValueError as exc:
        warnings.append(str(exc))
    try:
        configured_evidence_timeout = evidence_timeout(active_env)
    except ValueError as exc:
        warnings.append(str(exc))
    try:
        configured_source_budget = source_budget(active_env)
    except ValueError as exc:
        warnings.append(str(exc))
    try:
        configured_cache_ttl = cache_ttl(active_env)
    except ValueError as exc:
        warnings.append(str(exc))
    try:
        configured_negative_cache_ttl = negative_cache_ttl(active_env)
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
        "sentence_transformers": check_module("sentence_transformers"),
        "transformers": check_module("transformers"),
        "torch": check_module("torch"),
    }
    support_models = _support_model_status(
        reranker_model=reranker, nli_model=nli, model_dependencies=model_dependencies
    )
    sdk_available = check_module("mcp") if mcp_sdk_available is None else mcp_sdk_available
    python_mcp_compatible = sys.version_info >= (3, 10)

    if not python_mcp_compatible:
        warnings.append("The MCP server entry point requires Python 3.10 or newer.")
    if not sdk_available:
        warnings.append(
            "The MCP SDK is not installed; install published packages with "
            "`python -m pip install citationguard`, or use "
            "`python -m pip install -e .` from a source checkout."
        )
    if not contact_email_configured(active_env) and any(name in CONTACT_REQUIRED_SOURCES for name in canonical_sources):
        warnings.append("Set CITEGUARD_MAILTO to your contact email for polite OpenAlex/Crossref usage.")
    if cache != ":memory:" and not cache_parent_exists:
        warnings.append("Cache directory does not exist yet; CiteGuard will create it on first verification.")
    if cache != ":memory:" and cache_parent_exists and not cache_parent_writable:
        warnings.append("Cache directory is not writable; set CITEGUARD_CACHE to a writable path.")
    if not configured_remote_evidence:
        warnings.append(
            "Remote landing-page evidence harvesting is disabled by default; set CITEGUARD_REMOTE_EVIDENCE=1 for deeper support checks."
        )
    if not support_models["deep_models_available"]:
        warnings.append(
            "Deep claim-support models are not fully installed; support checks will fall back to heuristic mode."
        )
    if configured_fixture_path:
        warnings.append(
            "CITEGUARD_FIXTURE_CITATIONS is set; live scholarly sources are bypassed for offline fixture mode."
        )

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
        "http_min_interval_seconds": configured_http_min_interval,
        "source_budget_seconds": configured_source_budget,
        "cache_ttl_seconds": configured_cache_ttl,
        "negative_cache_ttl_seconds": configured_negative_cache_ttl,
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
        "support_models": support_models,
        "warnings": warnings,
    }


def _support_model_status(
    reranker_model: str,
    nli_model: str,
    model_dependencies: Mapping[str, bool],
) -> dict:
    missing = sorted(name for name, available in model_dependencies.items() if not available)
    deep_available = not missing
    return {
        "reranker_model": reranker_model or "default",
        "nli_model": nli_model or "default",
        "model_dependencies": dict(model_dependencies),
        "missing_dependencies": missing,
        "deep_models_available": deep_available,
        "engine": "production_ensemble" if deep_available else "heuristic_fallback",
        "next_action": stable_next_action("continue" if deep_available else "install_or_configure_dependency"),
        "install_hint": (
            ""
            if deep_available
            else 'Install published packages with `python -m pip install "citationguard[models]"`, '
            'or use `python -m pip install -e ".[models]"` from a source checkout.'
        ),
        "warmup_command": "citeguard models warmup",
        "model_weights_loaded": False,
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
    status["next_action"] = stable_next_action("continue" if parent_writable else "fix_configuration")
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
