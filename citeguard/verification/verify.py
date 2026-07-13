"""Verify a single citation: existence + metadata, with a suggested fix."""

from __future__ import annotations

from typing import Any, List, Optional

from citeguard.citation import CitationFormatter, author_coverage, sequence_similarity, year_matches
from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients.base import MetadataSource
from citeguard.retrieval.scholarly_clients.utils import normalize_arxiv_id, normalize_doi

from .models import FieldDiff, VerificationResult, Verdict, classify_source_failure_mode
from .resolve import STRONG_MATCH, resolve_citation

TITLE_MATCH = 0.90
AUTHOR_MATCH = 0.50
VENUE_MATCH = 0.60


def _field_diffs(candidate: CitationRecord, canonical: CitationRecord) -> List[FieldDiff]:
    """Compare only the fields the caller actually provided."""

    diffs: List[FieldDiff] = []
    if candidate.metadata.get("title_explicit"):
        matches = sequence_similarity(candidate.title, canonical.title) >= TITLE_MATCH
        diffs.append(FieldDiff("title", candidate.title, canonical.title, matches))
    if candidate.authors:
        matches = author_coverage(candidate.authors, canonical.authors) >= AUTHOR_MATCH
        diffs.append(FieldDiff("authors", candidate.authors, canonical.authors, matches))
    if candidate.year is not None:
        diffs.append(
            FieldDiff("year", candidate.year, canonical.year, year_matches(candidate.year, canonical.year))
        )
    if candidate.venue:
        matches = sequence_similarity(candidate.venue, canonical.venue) >= VENUE_MATCH
        diffs.append(FieldDiff("venue", candidate.venue, canonical.venue, matches))
    if candidate.doi:
        matches = normalize_doi(candidate.doi) == normalize_doi(canonical.doi)
        diffs.append(FieldDiff("doi", candidate.doi, canonical.doi, matches))
    if candidate.arxiv_id:
        matches = normalize_arxiv_id(candidate.arxiv_id) == normalize_arxiv_id(canonical.arxiv_id)
        diffs.append(FieldDiff("arxiv_id", candidate.arxiv_id, canonical.arxiv_id, matches))
    return diffs


def verify_citation(
    candidate: CitationRecord,
    source: MetadataSource,
    formatter: Optional[CitationFormatter] = None,
    doi_registry: Optional[Any] = None,
) -> VerificationResult:
    formatter = formatter or CitationFormatter()
    outcome = resolve_citation(candidate, source)
    checked, responded, failed = outcome.sources_checked, outcome.sources_responded, outcome.sources_failed
    failure_details = outcome.source_failure_details
    failure_mode = classify_source_failure_mode(checked, failed, responded)
    identifier_info = outcome.identifier_lookup or {}
    identifier_status = str(identifier_info.get("status", ""))
    miss_note = (
        f" Note: the provided {identifier_info.get('kind', 'identifier')} was not found at "
        f"{identifier_info.get('source', 'its home source')}."
        if identifier_status == "miss"
        else ""
    )

    if outcome.best is None or outcome.score < STRONG_MATCH:
        confidence = round(1.0 - outcome.score, 4)
        outage_limited = failure_mode != "none"
        outage = ""
        if failure_mode == "all_sources_failed":
            confidence = min(confidence, 0.35)
            outage = (
                f" All checked sources failed ({', '.join(failed)}); this verification is inconclusive, "
                "not evidence of fabrication."
            )
        elif failure_mode == "partial_outage":
            confidence = min(confidence, 0.65)
            outage = f" Source failures limited this check: {', '.join(failed)}."
        elif not responded:
            outage = " No source returned a matching record."
        doi_registration = None
        registry_note = ""
        if doi_registry is not None and candidate.doi:
            doi_registration = doi_registry.check(candidate.doi)
            if doi_registration.get("registered") is True:
                registry_note = (
                    " The DOI is registered in the global DOI system (possibly with a registrar whose"
                    " metadata is not in open sources, e.g. China DOI); treat this as unverifiable"
                    " metadata, not a fabricated citation."
                )
            elif doi_registration.get("registered") is False:
                registry_note = (
                    " The DOI was not found in the global DOI registry either, which lowers confidence"
                    " further but is still not proof of fabrication."
                )
        return VerificationResult(
            verdict=Verdict.NOT_FOUND,
            confidence=round(confidence, 4),
            input_citation=candidate,
            canonical_record=None,
            field_diffs=[],
            suggested_citation="",
            explanation=f"Could not be verified in {', '.join(checked)}.{outage}{registry_note}",
            sources_checked=checked,
            sources_responded=responded,
            sources_failed=failed,
            source_failure_details=failure_details,
            source_failure_mode=failure_mode,
            outage_limited=outage_limited,
            alternatives=outcome.alternatives,
            doi_registration=doi_registration,
            identifier_lookup=outcome.identifier_lookup,
        )

    if identifier_status == "failed" and outcome.best is not None and outcome.score < 1.0:
        return VerificationResult(
            verdict=Verdict.AMBIGUOUS,
            confidence=min(_confidence_with_source_failures(outcome.score, failure_mode), 0.6),
            input_citation=candidate,
            canonical_record=outcome.best,
            field_diffs=[],
            suggested_citation="",
            explanation=(
                f"The authoritative {identifier_info.get('kind', 'identifier')} lookup failed on "
                f"{identifier_info.get('source', 'its home source')}; a title-based match exists but cannot "
                "be confirmed against the provided identifier. Retry or check source health - this is not "
                "evidence of fabrication."
            ),
            sources_checked=checked,
            sources_responded=responded,
            sources_failed=failed,
            source_failure_details=failure_details,
            source_failure_mode=failure_mode,
            outage_limited=True,
            alternatives=outcome.alternatives,
            identifier_lookup=outcome.identifier_lookup,
        )

    if outcome.ambiguous:
        return VerificationResult(
            verdict=Verdict.AMBIGUOUS,
            confidence=_confidence_with_source_failures(outcome.score, failure_mode),
            input_citation=candidate,
            canonical_record=outcome.best,
            field_diffs=[],
            suggested_citation="",
            explanation=(
                "Multiple plausible matches; cannot disambiguate without a DOI or arXiv id."
                + _source_failure_note(failure_mode, failed)
                + miss_note
            ),
            sources_checked=checked,
            sources_responded=responded,
            sources_failed=failed,
            source_failure_details=failure_details,
            source_failure_mode=failure_mode,
            outage_limited=False,
            alternatives=outcome.alternatives,
            identifier_lookup=outcome.identifier_lookup,
        )

    diffs = _field_diffs(candidate, outcome.best)
    mismatched = [diff.field for diff in diffs if not diff.matches]
    if mismatched:
        return VerificationResult(
            verdict=Verdict.METADATA_MISMATCH,
            confidence=_confidence_with_source_failures(outcome.score, failure_mode),
            input_citation=candidate,
            canonical_record=outcome.best,
            field_diffs=diffs,
            suggested_citation=formatter.format_reference(outcome.best),
            explanation=(
                f"The paper exists, but these fields disagree with the canonical record: {', '.join(mismatched)}."
                + _source_failure_note(failure_mode, failed)
                + miss_note
            ),
            sources_checked=checked,
            sources_responded=responded,
            sources_failed=failed,
            source_failure_details=failure_details,
            source_failure_mode=failure_mode,
            outage_limited=False,
            identifier_lookup=outcome.identifier_lookup,
        )

    return VerificationResult(
        verdict=Verdict.VERIFIED,
        confidence=_confidence_with_source_failures(outcome.score, failure_mode),
        input_citation=candidate,
        canonical_record=outcome.best,
        field_diffs=diffs,
        suggested_citation="",
        explanation=(
            "Citation resolves to a real record and the provided metadata matches."
            + _source_failure_note(failure_mode, failed)
            + miss_note
        ),
        sources_checked=checked,
        sources_responded=responded,
        sources_failed=failed,
        source_failure_details=failure_details,
        source_failure_mode=failure_mode,
        outage_limited=False,
        identifier_lookup=outcome.identifier_lookup,
    )


def _confidence_with_source_failures(score: float, failure_mode: str) -> float:
    if failure_mode == "all_sources_failed":
        return round(min(score, 0.35), 4)
    if failure_mode == "partial_outage":
        return round(min(score, 0.85), 4)
    return round(score, 4)


def _source_failure_note(failure_mode: str, failed: List[str]) -> str:
    if failure_mode != "partial_outage":
        return ""
    return f" Confidence is reduced because these sources failed: {', '.join(failed)}."
