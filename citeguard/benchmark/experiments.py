"""Helpers for writing reproducible benchmark experiment artifacts."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


EXPERIMENT_ARTIFACT_SCHEMA_VERSION = 1


def write_experiment_artifacts(
    experiment_name: str,
    result: Dict[str, Any],
    config: Dict[str, Any],
    output_dir: str = "experiments",
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Write a result, config snapshot, and manifest under a versioned run folder."""

    clean_name = _slug(experiment_name) or "experiment"
    clean_run_id = _slug(run_id or _timestamp_run_id())
    run_path = Path(output_dir) / clean_run_id
    run_path.mkdir(parents=True, exist_ok=True)

    result_path = run_path / "result.json"
    config_path = run_path / "config.json"
    manifest_path = run_path / "manifest.json"
    _write_json(result_path, result)
    _write_json(config_path, config)

    manifest = {
        "schema_version": EXPERIMENT_ARTIFACT_SCHEMA_VERSION,
        "experiment_name": clean_name,
        "run_id": clean_run_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "files": {
            "result": result_path.name,
            "config": config_path.name,
            "manifest": manifest_path.name,
        },
        "result_summary": _result_summary(result),
    }
    _write_json(manifest_path, manifest)
    return {
        "schema_version": EXPERIMENT_ARTIFACT_SCHEMA_VERSION,
        "experiment_name": clean_name,
        "run_id": clean_run_id,
        "path": str(run_path),
        "files": {
            "result": str(result_path),
            "config": str(config_path),
            "manifest": str(manifest_path),
        },
    }


def _timestamp_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value).strip()).strip("-._")
    return slug[:120]


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False, sort_keys=True)
        handle.write("\n")


def _result_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    if "overall" in result and isinstance(result["overall"], dict):
        summary = dict(result["overall"])
    else:
        summary = {key: value for key, value in result.items() if isinstance(value, (int, float, str, bool))}
    if "quality_gate" in result and isinstance(result["quality_gate"], dict):
        summary["quality_gate_ok"] = bool(result["quality_gate"].get("ok"))
    _add_support_release_summary(summary, result)
    _add_false_support_triage_summary(summary, result)
    _add_support_acceptance_slice_summary(summary, result)
    _add_support_baseline_metric_summary(summary, result)
    _add_release_blocker_summary(summary, result)
    _add_abstention_analysis_summary(summary, result)
    _add_support_set_policy_summary(summary, result)
    _add_support_label_gate_summary(summary, result)
    _add_support_calibration_summary(summary, result)
    return summary


def _add_support_release_summary(summary: Dict[str, Any], result: Dict[str, Any]) -> None:
    release_summary = result.get("release_summary")
    if not isinstance(release_summary, dict):
        return
    metrics = release_summary.get("metrics")
    risk_counts = release_summary.get("risk_counts")
    review_queue = release_summary.get("review_queue")
    acceptance = release_summary.get("acceptance")
    abstention = release_summary.get("abstention")
    label_maturity = release_summary.get("label_maturity")
    metrics = metrics if isinstance(metrics, dict) else {}
    risk_counts = risk_counts if isinstance(risk_counts, dict) else {}
    review_queue = review_queue if isinstance(review_queue, dict) else {}
    acceptance = acceptance if isinstance(acceptance, dict) else {}
    abstention = abstention if isinstance(abstention, dict) else {}
    label_maturity = label_maturity if isinstance(label_maturity, dict) else {}

    summary["support_release_status"] = release_summary.get("status")
    summary["support_release_next_action"] = release_summary.get("next_action")
    summary["support_release_quality_gate_ok"] = release_summary.get("quality_gate_ok")
    summary["support_release_label_sidecar_gate_ok"] = release_summary.get("label_sidecar_gate_ok")
    summary["support_release_benchmark_claim_safe"] = bool(release_summary.get("benchmark_claim_safe"))
    summary["support_release_ok_to_accept_supported"] = bool(release_summary.get("ok_to_accept_supported"))
    summary["support_release_case_count"] = int(metrics.get("case_count", 0) or 0)
    summary["support_release_supported_precision"] = metrics.get("supported_precision")
    summary["support_release_supported_recall"] = metrics.get("supported_recall")
    summary["support_release_supported_f1"] = metrics.get("supported_f1")
    summary["support_release_macro_f1"] = metrics.get("macro_f1")
    summary["support_release_weighted_f1"] = metrics.get("weighted_f1")
    summary["support_release_false_support_rate"] = metrics.get("false_support_rate")
    summary["support_release_abstention_rate"] = metrics.get("abstention_rate")
    summary["support_release_contradiction_recall"] = metrics.get("contradiction_recall")
    summary["support_release_false_support_count"] = int(risk_counts.get("false_support", 0) or 0)
    summary["support_release_weak_false_support_count"] = int(risk_counts.get("weak_false_support", 0) or 0)
    summary["support_release_missed_contradiction_count"] = int(risk_counts.get("missed_contradiction", 0) or 0)
    summary["support_release_incorrect_abstention_count"] = int(risk_counts.get("incorrect_abstention", 0) or 0)
    summary["support_release_review_queue_count"] = int(review_queue.get("count", 0) or 0)
    summary["support_release_review_top_case_ids"] = list(review_queue.get("top_case_ids", []) or [])
    summary["support_release_blocking_case_ids"] = list(review_queue.get("blocking_case_ids", []) or [])
    summary["support_release_review_required_case_ids"] = list(
        review_queue.get("review_required_case_ids", []) or []
    )
    summary["support_release_block_acceptance_case_ids"] = list(
        acceptance.get("block_acceptance_case_ids", []) or []
    )
    summary["support_release_review_before_accepting_case_ids"] = list(
        acceptance.get("review_before_accepting_case_ids", []) or []
    )
    summary["support_release_top_risk_slice_id"] = acceptance.get("top_risk_slice_id")
    summary["support_release_top_risk_slice_case_ids"] = list(
        acceptance.get("top_risk_slice_case_ids", []) or []
    )
    summary["support_release_abstention_review_case_ids"] = list(abstention.get("review_case_ids", []) or [])
    summary["support_release_label_human_reviewed"] = int(label_maturity.get("human_reviewed", 0) or 0)
    summary["support_release_label_dual_annotated"] = int(label_maturity.get("dual_annotated", 0) or 0)
    summary["support_release_label_published_benchmark"] = int(
        label_maturity.get("published_benchmark", 0) or 0
    )
    summary["support_release_label_high_risk_unreviewed"] = int(
        label_maturity.get("high_risk_unreviewed", 0) or 0
    )


def _add_support_baseline_metric_summary(summary: Dict[str, Any], result: Dict[str, Any]) -> None:
    comparison = result.get("comparison")
    if not isinstance(comparison, list):
        return
    metric_fields = [
        "accuracy",
        "macro_precision",
        "macro_recall",
        "macro_f1",
        "weighted_precision",
        "weighted_recall",
        "weighted_f1",
        "false_support_rate",
        "abstention_rate",
        "supported_precision",
        "contradiction_recall",
    ]
    backend_metrics: Dict[str, Dict[str, Any]] = {}
    for row in comparison:
        if not isinstance(row, dict):
            continue
        backend = row.get("backend")
        if not backend:
            continue
        backend_metrics[str(backend)] = {field: row.get(field) for field in metric_fields}
    if backend_metrics:
        summary["support_baseline_metric_fields"] = metric_fields
        summary["support_baseline_metrics"] = backend_metrics


def _add_false_support_triage_summary(summary: Dict[str, Any], result: Dict[str, Any]) -> None:
    false_support_analysis = result.get("false_support_analysis")
    if isinstance(false_support_analysis, dict):
        top_risk_slice = false_support_analysis.get("top_risk_slice")
        acceptance_guard = false_support_analysis.get("acceptance_guard")
        review_plan = false_support_analysis.get("review_plan")
        summary["false_support_total_overcall_count"] = int(
            false_support_analysis.get("total_overcall_count", 0) or 0
        )
        summary["false_support_risk_slice_count"] = len(false_support_analysis.get("risk_slices", []) or [])
        if isinstance(acceptance_guard, dict):
            summary["false_support_ok_to_accept_supported"] = bool(
                acceptance_guard.get("ok_to_accept_supported")
            )
            summary["false_support_block_acceptance_count"] = int(
                acceptance_guard.get("block_acceptance_count", 0) or 0
            )
            summary["false_support_block_acceptance_case_ids"] = list(
                acceptance_guard.get("block_acceptance_case_ids", []) or []
            )
            summary["false_support_review_before_accepting_case_ids"] = list(
                acceptance_guard.get("review_before_accepting_case_ids", []) or []
            )
        if isinstance(top_risk_slice, dict):
            summary["false_support_top_risk_slice_id"] = top_risk_slice.get("id")
            summary["false_support_top_risk_slice_case_ids"] = list(top_risk_slice.get("case_ids", []) or [])
        else:
            summary["false_support_top_risk_slice_id"] = None
            summary["false_support_top_risk_slice_case_ids"] = []
        if isinstance(review_plan, dict):
            phases = review_plan.get("phases", [])
            if not isinstance(phases, list):
                phases = []
            summary["false_support_review_plan_status"] = review_plan.get("status")
            summary["false_support_review_plan_next_action"] = review_plan.get("next_action")
            summary["false_support_review_plan_phase_ids"] = [
                phase.get("id") for phase in phases if isinstance(phase, dict) and phase.get("id")
            ]
            summary["false_support_review_plan_top_risk_slice_id"] = review_plan.get("top_risk_slice_id")
            summary["false_support_review_plan_block_case_ids"] = list(
                review_plan.get("block_acceptance_case_ids", []) or []
            )
            summary["false_support_review_plan_review_case_ids"] = list(
                review_plan.get("review_before_accepting_case_ids", []) or []
            )
            recommended_packets = review_plan.get("recommended_annotation_packets", [])
            if not isinstance(recommended_packets, list):
                recommended_packets = []
            summary["false_support_review_plan_packet_ids"] = [
                packet.get("packet_id")
                for packet in recommended_packets
                if isinstance(packet, dict) and packet.get("packet_id")
            ]
            summary["false_support_review_plan_packet_count"] = int(
                review_plan.get("recommended_annotation_packet_count", len(summary["false_support_review_plan_packet_ids"])) or 0
            )
            summary["false_support_review_plan_packet_case_ids"] = list(
                review_plan.get("recommended_annotation_case_ids", []) or []
            )

    comparison = result.get("comparison")
    if isinstance(comparison, list):
        summary["false_support_overcall_backends"] = [
            row.get("backend")
            for row in comparison
            if isinstance(row, dict) and int(row.get("total_overcall_count", 0) or 0) > 0
        ]
        top_rows = [
            row
            for row in comparison
            if isinstance(row, dict) and isinstance(row.get("top_false_support_risk_slice"), dict)
        ]
        if top_rows:
            top_row = max(
                top_rows,
                key=lambda row: (
                    int((row.get("top_false_support_risk_slice") or {}).get("risk_score", 0) or 0),
                    int(row.get("total_overcall_count", 0) or 0),
                ),
            )
            top_slice = top_row["top_false_support_risk_slice"]
            summary["false_support_top_overcall_backend"] = top_row.get("backend")
            summary["false_support_top_risk_slice_id"] = top_slice.get("id")
            summary["false_support_top_risk_slice_case_ids"] = list(top_slice.get("case_ids", []) or [])
            summary["false_support_top_overcall_review_plan_status"] = top_row.get(
                "false_support_review_plan_status"
            )
            summary["false_support_top_overcall_review_plan_next_action"] = top_row.get(
                "false_support_review_plan_next_action"
            )
            summary["false_support_top_overcall_review_plan_phase_ids"] = list(
                top_row.get("false_support_review_plan_phase_ids", []) or []
            )
            summary["false_support_top_overcall_review_plan_block_case_ids"] = list(
                top_row.get("false_support_review_plan_block_case_ids", []) or []
            )
            summary["false_support_top_overcall_review_plan_review_case_ids"] = list(
                top_row.get("false_support_review_plan_review_case_ids", []) or []
            )
            summary["false_support_top_overcall_review_plan_packet_ids"] = list(
                top_row.get("false_support_review_plan_packet_ids", []) or []
            )
            summary["false_support_top_overcall_review_plan_packet_count"] = int(
                top_row.get("false_support_review_plan_packet_count", 0) or 0
            )
            summary["false_support_top_overcall_review_plan_packet_case_ids"] = list(
                top_row.get("false_support_review_plan_packet_case_ids", []) or []
            )
        else:
            summary.setdefault("false_support_top_overcall_backend", None)
            summary.setdefault("false_support_top_risk_slice_id", None)
            summary.setdefault("false_support_top_risk_slice_case_ids", [])
            summary.setdefault("false_support_top_overcall_review_plan_status", None)
            summary.setdefault("false_support_top_overcall_review_plan_next_action", None)
            summary.setdefault("false_support_top_overcall_review_plan_phase_ids", [])
            summary.setdefault("false_support_top_overcall_review_plan_block_case_ids", [])
            summary.setdefault("false_support_top_overcall_review_plan_review_case_ids", [])
            summary.setdefault("false_support_top_overcall_review_plan_packet_ids", [])
            summary.setdefault("false_support_top_overcall_review_plan_packet_count", 0)
            summary.setdefault("false_support_top_overcall_review_plan_packet_case_ids", [])


def _add_support_acceptance_slice_summary(summary: Dict[str, Any], result: Dict[str, Any]) -> None:
    acceptance_slices = result.get("acceptance_slices")
    if not isinstance(acceptance_slices, list):
        return
    rows = [row for row in acceptance_slices if isinstance(row, dict)]
    summary["support_acceptance_slice_ids"] = [
        str(row.get("id"))
        for row in rows
        if row.get("id")
    ]
    summary["support_acceptance_blocked_slice_ids"] = [
        str(row.get("id"))
        for row in rows
        if row.get("id") and row.get("status") == "blocked"
    ]
    summary["support_acceptance_review_required_slice_ids"] = [
        str(row.get("id"))
        for row in rows
        if row.get("id") and row.get("status") == "review_required"
    ]
    summary["support_acceptance_slice_case_counts"] = {
        str(row.get("id")): int(row.get("case_count", 0) or 0)
        for row in rows
        if row.get("id")
    }


def _add_release_blocker_summary(summary: Dict[str, Any], result: Dict[str, Any]) -> None:
    release_blocker = result.get("release_blocker_summary")
    if not isinstance(release_blocker, dict) and isinstance(result.get("quality_gate"), dict):
        release_blocker = result["quality_gate"].get("release_blocker_summary")
    if not isinstance(release_blocker, dict):
        return
    summary["release_blocked"] = bool(release_blocker.get("release_blocked"))
    summary["benchmark_claim_safe"] = bool(release_blocker.get("benchmark_claim_safe"))
    summary["release_blocking_count"] = int(release_blocker.get("blocking_count", 0) or 0)
    summary["release_blocking_case_ids"] = list(release_blocker.get("blocking_case_ids", []) or [])
    summary["release_review_required_count"] = int(release_blocker.get("review_required_count", 0) or 0)
    summary["release_review_required_case_ids"] = list(
        release_blocker.get("review_required_case_ids", []) or []
    )
    summary["release_next_action"] = release_blocker.get("next_action")


def _add_abstention_analysis_summary(summary: Dict[str, Any], result: Dict[str, Any]) -> None:
    abstention_analysis = result.get("abstention_analysis")
    if not isinstance(abstention_analysis, dict):
        return
    summary["abstention_total_count"] = int(abstention_analysis.get("total_abstention_count", 0) or 0)
    summary["abstention_incorrect_count"] = int(abstention_analysis.get("incorrect_abstention_count", 0) or 0)
    summary["abstention_correct_count"] = int(abstention_analysis.get("correct_abstention_count", 0) or 0)
    summary["abstention_review_case_ids"] = list(abstention_analysis.get("review_case_ids", []) or [])


def _add_support_set_policy_summary(summary: Dict[str, Any], result: Dict[str, Any]) -> None:
    support_set_policy = result.get("support_set_policy")
    if not isinstance(support_set_policy, dict):
        return
    dataset = support_set_policy.get("dataset")
    overall = support_set_policy.get("overall")
    cases = support_set_policy.get("cases")
    if not isinstance(dataset, dict):
        dataset = {}
    if not isinstance(overall, dict):
        overall = {}
    if not isinstance(cases, list):
        cases = []

    case_types = dataset.get("case_types", {})
    languages = dataset.get("languages", {})
    splits = dataset.get("splits", {})
    summary["support_set_policy_case_count"] = int(dataset.get("n", 0) or 0)
    summary["support_set_policy_case_types"] = dict(case_types) if isinstance(case_types, dict) else {}
    summary["support_set_policy_languages"] = dict(languages) if isinstance(languages, dict) else {}
    summary["support_set_policy_splits"] = dict(splits) if isinstance(splits, dict) else {}
    summary["support_set_policy_accuracy"] = overall.get("accuracy")
    summary["support_set_policy_case_ids"] = [
        case.get("case_id") for case in cases if isinstance(case, dict) and case.get("case_id")
    ]


def _add_support_label_gate_summary(summary: Dict[str, Any], result: Dict[str, Any]) -> None:
    label_gate = result.get("label_sidecar_gate")
    if not isinstance(label_gate, dict):
        return
    metrics = label_gate.get("metrics")
    if not isinstance(metrics, dict):
        metrics = {}

    summary["support_label_gate_ok"] = bool(label_gate.get("ok"))
    summary["support_label_sidecar_coverage"] = metrics.get("coverage")
    summary["support_label_human_reviewed"] = int(metrics.get("human_reviewed", 0) or 0)
    summary["support_label_high_risk_unreviewed"] = int(metrics.get("high_risk_unreviewed", 0) or 0)
    summary["support_label_full_text_required_unreviewed"] = int(
        metrics.get("full_text_required_unreviewed", 0) or 0
    )
    summary["support_label_policy_boundary_unreviewed"] = int(metrics.get("policy_boundary_unreviewed", 0) or 0)
    summary["support_label_dual_annotated"] = int(metrics.get("dual_annotated", 0) or 0)
    summary["support_label_unresolved_disagreements"] = int(metrics.get("unresolved_disagreements", 0) or 0)
    summary["support_label_supported_disagreements"] = int(metrics.get("supported_disagreements", 0) or 0)
    summary["support_label_raw_dual_agreement_rate"] = metrics.get("raw_dual_agreement_rate")
    summary["support_label_unresolved_disagreement_case_ids"] = list(
        metrics.get("unresolved_disagreement_case_ids", []) or []
    )
    summary["support_label_supported_disagreement_case_ids"] = list(
        metrics.get("supported_disagreement_case_ids", []) or []
    )
    summary["support_label_high_risk_case_count_by_language_case_type"] = _dict_or_empty(
        metrics.get("high_risk_case_count_by_language_case_type")
    )
    summary["support_label_high_risk_reviewed_by_language_case_type"] = _dict_or_empty(
        metrics.get("high_risk_reviewed_by_language_case_type")
    )
    summary["support_label_high_risk_unreviewed_by_language_case_type"] = _dict_or_empty(
        metrics.get("high_risk_unreviewed_by_language_case_type")
    )
    summary["support_label_label_source_counts"] = _dict_or_empty(metrics.get("label_source_counts"))
    summary["support_label_reviewed_by_label_source"] = _dict_or_empty(metrics.get("reviewed_by_label_source"))
    summary["support_label_unreviewed_by_label_source"] = _dict_or_empty(metrics.get("unreviewed_by_label_source"))
    summary["support_label_reviewed_source_locator_count"] = int(
        metrics.get("reviewed_source_locator_count", 0) or 0
    )
    summary["support_label_published_benchmark_source_locator_count"] = int(
        metrics.get("published_benchmark_source_locator_count", 0) or 0
    )
    summary["support_label_sidecar_provenance_complete_count"] = int(
        metrics.get("sidecar_provenance_complete_count", 0) or 0
    )
    summary["support_label_sidecar_provenance_complete_fraction"] = metrics.get(
        "sidecar_provenance_complete_fraction"
    )
    summary["support_label_sidecar_provenance_missing_count"] = int(
        metrics.get("sidecar_provenance_missing_count", 0) or 0
    )
    summary["support_label_sidecar_provenance_missing_case_ids"] = list(
        metrics.get("sidecar_provenance_missing_case_ids", []) or []
    )
    summary["support_label_sidecar_provenance_missing_case_ids_by_field"] = _dict_or_empty(
        metrics.get("sidecar_provenance_missing_case_ids_by_field")
    )
    summary["support_label_sidecar_provenance_field_present_counts"] = _dict_or_empty(
        metrics.get("sidecar_provenance_field_present_counts")
    )
    summary["support_label_dataset_cases"] = int(metrics.get("dataset_cases", 0) or 0)
    summary["support_label_sidecar_cases"] = int(metrics.get("sidecar_cases", 0) or 0)


def _add_support_calibration_summary(summary: Dict[str, Any], result: Dict[str, Any]) -> None:
    top_results = result.get("top_results")
    if not isinstance(top_results, list):
        return
    top_result = top_results[0] if top_results and isinstance(top_results[0], dict) else {}
    top_metrics = top_result.get("metrics") if isinstance(top_result, dict) else {}
    if not isinstance(top_metrics, dict):
        top_metrics = {}
    top_diagnostics = top_result.get("diagnostics") if isinstance(top_result, dict) else {}
    if not isinstance(top_diagnostics, dict):
        top_diagnostics = {}

    summary["support_calibration_top_result_count"] = len(top_results)
    summary["support_calibration_top_f1"] = top_metrics.get("f1")
    summary["support_calibration_top_precision"] = top_metrics.get("precision")
    summary["support_calibration_top_recall"] = top_metrics.get("recall")
    summary["support_calibration_top_false_support_rate"] = top_metrics.get("false_support_rate")
    summary["support_calibration_top_false_negative"] = top_metrics.get("false_negative")
    summary["support_calibration_top_false_positive_case_ids"] = list(
        top_diagnostics.get("false_positive_case_ids", []) or []
    )
    summary["support_calibration_top_false_negative_case_ids"] = list(
        top_diagnostics.get("false_negative_case_ids", []) or []
    )
    summary["support_calibration_top_false_positive_decision_paths"] = _dict_or_empty(
        _nested_dict_get(top_diagnostics, "decision_path_counts", "false_positive")
    )
    summary["support_calibration_top_false_negative_decision_paths"] = _dict_or_empty(
        _nested_dict_get(top_diagnostics, "decision_path_counts", "false_negative")
    )
    summary["support_calibration_top_false_positive_score_summary"] = _dict_or_empty(
        _nested_dict_get(top_diagnostics, "bucket_summaries", "false_positive")
    )
    summary["support_calibration_top_false_negative_score_summary"] = _dict_or_empty(
        _nested_dict_get(top_diagnostics, "bucket_summaries", "false_negative")
    )
    summary["support_calibration_input_mode"] = result.get("input_mode")
    summary["support_calibration_profile"] = result.get("profile")


def _dict_or_empty(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _nested_dict_get(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current
