#!/usr/bin/env python3
"""Live golden-case canary against real scholarly sources.

Runs a small pinned dataset of golden citations (data/eval/canary_golden.json)
through the live verification pipeline and fails (exit code 1) when any case
drifts from its expected outcome. Results degraded by source outages are
skipped rather than failed: the canary watches verdict drift, not source
availability.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.retrieval.scholarly_clients import build_live_metadata_source
from citeguard.runtime import DEFAULT_MAILTO, build_doi_registry_probe
from citeguard.verification import parse_citation, verify_citation

DEFAULT_DATASET = "data/eval/canary_golden.json"
DEFAULT_SOURCES = "openalex,crossref,arxiv"

SUPPORTED_EXPECT_KEYS = frozenset(
    {"verdict_in", "must_not", "canonical_year", "canonical_year_in", "doi_registered"}
)

# Golden cases that pin the M1 fixes; their expectations must never be loosened.
HARD_LINE_CASE_IDS = frozenset({"g01", "g02", "g04", "g05"})


def load_dataset(path: Optional[Any] = None, payload: Optional[Mapping[str, Any]] = None) -> List[Dict[str, Any]]:
    """Load and validate the golden dataset; return its list of cases.

    Accepts either a file ``path`` or an already-parsed ``payload`` mapping.
    Raises ``ValueError`` on duplicate ids, empty fields, or unsupported
    expect keys so a malformed dataset fails loudly before any network call.
    """

    if payload is None:
        if path is None:
            raise ValueError("load_dataset requires a path or a payload")
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("dataset must contain a non-empty 'cases' list")

    seen_ids = set()
    for case in cases:
        case_id = case.get("id")
        if not case_id or not isinstance(case_id, str):
            raise ValueError(f"case is missing a string id: {case!r}")
        if case_id in seen_ids:
            raise ValueError(f"duplicate case id: {case_id}")
        seen_ids.add(case_id)
        fields = case.get("fields")
        if not isinstance(fields, dict) or not fields:
            raise ValueError(f"case {case_id} must define non-empty 'fields'")
        expect = case.get("expect")
        if not isinstance(expect, dict) or not expect:
            raise ValueError(f"case {case_id} must define non-empty 'expect'")
        unsupported = set(expect) - SUPPORTED_EXPECT_KEYS
        if unsupported:
            raise ValueError(f"case {case_id} uses unsupported expect keys: {sorted(unsupported)}")
    return cases


def evaluate_case(result_dict: Mapping[str, Any], expect: Mapping[str, Any]) -> Tuple[str, List[str]]:
    """Return (status, reasons). status: 'pass' | 'fail' | 'skip'.

    A result with outage_limited=True is 'skip' (the canary watches verdict
    drift, not source availability). Otherwise every expect key must hold:
    verdict_in / must_not check result_dict['verdict']; canonical_year(_in)
    check result_dict['canonical_record']['year'] when a canonical record is
    expected to exist; doi_registered checks result_dict['doi_registration']['registered'].
    """

    if result_dict.get("outage_limited"):
        return "skip", ["outage_limited result; sources degraded, not verdict drift"]

    failures: List[str] = []
    skips: List[str] = []
    verdict = str(result_dict.get("verdict", ""))

    verdict_in = expect.get("verdict_in")
    if verdict_in is not None and verdict not in verdict_in:
        failures.append(f"verdict '{verdict}' not in allowed set {list(verdict_in)}")

    must_not = expect.get("must_not")
    if must_not is not None and verdict in must_not:
        failures.append(f"verdict '{verdict}' is in forbidden set {list(must_not)}")

    if "canonical_year" in expect or "canonical_year_in" in expect:
        canonical = result_dict.get("canonical_record")
        if not isinstance(canonical, dict):
            failures.append("canonical_record missing while a canonical year expectation is set")
        else:
            year = canonical.get("year")
            if "canonical_year" in expect and year != expect["canonical_year"]:
                failures.append(f"canonical year {year!r} != expected {expect['canonical_year']!r}")
            if "canonical_year_in" in expect and year not in expect["canonical_year_in"]:
                failures.append(f"canonical year {year!r} not in expected set {list(expect['canonical_year_in'])}")

    if "doi_registered" in expect:
        registration = result_dict.get("doi_registration")
        if not isinstance(registration, dict):
            failures.append("doi_registration missing while doi_registered expectation is set")
        elif registration.get("registered") is None:
            skips.append("doi registry unavailable; doi_registered check inconclusive")
        elif bool(registration.get("registered")) != bool(expect["doi_registered"]):
            failures.append(
                f"doi_registered {registration.get('registered')!r} != expected {expect['doi_registered']!r}"
            )

    if failures:
        return "fail", failures
    if skips:
        return "skip", skips
    return "pass", []


def run_canary(dataset_path: str, source_names: List[str], mailto: str) -> Dict[str, Any]:
    """Run every golden case against live sources and return the JSON report."""

    cases = load_dataset(dataset_path)
    source = build_live_metadata_source(source_names, mailto=mailto)
    doi_registry = build_doi_registry_probe()

    rows: List[Dict[str, Any]] = []
    for case in cases:
        candidate = parse_citation(**case["fields"])
        started = time.monotonic()
        result_dict = verify_citation(candidate, source, doi_registry=doi_registry).to_dict()
        elapsed = time.monotonic() - started
        status, reasons = evaluate_case(result_dict, case["expect"])
        rows.append(
            {
                "id": case["id"],
                "status": status,
                "verdict": result_dict.get("verdict"),
                "reasons": reasons,
                "elapsed_s": round(elapsed, 2),
            }
        )

    summary = {
        "pass": sum(1 for row in rows if row["status"] == "pass"),
        "fail": sum(1 for row in rows if row["status"] == "fail"),
        "skip": sum(1 for row in rows if row["status"] == "skip"),
    }
    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dataset": dataset_path,
        "sources": list(source_names),
        "summary": summary,
        "cases": rows,
    }


def _markdown_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render the JSON report as a Markdown summary for issue bodies."""

    summary = report["summary"]
    lines = [
        "# Canary golden-case report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Dataset: `{report['dataset']}`",
        f"- Sources: {', '.join(report['sources'])}",
        f"- Summary: {summary['pass']} pass / {summary['fail']} fail / {summary['skip']} skip",
        "",
        "| Case | Status | Verdict | Elapsed (s) | Reasons |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["cases"]:
        reasons = _markdown_cell("; ".join(row["reasons"])) if row["reasons"] else ""
        lines.append(
            f"| {row['id']} | {row['status']} | {row['verdict']} | {row['elapsed_s']} | {reasons} |"
        )

    failing = [row for row in report["cases"] if row["status"] == "fail"]
    if failing:
        lines.extend(["", "## Failing cases", ""])
        for row in failing:
            lines.append(f"- **{row['id']}** (verdict `{row['verdict']}`):")
            for reason in row["reasons"]:
                lines.append(f"  - {reason}")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the live golden-case canary against scholarly sources.")
    parser.add_argument("--dataset", default=DEFAULT_DATASET, help="Path to the golden dataset JSON.")
    parser.add_argument(
        "--sources",
        default=DEFAULT_SOURCES,
        help="Comma-separated live sources to check (default: openalex,crossref,arxiv).",
    )
    parser.add_argument("--report-md", help="Optional path for a Markdown summary of the run.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Accepted for interface symmetry; the JSON report is always printed to stdout.",
    )
    parser.add_argument("--min-pass", type=int, default=1, help="Minimum passing cases required for a healthy run.")
    parser.add_argument(
        "--max-skip-fraction",
        type=float,
        default=0.8,
        help="Fail source-health coverage when a larger fraction of cases is skipped.",
    )
    args = parser.parse_args()

    source_names = [name.strip() for name in args.sources.split(",") if name.strip()]
    mailto = os.environ.get("CITEGUARD_MAILTO", DEFAULT_MAILTO)
    if not mailto or mailto == DEFAULT_MAILTO:
        parser.error("Set CITEGUARD_MAILTO to a real contact email before running the live canary.")

    report = run_canary(args.dataset, source_names, mailto)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    if args.report_md:
        report_path = Path(args.report_md)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(render_markdown(report), encoding="utf-8")

    total = sum(report["summary"].values())
    skip_fraction = report["summary"]["skip"] / total if total else 1.0
    coverage_failed = report["summary"]["pass"] < args.min_pass or skip_fraction > args.max_skip_fraction
    return 1 if report["summary"]["fail"] or coverage_failed else 0


if __name__ == "__main__":
    sys.exit(main())
