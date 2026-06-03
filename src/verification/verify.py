"""Verify a single citation: existence + metadata, with a suggested fix."""

from __future__ import annotations

from typing import List, Optional

from src.citation import CitationFormatter, author_coverage, sequence_similarity, year_matches
from src.graph import CitationRecord
from src.retrieval.scholarly_clients.base import MetadataSource
from src.retrieval.scholarly_clients.utils import normalize_doi

from .models import FieldDiff, VerificationResult, Verdict
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
    return diffs


def verify_citation(
    candidate: CitationRecord,
    source: MetadataSource,
    formatter: Optional[CitationFormatter] = None,
) -> VerificationResult:
    formatter = formatter or CitationFormatter()
    outcome = resolve_citation(candidate, source)
    checked, responded = outcome.sources_checked, outcome.sources_responded

    if outcome.best is None or outcome.score < STRONG_MATCH:
        outage = "" if responded else " No source returned any result, which may also indicate a temporary source outage."
        return VerificationResult(
            verdict=Verdict.NOT_FOUND,
            confidence=round(1.0 - outcome.score, 4),
            input_citation=candidate,
            canonical_record=None,
            field_diffs=[],
            suggested_citation="",
            explanation=f"Could not be verified in {', '.join(checked)}.{outage}",
            sources_checked=checked,
            sources_responded=responded,
            alternatives=outcome.alternatives,
        )

    if outcome.ambiguous:
        return VerificationResult(
            verdict=Verdict.AMBIGUOUS,
            confidence=round(outcome.score, 4),
            input_citation=candidate,
            canonical_record=outcome.best,
            field_diffs=[],
            suggested_citation="",
            explanation="Multiple plausible matches; cannot disambiguate without a DOI or arXiv id.",
            sources_checked=checked,
            sources_responded=responded,
            alternatives=outcome.alternatives,
        )

    diffs = _field_diffs(candidate, outcome.best)
    mismatched = [diff.field for diff in diffs if not diff.matches]
    if mismatched:
        return VerificationResult(
            verdict=Verdict.METADATA_MISMATCH,
            confidence=round(outcome.score, 4),
            input_citation=candidate,
            canonical_record=outcome.best,
            field_diffs=diffs,
            suggested_citation=formatter.format_reference(outcome.best),
            explanation=f"The paper exists, but these fields disagree with the canonical record: {', '.join(mismatched)}.",
            sources_checked=checked,
            sources_responded=responded,
        )

    return VerificationResult(
        verdict=Verdict.VERIFIED,
        confidence=round(outcome.score, 4),
        input_citation=candidate,
        canonical_record=outcome.best,
        field_diffs=diffs,
        suggested_citation="",
        explanation="Citation resolves to a real record and the provided metadata matches.",
        sources_checked=checked,
        sources_responded=responded,
    )
