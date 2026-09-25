#!/usr/bin/env python3
"""Run a reproducible claim-support verifier component ablation matrix."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, Optional

from _bootstrap import ensure_project_root

ensure_project_root()

from citeguard.benchmark.experiments import write_experiment_artifacts
from citeguard.benchmark.support_ablations import (
    SUPPORT_ABLATION_NAMES,
    run_support_ablation_matrix,
)
from citeguard.verification.support_eval import (
    ALLOWED_SPLITS,
    filter_support_cases_by_split,
    load_support_eval,
    load_support_label_cases,
    validate_support_label_sidecar,
)
from citeguard.verifiers import DEFAULT_NLI_MODEL, DEFAULT_RERANKER_MODEL


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run false-support-sensitive verifier component ablations on one locked support-eval split."
    )
    parser.add_argument("--dataset", default="data/eval/support_eval.json")
    parser.add_argument("--label-sidecar", default="data/eval/support_eval_label_sidecar.json")
    parser.add_argument("--split", choices=sorted(ALLOWED_SPLITS), default="test")
    parser.add_argument(
        "--ablation",
        action="append",
        choices=list(SUPPORT_ABLATION_NAMES),
        help="Ablation to run; repeat for multiple. Defaults to the complete six-row verifier matrix.",
    )
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--nli-model", default=DEFAULT_NLI_MODEL)
    parser.add_argument("--heuristic-threshold", type=float, default=0.16)
    parser.add_argument("--reranker-threshold", type=float, default=0.45)
    parser.add_argument("--nli-threshold", type=float, default=0.50)
    parser.add_argument("--nli-margin", type=float, default=0.03)
    parser.add_argument("--max-false-support-rate", type=float, default=0.0)
    parser.add_argument("--max-false-support-count", type=int, default=0)
    parser.add_argument("--max-weak-false-support-count", type=int, default=0)
    parser.add_argument("--min-supported-precision", type=float, default=1.0)
    parser.add_argument("--min-contradiction-recall", type=float, default=1.0)
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Report component availability and planned rows without loading models or scoring cases.",
    )
    parser.add_argument(
        "--fail-on-unavailable",
        action="store_true",
        help="Exit non-zero when any requested row is unavailable, has a model error, or is only planned.",
    )
    parser.add_argument(
        "--fail-on-quality-gate",
        action="store_true",
        help="Exit non-zero when any completed row fails the strict false-support quality gate.",
    )
    parser.add_argument("--output-dir", help="Optional directory for standardized experiment artifacts.")
    parser.add_argument("--run-id", help="Optional stable run id for the experiment artifact folder.")
    args = parser.parse_args(argv)

    all_cases = load_support_eval(args.dataset)
    cases = filter_support_cases_by_split(all_cases, args.split)
    result = run_support_ablation_matrix(
        cases,
        args.ablation or SUPPORT_ABLATION_NAMES,
        reranker_model_name=args.reranker_model,
        nli_model_name=args.nli_model,
        heuristic_threshold=args.heuristic_threshold,
        reranker_threshold=args.reranker_threshold,
        nli_threshold=args.nli_threshold,
        nli_margin=args.nli_margin,
        quality_thresholds={
            "max_false_support_rate": args.max_false_support_rate,
            "max_false_support_count": args.max_false_support_count,
            "max_weak_false_support_count": args.max_weak_false_support_count,
            "min_supported_precision": args.min_supported_precision,
            "min_contradiction_recall": args.min_contradiction_recall,
        },
        plan_only=args.plan_only,
    )
    result.update(
        {
            "dataset": args.dataset,
            "split": args.split,
            "case_count": len(cases),
        }
    )
    _add_label_provenance(result, args.dataset, args.label_sidecar)

    config: Dict[str, Any] = {
        "script": "scripts/run_support_ablations.py",
        "dataset": args.dataset,
        "label_sidecar": args.label_sidecar,
        "split": args.split,
        "ablations": list(result["requested_ablations"]),
        "plan_only": args.plan_only,
        "models": {
            "reranker": args.reranker_model,
            "nli": args.nli_model,
        },
        "thresholds": {
            "heuristic": args.heuristic_threshold,
            "reranker": args.reranker_threshold,
            "nli": args.nli_threshold,
            "nli_margin": args.nli_margin,
            **dict(result["quality_thresholds"]),
        },
        "case_count": len(cases),
    }
    if args.output_dir:
        result["experiment_artifact"] = write_experiment_artifacts(
            "support_verifier_ablation",
            result,
            config,
            output_dir=args.output_dir,
            run_id=args.run_id,
        )

    print(json.dumps(result, indent=2, ensure_ascii=False))
    incomplete = not result["matrix_complete"]
    quality_failed = bool(result["completed_count"]) and not result["quality_gates_ok"]
    if args.fail_on_unavailable and incomplete:
        return 1
    if args.fail_on_quality_gate and quality_failed:
        return 1
    return 0


def _add_label_provenance(result: Dict[str, Any], dataset: str, label_sidecar: str) -> None:
    if not label_sidecar:
        result["label_provenance"] = {
            "available": False,
            "human_reviewed": 0,
            "dual_annotated": 0,
            "published_benchmark": 0,
            "benchmark_claim_safe": False,
        }
        return
    with open(label_sidecar, encoding="utf-8") as handle:
        sidecar = json.load(handle)
    summary = validate_support_label_sidecar(sidecar, load_support_label_cases(dataset))
    maturity = summary.get("label_maturity", {})
    result["label_provenance"] = {
        "available": True,
        "sidecar": label_sidecar,
        "coverage": summary.get("coverage"),
        "human_reviewed": int(summary.get("human_reviewed", 0) or 0),
        "dual_annotated": int(maturity.get("dual_annotated_count", 0) or 0),
        "published_benchmark": int(maturity.get("published_benchmark_count", 0) or 0),
        "unresolved_disagreements": int(maturity.get("unresolved_disagreement_count", 0) or 0),
        "benchmark_claim_safe": bool(
            int(summary.get("human_reviewed", 0) or 0) > 0
            and int(maturity.get("dual_annotated_count", 0) or 0) > 0
            and int(maturity.get("published_benchmark_count", 0) or 0) > 0
            and int(maturity.get("unresolved_disagreement_count", 0) or 0) == 0
        ),
        "policy": "ablation_metrics_do_not_upgrade_synthetic_labels_into_human_reviewed_benchmark_evidence",
    }


if __name__ == "__main__":
    sys.exit(main())
