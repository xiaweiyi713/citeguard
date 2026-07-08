"""Shared machine-readable error payloads."""

from __future__ import annotations

import re
from typing import Dict, Mapping, Optional, Set


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

ERROR_CODE_RETRYABLE: Dict[str, bool] = {
    "missing_citation_input": False,
    "missing_claim": False,
    "invalid_input": False,
    "invalid_json": False,
    "argument_parse_error": False,
    "file_error": False,
    "source_unavailable": True,
    "model_unavailable": False,
    "ambiguous_citation": False,
    "timeout": True,
    "unsupported_command": False,
}

ERROR_CODE_CATEGORY: Dict[str, str] = {
    "missing_citation_input": "missing_input",
    "missing_claim": "missing_input",
    "invalid_input": "input_repair",
    "invalid_json": "input_repair",
    "argument_parse_error": "input_repair",
    "file_error": "input_repair",
    "source_unavailable": "source_limited",
    "model_unavailable": "dependency_limited",
    "ambiguous_citation": "disambiguation",
    "timeout": "source_limited",
    "unsupported_command": "input_repair",
}

STABLE_ERROR_CODES: Set[str] = set(ERROR_CODE_RECOVERY)


def is_stable_error_code(code: str) -> bool:
    """Return whether `code` is part of CiteGuard's documented error contract."""

    return code in STABLE_ERROR_CODES


def error_code_registry() -> dict:
    """Return the stable error-code registry as a JSON-serializable contract."""

    return {
        "schema_version": ERROR_SCHEMA_VERSION,
        "codes": {
            code: {
                "recovery": ERROR_CODE_RECOVERY[code],
                "next_action": ERROR_CODE_NEXT_ACTION[code],
                "retryable": ERROR_CODE_RETRYABLE[code],
                "category": ERROR_CODE_CATEGORY[code],
            }
            for code in sorted(STABLE_ERROR_CODES)
        },
    }


def runtime_config_error_details(
    message: str,
    base: Optional[dict] = None,
    env: Optional[Mapping[str, str]] = None,
) -> dict:
    """Extract stable details from expected runtime configuration errors."""

    details = dict(base or {})
    env_match = re.search(r"\b(CITEGUARD_[A-Z0-9_]+)\b", message)
    if env_match:
        field = env_match.group(1)
        details["field"] = field
        details["source"] = "environment"
        if env is not None and field in env:
            details["received"] = env[field]
    if message.startswith("Unknown CITEGUARD_SOURCES value(s):"):
        invalid_part = message.split(":", 1)[1].split(".", 1)[0]
        invalid_values = [value.strip() for value in invalid_part.split(",") if value.strip()]
        if invalid_values:
            details["invalid_values"] = invalid_values
    valid_match = re.search(r"Valid values:\s*(.+?)\.$", message)
    if valid_match:
        details["valid_values"] = [value.strip() for value in valid_match.group(1).split(",") if value.strip()]
    expected = _runtime_config_expected(message)
    if expected:
        details["expected"] = expected
    return details


def _runtime_config_expected(message: str) -> str:
    if "must be a positive integer" in message:
        return "positive integer"
    if "must be a non-negative integer" in message:
        return "non-negative integer"
    if "must be a non-negative number" in message:
        return "non-negative number"
    if message.startswith("Unknown CITEGUARD_SOURCES value(s):") or message.startswith(
        "CITEGUARD_SOURCES did not contain any valid source names."
    ):
        return "comma-separated source names from valid_values"
    return ""


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
            "retryable": ERROR_CODE_RETRYABLE.get(code, False),
            "category": ERROR_CODE_CATEGORY.get(code, ""),
        },
        "exit_code": exit_code,
    }


__all__ = [
    "ERROR_SCHEMA_VERSION",
    "ERROR_CODE_RECOVERY",
    "ERROR_CODE_NEXT_ACTION",
    "ERROR_CODE_RETRYABLE",
    "ERROR_CODE_CATEGORY",
    "STABLE_ERROR_CODES",
    "error_code_registry",
    "error_payload",
    "is_stable_error_code",
    "runtime_config_error_details",
]
