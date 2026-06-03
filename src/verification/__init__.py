"""Claim-free citation verification (existence + metadata)."""

from .audit import audit_citations
from .cache import CachingMetadataSource
from .models import AuditReport, FieldDiff, VerificationResult, Verdict
from .parse import parse_citation
from .resolve import ResolveOutcome, resolve_citation, source_names, verification_match_score
from .verify import verify_citation

__all__ = [
    "AuditReport",
    "CachingMetadataSource",
    "FieldDiff",
    "ResolveOutcome",
    "VerificationResult",
    "Verdict",
    "audit_citations",
    "parse_citation",
    "resolve_citation",
    "source_names",
    "verification_match_score",
    "verify_citation",
]
