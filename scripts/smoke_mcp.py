#!/usr/bin/env python3
"""Smoke-test the CiteGuard MCP stdio server with an offline fixture."""

from __future__ import annotations

import argparse
import asyncio
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
        message = "MCP SDK is not installed. Install with `python -m pip install -e \".[mcp]\"`."
        if require_sdk:
            print(f"FAIL: {message}")
            return 1
        print(f"SKIP: {message}")
        return 0
    ClientSession, StdioServerParameters, stdio_client = mcp_client

    with tempfile.TemporaryDirectory() as tmpdir:
        fixture_path = Path(tmpdir) / "citations.json"
        fixture_path.write_text(json.dumps(FIXTURE_RECORDS), encoding="utf-8")
        env = dict(os.environ)
        env.update(
            {
                "CITEGUARD_FIXTURE_CITATIONS": str(fixture_path),
                "CITEGUARD_CACHE": ":memory:",
                "TOKENIZERS_PARALLELISM": "false",
            }
        )
        params = StdioServerParameters(command=command, args=server_args, env=env)

        async with stdio_client(params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                tool_names = {tool.name for tool in tools_result.tools}
                _require_tool(tool_names, "citeguard_status_tool")
                _require_tool(tool_names, "verify_citation_tool")
                _require_tool(tool_names, "audit_citations_tool")
                _require_tool(tool_names, "check_claim_support_tool")
                _require_tool(tool_names, "check_claim_support_set_tool")
                _require_tool(tool_names, "search_counterevidence_tool")
                _require_tool(tool_names, "audit_claim_support_tool")

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

                counterevidence = _coerce_tool_payload(
                    await session.call_tool(
                        "search_counterevidence_tool",
                        {"claim": "Method M improves task T.", "top_k": 1},
                    )
                )
                _require_counterevidence_payload(counterevidence)

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

    print(
        "OK: MCP stdio smoke passed "
        "(initialize, list_tools, status, offline verify, offline audit, offline support, "
        "offline support-audit citation set, offline counter-evidence leads, "
        "high-risk-only batch filtering, source-health next_action, structured errors)."
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
    details = error.get("details")
    if not isinstance(details, dict) or details.get("tool") != tool:
        raise RuntimeError(f"Expected error details.tool={tool!r}, got: {payload!r}")


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
    if summary.get("degraded") is not False:
        raise RuntimeError(f"Expected offline fixture status not to be degraded, got: {payload!r}")


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
    results = payload.get("results")
    if not isinstance(results, list) or len(results) != len(returned_indexes):
        raise RuntimeError(f"Expected filtered results to match returned indexes, got: {payload!r}")
    risk_ranking = payload.get("risk_ranking")
    if not isinstance(risk_ranking, list) or any(item.get("risk") != "high" for item in risk_ranking):
        raise RuntimeError(f"Expected high-risk-only risk_ranking, got: {payload!r}")


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
    _require_support_next_action(risk_item)
    review_summary = _require_review_summary(payload, total=1)
    if review_summary.get("top_risk_indexes") != [0]:
        raise RuntimeError(f"Expected support-audit top_risk_indexes=[0], got: {payload!r}")
    if review_summary["next_actions"].get(risk_item["next_action"]) != 1:
        raise RuntimeError(f"Expected support-audit next_action count for risk item, got: {payload!r}")
    if risk_item["next_action"] == "keep_claim" and review_summary["action_queues"]["safe_to_keep_indexes"] != [0]:
        raise RuntimeError(f"Expected supported citation-set action queue to keep index 0, got: {payload!r}")


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
    query_plan = payload.get("query_plan")
    if not isinstance(query_plan, list) or "improvement_negation" not in {item.get("role") for item in query_plan}:
        raise RuntimeError(f"Expected improvement_negation in query_plan, got: {payload!r}")
    if "review leads" not in str(payload.get("interpretation", "")):
        raise RuntimeError(f"Expected conservative review-leads interpretation, got: {payload!r}")
    if payload.get("source_failure_mode") != "none":
        raise RuntimeError(f"Expected no source failure in offline counter-evidence smoke, got: {payload!r}")
    _require_stable_next_action(payload, expected="review_counterevidence_leads")


if __name__ == "__main__":
    raise SystemExit(main())
