"""Run the claim-support evaluation with deterministic defaults."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict

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
    load_support_set_eval,
    run_support_eval,
    run_support_eval_fixture,
    run_support_eval_fixture_report,
    run_support_eval_report,
    run_support_set_policy_fixture_report,
    validate_support_label_sidecar,
    validate_support_eval_dataset,
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


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate CiteGuard claim-support assessment.")
    parser.add_argument("--dataset", default="data/eval/support_eval.json")
    parser.add_argument(
        "--report",
        action="store_true",
        help="Include breakdowns by case_type and evidence_scope plus per-case rows.",
    )
    parser.add_argument(
        "--review-queue-only",
        action="store_true",
        help=(
            "Print only the support-failure review queue and gate summaries. "
            "This implies --report and is useful for agent triage."
        ),
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate dataset schema, provenance, and coverage without loading support models.",
    )
    parser.add_argument(
        "--split",
        choices=sorted(ALLOWED_SPLITS),
        help="Evaluate only one benchmark split, e.g. dev for calibration or test for final reporting.",
    )
    parser.add_argument(
        "--label-sidecar",
        help="Optional JSON sidecar with annotator/adjudication metadata for the support labels.",
    )
    parser.add_argument(
        "--backend",
        choices=["fixture", "heuristic", "production"],
        default="fixture",
        help=(
            "Evaluation backend. fixture is deterministic/offline and validates report plumbing; "
            "heuristic runs the local lexical baseline; production loads configured model backends."
        ),
    )
    parser.add_argument(
        "--quality-gate",
        action="store_true",
        help=(
            "Attach conservative support-quality gates to the report and exit non-zero on failure. "
            "This implies --report because gates need error buckets and grouped metrics."
        ),
    )
    parser.add_argument("--max-false-support-rate", type=float, default=0.0)
    parser.add_argument("--max-false-support-count", type=int, default=0)
    parser.add_argument("--max-weak-false-support-count", type=int, default=0)
    parser.add_argument("--min-supported-precision", type=float, default=1.0)
    parser.add_argument("--min-contradiction-recall", type=float, default=1.0)
    parser.add_argument(
        "--min-sidecar-coverage",
        type=float,
        default=1.0,
        help="Minimum required label-sidecar coverage when --label-sidecar is provided.",
    )
    parser.add_argument(
        "--min-human-reviewed",
        type=int,
        default=0,
        help="Minimum required human-reviewed labels when --label-sidecar is provided.",
    )
    parser.add_argument(
        "--min-high-risk-reviewed",
        type=int,
        default=0,
        help=(
            "Minimum required human-reviewed high-risk labels when --label-sidecar is provided. "
            "High-risk cases include contradiction, hard_negative, full_text_required, and contradiction_set."
        ),
    )
    parser.add_argument(
        "--min-high-risk-reviewed-by-language",
        action="append",
        default=[],
        metavar="LANG=N",
        type=_parse_language_threshold,
        help=(
            "Minimum required human-reviewed high-risk labels for one language, e.g. zh=5. "
            "Repeat for multiple languages."
        ),
    )
    parser.add_argument(
        "--min-dual-annotated",
        type=int,
        default=0,
        help="Minimum required dual-annotated labels when --label-sidecar is provided.",
    )
    parser.add_argument(
        "--max-unresolved-disagreements",
        type=int,
        default=0,
        help="Maximum unresolved label disagreements allowed when --label-sidecar is provided.",
    )
    parser.add_argument(
        "--min-raw-dual-agreement-rate",
        type=float,
        default=None,
        help="Minimum raw agreement rate among dual-annotated labels when --label-sidecar is provided.",
    )
    parser.add_argument(
        "--max-supported-disagreements",
        type=int,
        default=None,
        help=(
            "Maximum dual-annotation disagreements involving a supported label when --label-sidecar is provided. "
            "Use 0 for release-grade human-reviewed benchmarks."
        ),
    )
    parser.add_argument(
        "--output-dir",
        help="Optional directory for standardized experiment artifacts, e.g. experiments/.",
    )
    parser.add_argument("--run-id", help="Optional stable run id for the experiment artifact folder.")
    args = parser.parse_args()
    min_high_risk_reviewed_by_language: Dict[str, int] = {}
    for language, threshold in args.min_high_risk_reviewed_by_language:
        if language in min_high_risk_reviewed_by_language:
            parser.error(f"--min-high-risk-reviewed-by-language was provided more than once for {language!r}")
        min_high_risk_reviewed_by_language[language] = threshold
    sidecar_summary = None
    sidecar_data = None
    if args.label_sidecar:
        with open(args.label_sidecar, encoding="utf-8") as handle:
            sidecar_data = json.load(handle)
    if args.validate_only:
        with open(args.dataset, encoding="utf-8") as handle:
            dataset = json.load(handle)
        validation = validate_support_eval_dataset(dataset)
        if sidecar_data is not None:
            cases = load_support_label_cases(args.dataset)
            validation["label_sidecar"] = validate_support_label_sidecar(sidecar_data, cases)
            validation["label_sidecar_gate"] = compute_support_label_sidecar_gate(
                validation["label_sidecar"],
                min_coverage=args.min_sidecar_coverage,
                min_human_reviewed=args.min_human_reviewed,
                min_high_risk_reviewed=args.min_high_risk_reviewed,
                min_high_risk_reviewed_by_language=min_high_risk_reviewed_by_language,
                min_dual_annotated=args.min_dual_annotated,
                max_unresolved_disagreements=args.max_unresolved_disagreements,
                min_raw_dual_agreement_rate=args.min_raw_dual_agreement_rate,
                max_supported_disagreements=args.max_supported_disagreements,
            )
        print(json.dumps(validation, indent=2, ensure_ascii=False))
        if sidecar_data is not None and not validation["label_sidecar_gate"]["ok"]:
            sys.exit(1)
        return
    cases = load_support_eval(args.dataset)
    if sidecar_data is not None:
        sidecar_summary = validate_support_label_sidecar(sidecar_data, load_support_label_cases(args.dataset))
    if args.split:
        cases = filter_support_cases_by_split(cases, args.split)
    wants_report = args.report or args.quality_gate or args.review_queue_only
    if args.backend == "fixture":
        result = run_support_eval_fixture_report(cases) if wants_report else run_support_eval_fixture(cases)
    else:
        backend = HeuristicSupportBackend() if args.backend == "heuristic" else build_configured_support_backend()
        result = run_support_eval_report(cases, backend) if wants_report else run_support_eval(cases, backend)
    if wants_report and isinstance(result, dict):
        set_cases = load_support_set_eval(args.dataset)
        if args.split:
            set_cases = [case for case in set_cases if case.split == args.split]
        if set_cases:
            result["support_set_policy"] = run_support_set_policy_fixture_report(set_cases)
    if sidecar_summary is not None and isinstance(result, dict):
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
    if args.quality_gate and isinstance(result, dict):
        result["quality_gate"] = compute_support_quality_gate(
            result,
            max_false_support_rate=args.max_false_support_rate,
            max_false_support_count=args.max_false_support_count,
            max_weak_false_support_count=args.max_weak_false_support_count,
            min_supported_precision=args.min_supported_precision,
            min_contradiction_recall=args.min_contradiction_recall,
        )
    if args.output_dir and isinstance(result, dict):
        result["experiment_artifact"] = write_experiment_artifacts(
            "support_eval",
            result,
            {
                "script": "scripts/eval_support.py",
                "dataset": args.dataset,
                "split": args.split or "all",
                "backend": args.backend,
                "report": wants_report,
                "label_sidecar": args.label_sidecar or "",
                "quality_gate": args.quality_gate,
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
    output = _review_queue_only_payload(result, args) if args.review_queue_only and isinstance(result, dict) else result
    print(json.dumps(output, indent=2, ensure_ascii=False))
    if (
        sidecar_summary is not None
        and isinstance(result, dict)
        and not result["label_sidecar_gate"]["ok"]
    ):
        sys.exit(1)
    if args.quality_gate and isinstance(result, dict) and not result["quality_gate"]["ok"]:
        sys.exit(1)


def _review_queue_only_payload(result: Dict[str, object], args: argparse.Namespace) -> Dict[str, object]:
    dataset = result.get("dataset", {})
    overall = result.get("overall", {})
    quality_gate = result.get("quality_gate")
    label_sidecar_gate = result.get("label_sidecar_gate")
    false_support_analysis = result.get("false_support_analysis", {})
    support_set_policy = result.get("support_set_policy", {})
    support_set_overall = support_set_policy.get("overall", {}) if isinstance(support_set_policy, dict) else {}
    payload: Dict[str, object] = {
        "dataset": args.dataset,
        "split": args.split or "all",
        "backend": args.backend,
        "case_count": dataset.get("n") if isinstance(dataset, dict) else None,
        "overall": {
            "accuracy": overall.get("accuracy") if isinstance(overall, dict) else None,
            "supported_precision": overall.get("supported_precision") if isinstance(overall, dict) else None,
            "false_support_rate": overall.get("false_support_rate") if isinstance(overall, dict) else None,
            "contradiction_recall": overall.get("contradiction_recall") if isinstance(overall, dict) else None,
        },
        "review_queue_summary": result.get("review_queue_summary", {}),
        "review_queue": list(result.get("review_queue", [])),
    }
    if isinstance(false_support_analysis, dict):
        payload["false_support_analysis"] = {
            "false_support_count": false_support_analysis.get("false_support_count", 0),
            "weak_false_support_count": false_support_analysis.get("weak_false_support_count", 0),
            "total_overcall_count": false_support_analysis.get("total_overcall_count", 0),
            "case_ids": list(false_support_analysis.get("case_ids", [])),
            "high_risk_case_ids": list(false_support_analysis.get("high_risk_case_ids", [])),
            "risk_slices": list(false_support_analysis.get("risk_slices", [])),
            "top_risk_slice": false_support_analysis.get("top_risk_slice"),
        }
    if isinstance(quality_gate, dict):
        payload["quality_gate"] = {
            "ok": quality_gate.get("ok"),
            "review_queue_case_ids": list(quality_gate.get("review_queue_case_ids", [])),
            "critical_review_case_ids": list(quality_gate.get("critical_review_case_ids", [])),
            "review_queue_summary": quality_gate.get("review_queue_summary", {}),
            "failures": list(quality_gate.get("failures", [])),
            "warnings": list(quality_gate.get("warnings", [])),
        }
    if isinstance(label_sidecar_gate, dict):
        payload["label_sidecar_gate"] = {
            "ok": label_sidecar_gate.get("ok"),
            "failures": list(label_sidecar_gate.get("failures", [])),
            "warnings": list(label_sidecar_gate.get("warnings", [])),
        }
    if support_set_overall:
        payload["support_set_policy"] = {
            "accuracy": support_set_overall.get("accuracy"),
            "contradiction_recall": support_set_overall.get("contradiction_recall"),
            "false_support_rate": support_set_overall.get("false_support_rate"),
        }
    if "experiment_artifact" in result:
        payload["experiment_artifact"] = result["experiment_artifact"]
    return payload


if __name__ == "__main__":
    main()
