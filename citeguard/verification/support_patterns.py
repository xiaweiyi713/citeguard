"""Auditable language rules for conservative support and outage handling."""

from __future__ import annotations

import json
import re
from importlib import resources
from typing import Any, Dict, Tuple

from citeguard.citation import normalize_text


def load_support_pattern_registry() -> Dict[str, Any]:
    """Load the packaged rule registry used to govern lexical safety rules."""

    path = resources.files(__package__).joinpath("support_pattern_registry.json")
    return json.loads(path.read_text(encoding="utf-8"))


_REGISTRY = load_support_pattern_registry()
_TERM_SETS = _REGISTRY["term_sets"]

ZH_SOURCE_OUTAGE_TERMS: Tuple[str, ...] = tuple(_TERM_SETS["zh_source_outage"])
ZH_FABRICATION_TERMS: Tuple[str, ...] = tuple(_TERM_SETS["zh_fabrication"])
ZH_CONFIDENCE_TERMS: Tuple[str, ...] = tuple(_TERM_SETS["zh_confidence"])
ZH_CONFIDENCE_REDUCTION_TERMS: Tuple[str, ...] = tuple(_TERM_SETS["zh_confidence_reduction"])
ZH_CERTAINTY_TERMS: Tuple[str, ...] = tuple(_TERM_SETS["zh_certainty"])
ZH_PROOF_DENIAL_TERMS: Tuple[str, ...] = tuple(_TERM_SETS["zh_proof_denial"])
ZH_EVIDENCE_DENIAL_TERMS: Tuple[str, ...] = tuple(_TERM_SETS["zh_evidence_denial"])
ZH_CLASSIFICATION_DENIAL_TERMS: Tuple[str, ...] = tuple(_TERM_SETS["zh_classification_denial"])
ZH_CLASSIFICATION_TERMS: Tuple[str, ...] = tuple(_TERM_SETS["zh_classification"])
ZH_RETRY_OR_HEALTH_TERMS: Tuple[str, ...] = tuple(_TERM_SETS["zh_retry_or_health"])


def english_contradiction_pattern(claim: str, evidence: str) -> bool:
    claim_text = normalize_text(claim)
    evidence_text = normalize_text(evidence)
    improvement_claim = re.search(
        r"\b(improves?|improved|increase[sd]?|increasing|boosts?|boosted|raises?|raised|gains?)\b",
        claim_text,
    )
    negative_result = re.search(
        r"\b(?:does|do|did)\s+not\s+(?:improve|increase|boost|raise|gain)\b"
        r"|\bnot\s+(?:improve|increase|boost|raise|gain)\b"
        r"|\b(reduces?|reduced|decreases?|decreased|lowers?|lowered|worse|harms?|harmed)\b",
        evidence_text,
    )
    if improvement_claim and negative_result:
        return True

    necessity_claim = re.search(r"\b(always|must|required|requires|necessary|only|all|every)\b", claim_text)
    optional_evidence = re.search(
        r"\b(optional|not\s+required|not\s+necessary|need\s+not|does\s+not\s+require|do\s+not\s+require|by\s+default)\b",
        evidence_text,
    )
    if necessity_claim and optional_evidence:
        return True

    support_claim = re.search(r"\b(supports?|supported|proves?|proved|demonstrates?|shows?)\b", claim_text)
    negative_support_claim = re.search(
        r"\b(?:not|fail(?:s|ed|ing)?|without|cannot|does\s+not|do\s+not|did\s+not)\s+(?:to\s+)?support\b",
        claim_text,
    )
    support_denial = re.search(
        r"\b(?:does|do|did)\s+not\s+support\b|\bnot\s+support\b|\bfails?\s+to\s+support\b",
        evidence_text,
    )
    if support_claim and not negative_support_claim and support_denial:
        return True

    verdict_claim = re.search(
        r"\b(?:is|are)\b.*\b(?:final|definitive)\b.*\b(?:verdicts?|decisions?|proof)\b",
        claim_text,
    )
    verdict_denial = re.search(
        r"\b(?:must|should|can)\s+not\b.*\b(?:presented|treated|classified|used)\b.*"
        r"\b(?:verdicts?|decisions?|proof)\b",
        evidence_text,
    )
    if verdict_claim and verdict_denial:
        return True

    fabrication_claim = re.search(r"\b(?:treats?|marks?|labels?|flags?|classifies?)\b.*\bfabricated\b", claim_text)
    fabrication_denial = re.search(
        r"\b(?:does|do|did)\s+not\s+(?:treat|mark|label|flag|classify)\b.*\bfabricated\b"
        r"|\bnot\s+(?:treat|mark|label|flag|classify)(?:ed)?\b.*\bfabricated\b",
        evidence_text,
    )
    return bool(fabrication_claim and fabrication_denial)


def full_text_boundary_pattern(claim: str, evidence: str) -> bool:
    """Detect claims that require details explicitly absent from the supplied excerpt."""

    claim_text = normalize_text(claim)
    evidence_text = normalize_text(evidence)
    detailed_claim = re.search(
        r"\b(?:excluded?|exclusion|eligibility|all|every|complete|full|supplement(?:ary)?|appendix|methods?)\b",
        claim_text,
    )
    deferred_evidence = re.search(
        r"\b(?:does|do|did)\s+not\s+(?:describe|report|include|state)\b"
        r"|\b(?:not|never)\s+(?:described|reported|included|stated)\b"
        r"|\b(?:see|refer(?:s|red)?\s+to|available\s+in)\b.*\b(?:supplement(?:ary)?|appendix|full[-\s]?text|methods?)\b",
        evidence_text,
    )
    zh_detailed_claim = any(term in claim_text for term in ("所有", "全部", "完整", "排除标准", "纳入标准", "补充材料", "附录"))
    zh_deferred_evidence = any(
        term in evidence_text
        for term in ("未描述", "没有描述", "未报告", "没有报告", "详见补充材料", "见补充材料", "摘要仅", "全文详见")
    )
    return bool((detailed_claim and deferred_evidence) or (zh_detailed_claim and zh_deferred_evidence))


def human_review_provenance_boundary_pattern(claim: str, evidence: str) -> bool:
    """Detect human-review claims that exceed explicitly synthetic provenance."""

    claim_text = normalize_text(claim)
    evidence_text = normalize_text(evidence)
    human_review_claim = re.search(
        r"\b(?:independent(?:ly)?|human[-\s]?reviewed|human[-\s]?annotated|adjudicated)\b.*\bbenchmark\b"
        r"|\bbenchmark\b.*\b(?:independent(?:ly)?|human[-\s]?reviewed|human[-\s]?annotated|adjudicated)\b",
        claim_text,
    )
    synthetic_boundary = re.search(
        r"\b(?:maintainer[-\s]?authored|synthetic|not\s+human[-\s]?reviewed|"
        r"independent\s+(?:annotation|review|adjudication).{0,30}\bplanned)\b",
        evidence_text,
    )
    zh_human_review_claim = "基准" in claim_text and any(
        term in claim_text for term in ("独立评审", "人工评审", "人工标注", "人工裁决")
    )
    zh_synthetic_boundary = any(
        term in evidence_text for term in ("维护者合成", "维护者编写", "未人工评审", "尚未人工评审", "计划独立评审")
    )
    return bool(
        (human_review_claim and synthetic_boundary)
        or (zh_human_review_claim and zh_synthetic_boundary)
    )


def source_outage_safety_pattern(claim: str, evidence: str) -> bool:
    claim_text = normalize_text(claim)
    evidence_text = normalize_text(evidence)
    outage_claim = re.search(
        r"\b(?:source|sources|outage|outages|unavailable|timeout|timeouts|not_found|not\s+found|missing)\b",
        claim_text,
    )
    zh_outage_claim = any(term in claim_text for term in ZH_SOURCE_OUTAGE_TERMS) or bool(
        re.search(r"(?:来源?|数据源).{0,4}(?:不可达|失败|故障)", claim_text)
    )
    fabrication_claim = re.search(r"\b(?:fabricated|fake|false|hallucinated|forged)\b", claim_text)
    zh_fabrication_claim = any(term in claim_text for term in ZH_FABRICATION_TERMS)
    confidence_claim = re.search(r"\b(?:increase|raises?|boosts?|proves?|evidence|confidence)\b", claim_text)
    zh_confidence_claim = any(term in claim_text for term in ZH_CONFIDENCE_TERMS)
    unsafe_inference_claim = re.search(
        r"\b(?:proves?|means?|demonstrates?|indicates?|treats?|labels?|classifies?|marks?|"
        r"increases?|raises?|boosts?)\b",
        claim_text,
    )
    zh_unsafe_inference_claim = any(
        term in claim_text
        for term in ("证明", "意味着", "表明", "判定", "标记", "归类", "就是", "作为", "提高", "增加", "提升")
    )
    zh_claim_denial = (
        any(term in claim_text for term in ZH_PROOF_DENIAL_TERMS + ZH_EVIDENCE_DENIAL_TERMS)
        or bool(re.search(r"(?:不应|不能|不可(?:将|把|视为|判定|标记|归类))", claim_text))
    )
    if not (outage_claim or zh_outage_claim) or not (
        fabrication_claim or zh_fabrication_claim or confidence_claim or zh_confidence_claim
    ):
        return False
    if not unsafe_inference_claim and (not zh_unsafe_inference_claim or zh_claim_denial):
        return False

    outage_evidence = re.search(
        r"\b(?:source|sources|outage|outages|unavailable|timeout|timeouts|not_found|not\s+found|missing)\b",
        evidence_text,
    )
    zh_outage_evidence = any(term in evidence_text for term in ZH_SOURCE_OUTAGE_TERMS) or bool(
        re.search(r"(?:来源?|数据源).{0,4}(?:不可达|失败|故障)", evidence_text)
    )
    safety_evidence = re.search(
        r"\b(?:lower|lowers|reduced?|decrease[sd]?|inconclusive|retry|source[-\s]?health)\b.*"
        r"\b(?:confidence|certainty|inspection|check)\b"
        r"|\bnot\s+(?:evidence|proof)\b.*\b(?:fabricated|fake|false|hallucinated|forged)\b"
        r"|\bmust\s+not\b.*\b(?:fabricated|fake|false|hallucinated|forged)\b",
        evidence_text,
    )
    zh_safety_evidence = (
        (any(term in evidence_text for term in ZH_CONFIDENCE_REDUCTION_TERMS)
         and any(term in evidence_text for term in ZH_CERTAINTY_TERMS))
        or (any(term in evidence_text for term in ZH_PROOF_DENIAL_TERMS)
            and any(term in evidence_text for term in ZH_FABRICATION_TERMS))
        or (any(term in evidence_text for term in ZH_EVIDENCE_DENIAL_TERMS)
            and any(term in evidence_text for term in ZH_FABRICATION_TERMS))
        or (any(term in evidence_text for term in ZH_CLASSIFICATION_DENIAL_TERMS)
            and any(term in evidence_text for term in ZH_CLASSIFICATION_TERMS)
            and any(term in evidence_text for term in ZH_FABRICATION_TERMS))
        or any(term in evidence_text for term in ZH_RETRY_OR_HEALTH_TERMS)
    )
    return bool((outage_evidence or zh_outage_evidence) and (safety_evidence or zh_safety_evidence))


def chinese_contradiction_pattern(claim: str, evidence: str) -> bool:
    claim_text = normalize_text(claim)
    evidence_text = normalize_text(evidence)
    universal_claim = any(term in claim_text for term in ("一定", "总是", "所有", "全部", "必然", "必须"))
    universal_denial = any(term in evidence_text for term in ("未必", "不一定", "并非", "不总是", "不必", "可选"))
    if universal_claim and universal_denial:
        return True
    improvement_claim = any(term in claim_text for term in ("提升", "提高", "增加", "改善"))
    negative_result = any(term in evidence_text for term in ("降低", "减少", "未提升", "没有提升", "不提升", "下降"))
    if improvement_claim and negative_result:
        return True
    support_denials = ("不支持", "未支持", "未必支持", "不能支持")
    return (
        "支持" in claim_text
        and not any(term in claim_text for term in support_denials)
        and any(term in evidence_text for term in support_denials)
    )
