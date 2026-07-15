#!/usr/bin/env python3
"""Run the automated model-safety review used for software releases.

This review may authorize packaging and publishing the software. It never
turns synthetic labels into human-reviewed benchmark evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.runtime import build_configured_support_backend
from citeguard.verification.support_eval import (
    compute_support_quality_gate,
    filter_support_cases_by_split,
    load_support_eval,
    load_support_set_eval,
    run_support_eval_report,
    run_support_set_policy_fixture_report,
)


SCHEMA_VERSION = 1
REQUIRED_MODEL_REVIEWERS = {
    "transformers_nli",
    "sentence_transformer_reranker",
    "heuristic_support",
}
REVIEW_CONTRACT_FILES = (
    "pyproject.toml",
    "uv.lock",
    "citeguard/runtime.py",
    "citeguard/verifiers/support_backends.py",
    "citeguard/verification/support_patterns.py",
    "citeguard/verification/support_scoring.py",
    "citeguard/verification/support_eval_execution.py",
    "citeguard/verification/support_eval_metrics.py",
    "citeguard/verification/support_eval_review.py",
    "scripts/automated_release_review.py",
)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compute_review_contract_digest(project_root: Path) -> str:
    """Hash the implementation files whose behavior the review authorizes."""

    digest = hashlib.sha256()
    for relative_path in REVIEW_CONTRACT_FILES:
        path = project_root / relative_path
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _model_reviewer_rows(probe: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for component in probe.get("components", []):
        details = component.get("details", {})
        rows.append(
            {
                "id": component.get("backend", ""),
                "available": details.get("available", True) is not False
                and details.get("error_code") != "model_unavailable",
                "model_name": details.get("model_name", "built_in_lexical_policy"),
                "role": (
                    "entailment_and_contradiction"
                    if component.get("backend") == "transformers_nli"
                    else "semantic_relevance"
                    if component.get("backend") == "sentence_transformer_reranker"
                    else "lexical_anchor"
                ),
            }
        )
    return rows


def build_automated_review_report(
    *,
    project_root: Path,
    dataset: str,
    split: str = "test",
    backend: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute production-model and deterministic policy reviewers."""

    dataset_path = (project_root / dataset).resolve()
    cases = filter_support_cases_by_split(load_support_eval(str(dataset_path)), split)
    active_backend = backend or build_configured_support_backend()
    report = run_support_eval_report(cases, active_backend)
    quality_gate = compute_support_quality_gate(report)

    set_cases = [case for case in load_support_set_eval(str(dataset_path)) if case.split == split]
    support_set_report = run_support_set_policy_fixture_report(set_cases)
    support_set_metrics = support_set_report.get("overall", {})

    probe = active_backend.assess(
        "The evidence supports the claim.",
        "The evidence directly supports the claim.",
    )
    reviewer_rows = _model_reviewer_rows(probe.details)
    reviewer_ids = {str(row["id"]) for row in reviewer_rows}
    all_reviewers_available = (
        reviewer_ids == REQUIRED_MODEL_REVIEWERS
        and all(bool(row["available"]) for row in reviewer_rows)
    )
    support_set_ok = (
        bool(set_cases)
        and support_set_metrics.get("accuracy") == 1.0
        and support_set_metrics.get("false_support_rate") == 0.0
        and support_set_metrics.get("contradiction_recall") == 1.0
    )
    software_release_allowed = bool(quality_gate.get("ok")) and all_reviewers_available and support_set_ok

    return {
        "schema_version": SCHEMA_VERSION,
        "review_type": "automated_release_review",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": {
            "path": dataset,
            "sha256": _sha256_file(dataset_path),
            "split": split,
            "case_count": len(cases),
            "label_sources": sorted({case.label_source for case in cases}),
        },
        "implementation_digest": compute_review_contract_digest(project_root),
        "reviewers": {
            "model_components": reviewer_rows,
            "required_model_components": sorted(REQUIRED_MODEL_REVIEWERS),
            "all_required_available": all_reviewers_available,
            "policy_checkers": [
                "support_quality_gate",
                "support_set_aggregation_fixture",
                "scope_and_provenance_boundaries",
            ],
            "independence": "diverse_automated_signals_not_independent_human_reviewers",
        },
        "quality_gate": quality_gate,
        "support_set_policy": {
            "ok": support_set_ok,
            "case_count": len(set_cases),
            "accuracy": support_set_metrics.get("accuracy"),
            "false_support_rate": support_set_metrics.get("false_support_rate"),
            "contradiction_recall": support_set_metrics.get("contradiction_recall"),
        },
        "authorization": {
            "software_release_allowed": software_release_allowed,
            "human_benchmark_claim_allowed": False,
        },
        "label_provenance": {
            "sources": sorted({case.label_source for case in cases}),
            "human_reviewed": False,
            "policy": "automated_review_does_not_change_label_provenance",
        },
        "limitations": [
            "The evaluation labels are maintainer-authored synthetic fixtures, not independent human annotations.",
            "Passing authorizes an ordinary software release only.",
            "Human-reviewed benchmark claims still require real independent annotation and adjudication.",
        ],
    }


def validate_automated_review_artifact(
    payload: Dict[str, Any],
    *,
    project_root: Path,
    dataset: str,
) -> Dict[str, Any]:
    """Reject stale, incomplete, unsafe, or provenance-inflating review artifacts."""

    errors: List[str] = []
    dataset_path = (project_root / dataset).resolve()
    if payload.get("schema_version") != SCHEMA_VERSION:
        errors.append("unsupported automated review schema_version")
    if payload.get("review_type") != "automated_release_review":
        errors.append("review_type must be automated_release_review")
    dataset_info = payload.get("dataset", {})
    if dataset_info.get("path") != dataset:
        errors.append("automated review dataset path does not match the release gate dataset")
    if dataset_info.get("split") != "test":
        errors.append("automated release review must run on the test split")
    expected_dataset_digest = _sha256_file(dataset_path)
    if dataset_info.get("sha256") != expected_dataset_digest:
        errors.append("automated review dataset digest is stale")
    expected_implementation_digest = compute_review_contract_digest(project_root)
    if payload.get("implementation_digest") != expected_implementation_digest:
        errors.append("automated review implementation digest is stale")

    reviewers = payload.get("reviewers", {})
    rows = reviewers.get("model_components", [])
    reviewer_ids = {str(row.get("id", "")) for row in rows if isinstance(row, dict)}
    if reviewer_ids != REQUIRED_MODEL_REVIEWERS:
        errors.append("automated review is missing a required model component")
    if not reviewers.get("all_required_available") or any(
        not row.get("available") for row in rows if isinstance(row, dict)
    ):
        errors.append("one or more automated model reviewers were unavailable")
    if not payload.get("quality_gate", {}).get("ok"):
        errors.append("support quality gate did not pass")
    if not payload.get("support_set_policy", {}).get("ok"):
        errors.append("support-set aggregation policy gate did not pass")

    authorization = payload.get("authorization", {})
    if not authorization.get("software_release_allowed"):
        errors.append("automated review did not authorize a software release")
    if authorization.get("human_benchmark_claim_allowed") is not False:
        errors.append("automated review must never authorize human benchmark claims")
    if payload.get("label_provenance", {}).get("human_reviewed") is not False:
        errors.append("automated review must preserve non-human label provenance")
    if errors:
        raise ValueError("; ".join(errors))
    return {
        "dataset_sha256": expected_dataset_digest,
        "implementation_digest": expected_implementation_digest,
        "reviewer_ids": sorted(reviewer_ids),
        "software_release_allowed": True,
        "human_benchmark_claim_allowed": False,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the production-model review that may authorize an ordinary software release."
    )
    parser.add_argument("--project-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--dataset", default="data/eval/support_eval.json")
    parser.add_argument("--split", choices=["test"], default="test")
    parser.add_argument("--output", help="Optional JSON artifact path; stdout is always emitted.")
    args = parser.parse_args(argv)

    project_root = Path(args.project_root).resolve()
    report = build_automated_review_report(
        project_root=project_root,
        dataset=args.dataset,
        split=args.split,
    )
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = project_root / output_path
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["authorization"]["software_release_allowed"] else 1


if __name__ == "__main__":
    sys.exit(main())
