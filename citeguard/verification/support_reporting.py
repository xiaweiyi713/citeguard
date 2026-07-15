"""Serialization, provenance, recovery, and risk-report helpers for support checks."""

from __future__ import annotations

import socket
from dataclasses import replace
from typing import Any, Dict, List, Optional, Union

from citeguard.citation import normalize_text
from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients.base import MetadataSource

from .models import input_source_provenance, stable_next_action
from .support import ClaimSupportSetResult, SupportResult, SupportVerdict, infer_evidence_source_name


def _snippet(text: str, limit: int = 360) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3].rstrip() + "..."


def _exception_failure_details(names: List[str], exc: Exception) -> List[Dict[str, Any]]:
    code, kind = _classify_source_exception(exc)
    return [
        {
            "source": name,
            "code": code,
            "kind": kind,
            "status_code": None,
            "url": "",
            "error": exc.__class__.__name__,
        }
        for name in names
    ]


def _source_failure_details(source: MetadataSource) -> List[Dict[str, Any]]:
    inner = getattr(source, "inner", source)
    details = [dict(item) for item in getattr(inner, "last_failure_details", [])]
    http_client = getattr(inner, "http_client", None)
    code = getattr(http_client, "last_error_code", "") if http_client is not None else ""
    if code:
        details.append(
            {
                "source": getattr(inner, "name", "metadata_source"),
                "code": code,
                "kind": getattr(http_client, "last_error_kind", ""),
                "status_code": getattr(http_client, "last_status_code", None),
                "url": getattr(http_client, "last_url", ""),
                "final_url": getattr(http_client, "last_final_url", ""),
                "redirected": bool(getattr(http_client, "last_redirected", False)),
                "error": getattr(http_client, "last_error", ""),
                "cache_hit": bool(getattr(http_client, "last_cache_hit", False)),
                "attempt_count": int(getattr(http_client, "last_attempt_count", 0) or 0),
                "retry_count": int(getattr(http_client, "last_retry_count", 0) or 0),
                "retry_after_seconds": getattr(http_client, "last_retry_after_seconds", None),
                "retry_delay_seconds": getattr(http_client, "last_retry_delay_seconds", None),
            }
        )
    return _dedupe_failure_details(details)


def _classify_source_exception(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout", "timeout"
    return "source_unavailable", "exception"


def _dedupe_failure_details(details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    deduped: List[Dict[str, Any]] = []
    for detail in details:
        if detail not in deduped:
            deduped.append(detail)
    return deduped


def _aggregate_evidence_scope(scopes: List[str]) -> str:
    unique = sorted({scope for scope in scopes if scope})
    if not unique:
        return "none"
    if len(unique) == 1:
        return unique[0]
    if "full_text" in unique:
        return "mixed_with_full_text"
    return "mixed"


def _support_set_evidence_provenance(result: ClaimSupportSetResult) -> Dict[str, List[str]]:
    scopes: List[str] = []
    source_names: List[str] = []
    source_fields: List[str] = []

    for child in result.results:
        source_field = str(child.evidence.get("source_field", "")).strip()
        source_url = str(child.evidence.get("source_url", "")).strip()
        scope = str(child.evidence_scope or child.evidence.get("evidence_scope", "")).strip()
        source_name = str(
            child.evidence.get("source_name") or infer_evidence_source_name(source_field, source_url)
        ).strip()

        if scope:
            scopes.append(scope)
        if source_name:
            source_names.append(source_name)
        if source_field:
            source_fields.append(source_field)

    if not scopes and result.evidence_scope:
        scopes.append(result.evidence_scope)

    return {
        "evidence_scopes": _ordered_nonempty_values(scopes, default="none"),
        "evidence_source_names": _ordered_nonempty_values(source_names, default="none"),
        "evidence_source_fields": _ordered_nonempty_values(source_fields, default="none"),
    }


def _support_set_mode_details(result: ClaimSupportSetResult) -> Dict[str, Any]:
    index_by_verdict: Dict[str, List[int]] = {verdict.value: [] for verdict in SupportVerdict}
    for index, child in enumerate(result.results):
        index_by_verdict.setdefault(child.verdict.value, []).append(index)

    evidence_provenance = _support_set_evidence_provenance(result)
    evidence_scopes = evidence_provenance["evidence_scopes"]
    full_text_present = any(scope in {"full_text", "mixed_with_full_text"} for scope in evidence_scopes)
    total = len(result.results)
    strong_count = len(index_by_verdict.get(SupportVerdict.SUPPORTED.value, []))
    weak_count = len(index_by_verdict.get(SupportVerdict.WEAKLY_SUPPORTED.value, []))
    contradicted_count = len(index_by_verdict.get(SupportVerdict.CONTRADICTED.value, []))
    insufficient_count = len(index_by_verdict.get(SupportVerdict.INSUFFICIENT_EVIDENCE.value, []))

    decision_by_mode = {
        "contradiction_dominates": "contradiction_dominates_aggregate",
        "single_strong_support": "one_strong_citation_supports_claim",
        "multiple_strong_support": "multiple_strong_citations_support_claim",
        "multiple_weak_support": "multiple_weak_citations_remain_tentative",
        "single_weak_support": "single_weak_citation_remains_tentative",
        "insufficient_evidence": "no_citation_confirms_claim",
    }
    reasons_by_mode = {
        "contradiction_dominates": [
            "at_least_one_citation_contradicted",
            "contradictions_dominate_support_set",
        ],
        "single_strong_support": ["one_citation_supported"],
        "multiple_strong_support": ["multiple_citations_supported"],
        "multiple_weak_support": [
            "multiple_citations_weakly_supported",
            "weak_sources_do_not_become_strong_support",
        ],
        "single_weak_support": [
            "one_citation_weakly_supported",
            "weak_source_requires_stronger_evidence_or_full_text",
        ],
        "insufficient_evidence": ["no_citation_supported_or_weakly_supported"],
    }
    if not full_text_present:
        reasons = list(reasons_by_mode.get(result.support_mode, []))
        reasons.append("no_full_text_evidence_in_aggregate")
    else:
        reasons = list(reasons_by_mode.get(result.support_mode, []))
        reasons.append("user_provided_full_text_evidence_present")

    return {
        "schema_version": 1,
        "support_mode": result.support_mode,
        "decision": decision_by_mode.get(result.support_mode, "unknown"),
        "policy": (
            "contradictions_dominate; multiple_weak_citations_remain_tentative; "
            "no_unstated_multi_hop_or_full_text_support"
        ),
        "reasons": reasons,
        "total_citation_count": total,
        "strong_support_count": strong_count,
        "weak_support_count": weak_count,
        "contradiction_count": contradicted_count,
        "insufficient_evidence_count": insufficient_count,
        "supported_indexes": list(index_by_verdict.get(SupportVerdict.SUPPORTED.value, [])),
        "weakly_supported_indexes": list(index_by_verdict.get(SupportVerdict.WEAKLY_SUPPORTED.value, [])),
        "contradicted_indexes": list(index_by_verdict.get(SupportVerdict.CONTRADICTED.value, [])),
        "insufficient_evidence_indexes": list(index_by_verdict.get(SupportVerdict.INSUFFICIENT_EVIDENCE.value, [])),
        "evidence_scope": result.evidence_scope,
        "evidence_scopes": evidence_scopes,
        "full_text_evidence_present": full_text_present,
    }


def _ordered_nonempty_values(values: List[str], *, default: str = "none") -> List[str]:
    ordered: List[str] = []
    seen = set()
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered or [default]


def _merge_candidate_evidence(record: CitationRecord, candidate: CitationRecord) -> CitationRecord:
    """Attach caller-provided evidence snippets to a resolved canonical record."""

    candidate_chunks = candidate.metadata.get("evidence_chunks", [])
    candidate_abstract = str(candidate.abstract or "").strip()
    # Carry caller-provided identifiers onto the resolved record so downstream
    # helpers (e.g. the OA full-text arXiv fallback) can use them.
    if candidate.arxiv_id and not record.arxiv_id:
        record = replace(record, arxiv_id=candidate.arxiv_id)
    if candidate.doi and not record.doi:
        record = replace(record, doi=candidate.doi)
    if not candidate_chunks and not candidate_abstract:
        return record

    metadata = dict(record.metadata)
    chunks = list(metadata.get("evidence_chunks", []))
    abstract = record.abstract

    if candidate_abstract:
        if not abstract:
            abstract = candidate_abstract
        elif normalize_text(candidate_abstract) != normalize_text(abstract):
            chunks.append(
                {
                    "text": candidate_abstract,
                    "source_field": "user_provided_abstract",
                    "source_url": "",
                    "evidence_scope": "abstract",
                }
            )

    if isinstance(candidate_chunks, list):
        chunks.extend(candidate_chunks)
    elif candidate_chunks:
        chunks.append(candidate_chunks)

    if chunks:
        metadata["evidence_chunks"] = chunks
    return replace(record, abstract=abstract, metadata=metadata)


def _counterevidence_review_for_result(result: SupportResult) -> Dict[str, Any]:
    if result.verdict == SupportVerdict.SUPPORTED:
        return {
            "counterevidence_review": False,
            "counterevidence_reason": "",
            "counterevidence_recommendation": "",
        }
    if result.verdict == SupportVerdict.CONTRADICTED:
        return {
            "counterevidence_review": True,
            "counterevidence_reason": "contradicted",
            "counterevidence_recommendation": (
                "Available evidence contradicts the claim; rewrite the claim or replace the citation before use."
            ),
        }
    if result.verdict == SupportVerdict.WEAKLY_SUPPORTED:
        return {
            "counterevidence_review": True,
            "counterevidence_reason": "weak_support",
            "counterevidence_recommendation": (
                "Support is only partial; inspect full text and look for stronger or contrary evidence."
            ),
        }

    resolution_verdict = result.resolution.get("verdict", "")
    if resolution_verdict in {"not_found", "ambiguous"}:
        return {
            "counterevidence_review": True,
            "counterevidence_reason": "unresolved_citation",
            "counterevidence_recommendation": (
                "Resolve the citation identity before treating the claim as supported or contradicted."
            ),
        }
    if result.engine == "heuristic":
        reason = "heuristic_limited"
    elif result.evidence_scope == "none":
        reason = "no_evidence_text"
    else:
        reason = "insufficient_evidence"
    return {
        "counterevidence_review": True,
        "counterevidence_reason": reason,
        "counterevidence_recommendation": (
            "Available evidence does not confirm the claim; inspect full text and review possible counter-evidence."
        ),
    }


def _counterevidence_review_for_set(verdict: SupportVerdict, summary: Dict[str, int]) -> Dict[str, Any]:
    if verdict == SupportVerdict.SUPPORTED:
        return {
            "counterevidence_review": False,
            "counterevidence_reason": "",
            "counterevidence_recommendation": "",
        }
    if verdict == SupportVerdict.CONTRADICTED:
        return {
            "counterevidence_review": True,
            "counterevidence_reason": "contradicted",
            "counterevidence_recommendation": (
                "At least one cited paper contradicts the claim; rewrite the claim or replace the citation set."
            ),
        }
    if summary.get(SupportVerdict.WEAKLY_SUPPORTED.value, 0):
        return {
            "counterevidence_review": True,
            "counterevidence_reason": "weak_support",
            "counterevidence_recommendation": (
                "The citation set is only weakly related; inspect full text and look for stronger or contrary evidence."
            ),
        }
    return {
        "counterevidence_review": True,
        "counterevidence_reason": "insufficient_evidence",
        "counterevidence_recommendation": (
            "No citation confirms the claim with available evidence; review full text or find stronger evidence."
        ),
    }


def _support_next_action(verdict: SupportVerdict, resolution: Dict[str, Any]) -> str:
    if verdict == SupportVerdict.SUPPORTED:
        return stable_next_action("keep_claim")
    if verdict == SupportVerdict.WEAKLY_SUPPORTED:
        return stable_next_action("tighten_claim_or_inspect_full_text")
    if verdict == SupportVerdict.CONTRADICTED:
        return stable_next_action("rewrite_or_replace_evidence")

    resolution_verdict = resolution.get("verdict", "")
    failure_mode = str(resolution.get("source_failure_mode", ""))
    if resolution_verdict == "ambiguous":
        return stable_next_action("disambiguate_identifier")
    if failure_mode == "all_sources_failed":
        return stable_next_action("retry_or_check_source_health")
    if resolution_verdict == "not_found":
        return stable_next_action("resolve_citation_identity")
    return stable_next_action("inspect_full_text_or_find_stronger_citation")


def _support_set_next_action(verdict: SupportVerdict) -> str:
    if verdict == SupportVerdict.SUPPORTED:
        return stable_next_action("keep_claim")
    if verdict == SupportVerdict.CONTRADICTED:
        return stable_next_action("rewrite_or_replace_evidence")
    if verdict == SupportVerdict.WEAKLY_SUPPORTED:
        return stable_next_action("tighten_claim_or_inspect_full_text")
    return stable_next_action("inspect_full_text_or_find_stronger_citation")


def _counterevidence_next_action(
    candidate_count: int,
    source_failure_mode: str = "none",
    sources_failed: Optional[List[str]] = None,
) -> str:
    if candidate_count > 0:
        return stable_next_action("review_counterevidence_leads")
    if source_failure_mode != "none" or sources_failed:
        return stable_next_action("retry_or_check_source_health")
    return stable_next_action("continue")


def _counterevidence_review_summary(
    candidates: List[Dict[str, Any]],
    *,
    source_failure_mode: str,
    sources_failed: List[str],
    next_action: str,
) -> Dict[str, Any]:
    signal_counts: Dict[str, int] = {}
    matched_query_role_counts: Dict[str, int] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        signal = str(candidate.get("signal", "") or "unknown")
        signal_counts[signal] = signal_counts.get(signal, 0) + 1
        roles = candidate.get("matched_query_roles", [])
        if not isinstance(roles, list):
            continue
        for role in roles:
            role_name = str(role)
            matched_query_role_counts[role_name] = matched_query_role_counts.get(role_name, 0) + 1

    top_candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else {}
    compact_top_candidate = None
    if top_candidate:
        compact_top_candidate = {
            "title": top_candidate.get("title", ""),
            "signal": top_candidate.get("signal", ""),
            "score": top_candidate.get("score"),
            "matched_query_roles": list(top_candidate.get("matched_query_roles", []) or []),
            "evidence_scope": top_candidate.get("evidence_scope", ""),
        }

    return {
        "candidate_count": len(candidates),
        "signal_counts": dict(sorted(signal_counts.items())),
        "matched_query_role_counts": dict(sorted(matched_query_role_counts.items())),
        "top_candidate": compact_top_candidate,
        "recommended_next_steps": _counterevidence_recommended_next_steps(
            candidates,
            source_failure_mode=source_failure_mode,
            sources_failed=sources_failed,
            next_action=next_action,
        ),
        "source_failure_mode": source_failure_mode,
        "sources_failed": list(sources_failed),
        "outage_limited": source_failure_mode == "all_sources_failed",
        "next_action": next_action,
        "policy": "review_leads_not_contradiction_verdicts",
    }


def _counterevidence_recommended_next_steps(
    candidates: List[Dict[str, Any]],
    *,
    source_failure_mode: str,
    sources_failed: List[str],
    next_action: str,
) -> Dict[str, Any]:
    explicit_indexes: List[int] = []
    source_outage_safety_indexes: List[int] = []
    related_indexes: List[int] = []
    for index, candidate in enumerate(candidates):
        if not isinstance(candidate, dict):
            continue
        signal = str(candidate.get("signal", "") or "")
        if signal == "explicit_contradiction_cue":
            explicit_indexes.append(index)
        elif signal == "source_outage_safety_cue":
            source_outage_safety_indexes.append(index)
        else:
            related_indexes.append(index)

    steps: List[Dict[str, Any]] = []
    if explicit_indexes:
        steps.append(
            {
                "action": "review_explicit_contradiction_leads",
                "queue": "explicit_contradiction_candidate_indexes",
                "candidate_indexes": explicit_indexes,
                "count": len(explicit_indexes),
                "priority": 1,
            }
        )
    if source_outage_safety_indexes:
        steps.append(
            {
                "action": "review_source_outage_safety_leads",
                "queue": "source_outage_safety_candidate_indexes",
                "candidate_indexes": source_outage_safety_indexes,
                "count": len(source_outage_safety_indexes),
                "priority": 2,
            }
        )
    if related_indexes:
        steps.append(
            {
                "action": "review_related_candidates",
                "queue": "related_candidate_indexes",
                "candidate_indexes": related_indexes,
                "count": len(related_indexes),
                "priority": 3,
            }
        )
    if not steps and (source_failure_mode != "none" or sources_failed):
        steps.append(
            {
                "action": "retry_or_check_source_health",
                "queue": "source_retry_sources",
                "sources": list(sources_failed),
                "count": len(sources_failed),
                "priority": 4,
            }
        )

    first = steps[0] if steps else {}
    return {
        "status": "review_required" if candidates else "source_retry" if steps else "clear",
        "next_action": next_action,
        "first_action": first.get("action", "continue"),
        "first_queue": first.get("queue", ""),
        "queue_order": [step["queue"] for step in steps],
        "explicit_contradiction_candidate_indexes": explicit_indexes,
        "source_outage_safety_candidate_indexes": source_outage_safety_indexes,
        "related_candidate_indexes": related_indexes,
        "source_retry_sources": list(sources_failed)
        if not candidates and (source_failure_mode != "none" or sources_failed)
        else [],
        "steps": steps,
        "policy": "prioritize_explicit_contradiction_cues_but_treat_all_candidates_as_review_leads",
    }


def _support_risk_item(index: int, result: SupportResult) -> Dict[str, Any]:
    if result.verdict == SupportVerdict.SUPPORTED:
        evidence_label = "full-text evidence" if result.evidence_scope == "full_text" else "available evidence"
        risk, score, recommendation = "low", 0.05, f"Claim is supported by the {evidence_label}."
    elif result.verdict == SupportVerdict.WEAKLY_SUPPORTED:
        risk, score, recommendation = "medium", 0.55, "Treat as tentative; tighten the claim or inspect full text."
    elif result.verdict == SupportVerdict.CONTRADICTED:
        risk, score, recommendation = (
            "high",
            0.98,
            "Do not use this citation for the claim without rewriting or replacing it.",
        )
    else:
        resolution_verdict = result.resolution.get("verdict", "")
        if resolution_verdict in {"not_found", "ambiguous"}:
            risk, score = "high", 0.9
            recommendation = "Resolve the citation first with a DOI/arXiv id before judging support."
        else:
            risk, score = "medium", 0.7
            recommendation = (
                "Available evidence cannot confirm the claim; inspect full text or use a stronger citation."
            )
    next_action = _support_next_action(result.verdict, result.resolution)
    item = {
        "index": index,
        "verdict": result.verdict.value,
        "risk": risk,
        "risk_score": round(score, 4),
        "risk_reason": _support_risk_reason(result),
        "claim": result.claim,
        "support_confidence": round(result.confidence, 4),
        "support_engine": result.engine,
        "resolution": dict(result.resolution),
        "resolution_verdict": str(result.resolution.get("verdict", "")),
        "resolved_title": str(result.resolution.get("title", "")),
        "resolved_year": result.resolution.get("year"),
        "canonical_metadata_quality": _resolution_metadata_quality(result.resolution),
        "source_metadata_missing_fields": _resolution_metadata_missing_fields(result.resolution),
        "source_metadata_confidence_effect": _resolution_metadata_confidence_effect(result.resolution),
        "evidence_scope": result.evidence_scope,
        "evidence_source_field": str(result.evidence.get("source_field", "")),
        "evidence_source_url": str(result.evidence.get("source_url", "")),
        "evidence_source_name": str(
            result.evidence.get("source_name")
            or infer_evidence_source_name(
                result.evidence.get("source_field", ""), result.evidence.get("source_url", "")
            )
        ),
        "next_action": next_action,
        "suggested_fix": _support_suggested_fix(result, next_action),
        "recommendation": recommendation,
    }
    item.update(_support_result_input_source_provenance(result))
    item.update(_counterevidence_review_for_result(result))
    return item


def _support_set_risk_item(index: int, result: ClaimSupportSetResult) -> Dict[str, Any]:
    if result.risk == "high":
        score = 0.98
    elif result.risk == "low":
        score = 0.05
    else:
        score = 0.72 if result.verdict == SupportVerdict.INSUFFICIENT_EVIDENCE else 0.6
    evidence_provenance = _support_set_evidence_provenance(result)
    item = {
        "index": index,
        "verdict": result.verdict.value,
        "risk": result.risk,
        "risk_score": round(score, 4),
        "risk_reason": _support_set_risk_reason(result),
        "claim": result.claim,
        "support_confidence": round(result.confidence, 4),
        "support_engine": "citation_set",
        "summary": dict(result.summary),
        "evidence_scope": result.evidence_scope,
        "evidence_scopes": evidence_provenance["evidence_scopes"],
        "evidence_source_names": evidence_provenance["evidence_source_names"],
        "evidence_source_fields": evidence_provenance["evidence_source_fields"],
        "source_metadata_missing_fields": _support_set_metadata_missing_fields(result),
        "source_metadata_confidence_effects": _support_set_metadata_confidence_effects(result),
        "support_mode": result.support_mode,
        "support_mode_details": _support_set_mode_details(result),
        "supporting_citation_count": result.supporting_citation_count,
        "contradicting_citation_count": result.contradicting_citation_count,
        "next_action": _support_set_next_action(result.verdict),
        "suggested_fix": _support_set_suggested_fix(result),
        "recommendation": result.recommendation,
    }
    item.update(_support_set_input_source_provenance(result))
    item.update(_counterevidence_review_for_set(result.verdict, result.summary))
    return item


def _support_risk_reason(result: SupportResult) -> str:
    if result.verdict == SupportVerdict.SUPPORTED:
        return "available_evidence_supports_claim"
    if result.verdict == SupportVerdict.WEAKLY_SUPPORTED:
        return "available_evidence_is_partial"
    if result.verdict == SupportVerdict.CONTRADICTED:
        return "available_evidence_contradicts_claim"
    resolution_verdict = str(result.resolution.get("verdict", ""))
    if resolution_verdict == "not_found":
        return "citation_identity_unresolved"
    if resolution_verdict == "ambiguous":
        return "citation_identity_ambiguous"
    return "available_evidence_does_not_confirm_claim"


def _support_set_risk_reason(result: ClaimSupportSetResult) -> str:
    reasons_by_mode = {
        "contradiction_dominates": "citation_set_contains_contradiction",
        "single_strong_support": "citation_set_has_single_strong_support",
        "multiple_strong_support": "citation_set_has_multiple_strong_support",
        "multiple_weak_support": "citation_set_has_only_weak_support",
        "single_weak_support": "citation_set_has_only_weak_support",
        "insufficient_evidence": "citation_set_evidence_does_not_confirm_claim",
    }
    return reasons_by_mode.get(result.support_mode, "citation_set_requires_review")


def _support_suggested_fix(result: SupportResult, next_action: str) -> Dict[str, Any]:
    resolution_verdict = str(result.resolution.get("verdict", ""))
    if next_action in {"resolve_citation_identity", "disambiguate_identifier"}:
        return {
            "kind": "resolve_citation_identity",
            "action": next_action,
            "resolution_verdict": resolution_verdict,
            "requested_identifiers": ["doi", "arxiv_id"],
            "requires_user_confirmation": True,
            "policy": "resolve_identity_before_judging_support",
        }
    if next_action == "rewrite_or_replace_evidence":
        return {
            "kind": "rewrite_claim_or_replace_evidence",
            "action": next_action,
            "requires_user_confirmation": True,
            "policy": "contradicted_support_requires_human_review",
        }
    if next_action in {"tighten_claim_or_inspect_full_text", "inspect_full_text_or_find_stronger_citation"}:
        return {
            "kind": "inspect_full_text_or_find_stronger_citation",
            "action": next_action,
            "evidence_scope": result.evidence_scope,
            "requires_user_confirmation": True,
            "policy": "limited_evidence_is_not_final_full_text_judgment",
        }
    return {
        "kind": "keep_claim",
        "action": next_action,
        "evidence_scope": result.evidence_scope,
        "requires_user_confirmation": False,
    }


def _support_set_suggested_fix(result: ClaimSupportSetResult) -> Dict[str, Any]:
    next_action = _support_set_next_action(result.verdict)
    if next_action == "keep_claim":
        return {
            "kind": "keep_claim",
            "action": next_action,
            "support_mode": result.support_mode,
            "requires_user_confirmation": False,
        }
    if next_action == "rewrite_or_replace_evidence":
        return {
            "kind": "rewrite_claim_or_replace_evidence",
            "action": next_action,
            "support_mode": result.support_mode,
            "requires_user_confirmation": True,
            "policy": "contradicted_support_requires_human_review",
        }
    return {
        "kind": "inspect_full_text_or_find_stronger_citation",
        "action": next_action,
        "support_mode": result.support_mode,
        "evidence_scope": result.evidence_scope,
        "requires_user_confirmation": True,
        "policy": "multiple_weak_or_insufficient_support_remains_tentative",
    }


def _support_result_input_source_provenance(result: SupportResult) -> Dict[str, Any]:
    return input_source_provenance(result.resolution)


def _support_set_input_source_provenance(result: ClaimSupportSetResult) -> Dict[str, Any]:
    paths = []
    formats = []
    types = []
    ids = []
    indexes = []
    locators = []
    line_starts = []
    line_ends = []
    for child in result.results:
        provenance = input_source_provenance(child.resolution)
        if provenance.get("input_source_path"):
            paths.append(str(provenance["input_source_path"]))
        if provenance.get("input_source_format"):
            formats.append(str(provenance["input_source_format"]))
        if provenance.get("input_source_type"):
            types.append(str(provenance["input_source_type"]))
        if provenance.get("input_source_id"):
            ids.append(str(provenance["input_source_id"]))
        if provenance.get("input_source_index") is not None:
            indexes.append(provenance["input_source_index"])
        if provenance.get("input_source_locator"):
            locators.append(str(provenance["input_source_locator"]))
        if provenance.get("input_source_line_start") is not None:
            line_starts.append(provenance["input_source_line_start"])
        if provenance.get("input_source_line_end") is not None:
            line_ends.append(provenance["input_source_line_end"])
    return {
        "input_source_paths": _ordered_nonempty_values(paths, default="none"),
        "input_source_formats": _ordered_nonempty_values(formats, default="none"),
        "input_source_types": _ordered_nonempty_values(types, default="none"),
        "input_source_ids": _ordered_nonempty_values(ids, default="none"),
        "input_source_indexes": indexes,
        "input_source_locators": _ordered_nonempty_values(locators, default="none"),
        "input_source_line_starts": line_starts,
        "input_source_line_ends": line_ends,
    }


def _resolution_metadata_quality(resolution: Dict[str, Any]) -> Dict[str, Any]:
    quality = resolution.get("canonical_metadata_quality", {})
    return dict(quality) if isinstance(quality, dict) else {}


def _resolution_metadata_missing_fields(resolution: Dict[str, Any]) -> List[str]:
    fields = resolution.get("source_metadata_missing_fields")
    if isinstance(fields, list):
        return [str(field) for field in fields]
    quality = _resolution_metadata_quality(resolution)
    quality_fields = quality.get("missing_fields", [])
    return [str(field) for field in quality_fields] if isinstance(quality_fields, list) else []


def _resolution_metadata_confidence_effect(resolution: Dict[str, Any]) -> str:
    effect = resolution.get("source_metadata_confidence_effect")
    if effect:
        return str(effect)
    quality = _resolution_metadata_quality(resolution)
    return str(quality.get("confidence_effect", "")) if quality else ""


def _support_set_metadata_missing_fields(result: ClaimSupportSetResult) -> List[str]:
    fields: List[str] = []
    for child in result.results:
        fields.extend(_resolution_metadata_missing_fields(child.resolution))
    return _ordered_nonempty_values(fields, default="none")


def _support_set_metadata_confidence_effects(result: ClaimSupportSetResult) -> List[str]:
    effects = [_resolution_metadata_confidence_effect(child.resolution) for child in result.results]
    return _ordered_nonempty_values(effects, default="none")


def _support_audit_risk_item(
    index: int,
    result: Union[SupportResult, ClaimSupportSetResult],
    input_mode: str,
) -> Dict[str, Any]:
    if isinstance(result, ClaimSupportSetResult):
        item = _support_set_risk_item(index, result)
    else:
        item = _support_risk_item(index, result)
    item["input_mode"] = input_mode
    return item
