"""Claim-free citation verification (existence + metadata)."""

from .audit import audit_citations
from .cache import CachingMetadataSource
from .models import AuditReport, FieldDiff, VerificationResult, Verdict
from .parse import parse_citation
from .resolve import ResolveOutcome, resolve_citation, source_names, verification_match_score
from .support import (
    DEFAULT_SUPPORT_POLICY,
    SupportDecisionPolicy,
    SupportResult,
    SupportVerdict,
    assess_support,
    check_claim_support,
)
from .verify import verify_citation

__all__ = [
    "AuditReport",
    "CachingMetadataSource",
    "DEFAULT_SUPPORT_POLICY",
    "FieldDiff",
    "ResolveOutcome",
    "SupportDecisionPolicy",
    "SupportResult",
    "SupportVerdict",
    "VerificationResult",
    "Verdict",
    "assess_support",
    "audit_citations",
    "check_claim_support",
    "parse_citation",
    "resolve_citation",
    "source_names",
    "verification_match_score",
    "verify_citation",
]
