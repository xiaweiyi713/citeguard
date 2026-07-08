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
    compute_support_release_summary,
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


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("expected a non-negative integer")
    return parsed


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
        "--review-queue-limit",
        type=_non_negative_int,
        default=None,
        help=(
            "When used with --review-queue-only, return only the first N risk-ordered "
            "review_queue rows while preserving full queue counts."
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
            "Set to 0 when a human-reviewed benchmark slice exists and supported-label disagreements must block release."
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
    if wants_report and isinstance(result, dict):
        result["release_summary"] = compute_support_release_summary(result, result.get("quality_gate"))
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
    acceptance_guard = result.get("acceptance_guard", {})
    acceptance_slices = result.get("acceptance_slices", [])
    abstention_analysis = result.get("abstention_analysis", {})
    release_blocker_summary = result.get("release_blocker_summary", {})
    support_set_policy = result.get("support_set_policy", {})
    support_set_overall = support_set_policy.get("overall", {}) if isinstance(support_set_policy, dict) else {}
    review_queue = list(result.get("review_queue", []))
    review_queue_limit = getattr(args, "review_queue_limit", None)
    returned_review_queue = review_queue
    if review_queue_limit is not None:
        returned_review_queue = review_queue[:review_queue_limit]
    payload: Dict[str, object] = {
        "dataset": args.dataset,
        "split": args.split or "all",
        "backend": args.backend,
        "review_queue_limit": review_queue_limit,
        "case_count": dataset.get("n") if isinstance(dataset, dict) else None,
        "overall": {
            "accuracy": overall.get("accuracy") if isinstance(overall, dict) else None,
            "supported_precision": overall.get("supported_precision") if isinstance(overall, dict) else None,
            "macro_precision": overall.get("macro_precision") if isinstance(overall, dict) else None,
            "macro_recall": overall.get("macro_recall") if isinstance(overall, dict) else None,
            "macro_f1": overall.get("macro_f1") if isinstance(overall, dict) else None,
            "weighted_precision": overall.get("weighted_precision") if isinstance(overall, dict) else None,
            "weighted_recall": overall.get("weighted_recall") if isinstance(overall, dict) else None,
            "weighted_f1": overall.get("weighted_f1") if isinstance(overall, dict) else None,
            "false_support_rate": overall.get("false_support_rate") if isinstance(overall, dict) else None,
            "support_overcall_rate": overall.get("support_overcall_rate") if isinstance(overall, dict) else None,
            "support_overcall_count": overall.get("support_overcall_count") if isinstance(overall, dict) else None,
            "abstention_rate": overall.get("abstention_rate") if isinstance(overall, dict) else None,
            "contradiction_recall": overall.get("contradiction_recall") if isinstance(overall, dict) else None,
        },
        "review_queue_summary": result.get("review_queue_summary", {}),
        "release_blocker_summary": release_blocker_summary if isinstance(release_blocker_summary, dict) else {},
        "release_summary": result.get("release_summary", {}),
        "review_queue": returned_review_queue,
    }
    if review_queue_limit is not None:
        payload["review_queue_filtered"] = {
            "limited": True,
            "limit": review_queue_limit,
            "returned": len(returned_review_queue),
            "original_count": len(review_queue),
            "omitted": max(0, len(review_queue) - len(returned_review_queue)),
            "returned_case_ids": [
                str(item.get("case_id", ""))
                for item in returned_review_queue
                if isinstance(item, dict) and item.get("case_id")
            ],
            "omitted_case_ids": [
                str(item.get("case_id", ""))
                for item in review_queue[review_queue_limit:]
                if isinstance(item, dict) and item.get("case_id")
            ],
            "policy": "review_queue_summary_and_quality_gate_counts_remain_full_queue",
        }
    if isinstance(false_support_analysis, dict):
        payload["false_support_analysis"] = {
            "false_support_count": false_support_analysis.get("false_support_count", 0),
            "weak_false_support_count": false_support_analysis.get("weak_false_support_count", 0),
            "total_overcall_count": false_support_analysis.get("total_overcall_count", 0),
            "case_ids": list(false_support_analysis.get("case_ids", [])),
            "false_support_case_ids": list(false_support_analysis.get("false_support_case_ids", [])),
            "weak_false_support_case_ids": list(false_support_analysis.get("weak_false_support_case_ids", [])),
            "high_risk_case_ids": list(false_support_analysis.get("high_risk_case_ids", [])),
            "high_risk_overcall_case_ids": list(
                false_support_analysis.get("high_risk_overcall_case_ids", [])
            ),
            "acceptance_guard": false_support_analysis.get("acceptance_guard", {}),
            "review_plan": false_support_analysis.get("review_plan", {}),
            "risk_slices": list(false_support_analysis.get("risk_slices", [])),
            "top_risk_slice": false_support_analysis.get("top_risk_slice"),
        }
    if isinstance(acceptance_guard, dict):
        payload["acceptance_guard"] = {
            "ok_to_accept_supported": acceptance_guard.get("ok_to_accept_supported"),
            "block_acceptance_count": acceptance_guard.get("block_acceptance_count", 0),
            "block_acceptance_case_ids": list(acceptance_guard.get("block_acceptance_case_ids", [])),
            "review_before_accepting_count": acceptance_guard.get("review_before_accepting_count", 0),
            "review_before_accepting_case_ids": list(
                acceptance_guard.get("review_before_accepting_case_ids", [])
            ),
            "next_action": acceptance_guard.get("next_action"),
            "policy": acceptance_guard.get("policy"),
        }
    if isinstance(acceptance_slices, list):
        payload["acceptance_slices"] = list(acceptance_slices)
    if isinstance(abstention_analysis, dict):
        payload["abstention_analysis"] = {
            "incorrect_abstention_count": abstention_analysis.get("incorrect_abstention_count", 0),
            "correct_abstention_count": abstention_analysis.get("correct_abstention_count", 0),
            "total_abstention_count": abstention_analysis.get("total_abstention_count", 0),
            "incorrect_case_ids": list(abstention_analysis.get("incorrect_case_ids", [])),
            "correct_case_ids": list(abstention_analysis.get("correct_case_ids", [])),
            "review_case_ids": list(abstention_analysis.get("review_case_ids", [])),
            "by_case_type": abstention_analysis.get("by_case_type", {}),
            "by_evidence_scope": abstention_analysis.get("by_evidence_scope", {}),
        }
    if isinstance(quality_gate, dict):
        payload["quality_gate"] = {
            "ok": quality_gate.get("ok"),
            "review_queue_case_ids": list(quality_gate.get("review_queue_case_ids", [])),
            "critical_review_case_ids": list(quality_gate.get("critical_review_case_ids", [])),
            "release_blocker_summary": quality_gate.get("release_blocker_summary", {}),
            "review_queue_summary": quality_gate.get("review_queue_summary", {}),
            "acceptance_slices": list(quality_gate.get("acceptance_slices", [])),
            "failures": list(quality_gate.get("failures", [])),
            "warnings": list(quality_gate.get("warnings", [])),
        }
    if isinstance(label_sidecar_gate, dict):
        label_metrics = label_sidecar_gate.get("metrics", {})
        compact_label_metrics = _compact_label_sidecar_metrics(label_metrics)
        payload["label_sidecar_gate"] = {
            "ok": label_sidecar_gate.get("ok"),
            "failures": list(label_sidecar_gate.get("failures", [])),
            "warnings": list(label_sidecar_gate.get("warnings", [])),
            "metrics": compact_label_metrics,
        }
        payload["label_maturity"] = compact_label_metrics
    if isinstance(support_set_policy, dict) and support_set_overall:
        support_set_dataset = support_set_policy.get("dataset", {})
        support_set_cases = support_set_policy.get("cases", [])
        case_ids = [
            case.get("case_id")
            for case in support_set_cases
            if isinstance(case, dict) and case.get("case_id")
        ] if isinstance(support_set_cases, list) else []
        payload["support_set_policy"] = {
            "accuracy": support_set_overall.get("accuracy"),
            "contradiction_recall": support_set_overall.get("contradiction_recall"),
            "false_support_rate": support_set_overall.get("false_support_rate"),
            "case_count": support_set_dataset.get("n") if isinstance(support_set_dataset, dict) else None,
            "case_types": support_set_dataset.get("case_types", {}) if isinstance(support_set_dataset, dict) else {},
            "languages": support_set_dataset.get("languages", {}) if isinstance(support_set_dataset, dict) else {},
            "splits": support_set_dataset.get("splits", {}) if isinstance(support_set_dataset, dict) else {},
            "case_ids": case_ids,
        }
    if "experiment_artifact" in result:
        payload["experiment_artifact"] = result["experiment_artifact"]
    return payload


def _compact_label_sidecar_metrics(metrics: object) -> Dict[str, object]:
    """Return the sidecar maturity fields agents need for benchmark triage."""

    if not isinstance(metrics, dict):
        return {}
    return {
        "coverage": metrics.get("coverage"),
        "human_reviewed": metrics.get("human_reviewed"),
        "high_risk_case_count": metrics.get("high_risk_case_count"),
        "high_risk_reviewed": metrics.get("high_risk_reviewed"),
        "high_risk_unreviewed": metrics.get("high_risk_unreviewed"),
        "high_risk_case_count_by_language": metrics.get("high_risk_case_count_by_language", {}),
        "high_risk_reviewed_by_language": metrics.get("high_risk_reviewed_by_language", {}),
        "high_risk_unreviewed_by_language": metrics.get("high_risk_unreviewed_by_language", {}),
        "high_risk_case_count_by_language_case_type": metrics.get(
            "high_risk_case_count_by_language_case_type", {}
        ),
        "high_risk_reviewed_by_language_case_type": metrics.get("high_risk_reviewed_by_language_case_type", {}),
        "high_risk_unreviewed_by_language_case_type": metrics.get(
            "high_risk_unreviewed_by_language_case_type", {}
        ),
        "full_text_required_unreviewed": metrics.get("full_text_required_unreviewed"),
        "full_text_required_unreviewed_case_ids": list(
            metrics.get("full_text_required_unreviewed_case_ids", []) or []
        ),
        "policy_boundary_unreviewed": metrics.get("policy_boundary_unreviewed"),
        "policy_boundary_unreviewed_case_ids": list(
            metrics.get("policy_boundary_unreviewed_case_ids", []) or []
        ),
        "dual_annotated": metrics.get("dual_annotated"),
        "raw_dual_agreement_rate": metrics.get("raw_dual_agreement_rate"),
        "unresolved_disagreements": metrics.get("unresolved_disagreements"),
        "unresolved_disagreement_case_ids": list(
            metrics.get("unresolved_disagreement_case_ids", []) or []
        ),
        "supported_disagreements": metrics.get("supported_disagreements"),
        "supported_disagreement_case_ids": list(
            metrics.get("supported_disagreement_case_ids", []) or []
        ),
        "label_source_counts": metrics.get("label_source_counts", {}),
        "reviewed_by_label_source": metrics.get("reviewed_by_label_source", {}),
        "unreviewed_by_label_source": metrics.get("unreviewed_by_label_source", {}),
        "reviewed_source_locator_count": metrics.get("reviewed_source_locator_count"),
        "published_benchmark_source_locator_count": metrics.get(
            "published_benchmark_source_locator_count"
        ),
        "sidecar_provenance_complete_count": metrics.get("sidecar_provenance_complete_count"),
        "sidecar_provenance_complete_fraction": metrics.get("sidecar_provenance_complete_fraction"),
        "sidecar_provenance_missing_count": metrics.get("sidecar_provenance_missing_count"),
        "sidecar_provenance_missing_case_ids": list(
            metrics.get("sidecar_provenance_missing_case_ids", []) or []
        ),
        "sidecar_provenance_missing_case_ids_by_field": metrics.get(
            "sidecar_provenance_missing_case_ids_by_field", {}
        ),
        "sidecar_provenance_field_present_counts": metrics.get(
            "sidecar_provenance_field_present_counts", {}
        ),
        "dataset_cases": metrics.get("dataset_cases"),
        "sidecar_cases": metrics.get("sidecar_cases"),
    }


if __name__ == "__main__":
    main()
