"""Public citation verification API."""

from citeguard.graph import CitationRecord
from citeguard.verifiers import SupportAssessment, SupportBackend

from .models import (
    AuditReport,
    FieldDiff,
    NEXT_ACTION_DESCRIPTIONS,
    STABLE_NEXT_ACTIONS,
    VerificationResult,
    Verdict,
    available_sources,
    source_failure_recovery_code,
    stable_next_action,
    verification_next_action,
    verification_recovery_code,
)
from .audit import audit_citations
from .cache import CACHE_SCHEMA_VERSION, CachingMetadataSource, clear_cache, export_cache_records, inspect_cache
from .extract import extract_citation_candidates, load_citation_candidates
from .parse import parse_citation
from .resolve import ResolveOutcome, resolve_citation, source_names, verification_match_score
from .support import (
    DEFAULT_SUPPORT_POLICY,
    ClaimSupportAuditItem,
    ClaimSupportRequest,
    ClaimSupportSetResult,
    CounterEvidenceSearchReport,
    SupportDecisionPolicy,
    SupportAuditReport,
    SupportResult,
    SupportVerdict,
    assess_support,
    audit_claim_support,
    check_claim_support,
    check_claim_support_set,
    enrich_support_payload_with_counterevidence,
    infer_evidence_scope,
    search_counterevidence_candidates,
)
from .verify import verify_citation

__all__ = [
    "AuditReport",
    "CACHE_SCHEMA_VERSION",
    "CachingMetadataSource",
    "CitationRecord",
    "ClaimSupportRequest",
    "ClaimSupportAuditItem",
    "ClaimSupportSetResult",
    "CounterEvidenceSearchReport",
    "DEFAULT_SUPPORT_POLICY",
    "FieldDiff",
    "NEXT_ACTION_DESCRIPTIONS",
    "ResolveOutcome",
    "STABLE_NEXT_ACTIONS",
    "SupportDecisionPolicy",
    "SupportAuditReport",
    "SupportAssessment",
    "SupportBackend",
    "SupportResult",
    "SupportVerdict",
    "VerificationResult",
    "Verdict",
    "assess_support",
    "audit_claim_support",
    "audit_citations",
    "available_sources",
    "check_claim_support",
    "check_claim_support_set",
    "enrich_support_payload_with_counterevidence",
    "clear_cache",
    "extract_citation_candidates",
    "export_cache_records",
    "inspect_cache",
    "infer_evidence_scope",
    "load_citation_candidates",
    "parse_citation",
    "resolve_citation",
    "search_counterevidence_candidates",
    "source_failure_recovery_code",
    "source_names",
    "stable_next_action",
    "verification_match_score",
    "verification_next_action",
    "verification_recovery_code",
    "verify_citation",
]
