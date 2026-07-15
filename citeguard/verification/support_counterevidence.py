"""Counter-evidence query planning, retrieval, ranking, and payload enrichment."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from citeguard.citation import normalize_text, tokenize_text
from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients.base import MetadataSource

from .models import classify_source_failure_mode
from .resolve import source_names
from .support import CounterEvidenceSearchReport
from .support_patterns import (
    ZH_CERTAINTY_TERMS as _ZH_CERTAINTY_TERMS,
    ZH_CONFIDENCE_REDUCTION_TERMS as _ZH_CONFIDENCE_REDUCTION_TERMS,
    ZH_EVIDENCE_DENIAL_TERMS as _ZH_EVIDENCE_DENIAL_TERMS,
    ZH_FABRICATION_TERMS as _ZH_FABRICATION_TERMS,
    ZH_PROOF_DENIAL_TERMS as _ZH_PROOF_DENIAL_TERMS,
    ZH_RETRY_OR_HEALTH_TERMS as _ZH_RETRY_OR_HEALTH_TERMS,
    ZH_SOURCE_OUTAGE_TERMS as _ZH_SOURCE_OUTAGE_TERMS,
    chinese_contradiction_pattern as _chinese_contradiction_pattern,
    english_contradiction_pattern as _english_contradiction_pattern,
    source_outage_safety_pattern as _source_outage_safety_pattern,
)
from .support_reporting import (
    _dedupe_failure_details,
    _exception_failure_details,
    _snippet,
    _source_failure_details,
)


def search_counterevidence_candidates(
    claim: str,
    source: MetadataSource,
    top_k: int = 5,
) -> CounterEvidenceSearchReport:
    """Search scholarly metadata for papers that may contain counter-evidence.

    The report is intentionally conservative. It returns ranked leads with
    lexical contradiction cues, but never changes the support verdict for a
    claim and never treats an empty result as proof that no counter-evidence
    exists.
    """

    cleaned_claim = " ".join(str(claim).split())
    checked = source_names(source)
    if not cleaned_claim:
        return CounterEvidenceSearchReport(
            claim=cleaned_claim,
            queries=[],
            candidates=[],
            sources_checked=checked,
            sources_responded=[],
        )

    query_plan = _counterevidence_query_plan(cleaned_claim)
    queries = [item["query"] for item in query_plan]
    records: List[CitationRecord] = []
    failures: List[str] = []
    failure_details: List[Dict[str, Any]] = []
    query_results: List[Dict[str, Any]] = []
    record_query_matches: Dict[str, Dict[str, Any]] = {}
    per_query = max(top_k * 2, 5)
    for query_item in query_plan:
        query = query_item["query"]
        query_records: List[CitationRecord] = []
        query_failures: List[str] = []
        query_failure_details: List[Dict[str, Any]] = []
        try:
            query_records = source.search(query, top_k=per_query)
            records.extend(query_records)
        except Exception as exc:
            query_failures.extend(checked)
            query_failure_details.extend(_exception_failure_details(checked, exc))
        query_failure_details.extend(_source_failure_details(source))
        inner = getattr(source, "inner", source)
        query_failures.extend(getattr(inner, "last_failures", []))
        query_failure_details.extend(getattr(inner, "last_failure_details", []))
        query_failures.extend(
            str(detail.get("source", ""))
            for detail in query_failure_details
            if detail.get("source") and detail.get("code")
        )
        for record in query_records:
            key = _counterevidence_record_key(record)
            match = record_query_matches.setdefault(key, {"queries": [], "roles": [], "rationales": []})
            if query not in match["queries"]:
                match["queries"].append(query)
            if query_item["role"] not in match["roles"]:
                match["roles"].append(query_item["role"])
            if query_item["rationale"] not in match["rationales"]:
                match["rationales"].append(query_item["rationale"])
        failures.extend(query_failures)
        failure_details.extend(query_failure_details)
        query_results.append(
            {
                "query": query,
                "role": query_item["role"],
                "rationale": query_item["rationale"],
                "returned": len(query_records),
                "sources_failed": sorted(set(query_failures)),
                "source_failure_mode": classify_source_failure_mode(
                    checked,
                    sorted(set(query_failures)),
                    sorted({record.source for record in query_records if record.source}),
                ),
            }
        )

    scored = _rank_counterevidence_records(
        cleaned_claim,
        _dedupe_counterevidence_records(records),
        record_query_matches=record_query_matches,
    )
    candidates = [item for item in scored[: max(0, int(top_k))]]
    responded = sorted({str(item.get("source", "")) for item in candidates if item.get("source")})
    failed = sorted(set(failures))
    failure_details = _dedupe_failure_details(failure_details)
    failed = sorted(
        set(failed)
        | {str(detail.get("source", "")) for detail in failure_details if detail.get("source") and detail.get("code")}
    )
    return CounterEvidenceSearchReport(
        claim=cleaned_claim,
        queries=queries,
        candidates=candidates,
        sources_checked=checked,
        sources_responded=responded,
        sources_failed=failed,
        source_failure_details=failure_details,
        source_failure_mode=classify_source_failure_mode(checked, failed, responded),
        query_plan=query_plan,
        query_results=query_results,
    )


def enrich_support_payload_with_counterevidence(
    payload: Dict[str, Any],
    source: MetadataSource,
    top_k: int = 3,
) -> Dict[str, Any]:
    """Attach counter-evidence lead searches to review-worthy support payloads."""

    enriched = dict(payload)
    cache: Dict[str, Dict[str, Any]] = {}

    def report_for_claim(claim: str) -> Dict[str, Any]:
        cleaned = " ".join(str(claim).split())
        if cleaned not in cache:
            cache[cleaned] = search_counterevidence_candidates(cleaned, source, top_k=top_k).to_dict()
        return cache[cleaned]

    def attach(item: Dict[str, Any]) -> None:
        if not item.get("counterevidence_review"):
            return
        claim = str(item.get("claim", "")).strip()
        if not claim:
            return
        item["counterevidence"] = report_for_claim(claim)

    results = []
    for result in enriched.get("results", []):
        item = dict(result)
        attach(item)
        results.append(item)
    if results:
        enriched["results"] = results

    risk_ranking = []
    for risk_item in enriched.get("risk_ranking", []):
        item = dict(risk_item)
        index = item.get("index")
        if isinstance(index, int) and 0 <= index < len(results):
            counterevidence = results[index].get("counterevidence")
            if counterevidence:
                item["counterevidence"] = counterevidence
        else:
            attach(item)
        risk_ranking.append(item)
    if risk_ranking:
        enriched["risk_ranking"] = risk_ranking

    if enriched.get("counterevidence_review") and "counterevidence" not in enriched:
        attach(enriched)

    enriched["counterevidence_included"] = True
    enriched["counterevidence_top_k"] = max(0, int(top_k))
    return enriched


def _counterevidence_queries(claim: str) -> List[str]:
    return [item["query"] for item in _counterevidence_query_plan(claim)]


def _counterevidence_query_plan(claim: str) -> List[Dict[str, str]]:
    queries = [
        {
            "query": claim,
            "role": "claim_similarity",
            "rationale": "Find papers closely related to the original claim before adding negation probes.",
        }
    ]
    normalized = normalize_text(claim)
    if re.search(r"\b(improves?|improved|increase[sd]?|boosts?|raises?|gains?)\b", normalized):
        queries.append(
            {
                "query": f"{claim} does not improve no improvement decreases worse",
                "role": "improvement_negation",
                "rationale": "Probe for papers reporting no improvement, decreases, or worse outcomes.",
            }
        )
    if re.search(r"\b(supports?|supported|proves?|demonstrates?|shows?)\b", normalized):
        queries.append(
            {
                "query": f"{claim} does not support fails to support no evidence",
                "role": "support_negation",
                "rationale": "Probe for papers saying the evidence does not support the claim.",
            }
        )
    if re.search(r"\b(always|must|required|requires|necessary|only|all|every)\b", normalized):
        queries.append(
            {
                "query": f"{claim} optional not required not necessary exception",
                "role": "necessity_exception",
                "rationale": "Probe for exceptions to absolute or necessity claims.",
            }
        )
    if re.search(
        r"\b(source|sources|outage|outages|unavailable|timeout|timeouts|not_found|not\s+found|fabricated|fake|hallucinated)\b",
        normalized,
    ) or any(term in normalized for term in _ZH_SOURCE_OUTAGE_TERMS + _ZH_FABRICATION_TERMS):
        zh_safety_terms = " ".join(
            _ZH_SOURCE_OUTAGE_TERMS
            + _ZH_PROOF_DENIAL_TERMS
            + _ZH_EVIDENCE_DENIAL_TERMS
            + _ZH_CONFIDENCE_REDUCTION_TERMS
            + _ZH_CERTAINTY_TERMS
            + _ZH_FABRICATION_TERMS
            + _ZH_RETRY_OR_HEALTH_TERMS
        )
        queries.append(
            {
                "query": (
                    f"{claim} source outage unavailable timeout not found "
                    f"not evidence fabricated lower confidence inconclusive {zh_safety_terms}"
                ),
                "role": "source_outage_safety",
                "rationale": (
                    "Probe for evidence that source outages or not-found results lower confidence "
                    "without proving fabrication."
                ),
            }
        )
    if any(term in normalized for term in ("提升", "提高", "增加", "改善")):
        queries.append(
            {
                "query": f"{claim} 未提升 没有提升 降低 减少",
                "role": "zh_improvement_negation",
                "rationale": "检索未提升、降低或减少等中文反向证据线索。",
            }
        )
    if any(term in normalized for term in ("一定", "总是", "所有", "全部", "必须")):
        queries.append(
            {
                "query": f"{claim} 未必 不一定 并非 可选",
                "role": "zh_necessity_exception",
                "rationale": "检索绝对化或必要性表述的例外线索。",
            }
        )
    deduped = []
    seen = set()
    for item in queries:
        query = item["query"]
        if query not in seen:
            seen.add(query)
            deduped.append(item)
    return deduped


def _counterevidence_record_key(record: CitationRecord) -> str:
    return record.doi.lower() or record.arxiv_id.lower() or normalize_text(record.title) or record.citation_id


def _dedupe_counterevidence_records(records: List[CitationRecord]) -> List[CitationRecord]:
    deduped: List[CitationRecord] = []
    seen = set()
    for record in records:
        key = _counterevidence_record_key(record)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _rank_counterevidence_records(
    claim: str,
    records: List[CitationRecord],
    record_query_matches: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    ranked = []
    record_query_matches = record_query_matches or {}
    for record in records:
        text = " ".join(part for part in [record.title, record.abstract] if part)
        if not text:
            continue
        claim_tokens = set(tokenize_text(claim))
        record_tokens = set(tokenize_text(text))
        overlap = len(claim_tokens & record_tokens)
        relatedness = overlap / max(len(claim_tokens), 1)
        source_outage_safety_cue = _source_outage_safety_pattern(claim, text)
        explicit_cue = (
            source_outage_safety_cue
            or _english_contradiction_pattern(claim, text)
            or _chinese_contradiction_pattern(claim, text)
        )
        cue_score = 1.0 if explicit_cue else 0.0
        source_score = float(record.metadata.get("source_score", 0.0))
        score = min(1.0, 0.55 * relatedness + 0.35 * cue_score + 0.10 * source_score)
        if score <= 0.0:
            continue
        query_match = record_query_matches.get(_counterevidence_record_key(record), {})
        ranked.append(
            (
                score,
                {
                    "title": record.title,
                    "authors": list(record.authors),
                    "year": record.year,
                    "venue": record.venue,
                    "doi": record.doi,
                    "arxiv_id": record.arxiv_id,
                    "url": record.url,
                    "source": record.source,
                    "score": round(score, 4),
                    "signal": (
                        "source_outage_safety_cue"
                        if source_outage_safety_cue
                        else "explicit_contradiction_cue"
                        if explicit_cue
                        else "related_candidate"
                    ),
                    "matched_queries": list(query_match.get("queries", [])),
                    "matched_query_roles": list(query_match.get("roles", [])),
                    "match_rationales": list(query_match.get("rationales", [])),
                    "evidence_scope": "abstract" if record.abstract else "title",
                    "abstract_snippet": _snippet(record.abstract),
                    "citation_id": record.citation_id,
                },
            )
        )
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item for _, item in ranked]
