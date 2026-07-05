"""Shared machine-readable error payloads."""

from __future__ import annotations

from typing import Dict, Optional, Set


ERROR_SCHEMA_VERSION = 1

ERROR_CODE_RECOVERY: Dict[str, str] = {
    "missing_citation_input": "Ask for a DOI, arXiv id, title, or pasted reference.",
    "missing_claim": "Ask for the sentence that the citation is supposed to support.",
    "invalid_input": "Fix the field type, object shape, or required item.",
    "invalid_json": "Repair the JSON or JSONL input.",
    "argument_parse_error": "Show command help or fix the CLI invocation.",
    "file_error": "Check the path and permissions.",
    "source_unavailable": "Retry later, inspect source health, and avoid treating not_found as fabricated.",
    "model_unavailable": "Install the models extra or treat support output as heuristic or weak.",
    "ambiguous_citation": "Ask for a DOI, arXiv id, or more metadata.",
    "timeout": "Retry, raise the timeout, or continue with reduced confidence.",
    "unsupported_command": "Upgrade CiteGuard or fix the invocation.",
}

ERROR_CODE_NEXT_ACTION: Dict[str, str] = {
    "missing_citation_input": "provide_missing_input",
    "missing_claim": "provide_missing_input",
    "invalid_input": "repair_input",
    "invalid_json": "repair_input",
    "argument_parse_error": "repair_input",
    "file_error": "repair_input",
    "source_unavailable": "retry_or_check_source_health",
    "model_unavailable": "install_or_configure_dependency",
    "ambiguous_citation": "disambiguate_identifier",
    "timeout": "retry_or_check_source_health",
    "unsupported_command": "repair_input",
}

STABLE_ERROR_CODES: Set[str] = set(ERROR_CODE_RECOVERY)


def is_stable_error_code(code: str) -> bool:
    """Return whether `code` is part of CiteGuard's documented error contract."""

    return code in STABLE_ERROR_CODES


def error_payload(
    code: str,
    message: str,
    details: Optional[dict] = None,
    exit_code: int = 2,
) -> dict:
    """Return a stable JSON-serializable error object for CLIs and tools."""

    return {
        "ok": False,
        "schema_version": ERROR_SCHEMA_VERSION,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
            "recovery": ERROR_CODE_RECOVERY.get(code, ""),
            "next_action": ERROR_CODE_NEXT_ACTION.get(code, ""),
        },
        "exit_code": exit_code,
    }


__all__ = [
    "ERROR_SCHEMA_VERSION",
    "ERROR_CODE_RECOVERY",
    "ERROR_CODE_NEXT_ACTION",
    "STABLE_ERROR_CODES",
    "error_payload",
    "is_stable_error_code",
]
