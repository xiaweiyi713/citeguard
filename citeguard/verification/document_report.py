"""Human-readable manuscript audit summaries and HTML reports."""

from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence

from citeguard.graph import CitationRecord
from citeguard.verifiers.support_backends import HeuristicSupportBackend

from .support import SupportVerdict, assess_support


def _as_mapping(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


ISSUE_IDENTITY = "identity"
ISSUE_INSUFFICIENT_EVIDENCE = "insufficient_evidence"
ISSUE_CONTRADICTION = "contradiction"
ISSUE_SCOPE = "scope_overclaim"
ISSUE_UNLINKED = "unlinked_citation"
ISSUE_AMBIGUOUS = "ambiguous_attachment"
ISSUE_SOURCE_UNAVAILABLE = "source_unavailable"

ISSUE_CATEGORY = {
    ISSUE_IDENTITY: "metadata",
    ISSUE_UNLINKED: "metadata",
    ISSUE_AMBIGUOUS: "metadata",
    ISSUE_INSUFFICIENT_EVIDENCE: "insufficient_evidence",
    ISSUE_SCOPE: "insufficient_evidence",
    ISSUE_CONTRADICTION: "contradiction",
    ISSUE_SOURCE_UNAVAILABLE: "source_unavailable",
    "supported": "supported",
}

_OVERCLAIM_MARKERS = (
    "all tasks",
    "every task",
    "always",
    "on all",
    "in every",
    "universally",
    "所有任务",
    "全部任务",
    "总是",
    "均优于",
)


def attach_manuscript_audit(
    payload: Mapping[str, Any],
    documents: Sequence[Mapping[str, Any]],
    bibliography: Sequence[Mapping[str, Any]],
    *,
    support_backend: Any = None,
) -> Dict[str, Any]:
    """Add in-text links, claim reviews, and a first-screen summary to a document audit."""

    from .intext import link_document_citations

    linked = link_document_citations(documents, bibliography)
    audit = _as_mapping(payload.get("audit"))
    results = list(audit.get("results") or [])
    claim_reviews = build_claim_reviews(
        linked,
        results,
        bibliography,
        support_backend=support_backend,
    )
    review_queue = list(payload.get("review_queue") or [])
    review_queue.extend(_claim_review_queue_items(claim_reviews, start_rank=len(review_queue) + 1))
    for index, item in enumerate(review_queue, start=1):
        item["rank"] = index
    manuscript_summary = build_manuscript_summary(payload, linked, claim_reviews)
    updated = dict(payload)
    updated["body_links"] = linked["body_links"]
    updated["unlinked_markers"] = linked["unlinked_markers"]
    updated["claim_reviews"] = claim_reviews
    updated["manuscript_summary"] = manuscript_summary
    updated["review_queue"] = review_queue
    queue_summary = dict(updated.get("review_queue_summary") or {})
    queue_summary["count"] = len(review_queue)
    queue_summary["high_risk_count"] = sum(item.get("risk") == "high" for item in review_queue)
    queue_summary["medium_risk_count"] = sum(item.get("risk") == "medium" for item in review_queue)
    queue_summary["requires_user_confirmation_count"] = len(review_queue)
    queue_summary["unlinked_marker_count"] = len(linked["unlinked_markers"])
    queue_summary["claim_review_count"] = len(claim_reviews)
    updated["review_queue_summary"] = queue_summary
    review_status = dict(updated.get("review_status") or {})
    if review_queue or linked["unlinked_markers"]:
        review_status["state"] = "review_required"
        review_status["review_required"] = True
        review_status["queue_count"] = len(review_queue)
        if review_status.get("next_action") in {"", "continue", None}:
            review_status["next_action"] = str(review_queue[0]["next_action"]) if review_queue else "resolve_citation_identity"
    updated["review_status"] = review_status
    return updated


def build_claim_reviews(
    linked: Mapping[str, Any],
    audit_results: Sequence[Mapping[str, Any]],
    bibliography: Sequence[Mapping[str, Any]],
    *,
    support_backend: Any = None,
) -> List[Dict[str, Any]]:
    """Turn body links into conservative claim-level review items."""

    reviews: List[Dict[str, Any]] = []
    for item in list(linked.get("unlinked_markers") or []):
        reviews.append(
            _review_item(
                item,
                issue=ISSUE_UNLINKED,
                risk="high",
                next_action="resolve_citation_identity",
                identity_verdict="unlinked",
                support_verdict="",
                evidence_coverage="none",
                evidence_text="",
                problem="This in-text citation marker does not match any extracted bibliography entry.",
                suggestion="Add the corresponding bibliography entry or correct the citation key/number.",
                rewritten=_unchanged(item.get("sentence", "")),
            )
        )
    for item in list(linked.get("body_links") or []):
        if item.get("link_status") == "ambiguous":
            reviews.append(
                _review_item(
                    item,
                    issue=ISSUE_AMBIGUOUS,
                    risk="medium",
                    next_action="disambiguate_identifier",
                    identity_verdict="ambiguous",
                    support_verdict="",
                    evidence_coverage="none",
                    evidence_text="",
                    problem="The citation marker matches more than one bibliography entry.",
                    suggestion="Keep the candidate matches visible and add a unique key, number, or identifier.",
                    rewritten=_unchanged(item.get("sentence", "")),
                    extra={"bibliography_indexes": list(item.get("bibliography_indexes") or [])},
                )
            )
            continue
        index = item.get("bibliography_index")
        result = audit_results[index] if isinstance(index, int) and 0 <= index < len(audit_results) else {}
        identity = str(result.get("verdict") or "")
        if identity in {"not_found", "ambiguous"}:
            reviews.append(
                _review_item(
                    item,
                    issue=ISSUE_IDENTITY,
                    risk="high",
                    next_action="resolve_identifier_or_replace",
                    identity_verdict=identity or "not_found",
                    support_verdict="",
                    evidence_coverage="none",
                    evidence_text="",
                    problem="The bibliography entry attached to this sentence could not be resolved as a unique paper.",
                    suggestion="Supply a DOI or arXiv id, or replace the citation, before judging the claim.",
                    rewritten=_unchanged(item.get("sentence", "")),
                )
            )
            continue
        if result.get("outage_limited"):
            reviews.append(
                _review_item(
                    item,
                    issue=ISSUE_SOURCE_UNAVAILABLE,
                    risk="medium",
                    next_action="retry_or_check_source_health",
                    identity_verdict=identity or "source_limited",
                    support_verdict="",
                    evidence_coverage="none",
                    evidence_text="",
                    problem="Scholarly sources were unavailable, so this citing sentence cannot be judged yet.",
                    suggestion="Retry later or inspect source health; do not treat this as evidence the claim is false.",
                    rewritten=_unchanged(item.get("sentence", "")),
                )
            )
            continue
        canonical = _as_mapping(result.get("canonical_record"))
        fallback = bibliography[index] if isinstance(index, int) and 0 <= index < len(bibliography) else {}
        record = _record_from_canonical(canonical, fallback)
        evidence_text = str(record.abstract or "").strip()
        if not evidence_text:
            reviews.append(
                _review_item(
                    item,
                    issue=ISSUE_INSUFFICIENT_EVIDENCE,
                    risk="medium",
                    next_action="inspect_full_text_or_find_stronger_citation",
                    identity_verdict=identity or "verified",
                    support_verdict="insufficient_evidence",
                    evidence_coverage="metadata_only",
                    evidence_text="",
                    problem="Paper identity is available, but no abstract or excerpt was present to judge the citing sentence.",
                    suggestion="Provide an abstract or lawful excerpt before treating the sentence as supported.",
                    rewritten=_unchanged(item.get("sentence", "")),
                )
            )
            continue
        backend = support_backend or HeuristicSupportBackend()
        for claim_text in _claim_units(str(item.get("sentence") or "")):
            claim_item = dict(item)
            claim_item["sentence"] = claim_text
            support = assess_support(claim_text, record, backend=backend)
            issue, problem, suggestion, next_action, risk = _support_issue(claim_item, support, evidence_text)
            reviews.append(
                _review_item(
                    claim_item,
                    issue=issue,
                    risk=risk,
                    next_action=next_action,
                    identity_verdict=identity or "verified",
                    support_verdict=support.verdict.value,
                    evidence_coverage=str(support.evidence_scope or "abstract"),
                    evidence_text=str((support.evidence or {}).get("text") or evidence_text),
                    problem=problem,
                    suggestion=suggestion,
                    rewritten=_rewrite_hint(claim_text, issue, evidence_text),
                )
            )
    return reviews


def build_manuscript_summary(
    payload: Mapping[str, Any],
    linked: Mapping[str, Any],
    claim_reviews: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    audit = _as_mapping(payload.get("audit"))
    summary = _as_mapping(audit.get("summary"))
    incomplete = 0
    document = _as_mapping(payload.get("document"))
    dependencies = _as_mapping(document.get("dependencies"))
    if not dependencies.get("complete", True):
        incomplete += len(list(dependencies.get("missing") or []))
    incomplete += len(linked.get("unlinked_markers") or [])
    incomplete += sum(1 for item in claim_reviews if item.get("issue") != "supported")
    issue_counts: Dict[str, int] = {}
    category_counts = {
        "metadata": 0,
        "insufficient_evidence": 0,
        "contradiction": 0,
        "source_unavailable": 0,
    }
    for item in claim_reviews:
        issue = str(item.get("issue") or "other")
        issue_counts[issue] = issue_counts.get(issue, 0) + 1
        category = str(item.get("category") or ISSUE_CATEGORY.get(issue, "other"))
        if category in category_counts:
            category_counts[category] += 1
    top = [
        {
            "locator": item.get("locator", ""),
            "issue": item.get("issue", ""),
            "sentence": item.get("sentence", ""),
            "next_action": item.get("next_action", ""),
        }
        for item in claim_reviews[:5]
    ]
    return {
        "citation_count": int(summary.get("verified", 0) or 0)
        + int(summary.get("not_found", 0) or 0)
        + int(summary.get("metadata_mismatch", 0) or 0)
        + int(summary.get("ambiguous", 0) or 0),
        "in_text_count": int(linked.get("in_text_count") or 0),
        "linked_count": len(list(linked.get("body_links") or [])),
        "unlinked_count": len(list(linked.get("unlinked_markers") or [])),
        "incomplete_count": incomplete,
        "issue_counts": issue_counts,
        "category_counts": category_counts,
        "top_reviews": top,
    }


def render_document_audit_html(payload: Mapping[str, Any]) -> str:
    """Render a local HTML report from the same document-audit JSON model."""

    summary = _as_mapping(payload.get("manuscript_summary"))
    document = _as_mapping(payload.get("document"))
    reviews = list(payload.get("claim_reviews") or payload.get("review_queue") or [])
    path = html.escape(str(document.get("path") or ""))
    citation_count = int(summary.get("citation_count") or 0)
    in_text_count = int(summary.get("in_text_count") or 0)
    incomplete = int(summary.get("incomplete_count") or 0)
    categories = _as_mapping(summary.get("category_counts"))
    rows = []
    for item in reviews:
        sentence = html.escape(str(item.get("sentence") or item.get("locator") or ""))
        evidence = html.escape(str(item.get("evidence_text") or ""))
        problem = html.escape(str(item.get("problem") or item.get("issue") or ""))
        suggestion = html.escape(str(item.get("suggestion") or ""))
        rewritten = item.get("rewritten") if isinstance(item.get("rewritten"), Mapping) else {}
        before = html.escape(str(rewritten.get("before") or item.get("sentence") or ""))
        after = html.escape(str(rewritten.get("after") or ""))
        rows.append(
            "<article class=\"review\">"
            f"<h3>{html.escape(str(item.get('category') or item.get('issue') or 'review'))}</h3>"
            f"<p class=\"meta\">locator: {html.escape(str(item.get('locator') or ''))} · "
            f"next: {html.escape(str(item.get('next_action') or ''))}</p>"
            f"<p><strong>Citing sentence</strong> {sentence}</p>"
            f"<p><strong>Problem</strong> {problem}</p>"
            f"<p><strong>Evidence</strong> {evidence or 'None available in this audit.'}</p>"
            f"<p><strong>Suggestion</strong> {suggestion}</p>"
            f"<pre class=\"diff\">- {before}\n+ {after}</pre>"
            "</article>"
        )
    metadata_n = int(categories.get("metadata") or 0)
    evidence_n = int(categories.get("insufficient_evidence") or 0)
    contradiction_n = int(categories.get("contradiction") or 0)
    source_n = int(categories.get("source_unavailable") or 0)
    top = list(summary.get("top_reviews") or [])
    top_items = "".join(
        f"<li>{html.escape(str(item.get('issue') or ''))}: {html.escape(str(item.get('sentence') or item.get('locator') or ''))}</li>"
        for item in top
    ) or "<li>No claim-level issues queued.</li>"
    lang = _html_lang(payload, reviews)
    return (
        f"<!DOCTYPE html>\n<html lang=\"{html.escape(lang)}\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<title>CiteGuard manuscript audit</title>\n<style>\n"
        "body{font-family:ui-sans-serif,system-ui,sans-serif;line-height:1.45;"
        "margin:1.5rem;max-width:52rem;color:#111}"
        "h1,h2,h3{line-height:1.2} .summary,.priority,.review{border:1px solid #ddd;"
        "padding:1rem;margin:1rem 0} pre.diff{white-space:pre-wrap;background:#f6f6f6;padding:.75rem}"
        ".meta{color:#555;font-size:.9rem}\n</style>\n</head>\n<body>\n"
        "<h1>CiteGuard manuscript audit</h1>\n"
        f"<p class=\"meta\">Source: {path}</p>\n"
        "<section class=\"summary\">\n"
        f"<p>Audited <strong>{citation_count}</strong> bibliography entries and "
        f"<strong>{in_text_count}</strong> in-text citations. "
        f"<strong>{incomplete}</strong> items still need review.</p>\n"
        "<ul>"
        f"<li>Metadata / identity: {metadata_n}</li>"
        f"<li>Insufficient evidence: {evidence_n}</li>"
        f"<li>Contradiction: {contradiction_n}</li>"
        f"<li>Source unavailable: {source_n}</li>"
        "</ul>\n"
        "</section>\n"
        "<section class=\"priority\">\n<h2>Check these first</h2>\n<ol>"
        f"{top_items}</ol>\n</section>\n"
        "<section>\n<h2>Claim reviews</h2>\n"
        f"{''.join(rows) or '<p>No in-text citations were linked in this file.</p>'}\n"
        "</section>\n</body>\n</html>\n"
    )


def _support_issue(
    item: Mapping[str, Any],
    support: Any,
    evidence_text: str,
) -> tuple:
    verdict = support.verdict
    sentence = str(item.get("sentence") or "")
    if verdict == SupportVerdict.CONTRADICTED:
        return (
            ISSUE_CONTRADICTION,
            "The available evidence contradicts the citing sentence.",
            "Rewrite the sentence so it matches the paper, or replace the citation.",
            "rewrite_or_replace_evidence",
            "high",
        )
    if verdict == SupportVerdict.SUPPORTED:
        return (
            "supported",
            "Current abstract-level evidence is consistent with the citing sentence.",
            "Keep the sentence, or optionally add the specific dataset/setting named in the paper.",
            "keep_claim",
            "low",
        )
    if _looks_like_scope_overclaim(sentence, evidence_text):
        return (
            ISSUE_SCOPE,
            "The citing sentence is broader than the reported setting in the available evidence.",
            "Limit the claim to the datasets, languages, or conditions the paper actually evaluated.",
            "tighten_claim_or_inspect_full_text",
            "high",
        )
    return (
        ISSUE_INSUFFICIENT_EVIDENCE,
        "Available evidence does not establish the citing sentence at its stated strength.",
        "Qualify the sentence or inspect lawful full text before treating it as supported.",
        "tighten_claim_or_inspect_full_text",
        "medium",
    )


def _looks_like_scope_overclaim(sentence: str, evidence_text: str) -> bool:
    lowered = sentence.lower()
    if not any(marker in lowered or marker in sentence for marker in _OVERCLAIM_MARKERS):
        return False
    evidence = evidence_text.lower()
    return any(token in evidence for token in ("two", "three", "dataset", "task", "limited", "两个", "三个"))


def _rewrite_hint(sentence: str, issue: str, evidence_text: str) -> Dict[str, str]:
    if issue == ISSUE_SCOPE:
        return {
            "before": sentence,
            "after": "Qualify the claim to the datasets or conditions actually reported in the cited paper.",
        }
    if issue == ISSUE_CONTRADICTION:
        return {
            "before": sentence,
            "after": "Rewrite the sentence to match the paper, or cite a different source.",
        }
    if issue in {ISSUE_INSUFFICIENT_EVIDENCE, ISSUE_IDENTITY, ISSUE_UNLINKED, ISSUE_SOURCE_UNAVAILABLE}:
        return {"before": sentence, "after": sentence}
    return {"before": sentence, "after": sentence}


def _unchanged(sentence: str) -> Dict[str, str]:
    return {"before": sentence, "after": sentence}


def _html_lang(payload: Mapping[str, Any], reviews: Sequence[Mapping[str, Any]]) -> str:
    parts = [str(_as_mapping(payload.get("document")).get("path") or "")]
    parts.extend(str(item.get("sentence") or "") for item in reviews)
    blob = "\n".join(parts)
    if re.search(r"[\u4e00-\u9fff]", blob):
        return "zh"
    return "en"


def _claim_units(sentence: str) -> List[str]:
    text = str(sentence or "").strip()
    if not text:
        return [""]
    parts = [part.strip() for part in re.split(r"[;；]", text) if part.strip()]
    if len(parts) > 1 and all(len(part) >= 12 for part in parts):
        return parts
    return [text]


def _review_item(
    marker: Mapping[str, Any],
    *,
    issue: str,
    risk: str,
    next_action: str,
    identity_verdict: str,
    support_verdict: str,
    evidence_coverage: str,
    evidence_text: str,
    problem: str,
    suggestion: str,
    rewritten: Mapping[str, str],
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    item = {
        "issue": issue,
        "risk": risk,
        "next_action": next_action,
        "locator": marker.get("locator", ""),
        "sentence": marker.get("sentence", ""),
        "paragraph": marker.get("paragraph", ""),
        "attachment": marker.get("attachment", "sentence"),
        "attachment_candidates": list(marker.get("attachment_candidates") or []),
        "cite_key": marker.get("cite_key", ""),
        "raw_marker": marker.get("raw_marker", ""),
        "bibliography_index": marker.get("bibliography_index"),
        "identity_verdict": identity_verdict,
        "support_verdict": support_verdict,
        "evidence_coverage": evidence_coverage,
        "evidence_text": evidence_text,
        "problem": problem,
        "suggestion": suggestion,
        "rewritten": dict(rewritten),
        "category": ISSUE_CATEGORY.get(issue, "other"),
        "requires_user_confirmation": True,
        "automatic_apply_allowed": False,
    }
    if extra:
        item.update(dict(extra))
    return item


def _claim_review_queue_items(reviews: Sequence[Mapping[str, Any]], *, start_rank: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    rank = start_rank
    for review in reviews:
        if review.get("issue") == "supported" or review.get("risk") == "low":
            continue
        items.append(
            {
                "rank": rank,
                "index": review.get("bibliography_index"),
                "risk": review.get("risk"),
                "risk_score": 0.85 if review.get("risk") == "high" else 0.55,
                "next_action": review.get("next_action"),
                "locator": review.get("locator", ""),
                "position": {"path": "", "line_start": None, "line_end": None},
                "suggested_fix": {
                    "kind": "claim_rewrite",
                    "before": (review.get("rewritten") or {}).get("before", ""),
                    "after": (review.get("rewritten") or {}).get("after", ""),
                    "note": review.get("suggestion", ""),
                },
                "requires_user_confirmation": True,
                "automatic_apply_allowed": False,
                "issue": review.get("issue"),
                "sentence": review.get("sentence", ""),
                "evidence_text": review.get("evidence_text", ""),
                "problem": review.get("problem", ""),
                "suggestion": review.get("suggestion", ""),
                "rewritten": dict(review.get("rewritten") or {}),
            }
        )
        rank += 1
    return items


def _record_from_canonical(canonical: Mapping[str, Any], fallback: Mapping[str, Any]) -> CitationRecord:
    data = dict(fallback)
    data.update({key: value for key, value in canonical.items() if value not in (None, "", [], {})})
    authors = data.get("authors") or []
    if not isinstance(authors, list):
        authors = []
    return CitationRecord(
        citation_id=str(data.get("citation_id") or data.get("source_id") or "document-citation"),
        title=str(data.get("title") or ""),
        authors=[str(item) for item in authors],
        year=data.get("year") if isinstance(data.get("year"), int) else None,
        venue=str(data.get("venue") or ""),
        abstract=str(data.get("abstract") or ""),
        doi=str(data.get("doi") or ""),
        arxiv_id=str(data.get("arxiv_id") or ""),
        url=str(data.get("url") or ""),
        source=str(data.get("source") or "document_audit"),
        metadata=dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), Mapping) else {},
    )
