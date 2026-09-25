"""Reproducible verifier-component ablations for claim-support evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from citeguard.verification.support_eval import (
    SupportCase,
    compute_support_quality_gate,
    run_support_eval_report,
)
from citeguard.verifiers import (
    DEFAULT_NLI_MODEL,
    DEFAULT_PRODUCTION_ENSEMBLE_POLICY,
    DEFAULT_RERANKER_MODEL,
    EnsembleSupportBackend,
    EnsembleSupportPolicy,
    HeuristicSupportBackend,
    SentenceTransformerRerankerBackend,
    SupportAssessment,
    SupportBackend,
    TransformersNLIBackend,
)


SUPPORT_ABLATION_SCHEMA_VERSION = 1
SUPPORT_ABLATION_COMPONENTS: Dict[str, tuple[str, ...]] = {
    "heuristic_only": ("heuristic_support",),
    "reranker_only": ("sentence_transformer_reranker",),
    "nli_only": ("transformers_nli",),
    "heuristic_reranker": ("heuristic_support", "sentence_transformer_reranker"),
    "reranker_nli": ("sentence_transformer_reranker", "transformers_nli"),
    "full_ensemble": (
        "heuristic_support",
        "sentence_transformer_reranker",
        "transformers_nli",
    ),
}
SUPPORT_ABLATION_NAMES = tuple(SUPPORT_ABLATION_COMPONENTS)
MODEL_COMPONENTS = frozenset({"sentence_transformer_reranker", "transformers_nli"})


@dataclass(frozen=True)
class SupportAblationRuntime:
    """One configured ablation backend plus dependency availability."""

    name: str
    components: tuple[str, ...]
    backend: SupportBackend
    component_availability: Dict[str, bool]
    model_names: Dict[str, str]

    @property
    def unavailable_components(self) -> List[str]:
        return [
            component
            for component in self.components
            if not self.component_availability.get(component, False)
        ]

    @property
    def runnable(self) -> bool:
        return not self.unavailable_components


def build_support_ablation_runtime(
    name: str,
    *,
    reranker_model_name: str = DEFAULT_RERANKER_MODEL,
    nli_model_name: str = DEFAULT_NLI_MODEL,
    heuristic_threshold: float = 0.16,
    reranker_threshold: float = 0.45,
    nli_threshold: float = 0.50,
    nli_margin: float = 0.03,
    ensemble_policy: Optional[EnsembleSupportPolicy] = None,
) -> SupportAblationRuntime:
    """Build one named component combination without silently dropping models."""

    if name not in SUPPORT_ABLATION_COMPONENTS:
        raise ValueError(f"unknown support ablation: {name}")
    components = SUPPORT_ABLATION_COMPONENTS[name]
    component_backends: Dict[str, SupportBackend] = {
        "heuristic_support": HeuristicSupportBackend(threshold=heuristic_threshold),
        "sentence_transformer_reranker": SentenceTransformerRerankerBackend(
            model_name=reranker_model_name,
            threshold=reranker_threshold,
        ),
        "transformers_nli": TransformersNLIBackend(
            model_name=nli_model_name,
            threshold=nli_threshold,
            margin=nli_margin,
        ),
    }
    selected = [component_backends[component] for component in components]
    availability = {
        component: bool(component_backends[component].is_available())
        if component in MODEL_COMPONENTS
        else True
        for component in components
    }
    backend: SupportBackend
    if len(selected) == 1:
        backend = selected[0]
    else:
        backend = EnsembleSupportBackend(
            selected,
            policy=ensemble_policy or DEFAULT_PRODUCTION_ENSEMBLE_POLICY,
        )
    return SupportAblationRuntime(
        name=name,
        components=components,
        backend=backend,
        component_availability=availability,
        model_names={
            "sentence_transformer_reranker": reranker_model_name,
            "transformers_nli": nli_model_name,
        },
    )


def run_support_ablation_matrix(
    cases: Sequence[SupportCase],
    ablation_names: Optional[Iterable[str]] = None,
    *,
    reranker_model_name: str = DEFAULT_RERANKER_MODEL,
    nli_model_name: str = DEFAULT_NLI_MODEL,
    heuristic_threshold: float = 0.16,
    reranker_threshold: float = 0.45,
    nli_threshold: float = 0.50,
    nli_margin: float = 0.03,
    ensemble_policy: Optional[EnsembleSupportPolicy] = None,
    quality_thresholds: Optional[Mapping[str, Any]] = None,
    plan_only: bool = False,
) -> Dict[str, Any]:
    """Run requested ablations and keep unavailable model rows out of metrics."""

    names = _unique_ablation_names(ablation_names or SUPPORT_ABLATION_NAMES)
    case_rows = list(cases)
    thresholds = {
        "max_false_support_rate": 0.0,
        "max_false_support_count": 0,
        "max_weak_false_support_count": 0,
        "min_supported_precision": 1.0,
        "min_contradiction_recall": 1.0,
    }
    thresholds.update(dict(quality_thresholds or {}))

    runs: List[Dict[str, Any]] = []
    comparison: List[Dict[str, Any]] = []
    for name in names:
        runtime = build_support_ablation_runtime(
            name,
            reranker_model_name=reranker_model_name,
            nli_model_name=nli_model_name,
            heuristic_threshold=heuristic_threshold,
            reranker_threshold=reranker_threshold,
            nli_threshold=nli_threshold,
            nli_margin=nli_margin,
            ensemble_policy=ensemble_policy,
        )
        run: Dict[str, Any] = {
            "name": name,
            "components": list(runtime.components),
            "component_availability": dict(runtime.component_availability),
            "unavailable_components": list(runtime.unavailable_components),
            "model_names": dict(runtime.model_names),
            "backend_name": str(getattr(runtime.backend, "backend_name", runtime.backend.__class__.__name__)),
        }
        if not runtime.runnable:
            run.update(
                {
                    "status": "unavailable",
                    "reason": "required_model_dependency_unavailable",
                    "report": None,
                    "quality_gate": None,
                }
            )
        elif plan_only:
            run.update(
                {
                    "status": "planned",
                    "reason": "plan_only",
                    "report": None,
                    "quality_gate": None,
                }
            )
        elif not case_rows:
            run.update(
                {
                    "status": "model_error",
                    "reason": "empty_eval_split",
                    "model_failure_details": [],
                    "report": None,
                    "quality_gate": None,
                }
            )
        else:
            probe = runtime.backend.assess(case_rows[0].claim, case_rows[0].evidence)
            model_failures = _assessment_model_failures(probe)
            if model_failures:
                run.update(
                    {
                        "status": "model_error",
                        "reason": "model_load_or_inference_failed",
                        "model_failure_details": model_failures,
                        "report": None,
                        "quality_gate": None,
                    }
                )
            else:
                report = run_support_eval_report(case_rows, runtime.backend)
                gate = compute_support_quality_gate(
                    report,
                    max_false_support_rate=float(thresholds["max_false_support_rate"]),
                    max_false_support_count=int(thresholds["max_false_support_count"]),
                    max_weak_false_support_count=int(thresholds["max_weak_false_support_count"]),
                    min_supported_precision=float(thresholds["min_supported_precision"]),
                    min_contradiction_recall=float(thresholds["min_contradiction_recall"]),
                )
                run.update(
                    {
                        "status": "completed",
                        "reason": "",
                        "model_failure_details": [],
                        "report": report,
                        "quality_gate": gate,
                    }
                )
        runs.append(run)
        comparison.append(_ablation_comparison_row(run))

    completed = [run["name"] for run in runs if run["status"] == "completed"]
    unavailable = [run["name"] for run in runs if run["status"] == "unavailable"]
    model_errors = [run["name"] for run in runs if run["status"] == "model_error"]
    planned = [run["name"] for run in runs if run["status"] == "planned"]
    completed_gates = [
        bool(run["quality_gate"].get("ok"))
        for run in runs
        if run["status"] == "completed" and isinstance(run.get("quality_gate"), dict)
    ]
    return {
        "schema_version": SUPPORT_ABLATION_SCHEMA_VERSION,
        "axis": "verifier_components",
        "requested_ablations": names,
        "completed_ablations": completed,
        "unavailable_ablations": unavailable,
        "model_error_ablations": model_errors,
        "planned_ablations": planned,
        "requested_count": len(names),
        "completed_count": len(completed),
        "unavailable_count": len(unavailable),
        "model_error_count": len(model_errors),
        "planned_count": len(planned),
        "matrix_complete": len(completed) == len(names),
        "quality_gates_ok": bool(completed_gates) and all(completed_gates),
        "quality_thresholds": thresholds,
        "comparison": comparison,
        "runs": runs,
        "interpretation": (
            "Compare metrics only for status=completed rows. Unavailable and model-error rows are not zero-score runs."
        ),
        "policy": (
            "missing_models_are_not_scored; false_support_gates_remain_strict; "
            "synthetic_seed_results_do_not_establish_human_reviewed_benchmark_quality"
        ),
    }


def _unique_ablation_names(names: Iterable[str]) -> List[str]:
    result: List[str] = []
    for name in names:
        normalized = str(name).strip()
        if normalized not in SUPPORT_ABLATION_COMPONENTS:
            raise ValueError(f"unknown support ablation: {normalized}")
        if normalized not in result:
            result.append(normalized)
    if not result:
        raise ValueError("at least one support ablation is required")
    return result


def _assessment_model_failures(assessment: SupportAssessment) -> List[Dict[str, Any]]:
    candidates = [
        {"backend": assessment.backend_name, "details": assessment.details},
        *[
            {
                "backend": component.get("backend", ""),
                "details": component.get("details", {}),
            }
            for component in assessment.details.get("components", [])
            if isinstance(component, dict)
        ],
    ]
    failures: List[Dict[str, Any]] = []
    for candidate in candidates:
        details = candidate.get("details")
        if not isinstance(details, dict) or details.get("error_code") != "model_unavailable":
            continue
        failures.append(
            {
                "backend": str(candidate.get("backend", "")),
                "model_name": str(details.get("model_name", "")),
                "error_code": "model_unavailable",
                "error_type": str(details.get("error_type", "")),
                "message": str(details.get("message", "")),
            }
        )
    return failures


def _ablation_comparison_row(run: Dict[str, Any]) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        "ablation": run["name"],
        "status": run["status"],
        "components": list(run["components"]),
        "backend_name": run["backend_name"],
        "unavailable_components": list(run.get("unavailable_components", [])),
        "quality_gate_ok": None,
    }
    report = run.get("report")
    gate = run.get("quality_gate")
    if run.get("status") != "completed" or not isinstance(report, dict):
        return row
    overall = report.get("overall", {}) if isinstance(report.get("overall"), dict) else {}
    for field in (
        "accuracy",
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "weighted_precision",
        "weighted_recall",
        "weighted_f1",
        "supported_precision",
        "supported_recall",
        "supported_f1",
        "false_support_rate",
        "support_overcall_count",
        "support_overcall_rate",
        "abstention_rate",
        "contradiction_recall",
    ):
        row[field] = overall.get(field)
    error_counts = report.get("error_bucket_counts", {})
    false_support = report.get("false_support_analysis", {})
    if not isinstance(error_counts, dict):
        error_counts = {}
    if not isinstance(false_support, dict):
        false_support = {}
    row.update(
        {
            "false_support_count": int(error_counts.get("false_support", 0) or 0),
            "weak_false_support_count": int(error_counts.get("weak_false_support", 0) or 0),
            "missed_contradiction_count": int(error_counts.get("missed_contradiction", 0) or 0),
            "false_support_case_ids": list(false_support.get("false_support_case_ids", []) or []),
            "weak_false_support_case_ids": list(false_support.get("weak_false_support_case_ids", []) or []),
            "quality_gate_ok": bool(gate.get("ok")) if isinstance(gate, dict) else False,
            "quality_gate_failure_codes": [
                str(item.get("code", ""))
                for item in (gate.get("failures", []) if isinstance(gate, dict) else [])
                if isinstance(item, dict) and item.get("code")
            ],
        }
    )
    return row
