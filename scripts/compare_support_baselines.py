#!/usr/bin/env python3
"""Compare deterministic support-eval baselines in one reproducible report."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from _bootstrap import ensure_project_root

ensure_project_root()

from citeguard.benchmark.experiments import write_experiment_artifacts
from citeguard.runtime import build_configured_support_backend
from citeguard.verifiers import HeuristicSupportBackend
from citeguard.verification.support_eval import (
    ALLOWED_SPLITS,
    compute_support_label_sidecar_gate,
    compute_support_quality_gate,
    filter_support_cases_by_split,
    load_support_label_cases,
    load_support_eval,
    run_support_eval_fixture_report,
    run_support_eval_report,
    validate_support_label_sidecar,
)


def _parse_language_threshold(value: str) -> tuple[str, int]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expected LANG=N, for example zh=5")
    language, raw_threshold = value.split("=", 1)
    language = language.strip().lower()
    if not language:
        raise argparse.ArgumentTypeError("language code is required before '='")
    try:
        threshold = int(raw_threshold)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("threshold must be a non-negative integer") from exc
    if threshold < 0:
        raise argparse.ArgumentTypeError("threshold must be a non-negative integer")
    return language, threshold


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare support-eval baselines and quality gates in a reproducible JSON table."
    )
    parser.add_argument("--dataset", default="data/eval/support_eval.json")
    parser.add_argument(
        "--split",
        choices=sorted(ALLOWED_SPLITS),
        default="test",
        help="Benchmark split to compare. Defaults to the release-oriented test split.",
    )
    parser.add_argument(
        "--backend",
        action="append",
        choices=["fixture", "heuristic", "production"],
        help="Backend to include; repeat for multiple. Defaults to fixture and heuristic.",
    )
    parser.add_argument(
        "--label-sidecar",
        default="data/eval/support_eval_label_sidecar.json",
        help="Optional label provenance sidecar. Defaults to the in-repo sidecar.",
    )
    parser.add_argument("--min-sidecar-coverage", type=float, default=1.0)
    parser.add_argument("--min-human-reviewed", type=int, default=0)
    parser.add_argument("--min-high-risk-reviewed", type=int, default=0)
    parser.add_argument(
        "--min-high-risk-reviewed-by-language",
        action="append",
        default=[],
        metavar="LANG=N",
        type=_parse_language_threshold,
        help="Minimum required human-reviewed high-risk labels for one language; repeat for multiple languages.",
    )
    parser.add_argument("--min-dual-annotated", type=int, default=0)
    parser.add_argument("--max-unresolved-disagreements", type=int, default=0)
    parser.add_argument("--min-raw-dual-agreement-rate", type=float, default=None)
    parser.add_argument("--max-supported-disagreements", type=int, default=None)
    parser.add_argument("--max-false-support-rate", type=float, default=0.0)
    parser.add_argument("--max-false-support-count", type=int, default=0)
    parser.add_argument("--max-weak-false-support-count", type=int, default=0)
    parser.add_argument("--min-supported-precision", type=float, default=1.0)
    parser.add_argument("--min-contradiction-recall", type=float, default=1.0)
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="Exit non-zero if any included backend or sidecar quality gate fails.",
    )
    parser.add_argument("--output-dir", help="Optional directory for standardized experiment artifacts.")
    parser.add_argument("--run-id", help="Optional stable run id for the experiment artifact folder.")
    args = parser.parse_args(argv)
    min_high_risk_reviewed_by_language: Dict[str, int] = {}
    for language, threshold in args.min_high_risk_reviewed_by_language:
        if language in min_high_risk_reviewed_by_language:
            parser.error(f"--min-high-risk-reviewed-by-language was provided more than once for {language!r}")
        min_high_risk_reviewed_by_language[language] = threshold

    backend_names = args.backend or ["fixture", "heuristic"]
    cases = load_support_eval(args.dataset)
    cases = filter_support_cases_by_split(cases, args.split)
    result: Dict[str, Any] = {
        "dataset": args.dataset,
        "split": args.split,
        "case_count": len(cases),
        "backends": [],
        "comparison": [],
    }

    for backend_name in backend_names:
        report = _run_backend(backend_name, cases)
        gate = compute_support_quality_gate(
            report,
            max_false_support_rate=args.max_false_support_rate,
            max_false_support_count=args.max_false_support_count,
            max_weak_false_support_count=args.max_weak_false_support_count,
            min_supported_precision=args.min_supported_precision,
            min_contradiction_recall=args.min_contradiction_recall,
        )
        result["backends"].append(
            {
                "name": backend_name,
                "report": report,
                "quality_gate": gate,
            }
        )
        result["comparison"].append(_comparison_row(backend_name, report, gate))

    if args.label_sidecar:
        with open(args.label_sidecar, encoding="utf-8") as handle:
            sidecar_data = json.load(handle)
        all_cases = load_support_label_cases(args.dataset)
        sidecar_summary = validate_support_label_sidecar(sidecar_data, all_cases)
        result["label_sidecar"] = sidecar_summary
        result["label_sidecar_gate"] = compute_support_label_sidecar_gate(
            sidecar_summary,
            min_coverage=args.min_sidecar_coverage,
            min_human_reviewed=args.min_human_reviewed,
            min_high_risk_reviewed=args.min_high_risk_reviewed,
            min_high_risk_reviewed_by_language=min_high_risk_reviewed_by_language,
            min_dual_annotated=args.min_dual_annotated,
            max_unresolved_disagreements=args.max_unresolved_disagreements,
            min_raw_dual_agreement_rate=args.min_raw_dual_agreement_rate,
            max_supported_disagreements=args.max_supported_disagreements,
        )

    result["quality_gates_ok"] = _all_gates_ok(result)
    if args.output_dir:
        result["experiment_artifact"] = write_experiment_artifacts(
            "support_baseline_comparison",
            result,
            {
                "script": "scripts/compare_support_baselines.py",
                "dataset": args.dataset,
                "split": args.split,
                "backends": backend_names,
                "label_sidecar": args.label_sidecar or "",
                "fail_on_gate": args.fail_on_gate,
                "thresholds": {
                    "max_false_support_rate": args.max_false_support_rate,
                    "max_false_support_count": args.max_false_support_count,
                    "max_weak_false_support_count": args.max_weak_false_support_count,
                    "min_supported_precision": args.min_supported_precision,
                    "min_contradiction_recall": args.min_contradiction_recall,
                    "min_sidecar_coverage": args.min_sidecar_coverage,
                    "min_human_reviewed": args.min_human_reviewed,
                    "min_high_risk_reviewed": args.min_high_risk_reviewed,
                    "min_high_risk_reviewed_by_language": min_high_risk_reviewed_by_language,
                    "min_dual_annotated": args.min_dual_annotated,
                    "max_unresolved_disagreements": args.max_unresolved_disagreements,
                    "min_raw_dual_agreement_rate": args.min_raw_dual_agreement_rate,
                    "max_supported_disagreements": args.max_supported_disagreements,
                },
                "case_count": len(cases),
            },
            output_dir=args.output_dir,
            run_id=args.run_id,
        )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if args.fail_on_gate and not result["quality_gates_ok"] else 0


def _run_backend(backend_name: str, cases) -> Dict[str, Any]:
    if backend_name == "fixture":
        return run_support_eval_fixture_report(cases)
    backend = HeuristicSupportBackend() if backend_name == "heuristic" else build_configured_support_backend()
    return run_support_eval_report(cases, backend)


def _comparison_row(backend_name: str, report: Dict[str, Any], gate: Dict[str, Any]) -> Dict[str, Any]:
    overall = report.get("overall", {})
    counts = report.get("error_bucket_counts", {})
    false_support_analysis = report.get("false_support_analysis", {})
    diagnostics = report.get("diagnostics", {})
    review_queue = list(report.get("review_queue", []))
    review_queue_summary = report.get("review_queue_summary", {})
    return {
        "backend": backend_name,
        "quality_gate_ok": bool(gate.get("ok")),
        "accuracy": overall.get("accuracy", 0.0),
        "supported_precision": overall.get("supported_precision", 0.0),
        "supported_recall": overall.get("supported_recall", 0.0),
        "supported_f1": overall.get("supported_f1", 0.0),
        "abstention_rate": overall.get("abstention_rate", 0.0),
        "false_support_rate": overall.get("false_support_rate", 0.0),
        "contradiction_recall": overall.get("contradiction_recall", 0.0),
        "false_support_count": counts.get("false_support", 0),
        "weak_false_support_count": counts.get("weak_false_support", 0),
        "total_overcall_count": false_support_analysis.get("total_overcall_count", 0),
        "high_risk_false_support_case_ids": list(false_support_analysis.get("high_risk_case_ids", [])),
        "false_support_risk_slices": list(false_support_analysis.get("risk_slices", [])),
        "top_false_support_risk_slice": false_support_analysis.get("top_risk_slice"),
        "review_queue_case_ids": [
            str(item.get("case_id", ""))
            for item in review_queue[:10]
            if item.get("case_id")
        ],
        "critical_review_case_ids": [
            str(item.get("case_id", ""))
            for item in review_queue
            if item.get("severity") == "critical" and item.get("case_id")
        ],
        "review_queue_by_severity": dict(review_queue_summary.get("by_severity", {}))
        if isinstance(review_queue_summary, dict)
        else {},
        "review_queue_by_recommended_action": dict(review_queue_summary.get("by_recommended_action", {}))
        if isinstance(review_queue_summary, dict)
        else {},
        "missed_contradiction_count": counts.get("missed_contradiction", 0),
        "heuristic_limited": bool(diagnostics.get("heuristic_limited")),
        "warnings": list(diagnostics.get("warnings", [])),
    }


def _all_gates_ok(result: Dict[str, Any]) -> bool:
    if result.get("label_sidecar_gate") and not result["label_sidecar_gate"].get("ok"):
        return False
    return all(item.get("quality_gate", {}).get("ok") for item in result.get("backends", []))


if __name__ == "__main__":
    sys.exit(main())
