#!/usr/bin/env python3
"""Smoke-test the CiteGuard MCP stdio server with an offline fixture."""

from __future__ import annotations

import argparse
import asyncio
import errno
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from _bootstrap import ensure_project_root

ensure_project_root()

from citeguard.errors import ERROR_CODE_CATEGORY, ERROR_CODE_RETRYABLE
from citeguard.runtime import SOURCE_HEALTH_SCHEMA_VERSION
from citeguard.verification import CACHE_SCHEMA_VERSION, REVIEW_ACTION_QUEUE_KEYS, STABLE_NEXT_ACTIONS


FIXTURE_RECORDS = [
    {
        "citation_id": "fixture-attention",
        "title": "Attention Is All You Need",
        "authors": ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
        "year": 2017,
        "venue": "NeurIPS",
        "doi": "",
        "arxiv_id": "1706.03762",
        "source": "fixture",
        "abstract": "The Transformer is a model architecture relying entirely on attention mechanisms.",
    },
    {
        "citation_id": "fixture-metadata-audit",
        "title": "Citation Auditing with Metadata Checks",
        "authors": ["Cite Guard"],
        "year": 2026,
        "venue": "CiteGuard Fixtures",
        "doi": "",
        "arxiv_id": "",
        "source": "fixture",
        "abstract": "Metadata checks help citation auditing workflows.",
    },
    {
        "citation_id": "fixture-counterevidence",
        "title": "Method M Does Not Improve Task T",
        "authors": ["A. Skeptic"],
        "year": 2024,
        "venue": "CiteGuard Fixtures",
        "doi": "",
        "arxiv_id": "",
        "source": "fixture",
        "abstract": "We show method M does not improve task T accuracy.",
    },
    {
        "citation_id": "fixture-source-outage-safety",
        "title": "Source Outages Are Not Fabrication Evidence",
        "authors": ["A. Auditor"],
        "year": 2026,
        "venue": "CiteGuard Fixtures",
        "doi": "",
        "arxiv_id": "",
        "source": "fixture",
        "abstract": (
            "Source outages and not_found results lower confidence and are not evidence "
            "that a citation is fabricated."
        ),
    },
    {
        "citation_id": "fixture-zh-source-outage-safety",
        "title": "源不可达不能证明引用伪造",
        "authors": ["A. Auditor"],
        "year": 2026,
        "venue": "CiteGuard Fixtures",
        "doi": "",
        "arxiv_id": "",
        "source": "fixture",
        "abstract": (
            "源不可达和未找到结果只会降低核验置信度，不能证明引用是伪造的，"
            "应检查来源健康或稍后重试。"
        ),
    },
]


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Run an offline MCP stdio smoke test for CiteGuard.")
    parser.add_argument(
        "--command",
        default="",
        help="Server command to launch. Defaults to citeguard-mcp when installed, otherwise the current Python executable.",
    )
    parser.add_argument(
        "--arg",
        action="append",
        default=None,
        help="Server argument; repeat for multiple args. Defaults to no args for citeguard-mcp or '-m citeguard.mcp.server' for the fallback.",
    )
    parser.add_argument(
        "--require-sdk",
        action="store_true",
        help="Fail instead of skipping when the optional MCP SDK is unavailable. Use this in CI/release gates.",
    )
    args = parser.parse_args(argv)
    command, server_args = _server_command(args.command, args.arg)
    return asyncio.run(_run_smoke(command, server_args, require_sdk=args.require_sdk))


def _server_command(command: str, args: Optional[List[str]]) -> tuple[str, List[str]]:
    if command:
        return command, args or []
    installed_entrypoint = shutil.which("citeguard-mcp")
    if installed_entrypoint:
        return installed_entrypoint, args or []
    return sys.executable, args if args is not None else ["-m", "citeguard.mcp.server"]


async def _run_smoke(command: str, server_args: List[str], require_sdk: bool = False) -> int:
    mcp_client = _load_mcp_client()
    if mcp_client is None:
        message = (
            'MCP SDK is not installed. Install published packages with '
            '`python -m pip install citationguard`, or use '
            '`python -m pip install -e .` from a source checkout.'
        )
        if require_sdk:
            print(f"FAIL: {message}")
            return 1
        print(f"SKIP: {message}")
        return 0
    ClientSession, StdioServerParameters, stdio_client = mcp_client

    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_path = Path(tmpdir) / "citations.json"
        fixture_path.write_text(json.dumps(FIXTURE_RECORDS), encoding="utf-8")
        full_text_path = Path(tmpdir) / "lawful-full-text-excerpt.txt"
        full_text_path.write_text(
            "The lawful full-text excerpt shows sparse retrieval improves citation audit recall.",
            encoding="utf-8",
        )
        missing_full_text_path = Path(tmpdir) / "missing-lawful-full-text-excerpt.txt"
        env = dict(os.environ)
        env.update(
            {
                "CITEGUARD_FIXTURE_CITATIONS": str(fixture_path),
                "CITEGUARD_CACHE": ":memory:",
                "CITEGUARD_ALLOWED_FILE_ROOTS": str(tmpdir),
                "TOKENIZERS_PARALLELISM": "false",
            }
        )
        params = StdioServerParameters(command=command, args=server_args, env=env)

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                tools_by_name = {tool.name: tool for tool in tools_result.tools}
                tool_names = set(tools_by_name)
                _require_tool(tool_names, "citeguard_status_tool")
                _require_tool(tool_names, "verify_citation_tool")
                _require_tool(tool_names, "audit_citations_tool")
                _require_tool(tool_names, "check_claim_support_tool")
                _require_tool(tool_names, "check_claim_support_set_tool")
                _require_tool(tool_names, "search_counterevidence_tool")
                _require_tool(tool_names, "audit_claim_support_tool")
                _require_tool_description(
                    tools_by_name,
                    "audit_citations_tool",
                    [
                        "risk_ranking",
                        "review_summary.triage_plan",
                        "review_summary.suggested_fix_summary",
                        "auto_apply_allowed=false",
                        "risk_reason",
                        "suggested_fix.kind",
                        "suggested_fix.requires_user_confirmation",
                        "filtered.returned_indexes",
                    ],
                )
                _require_tool_description(
                    tools_by_name,
                    "audit_claim_support_tool",
                    [
                        "risk_ranking",
                        "review_summary.triage_plan",
                        "review_summary.suggested_fix_summary",
                        "auto_apply_allowed=false",
                        "risk_reason",
                        "suggested_fix.kind",
                        "suggested_fix.requires_user_confirmation",
                        "full_text_file",
                        "evidence_scope=full_text",
                        "filtered.returned_indexes",
                    ],
                )
                _require_tool_description(
                    tools_by_name,
                    "check_claim_support_tool",
                    [
                        "full_text_file",
                        "evidence_scope=full_text",
                        "will not fetch gated",
                    ],
                )
                _require_tool_description(
                    tools_by_name,
                    "check_claim_support_set_tool",
                    [
                        "full_text_file",
                        "evidence_scope=full_text",
                        "support_mode_details",
                        "no_unstated_multi_hop_or_full_text_support",
                        "will not fetch gated",
                    ],
                )

                status = _coerce_tool_payload(await session.call_tool("citeguard_status_tool", {}))
                _require_status_payload(status, fixture_path)

                verify = _coerce_tool_payload(
                    await session.call_tool(
                        "verify_citation_tool",
                        {
                            "title": "Attention Is All You Need",
                            "authors": ["Ashish Vaswani"],
                            "year": 2017,
                            "arxiv_id": "1706.03762",
                        },
                    )
                )
                if verify.get("verdict") != "verified":
                    raise RuntimeError(f"Expected verified fixture result, got: {verify!r}")
                _require_stable_next_action(verify, expected="keep")

                verify_not_found = _coerce_tool_payload(
                    await session.call_tool(
                        "verify_citation_tool",
                        {
                            "title": "A Fixture Paper That Does Not Exist",
                        },
                    )
                )
                _require_not_found_safety_payload(verify_not_found)

                audit = _coerce_tool_payload(
                    await session.call_tool(
                        "audit_citations_tool",
                        {
                            "citations": [
                                {
                                    "title": "Attention Is All You Need",
                                    "arxiv_id": "1706.03762",
                                },
                                {
                                    "title": "A Fixture Paper That Does Not Exist",
                                },
                            ]
                        },
                    )
                )
                _require_audit_citations_payload(audit)

                audit_high_risk = _coerce_tool_payload(
                    await session.call_tool(
                        "audit_citations_tool",
                        {
                            "citations": [
                                {
                                    "title": "Attention Is All You Need",
                                    "arxiv_id": "1706.03762",
                                },
                                {
                                    "title": "A Fixture Paper That Does Not Exist",
                                },
                            ],
                            "high_risk_only": True,
                        },
                    )
                )
                _require_high_risk_filtered_payload(audit_high_risk, total=2, returned_indexes=[1])

                support = _coerce_tool_payload(
                    await session.call_tool(
                        "check_claim_support_tool",
                        {
                            "claim": "The Transformer relies entirely on attention mechanisms.",
                            "title": "Attention Is All You Need",
                            "arxiv_id": "1706.03762",
                        },
                    )
                )
                _require_support_payload(support)

                full_text_support = _coerce_tool_payload(
                    await session.call_tool(
                        "check_claim_support_tool",
                        {
                            "claim": "Sparse retrieval improves citation audit recall.",
                            "title": "Citation Auditing with Metadata Checks",
                            "full_text": [
                                "The lawful full-text excerpt shows sparse retrieval improves citation audit recall."
                            ],
                        },
                    )
                )
                _require_full_text_support_payload(full_text_support)

                full_text_file_support = _coerce_tool_payload(
                    await session.call_tool(
                        "check_claim_support_tool",
                        {
                            "claim": "Sparse retrieval improves citation audit recall.",
                            "title": "Citation Auditing with Metadata Checks",
                            "full_text_file": str(full_text_path),
                        },
                    )
                )
                _require_full_text_file_support_payload(full_text_file_support)

                support_set_full_text_file = _coerce_tool_payload(
                    await session.call_tool(
                        "check_claim_support_set_tool",
                        {
                            "claim": "Sparse retrieval improves citation audit recall.",
                            "citations": [
                                {
                                    "title": "Citation Auditing with Metadata Checks",
                                    "full_text_file": str(full_text_path),
                                }
                            ],
                        },
                    )
                )
                _require_support_set_full_text_file_payload(support_set_full_text_file)

                support_audit_full_text = _coerce_tool_payload(
                    await session.call_tool(
                        "audit_claim_support_tool",
                        {
                            "items": [
                                {
                                    "claim": "Sparse retrieval improves citation audit recall.",
                                    "title": "Citation Auditing with Metadata Checks",
                                    "full_text": [
                                        "The lawful full-text excerpt shows sparse retrieval improves citation audit recall."
                                    ],
                                }
                            ]
                        },
                    )
                )
                _require_support_audit_full_text_payload(support_audit_full_text)

                support_set_counterevidence = _coerce_tool_payload(
                    await session.call_tool(
                        "check_claim_support_set_tool",
                        {
                            "claim": "Method M improves task T.",
                            "citations": [
                                {"title": "A Fixture Paper That Does Not Exist"},
                                {"title": "A Second Fixture Paper That Does Not Exist"},
                            ],
                            "include_counterevidence": True,
                            "counterevidence_top_k": 1,
                        },
                    )
                )
                _require_support_set_counterevidence_payload(support_set_counterevidence)

                support_audit = _coerce_tool_payload(
                    await session.call_tool(
                        "audit_claim_support_tool",
                        {
                            "items": [
                                {
                                    "claim": "The Transformer relies entirely on attention mechanisms.",
                                    "citations": [
                                        {
                                            "title": "Attention Is All You Need",
                                            "arxiv_id": "1706.03762",
                                        },
                                        {
                                            "title": "Citation Auditing with Metadata Checks",
                                        },
                                    ],
                                    "lang": "en",
                                }
                            ]
                        },
                    )
                )
                _require_support_audit_set_payload(support_audit)

                support_audit_nested_full_text_file = _coerce_tool_payload(
                    await session.call_tool(
                        "audit_claim_support_tool",
                        {
                            "items": [
                                {
                                    "claim": "Sparse retrieval improves citation audit recall.",
                                    "citations": [
                                        {
                                            "title": "Citation Auditing with Metadata Checks",
                                            "full_text_file": str(full_text_path),
                                        }
                                    ],
                                }
                            ]
                        },
                    )
                )
                _require_support_audit_nested_full_text_file_payload(
                    support_audit_nested_full_text_file
                )

                support_audit_high_risk = _coerce_tool_payload(
                    await session.call_tool(
                        "audit_claim_support_tool",
                        {
                            "items": [
                                {
                                    "claim": "The Transformer relies entirely on attention mechanisms.",
                                    "title": "Attention Is All You Need",
                                    "arxiv_id": "1706.03762",
                                },
                                {
                                    "claim": "An unknown paper supports this claim.",
                                    "title": "A Fixture Paper That Does Not Exist",
                                },
                            ],
                            "high_risk_only": True,
                        },
                    )
                )
                _require_high_risk_filtered_payload(support_audit_high_risk, total=2, returned_indexes=[1])

                support_audit_high_risk_counterevidence = _coerce_tool_payload(
                    await session.call_tool(
                        "audit_claim_support_tool",
                        {
                            "items": [
                                {
                                    "claim": "The Transformer relies entirely on attention mechanisms.",
                                    "title": "Attention Is All You Need",
                                    "arxiv_id": "1706.03762",
                                },
                                {
                                    "claim": "Method M improves task T.",
                                    "title": "A Fixture Paper That Does Not Exist",
                                },
                            ],
                            "include_counterevidence": True,
                            "counterevidence_top_k": 1,
                            "high_risk_only": True,
                        },
                    )
                )
                _require_support_audit_high_risk_counterevidence_payload(
                    support_audit_high_risk_counterevidence
                )

                counterevidence = _coerce_tool_payload(
                    await session.call_tool(
                        "search_counterevidence_tool",
                        {"claim": "Method M improves task T.", "top_k": 1},
                    )
                )
                _require_counterevidence_payload(counterevidence)

                source_outage_counterevidence = _coerce_tool_payload(
                    await session.call_tool(
                        "search_counterevidence_tool",
                        {
                            "claim": "A source outage increases confidence that a citation is fabricated.",
                            "top_k": 1,
                        },
                    )
                )
                _require_source_outage_counterevidence_payload(source_outage_counterevidence)

                zh_source_outage_counterevidence = _coerce_tool_payload(
                    await session.call_tool(
                        "search_counterevidence_tool",
                        {
                            "claim": "源不可达会提高引用被判定为伪造的置信度。",
                            "top_k": 1,
                        },
                    )
                )
                _require_source_outage_counterevidence_payload(
                    zh_source_outage_counterevidence,
                    expected_claim="源不可达会提高引用被判定为伪造的置信度。",
                    expected_snippet="不能证明引用是伪造的",
                )

                missing_input = _coerce_tool_payload(
                    await session.call_tool("verify_citation_tool", {})
                )
                _require_error_payload(
                    missing_input,
                    code="missing_citation_input",
                    tool="verify_citation_tool",
                )

                missing_claim = _coerce_tool_payload(
                    await session.call_tool(
                        "check_claim_support_tool",
                        {"claim": "", "title": "Attention Is All You Need"},
                    )
                )
                _require_error_payload(
                    missing_claim,
                    code="missing_claim",
                    tool="check_claim_support_tool",
                )

                malformed_audit = _coerce_tool_payload(
                    await session.call_tool(
                        "audit_citations_tool",
                        {"citations": "not a list"},
                    )
                )
                _require_shape_error_payload(
                    malformed_audit,
                    tool="audit_citations_tool",
                    field="citations",
                    expected="list",
                    received="str",
                )

                malformed_support_audit = _coerce_tool_payload(
                    await session.call_tool(
                        "audit_claim_support_tool",
                        {"items": "not a list"},
                    )
                )
                _require_shape_error_payload(
                    malformed_support_audit,
                    tool="audit_claim_support_tool",
                    field="items",
                    expected="list",
                    received="str",
                )

                malformed_support_set = _coerce_tool_payload(
                    await session.call_tool(
                        "check_claim_support_set_tool",
                        {"claim": "A claim.", "citations": "not a list"},
                    )
                )
                _require_shape_error_payload(
                    malformed_support_set,
                    tool="check_claim_support_set_tool",
                    field="citations",
                    expected="non_empty_list",
                    received="str",
                )

                missing_support_set_full_text_file = _coerce_tool_payload(
                    await session.call_tool(
                        "check_claim_support_set_tool",
                        {
                            "claim": "Sparse retrieval improves citation audit recall.",
                            "citations": [
                                {
                                    "title": "Citation Auditing with Metadata Checks",
                                    "full_text_file": str(missing_full_text_path),
                                }
                            ],
                        },
                    )
                )
                _require_file_error_payload(
                    missing_support_set_full_text_file,
                    tool="check_claim_support_set_tool",
                    field="full_text_file",
                    filename=str(missing_full_text_path),
                    index=1,
                    expected_errno=errno.ENOENT,
                )

    print(
        "OK: MCP stdio smoke passed "
        "(initialize, list_tools, status, offline verify, offline audit, offline support, "
        "offline verify not-found safety, "
        "offline full-text support, offline full-text-file support, "
        "offline support-set full-text-file support, offline full-text support-audit, "
        "offline support-set counter-evidence leads, offline support-audit citation set, "
        "offline support-audit nested full-text-file support, offline counter-evidence leads, "
        "support-audit high-risk counter-evidence filtering, "
        "source-outage safety counter-evidence leads, Chinese source-outage safety leads, "
        "support-mode aggregation details, high-risk-only batch filtering, "
        "tool metadata descriptions, source-health next_action, source-health retry delay provenance, "
        "status source-health item contract, structured errors, "
        "support-model status next_action, batch shape error details, full-text-file error details)."
    )
    return 0


def _load_mcp_client() -> Optional[Tuple[Any, Any, Any]]:
    try:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
    except ImportError:
        return None
    return ClientSession, StdioServerParameters, stdio_client


def _require_tool(tool_names: set[str], name: str) -> None:
    if name not in tool_names:
        raise RuntimeError(f"Expected MCP tool {name!r}; available tools: {sorted(tool_names)}")


def _require_tool_description(tools_by_name: dict[str, Any], name: str, phrases: List[str]) -> None:
    tool = tools_by_name.get(name)
    description = getattr(tool, "description", "") if tool is not None else ""
    if not isinstance(description, str):
        description = str(description)
    missing = [phrase for phrase in phrases if phrase not in description]
    if missing:
        raise RuntimeError(f"Expected MCP tool {name!r} description to include {missing}; got: {description!r}")


def _coerce_tool_payload(result: Any) -> dict:
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured

    content = getattr(result, "content", None)
    if isinstance(content, list):
        for item in content:
            text = getattr(item, "text", None)
            if isinstance(text, str):
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed

    if isinstance(result, dict):
        return result
    raise RuntimeError(f"Could not decode MCP tool result: {result!r}")


def _require_error_payload(payload: dict, code: str, tool: str) -> None:
    if payload.get("ok") is not False:
        raise RuntimeError(f"Expected ok=false error payload, got: {payload!r}")
    if payload.get("schema_version") != 1:
        raise RuntimeError(f"Expected error schema_version=1, got: {payload!r}")
    error = payload.get("error")
    if not isinstance(error, dict):
        raise RuntimeError(f"Expected structured error object, got: {payload!r}")
    if error.get("code") != code:
        raise RuntimeError(f"Expected error code {code!r}, got: {payload!r}")
    if not isinstance(error.get("recovery"), str) or not error.get("recovery"):
        raise RuntimeError(f"Expected non-empty error.recovery, got: {payload!r}")
    next_action = error.get("next_action")
    if next_action not in STABLE_NEXT_ACTIONS:
        raise RuntimeError(f"Expected stable error.next_action, got: {payload!r}")
    if error.get("retryable") != ERROR_CODE_RETRYABLE.get(code):
        raise RuntimeError(f"Expected registry-backed error.retryable, got: {payload!r}")
    if error.get("category") != ERROR_CODE_CATEGORY.get(code):
        raise RuntimeError(f"Expected registry-backed error.category, got: {payload!r}")
    details = error.get("details")
    if not isinstance(details, dict) or details.get("tool") != tool:
        raise RuntimeError(f"Expected error details.tool={tool!r}, got: {payload!r}")


def _require_shape_error_payload(payload: dict, tool: str, field: str, expected: str, received: str) -> None:
    """Require details.field, details.expected, and details.received in MCP shape errors."""
    _require_error_payload(payload, code="invalid_input", tool=tool)
    details = payload["error"]["details"]
    expected_details = {
        "field": field,
        "expected": expected,
        "received": received,
    }
    for key, value in expected_details.items():
        if details.get(key) != value:
            raise RuntimeError(f"Expected error details.{key}={value!r}, got: {payload!r}")


def _require_file_error_payload(
    payload: dict,
    tool: str,
    field: str,
    filename: str,
    index: Optional[int] = None,
    citation_index: Optional[int] = None,
    expected_errno: Optional[int] = None,
) -> None:
    _require_error_payload(payload, code="file_error", tool=tool)
    details = payload["error"]["details"]
    expected_details = {
        "field": field,
        "filename": filename,
    }
    if index is not None:
        expected_details["index"] = index
    if citation_index is not None:
        expected_details["citation_index"] = citation_index
    if expected_errno is not None:
        expected_details["errno"] = expected_errno
    for key, value in expected_details.items():
        if details.get(key) != value:
            raise RuntimeError(f"Expected file error details.{key}={value!r}, got: {payload!r}")


def _require_status_payload(payload: dict, fixture_path: Path) -> None:
    if payload.get("service") != "CiteGuard":
        raise RuntimeError(f"Unexpected status payload: {payload!r}")
    if payload.get("schema_version") != 1:
        raise RuntimeError(f"Expected status schema_version=1, got: {payload!r}")
    if payload.get("fixture_citations_path") != str(fixture_path):
        raise RuntimeError("Status did not report the offline fixture path.")
    cache_status = payload.get("cache_status")
    if not isinstance(cache_status, dict):
        raise RuntimeError(f"Expected structured cache_status, got: {payload!r}")
    if cache_status.get("path") != ":memory:" or cache_status.get("inspect_ok") is not True:
        raise RuntimeError(f"Expected in-memory cache_status, got: {payload!r}")
    if cache_status.get("schema_version") != CACHE_SCHEMA_VERSION:
        raise RuntimeError(f"Expected cache_status schema_version={CACHE_SCHEMA_VERSION}, got: {payload!r}")
    _require_stable_next_action(cache_status, expected="continue")

    source_health = payload.get("source_health")
    if not isinstance(source_health, dict):
        raise RuntimeError(f"Expected structured source_health, got: {payload!r}")
    if source_health.get("schema_version") != SOURCE_HEALTH_SCHEMA_VERSION:
        raise RuntimeError(
            f"Expected source_health schema_version={SOURCE_HEALTH_SCHEMA_VERSION}, got: {payload!r}"
        )
    if source_health.get("mode") != "fixture":
        raise RuntimeError(f"Expected fixture source-health mode, got: {payload!r}")
    sources = source_health.get("sources")
    if not isinstance(sources, list) or len(sources) != 1:
        raise RuntimeError(f"Expected one fixture source-health item, got: {payload!r}")
    source_item = sources[0]
    if not isinstance(source_item, dict) or source_item.get("name") != "fixture":
        raise RuntimeError(f"Expected fixture source-health item, got: {payload!r}")
    if source_item.get("status") != "offline_fixture":
        raise RuntimeError(f"Expected offline_fixture source status, got: {payload!r}")
    _require_stable_next_action(source_item, expected="continue")
    if source_item.get("confidence_effect") != "none":
        raise RuntimeError(f"Expected fixture source item confidence_effect=none, got: {payload!r}")
    if source_item.get("interpretation") != "fixture_mode_bypasses_live_sources":
        raise RuntimeError(f"Expected fixture source item interpretation, got: {payload!r}")
    if source_item.get("recovery_code") != "":
        raise RuntimeError(f"Expected fixture source item recovery_code='', got: {payload!r}")
    if source_item.get("retry_after_seconds") is not None:
        raise RuntimeError(f"Expected fixture source item retry_after_seconds=None, got: {payload!r}")
    if source_item.get("retry_delay_seconds") is not None:
        raise RuntimeError(f"Expected fixture source item retry_delay_seconds=None, got: {payload!r}")
    if source_item.get("retry_guidance") != "continue":
        raise RuntimeError(f"Expected fixture source item retry_guidance=continue, got: {payload!r}")

    summary = source_health.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError(f"Expected source_health.summary, got: {payload!r}")
    _require_stable_next_action(summary, expected="continue")
    if summary.get("sources_available") != ["fixture"]:
        raise RuntimeError(f"Expected fixture in sources_available, got: {payload!r}")
    if summary.get("sources_failed") != []:
        raise RuntimeError(f"Expected no failed sources in offline fixture smoke, got: {payload!r}")
    if summary.get("failure_count") != 0 or summary.get("failure_details") != []:
        raise RuntimeError(f"Expected no source-health failures in offline fixture smoke, got: {payload!r}")
    if summary.get("failure_kind_counts") != {} or summary.get("failure_kind_sources") != {}:
        raise RuntimeError(f"Expected empty source-health failure-kind summary, got: {payload!r}")
    if summary.get("retry_delay_seconds") is not None:
        raise RuntimeError(f"Expected fixture source-health retry_delay_seconds=None, got: {payload!r}")
    if summary.get("retry_delay_sources") != []:
        raise RuntimeError(f"Expected empty source-health retry_delay_sources, got: {payload!r}")
    if summary.get("degraded") is not False:
        raise RuntimeError(f"Expected offline fixture status not to be degraded, got: {payload!r}")
    if summary.get("confidence_effect") != "none":
        raise RuntimeError(f"Expected fixture source-health to have no confidence effect, got: {payload!r}")
    if summary.get("interpretation") != "fixture_mode_bypasses_live_sources":
        raise RuntimeError(f"Expected fixture source-health interpretation, got: {payload!r}")

    support_models = payload.get("support_models")
    if not isinstance(support_models, dict):
        raise RuntimeError(f"Expected structured support_models status, got: {payload!r}")
    engine = support_models.get("engine")
    if engine not in {"heuristic_fallback", "production_ensemble"}:
        raise RuntimeError(f"Expected stable support_models.engine, got: {payload!r}")
    _require_stable_next_action(support_models)
    if support_models.get("deep_models_available") not in {True, False}:
        raise RuntimeError(f"Expected boolean support_models.deep_models_available, got: {payload!r}")
    if not isinstance(support_models.get("model_dependencies"), dict):
        raise RuntimeError(f"Expected support_models.model_dependencies, got: {payload!r}")
    missing = support_models.get("missing_dependencies")
    if not isinstance(missing, list):
        raise RuntimeError(f"Expected support_models.missing_dependencies, got: {payload!r}")
    if support_models.get("deep_models_available") is True:
        if engine != "production_ensemble" or support_models.get("next_action") != "continue" or missing != []:
            raise RuntimeError(f"Expected available deep support-model status, got: {payload!r}")
    else:
        if engine != "heuristic_fallback" or support_models.get("next_action") != "install_or_configure_dependency":
            raise RuntimeError(f"Expected heuristic support-model fallback status, got: {payload!r}")


def _require_stable_next_action(payload: dict, expected: Optional[str] = None) -> None:
    next_action = payload.get("next_action")
    if next_action not in STABLE_NEXT_ACTIONS:
        raise RuntimeError(f"Expected stable next_action, got: {payload!r}")
    if expected is not None and next_action != expected:
        raise RuntimeError(f"Expected next_action={expected!r}, got: {payload!r}")


def _require_support_payload(payload: dict) -> None:
    verdict = payload.get("verdict")
    if verdict not in {"supported", "weakly_supported", "insufficient_evidence", "contradicted"}:
        raise RuntimeError(f"Unexpected support verdict in MCP smoke: {payload!r}")
    _require_support_next_action(payload)
    resolution = payload.get("resolution")
    if not isinstance(resolution, dict) or resolution.get("verdict") != "matched":
        raise RuntimeError(f"Expected support resolution.verdict='matched', got: {payload!r}")
    if payload.get("evidence_scope") in {"", None, "none"}:
        raise RuntimeError(f"Expected non-empty support evidence_scope, got: {payload!r}")
    if not isinstance(payload.get("evidence"), dict):
        raise RuntimeError(f"Expected structured support evidence, got: {payload!r}")
    if not payload.get("engine"):
        raise RuntimeError(f"Expected support engine name, got: {payload!r}")


def _require_full_text_support_payload(payload: dict) -> None:
    _require_support_payload(payload)
    if payload.get("evidence_scope") != "full_text":
        raise RuntimeError(f"Expected full-text evidence_scope in MCP smoke, got: {payload!r}")
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        raise RuntimeError(f"Expected structured full-text support evidence, got: {payload!r}")
    if evidence.get("evidence_scope") != "full_text":
        raise RuntimeError(f"Expected evidence.evidence_scope=full_text, got: {payload!r}")
    if evidence.get("source_field") != "user_full_text_excerpt_1":
        raise RuntimeError(f"Expected user_full_text excerpt source field, got: {payload!r}")
    if "lawful full-text excerpt" not in str(evidence.get("text", "")):
        raise RuntimeError(f"Expected lawful full-text excerpt evidence text, got: {payload!r}")


def _require_full_text_file_support_payload(payload: dict) -> None:
    _require_support_payload(payload)
    if payload.get("evidence_scope") != "full_text":
        raise RuntimeError(f"Expected full-text-file evidence_scope in MCP smoke, got: {payload!r}")
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        raise RuntimeError(f"Expected structured full-text-file support evidence, got: {payload!r}")
    if evidence.get("evidence_scope") != "full_text":
        raise RuntimeError(f"Expected full-text-file evidence.evidence_scope=full_text, got: {payload!r}")
    if evidence.get("source_field") != "user_full_text_file_1":
        raise RuntimeError(f"Expected user_full_text_file source field, got: {payload!r}")
    if "lawful full-text excerpt" not in str(evidence.get("text", "")):
        raise RuntimeError(f"Expected lawful full-text-file evidence text, got: {payload!r}")


def _require_support_audit_full_text_payload(payload: dict) -> None:
    summary = payload.get("summary")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise RuntimeError(f"Expected one full-text support-audit result, got: {payload!r}")
    verdict = results[0].get("verdict") if isinstance(results[0], dict) else ""
    if verdict not in {"supported", "weakly_supported"}:
        raise RuntimeError(f"Expected a supported full-text support-audit item, got: {payload!r}")
    if not isinstance(summary, dict) or summary.get(verdict) != 1:
        raise RuntimeError(f"Expected the full-text verdict in the support-audit summary, got: {payload!r}")
    _require_full_text_support_payload(results[0])
    review_summary = _require_review_summary(payload, total=1)
    expected_risk_key = "low_risk_count" if verdict == "supported" else "medium_risk_count"
    if review_summary.get(expected_risk_key) != 1:
        raise RuntimeError(f"Expected model-appropriate full-text risk summary, got: {payload!r}")
    risk_ranking = payload.get("risk_ranking")
    if not isinstance(risk_ranking, list) or len(risk_ranking) != 1:
        raise RuntimeError(f"Expected one full-text support-audit risk row, got: {payload!r}")
    risk_item = risk_ranking[0]
    if risk_item.get("evidence_scope") != "full_text":
        raise RuntimeError(f"Expected full-text support-audit risk evidence_scope, got: {payload!r}")
    if risk_item.get("evidence_source_field") != "user_full_text_excerpt_1":
        raise RuntimeError(f"Expected full-text support-audit risk source field, got: {payload!r}")
    if verdict == "supported" and "full-text evidence" not in str(risk_item.get("recommendation", "")):
        raise RuntimeError(f"Expected scope-aware full-text recommendation, got: {payload!r}")
    _require_support_next_action(risk_item)


def _require_support_set_full_text_file_payload(payload: dict) -> None:
    if payload.get("verdict") not in {"supported", "weakly_supported"}:
        raise RuntimeError(f"Expected supported or conservative weak support-set full-text-file payload, got: {payload!r}")
    if payload.get("verdict") == "supported":
        expected_mode = "single_strong_support"
        expected_decision = "one_strong_citation_supports_claim"
    else:
        expected_mode = "single_weak_support"
        expected_decision = "single_weak_citation_remains_tentative"
    if payload.get("support_mode") != expected_mode:
        raise RuntimeError(f"Expected {expected_mode} support-set mode, got: {payload!r}")
    if payload.get("evidence_scope") != "full_text":
        raise RuntimeError(f"Expected support-set full-text-file evidence_scope, got: {payload!r}")
    if payload.get("evidence_source_fields") != ["user_full_text_file_1"]:
        raise RuntimeError(f"Expected support-set full-text-file source field, got: {payload!r}")
    _require_support_mode_details(payload, expected_decision=expected_decision)
    _require_support_next_action(payload)
    if payload.get("support_mode_details", {}).get("full_text_evidence_present") is not True:
        raise RuntimeError(f"Expected support-set full-text evidence flag, got: {payload!r}")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise RuntimeError(f"Expected one nested support-set result, got: {payload!r}")
    _require_full_text_file_support_payload(results[0])
    evidence = payload.get("evidence")
    if not isinstance(evidence, list) or len(evidence) != 1:
        raise RuntimeError(f"Expected one aggregate support-set evidence row, got: {payload!r}")
    if evidence[0].get("source_field") != "user_full_text_file_1":
        raise RuntimeError(f"Expected aggregate support-set full-text-file source field, got: {payload!r}")


def _require_support_audit_nested_full_text_file_payload(payload: dict) -> None:
    summary = payload.get("summary")
    if not isinstance(summary, dict) or summary.get("supported", 0) + summary.get("weakly_supported", 0) != 1:
        raise RuntimeError(f"Expected one supported or weakly_supported nested full-text-file support-audit item, got: {payload!r}")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise RuntimeError(f"Expected one nested full-text-file support-audit result, got: {payload!r}")
    result = results[0]
    if result.get("input_mode") != "citation_set":
        raise RuntimeError(f"Expected nested full-text-file input_mode='citation_set', got: {payload!r}")
    _require_support_set_full_text_file_payload(result)

    risk_ranking = payload.get("risk_ranking")
    if not isinstance(risk_ranking, list) or len(risk_ranking) != 1:
        raise RuntimeError(f"Expected one nested full-text-file risk row, got: {payload!r}")
    risk_item = risk_ranking[0]
    if risk_item.get("input_mode") != "citation_set":
        raise RuntimeError(f"Expected nested full-text-file risk input_mode, got: {payload!r}")
    if risk_item.get("evidence_scope") != "full_text":
        raise RuntimeError(f"Expected nested full-text-file risk evidence_scope, got: {payload!r}")
    if risk_item.get("evidence_source_fields") != ["user_full_text_file_1"]:
        raise RuntimeError(f"Expected nested full-text-file risk source field, got: {payload!r}")
    if risk_item.get("verdict") == "supported":
        expected_decision = "one_strong_citation_supports_claim"
    else:
        expected_decision = "single_weak_citation_remains_tentative"
    _require_support_mode_details(risk_item, expected_decision=expected_decision)
    _require_support_next_action(risk_item)
    _require_risk_reason(risk_item, payload)
    _require_suggested_fix(risk_item, payload)

    review_summary = _require_review_summary(payload, total=1)
    if risk_item.get("verdict") == "supported":
        expected_queue = "safe_to_keep_indexes"
        expected_next_action = "keep"
    else:
        expected_queue = "evidence_review_indexes"
        expected_next_action = "tighten_claim_or_inspect_full_text"
    if review_summary["action_queues"][expected_queue] != [0]:
        raise RuntimeError(f"Expected nested full-text-file support-audit {expected_queue}, got: {payload!r}")
    if review_summary["triage_plan"]["next_action"] != expected_next_action:
        raise RuntimeError(f"Expected nested full-text-file support-audit next_action={expected_next_action}, got: {payload!r}")


def _require_review_summary(payload: dict, total: int) -> dict:
    review_summary = payload.get("review_summary")
    if not isinstance(review_summary, dict):
        raise RuntimeError(f"Expected batch review_summary, got: {payload!r}")
    if review_summary.get("total") != total:
        raise RuntimeError(f"Expected review_summary.total={total}, got: {payload!r}")
    risk_counts = review_summary.get("risk_counts")
    if not isinstance(risk_counts, dict):
        raise RuntimeError(f"Expected review_summary.risk_counts, got: {payload!r}")
    if sum(value for value in risk_counts.values() if isinstance(value, int)) != total:
        raise RuntimeError(f"Expected review_summary risk counts to sum to {total}, got: {payload!r}")
    next_actions = review_summary.get("next_actions")
    if not isinstance(next_actions, dict) or not next_actions:
        raise RuntimeError(f"Expected non-empty review_summary.next_actions, got: {payload!r}")
    for action in next_actions:
        if action not in STABLE_NEXT_ACTIONS:
            raise RuntimeError(f"Expected stable review_summary next_action, got: {payload!r}")
    top_risk_indexes = review_summary.get("top_risk_indexes")
    if not isinstance(top_risk_indexes, list) or not top_risk_indexes:
        raise RuntimeError(f"Expected review_summary.top_risk_indexes, got: {payload!r}")
    _require_action_queues(review_summary, total)
    _require_triage_plan(review_summary, total)
    return review_summary


def _require_action_queues(review_summary: dict, total: int) -> None:
    action_queues = review_summary.get("action_queues")
    if not isinstance(action_queues, dict):
        raise RuntimeError(f"Expected review_summary.action_queues, got: {review_summary!r}")
    if set(action_queues) != set(REVIEW_ACTION_QUEUE_KEYS):
        raise RuntimeError(f"Unexpected review_summary.action_queues keys, got: {review_summary!r}")
    for key, indexes in action_queues.items():
        if not isinstance(indexes, list) or not all(isinstance(index, int) for index in indexes):
            raise RuntimeError(f"Expected integer list in action_queues.{key}, got: {review_summary!r}")
        if any(index < 0 or index >= total for index in indexes):
            raise RuntimeError(f"Expected action_queues indexes within batch bounds, got: {review_summary!r}")


def _require_triage_plan(review_summary: dict, total: int) -> None:
    triage_plan = review_summary.get("triage_plan")
    if not isinstance(triage_plan, dict):
        raise RuntimeError(f"Expected review_summary.triage_plan, got: {review_summary!r}")
    if triage_plan.get("schema_version") != 1:
        raise RuntimeError(f"Expected triage_plan schema_version=1, got: {review_summary!r}")
    if triage_plan.get("status") not in {"clear", "review_required"}:
        raise RuntimeError(f"Expected stable triage_plan.status, got: {review_summary!r}")
    if triage_plan.get("next_action") not in STABLE_NEXT_ACTIONS:
        raise RuntimeError(f"Expected stable triage_plan.next_action, got: {review_summary!r}")
    for key in (
        "review_required_indexes",
        "high_risk_indexes",
        "medium_risk_indexes",
        "source_retry_indexes",
        "safe_to_keep_indexes",
    ):
        indexes = triage_plan.get(key)
        if not isinstance(indexes, list) or not all(isinstance(index, int) for index in indexes):
            raise RuntimeError(f"Expected integer list in triage_plan.{key}, got: {review_summary!r}")
        if any(index < 0 or index >= total for index in indexes):
            raise RuntimeError(f"Expected triage_plan indexes within batch bounds, got: {review_summary!r}")
    policy = str(triage_plan.get("policy", ""))
    if "source_retry_is_inconclusive_not_fabrication" not in policy:
        raise RuntimeError(f"Expected triage_plan source retry safety policy, got: {review_summary!r}")


def _require_audit_citations_payload(payload: dict) -> None:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError(f"Expected audit summary, got: {payload!r}")
    if summary.get("verified") != 1 or summary.get("not_found") != 1:
        raise RuntimeError(f"Expected one verified and one not_found citation, got: {payload!r}")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 2:
        raise RuntimeError(f"Expected two audit results, got: {payload!r}")
    for result in results:
        _require_stable_next_action(result)
    risk_ranking = payload.get("risk_ranking")
    if not isinstance(risk_ranking, list) or len(risk_ranking) != 2:
        raise RuntimeError(f"Expected two audit risk items, got: {payload!r}")
    for item in risk_ranking:
        _require_stable_next_action(item)
        _require_risk_reason(item, payload)
        _require_suggested_fix(item, payload)
    review_summary = _require_review_summary(payload, total=2)
    if review_summary.get("high_risk_count") != 1 or review_summary.get("low_risk_count") != 1:
        raise RuntimeError(f"Expected audit review_summary high/low counts, got: {payload!r}")
    if review_summary.get("top_high_risk_indexes") != [1]:
        raise RuntimeError(f"Expected audit top_high_risk_indexes=[1], got: {payload!r}")
    if review_summary["next_actions"].get("keep") != 1:
        raise RuntimeError(f"Expected audit review_summary next_action keep count, got: {payload!r}")
    if review_summary["next_actions"].get("resolve_identifier_or_replace") != 1:
        raise RuntimeError(f"Expected audit review_summary not_found action count, got: {payload!r}")
    queues = review_summary["action_queues"]
    if queues["safe_to_keep_indexes"] != [0] or queues["identity_resolution_indexes"] != [1]:
        raise RuntimeError(f"Expected audit action_queues to route keep and identity work, got: {payload!r}")


def _require_not_found_safety_payload(payload: dict) -> None:
    if payload.get("verdict") != "not_found":
        raise RuntimeError(f"Expected verify_citation_tool not_found safety payload, got: {payload!r}")
    _require_stable_next_action(payload, expected="resolve_identifier_or_replace")
    if payload.get("outage_limited") is not False:
        raise RuntimeError(f"Expected fixture not_found not to be outage-limited, got: {payload!r}")
    if payload.get("source_failure_mode") != "none":
        raise RuntimeError(f"Expected fixture not_found source_failure_mode=none, got: {payload!r}")
    if payload.get("sources_failed") != []:
        raise RuntimeError(f"Expected fixture not_found sources_failed=[], got: {payload!r}")
    explanation = str(payload.get("explanation", "")).lower()
    if "could not be verified" not in explanation:
        raise RuntimeError(f"Expected conservative not_found explanation, got: {payload!r}")
    for unsafe_phrase in ("fake", "fabricated"):
        if unsafe_phrase in explanation:
            raise RuntimeError(
                f"Expected not_found explanation not to assert {unsafe_phrase!r}, got: {payload!r}"
            )

    suggested_fix = payload.get("suggested_fix")
    if isinstance(suggested_fix, dict):
        if suggested_fix.get("policy") != "not_found_is_high_risk_not_fabrication_proof":
            raise RuntimeError(f"Expected not_found safety policy in suggested_fix, got: {payload!r}")
        if suggested_fix.get("requires_user_confirmation") is not True:
            raise RuntimeError(f"Expected not_found suggested_fix to require user confirmation, got: {payload!r}")


def _require_high_risk_filtered_payload(payload: dict, total: int, returned_indexes: List[int]) -> None:
    filtered = payload.get("filtered")
    if not isinstance(filtered, dict) or filtered.get("high_risk_only") is not True:
        raise RuntimeError(f"Expected high-risk-only filtered metadata, got: {payload!r}")
    if filtered.get("original_results") != total:
        raise RuntimeError(f"Expected filtered.original_results={total}, got: {payload!r}")
    if filtered.get("returned_indexes") != returned_indexes:
        raise RuntimeError(f"Expected filtered.returned_indexes={returned_indexes}, got: {payload!r}")
    expected_omitted = [index for index in range(total) if index not in set(returned_indexes)]
    if filtered.get("omitted_indexes") != expected_omitted:
        raise RuntimeError(f"Expected filtered.omitted_indexes={expected_omitted}, got: {payload!r}")
    omitted_summary = filtered.get("omitted_review_summary")
    if not isinstance(omitted_summary, dict):
        raise RuntimeError(f"Expected filtered.omitted_review_summary, got: {payload!r}")
    if omitted_summary.get("total") != len(expected_omitted):
        raise RuntimeError(f"Expected omitted_review_summary.total={len(expected_omitted)}, got: {payload!r}")
    _require_action_queues(omitted_summary, total)
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != len(returned_indexes):
        raise RuntimeError(f"Expected filtered results to match returned indexes, got: {payload!r}")
    risk_ranking = payload.get("risk_ranking")
    if not isinstance(risk_ranking, list) or any(item.get("risk") != "high" for item in risk_ranking):
        raise RuntimeError(f"Expected high-risk-only risk_ranking, got: {payload!r}")
    for item in risk_ranking:
        _require_risk_reason(item, payload)
        _require_suggested_fix(item, payload)


def _require_support_audit_set_payload(payload: dict) -> None:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError(f"Expected support-audit summary, got: {payload!r}")
    for key in ("supported", "weakly_supported", "insufficient_evidence", "contradicted"):
        if key not in summary:
            raise RuntimeError(f"Expected support-audit summary.{key}, got: {payload!r}")

    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise RuntimeError(f"Expected one support-audit result, got: {payload!r}")
    result = results[0]
    if result.get("input_mode") != "citation_set":
        raise RuntimeError(f"Expected support-audit input_mode='citation_set', got: {payload!r}")
    if result.get("support_mode") in {"", None}:
        raise RuntimeError(f"Expected support-audit support_mode, got: {payload!r}")
    _require_support_mode_details(result)
    nested_results = result.get("results")
    if not isinstance(nested_results, list) or len(nested_results) != 2:
        raise RuntimeError(f"Expected two nested citation support results, got: {payload!r}")
    _require_support_next_action(result)
    for nested in nested_results:
        if not isinstance(nested, dict):
            raise RuntimeError(f"Expected structured nested support result, got: {payload!r}")
        _require_support_next_action(nested)

    risk_ranking = payload.get("risk_ranking")
    if not isinstance(risk_ranking, list) or len(risk_ranking) != 1:
        raise RuntimeError(f"Expected one support-audit risk item, got: {payload!r}")
    risk_item = risk_ranking[0]
    if risk_item.get("input_mode") != "citation_set":
        raise RuntimeError(f"Expected risk input_mode='citation_set', got: {payload!r}")
    if "supporting_citation_count" not in risk_item:
        raise RuntimeError(f"Expected supporting_citation_count in risk item, got: {payload!r}")
    _require_support_mode_details(risk_item)
    _require_support_next_action(risk_item)
    _require_risk_reason(risk_item, payload)
    _require_suggested_fix(risk_item, payload)
    review_summary = _require_review_summary(payload, total=1)
    if review_summary.get("top_risk_indexes") != [0]:
        raise RuntimeError(f"Expected support-audit top_risk_indexes=[0], got: {payload!r}")
    if review_summary["next_actions"].get(risk_item["next_action"]) != 1:
        raise RuntimeError(f"Expected support-audit next_action count for risk item, got: {payload!r}")
    if risk_item["next_action"] == "keep_claim" and review_summary["action_queues"]["safe_to_keep_indexes"] != [0]:
        raise RuntimeError(f"Expected supported citation-set action queue to keep index 0, got: {payload!r}")


def _require_risk_reason(item: dict, payload: dict) -> None:
    if not isinstance(item.get("risk_reason"), str) or not item.get("risk_reason"):
        raise RuntimeError(f"Expected risk_ranking risk_reason, got: {payload!r}")


def _require_suggested_fix(item: dict, payload: dict) -> None:
    suggested_fix = item.get("suggested_fix")
    if not isinstance(suggested_fix, dict):
        raise RuntimeError(f"Expected risk_ranking suggested_fix, got: {payload!r}")
    if not isinstance(suggested_fix.get("kind"), str) or not suggested_fix.get("kind"):
        raise RuntimeError(f"Expected suggested_fix.kind, got: {payload!r}")
    if suggested_fix.get("action") not in STABLE_NEXT_ACTIONS:
        raise RuntimeError(f"Expected stable suggested_fix.action, got: {payload!r}")
    if not isinstance(suggested_fix.get("requires_user_confirmation"), bool):
        raise RuntimeError(f"Expected suggested_fix.requires_user_confirmation, got: {payload!r}")


def _require_support_set_counterevidence_payload(payload: dict) -> None:
    if payload.get("support_mode") != "insufficient_evidence":
        raise RuntimeError(f"Expected support-set insufficient_evidence mode, got: {payload!r}")
    _require_support_mode_details(payload, expected_decision="no_citation_confirms_claim")
    if payload.get("counterevidence_included") is not True:
        raise RuntimeError(f"Expected support-set counterevidence_included=true, got: {payload!r}")
    if payload.get("counterevidence_review") is not True:
        raise RuntimeError(f"Expected support-set aggregate counterevidence_review=true, got: {payload!r}")
    if payload.get("counterevidence_top_k") != 1:
        raise RuntimeError(f"Expected support-set counterevidence_top_k=1, got: {payload!r}")
    if payload.get("counterevidence_reason") != "insufficient_evidence":
        raise RuntimeError(f"Expected support-set aggregate counterevidence reason, got: {payload!r}")
    _require_support_next_action(payload)
    counterevidence = payload.get("counterevidence")
    if not isinstance(counterevidence, dict):
        raise RuntimeError(f"Expected support-set aggregate counterevidence report, got: {payload!r}")
    _require_counterevidence_payload(counterevidence)
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 2:
        raise RuntimeError(f"Expected support-set per-citation results, got: {payload!r}")
    for result in results:
        if result.get("counterevidence_review") is not True:
            raise RuntimeError(f"Expected support-set nested result to keep review flag, got: {payload!r}")


def _require_support_mode_details(payload: dict, expected_decision: Optional[str] = None) -> None:
    details = payload.get("support_mode_details")
    if not isinstance(details, dict):
        raise RuntimeError(f"Expected support_mode_details, got: {payload!r}")
    if details.get("schema_version") != 1:
        raise RuntimeError(f"Expected support_mode_details.schema_version=1, got: {payload!r}")
    decision = details.get("decision")
    if not isinstance(decision, str) or not decision:
        raise RuntimeError(f"Expected support_mode_details.decision, got: {payload!r}")
    if expected_decision is not None and decision != expected_decision:
        raise RuntimeError(f"Expected support_mode_details.decision={expected_decision!r}, got: {payload!r}")
    policy = str(details.get("policy", ""))
    for required in (
        "contradictions_dominate",
        "multiple_weak_citations_remain_tentative",
        "no_unstated_multi_hop_or_full_text_support",
    ):
        if required not in policy:
            raise RuntimeError(f"Expected support_mode_details.policy to include {required!r}, got: {payload!r}")
    for key in (
        "supported_indexes",
        "weakly_supported_indexes",
        "contradicted_indexes",
        "insufficient_evidence_indexes",
    ):
        if not isinstance(details.get(key), list):
            raise RuntimeError(f"Expected support_mode_details.{key} list, got: {payload!r}")
    if not isinstance(details.get("full_text_evidence_present"), bool):
        raise RuntimeError(f"Expected support_mode_details.full_text_evidence_present bool, got: {payload!r}")


def _require_support_audit_high_risk_counterevidence_payload(payload: dict) -> None:
    _require_high_risk_filtered_payload(payload, total=2, returned_indexes=[1])
    if payload.get("counterevidence_included") is not True:
        raise RuntimeError(f"Expected counterevidence_included=true, got: {payload!r}")
    if payload.get("counterevidence_top_k") != 1:
        raise RuntimeError(f"Expected counterevidence_top_k=1, got: {payload!r}")
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != 1:
        raise RuntimeError(f"Expected one filtered support-audit result, got: {payload!r}")
    result = results[0]
    if result.get("counterevidence_review") is not True:
        raise RuntimeError(f"Expected filtered result to retain counterevidence_review, got: {payload!r}")
    counterevidence = result.get("counterevidence")
    if not isinstance(counterevidence, dict):
        raise RuntimeError(f"Expected filtered result counterevidence report, got: {payload!r}")
    _require_counterevidence_payload(counterevidence)

    risk_ranking = payload.get("risk_ranking")
    if not isinstance(risk_ranking, list) or len(risk_ranking) != 1:
        raise RuntimeError(f"Expected one filtered support-audit risk row, got: {payload!r}")
    risk_item = risk_ranking[0]
    if risk_item.get("index") != 1:
        raise RuntimeError(f"Expected filtered risk row to preserve original index 1, got: {payload!r}")
    risk_counterevidence = risk_item.get("counterevidence")
    if not isinstance(risk_counterevidence, dict):
        raise RuntimeError(f"Expected filtered risk row counterevidence report, got: {payload!r}")
    _require_counterevidence_payload(risk_counterevidence)

    omitted_summary = payload.get("filtered", {}).get("omitted_review_summary", {})
    if omitted_summary.get("total") != 1:
        raise RuntimeError(f"Expected one omitted support-audit row summary, got: {payload!r}")
    if omitted_summary.get("low_risk_count") + omitted_summary.get("medium_risk_count", 0) < 1:
        raise RuntimeError(f"Expected omitted summary to retain lower-risk row counts, got: {payload!r}")


def _require_support_next_action(payload: dict) -> None:
    verdict = payload.get("verdict")
    resolution = payload.get("resolution") if isinstance(payload.get("resolution"), dict) else {}
    expected_by_verdict = {
        "supported": "keep_claim",
        "weakly_supported": "tighten_claim_or_inspect_full_text",
        "contradicted": "rewrite_or_replace_evidence",
    }
    expected = expected_by_verdict.get(str(verdict))
    if expected is None:
        if resolution.get("verdict") == "ambiguous":
            expected = "disambiguate_identifier"
        elif resolution.get("source_failure_mode") == "all_sources_failed":
            expected = "retry_or_check_source_health"
        elif resolution.get("verdict") == "not_found":
            expected = "resolve_citation_identity"
        else:
            expected = "inspect_full_text_or_find_stronger_citation"
    _require_stable_next_action(payload, expected=expected)


def _require_counterevidence_payload(payload: dict) -> None:
    if payload.get("claim") != "Method M improves task T.":
        raise RuntimeError(f"Unexpected counter-evidence claim, got: {payload!r}")
    if payload.get("candidate_count") != 1:
        raise RuntimeError(f"Expected one counter-evidence candidate, got: {payload!r}")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise RuntimeError(f"Expected one counter-evidence candidate row, got: {payload!r}")
    candidate = candidates[0]
    if candidate.get("signal") != "explicit_contradiction_cue":
        raise RuntimeError(f"Expected explicit contradiction cue lead, got: {payload!r}")
    if "improvement_negation" not in set(candidate.get("matched_query_roles", [])):
        raise RuntimeError(f"Expected improvement_negation query role, got: {payload!r}")
    review_summary = payload.get("review_summary")
    if not isinstance(review_summary, dict):
        raise RuntimeError(f"Expected counter-evidence review_summary, got: {payload!r}")
    if review_summary.get("policy") != "review_leads_not_contradiction_verdicts":
        raise RuntimeError(f"Expected leads-only review_summary policy, got: {payload!r}")
    if review_summary.get("signal_counts", {}).get("explicit_contradiction_cue") != 1:
        raise RuntimeError(f"Expected review_summary explicit cue count, got: {payload!r}")
    if review_summary.get("top_candidate", {}).get("signal") != "explicit_contradiction_cue":
        raise RuntimeError(f"Expected review_summary top candidate signal, got: {payload!r}")
    query_plan = payload.get("query_plan")
    if not isinstance(query_plan, list) or "improvement_negation" not in {item.get("role") for item in query_plan}:
        raise RuntimeError(f"Expected improvement_negation in query_plan, got: {payload!r}")
    if "review leads" not in str(payload.get("interpretation", "")):
        raise RuntimeError(f"Expected conservative review-leads interpretation, got: {payload!r}")
    if payload.get("source_failure_mode") != "none":
        raise RuntimeError(f"Expected no source failure in offline counter-evidence smoke, got: {payload!r}")
    _require_stable_next_action(payload, expected="review_counterevidence_leads")


def _require_source_outage_counterevidence_payload(
    payload: dict,
    expected_claim: str = "A source outage increases confidence that a citation is fabricated.",
    expected_snippet: str = "",
) -> None:
    if payload.get("claim") != expected_claim:
        raise RuntimeError(f"Unexpected source-outage counter-evidence claim, got: {payload!r}")
    if payload.get("candidate_count") != 1:
        raise RuntimeError(f"Expected one source-outage safety candidate, got: {payload!r}")
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise RuntimeError(f"Expected one source-outage safety candidate row, got: {payload!r}")
    candidate = candidates[0]
    if candidate.get("signal") != "source_outage_safety_cue":
        raise RuntimeError(f"Expected source_outage_safety_cue lead, got: {payload!r}")
    if expected_snippet and expected_snippet not in str(candidate.get("abstract_snippet", "")):
        raise RuntimeError(f"Expected source-outage safety snippet {expected_snippet!r}, got: {payload!r}")
    if "source_outage_safety" not in set(candidate.get("matched_query_roles", [])):
        raise RuntimeError(f"Expected source_outage_safety query role, got: {payload!r}")
    query_plan = payload.get("query_plan")
    if not isinstance(query_plan, list) or "source_outage_safety" not in {item.get("role") for item in query_plan}:
        raise RuntimeError(f"Expected source_outage_safety in query_plan, got: {payload!r}")
    if "review leads" not in str(payload.get("interpretation", "")):
        raise RuntimeError(f"Expected conservative review-leads interpretation, got: {payload!r}")
    if payload.get("source_failure_mode") != "none":
        raise RuntimeError(f"Expected no source failure in offline source-outage safety smoke, got: {payload!r}")
    _require_stable_next_action(payload, expected="review_counterevidence_leads")


if __name__ == "__main__":
    raise SystemExit(main())
