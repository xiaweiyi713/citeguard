"""Versioned agent-facing output contracts distributed with CiteGuard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


CONTRACT_VERSION = "v1"
CONTRACT_SCHEMA_VERSION = 1
CONTRACT_SCHEMA_FILENAME = "agent-output.schema.json"
SKILL_TRIGGER_PREDICTION_SCHEMA_FILENAME = "skill-trigger-prediction.schema.json"

# These values are frozen for the v1 agent-facing CLI and MCP contract. Add a
# new contract version before changing any of these public vocabularies.
CITATION_VERDICTS = (
    "verified",
    "metadata_mismatch",
    "not_found",
    "ambiguous",
)
SUPPORT_VERDICTS = (
    "supported",
    "weakly_supported",
    "insufficient_evidence",
    "contradicted",
)
RISK_LEVELS = ("low", "medium", "high")
EVIDENCE_SCOPES = (
    "none",
    "title",
    "metadata",
    "metadata_snippet",
    "abstract",
    "full_text",
    "mixed",
    "mixed_with_full_text",
    "unknown",
)


def contract_schema_path() -> Path:
    """Return the installed v1 JSON Schema path."""

    return Path(__file__).resolve().parent / "v1" / CONTRACT_SCHEMA_FILENAME


def load_contract_schema() -> dict[str, Any]:
    """Load the v1 JSON Schema bundled with the installed package."""

    with contract_schema_path().open(encoding="utf-8") as handle:
        return json.load(handle)


def skill_trigger_prediction_schema_path() -> Path:
    """Return the installed v1 Skill-trigger prediction artifact JSON Schema path."""

    return Path(__file__).resolve().parent / "v1" / SKILL_TRIGGER_PREDICTION_SCHEMA_FILENAME


def load_skill_trigger_prediction_schema() -> dict[str, Any]:
    """Load the v1 Skill-trigger prediction artifact schema shipped with CiteGuard."""

    with skill_trigger_prediction_schema_path().open(encoding="utf-8") as handle:
        return json.load(handle)


def with_contract_version(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Add the stable v1 marker to a public CLI or MCP response.

    The marker belongs at the outer response boundary. Nested batch rows inherit
    the enclosing contract and deliberately remain compact.
    """

    result = dict(payload)
    existing = result.get("contract_version")
    if existing not in (None, CONTRACT_VERSION):
        raise ValueError(
            f"cannot relabel CiteGuard payload contract {existing!r} as {CONTRACT_VERSION!r}"
        )
    result["contract_version"] = CONTRACT_VERSION
    return result


__all__ = [
    "CITATION_VERDICTS",
    "CONTRACT_SCHEMA_FILENAME",
    "CONTRACT_SCHEMA_VERSION",
    "CONTRACT_VERSION",
    "EVIDENCE_SCOPES",
    "RISK_LEVELS",
    "SKILL_TRIGGER_PREDICTION_SCHEMA_FILENAME",
    "SUPPORT_VERDICTS",
    "contract_schema_path",
    "load_contract_schema",
    "load_skill_trigger_prediction_schema",
    "skill_trigger_prediction_schema_path",
    "with_contract_version",
]
