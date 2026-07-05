"""Public CiteGuard package facade."""

from citeguard.errors import ERROR_CODE_NEXT_ACTION, ERROR_SCHEMA_VERSION, error_payload
from citeguard.version import __version__

_VERIFICATION_EXPORTS = {
    "AuditReport",
    "CitationRecord",
    "ClaimSupportAuditItem",
    "ClaimSupportRequest",
    "ClaimSupportSetResult",
    "CounterEvidenceSearchReport",
    "FieldDiff",
    "NEXT_ACTION_DESCRIPTIONS",
    "STABLE_NEXT_ACTIONS",
    "SupportAuditReport",
    "SupportAssessment",
    "SupportBackend",
    "SupportResult",
    "SupportVerdict",
    "VerificationResult",
    "Verdict",
    "audit_claim_support",
    "audit_citations",
    "available_sources",
    "check_claim_support",
    "check_claim_support_set",
    "enrich_support_payload_with_counterevidence",
    "infer_evidence_scope",
    "parse_citation",
    "search_counterevidence_candidates",
    "source_failure_recovery_code",
    "stable_next_action",
    "verification_next_action",
    "verification_recovery_code",
    "verify_citation",
}


def __getattr__(name: str):
    if name in _VERIFICATION_EXPORTS:
        from citeguard import verification

        return getattr(verification, name)
    raise AttributeError(f"module 'citeguard' has no attribute {name!r}")

__all__ = [
    "AuditReport",
    "CitationRecord",
    "ClaimSupportAuditItem",
    "ClaimSupportRequest",
    "ClaimSupportSetResult",
    "CounterEvidenceSearchReport",
    "FieldDiff",
    "NEXT_ACTION_DESCRIPTIONS",
    "STABLE_NEXT_ACTIONS",
    "SupportAuditReport",
    "SupportAssessment",
    "SupportBackend",
    "SupportResult",
    "SupportVerdict",
    "VerificationResult",
    "Verdict",
    "ERROR_SCHEMA_VERSION",
    "ERROR_CODE_NEXT_ACTION",
    "__version__",
    "error_payload",
    "audit_claim_support",
    "audit_citations",
    "available_sources",
    "check_claim_support",
    "check_claim_support_set",
    "enrich_support_payload_with_counterevidence",
    "infer_evidence_scope",
    "parse_citation",
    "search_counterevidence_candidates",
    "source_failure_recovery_code",
    "stable_next_action",
    "verification_next_action",
    "verification_recovery_code",
    "verify_citation",
]
