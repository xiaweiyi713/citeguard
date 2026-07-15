"""Source readiness, polite-access, and live health-probe reporting."""

from __future__ import annotations

import os
import socket
import time
from typing import Any, Callable, Dict, List, Mapping, Optional

from citeguard.retrieval.scholarly_clients import build_live_metadata_source
from citeguard.retrieval.scholarly_clients.factory import polite_user_agent
from citeguard.runtime_config import (
    CONTACT_REQUIRED_SOURCES,
    DEFAULT_MAILTO,
    POLITE_ACCESS_SCHEMA_VERSION,
    SOURCE_ALIASES,
    SOURCE_HEALTH_SCHEMA_VERSION,
    configured_source_names,
    contact_email_configured,
    evidence_timeout,
    fixture_citations_path,
    http_min_interval,
    http_retries,
    http_retry_backoff,
    http_timeout,
    remote_evidence_enabled,
)
from citeguard.verification import source_failure_recovery_code, stable_next_action


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
        configured_http_min_interval = http_min_interval(active_env)
    except ValueError:
        configured_http_min_interval = None
    try:
        configured_evidence_timeout = evidence_timeout(active_env)
    except ValueError:
        configured_evidence_timeout = None

    if fixture_path:
        sources: List[Dict[str, Any]] = [
            {
                "name": "fixture",
                "status": "offline_fixture",
                "path": fixture_path,
                "live_sources_bypassed": requested,
                "polite_access": _source_polite_access("fixture", active_env, fixture_mode=True),
            }
        ]
        _annotate_source_health_items(sources, live_check_performed=False, mode="fixture")
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
        item: Dict[str, Any] = {
            "name": canonical,
            "status": "configured_not_checked",
            "live_check_performed": False,
            "http_timeout_seconds": configured_http_timeout,
            "http_retries": configured_http_retries,
            "http_retry_backoff_seconds": configured_http_retry_backoff,
            "http_min_interval_seconds": configured_http_min_interval,
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

    _annotate_source_health_items(sources, live_check_performed=bool(check_live), mode="live")
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
        str(item.get("name", "")) for item in sources if item.get("name") and item.get("status") in available_statuses
    ]
    sources_configured = [
        str(item.get("name", "")) for item in sources if item.get("name") and item.get("status") != "invalid_config"
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
        str(item.get("name", "")) for item in sources if item.get("name") and item.get("status") in failed_statuses
    ]
    invalid_sources = [
        str(item.get("name", "")) for item in sources if item.get("name") and item.get("status") == "invalid_config"
    ]
    failure_details = [dict(item["failure"]) for item in sources if isinstance(item.get("failure"), dict)]
    failure_kind_counts, failure_kind_sources = _source_health_failure_kinds(failure_details)
    retry_after_seconds, retry_after_sources = _source_health_retry_after(failure_details)
    retry_delay_seconds, retry_delay_sources = _source_health_retry_delay(failure_details)
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
    confidence_effect, interpretation = _source_health_confidence_contract(
        mode=mode,
        invalid_sources=invalid_sources,
        sources_failed=sources_failed,
        sources_unchecked=sources_unchecked,
        live_check_performed=live_check_performed,
        all_checked_failed=all_checked_failed,
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
        "failure_kind_counts": failure_kind_counts,
        "failure_kind_sources": failure_kind_sources,
        "retry_after_seconds": retry_after_seconds,
        "retry_after_sources": retry_after_sources,
        "retry_delay_seconds": retry_delay_seconds,
        "retry_delay_sources": retry_delay_sources,
        "retry_guidance": _source_health_retry_guidance(next_action, retry_after_seconds),
        "degraded": degraded,
        "all_checked_sources_failed": all_checked_failed,
        "confidence_effect": confidence_effect,
        "interpretation": interpretation,
        "recovery_code": recovery_code,
        "next_action": next_action,
    }


def _annotate_source_health_items(sources: List[dict], live_check_performed: bool, mode: str) -> None:
    for item in sources:
        item.update(_source_health_item_contract(item, live_check_performed=live_check_performed, mode=mode))


def _source_health_item_contract(item: dict, live_check_performed: bool, mode: str) -> dict:
    status = str(item.get("status", "unknown"))
    failure = item.get("failure") if isinstance(item.get("failure"), dict) else {}
    retry_after = failure.get("retry_after_seconds") if failure else None
    retry_delay = failure.get("retry_delay_seconds") if failure else None
    recovery_code = source_failure_recovery_code([failure]) if failure else ""

    if status == "invalid_config":
        next_action = stable_next_action("fix_configuration")
        confidence_effect = "invalid_configuration"
        interpretation = "invalid_source_configuration_must_be_fixed_before_source_reliability_conclusions"
        recovery_code = recovery_code or "invalid_input"
    elif status == "unavailable":
        next_action = stable_next_action("retry_or_check_source_health")
        confidence_effect = "source_unavailable"
        interpretation = "source_outage_lowers_confidence_not_fabrication_evidence"
    elif status == "configured_not_checked" and not live_check_performed:
        next_action = stable_next_action("inspect_source_health")
        confidence_effect = "not_checked"
        interpretation = "run_live_health_check_before_drawing_source_reliability_conclusions"
    elif status == "offline_fixture" or mode == "fixture":
        next_action = stable_next_action("continue")
        confidence_effect = "none"
        interpretation = "fixture_mode_bypasses_live_sources"
    elif status in {"available", "empty"}:
        next_action = stable_next_action("continue")
        confidence_effect = "none"
        interpretation = "source_health_ok"
    else:
        next_action = stable_next_action("inspect_source_health")
        confidence_effect = "unknown"
        interpretation = "inspect_source_health_before_drawing_source_reliability_conclusions"

    return {
        "next_action": next_action,
        "confidence_effect": confidence_effect,
        "interpretation": interpretation,
        "recovery_code": recovery_code,
        "retry_after_seconds": retry_after if isinstance(retry_after, (int, float)) else None,
        "retry_delay_seconds": retry_delay if isinstance(retry_delay, (int, float)) else None,
        "retry_guidance": _source_health_retry_guidance(
            next_action, retry_after if isinstance(retry_after, (int, float)) else None
        ),
    }


def _source_health_failure_kinds(failure_details: List[dict]) -> tuple[dict, dict]:
    counts: dict = {}
    sources_by_kind: dict = {}
    for detail in failure_details:
        kind = str(detail.get("kind") or detail.get("code") or "unknown")
        source = str(detail.get("source") or "")
        counts[kind] = counts.get(kind, 0) + 1
        if source and source not in sources_by_kind.setdefault(kind, []):
            sources_by_kind[kind].append(source)
    return counts, sources_by_kind


def _source_health_retry_after(failure_details: List[dict]) -> tuple[Optional[float], List[str]]:
    retry_after_values = []
    retry_after_sources = []
    for detail in failure_details:
        retry_after = detail.get("retry_after_seconds")
        if not isinstance(retry_after, (int, float)):
            continue
        retry_after_values.append(float(retry_after))
        source = str(detail.get("source") or "")
        if source and source not in retry_after_sources:
            retry_after_sources.append(source)
    if not retry_after_values:
        return None, []
    return max(retry_after_values), retry_after_sources


def _source_health_retry_delay(failure_details: List[dict]) -> tuple[Optional[float], List[str]]:
    retry_delay_values = []
    retry_delay_sources = []
    for detail in failure_details:
        retry_delay = detail.get("retry_delay_seconds")
        if not isinstance(retry_delay, (int, float)):
            continue
        retry_delay_values.append(float(retry_delay))
        source = str(detail.get("source") or "")
        if source and source not in retry_delay_sources:
            retry_delay_sources.append(source)
    if not retry_delay_values:
        return None, []
    return max(retry_delay_values), retry_delay_sources


def _source_health_retry_guidance(next_action: str, retry_after_seconds: Optional[float]) -> str:
    if retry_after_seconds is not None and retry_after_seconds > 0:
        return "wait_before_retry"
    if next_action == "retry_or_check_source_health":
        return "retry_or_check_source_health"
    if next_action == "fix_configuration":
        return "fix_configuration"
    if next_action == "inspect_source_health":
        return "inspect_source_health"
    return "continue"


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
    status = (
        "configured"
        if requires_contact and contact_configured
        else "missing_contact_email"
        if requires_contact
        else "not_required"
    )
    return {
        "requires_contact_email": requires_contact,
        "contact_email_configured": contact_configured,
        "status": status,
        "next_action": stable_next_action(
            "continue" if not requires_contact or contact_configured else "fix_configuration"
        ),
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


def _source_health_confidence_contract(
    *,
    mode: str,
    invalid_sources: List[str],
    sources_failed: List[str],
    sources_unchecked: List[str],
    live_check_performed: bool,
    all_checked_failed: bool,
) -> tuple[str, str]:
    if invalid_sources:
        return (
            "invalid_configuration",
            "invalid_source_configuration_must_be_fixed_before_source_reliability_conclusions",
        )
    if all_checked_failed:
        return (
            "all_sources_unavailable",
            "source_outage_lowers_confidence_not_fabrication_evidence",
        )
    if sources_failed:
        return (
            "partial_source_limited",
            "source_outage_lowers_confidence_not_fabrication_evidence",
        )
    if sources_unchecked and not live_check_performed:
        return (
            "not_checked",
            "run_live_health_check_before_drawing_source_reliability_conclusions",
        )
    if mode == "fixture":
        return ("none", "fixture_mode_bypasses_live_sources")
    return ("none", "source_health_ok")


def _probe_source_health(
    source_name: str,
    env: Mapping[str, str],
    health_query: str,
    source_factory: Optional[Callable[..., object]] = None,
) -> dict:
    started = time.monotonic()
    factory = source_factory or build_live_metadata_source
    try:
        source: Any = factory(
            [source_name],
            mailto=env.get("CITEGUARD_MAILTO", DEFAULT_MAILTO),
            semantic_scholar_api_key=env.get("SEMANTIC_SCHOLAR_API_KEY", ""),
            http_timeout=http_timeout(env),
            http_retries=http_retries(env),
            http_retry_backoff=http_retry_backoff(env),
            http_min_interval=http_min_interval(env),
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
    final_url = getattr(http_client, "last_final_url", "") if http_client is not None else ""
    redirected = bool(getattr(http_client, "last_redirected", False)) if http_client is not None else False
    cache_hit = bool(getattr(http_client, "last_cache_hit", False)) if http_client is not None else False
    attempt_count = int(getattr(http_client, "last_attempt_count", 0) or 0) if http_client is not None else 0
    retry_count = int(getattr(http_client, "last_retry_count", 0) or 0) if http_client is not None else 0
    retry_after_seconds = getattr(http_client, "last_retry_after_seconds", None) if http_client is not None else None
    retry_delay_seconds = getattr(http_client, "last_retry_delay_seconds", None) if http_client is not None else None

    if exc is not None and not code:
        code, kind = _classify_source_exception(exc)
        error = exc.__class__.__name__

    return {
        "source": source_name,
        "code": code,
        "kind": kind,
        "status_code": status_code,
        "url": url,
        "final_url": final_url,
        "redirected": redirected,
        "error": error,
        "cache_hit": cache_hit,
        "attempt_count": attempt_count,
        "retry_count": retry_count,
        "retry_after_seconds": retry_after_seconds,
        "retry_delay_seconds": retry_delay_seconds,
    }


def _classify_source_exception(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout", "timeout"
    return "source_unavailable", "exception"
