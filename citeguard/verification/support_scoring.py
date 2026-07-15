"""Evidence scoring and four-way verdict mapping for claim-support checks."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional

from citeguard.citation import tokenize_text
from citeguard.graph import CitationRecord
from citeguard.verifiers import SupportAssessment, SupportBackend, build_default_support_backend

from .support import (
    SupportDecisionPolicy,
    SupportResult,
    SupportVerdict,
    build_evidence_spans,
    infer_evidence_scope,
    infer_evidence_source_name,
)
from .support_patterns import (
    chinese_contradiction_pattern as _chinese_contradiction_pattern,
    english_contradiction_pattern as _english_contradiction_pattern,
    full_text_boundary_pattern as _full_text_boundary_pattern,
    human_review_provenance_boundary_pattern as _human_review_provenance_boundary_pattern,
    source_outage_safety_pattern as _source_outage_safety_pattern,
)


def _extract_nli(assessment: SupportAssessment) -> Optional[Dict[str, float]]:
    """Pull NLI probabilities out of an ensemble or NLI assessment, if present."""

    if assessment.backend_name == "transformers_nli":
        probs = assessment.details.get("probabilities")
        return dict(probs) if probs else None
    if assessment.backend_name == "ensemble_support":
        for component in assessment.details.get("components", []):
            if component.get("backend") == "transformers_nli":
                probs = component.get("details", {}).get("probabilities")
                return dict(probs) if probs else None
    return None


def _component_score(assessment: SupportAssessment, backend_name: str) -> float:
    if assessment.backend_name == backend_name:
        return float(assessment.score)
    for component in assessment.details.get("components", []):
        if component.get("backend") == backend_name:
            return float(component.get("score", 0.0))
    return 0.0


def _component_passed(assessment: SupportAssessment, backend_name: str) -> bool:
    if assessment.backend_name == backend_name:
        return bool(assessment.passed)
    for component in assessment.details.get("components", []):
        if component.get("backend") == backend_name:
            return bool(component.get("passed", False))
    return False


def _prob(nli: Optional[Dict[str, float]], key: str) -> float:
    return float(nli.get(key, 0.0)) if nli else 0.0


def _explicit_contradiction_confidence(claim: str, evidence: str, score: float = 0.0) -> float:
    """Return a conservative confidence for explicit claim/evidence contradiction cues."""

    if not claim or not evidence:
        return 0.0
    source_outage_safety = _source_outage_safety_pattern(claim, evidence)
    if not _is_related_enough(claim, evidence) and not source_outage_safety:
        return 0.0
    if not (
        _english_contradiction_pattern(claim, evidence)
        or _chinese_contradiction_pattern(claim, evidence)
        or source_outage_safety
    ):
        return 0.0

    claim_tokens = set(tokenize_text(claim))
    evidence_tokens = set(tokenize_text(evidence))
    overlap = claim_tokens & evidence_tokens
    coverage = len(overlap) / max(len(claim_tokens), 1)
    precision = len(overlap) / max(len(evidence_tokens), 1)
    confidence = 0.50 + 0.40 * coverage + 0.20 * precision + 0.10 * min(max(score, 0.0), 1.0)
    return round(min(0.85, max(0.58, confidence)), 4)


def _is_related_enough(claim: str, evidence: str) -> bool:
    claim_tokens = set(tokenize_text(claim))
    evidence_tokens = set(tokenize_text(evidence))
    overlap = claim_tokens & evidence_tokens
    if not overlap:
        return False
    coverage = len(overlap) / max(len(claim_tokens), 1)
    precision = len(overlap) / max(len(evidence_tokens), 1)
    return (len(overlap) >= 2 and coverage >= 0.25) or (len(overlap) >= 3 and precision >= 0.15)


def _span_evidence_scope(span: Dict[str, str]) -> str:
    return span.get("evidence_scope") or infer_evidence_scope(span.get("source_field", ""), span.get("source_url", ""))


def _support_anchor_score(claim: str, span: Dict[str, str], assessment: SupportAssessment) -> float:
    heuristic_score = _component_score(assessment, "heuristic_support")
    if heuristic_score > 0.0:
        return heuristic_score
    if _component_passed(assessment, "heuristic_support"):
        return max(heuristic_score, 0.18)
    if _is_related_enough(claim, span["text"]):
        return max(heuristic_score, 0.18)
    return 0.0


def _direct_metadata_support_candidate(
    claim: str,
    span: Dict[str, str],
    assessment: SupportAssessment,
    entailment: float,
    contradiction: float,
    policy: SupportDecisionPolicy,
) -> bool:
    scope = _span_evidence_scope(span)
    if scope not in ("metadata_snippet", "full_text"):
        return False
    if entailment < max(0.40, policy.entail_weak):
        return False
    if entailment < contradiction + policy.margin:
        return False
    return _support_anchor_score(claim, span, assessment) >= 0.18


def _weak_support_candidate(
    claim: str,
    span: Dict[str, str],
    assessment: SupportAssessment,
    nli: Optional[Dict[str, float]],
    policy: SupportDecisionPolicy,
) -> bool:
    anchor = _support_anchor_score(claim, span, assessment)
    if anchor <= 0.0:
        return False

    scope = _span_evidence_scope(span)
    if scope == "title" and anchor >= 0.25:
        return True

    entailment = _prob(nli, "entailment")
    contradiction = _prob(nli, "contradiction")
    if nli and contradiction >= entailment + policy.margin:
        return False
    if nli and entailment >= policy.entail_weak and entailment >= contradiction + policy.margin:
        return True

    return assessment.score >= policy.weak_relatedness and anchor >= 0.12


def assess_support(
    claim: str,
    citation: CitationRecord,
    backend: Optional[SupportBackend] = None,
    policy: SupportDecisionPolicy = SupportDecisionPolicy(),
    lang: str = "",
    resolution: Optional[Dict[str, Any]] = None,
) -> SupportResult:
    """Judge whether `citation` supports `claim`, over abstract-level evidence."""

    backend = backend or build_default_support_backend()
    resolution = resolution if resolution is not None else {"verdict": "matched", "title": citation.title}

    spans = build_evidence_spans(citation)
    if not spans:
        return SupportResult(
            verdict=SupportVerdict.INSUFFICIENT_EVIDENCE,
            confidence=0.0,
            claim=claim,
            evidence={
                "text": "",
                "source_field": "none",
                "source_url": "",
                "evidence_scope": "none",
                "source_name": "none",
            },
            nli_scores=None,
            engine="heuristic",
            resolution=resolution,
            explanation="No abstract or evidence text was available to judge support.",
            lang=lang,
            evidence_scope="none",
        )

    assessed = []
    for span in spans:
        assessment = backend.assess(claim, span["text"])
        assessed.append((span, assessment, _extract_nli(assessment)))
    model_failures = _model_failure_details_from_assessed(assessed)

    def emit(result: SupportResult) -> SupportResult:
        if not model_failures:
            return result
        return replace(result, model_failure_details=model_failures)

    engine = "ensemble" if any(nli for _, _, nli in assessed) else "heuristic"
    best_score_span, best_score_assessment, _ = max(
        assessed,
        key=lambda item: (item[1].score, _span_scope_priority(item[0])),
    )
    best_score = best_score_assessment.score

    if engine == "ensemble":
        ent_span, ent_assessment, ent_nli = max(
            assessed,
            key=lambda item: (_prob(item[2], "entailment"), _span_scope_priority(item[0])),
        )
        entailment = _prob(ent_nli, "entailment")
        ent_contra = _prob(ent_nli, "contradiction")
        related = [item for item in assessed if item[1].score >= policy.relatedness_floor]
        con_span, _, con_nli = max(
            related or assessed,
            key=lambda item: (_prob(item[2], "contradiction"), _span_scope_priority(item[0])),
        )
        contradiction = _prob(con_nli, "contradiction") if related else 0.0
        explicit_contradiction = max(
            (
                (_explicit_contradiction_confidence(claim, span["text"], assessment.score), span, nli)
                for span, assessment, nli in assessed
            ),
            key=lambda item: (item[0], _span_scope_priority(item[1])),
        )

        if explicit_contradiction[0] >= policy.contra_strong:
            return emit(
                _result(
                    SupportVerdict.CONTRADICTED,
                    explicit_contradiction[0],
                    claim,
                    explicit_contradiction[1],
                    explicit_contradiction[2],
                    engine,
                    resolution,
                    "The evidence contains an explicit contradiction cue for the claim.",
                    lang,
                )
            )
        full_text_boundary = max(
            (
                (
                    _full_text_boundary_pattern(claim, span["text"])
                    or _human_review_provenance_boundary_pattern(claim, span["text"]),
                    span,
                    nli,
                )
                for span, _assessment, nli in assessed
            ),
            key=lambda item: (item[0], _span_scope_priority(item[1])),
        )
        if full_text_boundary[0] and _span_evidence_scope(full_text_boundary[1]) != "full_text":
            return emit(
                _result(
                    SupportVerdict.INSUFFICIENT_EVIDENCE,
                    0.8,
                    claim,
                    full_text_boundary[1],
                    full_text_boundary[2],
                    engine,
                    resolution,
                    "The supplied evidence has a scope or provenance boundary that does not support the claim.",
                    lang,
                )
            )
        if entailment >= policy.entail_strong and entailment >= ent_contra + policy.margin:
            return emit(
                _result(
                    SupportVerdict.SUPPORTED,
                    entailment,
                    claim,
                    ent_span,
                    ent_nli,
                    engine,
                    resolution,
                    "The abstract entails the claim.",
                    lang,
                )
            )
        if contradiction >= policy.contra_strong:
            return emit(
                _result(
                    SupportVerdict.CONTRADICTED,
                    contradiction,
                    claim,
                    con_span,
                    con_nli,
                    engine,
                    resolution,
                    "The abstract contradicts the claim.",
                    lang,
                )
            )
        if _direct_metadata_support_candidate(
            claim,
            ent_span,
            ent_assessment,
            entailment,
            ent_contra,
            policy,
        ):
            return emit(
                _result(
                    SupportVerdict.SUPPORTED,
                    entailment,
                    claim,
                    ent_span,
                    ent_nli,
                    engine,
                    resolution,
                    "A source metadata or full-text evidence snippet directly supports the claim.",
                    lang,
                )
            )
        weak_candidates = []
        if _weak_support_candidate(claim, ent_span, ent_assessment, ent_nli, policy):
            weak_candidates.append(
                (
                    max(entailment, ent_assessment.score, _support_anchor_score(claim, ent_span, ent_assessment)),
                    ent_span,
                    ent_nli,
                )
            )
        if _weak_support_candidate(claim, best_score_span, best_score_assessment, None, policy):
            weak_candidates.append(
                (
                    max(best_score, _support_anchor_score(claim, best_score_span, best_score_assessment)),
                    best_score_span,
                    None,
                )
            )
        if weak_candidates:
            confidence, span, nli = max(weak_candidates, key=lambda item: (item[0], _span_scope_priority(item[1])))
            return emit(
                _result(
                    SupportVerdict.WEAKLY_SUPPORTED,
                    confidence,
                    claim,
                    span,
                    nli,
                    engine,
                    resolution,
                    "Partial or related evidence, but not strong enough.",
                    lang,
                )
            )
        return emit(
            _result(
                SupportVerdict.INSUFFICIENT_EVIDENCE,
                round(1.0 - best_score, 4),
                claim,
                best_score_span,
                ent_nli,
                engine,
                resolution,
                "The abstract does not address the claim (cannot confirm).",
                lang,
            )
        )

    if _weak_support_candidate(claim, best_score_span, best_score_assessment, None, policy):
        return emit(
            _result(
                SupportVerdict.WEAKLY_SUPPORTED,
                best_score,
                claim,
                best_score_span,
                None,
                engine,
                resolution,
                "Lexical overlap suggests relatedness; deep models not loaded.",
                lang,
            )
        )
    return emit(
        _result(
            SupportVerdict.INSUFFICIENT_EVIDENCE,
            round(1.0 - best_score, 4),
            claim,
            best_score_span,
            None,
            engine,
            resolution,
            "Insufficient lexical overlap; deep models not loaded.",
            lang,
        )
    )


def _result(verdict, confidence, claim, span, nli, engine, resolution, explanation, lang) -> SupportResult:
    evidence_scope = span.get("evidence_scope") or infer_evidence_scope(
        span["source_field"], span.get("source_url", "")
    )
    source_name = span.get("source_name") or infer_evidence_source_name(
        span["source_field"], span.get("source_url", "")
    )
    adjusted_confidence = _support_confidence_with_source_failures(float(confidence), resolution)
    if explanation.startswith("The abstract"):
        scope_subject = {
            "full_text": "The full-text evidence",
            "metadata_snippet": "The metadata evidence",
            "title": "The title",
        }.get(evidence_scope, "The abstract")
        explanation = scope_subject + explanation[len("The abstract") :]
    adjusted_explanation = explanation + _support_source_failure_note(resolution)
    return SupportResult(
        verdict=verdict,
        confidence=adjusted_confidence,
        claim=claim,
        evidence={
            "text": span["text"],
            "source_field": span["source_field"],
            "source_url": span.get("source_url", ""),
            "evidence_scope": evidence_scope,
            "source_name": source_name,
        },
        nli_scores=nli,
        engine=engine,
        resolution=resolution,
        explanation=adjusted_explanation,
        lang=lang,
        evidence_scope=evidence_scope,
    )


def _support_confidence_with_source_failures(confidence: float, resolution: Dict[str, Any]) -> float:
    if resolution.get("source_failure_mode") == "all_sources_failed":
        return round(min(confidence, 0.35), 4)
    if resolution.get("source_failure_mode") == "partial_outage":
        return round(min(confidence, 0.85), 4)
    return round(confidence, 4)


def _support_source_failure_note(resolution: Dict[str, Any]) -> str:
    if resolution.get("source_failure_mode") != "partial_outage":
        return ""
    failed = ", ".join(str(item) for item in resolution.get("sources_failed", []) if item)
    if not failed:
        return ""
    return f" Confidence is reduced because these sources failed: {failed}."


def _model_failure_details_from_assessed(assessed: List[tuple]) -> List[Dict[str, Any]]:
    failures: List[Dict[str, Any]] = []
    seen = set()
    for _, assessment, _ in assessed:
        candidates = [
            {"backend": assessment.backend_name, "details": assessment.details},
        ]
        for component in assessment.details.get("components", []):
            if isinstance(component, dict):
                candidates.append(
                    {
                        "backend": component.get("backend", ""),
                        "details": component.get("details", {}),
                    }
                )
        for candidate in candidates:
            details = candidate.get("details", {})
            if not isinstance(details, dict) or details.get("error_code") != "model_unavailable":
                continue
            item = {
                "backend": str(candidate.get("backend", "")),
                "model_name": str(details.get("model_name", "")),
                "error_code": "model_unavailable",
                "error_type": str(details.get("error_type", "")),
                "message": str(details.get("message", "")),
            }
            key = tuple(sorted(item.items()))
            if key in seen:
                continue
            seen.add(key)
            failures.append(item)
    return failures


def _span_scope_priority(span: Dict[str, str]) -> int:
    scope = span.get("evidence_scope") or infer_evidence_scope(span.get("source_field", ""), span.get("source_url", ""))
    return {
        "full_text": 5,
        "abstract": 4,
        "metadata_snippet": 3,
        "metadata": 2,
        "title": 1,
        "unknown": 0,
        "none": 0,
    }.get(scope, 0)
