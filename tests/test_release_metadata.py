"""Release metadata and public-interface guardrails."""

import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from citeguard.errors import (
    ERROR_CODE_CATEGORY,
    ERROR_CODE_NEXT_ACTION,
    ERROR_CODE_RECOVERY,
    ERROR_CODE_RETRYABLE,
    ERROR_SCHEMA_VERSION,
    STABLE_ERROR_CODES,
    error_code_registry,
)
from citeguard.retrieval.scholarly_clients.factory import DEFAULT_USER_AGENT
from citeguard.verification import STABLE_NEXT_ACTIONS
from citeguard.verification.support_eval import ALLOWED_SUPPORT_LABELS, load_support_eval, run_support_eval_report
from citeguard.verifiers import HeuristicSupportBackend
from citeguard.version import __version__
from scripts.release_package_gate import (
    _annotation_conflict_probe_case,
    _record_agent_skill_contract_gate,
    _record_batch_workflow_examples_gate,
    _record_benchmark_claim_safety_gate,
    _record_cache_replay_fixture_gate,
    _record_ci_mcp_smoke_contract_gate,
    _record_cli_error_contract_gate,
    _record_configuration_contract_gate,
    _record_counterevidence_safety_contract_gate,
    _record_error_codes_contract_gate,
    _record_full_text_evidence_boundary_contract_gate,
    _record_legacy_src_shim_contract,
    _record_live_source_health_contract_gate,
    _record_mcp_error_contract_gate,
    _record_mcp_extra_smoke,
    _record_mcp_stdio_smoke,
    _record_mcp_stdio_smoke_contract_gate,
    _record_published_smoke_plan,
    _record_project_metadata_contract,
    _record_public_api_contract_gate,
    _record_release_artifact_contract_gate,
    _record_security_compliance_contract_gate,
    _record_source_outage_safety_gate,
    _record_support_baseline_comparison_gate,
    _record_support_calibration_artifact_gate,
    _record_support_label_sidecar_gate,
    _record_support_review_queue_gate,
    _record_support_review_queue_annotation_packet_gate,
    _record_support_set_aggregation_contract_gate,
    _error_code_doc_rows,
    _human_reviewed_benchmark_occurrences,
    _public_api_contract_paths,
    _support_label_provenance_contract_errors,
)
from scripts.smoke_package import (
    _assert_archive_excludes_generated_files,
    _assert_archive_excludes_legacy_agent_scripts,
    _assert_archive_excludes_legacy_src_namespace,
    _assert_archive_excludes_historical_planning_docs,
    _assert_distribution_metadata_contract,
    _expected_sdist_release_files,
)


ROOT = Path(__file__).resolve().parents[1]
INTERNAL_PACKAGE = "s" + "rc"


def _support_label_gate_payload():
    return {
        "ok": True,
        "metrics": {
            "coverage": 1.0,
            "human_reviewed": 0,
            "high_risk_unreviewed": 35,
            "full_text_required_unreviewed": 7,
            "policy_boundary_unreviewed": 2,
            "dual_annotated": 0,
            "unresolved_disagreements": 0,
            "supported_disagreements": 0,
            "raw_dual_agreement_rate": None,
            "unresolved_disagreement_case_ids": [],
            "supported_disagreement_case_ids": [],
            "high_risk_case_count_by_language_case_type": {
                "en": {"contradiction": 9, "contradiction_set": 1, "full_text_required": 6, "hard_negative": 10},
                "zh": {"contradiction": 6, "full_text_required": 1, "hard_negative": 2},
            },
            "high_risk_reviewed_by_language_case_type": {},
            "high_risk_unreviewed_by_language_case_type": {
                "en": {"contradiction": 9, "contradiction_set": 1, "full_text_required": 6, "hard_negative": 10},
                "zh": {"contradiction": 6, "full_text_required": 1, "hard_negative": 2},
            },
            "label_source_counts": {"maintainer_synthetic": 54},
            "reviewed_by_label_source": {},
            "unreviewed_by_label_source": {"maintainer_synthetic": 54},
            "reviewed_source_locator_count": 0,
            "published_benchmark_source_locator_count": 0,
            "sidecar_provenance_complete_count": 54,
            "sidecar_provenance_complete_fraction": 1.0,
            "sidecar_provenance_missing_count": 0,
            "sidecar_provenance_missing_case_ids": [],
            "sidecar_provenance_missing_case_ids_by_field": {},
            "sidecar_provenance_field_present_counts": {
                "label_source": 54,
                "case_type": 54,
                "evidence_scope": 54,
                "split": 54,
                "lang": 54,
            },
            "dataset_cases": 54,
            "sidecar_cases": 54,
        },
    }


def _support_label_manifest_summary():
    return {
        "support_label_gate_ok": True,
        "support_label_sidecar_coverage": 1.0,
        "support_label_human_reviewed": 0,
        "support_label_high_risk_unreviewed": 35,
        "support_label_full_text_required_unreviewed": 7,
        "support_label_policy_boundary_unreviewed": 2,
        "support_label_dual_annotated": 0,
        "support_label_unresolved_disagreements": 0,
        "support_label_supported_disagreements": 0,
        "support_label_raw_dual_agreement_rate": None,
        "support_label_unresolved_disagreement_case_ids": [],
        "support_label_supported_disagreement_case_ids": [],
        "support_label_high_risk_case_count_by_language_case_type": {
            "en": {"contradiction": 9, "contradiction_set": 1, "full_text_required": 6, "hard_negative": 10},
            "zh": {"contradiction": 6, "full_text_required": 1, "hard_negative": 2},
        },
        "support_label_high_risk_reviewed_by_language_case_type": {},
        "support_label_high_risk_unreviewed_by_language_case_type": {
            "en": {"contradiction": 9, "contradiction_set": 1, "full_text_required": 6, "hard_negative": 10},
            "zh": {"contradiction": 6, "full_text_required": 1, "hard_negative": 2},
        },
        "support_label_label_source_counts": {"maintainer_synthetic": 54},
        "support_label_reviewed_by_label_source": {},
        "support_label_unreviewed_by_label_source": {"maintainer_synthetic": 54},
        "support_label_reviewed_source_locator_count": 0,
        "support_label_published_benchmark_source_locator_count": 0,
        "support_label_sidecar_provenance_complete_count": 54,
        "support_label_sidecar_provenance_complete_fraction": 1.0,
        "support_label_sidecar_provenance_missing_count": 0,
        "support_label_sidecar_provenance_missing_case_ids": [],
        "support_label_sidecar_provenance_missing_case_ids_by_field": {},
        "support_label_sidecar_provenance_field_present_counts": {
            "label_source": 54,
            "case_type": 54,
            "evidence_scope": 54,
            "split": 54,
            "lang": 54,
        },
        "support_label_dataset_cases": 54,
        "support_label_sidecar_cases": 54,
    }


def _clear_support_release_summary():
    return {
        "schema_version": 1,
        "status": "clear",
        "next_action": "continue",
        "quality_gate_ok": True,
        "label_sidecar_gate_ok": True,
        "benchmark_claim_safe": True,
        "ok_to_accept_supported": True,
        "metrics": {
            "case_count": 12,
            "supported_precision": 1.0,
            "supported_recall": 1.0,
            "supported_f1": 1.0,
            "macro_f1": 1.0,
            "weighted_f1": 1.0,
            "false_support_rate": 0.0,
            "abstention_rate": 0.0,
            "contradiction_recall": 1.0,
        },
        "risk_counts": {
            "false_support": 0,
            "weak_false_support": 0,
            "missed_contradiction": 0,
            "incorrect_abstention": 0,
        },
        "review_queue": {
            "count": 0,
            "top_case_ids": [],
            "blocking_case_ids": [],
            "review_required_case_ids": [],
        },
        "acceptance": {
            "block_acceptance_case_ids": [],
            "review_before_accepting_case_ids": [],
            "top_risk_slice_id": None,
            "top_risk_slice_case_ids": [],
        },
        "abstention": {"review_case_ids": []},
        "label_maturity": {
            "human_reviewed": 0,
            "dual_annotated": 0,
            "published_benchmark": 0,
            "high_risk_unreviewed": 35,
        },
    }


def _clear_support_release_manifest_summary():
    return {
        "support_release_status": "clear",
        "support_release_next_action": "continue",
        "support_release_quality_gate_ok": True,
        "support_release_label_sidecar_gate_ok": True,
        "support_release_benchmark_claim_safe": True,
        "support_release_ok_to_accept_supported": True,
        "support_release_case_count": 12,
        "support_release_supported_precision": 1.0,
        "support_release_supported_recall": 1.0,
        "support_release_supported_f1": 1.0,
        "support_release_macro_f1": 1.0,
        "support_release_weighted_f1": 1.0,
        "support_release_false_support_rate": 0.0,
        "support_release_abstention_rate": 0.0,
        "support_release_contradiction_recall": 1.0,
        "support_release_false_support_count": 0,
        "support_release_weak_false_support_count": 0,
        "support_release_missed_contradiction_count": 0,
        "support_release_incorrect_abstention_count": 0,
        "support_release_review_queue_count": 0,
        "support_release_review_top_case_ids": [],
        "support_release_blocking_case_ids": [],
        "support_release_review_required_case_ids": [],
        "support_release_block_acceptance_case_ids": [],
        "support_release_review_before_accepting_case_ids": [],
        "support_release_top_risk_slice_id": None,
        "support_release_top_risk_slice_case_ids": [],
        "support_release_abstention_review_case_ids": [],
        "support_release_label_human_reviewed": 0,
        "support_release_label_dual_annotated": 0,
        "support_release_label_published_benchmark": 0,
        "support_release_label_high_risk_unreviewed": 35,
    }


def _empty_release_blocker_summary():
    return {
        "release_blocked": False,
        "benchmark_claim_safe": True,
        "blocking_count": 0,
        "blocking_case_ids": [],
        "review_required_count": 0,
        "review_required_case_ids": [],
        "next_action": "continue",
    }


def _empty_release_blocker_manifest_summary():
    return {
        "release_blocked": False,
        "benchmark_claim_safe": True,
        "release_blocking_count": 0,
        "release_blocking_case_ids": [],
        "release_review_required_count": 0,
        "release_review_required_case_ids": [],
        "release_next_action": "continue",
    }


def _clear_support_acceptance_slices():
    return [
        {
            "id": "contradiction",
            "severity": "critical",
            "status": "clear",
            "case_count": 1,
            "case_ids": ["s03"],
            "false_support_count": 0,
            "false_support_case_ids": [],
            "weak_false_support_count": 0,
            "weak_false_support_case_ids": [],
            "recommended_action": "continue",
            "policy": "contradicted_cases_must_not_be_called_supported",
        },
        {
            "id": "hard_negative",
            "severity": "critical",
            "status": "clear",
            "case_count": 1,
            "case_ids": ["s02"],
            "false_support_count": 0,
            "false_support_case_ids": [],
            "weak_false_support_count": 0,
            "weak_false_support_case_ids": [],
            "recommended_action": "continue",
            "policy": "real_or_related_papers_without_claim_support_must_not_be_called_supported",
        },
        {
            "id": "full_text_boundary",
            "severity": "high",
            "status": "clear",
            "case_count": 1,
            "case_ids": ["s04"],
            "false_support_count": 0,
            "false_support_case_ids": [],
            "weak_false_support_count": 0,
            "weak_false_support_case_ids": [],
            "recommended_action": "continue",
            "policy": "abstract_or_metadata_evidence_must_not_be_upgraded_to_full_text_support",
        },
        {
            "id": "test_split",
            "severity": "high",
            "status": "clear",
            "case_count": 3,
            "case_ids": ["s02", "s03", "s04"],
            "false_support_count": 0,
            "false_support_case_ids": [],
            "weak_false_support_count": 0,
            "weak_false_support_case_ids": [],
            "recommended_action": "continue",
            "policy": "heldout_test_overcalls_require_release_review",
        },
        {
            "id": "non_english",
            "severity": "high",
            "status": "clear",
            "case_count": 1,
            "case_ids": ["s05"],
            "false_support_count": 0,
            "false_support_case_ids": [],
            "weak_false_support_count": 0,
            "weak_false_support_case_ids": [],
            "recommended_action": "continue",
            "policy": "non_english_overcalls_require_language_specific_review",
        },
    ]


def _clear_support_acceptance_slice_manifest_summary():
    return {
        "support_acceptance_slice_ids": [
            "contradiction",
            "hard_negative",
            "full_text_boundary",
            "test_split",
            "non_english",
        ],
        "support_acceptance_blocked_slice_ids": [],
        "support_acceptance_review_required_slice_ids": [],
        "support_acceptance_slice_case_counts": {
            "contradiction": 1,
            "hard_negative": 1,
            "full_text_boundary": 1,
            "test_split": 3,
            "non_english": 1,
        },
    }


def _empty_false_support_review_plan():
    plan = {
        "schema_version": 1,
        "status": "clear",
        "next_action": "continue",
        "block_acceptance_case_ids": [],
        "review_before_accepting_case_ids": [],
        "top_risk_slice_id": None,
        "top_risk_slice_case_ids": [],
        "recommended_annotation_packets": [],
        "recommended_annotation_packet_count": 0,
        "recommended_annotation_case_ids": [],
        "phases": [
            {
                "id": "supported_overcall_blockers",
                "priority": 1,
                "status": "clear",
                "recommended_action": "rewrite_or_replace_evidence",
                "case_ids": [],
                "count": 0,
            },
            {
                "id": "weak_support_overcall_review",
                "priority": 2,
                "status": "clear",
                "recommended_action": "downgrade_or_find_stronger_evidence",
                "case_ids": [],
                "count": 0,
            },
            {
                "id": "highest_risk_slice_review",
                "priority": 3,
                "status": "clear",
                "recommended_action": "continue",
                "risk_slice_id": None,
                "case_ids": [],
                "count": 0,
            },
        ],
    }
    for phase in plan["phases"]:
        packet_id = "support-label-packet-{}".format(str(phase["id"]).replace("_", "-"))
        command = [
            "python",
            "scripts/prepare_support_label_sidecar.py",
            "--annotation-packet",
            "--review-phase",
            str(phase["id"]),
            "--output",
            f"experiments/{packet_id}.json",
        ]
        phase["annotation_packet"] = {
            "schema_version": 1,
            "packet_id": packet_id,
            "review_phase": phase["id"],
            "status": phase["status"],
            "case_ids": [],
            "count": 0,
            "command_template": command,
            "output": f"experiments/{packet_id}.json",
            "instructions_output": f"experiments/{packet_id}-instructions.md",
        }
        phase["command_template"] = list(command)
        phase["packet_id"] = packet_id
    return plan


def _empty_false_support_review_plan_manifest_summary():
    return {
        "false_support_review_plan_status": "clear",
        "false_support_review_plan_next_action": "continue",
        "false_support_review_plan_phase_ids": [
            "supported_overcall_blockers",
            "weak_support_overcall_review",
            "highest_risk_slice_review",
        ],
        "false_support_review_plan_top_risk_slice_id": None,
        "false_support_review_plan_block_case_ids": [],
        "false_support_review_plan_review_case_ids": [],
        "false_support_review_plan_packet_ids": [],
        "false_support_review_plan_packet_count": 0,
        "false_support_review_plan_packet_case_ids": [],
    }


def _heuristic_false_support_review_plan_row_fields():
    return {
        "false_support_review_plan_status": "blocked",
        "false_support_review_plan_next_action": "review_supported_overcalls_before_release",
        "false_support_review_plan_phase_ids": [
            "supported_overcall_blockers",
            "weak_support_overcall_review",
            "highest_risk_slice_review",
        ],
        "false_support_review_plan_top_risk_slice_id": "contradicted_overcalled",
        "false_support_review_plan_block_case_ids": ["s10"],
        "false_support_review_plan_review_case_ids": ["s11"],
        "false_support_review_plan_packet_ids": ["support-label-packet-supported-overcall-blockers-test"],
        "false_support_review_plan_packet_count": 1,
        "false_support_review_plan_packet_case_ids": ["s10", "s11"],
    }


def _empty_false_support_review_plan_row_fields():
    return {
        "false_support_review_plan_status": "clear",
        "false_support_review_plan_next_action": "continue",
        "false_support_review_plan_phase_ids": [
            "supported_overcall_blockers",
            "weak_support_overcall_review",
            "highest_risk_slice_review",
        ],
        "false_support_review_plan_top_risk_slice_id": None,
        "false_support_review_plan_block_case_ids": [],
        "false_support_review_plan_review_case_ids": [],
        "false_support_review_plan_packet_ids": [],
        "false_support_review_plan_packet_count": 0,
        "false_support_review_plan_packet_case_ids": [],
    }


def _heuristic_false_support_review_plan_manifest_summary():
    row_fields = _heuristic_false_support_review_plan_row_fields()
    return {
        "false_support_top_overcall_review_plan_status": row_fields["false_support_review_plan_status"],
        "false_support_top_overcall_review_plan_next_action": row_fields[
            "false_support_review_plan_next_action"
        ],
        "false_support_top_overcall_review_plan_phase_ids": row_fields[
            "false_support_review_plan_phase_ids"
        ],
        "false_support_top_overcall_review_plan_block_case_ids": row_fields[
            "false_support_review_plan_block_case_ids"
        ],
        "false_support_top_overcall_review_plan_review_case_ids": row_fields[
            "false_support_review_plan_review_case_ids"
        ],
        "false_support_top_overcall_review_plan_packet_ids": row_fields[
            "false_support_review_plan_packet_ids"
        ],
        "false_support_top_overcall_review_plan_packet_count": row_fields[
            "false_support_review_plan_packet_count"
        ],
        "false_support_top_overcall_review_plan_packet_case_ids": row_fields[
            "false_support_review_plan_packet_case_ids"
        ],
    }


def _perfect_support_metric_manifest_summary():
    return {
        "macro_precision": 1.0,
        "macro_recall": 1.0,
        "macro_f1": 1.0,
        "weighted_precision": 1.0,
        "weighted_recall": 1.0,
        "weighted_f1": 1.0,
    }


def _baseline_metric_fields():
    return [
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


def _baseline_row_metrics(macro_f1=1.0, weighted_f1=1.0):
    return {
        "accuracy": 1.0,
        "macro_precision": 1.0,
        "macro_recall": macro_f1,
        "macro_f1": macro_f1,
        "weighted_precision": 1.0,
        "weighted_recall": weighted_f1,
        "weighted_f1": weighted_f1,
        "false_support_rate": 0.0,
        "abstention_rate": 0.0,
        "supported_precision": 1.0,
        "contradiction_recall": 1.0,
    }


def _support_label_review_plan_audit_payload():
    high_risk_unreviewed_by_language_case_type = {
        "en": {"contradiction": 9, "contradiction_set": 1, "full_text_required": 6, "hard_negative": 10},
        "zh": {"contradiction": 6, "full_text_required": 1, "hard_negative": 2},
    }

    def high_risk_slice_packet(language, case_type, count):
        slug = f"{language}_{case_type}"
        return {
            "id": f"high_risk_unreviewed_{slug}",
            "candidate_case_count": count,
            "candidate_case_ids": [f"{slug}_case"],
            "command": [
                "python3",
                "scripts/prepare_support_label_sidecar.py",
                "--dataset",
                "data/eval/support_eval.json",
                "--existing-sidecar",
                "data/eval/support_eval_label_sidecar.json",
                "--annotation-packet",
                "--review-phase",
                "first_review_high_risk",
                "--packet-purpose",
                f"Assign first-review packet for unreviewed high-risk `{language}` `{case_type}` cases.",
                "--priority",
                "high",
                "--lang",
                language,
                "--case-type",
                case_type,
                "--unreviewed-only",
                "--output",
                f"experiments/support-label-packet-high-risk-unreviewed-{language}-{case_type}.json",
                "--instructions-output",
                f"experiments/support-label-packet-high-risk-unreviewed-{language}-{case_type}-instructions.md",
            ],
            "output": f"experiments/support-label-packet-high-risk-unreviewed-{language}-{case_type}.json",
            "instructions_output": (
                f"experiments/support-label-packet-high-risk-unreviewed-{language}-{case_type}-instructions.md"
            ),
        }

    high_risk_slice_packets = [
        high_risk_slice_packet(language, case_type, count)
        for language, by_case_type in high_risk_unreviewed_by_language_case_type.items()
        for case_type, count in by_case_type.items()
    ]
    high_risk_slice_packet_ids = [packet["id"] for packet in high_risk_slice_packets]
    return {
        "high_risk_unreviewed_by_language_case_type": high_risk_unreviewed_by_language_case_type,
        "recommended_packets": [
            {
                "id": "high_risk_unreviewed_balanced",
                "candidate_case_count": 35,
                "candidate_case_ids": ["s04", "s35"],
                "command": [
                    "python3",
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    "data/eval/support_eval.json",
                    "--existing-sidecar",
                    "data/eval/support_eval_label_sidecar.json",
                    "--annotation-packet",
                    "--review-phase",
                    "first_review_high_risk",
                    "--packet-purpose",
                    "Assign a balanced first-review packet for unreviewed high-risk support cases.",
                    "--priority",
                    "high",
                    "--unreviewed-only",
                    "--limit-per-language",
                    "1",
                    "--limit-per-case-type",
                    "1",
                    "--limit-per-evidence-scope",
                    "1",
                    "--output",
                    "experiments/support-label-packet-high-risk-unreviewed-balanced.json",
                    "--instructions-output",
                    "experiments/support-label-packet-high-risk-unreviewed-balanced-instructions.md",
                ],
                "output": "experiments/support-label-packet-high-risk-unreviewed-balanced.json",
                "instructions_output": "experiments/support-label-packet-high-risk-unreviewed-balanced-instructions.md",
            },
            {
                "id": "full_text_required_unreviewed",
                "candidate_case_count": 7,
                "candidate_case_ids": ["s17", "s30", "s43", "s13", "s38", "s20", "s33"],
                "command": [
                    "python3",
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    "data/eval/support_eval.json",
                    "--existing-sidecar",
                    "data/eval/support_eval_label_sidecar.json",
                    "--annotation-packet",
                    "--review-phase",
                    "first_review_high_risk",
                    "--packet-purpose",
                    "Assign first-review packet for cases where abstract-level evidence may be insufficient and lawful full-text inspection is required.",
                    "--case-type",
                    "full_text_required",
                    "--unreviewed-only",
                    "--limit",
                    "10",
                    "--output",
                    "experiments/support-label-packet-full-text-required-unreviewed.json",
                    "--instructions-output",
                    "experiments/support-label-packet-full-text-required-unreviewed-instructions.md",
                ],
                "output": "experiments/support-label-packet-full-text-required-unreviewed.json",
                "instructions_output": "experiments/support-label-packet-full-text-required-unreviewed-instructions.md",
            },
            {
                "id": "policy_boundary_unreviewed",
                "candidate_case_count": 2,
                "candidate_case_ids": ["ss02", "ss05"],
                "command": [
                    "python3",
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    "data/eval/support_eval.json",
                    "--existing-sidecar",
                    "data/eval/support_eval_label_sidecar.json",
                    "--annotation-packet",
                    "--review-phase",
                    "first_review_high_risk",
                    "--packet-purpose",
                    "Assign first-review packet for citation-set policy boundaries where multiple weak citations must stay tentative.",
                    "--case-type",
                    "weak_set_boundary",
                    "--unreviewed-only",
                    "--limit",
                    "10",
                    "--output",
                    "experiments/support-label-packet-policy-boundary-unreviewed.json",
                    "--instructions-output",
                    "experiments/support-label-packet-policy-boundary-unreviewed-instructions.md",
                ],
                "output": "experiments/support-label-packet-policy-boundary-unreviewed.json",
                "instructions_output": "experiments/support-label-packet-policy-boundary-unreviewed-instructions.md",
            },
            {
                "id": "high_risk_unreviewed_en",
                "candidate_case_count": 25,
                "candidate_case_ids": ["s04"],
                "command": [
                    "python3",
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    "data/eval/support_eval.json",
                    "--existing-sidecar",
                    "data/eval/support_eval_label_sidecar.json",
                    "--annotation-packet",
                    "--review-phase",
                    "first_review_high_risk",
                    "--packet-purpose",
                    "Assign first-review packet for unreviewed high-risk `en` cases.",
                    "--priority",
                    "high",
                    "--lang",
                    "en",
                    "--unreviewed-only",
                    "--output",
                    "experiments/support-label-packet-high-risk-unreviewed-en.json",
                    "--instructions-output",
                    "experiments/support-label-packet-high-risk-unreviewed-en-instructions.md",
                ],
                "output": "experiments/support-label-packet-high-risk-unreviewed-en.json",
                "instructions_output": "experiments/support-label-packet-high-risk-unreviewed-en-instructions.md",
            },
            {
                "id": "high_risk_unreviewed_zh",
                "candidate_case_count": 9,
                "candidate_case_ids": ["s35"],
                "command": [
                    "python3",
                    "scripts/prepare_support_label_sidecar.py",
                    "--dataset",
                    "data/eval/support_eval.json",
                    "--existing-sidecar",
                    "data/eval/support_eval_label_sidecar.json",
                    "--annotation-packet",
                    "--review-phase",
                    "first_review_high_risk",
                    "--packet-purpose",
                    "Assign first-review packet for unreviewed high-risk `zh` cases.",
                    "--priority",
                    "high",
                    "--lang",
                    "zh",
                    "--unreviewed-only",
                    "--output",
                    "experiments/support-label-packet-high-risk-unreviewed-zh.json",
                    "--instructions-output",
                    "experiments/support-label-packet-high-risk-unreviewed-zh-instructions.md",
                ],
                "output": "experiments/support-label-packet-high-risk-unreviewed-zh.json",
                "instructions_output": "experiments/support-label-packet-high-risk-unreviewed-zh-instructions.md",
            },
            *high_risk_slice_packets,
        ],
        "review_plan": {
            "schema_version": 1,
            "status": "blocked",
            "next_phase": "first_review_high_risk",
            "human_reviewed": 0,
            "dual_annotated": 0,
            "high_risk_reviewed": 0,
            "high_risk_unreviewed": 35,
            "high_risk_unreviewed_by_language_case_type": high_risk_unreviewed_by_language_case_type,
            "full_text_required_unreviewed": 7,
            "policy_boundary_unreviewed": 2,
            "phases": [
                {
                    "id": "first_review_high_risk",
                    "status": "ready",
                    "candidate_case_count": 37,
                    "candidate_case_ids": ["s10", "s17", "s48", "ss02", "ss05"],
                    "candidate_case_count_by_language_case_type": high_risk_unreviewed_by_language_case_type,
                    "recommended_packet_ids": [
                        "high_risk_unreviewed_balanced",
                        "full_text_required_unreviewed",
                        "policy_boundary_unreviewed",
                        "high_risk_unreviewed_en",
                        "high_risk_unreviewed_zh",
                        *high_risk_slice_packet_ids,
                    ],
                },
                {
                    "id": "second_review",
                    "status": "waiting_for_first_review",
                    "candidate_case_count": 0,
                    "recommended_packet_ids": [],
                },
                {
                    "id": "adjudication",
                    "status": "waiting_for_dual_annotation",
                    "candidate_case_count": 0,
                    "supported_disagreement_count": 0,
                    "command_template": [
                        "python3",
                        "scripts/prepare_support_label_sidecar.py",
                        "--apply-adjudications",
                        "experiments/resolved-support-label-adjudications.json",
                    ],
                },
                {
                    "id": "raise_release_gates",
                    "status": "blocked",
                    "candidate_case_count": 33,
                    "suggested_thresholds": {
                        "min_human_reviewed": 1,
                        "min_high_risk_reviewed": 1,
                        "max_unresolved_disagreements": 0,
                        "max_supported_disagreements": 0,
                    },
                    "command_template": [
                        "python3",
                        "scripts/eval_support.py",
                        "--validate-only",
                        "--max-supported-disagreements",
                        "0",
                    ],
                },
            ],
        }
    }


def _support_label_review_plan_run_no_check_side_effect(*audit_probes):
    probes = iter(audit_probes)

    def side_effect(cmd, cwd):
        if "--annotation-packet" not in cmd:
            return next(probes)
        packet_path = Path(cmd[cmd.index("--output") + 1])
        instructions_path = Path(cmd[cmd.index("--instructions-output") + 1])
        language = cmd[cmd.index("--lang") + 1] if "--lang" in cmd else ""
        case_type = cmd[cmd.index("--case-type") + 1] if "--case-type" in cmd else ""
        is_slice_packet = bool(language and case_type)
        case_count = 9 if language == "en" and case_type == "contradiction" else 8 if is_slice_packet else 2
        case_ids = [f"{language}-{case_type}-{index}" for index in range(1, case_count + 1)] if is_slice_packet else [
            "s04",
            "s35",
        ]
        packet_purpose = (
            f"Assign first-review packet for unreviewed high-risk `{language}` `{case_type}` cases."
            if is_slice_packet
            else "Assign a balanced first-review packet for unreviewed high-risk support cases."
        )
        packet_summary = {
            "case_ids": case_ids,
            "case_count_by_review_status": {"not_human_reviewed": case_count},
        }
        if is_slice_packet:
            packet_summary["case_count_by_language"] = {language: case_count}
            packet_summary["case_count_by_case_type"] = {case_type: case_count}
        packet_path.write_text(
            json.dumps(
                {
                    "ok": True,
                    "packet_type": "support_label_annotation_packet",
                    "packet_id": "support-packet-release-gate",
                    "review_phase": "first_review_high_risk",
                    "packet_purpose": packet_purpose,
                    "n": case_count,
                    "hidden_fields": ["gold", "predicted", "adjudicated_label", "annotator_labels", "label_notes"],
                    "packet_summary": packet_summary,
                    "cases": [
                        {
                            "packet_id": "support-packet-release-gate",
                            "packet_case_index": index,
                            "case_id": case_id,
                            "review_phase": "first_review_high_risk",
                            "packet_purpose": packet_purpose,
                            "annotation": {
                                "annotator_label": "",
                                "evidence_scope_assessed": "",
                                "full_text_needed": "",
                            },
                        }
                        for index, case_id in enumerate(case_ids, start=1)
                    ],
                }
            ),
            encoding="utf-8",
        )
        instructions_path.write_text(
            "Packet summary\ncase_count_by_review_status\nReview phase: `first_review_high_risk`\n"
            "annotation.evidence_scope_assessed\nannotation.full_text_needed\n",
            encoding="utf-8",
        )
        return mock.Mock(returncode=0, stdout="", stderr="")

    return side_effect


class ReleaseMetadataTests(unittest.TestCase):
    def test_pyproject_declares_public_entry_points_and_extras(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        self.assertIn(f'version = "{__version__}"', pyproject)
        self.assertIn('description = "A skeptical citation auditor for agent writing workflows."', pyproject)
        self.assertIn('"skeptical-citation-auditor"', pyproject)
        self.assertIn('"agent-tools"', pyproject)
        self.assertIn('"mcp"', pyproject)
        self.assertIn('"research-integrity"', pyproject)
        self.assertNotIn('"research-agents"', pyproject)
        self.assertIn('citeguard = "citeguard.cli:main"', pyproject)
        self.assertIn('citeguard-mcp = "citeguard.mcp.server:main"', pyproject)
        self.assertIn('include = ["citeguard", "citeguard.*"]', pyproject)
        self.assertNotIn(f'"{INTERNAL_PACKAGE}"', pyproject)
        self.assertNotIn(f'"{INTERNAL_PACKAGE}.*"', pyproject)
        self.assertIn("mcp = [", pyproject)
        self.assertIn('"mcp>=1.2"', pyproject)
        self.assertIn("pdf = [", pyproject)
        self.assertIn('"pypdf>=4,<6"', pyproject)
        self.assertIn("models = [", pyproject)
        self.assertIn('"Topic :: Text Processing :: Linguistic"', pyproject)
        self.assertIn('"Typing :: Typed"', pyproject)
        self.assertIn('Documentation = "https://github.com/xiaweiyi713/citeguard#readme"', pyproject)
        self.assertIn('citeguard = ["py.typed"]', pyproject)

    def test_legacy_setup_matches_public_console_scripts(self):
        setup = (ROOT / "setup.py").read_text(encoding="utf-8")

        self.assertIn(f'version="{__version__}"', setup)
        self.assertIn('description="A skeptical citation auditor for agent writing workflows."', setup)
        self.assertIn('keywords=[', setup)
        self.assertIn('"skeptical-citation-auditor"', setup)
        self.assertIn('"agent-tools"', setup)
        self.assertIn('"mcp"', setup)
        self.assertIn('"research-integrity"', setup)
        self.assertNotIn('"research-agents"', setup)
        self.assertIn('"citeguard=citeguard.cli:main"', setup)
        self.assertIn('"citeguard-mcp=citeguard.mcp.server:main"', setup)
        self.assertIn('find_packages(include=["citeguard", "citeguard.*"])', setup)
        self.assertNotIn(f'"{INTERNAL_PACKAGE}"', setup)
        self.assertNotIn(f'"{INTERNAL_PACKAGE}.*"', setup)
        self.assertIn('"mcp": [', setup)
        self.assertIn('"pdf": [', setup)
        self.assertIn('"pypdf>=4,<6"', setup)
        self.assertIn('"Topic :: Text Processing :: Linguistic"', setup)
        self.assertIn('"Typing :: Typed"', setup)
        self.assertIn('"Documentation": "https://github.com/xiaweiyi713/citeguard#readme"', setup)
        self.assertIn('package_data={"citeguard": ["py.typed"]}', setup)

    def test_release_gate_records_public_only_package_discovery(self):
        summary = {"ok": True, "steps": []}

        _record_project_metadata_contract(summary, ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "project_metadata_contract")
        self.assertIn("docs/github_launch.md", summary["steps"][0]["checked_files"])
        self.assertIn("CITATION.cff", summary["steps"][0]["checked_files"])
        self.assertEqual(summary["steps"][0]["citation_metadata"]["required_phrase_count"], 10)
        self.assertEqual(summary["steps"][0]["citation_metadata"]["stale_phrase_count"], 3)
        self.assertIn("skeptical citation auditor", summary["steps"][0]["citation_metadata"]["policy"])
        self.assertEqual(summary["steps"][0]["readme_package_surface"]["required_phrase_count"], 4)
        self.assertEqual(summary["steps"][0]["readme_package_surface"]["stale_phrase_count"], 4)
        self.assertIn("published product surface", summary["steps"][0]["readme_package_surface"]["policy"])
        self.assertEqual(summary["steps"][0]["experimental_module_boundary"]["required_phrase_count"], 10)
        self.assertIn("source-checkout experiments", summary["steps"][0]["experimental_module_boundary"]["policy"])
        self.assertEqual(summary["steps"][0]["github_launch_copy"]["required_phrase_count"], 9)
        self.assertEqual(summary["steps"][0]["github_launch_copy"]["stale_phrase_count"], 5)
        self.assertIn("agent-facing skeptical citation auditor", summary["steps"][0]["github_launch_copy"]["policy"])
        self.assertIn("skeptical-citation-auditor", summary["steps"][0]["package_keywords"])
        self.assertIn("agent-tools", summary["steps"][0]["package_keywords"])
        self.assertIn("research-integrity", summary["steps"][0]["package_keywords"])
        discovery = summary["steps"][0]["public_package_discovery"]
        self.assertEqual(discovery["pyproject_include"], ["citeguard", "citeguard.*"])
        self.assertEqual(discovery["setup_find_packages_include"], ["citeguard", "citeguard.*"])
        self.assertFalse(discovery["legacy_namespace_included"])
        self.assertTrue(discovery["published_artifacts_exclude_legacy_src"])
        self.assertTrue(summary["steps"][0]["typed_package"])

    def test_runtime_version_surfaces_match_package_metadata(self):
        api_app = (ROOT / "citeguard" / "api" / "app.py").read_text(encoding="utf-8")
        factory = (ROOT / "citeguard" / "retrieval" / "scholarly_clients" / "factory.py").read_text(encoding="utf-8")
        http_client = (ROOT / "citeguard" / "retrieval" / "scholarly_clients" / "http.py").read_text(encoding="utf-8")

        self.assertEqual(DEFAULT_USER_AGENT, f"CiteGuard/{__version__}")
        self.assertIn("version=__version__", api_app)
        self.assertIn('DEFAULT_USER_AGENT = f"CiteGuard/{__version__}"', factory)
        self.assertIn('DEFAULT_HTTP_USER_AGENT = f"CiteGuard/{__version__}"', http_client)

    def test_manifest_ships_docs_examples_eval_data_and_skill(self):
        manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8")

        expected_patterns = [
            r"include README\.md",
            r"include CITATION\.cff",
            r"include CHANGELOG\.md",
            r"recursive-include docs \*\.md \*\.svg \*\.csv \*\.yml",
            r"recursive-include examples \*\.json \*\.jsonl \*\.md \*\.txt",
            r"recursive-include data/eval \*\.json",
            r"recursive-include skills \*\.md \*\.yaml",
            r"recursive-include scripts \*\.py",
            r"prune docs/superpowers",
            r"prune docs/issues",
            r"exclude docs/proposal\.md",
            r"exclude scripts/run_agent\.py",
            r"exclude scripts/evaluate\.py",
        ]
        for pattern in expected_patterns:
            with self.subTest(pattern=pattern):
                self.assertRegex(manifest, pattern)

    def test_sdist_release_files_include_runtime_configs(self):
        expected_files = _expected_sdist_release_files()

        for relative in [
            "configs/experiment.yaml",
            "configs/model.yaml",
            "configs/retrieval.yaml",
            "configs/verifier.yaml",
        ]:
            with self.subTest(relative=relative):
                self.assertIn(relative, expected_files)
                self.assertTrue((ROOT / relative).exists())

    def test_release_gate_records_release_artifact_contract(self):
        summary = {"ok": True, "steps": []}

        _record_release_artifact_contract_gate(summary, ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "release_artifact_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertIn("docs/releases/v0.1.0.md", summary["steps"][0]["release_notes"])
        self.assertIn("docs/releases/v0.1.0.md", summary["steps"][0]["expected_sdist_release_files"])
        self.assertIn("configs/retrieval.yaml", summary["steps"][0]["expected_sdist_release_files"])
        self.assertIn("recursive-include configs *.yaml", summary["steps"][0]["manifest_rules_checked"])
        self.assertIn("src/", summary["steps"][0]["excluded_legacy_paths"])
        self.assertIn("historical planning surfaces", summary["steps"][0]["policy"])

    def test_package_smoke_rejects_generated_archive_files(self):
        smoke = (ROOT / "scripts" / "smoke_package.py").read_text(encoding="utf-8")

        self.assertIn('"pdf"', smoke)
        self.assertIn("Requires-Dist", smoke)
        self.assertIn("pypdf", smoke)
        self.assertIn('"CITATION.cff"', smoke)
        self.assertIn('"citeguard/__main__.py"', smoke)
        self.assertIn('"docs/benchmark_design.md"', smoke)
        self.assertIn('"docs/benchmark_todo.md"', smoke)
        self.assertIn('"docs/chinaxiv_spike.md"', smoke)
        self.assertIn('"docs/configuration.md"', smoke)
        self.assertIn('"docs/github_launch.md"', smoke)
        self.assertIn('"docs/public_api_migration.md"', smoke)
        self.assertIn('"docs/support_labeling_guidelines.md"', smoke)
        self.assertIn('"examples/references.md"', smoke)
        self.assertIn("_SDIST_COPY_IGNORE_PATTERNS", smoke)
        self.assertIn('"experiments"', smoke)
        self.assertIn('"paper"', smoke)
        self.assertIn('".ipynb_checkpoints"', smoke)
        self.assertIn("_assert_archive_excludes_legacy_agent_scripts", smoke)
        self.assertIn("_assert_archive_excludes_historical_planning_docs", smoke)
        self.assertIn('"-m", "citeguard"', smoke)
        _assert_archive_excludes_generated_files(
            {"citeguard/__init__.py", "citeguard.egg-info/SOURCES.txt"},
            archive_label="unit",
        )
        with self.assertRaisesRegex(RuntimeError, "generated/local files"):
            _assert_archive_excludes_generated_files(
                {
                    "citeguard/__pycache__/__init__.cpython-311.pyc",
                    "docs/.DS_Store",
                },
                archive_label="unit",
            )
        _assert_archive_excludes_legacy_agent_scripts(
            {"scripts/demo_verify.py", "scripts/smoke_package.py"},
            archive_label="unit",
        )
        with self.assertRaisesRegex(RuntimeError, "legacy writing-agent prototype scripts"):
            _assert_archive_excludes_legacy_agent_scripts(
                {"scripts/run_agent.py", "scripts/evaluate.py"},
                archive_label="unit",
            )
        _assert_archive_excludes_historical_planning_docs(
            {"docs/cli_reference.md", "docs/release_checklist.md"},
            archive_label="unit",
        )
        with self.assertRaisesRegex(RuntimeError, "historical planning docs"):
            _assert_archive_excludes_historical_planning_docs(
                {
                    "docs/proposal.md",
                    "docs/superpowers/plans/old.md",
                    "docs/issues/benchmark_phase1_issue_final.md",
                },
                archive_label="unit",
            )

    def test_citation_cff_matches_current_agent_auditor_package(self):
        citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")

        required_phrases = [
            'title: "CiteGuard"',
            'type: software',
            'version: "0.1.0"',
            "skeptical citation auditor for agent writing workflows",
            'repository-code: "https://github.com/xiaweiyi713/citeguard"',
            'url: "https://github.com/xiaweiyi713/citeguard#readme"',
            "citation verification",
            "skeptical citation auditor",
            "agent tools",
            "research integrity",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, citation)

        stale_phrases = [
            "research agent prototype",
            "research agents",
            "falsification-first research agent",
        ]
        for phrase in stale_phrases:
            with self.subTest(stale_phrase=phrase):
                self.assertNotIn(phrase, citation)

    def test_package_smoke_rejects_legacy_src_namespace_in_archives(self):
        _assert_archive_excludes_legacy_src_namespace(
            {"citeguard/__init__.py", "docs/cli_reference.md"},
            archive_label="unit",
        )
        with self.assertRaisesRegex(RuntimeError, "legacy src compatibility namespace"):
            _assert_archive_excludes_legacy_src_namespace(
                {"citeguard/__init__.py", "src/__init__.py", "src/verification/verify.py"},
                archive_label="unit",
            )

    def test_published_package_config_only_discovers_citeguard_packages(self):
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        setup_py = (ROOT / "setup.py").read_text(encoding="utf-8")

        self.assertIn('include = ["citeguard", "citeguard.*"]', pyproject)
        self.assertNotIn(f'"{INTERNAL_PACKAGE}"', pyproject)
        self.assertNotIn(f'"{INTERNAL_PACKAGE}.*"', pyproject)
        self.assertIn('find_packages(include=["citeguard", "citeguard.*"])', setup_py)
        self.assertNotIn(f'"{INTERNAL_PACKAGE}"', setup_py)
        self.assertNotIn(f'"{INTERNAL_PACKAGE}.*"', setup_py)

    def test_package_smoke_validates_distribution_metadata_contract(self):
        good_metadata = f"""Metadata-Version: 2.1
Name: citeguard
Version: {__version__}
Summary: A skeptical citation auditor for agent writing workflows.
Keywords: citation-verification skeptical-citation-auditor agent-tools mcp scientific-writing claim-support research-integrity hallucination-mitigation evidence-attribution
Requires-Python: >=3.9
Classifier: Intended Audience :: Science/Research
Classifier: License :: OSI Approved :: MIT License
Classifier: Programming Language :: Python :: 3
Classifier: Programming Language :: Python :: 3.10
Classifier: Topic :: Scientific/Engineering :: Artificial Intelligence
Classifier: Topic :: Scientific/Engineering :: Information Analysis
Classifier: Topic :: Text Processing :: Linguistic
Classifier: Typing :: Typed
Provides-Extra: api
Provides-Extra: mcp
Provides-Extra: models
Provides-Extra: pdf
Requires-Dist: mcp>=1.2; extra == "mcp"
Requires-Dist: pypdf<6,>=4; extra == "pdf"
Project-URL: Homepage, https://github.com/xiaweiyi713/citeguard
Project-URL: Repository, https://github.com/xiaweiyi713/citeguard
Project-URL: Issues, https://github.com/xiaweiyi713/citeguard/issues
Project-URL: Changelog, https://github.com/xiaweiyi713/citeguard/blob/main/CHANGELOG.md
Project-URL: Documentation, https://github.com/xiaweiyi713/citeguard#readme
License-File: LICENSE
"""
        _assert_distribution_metadata_contract(good_metadata, archive_label="unit")

        bad_metadata = good_metadata.replace(
            "A skeptical citation auditor for agent writing workflows.",
            "TODO research agent prototype",
        )
        with self.assertRaisesRegex(RuntimeError, "metadata contract failed"):
            _assert_distribution_metadata_contract(bad_metadata, archive_label="unit")

    def test_public_docs_tests_and_scripts_do_not_use_src_imports(self):
        public_paths = [
            ROOT / "README.md",
            ROOT / "CHANGELOG.md",
            ROOT / "ROADMAP.md",
            ROOT / "pyproject.toml",
            ROOT / "setup.py",
            ROOT / "docs" / "architecture.md",
            ROOT / "docs" / "benchmark_design.md",
            ROOT / "docs" / "benchmark_todo.md",
            ROOT / "docs" / "chinaxiv_spike.md",
            ROOT / "docs" / "cli_reference.md",
            ROOT / "docs" / "configuration.md",
            ROOT / "docs" / "mcp_setup.md",
            ROOT / "docs" / "error_codes.md",
            ROOT / "docs" / "github_launch.md",
            ROOT / "docs" / "release_checklist.md",
            ROOT / "docs" / "security_compliance.md",
            ROOT / "docs" / "support_labeling_guidelines.md",
            ROOT / "skills" / "citeguard-verify" / "SKILL.md",
            ROOT / "skills" / "citeguard-verify" / "references" / "examples.md",
            ROOT / "skills" / "citeguard-verify" / "agents" / "openai.yaml",
        ]
        public_paths.extend(sorted((ROOT / "examples").glob("*.json")))
        public_paths.extend(sorted((ROOT / "examples").glob("*.jsonl")))
        public_paths.extend(sorted((ROOT / "examples").glob("*.md")))
        public_paths.extend(sorted((ROOT / "tests").glob("test_*.py")))
        public_paths.extend(sorted((ROOT / "scripts").glob("*.py")))

        pattern = re.compile(r"\b(from {0}\.|import {0}\b|{0}\.)".format(INTERNAL_PACKAGE))
        offenders = []
        for path in public_paths:
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                offenders.append(str(path.relative_to(ROOT)))

        self.assertEqual(offenders, [])

    def test_public_api_contract_scans_release_facing_examples_and_skill_references(self):
        public_paths = {path.relative_to(ROOT).as_posix() for path in _public_api_contract_paths(ROOT)}

        for expected in [
            "README.md",
            "ROADMAP.md",
            "pyproject.toml",
            "setup.py",
            "docs/chinaxiv_spike.md",
            "docs/configuration.md",
            "docs/releases/v0.1.0.md",
            "examples/citations.json",
            "examples/citations.jsonl",
            "examples/claim_citations.json",
            "examples/claim_citations.jsonl",
            "examples/claim_citations_full_text_file.json",
            "examples/lawful_full_text_excerpt.txt",
            "examples/references.md",
            "skills/citeguard-verify/references/examples.md",
            "skills/citeguard-verify/agents/openai.yaml",
        ]:
            with self.subTest(expected=expected):
                self.assertIn(expected, public_paths)

    def test_public_citeguard_package_does_not_depend_on_legacy_src_package(self):
        pattern = re.compile(r"\b(from {0}\.|import {0}\b|{0}\.)".format(INTERNAL_PACKAGE))
        offenders = []
        for path in sorted((ROOT / "citeguard").rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if pattern.search(text):
                offenders.append(str(path.relative_to(ROOT)))

        self.assertEqual(offenders, [])

    def test_public_docs_are_citeguard_package_first(self):
        readme = ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8"))
        benchmark_design = (ROOT / "docs" / "benchmark_design.md").read_text(encoding="utf-8")

        self.assertIn("citeguard/", readme)
        self.assertIn("`citeguard.*` auditor package", readme)
        self.assertIn("not part of the published package surface", readme)
        self.assertIn("source-checkout experiments and benchmark/API utilities", readme)
        self.assertIn("src/                       # legacy compatibility shims", readme)
        self.assertIn("docs/public_api_migration.md", readme)
        self.assertNotIn("docs/superpowers/", readme)
        self.assertNotIn("docs/proposal.md", readme)
        self.assertNotIn("Research framing / proposal", readme)
        self.assertNotIn('writing agent" prototype', readme)
        self.assertNotIn("writing-agent and benchmark surfaces", readme)
        self.assertNotIn("research agent prototype", readme)
        self.assertNotIn("falsification-first research agent", readme)
        self.assertNotIn("src/\n  verification/", readme)
        self.assertIn("docs/configuration.md", readme)
        self.assertIn("citeguard/benchmark/metrics.py", benchmark_design)
        self.assertNotIn("src/benchmark/metrics.py", benchmark_design)

    def test_chinese_quickstart_separates_installed_package_from_source_demo(self):
        readme_zh = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("已安装包场景请优先使用 `citeguard` / `citeguard-mcp` 入口", readme_zh)
        self.assertIn("源码签出场景还可以运行 `python3 scripts/demo_verify.py`", readme_zh)
        self.assertNotIn("或直接 `python3 scripts/demo_verify.py` 看实时效果", readme_zh)

    def test_english_demo_separates_source_checkout_from_installed_entrypoints(self):
        readme = ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8"))
        see_it_work = readme.split("## See it work", 1)[1].split("## What it does", 1)[0]

        self.assertIn("From a source checkout, run the demo script yourself", see_it_work)
        self.assertIn("python3 scripts/demo_verify.py", see_it_work)
        self.assertIn("Installed-package users should use the stable `citeguard` CLI", see_it_work)
        self.assertIn("`citeguard-mcp` entry points", see_it_work)

    def test_mcp_install_docs_put_published_package_before_editable_checkout(self):
        readme = ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8"))
        mcp_setup = (ROOT / "docs" / "mcp_setup.md").read_text(encoding="utf-8")
        readme_mcp_section = readme.split("### As an agent tool (MCP)", 1)[1].split("##", 1)[0]

        for label, text in {"README.md": readme_mcp_section, "docs/mcp_setup.md": mcp_setup}.items():
            with self.subTest(label=label):
                self.assertIn('python -m pip install "citeguard[mcp]"', text)
                self.assertIn('python -m pip install -e ".[mcp]"', text)
                self.assertIn("For an installed or published package", text)
                self.assertIn("For a local source checkout", text)
                self.assertLess(
                    text.index('python -m pip install "citeguard[mcp]"'),
                    text.index('python -m pip install -e ".[mcp]"'),
                )

    def test_quickstart_puts_published_package_before_editable_checkout(self):
        readme = ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8"))
        quickstart = readme.split("## Quick start", 1)[1].split("Check your local configuration", 1)[0]

        self.assertIn("For an installed or published package", quickstart)
        self.assertIn("From a local source checkout", quickstart)
        self.assertIn("python -m pip install citeguard", quickstart)
        self.assertIn("python -m pip install -e .", quickstart)
        self.assertLess(
            quickstart.index("python -m pip install citeguard"),
            quickstart.index("python -m pip install -e ."),
        )

    def test_release_notes_put_published_package_before_source_checkout(self):
        notes = (ROOT / "docs" / "releases" / "v0.1.0.md").read_text(encoding="utf-8")
        recommended = notes.split("## Recommended First Commands", 1)[1].split("## Release Verification", 1)[0]

        self.assertIn("python -m pip install citeguard", recommended)
        self.assertIn("For source checkout release rehearsal", recommended)
        self.assertIn('python -m pip install "citeguard[mcp]"', recommended)
        self.assertIn('python -m pip install -e ".[mcp]"', recommended)
        self.assertLess(
            recommended.index("python -m pip install citeguard"),
            recommended.index("python -m pip install -e ."),
        )
        self.assertLess(
            recommended.index('python -m pip install "citeguard[mcp]"'),
            recommended.index('python -m pip install -e ".[mcp]"'),
        )

    def test_chinaxiv_spike_uses_public_adapter_paths(self):
        spike = (ROOT / "docs" / "chinaxiv_spike.md").read_text(encoding="utf-8")

        required_phrases = [
            "citeguard/retrieval/scholarly_clients/base.py",
            "citeguard/retrieval/scholarly_clients/factory.py",
            "citeguard/retrieval/scholarly_clients/crossref.py",
            "citeguard/retrieval/scholarly_clients/openalex.py",
            "We will **not** integrate ChinaXiv as a metadata source",
            "We will **not** scrape login-gated, paywalled, or otherwise restricted ChinaXiv content",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, spike)

        stale_paths = [
            "src/retrieval/scholarly_clients/base.py",
            "src/retrieval/scholarly_clients/factory.py",
            "src/retrieval/scholarly_clients/crossref.py",
            "src/retrieval/scholarly_clients/openalex.py",
        ]
        for stale_path in stale_paths:
            with self.subTest(stale_path=stale_path):
                self.assertNotIn(stale_path, spike)

    def test_project_proposal_uses_public_package_layout(self):
        proposal = (ROOT / "docs" / "proposal.md").read_text(encoding="utf-8")

        for phrase in [
            "产品接口以 `citeguard.*` 为稳定边界",
            "├── citeguard/",
            "│   ├── runtime.py",
            "│   ├── cli.py",
            "│   ├── mcp/",
            "│   ├── retrieval/",
            "│   ├── verification/",
            "│   ├── benchmark/",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, proposal)

        self.assertNotIn("├── src/", proposal)

    def test_public_api_migration_documents_legacy_deprecation(self):
        migration = (ROOT / "docs" / "public_api_migration.md").read_text(encoding="utf-8")
        legacy_init = (ROOT / INTERNAL_PACKAGE / "__init__.py").read_text(encoding="utf-8")
        legacy_retrieval_init = (ROOT / INTERNAL_PACKAGE / "retrieval" / "__init__.py").read_text(encoding="utf-8")
        legacy_verification_init = (ROOT / INTERNAL_PACKAGE / "verification" / "__init__.py").read_text(encoding="utf-8")

        for public_package in [
            "citeguard.verification",
            "citeguard.retrieval",
            "citeguard.mcp",
            "citeguard.cli",
            "citeguard.runtime",
        ]:
            with self.subTest(public_package=public_package):
                self.assertIn(public_package, migration)

        for phrase in [
            "## Experimental Source-Checkout Modules",
            "`citeguard.orchestrator`",
            "`citeguard.planner`",
            "`citeguard.writer`",
            "not the stable v0.1 product contract",
            "auditor package surface",
        ]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, migration)

        self.assertIn("DeprecationWarning", migration)
        self.assertIn("temporary compatibility bridge", migration)
        self.assertIn("same public `__all__` lists", migration)
        self.assertIn("root package facade", migration)
        self.assertIn("does not export the experimental source-checkout modules", migration)
        self.assertIn("citeguard.__all__", migration)
        self.assertIn("local export", migration)
        self.assertIn("compatibility package is deprecated", legacy_init)
        self.assertIn("from citeguard.version import __version__", legacy_init)
        self.assertIn("from citeguard.retrieval import *", legacy_retrieval_init)
        self.assertIn("from citeguard.retrieval import __all__", legacy_retrieval_init)
        self.assertIn("from citeguard.verification import *", legacy_verification_init)
        self.assertIn("from citeguard.verification import __all__", legacy_verification_init)

    def test_historical_superpowers_docs_do_not_look_like_current_api_guidance(self):
        docs_root = ROOT / "docs" / "superpowers"
        legacy_name = INTERNAL_PACKAGE
        pattern = re.compile(r"\b(from {0}\.|import {0}\b|{0}\.)".format(legacy_name))
        offenders = []
        for path in sorted(docs_root.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            if not pattern.search(text):
                continue
            required_phrases = [
                "Archived historical",
                "pre-migration",
                "stable public `citeguard.*` package",
                "historical compatibility context",
                "docs/public_api_migration.md",
            ]
            missing = [phrase for phrase in required_phrases if phrase not in text]
            if missing:
                offenders.append(f"{path.relative_to(ROOT)} missing {missing}")

        self.assertEqual(offenders, [])

    def test_roadmap_tracks_agent_auditor_release_state(self):
        roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")

        required_phrases = [
            "stable agent-facing skeptical citation auditor",
            "`Alpha agent-auditor package`",
            "Public `citeguard.*` package facades",
            "legacy `src` root package",
            "MCP stdio smoke coverage",
            "Batch citation and claim-support audits with JSON/JSONL input",
            "Source-health/status contracts",
            "checked/failed source separation",
            "SQLite cache schema/version inspection",
            "deterministic offline replay fixtures",
            "Agent skill instructions",
            "false-support risk",
            "human review coverage",
            "full-text evidence opt-in",
            "do not bypass paywalls or gated sources",
            "Codex",
            "Claude Code",
            "Cursor",
            "source outages, model failures, and missing snippets as uncertainty",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, roadmap)

    def test_v010_release_note_matches_current_agent_auditor_package(self):
        release_note = (ROOT / "docs" / "releases" / "v0.1.0.md").read_text(encoding="utf-8")

        required_phrases = [
            "agent-facing skeptical citation auditor",
            "Skeptical citation auditing for agent writing workflows",
            "public `citeguard.*`",
            "`citeguard` CLI and `citeguard-mcp` stdio server",
            "`citeguard verify`, `audit`, `support`, `support-set`, `support-audit`",
            "JSON and JSONL batch audits",
            "Offline MCP stdio smoke coverage",
            "Source-health/status contracts",
            "stable `error.next_action`,",
            "`error.retryable`, and `error.category`",
            "SQLite cache inspect, clear, deterministic export",
            "Support-eval seed package",
            "python scripts/smoke_package.py --install-mode wheel --extra mcp --with-deps --mcp-stdio-smoke",
            "python scripts/smoke_published_package.py --version 0.1.0 --extra mcp --require-extra-import mcp --mcp-stdio-smoke --run",
            "python scripts/release_package_gate.py --skip-install-smoke --include-testpypi-smoke-plan --include-testpypi-mcp-smoke-plan",
            "isolated",
            "`config_errors`",
            "not a final legal, bibliographic, or research-integrity authority",
            "not a human-reviewed benchmark",
            "does not scrape gated sources, bypass paywalls",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, release_note)

        stale_phrases = [
            "research prototype",
            "run_agent.py",
            "`CCEG` graph model",
            "constrained writing",
            "SupportVerifier",
        ]
        for phrase in stale_phrases:
            with self.subTest(stale_phrase=phrase):
                self.assertNotIn(phrase, release_note)

    def test_github_launch_copy_matches_current_agent_auditor_package(self):
        launch = (ROOT / "docs" / "github_launch.md").read_text(encoding="utf-8")

        required_phrases = [
            "agent-facing skeptical citation auditor",
            "Skeptical citation auditing for agent writing workflows",
            "public `citeguard.*` Python package",
            "`citeguard` CLI",
            "`citeguard-mcp` stdio server",
            "JSON/JSONL batch audits",
            "not proof that a citation is fabricated",
            "source-health aware outputs",
            "不可达来源视为不确定性而不是伪造证据",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, launch)

        stale_phrases = [
            "research prototype",
            "research agent prototype",
            "First public research prototype",
            "Agent 原型",
            "Falsification-first research agent",
        ]
        for phrase in stale_phrases:
            with self.subTest(stale_phrase=phrase):
                self.assertNotIn(phrase, launch)

    def test_error_code_documentation_matches_public_registry(self):
        docs = (ROOT / "docs" / "error_codes.md").read_text(encoding="utf-8")
        stable_codes_section = docs.split("## Stable Codes", 1)[1].split("## Details Contract", 1)[0]
        documented = set(re.findall(r"\| `([^`]+)` \|", stable_codes_section))
        documented_rows = _error_code_doc_rows(stable_codes_section)

        self.assertEqual(documented, STABLE_ERROR_CODES)
        self.assertEqual(set(ERROR_CODE_NEXT_ACTION), STABLE_ERROR_CODES)
        self.assertEqual(set(ERROR_CODE_RETRYABLE), STABLE_ERROR_CODES)
        self.assertEqual(set(ERROR_CODE_CATEGORY), STABLE_ERROR_CODES)
        for code in STABLE_ERROR_CODES:
            with self.subTest(code=code):
                self.assertEqual(documented_rows[code]["category"], ERROR_CODE_CATEGORY[code])
                self.assertEqual(documented_rows[code]["retryable"], str(ERROR_CODE_RETRYABLE[code]).lower())
                self.assertEqual(documented_rows[code]["recovery"], ERROR_CODE_RECOVERY[code])
        self.assertTrue(set(ERROR_CODE_NEXT_ACTION.values()).issubset(STABLE_NEXT_ACTIONS))
        self.assertIn("ERROR_SCHEMA_VERSION", docs)
        self.assertIn(f'"schema_version": {ERROR_SCHEMA_VERSION}', docs)
        self.assertIn('"recovery": "Ask for a DOI, arXiv id, title, or pasted reference."', docs)
        self.assertIn('"next_action": "provide_missing_input"', docs)
        self.assertIn('"retryable": false', docs)
        self.assertIn('"category": "missing_input"', docs)
        self.assertIn("error_code_registry()", docs)
        self.assertIn("`error.recovery` is present on every error payload", docs)
        self.assertIn("`error.next_action` is present on every error payload", docs)
        self.assertIn("`error.retryable` is true only for transient retry candidates", docs)
        self.assertIn("`error.category` gives a compact stable class", docs)
        self.assertIn("`error.retryable` is present on every error payload", docs)
        self.assertIn("`error.category` is present on every error payload", docs)
        self.assertIn("Prefer `error.retryable` and `error.category`", docs)
        self.assertIn("ERROR_CODE_NEXT_ACTION", docs)
        self.assertIn("ERROR_CODE_RETRYABLE", docs)
        self.assertIn("ERROR_CODE_CATEGORY", docs)
        registry = error_code_registry()
        self.assertEqual(registry["schema_version"], ERROR_SCHEMA_VERSION)
        self.assertEqual(set(registry["codes"]), STABLE_ERROR_CODES)
        self.assertEqual(registry["codes"]["missing_citation_input"]["next_action"], "provide_missing_input")
        self.assertFalse(registry["codes"]["missing_citation_input"]["retryable"])
        self.assertEqual(registry["codes"]["missing_citation_input"]["category"], "missing_input")
        self.assertTrue(registry["codes"]["source_unavailable"]["retryable"])
        self.assertEqual(registry["codes"]["source_unavailable"]["category"], "source_limited")

    def test_next_action_documentation_matches_public_registry(self):
        docs = (ROOT / "docs" / "error_codes.md").read_text(encoding="utf-8")
        next_action_section = docs.split("## Stable next_action Values", 1)[1].split("## Stable Codes", 1)[0]
        documented = set(re.findall(r"\| `([^`]+)` \|", next_action_section))

        self.assertEqual(documented, STABLE_NEXT_ACTIONS)
        self.assertIn("Prefer `next_action` for workflow branching", docs)

    def test_ci_runs_release_and_mcp_smoke_gates(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn("python scripts/eval_verification.py", workflow)
        self.assertIn("python scripts/eval_support.py --validate-only", workflow)
        self.assertIn("python scripts/eval_support.py --report --split test", workflow)
        self.assertIn("python scripts/compare_support_baselines.py --split test", workflow)
        self.assertIn("--label-sidecar data/eval/support_eval_label_sidecar.json", workflow)
        self.assertIn("--min-sidecar-coverage 1.0", workflow)
        self.assertIn("--min-human-reviewed 0", workflow)
        self.assertIn("--min-high-risk-reviewed 0", workflow)
        self.assertIn("--min-high-risk-reviewed-by-language zh=0", workflow)
        self.assertIn("python scripts/smoke_package.py --install-mode wheel", workflow)
        self.assertIn("python scripts/smoke_package.py --install-mode sdist", workflow)
        self.assertIn(
            "python scripts/release_package_gate.py --skip-install-smoke --include-mcp-extra-smoke --require-mcp-extra-smoke",
            workflow,
        )
        self.assertIn(
            "python scripts/release_package_gate.py --skip-install-smoke --include-mcp-stdio-smoke --require-mcp-stdio-smoke",
            workflow,
        )
        self.assertIn("python -m pip install build twine", workflow)
        self.assertIn("python scripts/release_package_gate.py --skip-install-smoke --require-build-tools", workflow)
        self.assertIn('python-version: "3.10"', workflow)
        self.assertIn('python -m pip install -e ".[mcp]"', workflow)
        self.assertIn("python scripts/smoke_mcp.py --require-sdk", workflow)

    def test_release_gate_records_ci_mcp_smoke_contract(self):
        summary = {"ok": True, "steps": []}

        _record_ci_mcp_smoke_contract_gate(summary, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "ci_mcp_smoke_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["workflow"], ".github/workflows/ci.yml")
        self.assertEqual(summary["steps"][0]["job"], "mcp-smoke")
        self.assertEqual(summary["steps"][0]["python_version"], "3.10")
        commands = summary["steps"][0]["required_commands"]
        self.assertIn('python -m pip install -e ".[mcp]"', commands)
        self.assertIn("python scripts/smoke_mcp.py --require-sdk", commands)
        self.assertIn(
            "python scripts/release_package_gate.py --skip-install-smoke --include-mcp-stdio-smoke --require-mcp-stdio-smoke",
            commands,
        )
        self.assertIn("Python 3.10+ MCP extra and stdio smoke gates", summary["steps"][0]["policy"])

    def test_release_package_gate_is_documented_and_packaged(self):
        readme = ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8"))
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        checklist = (ROOT / "docs" / "release_checklist.md").read_text(encoding="utf-8")
        smoke = (ROOT / "scripts" / "smoke_package.py").read_text(encoding="utf-8")
        gate = (ROOT / "scripts" / "release_package_gate.py").read_text(encoding="utf-8")
        combined = f"{readme}\n{changelog}\n{checklist}\n{smoke}\n{gate}"

        required_phrases = [
            "scripts/release_package_gate.py",
            "scripts/smoke_published_package.py",
            "installed-version checks against the requested `--version`",
            "License-File: LICENSE",
            "--require-build-tools",
            "--skip-install-smoke",
            "--include-mcp-extra-smoke",
            "--require-mcp-extra-smoke",
            "--include-mcp-stdio-smoke",
            "--require-mcp-stdio-smoke",
            "--include-published-smoke-plan",
            "--include-published-mcp-smoke-plan",
            "--include-published-smoke-run",
            "--include-published-mcp-smoke-run",
            "--include-testpypi-smoke-plan",
            "--include-testpypi-mcp-smoke-plan",
            "--include-testpypi-smoke-run",
            "--include-testpypi-mcp-smoke-run",
            "--skip-support-label-gate",
            "--skip-support-review-queue",
            "--support-label-sidecar",
            "--support-eval-dataset",
            "--min-high-risk-reviewed-by-language",
            "--with-deps",
            "--extra mcp",
            "support_label_sidecar_gate",
            "release_artifact_contract",
            "_record_release_artifact_contract_gate",
            "release artifacts ship public docs, examples, configs, eval fixtures, scripts, and the agent skill",
            "benchmark_claim_safety",
            "_record_benchmark_claim_safety_gate",
            "unsafe_human_reviewed_benchmark_claims",
            "do not describe the synthetic seed set as a human-reviewed benchmark",
            "legacy_src_shim_contract",
            "_record_legacy_src_shim_contract",
            "legacy shims only; new code imports citeguard.*",
            "public_api_contract",
            "_record_public_api_contract_gate",
            "README, tests, scripts, user-facing docs, and citeguard.* code stay on public citeguard.* imports",
            "public_offenders",
            "package_offenders",
            "local_package_smoke_public_api_contract",
            "stable_error_codes_from_errors_module",
            "cache_replay_fixture",
            "_record_cache_replay_fixture_gate",
            "cache export",
            "--deterministic",
            "--operation",
            "selected_cache_entry_count",
            "filtered manifests, inspect output, and clear output keep total and selected cache counts separate",
            "byte_identical",
            "raw match score provenance",
            "cache inspect",
            "cache clear",
            "non-sensitive counts",
            "preserve schema metadata",
            "error_codes_contract",
            "_record_error_codes_contract_gate",
            "stable error codes, recovery guidance, next_action mappings, and docs stay synchronized for agents",
            "ERROR_CODE_RECOVERY",
            "ERROR_CODE_NEXT_ACTION",
            "cli_error_contract",
            "_record_cli_error_contract_gate",
            "verify_missing_citation",
            "audit_missing_file",
            "support_audit_invalid_jsonl",
            "source_outage_safety",
            "_record_source_outage_safety_gate",
            "all_sources_failed",
            "outage_limited",
            "retry_or_check_source_health",
            "counterevidence_safety_contract",
            "_record_counterevidence_safety_contract_gate",
            "counter-evidence search returns review leads only, not contradiction verdicts",
            "full_text_evidence_boundary_contract",
            "_record_full_text_evidence_boundary_contract_gate",
            "local/user-provided opt-in evidence",
            "abstract-only results are not upgraded",
            "support_set_aggregation_contract",
            "_record_support_set_aggregation_contract_gate",
            "multiple weak citation-set evidence remains tentative",
            "multiple_weak_support",
            "live_source_health_contract",
            "_record_live_source_health_contract_gate",
            "release gate enforces source-level health for OpenAlex, Crossref, arXiv, and Semantic Scholar",
            "semantic-scholar",
            "api_key_configured",
            "rate_limited",
            "security_compliance_contract",
            "_record_security_compliance_contract_gate",
            "fixture_bypasses_live_sources",
            "missing_contact_email",
            "semantic_scholar",
            "not_required",
            "blocked_gated_source_suffixes",
            "remote_evidence_policy",
            "agent_skill_contract",
            "_record_agent_skill_contract_gate",
            "without silent edits or source-outage fabrication overclaims",
            "batch_workflow_examples",
            "_record_batch_workflow_examples_gate",
            "audit_metadata_mismatch",
            "audit_metadata_suggested_citation_present",
            "examples/references.md",
            "examples/claim_citations.jsonl",
            "examples/claim_citations_full_text_file.json",
            "examples/lawful_full_text_excerpt.txt",
            "support_omitted_review_summary",
            "support_risk_provenance",
            "support_engine",
            "resolution_verdict",
            "evidence_source_name",
            "evidence_source_field",
            "support_set_summary",
            "support_review_queue",
            "support_baseline_comparison",
            "support_review_queue_annotation_packet",
            "_record_support_review_queue_gate",
            "_record_support_baseline_comparison_gate",
            "_record_support_review_queue_annotation_packet_gate",
            "false_support_triage_present",
            "rows_missing_active_risk_slices",
            "heuristic_top_false_support_risk_slice",
            "merge_report.adjudication_queue",
            "adjudication_template",
            "reviewer rationales",
            "--review-queue-only",
            "--from-review-queue",
            '"review_queue_rank"',
            'quality_gate.get("review_queue_case_ids", [])',
            'quality_gate.get("critical_review_case_ids", [])',
            'gate.get("thresholds", {})',
            'gate.get("metrics", {})',
            'gate.get("failures", [])',
            "structured",
            "_MCP_EXTRA_SMOKE",
            "mcp_extra_wheel_install_smoke",
            "mcp_stdio_smoke_contract",
            "_record_mcp_stdio_smoke_contract_gate",
            "MCP stdio smoke must cover initialize, list_tools",
            "batch tool metadata descriptions",
            "fixture-backed verification",
            "structured_errors",
            "ci_mcp_smoke_contract",
            "_record_ci_mcp_smoke_contract_gate",
            "CI must run Python 3.10+ MCP extra and stdio smoke gates",
            "mcp_error_contract",
            "_record_mcp_error_contract_gate",
            "MCP direct tool errors must use the shared ok=false schema",
            "mcp_stdio_smoke",
            "published_package_smoke_plan",
            "published_mcp_smoke_plan",
            "testpypi_package_smoke_plan",
            "testpypi_mcp_smoke_plan",
            "published_package_smoke_run",
            "published_mcp_smoke_run",
            "testpypi_package_smoke_run",
            "testpypi_mcp_smoke_run",
            "failed_checks",
            "smoke_cwd",
            "release summary includes `config_errors`",
            "Non-empty `config_errors` fail the",
            "MCP extra install smoke requires Python 3.10+",
            "MCP stdio smoke requires Python 3.10+",
            "python -m build",
            "python -m twine check",
            "pep517_build_and_twine_check",
            "project_metadata_contract",
            "distribution metadata contract",
            "python -m citeguard",
            "python scripts/smoke_package.py --install-mode wheel --extra mcp --with-deps --mcp-stdio-smoke",
            "drives the installed stdio server through an offline MCP client",
            "local wheel MCP stdio package smoke coverage",
            "`citeguard-mcp` entry point through an offline MCP client before release",
            "python scripts/release_package_gate.py --skip-install-smoke --include-mcp-extra-smoke --require-mcp-extra-smoke",
            "python scripts/release_package_gate.py --skip-install-smoke --include-mcp-stdio-smoke --require-mcp-stdio-smoke",
            "python scripts/release_package_gate.py --skip-install-smoke --include-published-smoke-plan --include-published-mcp-smoke-plan",
            "python scripts/release_package_gate.py --skip-install-smoke --include-testpypi-smoke-plan --include-testpypi-mcp-smoke-plan",
            "python scripts/release_package_gate.py --skip-install-smoke --include-testpypi-smoke-run --include-testpypi-mcp-smoke-run",
            "python scripts/release_package_gate.py --skip-install-smoke --include-published-smoke-run --include-published-mcp-smoke-run",
            "python scripts/release_package_gate.py --require-build-tools --min-high-risk-reviewed-by-language zh=0",
            "python scripts/smoke_mcp.py --require-sdk",
            "python scripts/smoke_published_package.py --version 0.1.0",
            "root facade API checks",
            "`error_code_registry()`",
            "--index-url https://test.pypi.org/simple/",
            "--extra-index-url https://pypi.org/simple",
            "--require-extra-import mcp",
            "post-publish MCP stdio smoke coverage to call",
            "`check_claim_support_set_tool` and verify `support_mode_details`",
            "conservative no-unstated-full-text support policy fields",
            "mcp_stdio_smoke_requires_mcp_extra",
            "configuration error",
            "`--mcp-stdio-smoke` is used without `--extra mcp`",
            "isolated `smoke-cwd` with `PYTHONPATH` removed",
            "repository-local sources cannot hide",
            "`--require-extra-import` accepts only",
            "invalid_required_extra_import",
            "citeguard.mcp.server",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_readme_test_command_avoids_stale_fixed_test_count(self):
        readme = ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8"))
        tests_section = readme.split("## Tests & reproducibility", 1)[1].split("## Cache and reproducibility", 1)[0]

        self.assertIn("python3 -m unittest discover -s tests -v", tests_section)
        self.assertIn("full unittest suite", tests_section)
        self.assertIn("optional MCP stdio smoke skips without the MCP SDK", tests_section)
        self.assertIsNone(re.search(r"\b\d+\s+tests\b", tests_section))

    def test_release_gate_records_mcp_extra_smoke_policy(self):
        summary = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 9)):
            _record_mcp_extra_smoke(summary, python="python3", project_root=ROOT, require=False)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "mcp_extra_wheel_install_smoke")
        self.assertEqual(summary["steps"][0]["status"], "skipped")

        required = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 9)):
            _record_mcp_extra_smoke(required, python="python3", project_root=ROOT, require=True)

        self.assertFalse(required["ok"])
        self.assertEqual(required["steps"][0]["status"], "failed")

        dispatched = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 10)), mock.patch(
            "scripts.release_package_gate._record_subprocess_step"
        ) as record:
            _record_mcp_extra_smoke(dispatched, python="python3.10", project_root=ROOT, require=True)

        record.assert_called_once()
        args, kwargs = record.call_args
        self.assertEqual(args[1], "mcp_extra_wheel_install_smoke")
        self.assertEqual(
            args[2],
            [
                "python3.10",
                "scripts/smoke_package.py",
                "--install-mode",
                "wheel",
                "--extra",
                "mcp",
                "--with-deps",
                "--mcp-stdio-smoke",
            ],
        )
        self.assertEqual(kwargs["cwd"], ROOT)

    def test_release_gate_records_mcp_stdio_smoke_policy(self):
        summary = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 9)):
            _record_mcp_stdio_smoke(summary, python="python3", project_root=ROOT, require=False)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "mcp_stdio_smoke")
        self.assertEqual(summary["steps"][0]["status"], "skipped")
        self.assertIn("Python 3.10+", summary["steps"][0]["message"])

        required_py39 = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 9)):
            _record_mcp_stdio_smoke(required_py39, python="python3", project_root=ROOT, require=True)

        self.assertFalse(required_py39["ok"])
        self.assertEqual(required_py39["steps"][0]["status"], "failed")

        missing_sdk = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 10)), mock.patch(
            "scripts.release_package_gate._module_available", return_value=False
        ):
            _record_mcp_stdio_smoke(missing_sdk, python="python3.10", project_root=ROOT, require=False)

        self.assertTrue(missing_sdk["ok"])
        self.assertEqual(missing_sdk["steps"][0]["status"], "skipped")
        self.assertIn("MCP SDK is not installed", missing_sdk["steps"][0]["message"])
        self.assertIn('python -m pip install "citeguard[mcp]"', missing_sdk["steps"][0]["message"])
        self.assertLess(
            missing_sdk["steps"][0]["message"].index('python -m pip install "citeguard[mcp]"'),
            missing_sdk["steps"][0]["message"].index('python -m pip install -e ".[mcp]"'),
        )

        required_missing_sdk = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 10)), mock.patch(
            "scripts.release_package_gate._module_available", return_value=False
        ):
            _record_mcp_stdio_smoke(required_missing_sdk, python="python3.10", project_root=ROOT, require=True)

        self.assertFalse(required_missing_sdk["ok"])
        self.assertEqual(required_missing_sdk["steps"][0]["status"], "failed")

        dispatched = {"ok": True, "steps": []}
        with mock.patch("scripts.release_package_gate._python_version_tuple", return_value=(3, 10)), mock.patch(
            "scripts.release_package_gate._module_available", return_value=True
        ), mock.patch("scripts.release_package_gate._record_subprocess_step") as record:
            _record_mcp_stdio_smoke(dispatched, python="python3.10", project_root=ROOT, require=True)

        record.assert_called_once()
        args, kwargs = record.call_args
        self.assertEqual(args[1], "mcp_stdio_smoke")
        self.assertEqual(args[2], ["python3.10", "scripts/smoke_mcp.py", "--require-sdk"])
        self.assertEqual(kwargs["cwd"], ROOT)

    def test_release_gate_records_mcp_stdio_smoke_contract(self):
        summary = {"ok": True, "steps": []}
        _record_mcp_stdio_smoke_contract_gate(summary, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "mcp_stdio_smoke_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["script"], "scripts/smoke_mcp.py")
        self.assertIn("README.md", summary["steps"][0]["docs_checked"])
        self.assertEqual(
            summary["steps"][0]["required_tools"],
            [
                "citeguard_status_tool",
                "verify_citation_tool",
                "audit_citations_tool",
                "check_claim_support_tool",
                "check_claim_support_set_tool",
                "search_counterevidence_tool",
                "audit_claim_support_tool",
            ],
        )
        behaviors = summary["steps"][0]["checked_behaviors"]
        for behavior in [
            "initialize",
            "list_tools",
            "tool_metadata_descriptions",
            "offline_fixture",
            "status_payload",
            "status_source_health_retry_delay",
            "fixture_verify",
            "audit_high_risk_filter",
            "claim_support",
            "full_text_support",
            "full_text_file_support",
            "support_audit_full_text",
            "claim_support_set",
            "claim_support_set_counterevidence",
            "support_audit_citation_set",
            "support_mode_details",
            "support_audit_high_risk_filter",
            "support_audit_high_risk_counterevidence",
            "counterevidence",
            "source_outage_safety",
            "zh_source_outage_safety",
            "structured_errors",
            "batch_shape_errors",
            "missing_sdk_skip",
            "require_sdk_fail",
        ]:
            with self.subTest(behavior=behavior):
                self.assertTrue(behaviors[behavior])
        self.assertIn("missing_citation_input", summary["steps"][0]["structured_error_codes"])
        self.assertIn("missing_claim", summary["steps"][0]["structured_error_codes"])
        self.assertEqual(summary["steps"][0]["shape_error_fields"], ["citations", "items", "citations"])
        self.assertIn("initialize, list_tools", summary["steps"][0]["policy"])
        self.assertIn("full-text support", summary["steps"][0]["policy"])
        self.assertIn("full-text-file support", summary["steps"][0]["policy"])
        self.assertIn("per-source health item contracts", summary["steps"][0]["policy"])
        self.assertIn("structured errors", summary["steps"][0]["policy"])

    def test_release_gate_records_mcp_error_contract(self):
        summary = {"ok": True, "steps": []}

        _record_mcp_error_contract_gate(summary)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "mcp_error_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["schema_version"], ERROR_SCHEMA_VERSION)
        cases = {case["name"]: case for case in summary["steps"][0]["cases"]}
        self.assertEqual(
            set(cases),
            {
                "verify_missing_citation",
                "audit_invalid_shape",
                "support_missing_claim",
                "support_full_text_file_missing",
                "support_set_empty_citations",
                "counterevidence_missing_claim",
                "counterevidence_invalid_top_k",
                "support_audit_invalid_shape",
                "support_audit_nested_invalid_field",
                "support_audit_nested_full_text_file_missing",
                "verify_invalid_source_configuration",
            },
        )
        self.assertEqual(cases["verify_missing_citation"]["actual_code"], "missing_citation_input")
        self.assertEqual(cases["verify_missing_citation"]["next_action"], "provide_missing_input")
        self.assertFalse(cases["verify_missing_citation"]["retryable"])
        self.assertEqual(cases["verify_missing_citation"]["category"], "missing_input")
        self.assertEqual(cases["support_missing_claim"]["actual_code"], "missing_claim")
        self.assertEqual(cases["support_full_text_file_missing"]["actual_code"], "file_error")
        self.assertEqual(cases["support_full_text_file_missing"]["next_action"], "repair_input")
        self.assertFalse(cases["support_full_text_file_missing"]["retryable"])
        self.assertEqual(cases["support_full_text_file_missing"]["category"], "input_repair")
        self.assertIn("errno", cases["support_full_text_file_missing"]["details_keys"])
        self.assertIn("filename", cases["support_full_text_file_missing"]["details_keys"])
        self.assertIn("tool", cases["support_full_text_file_missing"]["details_keys"])
        self.assertEqual(cases["counterevidence_invalid_top_k"]["actual_code"], "invalid_input")
        self.assertIn("citation_index", cases["support_audit_nested_invalid_field"]["details_keys"])
        self.assertEqual(cases["support_audit_nested_full_text_file_missing"]["actual_code"], "file_error")
        self.assertIn("citation_index", cases["support_audit_nested_full_text_file_missing"]["details_keys"])
        self.assertIn("errno", cases["support_audit_nested_full_text_file_missing"]["details_keys"])
        self.assertIn("filename", cases["support_audit_nested_full_text_file_missing"]["details_keys"])
        self.assertEqual(cases["verify_invalid_source_configuration"]["actual_code"], "invalid_input")
        self.assertIn("source", cases["verify_invalid_source_configuration"]["details_keys"])
        self.assertIn("valid_values", cases["verify_invalid_source_configuration"]["details_keys"])
        self.assertEqual(
            set(summary["steps"][0]["tools"]),
            {
                "audit_citations_tool",
                "audit_claim_support_tool",
                "check_claim_support_set_tool",
                "check_claim_support_tool",
                "search_counterevidence_tool",
                "verify_citation_tool",
            },
        )
        self.assertEqual(
            set(summary["steps"][0]["error_codes"]),
            {"file_error", "invalid_input", "missing_citation_input", "missing_claim"},
        )
        self.assertIn("ok=false schema", summary["steps"][0]["policy"])

    def test_release_gate_records_published_smoke_plan(self):
        summary = {"ok": True, "steps": []}
        completed = mock.Mock(
            stdout=json.dumps(
                {
                    "ok": True,
                    "dry_run": True,
                    "package_spec": "citeguard==0.1.0",
                    "install_command": ["python", "-m", "pip", "install", "citeguard==0.1.0"],
                    "planned_checks": [
                        "pip_install",
                        "import_citeguard",
                        "version_contract",
                        "import_console_modules",
                        "public_package_files",
                        "public_api_contract",
                        "distribution_metadata",
                        "legacy_src_namespace_absent",
                        "entry_points",
                        "citeguard_cli_help",
                        "python_m_citeguard_cli_help",
                        "citeguard_cli_fixture_verify",
                        "python_m_citeguard_cli_fixture_verify",
                        "citeguard_cli_fixture_support",
                        "python_m_citeguard_cli_fixture_support",
                        "citeguard_cli_fixture_batch",
                        "python_m_citeguard_cli_fixture_batch",
                        "citeguard_cli_fixture_extract",
                        "python_m_citeguard_cli_fixture_extract",
                        "citeguard_cli_error_contract",
                        "python_m_citeguard_cli_error_contract",
                        "citeguard_status",
                        "python_m_citeguard_status",
                    ],
                }
            )
        )
        with mock.patch("scripts.release_package_gate._run", return_value=completed) as run:
            _record_published_smoke_plan(
                summary,
                python="python3",
                project_root=ROOT,
                extra="",
                require_extra_import="",
            )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "published_package_smoke_plan")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["package_spec"], "citeguard==0.1.0")
        self.assertEqual(summary["steps"][0]["config_errors"], [])
        self.assertIn("version_contract", summary["steps"][0]["planned_checks"])
        self.assertIn("public_package_files", summary["steps"][0]["planned_checks"])
        self.assertIn("public_api_contract", summary["steps"][0]["planned_checks"])
        self.assertIn("distribution_metadata", summary["steps"][0]["planned_checks"])
        self.assertIn("legacy_src_namespace_absent", summary["steps"][0]["planned_checks"])
        self.assertIn("entry_points", summary["steps"][0]["planned_checks"])
        self.assertIn("citeguard_cli_help", summary["steps"][0]["planned_checks"])
        self.assertIn("python_m_citeguard_cli_help", summary["steps"][0]["planned_checks"])
        self.assertIn("citeguard_cli_fixture_verify", summary["steps"][0]["planned_checks"])
        self.assertIn("python_m_citeguard_cli_fixture_verify", summary["steps"][0]["planned_checks"])
        self.assertIn("citeguard_cli_fixture_support", summary["steps"][0]["planned_checks"])
        self.assertIn("python_m_citeguard_cli_fixture_support", summary["steps"][0]["planned_checks"])
        self.assertIn("citeguard_cli_fixture_batch", summary["steps"][0]["planned_checks"])
        self.assertIn("python_m_citeguard_cli_fixture_batch", summary["steps"][0]["planned_checks"])
        self.assertIn("citeguard_cli_fixture_extract", summary["steps"][0]["planned_checks"])
        self.assertIn("python_m_citeguard_cli_fixture_extract", summary["steps"][0]["planned_checks"])
        self.assertIn("citeguard_cli_error_contract", summary["steps"][0]["planned_checks"])
        self.assertIn("python_m_citeguard_cli_error_contract", summary["steps"][0]["planned_checks"])
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["python3", "scripts/smoke_published_package.py", "--version", __version__])

        run_summary = {"ok": True, "steps": []}
        core_planned_checks = json.loads(completed.stdout)["planned_checks"]
        run_completed = mock.Mock(
            stdout=json.dumps(
                {
                    "ok": True,
                    "dry_run": False,
                    "package_spec": "citeguard==0.1.0",
                    "install_command": ["python", "-m", "pip", "install", "citeguard==0.1.0"],
                    "planned_checks": core_planned_checks,
                    "checks": [{"name": name, "status": "passed"} for name in core_planned_checks],
                    "config_errors": [],
                    "venv_dir": "/tmp/citeguard-published-smoke",
                    "smoke_cwd": "/tmp/citeguard-published-smoke/smoke-cwd",
                }
            )
        )
        with mock.patch("scripts.release_package_gate._run", return_value=run_completed) as run_smoke:
            _record_published_smoke_plan(
                run_summary,
                python="python3",
                project_root=ROOT,
                extra="",
                require_extra_import="",
                run=True,
            )

        self.assertTrue(run_summary["ok"])
        self.assertEqual(run_summary["steps"][0]["name"], "published_package_smoke_run")
        self.assertEqual(run_summary["steps"][0]["status"], "passed")
        self.assertFalse(run_summary["steps"][0]["dry_run"])
        self.assertTrue(run_summary["steps"][0]["run"])
        self.assertEqual(run_summary["steps"][0]["check_count"], len(core_planned_checks))
        self.assertEqual(run_summary["steps"][0]["failed_checks"], [])
        self.assertEqual(run_summary["steps"][0]["venv_dir"], "/tmp/citeguard-published-smoke")
        self.assertEqual(
            run_smoke.call_args.args[0],
            ["python3", "scripts/smoke_published_package.py", "--version", __version__, "--run"],
        )

        mcp_summary = {"ok": True, "steps": []}
        mcp_completed = mock.Mock(
            stdout=json.dumps(
                {
                    "ok": True,
                    "dry_run": True,
                    "package_spec": "citeguard[mcp]==0.1.0",
                    "install_command": ["python", "-m", "pip", "install", "citeguard[mcp]==0.1.0"],
                    "planned_checks": [
                        "pip_install",
                        "import_citeguard",
                        "version_contract",
                        "import_console_modules",
                        "public_package_files",
                        "public_api_contract",
                        "distribution_metadata",
                        "legacy_src_namespace_absent",
                        "entry_points",
                        "import_mcp",
                        "citeguard_cli_help",
                        "python_m_citeguard_cli_help",
                        "citeguard_cli_fixture_verify",
                        "python_m_citeguard_cli_fixture_verify",
                        "citeguard_cli_fixture_support",
                        "python_m_citeguard_cli_fixture_support",
                        "citeguard_cli_fixture_batch",
                        "python_m_citeguard_cli_fixture_batch",
                        "citeguard_cli_fixture_extract",
                        "python_m_citeguard_cli_fixture_extract",
                        "citeguard_cli_error_contract",
                        "python_m_citeguard_cli_error_contract",
                        "citeguard_status",
                        "python_m_citeguard_status",
                        "mcp_stdio_smoke",
                    ],
            }
        )
        )
        with mock.patch("scripts.release_package_gate._run", return_value=mcp_completed) as mcp_run:
            _record_published_smoke_plan(
                mcp_summary,
                python="python3",
                project_root=ROOT,
                extra="mcp",
                require_extra_import="mcp",
                mcp_stdio_smoke=True,
            )

        self.assertTrue(mcp_summary["ok"])
        self.assertEqual(mcp_summary["steps"][0]["name"], "published_mcp_smoke_plan")
        self.assertEqual(mcp_summary["steps"][0]["package_spec"], "citeguard[mcp]==0.1.0")
        self.assertEqual(mcp_summary["steps"][0]["config_errors"], [])
        self.assertIn("version_contract", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("public_package_files", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("public_api_contract", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("distribution_metadata", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("legacy_src_namespace_absent", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("entry_points", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("import_mcp", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("citeguard_cli_help", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("python_m_citeguard_cli_help", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("citeguard_cli_fixture_verify", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("python_m_citeguard_cli_fixture_verify", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("citeguard_cli_fixture_support", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("python_m_citeguard_cli_fixture_support", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("citeguard_cli_fixture_batch", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("python_m_citeguard_cli_fixture_batch", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("citeguard_cli_fixture_extract", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("python_m_citeguard_cli_fixture_extract", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("citeguard_cli_error_contract", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("python_m_citeguard_cli_error_contract", mcp_summary["steps"][0]["planned_checks"])
        self.assertIn("mcp_stdio_smoke", mcp_summary["steps"][0]["planned_checks"])
        self.assertEqual(
            mcp_run.call_args.args[0],
            [
                "python3",
                "scripts/smoke_published_package.py",
                "--version",
                __version__,
                "--extra",
                "mcp",
                "--require-extra-import",
                "mcp",
                "--mcp-stdio-smoke",
            ],
        )

        testpypi_summary = {"ok": True, "steps": []}
        testpypi_completed = mock.Mock(
            stdout=json.dumps(
                {
                    "ok": True,
                    "dry_run": True,
                    "package_spec": "citeguard[mcp]==0.1.0",
                    "install_command": [
                        "python",
                        "-m",
                        "pip",
                        "install",
                        "--index-url",
                        "https://test.pypi.org/simple/",
                        "--extra-index-url",
                        "https://pypi.org/simple",
                        "citeguard[mcp]==0.1.0",
                    ],
                    "planned_checks": [
                        "pip_install",
                        "import_citeguard",
                        "version_contract",
                        "import_console_modules",
                        "public_package_files",
                        "public_api_contract",
                        "distribution_metadata",
                        "legacy_src_namespace_absent",
                        "entry_points",
                        "import_mcp",
                        "citeguard_cli_help",
                        "python_m_citeguard_cli_help",
                        "citeguard_cli_fixture_verify",
                        "python_m_citeguard_cli_fixture_verify",
                        "citeguard_cli_fixture_support",
                        "python_m_citeguard_cli_fixture_support",
                        "citeguard_cli_fixture_batch",
                        "python_m_citeguard_cli_fixture_batch",
                        "citeguard_cli_fixture_extract",
                        "python_m_citeguard_cli_fixture_extract",
                        "citeguard_cli_error_contract",
                        "python_m_citeguard_cli_error_contract",
                        "citeguard_status",
                        "python_m_citeguard_status",
                        "mcp_stdio_smoke",
                    ],
                    "config_errors": [],
                }
            )
        )
        with mock.patch("scripts.release_package_gate._run", return_value=testpypi_completed) as testpypi_run:
            _record_published_smoke_plan(
                testpypi_summary,
                python="python3",
                project_root=ROOT,
                extra="mcp",
                require_extra_import="mcp",
                mcp_stdio_smoke=True,
                index_label="testpypi",
                index_url="https://test.pypi.org/simple/",
                extra_index_urls=["https://pypi.org/simple"],
            )

        self.assertTrue(testpypi_summary["ok"])
        self.assertEqual(testpypi_summary["steps"][0]["name"], "testpypi_mcp_smoke_plan")
        self.assertEqual(testpypi_summary["steps"][0]["index_label"], "testpypi")
        self.assertEqual(testpypi_summary["steps"][0]["index_url"], "https://test.pypi.org/simple/")
        self.assertEqual(testpypi_summary["steps"][0]["extra_index_urls"], ["https://pypi.org/simple"])
        self.assertEqual(
            testpypi_summary["steps"][0]["install_command"],
            [
                "python",
                "-m",
                "pip",
                "install",
                "--index-url",
                "https://test.pypi.org/simple/",
                "--extra-index-url",
                "https://pypi.org/simple",
                "citeguard[mcp]==0.1.0",
            ],
        )
        self.assertEqual(
            testpypi_run.call_args.args[0],
            [
                "python3",
                "scripts/smoke_published_package.py",
                "--version",
                __version__,
                "--index-url",
                "https://test.pypi.org/simple/",
                "--extra-index-url",
                "https://pypi.org/simple",
                "--extra",
                "mcp",
                "--require-extra-import",
                "mcp",
                "--mcp-stdio-smoke",
            ],
        )

        testpypi_run_summary = {"ok": True, "steps": []}
        testpypi_run_completed = mock.Mock(
            stdout=json.dumps(
                {
                    "ok": True,
                    "dry_run": False,
                    "package_spec": "citeguard[mcp]==0.1.0",
                    "install_command": testpypi_summary["steps"][0]["install_command"],
                    "planned_checks": testpypi_summary["steps"][0]["planned_checks"],
                    "checks": [
                        {"name": name, "status": "passed"}
                        for name in testpypi_summary["steps"][0]["planned_checks"]
                    ],
                    "config_errors": [],
                    "venv_dir": "/tmp/citeguard-testpypi-smoke",
                    "smoke_cwd": "/tmp/citeguard-testpypi-smoke/smoke-cwd",
                }
            )
        )
        with mock.patch("scripts.release_package_gate._run", return_value=testpypi_run_completed) as testpypi_smoke_run:
            _record_published_smoke_plan(
                testpypi_run_summary,
                python="python3",
                project_root=ROOT,
                extra="mcp",
                require_extra_import="mcp",
                mcp_stdio_smoke=True,
                index_label="testpypi",
                index_url="https://test.pypi.org/simple/",
                extra_index_urls=["https://pypi.org/simple"],
                run=True,
            )

        self.assertTrue(testpypi_run_summary["ok"])
        self.assertEqual(testpypi_run_summary["steps"][0]["name"], "testpypi_mcp_smoke_run")
        self.assertEqual(testpypi_run_summary["steps"][0]["failed_checks"], [])
        self.assertEqual(
            testpypi_smoke_run.call_args.args[0],
            [
                "python3",
                "scripts/smoke_published_package.py",
                "--version",
                __version__,
                "--run",
                "--index-url",
                "https://test.pypi.org/simple/",
                "--extra-index-url",
                "https://pypi.org/simple",
                "--extra",
                "mcp",
                "--require-extra-import",
                "mcp",
                "--mcp-stdio-smoke",
            ],
        )

        failed_run_summary = {"ok": True, "steps": []}
        failed_run_completed = mock.Mock(
            stdout=json.dumps(
                {
                    "ok": False,
                    "dry_run": False,
                    "package_spec": "citeguard==0.1.0",
                    "install_command": ["python", "-m", "pip", "install", "citeguard==0.1.0"],
                    "planned_checks": core_planned_checks,
                    "checks": [
                        {"name": name, "status": "failed" if name == "pip_install" else "passed"}
                        for name in core_planned_checks
                    ],
                    "config_errors": [],
                }
            )
        )
        with mock.patch("scripts.release_package_gate._run", return_value=failed_run_completed):
            _record_published_smoke_plan(
                failed_run_summary,
                python="python3",
                project_root=ROOT,
                extra="",
                require_extra_import="",
                run=True,
            )

        self.assertFalse(failed_run_summary["ok"])
        self.assertEqual(failed_run_summary["steps"][0]["status"], "failed")
        self.assertEqual(failed_run_summary["steps"][0]["failed_checks"], ["pip_install"])

        bad_summary = {"ok": True, "steps": []}
        bad_completed = mock.Mock(
            stdout=json.dumps(
                {
                    "ok": False,
                    "dry_run": True,
                    "package_spec": "citeguard==0.1.0",
                    "install_command": ["python", "-m", "pip", "install", "citeguard==0.1.0"],
                    "planned_checks": [
                        "pip_install",
                        "import_citeguard",
                        "import_console_modules",
                        "entry_points",
                        "citeguard_status",
                        "python_m_citeguard_status",
                        "mcp_stdio_smoke",
                    ],
                    "config_errors": [
                        {
                            "code": "mcp_stdio_smoke_requires_mcp_extra",
                            "message": "--mcp-stdio-smoke requires --extra mcp",
                            "details": {"required_extra": "mcp"},
                        }
                    ],
                }
            )
        )
        with mock.patch("scripts.release_package_gate._run", return_value=bad_completed):
            _record_published_smoke_plan(
                bad_summary,
                python="python3",
                project_root=ROOT,
                extra="",
                require_extra_import="",
                mcp_stdio_smoke=True,
            )

        self.assertFalse(bad_summary["ok"])
        self.assertEqual(bad_summary["steps"][0]["status"], "failed")
        self.assertEqual(
            bad_summary["steps"][0]["config_errors"][0]["code"],
            "mcp_stdio_smoke_requires_mcp_extra",
        )

    def test_release_gate_records_support_label_sidecar_gate(self):
        summary = {"ok": True, "steps": []}
        completed = mock.Mock(
            stdout=(
                '{"label_sidecar_gate": {"ok": true, '
                '"thresholds": {"min_high_risk_reviewed_by_language": {"zh": 1}}, '
                '"metrics": {"high_risk_case_count_by_language": {"zh": 5}, '
                '"high_risk_reviewed_by_language": {"zh": 1}, '
                '"high_risk_case_count_by_language_case_type": {"zh": {"contradiction": 3, "hard_negative": 2}}, '
                '"high_risk_reviewed_by_language_case_type": {"zh": {"contradiction": 1}}, '
                '"high_risk_unreviewed_by_language_case_type": {"zh": {"contradiction": 2, "hard_negative": 2}}, '
                '"full_text_required_case_count": 7, '
                '"full_text_required_reviewed": 0, '
                '"full_text_required_unreviewed": 7, '
                '"full_text_required_unreviewed_by_language": {"en": 6, "zh": 1}, '
                '"full_text_required_unreviewed_case_ids": ["s17", "s30", "s43", "s13", "s38", "s20", "s33"], '
                '"policy_boundary_case_count": 2, '
                '"policy_boundary_reviewed": 0, '
                '"policy_boundary_unreviewed": 2, '
                '"policy_boundary_unreviewed_by_language": {"en": 1, "zh": 1}, '
                '"policy_boundary_unreviewed_case_ids": ["ss02", "ss05"], '
                '"label_source_counts": {"maintainer_synthetic": 54}, '
                '"reviewed_by_label_source": {}, '
                '"unreviewed_by_label_source": {"maintainer_synthetic": 54}, '
                '"reviewed_source_locator_count": 0, '
                '"reviewed_missing_source_locator_count": 0, '
                '"published_benchmark_source_locator_count": 0, '
                '"sidecar_provenance_complete_count": 54, '
                '"sidecar_provenance_complete_fraction": 1.0, '
                '"sidecar_provenance_missing_count": 0, '
                '"sidecar_provenance_missing_case_ids": [], '
                '"sidecar_provenance_missing_case_ids_by_field": {}, '
                '"sidecar_provenance_field_present_counts": {"label_source": 54, "case_type": 54, "evidence_scope": 54, "split": 54, "lang": 54}, '
                '"dataset_cases": 54, '
                '"sidecar_cases": 54}, '
                '"failures": []}}'
            )
        )
        full_text_probe = mock.Mock(
            returncode=1,
            stdout=(
                '{"audit_gate": {"ok": false, '
                '"metrics": {"full_text_required_unreviewed_count": 7}, '
                '"failures": [{"code": "full_text_required_unreviewed", '
                '"case_ids": ["s17", "s30", "s43", "s13", "s38", "s20", "s33"]}]}}'
            ),
            stderr="",
        )
        policy_probe = mock.Mock(
            returncode=1,
            stdout=(
                '{"audit_gate": {"ok": false, '
                '"metrics": {"policy_boundary_unreviewed_count": 2}, '
                '"failures": [{"code": "policy_boundary_unreviewed", '
                '"case_ids": ["ss02", "ss05"]}]}}'
            ),
            stderr="",
        )
        review_plan_probe = mock.Mock(
            returncode=0,
            stdout=json.dumps(_support_label_review_plan_audit_payload()),
            stderr="",
        )
        with mock.patch("scripts.release_package_gate._run", return_value=completed) as run, mock.patch(
            "scripts.release_package_gate._run_no_check",
            side_effect=_support_label_review_plan_run_no_check_side_effect(
                full_text_probe,
                policy_probe,
                review_plan_probe,
            ),
        ) as run_no_check:
            _record_support_label_sidecar_gate(
                summary,
                python="python3",
                project_root=ROOT,
                dataset="data/eval/support_eval.json",
                label_sidecar="data/eval/support_eval_label_sidecar.json",
                min_sidecar_coverage=1.0,
                min_human_reviewed=2,
                min_high_risk_reviewed=1,
                min_high_risk_reviewed_by_language=["zh=1"],
                min_dual_annotated=2,
                max_unresolved_disagreements=0,
                min_raw_dual_agreement_rate=0.8,
                max_supported_disagreements=0,
            )

        run.assert_called_once()
        self.assertEqual(run_no_check.call_count, 5)
        self.assertEqual(
            run.call_args.args[0],
            [
                "python3",
                "scripts/eval_support.py",
                "--validate-only",
                "--dataset",
                "data/eval/support_eval.json",
                "--label-sidecar",
                "data/eval/support_eval_label_sidecar.json",
                "--min-sidecar-coverage",
                "1.0",
                "--min-human-reviewed",
                "2",
                "--min-high-risk-reviewed",
                "1",
                "--min-dual-annotated",
                "2",
                "--max-unresolved-disagreements",
                "0",
                "--min-high-risk-reviewed-by-language",
                "zh=1",
                "--min-raw-dual-agreement-rate",
                "0.8",
                "--max-supported-disagreements",
                "0",
            ],
        )
        self.assertEqual(run.call_args.kwargs["cwd"], ROOT)
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["thresholds"]["min_high_risk_reviewed_by_language"], {"zh": 1})
        self.assertEqual(summary["steps"][0]["metrics"]["high_risk_case_count_by_language"], {"zh": 5})
        self.assertEqual(
            summary["steps"][0]["metrics"]["high_risk_case_count_by_language_case_type"],
            {"zh": {"contradiction": 3, "hard_negative": 2}},
        )
        self.assertEqual(
            summary["steps"][0]["metrics"]["high_risk_reviewed_by_language_case_type"],
            {"zh": {"contradiction": 1}},
        )
        self.assertEqual(
            summary["steps"][0]["metrics"]["high_risk_unreviewed_by_language_case_type"],
            {"zh": {"contradiction": 2, "hard_negative": 2}},
        )
        self.assertEqual(summary["steps"][0]["metrics"]["full_text_required_case_count"], 7)
        self.assertEqual(summary["steps"][0]["metrics"]["full_text_required_unreviewed"], 7)
        self.assertEqual(
            summary["steps"][0]["metrics"]["full_text_required_unreviewed_by_language"],
            {"en": 6, "zh": 1},
        )
        self.assertEqual(
            summary["steps"][0]["metrics"]["full_text_required_unreviewed_case_ids"],
            ["s17", "s30", "s43", "s13", "s38", "s20", "s33"],
        )
        self.assertEqual(summary["steps"][0]["metrics"]["policy_boundary_case_count"], 2)
        self.assertEqual(summary["steps"][0]["metrics"]["policy_boundary_unreviewed"], 2)
        self.assertEqual(
            summary["steps"][0]["metrics"]["policy_boundary_unreviewed_by_language"],
            {"en": 1, "zh": 1},
        )
        self.assertEqual(summary["steps"][0]["metrics"]["policy_boundary_unreviewed_case_ids"], ["ss02", "ss05"])
        self.assertEqual(
            summary["steps"][0]["metrics"]["label_source_counts"],
            {"maintainer_synthetic": 54},
        )
        self.assertEqual(summary["steps"][0]["metrics"]["reviewed_by_label_source"], {})
        self.assertEqual(
            summary["steps"][0]["metrics"]["unreviewed_by_label_source"],
            {"maintainer_synthetic": 54},
        )
        self.assertEqual(summary["steps"][0]["metrics"]["reviewed_source_locator_count"], 0)
        self.assertEqual(summary["steps"][0]["metrics"]["reviewed_missing_source_locator_count"], 0)
        self.assertEqual(summary["steps"][0]["metrics"]["published_benchmark_source_locator_count"], 0)
        self.assertEqual(summary["steps"][0]["failures"], [])
        self.assertEqual(summary["steps"][0]["audit_fail_flag_errors"], [])
        self.assertEqual(summary["steps"][0]["label_provenance_errors"], [])
        self.assertEqual(
            [item["flag"] for item in summary["steps"][0]["audit_fail_flag_smokes"]],
            ["--fail-on-full-text-required-unreviewed", "--fail-on-policy-boundary-unreviewed"],
        )
        self.assertEqual(
            [item["expected_code"] for item in summary["steps"][0]["audit_fail_flag_smokes"]],
            ["full_text_required_unreviewed", "policy_boundary_unreviewed"],
        )
        self.assertTrue(all(item["status"] == "passed" for item in summary["steps"][0]["audit_fail_flag_smokes"]))
        self.assertEqual(summary["steps"][0]["review_plan_errors"], [])
        self.assertEqual(summary["steps"][0]["review_plan_smoke"]["status"], "passed")
        self.assertEqual(summary["steps"][0]["review_plan_smoke"]["next_phase"], "first_review_high_risk")
        self.assertGreater(summary["steps"][0]["review_plan_smoke"]["high_risk_unreviewed"], 0)
        self.assertEqual(
            summary["steps"][0]["review_plan_smoke"]["full_text_required_unreviewed"],
            summary["steps"][0]["metrics"]["full_text_required_unreviewed"],
        )
        self.assertEqual(
            summary["steps"][0]["review_plan_smoke"]["policy_boundary_unreviewed"],
            summary["steps"][0]["metrics"]["policy_boundary_unreviewed"],
        )
        self.assertEqual(
            summary["steps"][0]["review_plan_smoke"]["high_risk_unreviewed_by_language_case_type"],
            _support_label_review_plan_audit_payload()["high_risk_unreviewed_by_language_case_type"],
        )
        self.assertEqual(
            summary["steps"][0]["review_plan_smoke"]["first_review_candidate_count"],
            summary["steps"][0]["review_plan_smoke"]["high_risk_unreviewed"]
            + summary["steps"][0]["review_plan_smoke"]["policy_boundary_unreviewed"],
        )
        self.assertEqual(
            summary["steps"][0]["review_plan_smoke"]["first_review_candidate_count_by_language_case_type"],
            _support_label_review_plan_audit_payload()["high_risk_unreviewed_by_language_case_type"],
        )
        self.assertEqual(summary["steps"][0]["review_plan_smoke"]["recommended_packet_errors"], [])
        self.assertIn(
            "high_risk_unreviewed_zh_contradiction",
            summary["steps"][0]["review_plan_smoke"]["language_case_type_packet_ids"],
        )
        self.assertIn(
            "high_risk_unreviewed_en_contradiction_set",
            summary["steps"][0]["review_plan_smoke"]["first_review_packet_ids"],
        )
        self.assertEqual(
            summary["steps"][0]["review_plan_smoke"]["language_case_type_packet_smoke"]["status"],
            "passed",
        )
        self.assertEqual(
            summary["steps"][0]["review_plan_smoke"]["language_case_type_packet_smoke"]["packet_id"],
            "high_risk_unreviewed_en_contradiction",
        )
        self.assertEqual(
            summary["steps"][0]["review_plan_smoke"]["language_case_type_packet_smoke"]["case_count_by_language"],
            {"en": 9},
        )
        self.assertEqual(
            summary["steps"][0]["review_plan_smoke"]["language_case_type_packet_smoke"]["case_count_by_case_type"],
            {"contradiction": 9},
        )
        self.assertEqual(
            summary["steps"][0]["review_plan_smoke"]["recommended_packet_smoke"]["status"],
            "passed",
        )
        self.assertEqual(
            summary["steps"][0]["review_plan_smoke"]["recommended_packet_smoke"]["case_count_by_review_status"],
            {"not_human_reviewed": 2},
        )
        self.assertEqual(
            summary["steps"][0]["review_plan_smoke"]["recommended_packet_smoke"]["review_phase"],
            "first_review_high_risk",
        )
        self.assertIn(
            "balanced first-review",
            summary["steps"][0]["review_plan_smoke"]["recommended_packet_smoke"]["packet_purpose"],
        )
        self.assertEqual(
            summary["steps"][0]["review_plan_smoke"]["recommended_packet_smoke"]["leaked_hidden_fields"],
            [],
        )
        self.assertTrue(
            summary["steps"][0]["review_plan_smoke"]["recommended_packet_smoke"][
                "scope_annotation_fields_present"
            ]
        )
        self.assertIn(
            "policy_boundary_unreviewed",
            summary["steps"][0]["review_plan_smoke"]["first_review_packet_ids"],
        )
        self.assertEqual(summary["steps"][0]["review_plan_smoke"]["policy_boundary_case_ids"], ["ss02", "ss05"])
        self.assertEqual(summary["steps"][0]["review_plan_smoke"]["release_gate_status"], "blocked")

    def test_release_gate_records_failed_support_label_sidecar_gate_payload(self):
        summary = {"ok": True, "steps": []}
        error = subprocess.CalledProcessError(
            1,
            ["python3", "scripts/eval_support.py"],
            output=(
                '{"label_sidecar_gate": {"ok": false, '
                '"thresholds": {"min_high_risk_reviewed_by_language": {"zh": 1}}, '
                '"metrics": {"high_risk_case_count_by_language": {"zh": 5}, '
                '"high_risk_reviewed_by_language": {}}, '
                '"failures": [{"code": "sidecar_high_risk_reviewed_by_language", '
                '"language": "zh", "actual": 0, "threshold": 1}]}}'
            ),
            stderr="",
        )
        with mock.patch("scripts.release_package_gate._run", side_effect=error):
            _record_support_label_sidecar_gate(
                summary,
                python="python3",
                project_root=ROOT,
                dataset="data/eval/support_eval.json",
                label_sidecar="data/eval/support_eval_label_sidecar.json",
                min_sidecar_coverage=1.0,
                min_human_reviewed=0,
                min_high_risk_reviewed=0,
                min_high_risk_reviewed_by_language=["zh=1"],
                min_dual_annotated=0,
                max_unresolved_disagreements=0,
                min_raw_dual_agreement_rate=None,
                max_supported_disagreements=None,
            )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["steps"][0]["status"], "failed")
        self.assertEqual(summary["steps"][0]["failures"][0]["code"], "sidecar_high_risk_reviewed_by_language")
        self.assertEqual(summary["steps"][0]["failures"][0]["language"], "zh")
        self.assertEqual(summary["steps"][0]["metrics"]["high_risk_case_count_by_language"], {"zh": 5})

    def test_release_gate_fails_on_support_label_provenance_drift(self):
        summary = {"ok": True, "steps": []}
        completed = mock.Mock(
            stdout=(
                '{"label_sidecar_gate": {"ok": true, '
                '"thresholds": {}, '
                '"metrics": {"label_source_counts": {"unknown": 52}, '
                '"reviewed_by_label_source": {}, '
                '"unreviewed_by_label_source": {"unknown": 52}, '
                '"reviewed_source_locator_count": 0, '
                '"reviewed_missing_source_locator_count": 0, '
                '"published_benchmark_source_locator_count": 0}, '
                '"failures": []}}'
            )
        )
        full_text_probe = mock.Mock(
            returncode=1,
            stdout=(
                '{"audit_gate": {"ok": false, '
                '"metrics": {"full_text_required_unreviewed_count": 7}, '
                '"failures": [{"code": "full_text_required_unreviewed", '
                '"case_ids": ["s17", "s30", "s43", "s13", "s38", "s20", "s33"]}]}}'
            ),
            stderr="",
        )
        policy_probe = mock.Mock(
            returncode=1,
            stdout=(
                '{"audit_gate": {"ok": false, '
                '"metrics": {"policy_boundary_unreviewed_count": 2}, '
                '"failures": [{"code": "policy_boundary_unreviewed", '
                '"case_ids": ["ss02", "ss05"]}]}}'
            ),
            stderr="",
        )
        review_plan_probe = mock.Mock(
            returncode=0,
            stdout=json.dumps(_support_label_review_plan_audit_payload()),
            stderr="",
        )
        with mock.patch("scripts.release_package_gate._run", return_value=completed), mock.patch(
            "scripts.release_package_gate._run_no_check",
            side_effect=_support_label_review_plan_run_no_check_side_effect(
                full_text_probe,
                policy_probe,
                review_plan_probe,
            ),
        ):
            _record_support_label_sidecar_gate(
                summary,
                python="python3",
                project_root=ROOT,
                dataset="data/eval/support_eval.json",
                label_sidecar="data/eval/support_eval_label_sidecar.json",
                min_sidecar_coverage=1.0,
                min_human_reviewed=0,
                min_high_risk_reviewed=0,
                min_high_risk_reviewed_by_language=[],
                min_dual_annotated=0,
                max_unresolved_disagreements=0,
                min_raw_dual_agreement_rate=None,
                max_supported_disagreements=None,
            )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["steps"][0]["status"], "failed")
        self.assertIn("label_source_counts", summary["steps"][0]["label_provenance_errors"][0])

    def test_support_label_provenance_contract_allows_future_human_review(self):
        errors = _support_label_provenance_contract_errors(
            {
                "dataset_cases": 54,
                "sidecar_cases": 54,
                "human_reviewed": 2,
                "published_benchmark": 1,
                "label_source_counts": {
                    "maintainer_synthetic": 52,
                    "dual_annotator_adjudicated": 1,
                    "published_benchmark": 1,
                },
                "reviewed_by_label_source": {
                    "dual_annotator_adjudicated": 1,
                    "published_benchmark": 1,
                },
                "unreviewed_by_label_source": {"maintainer_synthetic": 52},
                "reviewed_source_locator_count": 2,
                "reviewed_missing_source_locator_count": 0,
                "published_benchmark_source_locator_count": 1,
            }
        )

        self.assertEqual(errors, [])

    def test_release_gate_records_benchmark_claim_safety_contract(self):
        summary = {"ok": True, "steps": []}

        _record_benchmark_claim_safety_gate(
            summary,
            project_root=ROOT,
            dataset="data/eval/support_eval.json",
            label_sidecar="data/eval/support_eval_label_sidecar.json",
        )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "benchmark_claim_safety")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["dataset"], "data/eval/support_eval.json")
        self.assertEqual(summary["steps"][0]["label_sidecar"], "data/eval/support_eval_label_sidecar.json")
        self.assertEqual(summary["steps"][0]["case_count"], 54)
        self.assertEqual(summary["steps"][0]["evidence_case_count"], 48)
        self.assertEqual(summary["steps"][0]["citation_set_case_count"], 6)
        self.assertEqual(summary["steps"][0]["sidecar_case_count"], 54)
        self.assertEqual(summary["steps"][0]["sidecar_case_provenance"]["complete_count"], 54)
        self.assertEqual(summary["steps"][0]["sidecar_case_provenance"]["complete_fraction"], 1.0)
        self.assertEqual(summary["steps"][0]["sidecar_case_provenance"]["missing_count"], 0)
        self.assertEqual(summary["steps"][0]["sidecar_case_provenance"]["missing_case_ids"], [])
        self.assertEqual(
            summary["steps"][0]["sidecar_case_provenance"]["field_present_counts"]["case_type"],
            54,
        )
        self.assertEqual(
            summary["steps"][0]["sidecar_case_provenance"]["field_present_counts"]["label_source"],
            54,
        )
        self.assertEqual(summary["steps"][0]["human_reviewed"], 0)
        self.assertEqual(summary["steps"][0]["dual_annotated"], 0)
        self.assertEqual(summary["steps"][0]["published_benchmark"], 0)
        self.assertIn("README.md", summary["steps"][0]["release_docs_checked"])
        self.assertIn("CHANGELOG.md", summary["steps"][0]["release_docs_checked"])
        self.assertIn("ROADMAP.md", summary["steps"][0]["release_docs_checked"])
        self.assertIn("docs/benchmark_design.md", summary["steps"][0]["release_docs_checked"])
        self.assertIn("docs/benchmark_todo.md", summary["steps"][0]["release_docs_checked"])
        self.assertIn("docs/github_launch.md", summary["steps"][0]["release_docs_checked"])
        self.assertIn("docs/release_checklist.md", summary["steps"][0]["release_docs_checked"])
        self.assertIn("docs/support_labeling_guidelines.md", summary["steps"][0]["release_docs_checked"])
        self.assertIn("scripts/eval_support.py", summary["steps"][0]["release_docs_checked"])
        self.assertIn("skills/citeguard-verify/references/examples.md", summary["steps"][0]["release_docs_checked"])
        self.assertIn("docs/releases/v0.1.0.md", summary["steps"][0]["release_docs_checked"])
        self.assertEqual(summary["steps"][0]["unsafe_human_reviewed_benchmark_claims"], [])
        occurrences = summary["steps"][0]["human_reviewed_benchmark_occurrences"]
        self.assertTrue(any(item["path"] == "README.en.md" for item in occurrences))
        self.assertTrue(any(item["path"] == "docs/support_labeling_guidelines.md" for item in occurrences))
        self.assertTrue(any(item["path"] == "skills/citeguard-verify/references/examples.md" for item in occurrences))
        self.assertTrue(any(item["path"] == "scripts/eval_support.py" for item in occurrences))
        self.assertTrue(all(item["qualified_as_not_ready"] for item in occurrences))
        unsafe_occurrences = _human_reviewed_benchmark_occurrences(
            "Use 0 for release-grade human-reviewed benchmarks.",
            "bad-help",
        )
        self.assertEqual(len(unsafe_occurrences), 1)
        self.assertFalse(unsafe_occurrences[0]["qualified_as_not_ready"])
        unsafe_large_claims = _human_reviewed_benchmark_occurrences(
            "CiteGuard ships a large human-reviewed benchmark.",
            "bad-release-copy",
        )
        self.assertEqual(len(unsafe_large_claims), 1)
        self.assertFalse(unsafe_large_claims[0]["qualified_as_not_ready"])
        self.assertIn("synthetic seed set", summary["steps"][0]["policy"])

    def test_release_gate_records_legacy_src_shim_contract(self):
        summary = {"ok": True, "steps": []}

        _record_legacy_src_shim_contract(summary, ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "legacy_src_shim_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertGreater(summary["steps"][0]["file_count"], 0)
        self.assertLessEqual(summary["steps"][0]["max_lines"], 25)
        self.assertEqual(summary["steps"][0]["checked_root"], "src")
        self.assertEqual(summary["steps"][0]["policy"], "legacy shims only; new code imports citeguard.*")

    def test_release_gate_records_public_api_contract(self):
        summary = {"ok": True, "steps": []}

        _record_public_api_contract_gate(summary, ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "public_api_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertGreater(summary["steps"][0]["public_files_checked"], 0)
        self.assertGreater(summary["steps"][0]["package_files_checked"], 0)
        self.assertEqual(summary["steps"][0]["migration_doc"], "docs/public_api_migration.md")
        self.assertEqual(summary["steps"][0]["public_offenders"], [])
        self.assertEqual(summary["steps"][0]["package_offenders"], [])
        self.assertIn("citeguard.verification", summary["steps"][0]["public_packages"])
        self.assertIn("citeguard.runtime", summary["steps"][0]["public_packages"])
        self.assertIn("verify_citation", summary["steps"][0]["root_facade_exports"])
        self.assertIn("check_claim_support_set", summary["steps"][0]["root_facade_exports"])
        self.assertIn("error_code_registry", summary["steps"][0]["root_facade_exports"])
        self.assertEqual(summary["steps"][0]["root_facade_experimental_exports"], [])
        self.assertIn("verify_citation", summary["steps"][0]["root_facade_required_exports"])
        self.assertIn("error_code_registry", summary["steps"][0]["root_facade_required_exports"])
        smoke_contract = summary["steps"][0]["local_package_smoke_public_api_contract"]
        self.assertTrue(smoke_contract["ok"])
        self.assertEqual(smoke_contract["script"], "scripts/smoke_package.py")
        self.assertEqual(smoke_contract["inline_script"], "_IMPORT_SMOKE")
        self.assertEqual(smoke_contract["missing_checks"], [])
        self.assertEqual(smoke_contract["stable_error_codes_import"], "citeguard.errors")
        self.assertIn("error_code_registry", smoke_contract["checks"])
        self.assertIn("timeout_retryable", smoke_contract["checks"])
        self.assertIn("error_category", smoke_contract["checks"])
        self.assertIn("root_experimental_exports", smoke_contract["checks"])
        self.assertIn("stable_error_codes_from_errors_module", smoke_contract["checks"])
        self.assertIn("citeguard.* imports", summary["steps"][0]["policy"])

    def test_release_gate_records_cache_replay_fixture_contract(self):
        summary = {"ok": True, "steps": []}

        _record_cache_replay_fixture_gate(summary, python=sys.executable, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "cache_replay_fixture")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertTrue(summary["steps"][0]["deterministic"])
        self.assertTrue(summary["steps"][0]["byte_identical"])
        self.assertEqual(summary["steps"][0]["fixture_record_count"], 1)
        self.assertEqual(summary["steps"][0]["record_count"], 1)
        self.assertEqual(summary["steps"][0]["replay_record_title"], "Release Cache Replay Fixture")
        self.assertEqual(summary["steps"][0]["manifest_fixture_format"], "manifest_records")
        self.assertEqual(summary["steps"][0]["manifest_fixture_record_count"], 1)
        self.assertEqual(summary["steps"][0]["manifest_replay_record_title"], "Release Cache Replay Fixture")
        filtered_lookup = summary["steps"][0]["filtered_lookup"]
        self.assertEqual(filtered_lookup["record_count"], 1)
        self.assertEqual(filtered_lookup["cache_entry_count"], 2)
        self.assertEqual(filtered_lookup["selected_cache_entry_count"], 1)
        self.assertEqual(filtered_lookup["selected_cache_entry_prefixes"]["lookup"], 1)
        self.assertEqual(filtered_lookup["selected_cache_entry_prefixes"]["search"], 0)
        self.assertEqual(filtered_lookup["export_filters"]["operation"], "lookup")
        self.assertEqual(filtered_lookup["inspect_selected_entries"], 1)
        self.assertEqual(filtered_lookup["inspect_selected_entry_prefixes"]["lookup"], 1)
        self.assertEqual(filtered_lookup["inspect_selected_entry_prefixes"]["search"], 0)
        self.assertEqual(filtered_lookup["inspect_filters"]["operation"], "lookup")
        self.assertEqual(filtered_lookup["missing_source_clear_cleared_entries"], 0)
        self.assertEqual(filtered_lookup["missing_source_clear_remaining_entries"], 2)
        self.assertEqual(filtered_lookup["missing_source_clear_selected_entry_prefixes"]["lookup"], 0)
        self.assertEqual(filtered_lookup["missing_source_clear_selected_entry_prefixes"]["search"], 0)
        self.assertEqual(filtered_lookup["missing_source_clear_filters"]["source"], "openalex")
        self.assertEqual(filtered_lookup["clear_cleared_entries"], 1)
        self.assertEqual(filtered_lookup["clear_remaining_entries"], 1)
        self.assertEqual(filtered_lookup["clear_selected_entry_prefixes"]["lookup"], 1)
        self.assertEqual(filtered_lookup["clear_selected_entry_prefixes"]["search"], 0)
        self.assertEqual(filtered_lookup["clear_filters"]["operation"], "lookup")
        self.assertEqual(filtered_lookup["fixture_record_count"], 1)
        self.assertEqual(filtered_lookup["replay_record_title"], "Release Cache Replay Fixture")
        self.assertEqual(filtered_lookup["cache_provenance_operation"], "lookup")
        self.assertEqual(summary["steps"][0]["leaked_timestamp_fields"], [])
        provenance = summary["steps"][0]["cache_provenance"]
        self.assertEqual(provenance["operation"], "search")
        self.assertEqual(provenance["source"], "metadata_source")
        self.assertEqual(provenance["query"], "Release Cache Replay Fixture")
        self.assertEqual(provenance["normalized_query"], "release cache replay fixture")
        self.assertEqual(provenance["record_source"], "release_fixture")
        self.assertIsInstance(provenance["raw_match_score"], float)
        self.assertIn("raw match score provenance", summary["steps"][0]["policy"])
        self.assertEqual(summary["steps"][0]["inspect_before"]["entries"], 1)
        self.assertEqual(summary["steps"][0]["inspect_before"]["entry_prefixes"]["search"], 1)
        self.assertEqual(summary["steps"][0]["inspect_after_filtered_clear"]["entries"], 1)
        self.assertEqual(summary["steps"][0]["inspect_after_filtered_clear"]["entry_prefixes"]["search"], 1)
        self.assertEqual(summary["steps"][0]["inspect_after_filtered_clear"]["entry_prefixes"]["lookup"], 0)
        self.assertEqual(summary["steps"][0]["clear"]["cleared_entries"], 1)
        self.assertEqual(summary["steps"][0]["clear"]["remaining_entries"], 0)
        self.assertEqual(summary["steps"][0]["inspect_after"]["entries"], 0)
        self.assertEqual(
            summary["steps"][0]["inspect_before"]["schema_version"],
            summary["steps"][0]["clear"]["schema_version"],
        )
        self.assertEqual(
            summary["steps"][0]["inspect_before"]["schema_version"],
            summary["steps"][0]["inspect_after"]["schema_version"],
        )
        commands = summary["steps"][0]["commands"]
        self.assertIn("inspect", commands[0])
        self.assertIn("--deterministic", commands[1])
        self.assertIn("cache", commands[1])
        self.assertIn("export", commands[1])
        self.assertTrue(any("--include-manifest" in command for command in commands))
        self.assertTrue(any("--operation" in command and "lookup" in command for command in commands))
        self.assertTrue(any("clear" in command for command in commands))
        self.assertIn("operation-filtered", summary["steps"][0]["policy"])
        self.assertIn("manifest-wrapped fixtures", summary["steps"][0]["policy"])
        self.assertIn(
            "filtered manifests, inspect output, and clear output keep total and selected cache counts separate",
            summary["steps"][0]["policy"],
        )
        self.assertIn("inspect/clear expose non-sensitive counts", summary["steps"][0]["policy"])

    def test_release_gate_records_error_codes_contract(self):
        summary = {"ok": True, "steps": []}

        _record_error_codes_contract_gate(summary, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "error_codes_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["schema_version"], ERROR_SCHEMA_VERSION)
        self.assertEqual(summary["steps"][0]["stable_code_count"], len(STABLE_ERROR_CODES))
        self.assertEqual(summary["steps"][0]["registry_code_count"], len(STABLE_ERROR_CODES))
        self.assertEqual(summary["steps"][0]["documented_code_count"], len(STABLE_ERROR_CODES))
        self.assertGreaterEqual(summary["steps"][0]["documented_next_action_count"], len(set(ERROR_CODE_NEXT_ACTION.values())))
        self.assertEqual(set(summary["steps"][0]["error_codes"]), STABLE_ERROR_CODES)
        self.assertEqual(summary["steps"][0]["error_next_actions"]["timeout"], "retry_or_check_source_health")
        self.assertEqual(
            summary["steps"][0]["documented_error_recovery"]["missing_citation_input"],
            ERROR_CODE_RECOVERY["missing_citation_input"],
        )
        self.assertTrue(summary["steps"][0]["error_retryable"]["timeout"])
        self.assertTrue(summary["steps"][0]["error_retryable"]["source_unavailable"])
        self.assertFalse(summary["steps"][0]["error_retryable"]["missing_claim"])
        self.assertEqual(summary["steps"][0]["error_categories"]["timeout"], "source_limited")
        self.assertEqual(summary["steps"][0]["error_categories"]["model_unavailable"], "dependency_limited")
        self.assertEqual(summary["steps"][0]["error_registry_sample"]["code"], "missing_citation_input")
        self.assertEqual(summary["steps"][0]["error_registry_sample"]["next_action"], "provide_missing_input")
        self.assertIn("DOI", summary["steps"][0]["error_registry_sample"]["recovery"])
        self.assertFalse(summary["steps"][0]["error_registry_sample"]["retryable"])
        self.assertEqual(summary["steps"][0]["error_registry_sample"]["category"], "missing_input")
        self.assertEqual(summary["steps"][0]["sample_error"]["code"], "missing_citation_input")
        self.assertEqual(summary["steps"][0]["sample_error"]["next_action"], "provide_missing_input")
        self.assertFalse(summary["steps"][0]["sample_error"]["retryable"])
        self.assertEqual(summary["steps"][0]["sample_error"]["category"], "missing_input")
        self.assertEqual(summary["steps"][0]["sample_error"]["details_keys"], ["command"])
        self.assertEqual(summary["steps"][0]["runtime_config_error_details"]["field"], "CITEGUARD_SOURCES")
        self.assertEqual(summary["steps"][0]["runtime_config_error_details"]["source"], "environment")
        self.assertEqual(summary["steps"][0]["runtime_config_error_details"]["invalid_values"], ["bad"])
        self.assertEqual(summary["steps"][0]["runtime_config_error_details"]["valid_values"], ["arxiv", "openalex"])
        self.assertEqual(summary["steps"][0]["runtime_config_error_details"]["base_keys"], ["tool"])
        self.assertEqual(summary["steps"][0]["numeric_runtime_config_error_details"]["field"], "CITEGUARD_HTTP_TIMEOUT")
        self.assertEqual(summary["steps"][0]["numeric_runtime_config_error_details"]["source"], "environment")
        self.assertEqual(summary["steps"][0]["numeric_runtime_config_error_details"]["expected"], "positive integer")
        self.assertEqual(summary["steps"][0]["numeric_runtime_config_error_details"]["received"], "0")
        self.assertEqual(summary["steps"][0]["numeric_runtime_config_error_details"]["base_keys"], ["command"])
        self.assertEqual(summary["steps"][0]["docs_file"], "docs/error_codes.md")
        self.assertIn("docs stay synchronized", summary["steps"][0]["policy"])

    def test_release_gate_records_configuration_contract(self):
        summary = {"ok": True, "steps": []}

        _record_configuration_contract_gate(summary, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "configuration_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(
            summary["steps"][0]["docs_checked"],
            ["README.md", "docs/configuration.md", "docs/release_checklist.md"],
        )
        self.assertIn("CITEGUARD_SOURCES", summary["steps"][0]["environment_variables"])
        self.assertIn("CITEGUARD_FIXTURE_CITATIONS", summary["steps"][0]["environment_variables"])
        self.assertIn("CITEGUARD_HTTP_MIN_INTERVAL", summary["steps"][0]["environment_variables"])
        self.assertIn("SEMANTIC_SCHOLAR_API_KEY", summary["steps"][0]["environment_variables"])
        self.assertIn("source_health", summary["steps"][0]["status_fields"])
        self.assertIn("remote_evidence_policy", summary["steps"][0]["status_fields"])
        self.assertEqual(summary["steps"][0]["fixture_mode"], "fixture")
        self.assertEqual(summary["steps"][0]["cache_path"], ":memory:")
        self.assertEqual(summary["steps"][0]["http"]["timeout_seconds"], 7)
        self.assertEqual(summary["steps"][0]["http"]["retries"], 2)
        self.assertEqual(summary["steps"][0]["http"]["retry_backoff_seconds"], 0.5)
        self.assertEqual(summary["steps"][0]["http"]["min_interval_seconds"], 0.25)
        self.assertTrue(summary["steps"][0]["remote_evidence_enabled"])
        self.assertEqual(
            summary["steps"][0]["doc_discoverability"],
            {"readme_setup_reference": True, "release_checklist_documentation": True},
        )
        self.assertEqual(summary["steps"][0]["support_models"]["reranker_model"], "release-reranker")
        self.assertEqual(summary["steps"][0]["support_models"]["nli_model"], "release-nli")
        self.assertEqual(summary["steps"][0]["support_models"]["engine"], "heuristic_fallback")
        self.assertFalse(summary["steps"][0]["support_models"]["deep_models_available"])
        self.assertEqual(summary["steps"][0]["support_models"]["next_action"], "install_or_configure_dependency")
        self.assertIn("sentence_transformers", summary["steps"][0]["support_models"]["missing_dependencies"])
        model_install_hint = summary["steps"][0]["support_models"]["install_hint"]
        self.assertIn('python -m pip install "citeguard[models]"', model_install_hint)
        self.assertIn('python -m pip install -e ".[models]"', model_install_hint)
        self.assertLess(
            model_install_hint.index('python -m pip install "citeguard[models]"'),
            model_install_hint.index('python -m pip install -e ".[models]"'),
        )
        self.assertIn("configuration docs", summary["steps"][0]["policy"])

    def test_release_gate_records_cli_error_contract(self):
        summary = {"ok": True, "steps": []}

        _record_cli_error_contract_gate(summary, python=sys.executable, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "cli_error_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["schema_version"], ERROR_SCHEMA_VERSION)
        cases = {case["name"]: case for case in summary["steps"][0]["cases"]}
        self.assertEqual(
            set(cases),
            {
                "verify_missing_citation",
                "audit_missing_file",
                "extract_malformed_docx",
                "audit_malformed_docx",
                "support_audit_malformed_docx",
                "support_audit_invalid_jsonl",
                "support_missing_required_claim_arg",
                "verify_invalid_source_configuration",
            },
        )
        self.assertEqual(cases["verify_missing_citation"]["actual_code"], "missing_citation_input")
        self.assertEqual(cases["verify_missing_citation"]["next_action"], "provide_missing_input")
        self.assertFalse(cases["verify_missing_citation"]["retryable"])
        self.assertEqual(cases["verify_missing_citation"]["category"], "missing_input")
        self.assertIn("command", cases["verify_missing_citation"]["details_keys"])
        self.assertEqual(cases["audit_missing_file"]["actual_code"], "file_error")
        self.assertEqual(cases["audit_missing_file"]["next_action"], "repair_input")
        self.assertFalse(cases["audit_missing_file"]["retryable"])
        self.assertEqual(cases["audit_missing_file"]["category"], "input_repair")
        self.assertIn("errno", cases["audit_missing_file"]["details_keys"])
        self.assertIn("filename", cases["audit_missing_file"]["details_keys"])
        for case_name in ["extract_malformed_docx", "audit_malformed_docx", "support_audit_malformed_docx"]:
            with self.subTest(case_name=case_name):
                self.assertEqual(cases[case_name]["actual_code"], "file_error")
                self.assertEqual(cases[case_name]["next_action"], "repair_input")
                self.assertFalse(cases[case_name]["retryable"])
                self.assertEqual(cases[case_name]["category"], "input_repair")
                self.assertIn("filename", cases[case_name]["details_keys"])
        self.assertEqual(cases["support_audit_invalid_jsonl"]["actual_code"], "invalid_json")
        self.assertIn("line", cases["support_audit_invalid_jsonl"]["details_keys"])
        self.assertIn("column", cases["support_audit_invalid_jsonl"]["details_keys"])
        self.assertEqual(cases["support_missing_required_claim_arg"]["actual_code"], "argument_parse_error")
        self.assertIn("prog", cases["support_missing_required_claim_arg"]["details_keys"])
        self.assertIn("arguments", cases["support_missing_required_claim_arg"]["details_keys"])
        self.assertEqual(cases["verify_invalid_source_configuration"]["actual_code"], "invalid_input")
        self.assertIn("source", cases["verify_invalid_source_configuration"]["details_keys"])
        self.assertIn("valid_values", cases["verify_invalid_source_configuration"]["details_keys"])

    def test_release_gate_records_source_outage_safety_contract(self):
        summary = {"ok": True, "steps": []}

        _record_source_outage_safety_gate(summary, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "source_outage_safety")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        verification = summary["steps"][0]["verification"]
        self.assertEqual(verification["verdict"], "not_found")
        self.assertLessEqual(verification["confidence"], 0.35)
        self.assertEqual(verification["source_failure_mode"], "all_sources_failed")
        self.assertTrue(verification["outage_limited"])
        self.assertEqual(verification["sources_failed"], ["release_timeout_source"])
        self.assertEqual(verification["sources_available"], [])
        self.assertEqual(verification["recovery_code"], "timeout")
        self.assertEqual(verification["next_action"], "retry_or_check_source_health")
        rate_limited = summary["steps"][0]["rate_limited_verification"]
        self.assertEqual(rate_limited["verdict"], "not_found")
        self.assertEqual(rate_limited["source_failure_mode"], "all_sources_failed")
        self.assertEqual(rate_limited["sources_failed"], ["release_rate_limited_source"])
        self.assertEqual(rate_limited["retry_after_seconds"], 2.0)
        self.assertEqual(rate_limited["next_action"], "retry_or_check_source_health")
        health = summary["steps"][0]["source_health"]
        self.assertEqual(health["sources_checked"], ["openalex", "crossref"])
        self.assertEqual(health["sources_responded"], ["crossref"])
        self.assertEqual(health["sources_failed"], ["openalex"])
        self.assertEqual(health["failure_kind_counts"], {"timeout": 1})
        self.assertEqual(health["failure_kind_sources"], {"timeout": ["openalex"]})
        self.assertEqual(health["next_action"], "retry_or_check_source_health")
        self.assertFalse(health["all_checked_sources_failed"])
        self.assertEqual(health["confidence_effect"], "partial_source_limited")
        self.assertEqual(health["interpretation"], "source_outage_lowers_confidence_not_fabrication_evidence")

    def test_release_gate_records_counterevidence_safety_contract(self):
        summary = {"ok": True, "steps": []}

        _record_counterevidence_safety_contract_gate(summary, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "counterevidence_safety_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["next_action"], "review_counterevidence_leads")
        self.assertEqual(summary["steps"][0]["candidate_count"], 1)
        self.assertEqual(summary["steps"][0]["candidate_signal"], "explicit_contradiction_cue")
        self.assertIn("improvement_negation", summary["steps"][0]["candidate_query_roles"])
        self.assertEqual(
            summary["steps"][0]["review_summary"]["recommended_next_steps"]["first_queue"],
            "explicit_contradiction_candidate_indexes",
        )
        self.assertEqual(
            summary["steps"][0]["review_summary"]["recommended_next_steps"]["explicit_contradiction_candidate_indexes"],
            [0],
        )
        self.assertIn("review leads, not a contradiction verdict", summary["steps"][0]["interpretation"])
        self.assertIn("review leads only", summary["steps"][0]["policy"])

    def test_release_gate_records_full_text_evidence_boundary_contract(self):
        summary = {"ok": True, "steps": []}

        _record_full_text_evidence_boundary_contract_gate(summary, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "full_text_evidence_boundary_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertIn("docs/security_compliance.md", summary["steps"][0]["docs_checked"])
        self.assertEqual(summary["steps"][0]["full_text_probe"]["evidence_scope"], "full_text")
        self.assertEqual(
            summary["steps"][0]["full_text_probe"]["source_field"],
            "user_full_text_excerpt_1",
        )
        self.assertNotEqual(summary["steps"][0]["abstract_probe"]["evidence_scope"], "full_text")
        self.assertIn("local/user-provided", summary["steps"][0]["policy"])

    def test_release_gate_records_support_set_aggregation_contract(self):
        summary = {"ok": True, "steps": []}

        _record_support_set_aggregation_contract_gate(summary, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "support_set_aggregation_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["verdict"], "weakly_supported")
        self.assertEqual(summary["steps"][0]["support_mode"], "multiple_weak_support")
        self.assertEqual(summary["steps"][0]["next_action"], "tighten_claim_or_inspect_full_text")
        self.assertEqual(summary["steps"][0]["risk"], "medium")
        self.assertEqual(summary["steps"][0]["evidence_scope"], "abstract")
        self.assertEqual(summary["steps"][0]["evidence_scopes"], ["abstract"])
        self.assertEqual(summary["steps"][0]["evidence_source_names"], ["release_fixture"])
        self.assertEqual(summary["steps"][0]["evidence_source_fields"], ["abstract_sentence_1"])
        self.assertEqual(summary["steps"][0]["evidence_indexes"], [0, 1])
        self.assertEqual(summary["steps"][0]["supporting_citation_count"], 2)
        self.assertEqual(summary["steps"][0]["contradicting_citation_count"], 0)
        self.assertEqual(
            summary["steps"][0]["support_mode_details"]["decision"],
            "multiple_weak_citations_remain_tentative",
        )
        self.assertIn(
            "no_unstated_multi_hop_or_full_text_support",
            summary["steps"][0]["support_mode_details"]["policy"],
        )
        self.assertEqual(summary["steps"][0]["support_mode_details"]["weakly_supported_indexes"], [0, 1])
        self.assertEqual(summary["steps"][0]["support_mode_details"]["supported_indexes"], [])
        self.assertEqual(summary["steps"][0]["support_mode_details"]["contradicted_indexes"], [])
        self.assertFalse(summary["steps"][0]["support_mode_details"]["full_text_evidence_present"])
        self.assertIn("multiple weak citation-set evidence remains tentative", summary["steps"][0]["policy"])

    def test_release_gate_records_live_source_health_contract(self):
        summary = {"ok": True, "steps": []}

        _record_live_source_health_contract_gate(summary, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "live_source_health_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(
            summary["steps"][0]["docs_checked"],
            ["README.md", "docs/cli_reference.md", "docs/release_checklist.md", "docs/security_compliance.md"],
        )
        self.assertEqual(
            summary["steps"][0]["aliases_checked"],
            ["OpenAlex", "crossref", "arxiv", "semantic-scholar", "s2"],
        )
        self.assertEqual(
            summary["steps"][0]["canonical_sources"],
            ["openalex", "crossref", "arxiv", "semantic_scholar"],
        )
        self.assertEqual(
            summary["steps"][0]["sources_checked"],
            ["openalex", "crossref", "arxiv", "semantic_scholar"],
        )
        self.assertEqual(summary["steps"][0]["sources_responded"], ["arxiv"])
        self.assertEqual(summary["steps"][0]["sources_failed"], ["openalex", "crossref", "semantic_scholar"])
        self.assertEqual(
            summary["steps"][0]["failure_kind_counts"],
            {"timeout": 1, "invalid_json": 1, "rate_limited": 1},
        )
        self.assertEqual(
            summary["steps"][0]["failure_kind_sources"],
            {"timeout": ["openalex"], "invalid_json": ["crossref"], "rate_limited": ["semantic_scholar"]},
        )
        self.assertEqual(summary["steps"][0]["retry_after_seconds"], 2.0)
        self.assertEqual(summary["steps"][0]["retry_after_sources"], ["semantic_scholar"])
        self.assertEqual(summary["steps"][0]["retry_delay_seconds"], 1.5)
        self.assertEqual(summary["steps"][0]["retry_delay_sources"], ["semantic_scholar"])
        self.assertEqual(summary["steps"][0]["retry_guidance"], "wait_before_retry")
        self.assertEqual(summary["steps"][0]["zero_retry_after"]["retry_after_seconds"], 0.0)
        self.assertEqual(summary["steps"][0]["zero_retry_after"]["retry_after_sources"], ["semantic_scholar"])
        self.assertIsNone(summary["steps"][0]["zero_retry_after"]["retry_delay_seconds"])
        self.assertEqual(summary["steps"][0]["zero_retry_after"]["retry_delay_sources"], [])
        self.assertIsNone(summary["steps"][0]["zero_retry_after"]["source_retry_delay_seconds"])
        self.assertEqual(
            summary["steps"][0]["zero_retry_after"]["summary_retry_guidance"],
            "retry_or_check_source_health",
        )
        self.assertEqual(
            summary["steps"][0]["zero_retry_after"]["source_retry_guidance"],
            "retry_or_check_source_health",
        )
        failure_details = {item["source"]: item for item in summary["steps"][0]["failure_details"]}
        self.assertEqual(failure_details["crossref"]["kind"], "invalid_json")
        self.assertEqual(failure_details["crossref"]["code"], "source_unavailable")
        self.assertEqual(failure_details["crossref"]["status_code"], 200)
        self.assertEqual(failure_details["semantic_scholar"]["attempt_count"], 2)
        self.assertEqual(failure_details["semantic_scholar"]["retry_count"], 1)
        self.assertEqual(
            failure_details["semantic_scholar"]["final_url"],
            "https://api.semanticscholar.org/graph/v1/paper/search?offset=0",
        )
        self.assertTrue(failure_details["semantic_scholar"]["redirected"])
        self.assertEqual(failure_details["semantic_scholar"]["retry_after_seconds"], 2.0)
        self.assertEqual(failure_details["semantic_scholar"]["retry_delay_seconds"], 1.5)
        self.assertEqual(summary["steps"][0]["confidence_effect"], "partial_source_limited")
        self.assertEqual(
            summary["steps"][0]["interpretation"],
            "source_outage_lowers_confidence_not_fabrication_evidence",
        )
        self.assertTrue(summary["steps"][0]["semantic_scholar"]["api_key_configured"])
        self.assertEqual(summary["steps"][0]["semantic_scholar"]["polite_access"]["status"], "not_required")
        self.assertEqual(summary["steps"][0]["semantic_scholar"]["retry_delay_seconds"], 1.5)
        metadata_quality = summary["steps"][0]["metadata_quality_contract"]
        self.assertIn("identifier", metadata_quality["crossref"]["present_fields"])
        self.assertIn("identifier", metadata_quality["arxiv"]["present_fields"])
        self.assertTrue(metadata_quality["crossref"]["identifiers"]["doi"])
        self.assertTrue(metadata_quality["arxiv"]["identifiers"]["arxiv_id"])
        self.assertIn("identifier", metadata_quality["openalex"]["missing_fields"])
        self.assertIn("identifier", metadata_quality["semantic_scholar"]["missing_fields"])
        self.assertEqual(
            metadata_quality["openalex"]["confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )
        self.assertIn("OpenAlex, Crossref, arXiv, and Semantic Scholar", summary["steps"][0]["policy"])

    def test_release_gate_records_security_compliance_contract(self):
        summary = {"ok": True, "steps": []}

        _record_security_compliance_contract_gate(summary, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "security_compliance_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(
            summary["steps"][0]["docs_checked"],
            ["README.md", "docs/chinaxiv_spike.md", "docs/release_checklist.md", "docs/security_compliance.md"],
        )
        self.assertIn("cnki.net", summary["steps"][0]["blocked_gated_source_suffixes"])
        self.assertIn("wanfangdata.com", summary["steps"][0]["blocked_gated_source_suffixes"])
        self.assertIn("cqvip.com", summary["steps"][0]["blocked_gated_source_suffixes"])
        missing_contact = summary["steps"][0]["missing_contact"]
        self.assertEqual(missing_contact["status"], "missing_contact_email")
        self.assertFalse(missing_contact["compliant"])
        self.assertEqual(missing_contact["configured_contact_required_sources"], ["openalex", "crossref"])
        self.assertEqual(missing_contact["next_action"], "fix_configuration")
        configured_contact = summary["steps"][0]["configured_contact"]
        self.assertEqual(configured_contact["status"], "configured")
        self.assertTrue(configured_contact["compliant"])
        self.assertEqual(configured_contact["configured_contact_required_sources"], ["openalex"])
        self.assertEqual(configured_contact["next_action"], "continue")
        fixture_mode = summary["steps"][0]["fixture_mode"]
        self.assertEqual(fixture_mode["status"], "fixture_bypasses_live_sources")
        self.assertTrue(fixture_mode["compliant"])
        self.assertEqual(fixture_mode["next_action"], "continue")
        mailto_policy = summary["steps"][0]["mailto_parameter_policy"]
        self.assertEqual(mailto_policy["placeholder_contact"], "research@example.com")
        self.assertEqual(mailto_policy["default_mailto_by_source"], {"openalex": "", "crossref": ""})
        self.assertTrue(
            all("research@example.com" not in user_agent for user_agent in mailto_policy["default_user_agents"].values())
        )
        self.assertEqual(
            mailto_policy["configured_mailto_by_source"],
            {"openalex": "release-gate@example.com", "crossref": "release-gate@example.com"},
        )
        self.assertTrue(
            all(
                "mailto:release-gate@example.com" in user_agent
                for user_agent in mailto_policy["configured_user_agents"].values()
            )
        )
        self.assertIn("placeholder contact emails", mailto_policy["policy"])
        polite_access = summary["steps"][0]["source_health_polite_access"]
        self.assertEqual(polite_access["openalex"]["status"], "missing_contact_email")
        self.assertEqual(polite_access["crossref"]["status"], "missing_contact_email")
        self.assertEqual(polite_access["arxiv"]["status"], "not_required")
        self.assertEqual(polite_access["semantic_scholar"]["status"], "not_required")
        self.assertEqual(polite_access["semantic_scholar"]["next_action"], "continue")
        self.assertFalse(summary["steps"][0]["remote_evidence_policy"]["default_enabled"])
        self.assertFalse(summary["steps"][0]["remote_evidence_policy"]["non_http_urls_allowed"])
        fetch_smoke = summary["steps"][0]["remote_evidence_fetch_smoke"]
        self.assertEqual(fetch_smoke["requested_urls"], ["https://example.org/open-paper"])
        self.assertEqual(
            fetch_smoke["blocked_url_checks"],
            {"cnki": False, "wanfang": False, "file": False, "open_http": True},
        )
        self.assertGreaterEqual(fetch_smoke["chunk_count"], 1)
        self.assertEqual(fetch_smoke["failure_count"], 0)
        rate_limited_failure = fetch_smoke["rate_limited_failure"]
        self.assertEqual(rate_limited_failure["requested_urls"], ["https://example.org/rate-limited-paper"])
        self.assertEqual(rate_limited_failure["code"], "source_unavailable")
        self.assertEqual(rate_limited_failure["kind"], "rate_limited")
        self.assertEqual(rate_limited_failure["status_code"], 429)
        self.assertEqual(rate_limited_failure["attempt_count"], 1)
        self.assertEqual(rate_limited_failure["retry_count"], 0)
        self.assertEqual(rate_limited_failure["retry_after_seconds"], 2.0)
        self.assertIsNone(rate_limited_failure["retry_delay_seconds"])
        non_html_failure = fetch_smoke["non_html_failure"]
        self.assertEqual(non_html_failure["requested_urls"], ["https://example.org/publisher.pdf"])
        self.assertEqual(non_html_failure["code"], "source_unavailable")
        self.assertEqual(non_html_failure["kind"], "non_html_response")
        self.assertEqual(non_html_failure["status_code"], 200)
        self.assertEqual(non_html_failure["attempt_count"], 1)
        self.assertEqual(non_html_failure["retry_count"], 0)
        self.assertIsNone(non_html_failure["retry_delay_seconds"])
        no_extractable_failure = fetch_smoke["no_extractable_failure"]
        self.assertEqual(no_extractable_failure["requested_urls"], ["https://example.org/empty-publisher-page"])
        self.assertEqual(no_extractable_failure["code"], "source_unavailable")
        self.assertEqual(no_extractable_failure["kind"], "no_extractable_evidence")
        self.assertEqual(no_extractable_failure["status_code"], 200)
        self.assertEqual(no_extractable_failure["attempt_count"], 1)
        self.assertEqual(no_extractable_failure["retry_count"], 0)
        self.assertIsNone(no_extractable_failure["retry_delay_seconds"])
        self.assertIn("no gated-source/paywall bypass", summary["steps"][0]["policy"])

    def test_release_gate_records_agent_skill_contract(self):
        summary = {"ok": True, "steps": []}

        _record_agent_skill_contract_gate(summary, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "agent_skill_contract")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["skill_file"], "skills/citeguard-verify/SKILL.md")
        self.assertEqual(
            summary["steps"][0]["examples_file"],
            "skills/citeguard-verify/references/examples.md",
        )
        self.assertEqual(summary["steps"][0]["checked_contracts"]["trigger_count"], 3)
        self.assertEqual(summary["steps"][0]["checked_contracts"]["forbidden_behavior_count"], 3)
        self.assertEqual(summary["steps"][0]["checked_contracts"]["client_setup_count"], 3)
        self.assertEqual(summary["steps"][0]["checked_contracts"]["tool_example_count"], 10)
        self.assertEqual(
            summary["steps"][0]["checked_contracts"]["support_audit_reference_file_example_count"],
            1,
        )
        self.assertEqual(summary["steps"][0]["checked_contracts"]["structured_error_example_count"], 1)
        self.assertEqual(summary["steps"][0]["checked_contracts"]["file_error_example_count"], 1)
        self.assertEqual(summary["steps"][0]["checked_contracts"]["safe_wording_example_count"], 7)
        self.assertEqual(summary["steps"][0]["checked_contracts"]["full_text_support_payload_example_count"], 1)
        self.assertEqual(summary["steps"][0]["checked_contracts"]["full_text_file_support_payload_example_count"], 3)
        self.assertEqual(summary["steps"][0]["checked_contracts"]["full_text_boundary_example_count"], 1)
        self.assertEqual(summary["steps"][0]["checked_contracts"]["policy_boundary_example_count"], 1)
        self.assertEqual(summary["steps"][0]["checked_contracts"]["pre_response_safety_check_count"], 5)
        skill = (ROOT / "skills" / "citeguard-verify" / "SKILL.md").read_text(encoding="utf-8")
        examples = (ROOT / "skills" / "citeguard-verify" / "references" / "examples.md").read_text(encoding="utf-8")
        self.assertIn("`overall.macro_f1`", skill)
        self.assertIn("`overall.weighted_f1`", skill)
        self.assertIn("compiled `.bbl`", skill)
        self.assertIn("Markdown/LaTeX/BibTeX/BBL/DOCX/plain-text", skill)
        self.assertIn("Markdown/LaTeX/BibTeX/BBL/DOCX", examples)
        self.assertIn("citeguard extract paper.bbl", examples)
        self.assertIn("source_format=bbl", examples)
        self.assertIn("do not treat the `.bbl` as proof", examples)
        self.assertIn("compact metric snapshot", examples)
        support_cases = [
            case for case in load_support_eval(str(ROOT / "data" / "eval" / "support_eval.json")) if case.split == "test"
        ]
        support_report = run_support_eval_report(support_cases, HeuristicSupportBackend())
        self.assertIn(f'"macro_f1": {support_report["overall"]["macro_f1"]}', examples)
        self.assertIn(f'"weighted_f1": {support_report["overall"]["weighted_f1"]}', examples)
        self.assertIn(
            f'`false_support_analysis.review_plan.status={support_report["false_support_analysis"]["review_plan"]["status"]}`',
            examples,
        )
        self.assertIn("do not use accuracy alone", examples)
        readme = ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8"))
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        jsonl_high_risk_command = "citeguard support-audit examples/claim_citations.jsonl --high-risk-only"
        self.assertIn(jsonl_high_risk_command, readme)
        self.assertIn(jsonl_high_risk_command, cli_reference)
        self.assertEqual(summary["steps"][0]["checked_contracts"]["source_health_confidence_contract_count"], 1)
        self.assertEqual(summary["steps"][0]["checked_contracts"]["presentation_example_count"], 1)
        self.assertEqual(summary["steps"][0]["checked_contracts"]["scenario_response_example_count"], 2)
        self.assertIn("Ambiguous compact response example:", examples)
        self.assertIn("Metadata mismatch compact response example:", examples)
        self.assertIn("`disambiguate_identifier`", examples)
        self.assertIn("`review_metadata`", examples)
        self.assertIn("`field_diffs=year,venue`", examples)
        self.assertIn("`suggested_fix.requires_user_confirmation=true`", examples)
        self.assertIn("proactively audit citations", summary["steps"][0]["policy"])
        self.assertIn("without silent edits", summary["steps"][0]["policy"])

    def test_release_gate_records_batch_workflow_examples_contract(self):
        summary = {"ok": True, "steps": []}

        _record_batch_workflow_examples_gate(summary, python=sys.executable, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "batch_workflow_examples")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["fixture"], "examples/citations.json")
        self.assertEqual(summary["steps"][0]["jsonl_fixture"], "examples/citations.jsonl")
        self.assertEqual(
            set(summary["steps"][0]["help_commands"]),
            {"audit_help", "support_set_help", "support_audit_help"},
        )
        for name, contract in summary["steps"][0]["help_contracts"].items():
            with self.subTest(help_contract=name):
                self.assertTrue(contract["documents_jsonl"])
                self.assertTrue(contract["documents_reference_files"])
                self.assertTrue(contract["documents_bibtex_bbl"])
        readme = ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8"))
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        release_note = (ROOT / "docs" / "releases" / "v0.1.0.md").read_text(encoding="utf-8")
        reference_input_phrase = "Markdown/LaTeX/BibTeX/BBL/DOCX"
        self.assertIn(reference_input_phrase, readme)
        self.assertIn(reference_input_phrase, cli_reference)
        self.assertIn("LaTeX/BibTeX/BBL", release_note)
        self.assertEqual(summary["steps"][0]["extract_count"], 2)
        self.assertEqual(summary["steps"][0]["extract_line_range"]["source_line_start"], 5)
        self.assertEqual(summary["steps"][0]["extract_line_range"]["source_line_end"], 5)
        self.assertEqual(summary["steps"][0]["extract_latex_bibliography"]["count"], 1)
        self.assertEqual(summary["steps"][0]["extract_latex_bibliography"]["source_format"], "bibtex")
        self.assertEqual(summary["steps"][0]["extract_latex_bibliography"]["source_id"], "vaswani2017")
        self.assertEqual(summary["steps"][0]["extract_latex_bibliography"]["title"], "Attention Is All You Need")
        self.assertTrue(summary["steps"][0]["extract_latex_bibliography"]["source_path"].endswith("refs.bib"))
        self.assertTrue(summary["steps"][0]["extract_latex_bibliography"]["expanded_macro_venue"])
        self.assertEqual(summary["steps"][0]["extract_latex_bbl"]["count"], 1)
        self.assertEqual(summary["steps"][0]["extract_latex_bbl"]["source_format"], "bbl")
        self.assertEqual(summary["steps"][0]["extract_latex_bbl"]["source_id"], "vaswani2017")
        self.assertTrue(summary["steps"][0]["extract_latex_bbl"]["source_path"].endswith("paper.bbl"))
        self.assertTrue(summary["steps"][0]["extract_latex_bbl"]["source_locator"].endswith("paper.bbl#citation-1"))
        self.assertEqual(summary["steps"][0]["extract_latex_bbl"]["arxiv_id"], "1706.03762")
        self.assertEqual(summary["steps"][0]["extract_pasted_reference_list"]["count"], 2)
        self.assertEqual(summary["steps"][0]["extract_pasted_reference_list"]["source_type"], "reference_list")
        self.assertEqual(summary["steps"][0]["extract_pasted_reference_list"]["source_format"], "text")
        self.assertTrue(summary["steps"][0]["extract_pasted_reference_list"]["wrapped_continuation"])
        self.assertEqual(
            summary["steps"][0]["extract_pasted_reference_list"]["line_range"],
            {"source_line_start": 1, "source_line_end": 2},
        )
        self.assertEqual(summary["steps"][0]["extract_unnumbered_reference_list"]["count"], 2)
        self.assertEqual(summary["steps"][0]["extract_unnumbered_reference_list"]["source_type"], "reference_list")
        self.assertEqual(summary["steps"][0]["extract_unnumbered_reference_list"]["source_format"], "text")
        self.assertEqual(
            summary["steps"][0]["extract_unnumbered_reference_list"]["line_range"],
            {"source_line_start": 1, "source_line_end": 1},
        )
        self.assertEqual(summary["steps"][0]["extract_docx_reference_list"]["count"], 2)
        self.assertEqual(summary["steps"][0]["extract_docx_reference_list"]["source_format"], "docx")
        self.assertTrue(summary["steps"][0]["extract_docx_reference_list"]["source_path"].endswith("references.docx"))
        self.assertTrue(
            summary["steps"][0]["extract_docx_reference_list"]["source_locator"].endswith(
                "references.docx#citation-1"
            )
        )
        self.assertEqual(
            summary["steps"][0]["extract_docx_reference_list"]["line_range"],
            {"source_line_start": 2, "source_line_end": 2},
        )
        self.assertEqual(summary["steps"][0]["audit_summary"]["verified"], 1)
        self.assertEqual(summary["steps"][0]["audit_summary"]["not_found"], 1)
        self.assertFalse(
            summary["steps"][0]["audit_review_summary_source_traceability"]["has_source_backed_items"]
        )
        self.assertEqual(summary["steps"][0]["audit_review_summary_source_traceability"]["source_indexes"], [])
        self.assertEqual(summary["steps"][0]["audit_top_risk_reason"], "no_strong_match")
        self.assertEqual(summary["steps"][0]["audit_top_suggested_fix"]["kind"], "add_identifier_or_replace")
        self.assertTrue(summary["steps"][0]["audit_top_suggested_fix"]["requires_user_confirmation"])
        self.assertEqual(
            summary["steps"][0]["audit_top_suggested_fix"]["policy"],
            "not_found_is_high_risk_not_fabrication_proof",
        )
        self.assertFalse(summary["steps"][0]["audit_suggested_fix_summary"]["auto_apply_allowed"])
        self.assertEqual(
            summary["steps"][0]["audit_suggested_fix_summary"]["confirmation_required_indexes"],
            [1],
        )
        self.assertEqual(
            summary["steps"][0]["audit_suggested_fix_summary"]["no_confirmation_required_indexes"],
            [0],
        )
        self.assertEqual(
            summary["steps"][0]["audit_suggested_fix_summary"]["fix_kind_indexes"]["add_identifier_or_replace"],
            [1],
        )
        self.assertEqual(
            summary["steps"][0]["audit_suggested_fix_summary"]["fix_kind_indexes"]["keep"],
            [0],
        )
        self.assertEqual(summary["steps"][0]["audit_suggested_fix_summary"]["missing_suggested_fix_indexes"], [])
        self.assertIn("must_not_silently_apply", summary["steps"][0]["audit_suggested_fix_summary"]["policy"])
        self.assertEqual(summary["steps"][0]["audit_latex_bibliography"]["summary"]["verified"], 1)
        self.assertEqual(summary["steps"][0]["audit_latex_bibliography"]["input_source_format"], "bibtex")
        self.assertEqual(summary["steps"][0]["audit_jsonl_returned_indexes"], [1])
        self.assertEqual(summary["steps"][0]["audit_jsonl_omitted_review_summary"]["low_risk_count"], 1)
        self.assertEqual(
            summary["steps"][0]["audit_jsonl_omitted_review_summary"]["action_queues"]["safe_to_keep_indexes"],
            [0],
        )
        self.assertFalse(
            summary["steps"][0]["audit_jsonl_omitted_review_summary"]["suggested_fix_summary"][
                "auto_apply_allowed"
            ]
        )
        self.assertEqual(
            summary["steps"][0]["audit_jsonl_omitted_review_summary"]["suggested_fix_summary"][
                "fix_kind_indexes"
            ]["keep"],
            [0],
        )
        self.assertEqual(summary["steps"][0]["audit_metadata_mismatch_fields"], ["year", "venue"])
        self.assertEqual(
            summary["steps"][0]["audit_metadata_mismatch_risk_reason"],
            "metadata_fields_mismatch",
        )
        self.assertEqual(
            summary["steps"][0]["audit_metadata_mismatch_suggested_fix"]["kind"],
            "review_metadata_correction",
        )
        self.assertEqual(
            summary["steps"][0]["audit_metadata_mismatch_suggested_fix"]["mismatched_fields"],
            ["year", "venue"],
        )
        self.assertTrue(summary["steps"][0]["audit_metadata_suggested_citation_present"])
        self.assertEqual(
            summary["steps"][0]["audit_sparse_metadata_quality"]["missing_fields"],
            ["venue", "abstract", "url"],
        )
        self.assertEqual(
            summary["steps"][0]["audit_sparse_metadata_quality"]["confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )
        self.assertTrue(summary["steps"][0]["audit_sparse_metadata_quality"]["identifier_provenance"]["doi"])
        self.assertEqual(summary["steps"][0]["audit_returned_indexes"], [1])
        self.assertEqual(
            summary["steps"][0]["audit_markdown_source_traceability"]["source_paths"],
            ["examples/references.md"],
        )
        self.assertEqual(summary["steps"][0]["audit_markdown_source_traceability"]["source_indexes"], [1, 2])
        self.assertEqual(summary["steps"][0]["audit_markdown_source_traceability"]["high_risk_source_indexes"], [2])
        self.assertEqual(
            summary["steps"][0]["audit_markdown_source_traceability"]["review_required_source_indexes"],
            [2],
        )
        self.assertIn(
            "examples/references.md#citation-2",
            summary["steps"][0]["audit_markdown_source_traceability"]["review_required_source_locators"],
        )
        self.assertEqual(
            summary["steps"][0]["audit_markdown_line_range"],
            {"input_source_line_start": 6, "input_source_line_end": 6},
        )
        self.assertEqual(summary["steps"][0]["audit_docx_returned_indexes"], [1])
        self.assertEqual(summary["steps"][0]["audit_docx_source_traceability"]["source_formats"], ["docx"])
        self.assertEqual(summary["steps"][0]["audit_docx_source_traceability"]["source_indexes"], [1, 2])
        self.assertEqual(summary["steps"][0]["audit_docx_source_traceability"]["high_risk_source_indexes"], [2])
        self.assertTrue(summary["steps"][0]["audit_docx_source_traceability"]["source_paths"][0].endswith("references.docx"))
        self.assertEqual(summary["steps"][0]["audit_docx_omitted_source_traceability"]["source_indexes"], [1])
        self.assertEqual(
            summary["steps"][0]["audit_docx_line_range"],
            {"input_source_line_start": 3, "input_source_line_end": 3},
        )
        self.assertEqual(summary["steps"][0]["audit_triage_plan"]["schema_version"], 1)
        self.assertEqual(summary["steps"][0]["audit_triage_plan"]["status"], "review_required")
        self.assertEqual(summary["steps"][0]["audit_triage_plan"]["first_queue"], "identity_resolution_indexes")
        self.assertEqual(summary["steps"][0]["audit_triage_plan"]["review_required_indexes"], [1])
        self.assertIn(
            "source_retry_is_inconclusive_not_fabrication",
            summary["steps"][0]["audit_triage_plan"]["policy"],
        )
        self.assertEqual(summary["steps"][0]["support_summary"]["insufficient_evidence"], 3)
        self.assertFalse(
            summary["steps"][0]["support_review_summary_source_traceability"]["has_source_backed_items"]
        )
        self.assertEqual(summary["steps"][0]["support_triage_plan"]["schema_version"], 1)
        self.assertEqual(summary["steps"][0]["support_triage_plan"]["status"], "review_required")
        self.assertEqual(summary["steps"][0]["support_triage_plan"]["first_queue"], "identity_resolution_indexes")
        self.assertEqual(summary["steps"][0]["support_triage_plan"]["review_required_indexes"], [1, 2, 0])
        self.assertEqual(summary["steps"][0]["support_triage_plan"]["high_risk_indexes"], [1])
        self.assertFalse(summary["steps"][0]["support_suggested_fix_summary"]["auto_apply_allowed"])
        self.assertEqual(
            summary["steps"][0]["support_suggested_fix_summary"]["confirmation_required_indexes"],
            [1, 2, 0],
        )
        self.assertEqual(
            summary["steps"][0]["support_suggested_fix_summary"]["fix_kind_indexes"]["resolve_citation_identity"],
            [1],
        )
        self.assertEqual(
            summary["steps"][0]["support_suggested_fix_summary"]["fix_kind_indexes"][
                "inspect_full_text_or_find_stronger_citation"
            ],
            [2, 0],
        )
        self.assertEqual(summary["steps"][0]["support_suggested_fix_summary"]["missing_suggested_fix_indexes"], [])
        self.assertIn("must_not_silently_apply", summary["steps"][0]["support_suggested_fix_summary"]["policy"])
        self.assertEqual(
            summary["steps"][0]["support_risk_provenance"]["risk_reason"],
            "citation_identity_unresolved",
        )
        self.assertEqual(
            summary["steps"][0]["support_risk_provenance"]["suggested_fix"]["kind"],
            "resolve_citation_identity",
        )
        self.assertEqual(
            summary["steps"][0]["support_risk_provenance"]["suggested_fix"]["policy"],
            "resolve_identity_before_judging_support",
        )
        self.assertEqual(summary["steps"][0]["support_risk_provenance"]["support_confidence"], 0.0)
        self.assertEqual(summary["steps"][0]["support_risk_provenance"]["support_engine"], "none")
        self.assertEqual(summary["steps"][0]["support_risk_provenance"]["resolution_verdict"], "not_found")
        self.assertEqual(summary["steps"][0]["support_risk_provenance"]["evidence_source_name"], "none")
        self.assertEqual(summary["steps"][0]["support_risk_provenance"]["evidence_source_field"], "none")
        self.assertEqual(
            summary["steps"][0]["support_sparse_metadata_quality"]["result_missing_fields"],
            ["venue", "abstract", "url"],
        )
        self.assertEqual(
            summary["steps"][0]["support_sparse_metadata_quality"]["risk_missing_fields"],
            ["venue", "abstract", "url"],
        )
        self.assertEqual(
            summary["steps"][0]["support_sparse_metadata_quality"]["risk_confidence_effect"],
            "missing_metadata_lowers_confidence_not_fabrication_evidence",
        )
        self.assertEqual(summary["steps"][0]["support_input_modes"], ["citation", "citation", "citation_set"])
        self.assertEqual(summary["steps"][0]["support_returned_indexes"], [1])
        self.assertEqual(summary["steps"][0]["support_omitted_review_summary"]["medium_risk_count"], 2)
        self.assertFalse(
            summary["steps"][0]["support_omitted_review_summary"]["suggested_fix_summary"]["auto_apply_allowed"]
        )
        self.assertEqual(
            summary["steps"][0]["support_omitted_review_summary"]["suggested_fix_summary"][
                "confirmation_required_indexes"
            ],
            [2, 0],
        )
        self.assertEqual(summary["steps"][0]["support_full_text_summary"]["weakly_supported"], 1)
        self.assertEqual(summary["steps"][0]["support_full_text_evidence_scope"], "full_text")
        self.assertEqual(summary["steps"][0]["support_full_text_source_name"], "user_provided")
        self.assertEqual(summary["steps"][0]["support_full_text_source_field"], "user_full_text_excerpt_1")
        self.assertEqual(summary["steps"][0]["support_full_text_resolution_verdict"], "matched")
        self.assertEqual(summary["steps"][0]["support_full_text_risk"]["evidence_scope"], "full_text")
        self.assertEqual(summary["steps"][0]["support_full_text_risk"]["evidence_source_name"], "user_provided")
        self.assertEqual(
            summary["steps"][0]["support_full_text_risk"]["evidence_source_field"],
            "user_full_text_excerpt_1",
        )
        self.assertEqual(
            summary["steps"][0]["support_full_text_risk"]["next_action"],
            "tighten_claim_or_inspect_full_text",
        )
        self.assertEqual(summary["steps"][0]["support_full_text_file_summary"]["weakly_supported"], 1)
        self.assertEqual(summary["steps"][0]["support_full_text_file_evidence_scope"], "full_text")
        self.assertEqual(summary["steps"][0]["support_full_text_file_source_name"], "user_provided")
        self.assertEqual(summary["steps"][0]["support_full_text_file_source_field"], "user_full_text_file_1")
        self.assertEqual(summary["steps"][0]["support_full_text_file_resolution_verdict"], "matched")
        self.assertEqual(summary["steps"][0]["support_full_text_file_risk"]["evidence_scope"], "full_text")
        self.assertEqual(summary["steps"][0]["support_full_text_file_risk"]["evidence_source_name"], "user_provided")
        self.assertEqual(
            summary["steps"][0]["support_full_text_file_risk"]["evidence_source_field"],
            "user_full_text_file_1",
        )
        self.assertEqual(
            summary["steps"][0]["support_full_text_file_risk"]["next_action"],
            "tighten_claim_or_inspect_full_text",
        )
        self.assertEqual(summary["steps"][0]["support_markdown_summary"]["insufficient_evidence"], 2)
        self.assertEqual(summary["steps"][0]["support_markdown_result_count"], 2)
        self.assertEqual(
            summary["steps"][0]["support_markdown_source_traceability"]["source_paths"],
            ["examples/references.md"],
        )
        self.assertEqual(summary["steps"][0]["support_markdown_source_traceability"]["source_indexes"], [1, 2])
        self.assertEqual(summary["steps"][0]["support_markdown_source_traceability"]["high_risk_source_indexes"], [2])
        self.assertEqual(
            summary["steps"][0]["support_markdown_source_traceability"]["review_required_source_indexes"],
            [1, 2],
        )
        self.assertEqual(summary["steps"][0]["support_markdown_line_range"]["result_line_start"], 5)
        self.assertEqual(summary["steps"][0]["support_markdown_line_range"]["result_line_end"], 5)
        self.assertIn(summary["steps"][0]["support_markdown_line_range"]["risk_line_start"], {5, 6})
        self.assertEqual(summary["steps"][0]["support_markdown_returned_indexes"], [1])
        self.assertEqual(summary["steps"][0]["support_markdown_original_results"], 2)
        self.assertEqual(
            summary["steps"][0]["support_markdown_omitted_review_summary"]["medium_risk_count"],
            1,
        )
        self.assertEqual(
            summary["steps"][0]["support_markdown_omitted_review_summary"]["suggested_fix_summary"][
                "confirmation_required_indexes"
            ],
            [0],
        )
        self.assertEqual(summary["steps"][0]["support_markdown_omitted_source_traceability"]["source_indexes"], [1])
        self.assertEqual(
            summary["steps"][0]["support_markdown_omitted_source_traceability"]["review_required_source_locators"],
            ["examples/references.md#citation-1"],
        )
        self.assertEqual(summary["steps"][0]["support_docx_returned_indexes"], [1])
        self.assertEqual(summary["steps"][0]["support_docx_source_traceability"]["source_formats"], ["docx"])
        self.assertEqual(summary["steps"][0]["support_docx_source_traceability"]["source_indexes"], [1, 2])
        self.assertEqual(summary["steps"][0]["support_docx_source_traceability"]["high_risk_source_indexes"], [2])
        self.assertTrue(summary["steps"][0]["support_docx_source_traceability"]["source_paths"][0].endswith("references.docx"))
        self.assertEqual(summary["steps"][0]["support_docx_omitted_source_traceability"]["source_indexes"], [1])
        self.assertTrue(
            summary["steps"][0]["support_docx_omitted_source_traceability"]["review_required_source_locators"][0].endswith(
                "references.docx#citation-1"
            )
        )
        self.assertTrue(summary["steps"][0]["support_markdown_counterevidence_included"])
        self.assertEqual(summary["steps"][0]["support_markdown_counterevidence_review_count"], 2)
        self.assertEqual(summary["steps"][0]["support_markdown_counterevidence_query_roles"], ["claim_similarity"])
        self.assertEqual(summary["steps"][0]["support_markdown_counterevidence_risk_indexes"], [1, 0])
        self.assertTrue(summary["steps"][0]["support_counterevidence_included"])
        self.assertEqual(summary["steps"][0]["support_counterevidence_review_count"], 3)
        self.assertEqual(
            summary["steps"][0]["support_counterevidence_first_next_action"],
            "review_counterevidence_leads",
        )
        self.assertEqual(summary["steps"][0]["support_counterevidence_query_roles"], ["claim_similarity"])
        self.assertTrue(summary["steps"][0]["support_counterevidence_source_outage_probe"])
        self.assertEqual(summary["steps"][0]["support_set_mode"], "insufficient_evidence")
        self.assertEqual(
            summary["steps"][0]["support_citation_set_risk_reason"],
            "citation_set_evidence_does_not_confirm_claim",
        )
        self.assertEqual(
            summary["steps"][0]["support_citation_set_suggested_fix"]["kind"],
            "inspect_full_text_or_find_stronger_citation",
        )
        self.assertEqual(summary["steps"][0]["support_set_summary"]["insufficient_evidence"], 2)
        self.assertEqual(summary["steps"][0]["support_set_result_count"], 2)
        self.assertTrue(summary["steps"][0]["support_set_counterevidence_included"])
        self.assertEqual(
            summary["steps"][0]["support_set_counterevidence_next_action"],
            "review_counterevidence_leads",
        )
        self.assertEqual(summary["steps"][0]["support_set_counterevidence_candidate_count"], 1)
        self.assertEqual(summary["steps"][0]["support_set_counterevidence_query_roles"], ["claim_similarity"])
        self.assertEqual(summary["steps"][0]["support_set_markdown_mode"], "insufficient_evidence")
        self.assertEqual(summary["steps"][0]["support_set_markdown_summary"]["insufficient_evidence"], 2)
        self.assertEqual(summary["steps"][0]["support_set_markdown_result_count"], 2)
        self.assertEqual(summary["steps"][0]["support_set_markdown_line_starts"], [5, 6])
        self.assertEqual(summary["steps"][0]["support_set_markdown_line_ends"], [5, 6])
        self.assertEqual(summary["steps"][0]["support_set_docx_mode"], "insufficient_evidence")
        self.assertEqual(summary["steps"][0]["support_set_docx_summary"]["insufficient_evidence"], 2)
        self.assertEqual(summary["steps"][0]["support_set_docx_result_count"], 2)
        self.assertEqual(summary["steps"][0]["support_set_docx_line_starts"], [2, 3])
        self.assertEqual(summary["steps"][0]["support_set_docx_line_ends"], [2, 3])
        self.assertIn("extract_references", summary["steps"][0]["commands"])
        self.assertIn("extract_docx_reference_list", summary["steps"][0]["commands"])
        self.assertIn("audit_jsonl_high_risk", summary["steps"][0]["commands"])
        self.assertIn("examples/citations.jsonl", summary["steps"][0]["commands"]["audit_jsonl_high_risk"])
        self.assertIn("audit_docx_high_risk", summary["steps"][0]["commands"])
        self.assertIn("audit_metadata_mismatch", summary["steps"][0]["commands"])
        self.assertIn("support_audit_jsonl_high_risk", summary["steps"][0]["commands"])
        self.assertIn("support_audit_full_text_json", summary["steps"][0]["commands"])
        self.assertIn(
            "examples/claim_citations_full_text.json",
            summary["steps"][0]["commands"]["support_audit_full_text_json"],
        )
        self.assertIn("support_audit_full_text_file_json", summary["steps"][0]["commands"])
        self.assertIn(
            "examples/claim_citations_full_text_file.json",
            summary["steps"][0]["commands"]["support_audit_full_text_file_json"],
        )
        self.assertIn("support_audit_markdown", summary["steps"][0]["commands"])
        self.assertIn("support_audit_markdown_high_risk", summary["steps"][0]["commands"])
        self.assertIn("support_audit_markdown_counterevidence", summary["steps"][0]["commands"])
        self.assertIn("support_audit_docx_high_risk", summary["steps"][0]["commands"])
        self.assertIn("support_audit_counterevidence", summary["steps"][0]["commands"])
        self.assertIn("support_set", summary["steps"][0]["commands"])
        self.assertIn("support_set_counterevidence", summary["steps"][0]["commands"])
        self.assertIn("support_set_markdown", summary["steps"][0]["commands"])
        self.assertIn("support_set_docx", summary["steps"][0]["commands"])

    def test_release_gate_records_support_review_queue_contract(self):
        summary = {"ok": True, "steps": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "result_summary": {
                            "false_support_total_overcall_count": 0,
                            "false_support_risk_slice_count": 0,
                            "false_support_ok_to_accept_supported": True,
                            "false_support_block_acceptance_count": 0,
                            "false_support_block_acceptance_case_ids": [],
                            "false_support_review_before_accepting_case_ids": [],
                            **_clear_support_acceptance_slice_manifest_summary(),
                            **_empty_false_support_review_plan_manifest_summary(),
                            "support_overcall_count": 0,
                            "support_overcall_rate": 0.0,
                            **_perfect_support_metric_manifest_summary(),
                            "abstention_total_count": 0,
                            "abstention_incorrect_count": 0,
                            "abstention_correct_count": 0,
                            "abstention_review_case_ids": [],
                            "false_support_top_risk_slice_id": None,
                            "false_support_top_risk_slice_case_ids": [],
                            **_empty_release_blocker_manifest_summary(),
                            "support_set_policy_case_count": 3,
                            "support_set_policy_case_types": {
                                "contradiction_set": 1,
                                "weak_set_boundary": 2,
                            },
                            "support_set_policy_languages": {"en": 2, "zh": 1},
                            "support_set_policy_splits": {"test": 3},
                            "support_set_policy_accuracy": 1.0,
                            "support_set_policy_case_ids": ["ss02", "ss03", "ss05"],
                            **_support_label_manifest_summary(),
                            **_clear_support_release_manifest_summary(),
                        }
                    }
                ),
                encoding="utf-8",
            )
            completed = mock.Mock(
                stdout=json.dumps(
                    {
                        "case_count": 12,
                        "overall": {
                            "support_overcall_count": 0,
                            "support_overcall_rate": 0.0,
                        },
                        "review_queue": [],
                        "review_queue_summary": {"count": 0, "by_severity": {}},
                        "release_blocker_summary": _empty_release_blocker_summary(),
                        "false_support_analysis": {
                            "total_overcall_count": 0,
                            "acceptance_guard": {
                                "ok_to_accept_supported": True,
                                "block_acceptance_count": 0,
                                "block_acceptance_case_ids": [],
                                "review_before_accepting_case_ids": [],
                                "policy": "supported_overcalls_block_acceptance; weak_overcalls_require_review",
                            },
                            "risk_slices": [],
                            "top_risk_slice": None,
                            "review_plan": _empty_false_support_review_plan(),
                        },
                        "acceptance_guard": {
                            "ok_to_accept_supported": True,
                            "block_acceptance_count": 0,
                            "block_acceptance_case_ids": [],
                            "review_before_accepting_case_ids": [],
                            "policy": "supported_overcalls_block_acceptance; weak_overcalls_require_review",
                        },
                        "acceptance_slices": _clear_support_acceptance_slices(),
                        "abstention_analysis": {
                            "total_abstention_count": 0,
                            "incorrect_abstention_count": 0,
                            "correct_abstention_count": 0,
                            "review_case_ids": [],
                        },
                        "label_maturity": _support_label_gate_payload()["metrics"],
                        "release_summary": _clear_support_release_summary(),
                        "quality_gate": {
                            "ok": True,
                            "review_queue_case_ids": [],
                            "critical_review_case_ids": [],
                            "release_blocker_summary": _empty_release_blocker_summary(),
                            "acceptance_slices": _clear_support_acceptance_slices(),
                            "failures": [],
                        },
                        "label_sidecar_gate": _support_label_gate_payload(),
                        "support_set_policy": {
                            "accuracy": 1.0,
                            "contradiction_recall": 1.0,
                            "false_support_rate": 0.0,
                            "case_count": 3,
                            "case_types": {
                                "contradiction_set": 1,
                                "weak_set_boundary": 2,
                            },
                            "languages": {"en": 2, "zh": 1},
                            "splits": {"test": 3},
                            "case_ids": ["ss02", "ss03", "ss05"],
                        },
                        "experiment_artifact": {
                            "files": {
                                "manifest": str(manifest_path),
                            }
                        },
                    }
                )
            )
            limited_completed = mock.Mock(
                stdout=json.dumps(
                    {
                        "review_queue_limit": 2,
                        "review_queue_summary": {"count": 7},
                        "review_queue": [
                            {"case_id": "s10"},
                            {"case_id": "s16"},
                        ],
                        "review_queue_filtered": {
                            "limited": True,
                            "limit": 2,
                            "returned": 2,
                            "original_count": 7,
                            "omitted": 5,
                            "returned_case_ids": ["s10", "s16"],
                            "omitted_case_ids": ["s27", "s36", "s39", "s09", "s24"],
                            "policy": "review_queue_summary_and_quality_gate_counts_remain_full_queue",
                        },
                    }
                )
            )
            with mock.patch("scripts.release_package_gate._run", side_effect=[completed, limited_completed]) as run:
                _record_support_review_queue_gate(
                    summary,
                    python="python3",
                    project_root=ROOT,
                    dataset="data/eval/support_eval.json",
                    label_sidecar="data/eval/support_eval_label_sidecar.json",
                )

        self.assertEqual(run.call_count, 2)
        called_cmd = run.call_args_list[0].args[0]
        limited_cmd = run.call_args_list[1].args[0]
        output_dir_index = called_cmd.index("--output-dir")
        self.assertEqual(
            called_cmd[:output_dir_index],
            [
                "python3",
                "scripts/eval_support.py",
                "--dataset",
                "data/eval/support_eval.json",
                "--split",
                "test",
                "--backend",
                "fixture",
                "--quality-gate",
                "--label-sidecar",
                "data/eval/support_eval_label_sidecar.json",
                "--review-queue-only",
            ],
        )
        self.assertEqual(called_cmd[output_dir_index + 2 :], ["--run-id", "release-support-review-queue"])
        self.assertEqual(
            limited_cmd,
            [
                "python3",
                "scripts/eval_support.py",
                "--dataset",
                "data/eval/support_eval.json",
                "--split",
                "test",
                "--backend",
                "heuristic",
                "--review-queue-only",
                "--review-queue-limit",
                "2",
            ],
        )
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "support_review_queue")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["review_queue_count"], 0)
        self.assertEqual(summary["steps"][0]["review_queue_summary"], {"count": 0, "by_severity": {}})
        self.assertEqual(summary["steps"][0]["review_queue_case_ids"], [])
        self.assertTrue(summary["steps"][0]["false_support_triage_present"])
        self.assertTrue(summary["steps"][0]["acceptance_guard_present"])
        self.assertTrue(summary["steps"][0]["acceptance_slices_present"])
        self.assertTrue(summary["steps"][0]["acceptance_guard"]["ok_to_accept_supported"])
        self.assertEqual(
            [item["id"] for item in summary["steps"][0]["acceptance_slices"]],
            [
                "contradiction",
                "hard_negative",
                "full_text_boundary",
                "test_split",
                "non_english",
            ],
        )
        self.assertTrue(summary["steps"][0]["abstention_analysis_present"])
        self.assertTrue(summary["steps"][0]["release_blocker_summary_present"])
        self.assertFalse(summary["steps"][0]["release_blocker_summary"]["release_blocked"])
        self.assertTrue(summary["steps"][0]["release_blocker_summary"]["benchmark_claim_safe"])
        self.assertTrue(summary["steps"][0]["label_maturity_present"])
        self.assertEqual(summary["steps"][0]["label_maturity"]["human_reviewed"], 0)
        self.assertEqual(summary["steps"][0]["label_maturity"]["dual_annotated"], 0)
        self.assertEqual(summary["steps"][0]["false_support_analysis"]["risk_slices"], [])
        self.assertEqual(summary["steps"][0]["false_support_analysis"]["review_plan"]["status"], "clear")
        self.assertEqual(
            summary["steps"][0]["false_support_analysis"]["review_plan"]["next_action"],
            "continue",
        )
        self.assertEqual(summary["steps"][0]["abstention_analysis"]["total_abstention_count"], 0)
        self.assertTrue(summary["steps"][0]["manifest_false_support_triage_present"])
        self.assertTrue(summary["steps"][0]["manifest_support_release_summary_present"])
        self.assertEqual(summary["steps"][0]["release_summary"]["status"], "clear")
        self.assertEqual(summary["steps"][0]["release_summary"]["next_action"], "continue")
        self.assertTrue(summary["steps"][0]["release_summary"]["ok_to_accept_supported"])
        self.assertTrue(summary["steps"][0]["support_set_policy_present"])
        self.assertTrue(summary["steps"][0]["support_label_manifest_present"])
        self.assertEqual(summary["steps"][0]["limited_review_queue"]["returned"], 2)
        self.assertEqual(summary["steps"][0]["limited_review_queue"]["original_count"], 7)
        self.assertEqual(summary["steps"][0]["limited_review_queue"]["omitted"], 5)
        self.assertEqual(summary["steps"][0]["limited_review_queue_errors"], [])
        self.assertEqual(summary["steps"][0]["support_set_policy"]["case_ids"], ["ss02", "ss03", "ss05"])
        self.assertEqual(summary["steps"][0]["manifest_errors"], [])
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["false_support_risk_slice_count"], 0)
        self.assertEqual(
            summary["steps"][0]["manifest_result_summary"]["false_support_review_plan_status"],
            "clear",
        )
        self.assertEqual(
            summary["steps"][0]["manifest_result_summary"]["false_support_review_plan_phase_ids"],
            [
                "supported_overcall_blockers",
                "weak_support_overcall_review",
                "highest_risk_slice_review",
            ],
        )
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["false_support_block_acceptance_count"], 0)
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["support_overcall_count"], 0)
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["support_overcall_rate"], 0.0)
        self.assertEqual(
            summary["steps"][0]["manifest_result_summary"]["support_acceptance_blocked_slice_ids"],
            [],
        )
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["macro_f1"], 1.0)
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["weighted_f1"], 1.0)
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["abstention_total_count"], 0)
        self.assertFalse(summary["steps"][0]["manifest_result_summary"]["release_blocked"])
        self.assertTrue(summary["steps"][0]["manifest_result_summary"]["benchmark_claim_safe"])
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["release_next_action"], "continue")
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["support_set_policy_case_count"], 3)
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["support_label_dual_annotated"], 0)
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["support_label_unresolved_disagreements"], 0)
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["support_label_supported_disagreements"], 0)
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["support_release_status"], "clear")
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["support_release_next_action"], "continue")
        self.assertTrue(summary["steps"][0]["manifest_result_summary"]["support_release_quality_gate_ok"])
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["support_release_review_top_case_ids"], [])
        self.assertEqual(summary["steps"][0]["manifest_result_summary"]["support_release_label_high_risk_unreviewed"], 35)
        self.assertIsNone(summary["steps"][0]["manifest_result_summary"]["support_label_raw_dual_agreement_rate"])
        self.assertEqual(
            summary["steps"][0]["manifest_result_summary"]["support_label_supported_disagreement_case_ids"],
            [],
        )
        self.assertEqual(
            summary["steps"][0]["manifest_result_summary"][
                "support_label_high_risk_unreviewed_by_language_case_type"
            ],
            {
                "en": {"contradiction": 9, "contradiction_set": 1, "full_text_required": 6, "hard_negative": 10},
                "zh": {"contradiction": 6, "full_text_required": 1, "hard_negative": 2},
            },
        )

    def test_release_gate_fails_on_support_review_manifest_mismatch(self):
        summary = {"ok": True, "steps": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "result_summary": {
                            "false_support_total_overcall_count": 1,
                            "false_support_risk_slice_count": 0,
                            "false_support_ok_to_accept_supported": True,
                            "false_support_block_acceptance_count": 0,
                            "false_support_block_acceptance_case_ids": [],
                            "false_support_review_before_accepting_case_ids": [],
                            **_empty_false_support_review_plan_manifest_summary(),
                            "support_overcall_count": 0,
                            "support_overcall_rate": 0.0,
                            **_perfect_support_metric_manifest_summary(),
                            "abstention_total_count": 0,
                            "abstention_incorrect_count": 0,
                            "abstention_correct_count": 0,
                            "abstention_review_case_ids": [],
                            "false_support_top_risk_slice_id": None,
                            "false_support_top_risk_slice_case_ids": [],
                            **_empty_release_blocker_manifest_summary(),
                            "support_set_policy_case_count": 3,
                            "support_set_policy_case_types": {
                                "contradiction_set": 1,
                                "weak_set_boundary": 2,
                            },
                            "support_set_policy_languages": {"en": 2, "zh": 1},
                            "support_set_policy_splits": {"test": 3},
                            "support_set_policy_accuracy": 1.0,
                            "support_set_policy_case_ids": ["ss02", "ss03", "ss05"],
                            **_support_label_manifest_summary(),
                        }
                    }
                ),
                encoding="utf-8",
            )
            completed = mock.Mock(
                stdout=json.dumps(
                    {
                        "case_count": 12,
                        "review_queue": [],
                        "review_queue_summary": {"count": 0},
                        "release_blocker_summary": _empty_release_blocker_summary(),
                        "false_support_analysis": {
                            "total_overcall_count": 0,
                            "acceptance_guard": {
                                "ok_to_accept_supported": True,
                                "block_acceptance_count": 0,
                                "block_acceptance_case_ids": [],
                                "review_before_accepting_case_ids": [],
                                "policy": "supported_overcalls_block_acceptance; weak_overcalls_require_review",
                            },
                            "risk_slices": [],
                            "top_risk_slice": None,
                            "review_plan": _empty_false_support_review_plan(),
                        },
                        "acceptance_guard": {
                            "ok_to_accept_supported": True,
                            "block_acceptance_count": 0,
                            "block_acceptance_case_ids": [],
                            "review_before_accepting_case_ids": [],
                            "policy": "supported_overcalls_block_acceptance; weak_overcalls_require_review",
                        },
                        "abstention_analysis": {
                            "total_abstention_count": 0,
                            "incorrect_abstention_count": 0,
                            "correct_abstention_count": 0,
                            "review_case_ids": [],
                        },
                        "label_maturity": _support_label_gate_payload()["metrics"],
                        "quality_gate": {
                            "ok": True,
                            "review_queue_case_ids": [],
                            "critical_review_case_ids": [],
                            "release_blocker_summary": _empty_release_blocker_summary(),
                        },
                        "label_sidecar_gate": _support_label_gate_payload(),
                        "support_set_policy": {
                            "accuracy": 1.0,
                            "case_count": 3,
                            "case_types": {"contradiction_set": 1, "weak_set_boundary": 2},
                            "languages": {"en": 2, "zh": 1},
                            "splits": {"test": 3},
                            "case_ids": ["ss02", "ss03", "ss05"],
                        },
                        "experiment_artifact": {"files": {"manifest": str(manifest_path)}},
                    }
                )
            )
            with mock.patch("scripts.release_package_gate._run", return_value=completed):
                _record_support_review_queue_gate(
                    summary,
                    python="python3",
                    project_root=ROOT,
                    dataset="data/eval/support_eval.json",
                    label_sidecar="data/eval/support_eval_label_sidecar.json",
                )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "support_review_queue")
        self.assertEqual(summary["steps"][0]["status"], "failed")
        self.assertIn("manifest_total_overcall_count_mismatch", summary["steps"][0]["manifest_errors"])

    def test_release_gate_fails_on_missing_support_set_policy_contract(self):
        summary = {"ok": True, "steps": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "result_summary": {
                            "false_support_total_overcall_count": 0,
                            "false_support_risk_slice_count": 0,
                            "false_support_ok_to_accept_supported": True,
                            "false_support_block_acceptance_count": 0,
                            "false_support_block_acceptance_case_ids": [],
                            "false_support_review_before_accepting_case_ids": [],
                            **_empty_false_support_review_plan_manifest_summary(),
                            "support_overcall_count": 0,
                            "support_overcall_rate": 0.0,
                            **_perfect_support_metric_manifest_summary(),
                            "abstention_total_count": 0,
                            "abstention_incorrect_count": 0,
                            "abstention_correct_count": 0,
                            "abstention_review_case_ids": [],
                            "false_support_top_risk_slice_id": None,
                            "false_support_top_risk_slice_case_ids": [],
                            **_empty_release_blocker_manifest_summary(),
                            "support_set_policy_case_count": 2,
                            "support_set_policy_case_types": {"weak_set_boundary": 1},
                            "support_set_policy_languages": {"en": 2},
                            "support_set_policy_splits": {"test": 2},
                            "support_set_policy_accuracy": 1.0,
                            "support_set_policy_case_ids": ["ss02", "ss03"],
                        }
                    }
                ),
                encoding="utf-8",
            )
            completed = mock.Mock(
                stdout=json.dumps(
                    {
                        "case_count": 12,
                        "review_queue": [],
                        "review_queue_summary": {"count": 0},
                        "release_blocker_summary": _empty_release_blocker_summary(),
                        "false_support_analysis": {
                            "total_overcall_count": 0,
                            "acceptance_guard": {
                                "ok_to_accept_supported": True,
                                "block_acceptance_count": 0,
                                "block_acceptance_case_ids": [],
                                "review_before_accepting_case_ids": [],
                                "policy": "supported_overcalls_block_acceptance; weak_overcalls_require_review",
                            },
                            "risk_slices": [],
                            "top_risk_slice": None,
                            "review_plan": _empty_false_support_review_plan(),
                        },
                        "acceptance_guard": {
                            "ok_to_accept_supported": True,
                            "block_acceptance_count": 0,
                            "block_acceptance_case_ids": [],
                            "review_before_accepting_case_ids": [],
                            "policy": "supported_overcalls_block_acceptance; weak_overcalls_require_review",
                        },
                        "abstention_analysis": {
                            "total_abstention_count": 0,
                            "incorrect_abstention_count": 0,
                            "correct_abstention_count": 0,
                            "review_case_ids": [],
                        },
                        "label_maturity": _support_label_gate_payload()["metrics"],
                        "quality_gate": {
                            "ok": True,
                            "review_queue_case_ids": [],
                            "critical_review_case_ids": [],
                            "release_blocker_summary": _empty_release_blocker_summary(),
                        },
                        "label_sidecar_gate": _support_label_gate_payload(),
                        "support_set_policy": {
                            "accuracy": 1.0,
                            "case_count": 2,
                            "case_types": {"weak_set_boundary": 1},
                            "languages": {"en": 2},
                            "splits": {"test": 2},
                            "case_ids": ["ss02", "ss03"],
                        },
                        "experiment_artifact": {"files": {"manifest": str(manifest_path)}},
                    }
                )
            )
            with mock.patch("scripts.release_package_gate._run", return_value=completed):
                _record_support_review_queue_gate(
                    summary,
                    python="python3",
                    project_root=ROOT,
                    dataset="data/eval/support_eval.json",
                    label_sidecar="data/eval/support_eval_label_sidecar.json",
                )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "support_review_queue")
        self.assertEqual(summary["steps"][0]["status"], "failed")
        self.assertFalse(summary["steps"][0]["support_set_policy_present"])
        self.assertIn("support_set_policy_missing_contradiction_set", summary["steps"][0]["manifest_errors"])
        self.assertIn("support_set_policy_missing_zh_case", summary["steps"][0]["manifest_errors"])
        self.assertIn("support_set_policy_missing_case_ss05", summary["steps"][0]["manifest_errors"])

    def test_release_gate_records_support_baseline_comparison_contract(self):
        summary = {"ok": True, "steps": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "result_summary": {
                            "false_support_overcall_backends": ["heuristic"],
                            "false_support_top_overcall_backend": "heuristic",
                            "false_support_top_risk_slice_id": "contradicted_overcalled",
                            "false_support_top_risk_slice_case_ids": ["s10"],
                            **_heuristic_false_support_review_plan_manifest_summary(),
                            "support_baseline_metric_fields": _baseline_metric_fields(),
                            "support_baseline_metrics": {
                                "fixture": _baseline_row_metrics(),
                                "heuristic": _baseline_row_metrics(macro_f1=0.52, weighted_f1=0.69),
                            },
                            "support_set_policy_case_count": 3,
                            "support_set_policy_case_types": {
                                "contradiction_set": 1,
                                "weak_set_boundary": 2,
                            },
                            "support_set_policy_languages": {"en": 2, "zh": 1},
                            "support_set_policy_splits": {"test": 3},
                            "support_set_policy_accuracy": 1.0,
                            "support_set_policy_case_ids": ["ss02", "ss03", "ss05"],
                            **_support_label_manifest_summary(),
                        }
                    }
                ),
                encoding="utf-8",
            )
            completed = mock.Mock(
                stdout=json.dumps(
                    {
                        "case_count": 13,
                        "support_set_policy": {
                            "backend": "support_set_policy_fixture",
                            "dataset": {
                                "n": 3,
                                "case_types": {
                                    "contradiction_set": 1,
                                    "weak_set_boundary": 2,
                                },
                                "languages": {"en": 2, "zh": 1},
                                "splits": {"test": 3},
                            },
                            "overall": {
                                "accuracy": 1.0,
                                "contradiction_recall": 1.0,
                                "false_support_rate": 0.0,
                            },
                            "cases": [
                                {"case_id": "ss02"},
                                {"case_id": "ss03"},
                                {"case_id": "ss05"},
                            ],
                        },
                        "quality_gates_ok": False,
                        "label_sidecar_gate": _support_label_gate_payload(),
                        "experiment_artifact": {
                            "files": {
                                "manifest": str(manifest_path),
                            }
                        },
                        "comparison": [
                            {
                                "backend": "fixture",
                                "quality_gate_ok": True,
                                **_baseline_row_metrics(),
                                "total_overcall_count": 0,
                                "support_overcall_count": 0,
                                "support_overcall_rate": 0.0,
                                "ok_to_accept_supported": True,
                                "block_acceptance_case_ids": [],
                                "review_before_accepting_case_ids": [],
                                "false_support_risk_slices": [],
                                "top_false_support_risk_slice": None,
                                **_empty_false_support_review_plan_row_fields(),
                                "heuristic_limited": False,
                            },
                            {
                                "backend": "heuristic",
                                "quality_gate_ok": False,
                                **_baseline_row_metrics(macro_f1=0.52, weighted_f1=0.69),
                                "total_overcall_count": 2,
                                "support_overcall_count": 2,
                                "support_overcall_rate": 0.5,
                                "ok_to_accept_supported": False,
                                "block_acceptance_case_ids": ["s10"],
                                "review_before_accepting_case_ids": ["s11"],
                                "false_support_risk_slices": [
                                    {
                                        "id": "contradicted_overcalled",
                                        "case_ids": ["s10"],
                                    }
                                ],
                                "top_false_support_risk_slice": {
                                    "id": "contradicted_overcalled",
                                    "case_ids": ["s10"],
                                },
                                **_heuristic_false_support_review_plan_row_fields(),
                                "heuristic_limited": True,
                            },
                        ],
                    }
                )
            )
            with mock.patch("scripts.release_package_gate._run", return_value=completed) as run:
                _record_support_baseline_comparison_gate(
                    summary,
                    python="python3",
                    project_root=ROOT,
                    dataset="data/eval/support_eval.json",
                    label_sidecar="data/eval/support_eval_label_sidecar.json",
                    min_sidecar_coverage=1.0,
                    min_human_reviewed=0,
                    min_high_risk_reviewed=0,
                    min_high_risk_reviewed_by_language=["zh=0"],
                    min_dual_annotated=0,
                    max_unresolved_disagreements=0,
                    min_raw_dual_agreement_rate=None,
                    max_supported_disagreements=0,
                )

        run.assert_called_once()
        called_cmd = run.call_args.args[0]
        output_dir_index = called_cmd.index("--output-dir")
        self.assertEqual(
            called_cmd[:output_dir_index],
            [
                "python3",
                "scripts/compare_support_baselines.py",
                "--dataset",
                "data/eval/support_eval.json",
                "--split",
                "test",
                "--label-sidecar",
                "data/eval/support_eval_label_sidecar.json",
                "--min-sidecar-coverage",
                "1.0",
                "--min-human-reviewed",
                "0",
                "--min-high-risk-reviewed",
                "0",
                "--min-dual-annotated",
                "0",
                "--max-unresolved-disagreements",
                "0",
                "--min-high-risk-reviewed-by-language",
                "zh=0",
                "--max-supported-disagreements",
                "0",
            ],
        )
        self.assertEqual(called_cmd[output_dir_index + 2 :], ["--run-id", "release-support-baseline-comparison"])
        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "support_baseline_comparison")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["quality_gates_ok"], False)
        self.assertEqual(summary["steps"][0]["backends"], ["fixture", "heuristic"])
        self.assertEqual(summary["steps"][0]["fixture_quality_gate_ok"], True)
        self.assertEqual(summary["steps"][0]["heuristic_quality_gate_ok"], False)
        self.assertEqual(summary["steps"][0]["heuristic_limited"], True)
        self.assertEqual(summary["steps"][0]["heuristic_total_overcall_count"], 2)
        self.assertEqual(
            summary["steps"][0]["heuristic_top_false_support_risk_slice"]["id"],
            "contradicted_overcalled",
        )
        self.assertEqual(summary["steps"][0]["rows_missing_risk_fields"], [])
        self.assertEqual(summary["steps"][0]["rows_missing_active_risk_slices"], [])
        self.assertEqual(summary["steps"][0]["rows_missing_metric_fields"], [])
        self.assertTrue(summary["steps"][0]["manifest_false_support_triage_present"])
        self.assertTrue(summary["steps"][0]["support_set_policy_present"])
        self.assertTrue(summary["steps"][0]["support_label_manifest_present"])
        self.assertEqual(summary["steps"][0]["support_set_policy"]["case_ids"], ["ss02", "ss03", "ss05"])
        self.assertEqual(summary["steps"][0]["manifest_errors"], [])
        self.assertEqual(
            summary["steps"][0]["manifest_result_summary"]["false_support_overcall_backends"],
            ["heuristic"],
        )
        self.assertEqual(
            summary["steps"][0]["manifest_result_summary"]["support_label_label_source_counts"],
            {"maintainer_synthetic": 54},
        )
        self.assertEqual(
            summary["steps"][0]["manifest_result_summary"][
                "support_label_high_risk_case_count_by_language_case_type"
            ]["zh"],
            {"contradiction": 6, "full_text_required": 1, "hard_negative": 2},
        )
        self.assertEqual(
            summary["steps"][0]["manifest_result_summary"]["support_baseline_metrics"]["heuristic"]["macro_f1"],
            0.52,
        )
        self.assertEqual(
            summary["steps"][0]["manifest_result_summary"]["false_support_top_overcall_review_plan_status"],
            "blocked",
        )
        self.assertEqual(
            summary["steps"][0]["manifest_result_summary"]["false_support_top_overcall_review_plan_next_action"],
            "review_supported_overcalls_before_release",
        )
        self.assertEqual(
            summary["steps"][0]["manifest_result_summary"]["false_support_top_overcall_review_plan_phase_ids"],
            [
                "supported_overcall_blockers",
                "weak_support_overcall_review",
                "highest_risk_slice_review",
            ],
        )

    def test_release_gate_records_support_calibration_artifact_contract(self):
        summary = {"ok": True, "steps": []}

        _record_support_calibration_artifact_gate(summary, python=sys.executable, project_root=ROOT)

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "support_calibration_artifact")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(
            summary["steps"][0]["docs_checked"],
            ["docs/benchmark_todo.md", "docs/release_checklist.md"],
        )
        self.assertEqual(summary["steps"][0]["input_mode"], "scored_dataset")
        self.assertEqual(summary["steps"][0]["dataset_size"], 2)
        self.assertEqual(summary["steps"][0]["support_eval_split"], "dev")
        self.assertGreater(summary["steps"][0]["support_eval_example_count"], 0)
        self.assertGreater(summary["steps"][0]["support_eval_positive_count"], 0)
        self.assertGreater(summary["steps"][0]["support_eval_negative_count"], 0)
        self.assertEqual(summary["steps"][0]["top_result_count"], 2)
        self.assertIn("--scored-dataset", summary["steps"][0]["command"])
        manifest_summary = summary["steps"][0]["manifest_summary"]
        self.assertEqual(manifest_summary["support_calibration_input_mode"], "scored_dataset")
        self.assertEqual(manifest_summary["support_calibration_profile"], "quick")
        self.assertEqual(manifest_summary["support_calibration_top_result_count"], 2)
        self.assertIn("support_calibration_top_false_support_rate", manifest_summary)
        self.assertIn("support_calibration_top_false_positive_case_ids", manifest_summary)
        self.assertIn("support_calibration_top_false_negative_case_ids", manifest_summary)
        self.assertIn("support_calibration_top_false_positive_decision_paths", manifest_summary)
        self.assertIn("support_calibration_top_false_positive_score_summary", manifest_summary)
        self.assertIn("deterministic scored fixtures", summary["steps"][0]["policy"])

    def test_release_gate_fails_on_support_baseline_manifest_mismatch(self):
        summary = {"ok": True, "steps": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "result_summary": {
                            "false_support_overcall_backends": [],
                            "false_support_top_overcall_backend": "heuristic",
                            "false_support_top_risk_slice_id": "contradicted_overcalled",
                            "false_support_top_risk_slice_case_ids": ["s10"],
                            **_heuristic_false_support_review_plan_manifest_summary(),
                            "support_set_policy_case_count": 3,
                            "support_set_policy_case_types": {
                                "contradiction_set": 1,
                                "weak_set_boundary": 2,
                            },
                            "support_set_policy_languages": {"en": 2, "zh": 1},
                            "support_set_policy_splits": {"test": 3},
                            "support_set_policy_accuracy": 1.0,
                            "support_set_policy_case_ids": ["ss02", "ss03", "ss05"],
                            **_support_label_manifest_summary(),
                        }
                    }
                ),
                encoding="utf-8",
            )
            completed = mock.Mock(
                stdout=json.dumps(
                    {
                        "case_count": 13,
                        "support_set_policy": {
                            "case_count": 3,
                            "case_types": {
                                "contradiction_set": 1,
                                "weak_set_boundary": 2,
                            },
                            "languages": {"en": 2, "zh": 1},
                            "splits": {"test": 3},
                            "case_ids": ["ss02", "ss03", "ss05"],
                        },
                        "label_sidecar_gate": _support_label_gate_payload(),
                        "comparison": [
                            {
                                "backend": "fixture",
                                "quality_gate_ok": True,
                                "total_overcall_count": 0,
                                "false_support_risk_slices": [],
                                "top_false_support_risk_slice": None,
                            },
                            {
                                "backend": "heuristic",
                                "quality_gate_ok": False,
                                "total_overcall_count": 1,
                                "false_support_risk_slices": [
                                    {"id": "contradicted_overcalled", "case_ids": ["s10"]}
                                ],
                                "top_false_support_risk_slice": {
                                    "id": "contradicted_overcalled",
                                    "case_ids": ["s10"],
                                },
                                **_heuristic_false_support_review_plan_row_fields(),
                            },
                        ],
                        "experiment_artifact": {"files": {"manifest": str(manifest_path)}},
                    }
                )
            )
            with mock.patch("scripts.release_package_gate._run", return_value=completed):
                _record_support_baseline_comparison_gate(
                    summary,
                    python="python3",
                    project_root=ROOT,
                    dataset="data/eval/support_eval.json",
                    label_sidecar="data/eval/support_eval_label_sidecar.json",
                    min_sidecar_coverage=1.0,
                    min_human_reviewed=0,
                    min_high_risk_reviewed=0,
                    min_high_risk_reviewed_by_language=[],
                    min_dual_annotated=0,
                    max_unresolved_disagreements=0,
                    min_raw_dual_agreement_rate=None,
                    max_supported_disagreements=None,
                )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "support_baseline_comparison")
        self.assertEqual(summary["steps"][0]["status"], "failed")
        self.assertIn("manifest_overcall_backends_mismatch", summary["steps"][0]["manifest_errors"])

    def test_release_gate_fails_on_support_label_manifest_mismatch(self):
        summary = {"ok": True, "steps": []}
        support_label_summary = _support_label_manifest_summary()
        support_label_summary["support_label_human_reviewed"] = 1
        with tempfile.TemporaryDirectory() as tmpdir:
            manifest_path = Path(tmpdir) / "manifest.json"
            manifest_path.write_text(
                json.dumps(
                    {
                        "result_summary": {
                            "false_support_overcall_backends": ["heuristic"],
                            "false_support_top_overcall_backend": "heuristic",
                            "false_support_top_risk_slice_id": "contradicted_overcalled",
                            "false_support_top_risk_slice_case_ids": ["s10"],
                            **_heuristic_false_support_review_plan_manifest_summary(),
                            "support_set_policy_case_count": 3,
                            "support_set_policy_case_types": {
                                "contradiction_set": 1,
                                "weak_set_boundary": 2,
                            },
                            "support_set_policy_languages": {"en": 2, "zh": 1},
                            "support_set_policy_splits": {"test": 3},
                            "support_set_policy_accuracy": 1.0,
                            "support_set_policy_case_ids": ["ss02", "ss03", "ss05"],
                            **support_label_summary,
                        }
                    }
                ),
                encoding="utf-8",
            )
            completed = mock.Mock(
                stdout=json.dumps(
                    {
                        "case_count": 13,
                        "support_set_policy": {
                            "case_count": 3,
                            "case_types": {
                                "contradiction_set": 1,
                                "weak_set_boundary": 2,
                            },
                            "languages": {"en": 2, "zh": 1},
                            "splits": {"test": 3},
                            "case_ids": ["ss02", "ss03", "ss05"],
                        },
                        "label_sidecar_gate": _support_label_gate_payload(),
                        "comparison": [
                            {
                                "backend": "fixture",
                                "quality_gate_ok": True,
                                "total_overcall_count": 0,
                                "false_support_risk_slices": [],
                                "top_false_support_risk_slice": None,
                            },
                            {
                                "backend": "heuristic",
                                "quality_gate_ok": False,
                                "total_overcall_count": 1,
                                "false_support_risk_slices": [
                                    {"id": "contradicted_overcalled", "case_ids": ["s10"]}
                                ],
                                "top_false_support_risk_slice": {
                                    "id": "contradicted_overcalled",
                                    "case_ids": ["s10"],
                                },
                                **_heuristic_false_support_review_plan_row_fields(),
                            },
                        ],
                        "experiment_artifact": {"files": {"manifest": str(manifest_path)}},
                    }
                )
            )
            with mock.patch("scripts.release_package_gate._run", return_value=completed):
                _record_support_baseline_comparison_gate(
                    summary,
                    python="python3",
                    project_root=ROOT,
                    dataset="data/eval/support_eval.json",
                    label_sidecar="data/eval/support_eval_label_sidecar.json",
                    min_sidecar_coverage=1.0,
                    min_human_reviewed=0,
                    min_high_risk_reviewed=0,
                    min_high_risk_reviewed_by_language=[],
                    min_dual_annotated=0,
                    max_unresolved_disagreements=0,
                    min_raw_dual_agreement_rate=None,
                    max_supported_disagreements=None,
                )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["steps"][0]["name"], "support_baseline_comparison")
        self.assertEqual(summary["steps"][0]["status"], "failed")
        self.assertIn(
            "manifest_support_label_human_reviewed_mismatch",
            summary["steps"][0]["manifest_errors"],
        )

    def test_release_gate_records_support_review_queue_annotation_packet_contract(self):
        summary = {"ok": True, "steps": []}
        completed = mock.Mock(stdout="")
        probe_case_id, probe_label = _annotation_conflict_probe_case(ROOT / "data" / "eval" / "support_eval.json")
        merge_stdout = json.dumps(
            {
                "merge_report": {
                    "ok": False,
                    "conflicts": [
                        {
                            "code": "label_mismatch",
                            "annotation_examples": [
                                {
                                    "packet_id": "support-packet-release-gate-conflict",
                                    "packet_digest": "sha256:" + "e" * 64,
                                    "packet_case_index": 1,
                                    "annotator_id": "release-gate-reviewer",
                                    "label": probe_label,
                                    "rationale": "probe",
                                    "confidence": "low",
                                    "evidence_scope_assessed": "abstract",
                                    "full_text_needed": "unclear",
                                    "review_phase": "first_review_high_risk",
                                    "packet_purpose": "Release-gate conflict provenance probe.",
                                }
                            ],
                        }
                    ],
                    "adjudication_queue": [
                        {
                            "conflict_code": "label_mismatch",
                            "adjudication_template": {
                                "case_id": probe_case_id,
                                "annotator_labels": [probe_label],
                                "adjudicated_label": "",
                                "adjudicator": "",
                                "rationale": "",
                                "source_locator": "",
                                "source_packet_ids": ["support-packet-release-gate-conflict"],
                                "source_packet_metadata": [
                                    {
                                        "packet_id": "support-packet-release-gate-conflict",
                                        "packet_digest": "sha256:" + "e" * 64,
                                        "review_phase": "first_review_high_risk",
                                        "packet_purpose": "Release-gate conflict provenance probe.",
                                    }
                                ],
                            },
                        }
                    ],
                }
            }
        )
        merge_completed = mock.Mock(returncode=1, stdout=merge_stdout, stderr="")
        review_protocol = {
            "schema_version": 1,
            "packet_role": "first_review",
            "independent_labeling_required": True,
            "reviewer_must_not_see_hidden_labels": True,
            "packet_target_annotator_count": 1,
            "benchmark_target_annotator_count": 2,
            "cases_already_single_annotated": 0,
            "second_review_required_after_first_review": True,
            "adjudication_required_on_disagreement": True,
            "merge_policy": (
                "single_annotator_until_second_review; "
                "dual_annotator_agreed_or_adjudicated_before_benchmark_claims"
            ),
        }

        def fake_run(cmd, *, cwd):
            packet_path = Path(cmd[cmd.index("--output") + 1])
            instructions_path = Path(cmd[cmd.index("--instructions-output") + 1])
            if "--case-type" in cmd and "full_text_required" in cmd:
                packet_id = "support-packet-full-text"
                packet_digest = "sha256:" + "f" * 64
                packet_path.write_text(
                    json.dumps(
                        {
                            "ok": True,
                            "packet_type": "support_label_annotation_packet",
                            "packet_id": packet_id,
                            "packet_digest": packet_digest,
                            "n": 7,
                            "hidden_fields": [
                                "gold",
                                "predicted",
                                "adjudicated_label",
                                "annotator_labels",
                                "label_notes",
                            ],
                            "review_protocol": review_protocol,
                            "packet_summary": {
                                "case_ids": ["s17", "s30", "s43", "s13", "s38", "s20", "s33"]
                            },
                            "cases": [
                                {
                                    "case_id": case_id,
                                    "packet_digest": packet_digest,
                                    "case_type": "full_text_required",
                                    "review_protocol": review_protocol,
                                    "annotation": {"evidence_scope_assessed": "", "full_text_needed": ""},
                                }
                                for case_id in ["s17", "s30", "s43", "s13", "s38", "s20", "s33"]
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                instructions_path.write_text(
                    "Claims needing unavailable full text are labeled `insufficient_evidence`, not guessed.\n"
                    "Review protocol: label independently before discussion.\n"
                    "`review_protocol` is machine-readable reviewer assignment protocol.\n"
                    "annotation.evidence_scope_assessed\nannotation.full_text_needed\npacket_digest\n",
                    encoding="utf-8",
                )
            elif "--case-type" in cmd and "weak_set_boundary" in cmd:
                packet_id = "support-packet-policy"
                packet_digest = "sha256:" + "p" * 64
                packet_path.write_text(
                    json.dumps(
                        {
                            "ok": True,
                            "packet_type": "support_label_annotation_packet",
                            "packet_id": packet_id,
                            "packet_digest": packet_digest,
                            "n": 2,
                            "hidden_fields": [
                                "gold",
                                "predicted",
                                "adjudicated_label",
                                "annotator_labels",
                                "label_notes",
                            ],
                            "review_protocol": review_protocol,
                            "packet_summary": {"case_ids": ["ss02", "ss05"]},
                            "cases": [
                                {
                                    "case_id": case_id,
                                    "packet_digest": packet_digest,
                                    "case_type": "weak_set_boundary",
                                    "review_protocol": review_protocol,
                                    "annotation": {"evidence_scope_assessed": "", "full_text_needed": ""},
                                }
                                for case_id in ["ss02", "ss05"]
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                instructions_path.write_text(
                    "Do not edit `case_id`.\nAlso do not edit `packet_id`.\n"
                    "Review protocol: independent annotation comes before adjudication.\n"
                    "`review_protocol` is machine-readable reviewer assignment protocol.\n"
                    "annotation.evidence_scope_assessed\nannotation.full_text_needed\npacket_digest\n",
                    encoding="utf-8",
                )
            else:
                packet_id = "support-packet-test"
                packet_digest = "sha256:" + "q" * 64
                packet_path.write_text(
                    json.dumps(
                        {
                            "ok": True,
                            "packet_type": "support_label_annotation_packet",
                            "packet_id": packet_id,
                            "packet_digest": packet_digest,
                            "n": 2,
                            "hidden_fields": [
                                "gold",
                                "predicted",
                                "adjudicated_label",
                                "annotator_labels",
                                "label_notes",
                            ],
                            "filters": {"from_review_queue": True, "review_queue_case_ids": ["s10", "s16"]},
                            "review_protocol": review_protocol,
                            "packet_summary": {"case_ids": ["s10", "s16"]},
                            "cases": [
                                {
                                    "case_id": "s10",
                                    "packet_digest": packet_digest,
                                    "review_queue_rank": 1,
                                    "review_protocol": review_protocol,
                                    "annotation": {"evidence_scope_assessed": "", "full_text_needed": ""},
                                },
                                {
                                    "case_id": "s16",
                                    "packet_digest": packet_digest,
                                    "review_queue_rank": 2,
                                    "review_protocol": review_protocol,
                                    "annotation": {"evidence_scope_assessed": "", "full_text_needed": ""},
                                },
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                instructions_path.write_text(
                    "Use `review_queue_rank` only as assignment priority.\n"
                    "Review protocol: independent annotation comes before adjudication.\n"
                    "`review_protocol` is machine-readable reviewer assignment protocol.\n"
                    "annotation.evidence_scope_assessed\nannotation.full_text_needed\npacket_digest\n",
                    encoding="utf-8",
                )
            return completed

        with mock.patch("scripts.release_package_gate._run", side_effect=fake_run) as run, mock.patch(
            "scripts.release_package_gate.subprocess.run",
            return_value=merge_completed,
        ) as subprocess_run:
            _record_support_review_queue_annotation_packet_gate(
                summary,
                python="python3",
                project_root=ROOT,
                dataset="data/eval/support_eval.json",
                label_sidecar="data/eval/support_eval_label_sidecar.json",
            )

        self.assertEqual(run.call_count, 3)
        subprocess_run.assert_called_once()
        command = run.call_args_list[0].args[0]
        full_text_command = run.call_args_list[1].args[0]
        policy_command = run.call_args_list[2].args[0]
        merge_command = subprocess_run.call_args.args[0]
        self.assertIn("scripts/prepare_support_label_sidecar.py", command)
        self.assertIn("--from-review-queue", command)
        self.assertIn("--review-backend", command)
        self.assertIn("heuristic", command)
        self.assertIn("--case-type", full_text_command)
        self.assertIn("full_text_required", full_text_command)
        self.assertIn("--unreviewed-only", full_text_command)
        self.assertIn("--case-type", policy_command)
        self.assertIn("weak_set_boundary", policy_command)
        self.assertIn("--unreviewed-only", policy_command)
        self.assertIn("--merge-annotation-packet", merge_command)
        self.assertEqual(summary["steps"][0]["name"], "support_review_queue_annotation_packet")
        self.assertEqual(summary["steps"][0]["status"], "passed")
        self.assertEqual(summary["steps"][0]["packet_case_ids"], ["s10", "s16"])
        self.assertEqual(summary["steps"][0]["review_queue_case_ids"], ["s10", "s16"])
        self.assertEqual(summary["steps"][0]["review_queue_ranks"], [1, 2])
        self.assertIn("gold", summary["steps"][0]["hidden_fields"])
        self.assertIn("adjudicated_label", summary["steps"][0]["hidden_fields"])
        self.assertEqual(summary["steps"][0]["leaked_hidden_fields"], [])
        self.assertTrue(summary["steps"][0]["scope_annotation_fields_present"])
        self.assertTrue(summary["steps"][0]["packet_digest_present"])
        self.assertTrue(summary["steps"][0]["packet_digest"].startswith("sha256:"))
        self.assertTrue(summary["steps"][0]["review_protocol_present"])
        self.assertTrue(summary["steps"][0]["review_protocol_contract"]["ok"])
        self.assertEqual(summary["steps"][0]["review_protocol"]["packet_role"], "first_review")
        self.assertTrue(summary["steps"][0]["instructions_review_protocol_present"])
        self.assertEqual(
            summary["steps"][0]["full_text_boundary_packet_case_ids"],
            ["s17", "s30", "s43", "s13", "s38", "s20", "s33"],
        )
        self.assertEqual(summary["steps"][0]["full_text_boundary_case_types"], ["full_text_required"] * 7)
        self.assertIn("gold", summary["steps"][0]["full_text_boundary_hidden_fields"])
        self.assertEqual(summary["steps"][0]["full_text_boundary_leaked_hidden_fields"], [])
        self.assertTrue(summary["steps"][0]["full_text_boundary_scope_annotation_fields_present"])
        self.assertTrue(summary["steps"][0]["full_text_boundary_packet_digest_present"])
        self.assertTrue(summary["steps"][0]["full_text_boundary_review_protocol_present"])
        self.assertTrue(summary["steps"][0]["full_text_boundary_review_protocol_contract"]["ok"])
        self.assertEqual(summary["steps"][0]["full_text_boundary_review_protocol"]["packet_role"], "first_review")
        self.assertTrue(summary["steps"][0]["full_text_boundary_instructions_review_protocol_present"])
        self.assertEqual(summary["steps"][0]["policy_boundary_packet_case_ids"], ["ss02", "ss05"])
        self.assertEqual(
            summary["steps"][0]["policy_boundary_case_types"],
            ["weak_set_boundary", "weak_set_boundary"],
        )
        self.assertIn("gold", summary["steps"][0]["policy_boundary_hidden_fields"])
        self.assertEqual(summary["steps"][0]["policy_boundary_leaked_hidden_fields"], [])
        self.assertTrue(summary["steps"][0]["policy_boundary_scope_annotation_fields_present"])
        self.assertTrue(summary["steps"][0]["policy_boundary_packet_digest_present"])
        self.assertTrue(summary["steps"][0]["policy_boundary_review_protocol_present"])
        self.assertTrue(summary["steps"][0]["policy_boundary_review_protocol_contract"]["ok"])
        self.assertEqual(summary["steps"][0]["policy_boundary_review_protocol"]["packet_role"], "first_review")
        self.assertTrue(summary["steps"][0]["policy_boundary_instructions_review_protocol_present"])
        self.assertEqual(summary["steps"][0]["merge_conflict_probe"]["case_id"], probe_case_id)
        self.assertEqual(summary["steps"][0]["merge_conflict_probe"]["probe_label"], probe_label)
        self.assertEqual(summary["steps"][0]["merge_conflict_probe"]["conflict_code"], "label_mismatch")
        self.assertEqual(summary["steps"][0]["merge_conflict_probe"]["adjudication_queue_count"], 1)
        self.assertIn("adjudicated_label", summary["steps"][0]["merge_conflict_probe"]["adjudication_template_fields"])
        self.assertIn("packet_id", summary["steps"][0]["merge_conflict_probe"]["annotation_example_fields"])
        self.assertIn("packet_digest", summary["steps"][0]["merge_conflict_probe"]["annotation_example_fields"])
        self.assertIn("packet_case_index", summary["steps"][0]["merge_conflict_probe"]["annotation_example_fields"])
        self.assertIn("source_packet_ids", summary["steps"][0]["merge_conflict_probe"]["adjudication_template_fields"])
        self.assertIn("source_packet_metadata", summary["steps"][0]["merge_conflict_probe"]["adjudication_template_fields"])
        self.assertIn("review_phase", summary["steps"][0]["merge_conflict_probe"]["annotation_example_fields"])
        self.assertIn("packet_purpose", summary["steps"][0]["merge_conflict_probe"]["annotation_example_fields"])
        self.assertIn("rationale", summary["steps"][0]["merge_conflict_probe"]["annotation_example_fields"])
        self.assertIn(
            "evidence_scope_assessed",
            summary["steps"][0]["merge_conflict_probe"]["annotation_example_fields"],
        )
        self.assertIn("full_text_needed", summary["steps"][0]["merge_conflict_probe"]["annotation_example_fields"])

    def test_release_gate_annotation_conflict_probe_uses_dataset_case(self):
        case_id, probe_label = _annotation_conflict_probe_case(ROOT / "data" / "eval" / "support_eval.json")
        data = json.loads((ROOT / "data" / "eval" / "support_eval.json").read_text(encoding="utf-8"))
        gold_by_id = {case["id"]: case["gold"] for case in data["cases"]}

        self.assertTrue(case_id)
        self.assertIn(case_id, gold_by_id)
        self.assertIn(probe_label, ALLOWED_SUPPORT_LABELS)
        self.assertNotEqual(probe_label, gold_by_id[case_id])

    def test_mcp_smoke_checks_structured_errors(self):
        smoke = (ROOT / "scripts" / "smoke_mcp.py").read_text(encoding="utf-8")
        setup_doc = (ROOT / "docs" / "mcp_setup.md").read_text(encoding="utf-8")
        release_gate = (ROOT / "scripts" / "release_package_gate.py").read_text(encoding="utf-8")

        self.assertIn("_require_error_payload", smoke)
        self.assertIn("_require_shape_error_payload", smoke)
        self.assertIn("_require_status_payload", smoke)
        self.assertIn("_require_stable_next_action", smoke)
        self.assertIn("_require_support_next_action", smoke)
        self.assertIn("_require_support_payload", smoke)
        self.assertIn("_require_full_text_support_payload", smoke)
        self.assertIn("_require_full_text_file_support_payload", smoke)
        self.assertIn("_require_support_set_full_text_file_payload", smoke)
        self.assertIn("_require_support_audit_nested_full_text_file_payload", smoke)
        self.assertIn("_require_file_error_payload", smoke)
        self.assertIn("expected_errno", smoke)
        self.assertIn("errno.ENOENT", smoke)
        self.assertIn("_require_support_audit_full_text_payload", smoke)
        self.assertIn("offline full-text-file support", smoke)
        self.assertIn("offline support-set full-text-file support", smoke)
        self.assertIn("offline support-audit nested full-text-file support", smoke)
        self.assertIn("user_full_text_file_1", smoke)
        self.assertIn("offline full-text support-audit", smoke)
        self.assertIn("user_full_text_excerpt_1", smoke)
        self.assertIn("offline full-text support", smoke)
        self.assertIn("_require_support_audit_set_payload", smoke)
        self.assertIn("_require_support_set_counterevidence_payload", smoke)
        self.assertIn("_require_support_mode_details", smoke)
        self.assertIn("support-mode aggregation details", smoke)
        self.assertIn("no_unstated_multi_hop_or_full_text_support", smoke)
        self.assertIn("_require_audit_citations_payload", smoke)
        self.assertIn("_require_not_found_safety_payload", smoke)
        self.assertIn("offline verify not-found safety", smoke)
        self.assertIn("resolve_identifier_or_replace", smoke)
        self.assertIn("not_found_is_high_risk_not_fabrication_proof", smoke)
        self.assertIn("_require_review_summary", smoke)
        self.assertIn("_require_action_queues", smoke)
        self.assertIn("_require_triage_plan", smoke)
        self.assertIn("_require_risk_reason", smoke)
        self.assertIn("_require_suggested_fix", smoke)
        self.assertIn("_require_tool_description", smoke)
        self.assertIn("tool metadata descriptions", smoke)
        self.assertIn("will not fetch gated", smoke)
        self.assertIn("no_unstated_multi_hop_or_full_text_support", smoke)
        self.assertIn("--require-sdk", smoke)
        self.assertIn("require_sdk", smoke)
        self.assertIn("source_health", smoke)
        self.assertIn("sources_available", smoke)
        self.assertIn("sources_failed", smoke)
        self.assertIn("retry_delay_seconds", smoke)
        self.assertIn("retry_delay_sources", smoke)
        self.assertIn("source-health retry delay provenance", smoke)
        self.assertIn("STABLE_NEXT_ACTIONS", smoke)
        self.assertIn("schema_version", smoke)
        self.assertIn("error.recovery", smoke)
        self.assertIn("error.next_action", smoke)
        self.assertIn("ERROR_CODE_RETRYABLE", smoke)
        self.assertIn("ERROR_CODE_CATEGORY", smoke)
        self.assertIn("error.retryable", smoke)
        self.assertIn("error.category", smoke)
        self.assertIn("details.expected", smoke)
        self.assertIn("details.received", smoke)
        self.assertIn("batch shape error details", smoke)
        self.assertIn("full-text-file error details", smoke)
        self.assertIn("missing_support_set_full_text_file", smoke)
        self.assertIn('shutil.which("citeguard-mcp")', smoke)
        self.assertIn("missing_citation_input", smoke)
        self.assertIn("missing_claim", smoke)
        self.assertIn("audit_citations_tool", smoke)
        self.assertIn("audit_claim_support_tool", smoke)
        self.assertIn("review_summary", smoke)
        self.assertIn("action_queues", smoke)
        self.assertIn("review_summary.triage_plan", smoke)
        self.assertIn("review_summary.suggested_fix_summary", smoke)
        self.assertIn("auto_apply_allowed=false", smoke)
        self.assertIn("risk_reason", smoke)
        self.assertIn("suggested_fix", smoke)
        self.assertIn("tool_metadata_phrases", release_gate)
        self.assertIn("tool_metadata_checked", release_gate)
        self.assertIn("support_tool_metadata_full_text_file", release_gate)
        self.assertIn("support_set_tool_metadata", release_gate)
        self.assertIn("MCP tool metadata missing required phrase", release_gate)
        self.assertIn("high_risk_only", smoke)
        self.assertIn("_require_high_risk_filtered_payload", smoke)
        self.assertIn("_require_support_audit_high_risk_counterevidence_payload", smoke)
        self.assertIn("include_counterevidence", smoke)
        self.assertIn("offline support-set counter-evidence leads", smoke)
        self.assertIn("support-audit high-risk counter-evidence filtering", smoke)
        self.assertIn("filtered.returned_indexes", smoke)
        self.assertIn("filtered.omitted_review_summary", smoke)
        self.assertIn("search_counterevidence_tool", smoke)
        self.assertIn("_require_counterevidence_payload", smoke)
        self.assertIn("review_counterevidence_leads", smoke)
        self.assertIn("explicit_contradiction_cue", smoke)
        self.assertIn("improvement_negation", smoke)
        self.assertIn("source_outage_safety", smoke)
        self.assertIn("source_outage_safety_cue", smoke)
        self.assertIn("source-outage safety counter-evidence leads", smoke)
        self.assertIn("Chinese source-outage safety leads", smoke)
        self.assertIn("源不可达会提高引用被判定为伪造的置信度", smoke)
        self.assertIn("input_mode", smoke)
        self.assertIn("citation_set", smoke)
        self.assertIn("installed `citeguard-mcp`", setup_doc)
        self.assertIn("audit_citations_tool", setup_doc)
        self.assertIn("check_claim_support_tool", setup_doc)
        self.assertIn("evidence_scope=full_text", setup_doc)
        self.assertIn("user_full_text_file_1", setup_doc)
        self.assertIn("audit_claim_support_tool", setup_doc)
        self.assertIn("checks batch tool metadata descriptions", setup_doc)
        self.assertIn("review_summary", setup_doc)
        self.assertIn("action_queues", setup_doc)
        self.assertIn("review_summary.triage_plan", setup_doc)
        self.assertIn("review_summary.suggested_fix_summary", setup_doc)
        self.assertIn("auto_apply_allowed=false", setup_doc)
        self.assertIn("risk_reason", setup_doc)
        self.assertIn("suggested_fix.kind", setup_doc)
        self.assertIn("suggested_fix.requires_user_confirmation", setup_doc)
        self.assertIn("high_risk_only=true", setup_doc)
        self.assertIn("filtered.returned_indexes", setup_doc)
        self.assertIn("top risk indexes", setup_doc)
        self.assertIn("python scripts/smoke_mcp.py --require-sdk", setup_doc)
        self.assertIn("missing MCP dependencies are a failure", setup_doc)
        self.assertIn("search_counterevidence_tool", setup_doc)
        self.assertIn("signal=explicit_contradiction_cue", setup_doc)
        self.assertIn("input_mode=citation_set", setup_doc)
        self.assertIn("MCP SDK requires Python 3.10+", setup_doc)
        self.assertIn("Top-level batch shape errors", setup_doc)
        self.assertIn("details.expected", setup_doc)
        self.assertIn("details.received", setup_doc)
        self.assertIn("details.field=citations", setup_doc)
        self.assertIn("details.field=items", setup_doc)
        self.assertIn("MCP SDK requires Python 3.10+", ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8")))
        self.assertIn("structured error contract", setup_doc)
        self.assertIn("error.recovery", setup_doc)
        self.assertIn("error.next_action", setup_doc)
        self.assertIn("source_health.schema_version", setup_doc)
        self.assertIn("configured/checked/responded/unchecked sources", setup_doc)
        self.assertIn("source_health.summary", setup_doc)
        self.assertIn("failure_details", setup_doc)
        self.assertIn("failure_count", setup_doc)
        self.assertIn("final_url", setup_doc)
        self.assertIn("redirected", setup_doc)
        self.assertIn("retry_after_seconds", setup_doc)
        self.assertIn("next_action", setup_doc)
        self.assertIn("support_models.install_hint", setup_doc)
        self.assertIn("`citeguard[models]`", setup_doc)
        self.assertIn("`.[models]` from a source checkout", setup_doc)
        self.assertLess(
            setup_doc.index("`citeguard[models]`"),
            setup_doc.index("`.[models]` from a source checkout"),
        )
        self.assertIn("next_action=review_counterevidence_leads", setup_doc)
        self.assertIn("cache_status", setup_doc)
        self.assertIn("without exposing", setup_doc)
        self.assertIn("raw cache queries", setup_doc)
        self.assertIn("polite_access", setup_doc)
        self.assertIn("CITEGUARD_MAILTO", setup_doc)
        self.assertIn("fix_configuration", setup_doc)
        self.assertIn("not evidence that a citation is", setup_doc)
        self.assertIn("`verify_citation_tool` `not_found`", setup_doc)
        self.assertIn("does not call the citation fake or fabricated", setup_doc)
        readme = ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8"))
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        support = (ROOT / "citeguard" / "verification" / "support.py").read_text(encoding="utf-8")
        combined_counterevidence_contract = f"{readme}\n{setup_doc}\n{cli_reference}\n{support}"
        self.assertIn("source_outage_safety", combined_counterevidence_contract)
        self.assertIn("source_outage_safety_cue", combined_counterevidence_contract)
        self.assertIn("not_found", combined_counterevidence_contract)
        self.assertIn("Chinese source-outage/not-found overclaims", combined_counterevidence_contract)
        self.assertIn("源不可达", combined_counterevidence_contract)

    def test_cli_reference_documents_status_schema_contract(self):
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")

        required_phrases = [
            "schema_version",
            "source_health.schema_version",
            "sources_configured",
            "sources_checked",
            "sources_responded",
            "sources_unchecked",
            "failure_details",
            "failure_count",
            "next_action",
            "cache_status",
            "inspect_ok",
            "polite_access",
            "configured_contact_required_sources",
            "contact_env_var",
            "polite_access.status",
            "error.next_action",
            "Crossref records with missing `container-title`",
            "Semantic Scholar",
            "non-object `externalIds`",
            "arXiv Atom entries",
            "blank entries are skipped",
            "incomplete metadata, not evidence",
            "metadata.evidence_harvest_failures",
            "stage=remote_evidence",
            "attempt_count",
            "retry_count",
            "retry_after_seconds",
            "rate-limited landing",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, cli_reference)

    def test_cache_replay_fixture_export_is_documented_as_deterministic(self):
        readme = ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8"))
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        mcp_setup = (ROOT / "docs" / "mcp_setup.md").read_text(encoding="utf-8")
        checklist = (ROOT / "docs" / "release_checklist.md").read_text(encoding="utf-8")
        combined = f"{readme}\n{cli_reference}\n{mcp_setup}\n{checklist}"

        required_phrases = [
            "cache export --deterministic --output",
            "deterministic records-only fixture",
            "strip timestamp-only",
            "timestamp-only manifest fields",
            "raw match score",
            "--operation lookup",
            "--source SOURCE",
            "selected_cache_entry_*",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_cli_reference_documents_full_text_file_error_contract(self):
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        error_docs = (ROOT / "docs" / "error_codes.md").read_text(encoding="utf-8")
        combined = f"{cli_reference}\n{error_docs}"

        required_phrases = [
            "details.field=full_text_file",
            "details.dependency=pypdf",
            "details.command",
            "details.index",
            "details.tool",
            "details.citation_index",
            "file_error",
            "details.filename",
            "details.errno",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_cli_reference_documents_batch_shape_error_contract(self):
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        error_docs = (ROOT / "docs" / "error_codes.md").read_text(encoding="utf-8")
        combined = f"{cli_reference}\n{error_docs}"

        required_phrases = [
            "details.command",
            "details.expected",
            "details.received",
            "1-based `details.index`",
            "details.line",
            "details.column",
            "JSON/JSONL parse errors",
            "filtered.returned_indexes",
            "filtered.omitted_indexes",
            "filtered.omitted_review_summary",
            "omitted rows' risk counts",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_cli_reference_documents_input_file_error_contract(self):
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        error_docs = (ROOT / "docs" / "error_codes.md").read_text(encoding="utf-8")
        combined = f"{cli_reference}\n{error_docs}"

        required_phrases = [
            "Missing or unreadable input files",
            "file_error",
            "details.field=path",
            "details.command",
            "details.filename",
            "details.errno",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_cli_reference_documents_output_file_error_contract(self):
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        error_docs = (ROOT / "docs" / "error_codes.md").read_text(encoding="utf-8")
        combined = f"{cli_reference}\n{error_docs}"

        required_phrases = [
            "cache export --output",
            "details.field=output",
            "details.command=cache",
            "details.cache_command=export",
            "details.filename",
            "details.errno",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_support_audit_citation_set_workflow_is_documented(self):
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        mcp_setup = (ROOT / "docs" / "mcp_setup.md").read_text(encoding="utf-8")
        skill = (ROOT / "skills" / "citeguard-verify" / "SKILL.md").read_text(encoding="utf-8")
        example = (ROOT / "examples" / "claim_citations.json").read_text(encoding="utf-8")
        combined = f"{cli_reference}\n{mcp_setup}\n{skill}\n{example}"

        required_phrases = [
            "citation-set item",
            "`citations`, a non-empty list of citation objects",
            "input_mode=citation_set",
            "support_mode",
            'support-audit examples/references.md --claim "The cited papers support my claim." --high-risk-only',
            'support-audit examples/references.md --claim "The cited papers support my claim." --with-counterevidence',
            "reference-file input, preserving original extracted-citation indexes",
            "reference-file counter-evidence review leads",
            "input_source_path",
            "input_source_index",
            "input_source_locator",
            "input_source_line_start",
            "input_source_line_end",
            '"citations"',
            "audit_claim_support_tool",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_support_set_policy_fixture_is_documented_for_release(self):
        benchmark_design = (ROOT / "docs" / "benchmark_design.md").read_text(encoding="utf-8")
        benchmark_todo = (ROOT / "docs" / "benchmark_todo.md").read_text(encoding="utf-8")
        checklist = (ROOT / "docs" / "release_checklist.md").read_text(encoding="utf-8")
        eval_script = (ROOT / "scripts" / "eval_support.py").read_text(encoding="utf-8")
        combined = f"{benchmark_design}\n{benchmark_todo}\n{checklist}\n{eval_script}"

        required_phrases = [
            "support_set_policy",
            "citation-set",
            "multiple weak",
            "run_support_set_policy_fixture_report",
            "support_set_policy_case_count",
            "support_set_policy_case_types",
            "support_set_policy_languages",
            "support_set_policy_case_ids",
            "case-type/language coverage",
            "manifest fields",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_false_support_analysis_is_documented_for_release(self):
        readme = ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8"))
        support_eval_doc = (ROOT / "docs" / "support_eval.md").read_text(encoding="utf-8")
        cli_reference = (ROOT / "docs" / "cli_reference.md").read_text(encoding="utf-8")
        benchmark_design = (ROOT / "docs" / "benchmark_design.md").read_text(encoding="utf-8")
        benchmark_todo = (ROOT / "docs" / "benchmark_todo.md").read_text(encoding="utf-8")
        compare_script = (ROOT / "scripts" / "compare_support_baselines.py").read_text(encoding="utf-8")
        combined = f"{readme}\n{support_eval_doc}\n{cli_reference}\n{benchmark_design}\n{benchmark_todo}\n{compare_script}"

        required_phrases = [
            "macro and weighted precision/recall/F1",
            "macro precision / recall / F1 and weighted precision / recall / F1",
            "per-label precision/recall/F1",
            "per-label precision / recall / F1",
            "`per_label`",
            "`review_queue`",
            "--review-queue-only",
            "review_queue_case_ids",
            "critical_review_case_ids",
            "quality_gate.review_queue_case_ids",
            "quality_gate.critical_review_case_ids",
            "`recommended_action`",
            "false_support_analysis",
            "abstention_analysis",
            "incorrect_abstention_count",
            "correct_abstention_count",
            "abstention_analysis.review_case_ids",
            "abstention_total_count",
            "abstention_incorrect_count",
            "abstention_correct_count",
            "abstention_review_case_ids",
            "total_overcall_count",
            "risk_slices",
            "top_risk_slice",
            "false_support_analysis.risk_slices",
            "false_support_analysis.top_risk_slice",
            "false_support_analysis.review_plan",
            "review_plan.status",
            "recommended_annotation_packets",
            "annotation_packet.command_template",
            "supported_overcall_blockers",
            "weak_support_overcall_review",
            "release_blocker_summary.release_blocked",
            "release_blocker_summary.benchmark_claim_safe",
            "release_blocker_summary.blocking_case_ids",
            "release_blocker_summary.next_action",
            "false_support_risk_slices",
            "top_false_support_risk_slice",
            "false_support_total_overcall_count",
            "acceptance_guard",
            "ok_to_accept_supported",
            "block_acceptance_case_ids",
            "review_before_accepting_case_ids",
            "false_support_ok_to_accept_supported",
            "false_support_block_acceptance_count",
            "false_support_block_acceptance_case_ids",
            "false_support_review_before_accepting_case_ids",
            "support_overcall_count",
            "support_overcall_rate",
            "false_support_risk_slice_count",
            "false_support_top_risk_slice_id",
            "false_support_top_risk_slice_case_ids",
            "false_support_review_plan_status",
            "false_support_review_plan_phase_ids",
            "false_support_overcall_backends",
            "false_support_top_overcall_backend",
            "false_support_top_overcall_review_plan_status",
            "false_support_top_overcall_review_plan_next_action",
            "false_support_top_overcall_review_plan_phase_ids",
            "support_release_status",
            "support_release_next_action",
            "support_release_quality_gate_ok",
            "support_release_label_sidecar_gate_ok",
            "support_release_benchmark_claim_safe",
            "support_release_review_top_case_ids",
            "support_release_blocking_case_ids",
            "support_release_review_required_case_ids",
            "support_release_top_risk_slice_id",
            "support_release_label_high_risk_unreviewed",
            "Support Eval Scripts",
            "scripts/compare_support_baselines.py",
            "high-risk false support case ids",
            "high_risk_false_support_case_ids",
            "false_support_case_ids",
            "weak_false_support_case_ids",
            "high_risk_overcall_case_ids",
            "by_language",
            "language 覆盖",
            "test split",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_support_seed_documents_new_high_risk_boundaries(self):
        readme = ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8"))
        support_eval_doc = (ROOT / "docs" / "support_eval.md").read_text(encoding="utf-8")
        changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        benchmark_todo = (ROOT / "docs" / "benchmark_todo.md").read_text(encoding="utf-8")
        support_eval = (ROOT / "data" / "eval" / "support_eval.json").read_text(encoding="utf-8")
        sidecar = (ROOT / "data" / "eval" / "support_eval_label_sidecar.json").read_text(encoding="utf-8")
        support_eval_payload = json.loads(support_eval)
        evidence_case_count = len(support_eval_payload["cases"])
        set_case_count = len(support_eval_payload["set_cases"])
        combined = f"{readme}\n{support_eval_doc}\n{changelog}\n{benchmark_todo}\n{support_eval}\n{sidecar}"

        required_phrases = [
            f"{evidence_case_count} evidence-level cases",
            "benchmark provenance",
            "source-outage-to-fabrication inferences",
            "source outage",
            "Chinese source-outage/not-found safety benchmark cases",
            "eligibility criteria",
            "simulated-review causal",
            "reviewer-replacement overclaims",
            "multi-paper weak-evidence over-synthesis",
            "model-availability-as-support overclaims",
            "supplemental-material full-text boundaries",
            "Semantic Scholar rate-limit non-existence overclaims",
            f"{set_case_count} citation-set policy cases",
            "Chinese citation-set weak aggregation boundary",
            "source-limited citation-set fabrication boundary",
            '"id": "s31"',
            '"id": "s32"',
            '"id": "s33"',
            '"id": "s34"',
            '"id": "s35"',
            '"id": "s36"',
            '"id": "s37"',
            '"id": "s38"',
            '"id": "s39"',
            '"id": "s40"',
            '"id": "s41"',
            '"id": "s42"',
            '"id": "s43"',
            '"id": "s44"',
            '"case_id": "s31"',
            '"case_id": "s32"',
            '"case_id": "s33"',
            '"case_id": "s34"',
            '"case_id": "s35"',
            '"case_id": "s36"',
            '"case_id": "s37"',
            '"case_id": "s38"',
            '"case_id": "s39"',
            '"case_id": "s40"',
            '"case_id": "s41"',
            '"case_id": "s42"',
            '"case_id": "s43"',
            '"case_id": "s44"',
            '"id": "ss05"',
            '"id": "ss06"',
            '"case_id": "ss05"',
            '"case_id": "ss06"',
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)

    def test_release_checklist_includes_support_label_audit(self):
        checklist = (ROOT / "docs" / "release_checklist.md").read_text(encoding="utf-8")
        benchmark_design = (ROOT / "docs" / "benchmark_design.md").read_text(encoding="utf-8")
        benchmark_todo = (ROOT / "docs" / "benchmark_todo.md").read_text(encoding="utf-8")
        guidelines = (ROOT / "docs" / "support_labeling_guidelines.md").read_text(encoding="utf-8")
        combined = f"{checklist}\n{benchmark_design}\n{benchmark_todo}\n{guidelines}"

        self.assertIn("prepare_support_label_sidecar.py", checklist)
        self.assertIn("docs/configuration.md", checklist)
        self.assertIn("current CLI, runtime, and MCP behavior", checklist)
        self.assertIn("--audit", checklist)
        self.assertIn("--annotation-packet --priority high --split test", checklist)
        self.assertIn("--instructions-output", checklist)
        self.assertIn("annotator instruction", checklist)
        self.assertIn("--merge-annotation-packet", checklist)
        self.assertIn("merge_report.conflicts", checklist)
        self.assertIn("--apply-adjudications", checklist)
        self.assertIn("adjudication_report.conflicts", checklist)
        self.assertIn("annotation.annotator_id", checklist)
        self.assertIn("review_focus", combined)
        self.assertIn("label hint", guidelines)
        self.assertIn("不能当作 label", benchmark_design)
        self.assertIn("duplicate_annotator", checklist)
        self.assertIn("adjudicated_label", checklist)
        self.assertIn("human-reviewed benchmark", checklist)
        eval_support = (ROOT / "scripts" / "eval_support.py").read_text(encoding="utf-8")
        self.assertIn(
            "Set to 0 when a human-reviewed benchmark slice exists and supported-label disagreements must block release.",
            eval_support,
        )
        self.assertNotIn("Use 0 for release-grade human-reviewed benchmarks.", eval_support)
        self.assertIn("compare_support_baselines.py", checklist)
        self.assertIn("support-baselines-release", checklist)
        self.assertIn("--review-queue-only", checklist)
        self.assertIn("quality_gate.review_queue_case_ids", checklist)
        self.assertIn("quality_gate.critical_review_case_ids", checklist)
        self.assertIn("package archive cleanliness", checklist)
        self.assertIn("__pycache__", checklist)
        self.assertIn("baseline comparison table", benchmark_design)
        self.assertIn('python -m pip install "citeguard[pdf]"', checklist)
        self.assertIn('python -m pip install -e ".[pdf]"', checklist)
        self.assertLess(
            checklist.index('python -m pip install "citeguard[pdf]"'),
            checklist.index('python -m pip install -e ".[pdf]"'),
        )
        self.assertIn("local PDF full-text evidence support", checklist)
        self.assertIn("--fail-on-high-risk-unreviewed", checklist)
        self.assertIn("--fail-on-high-risk-unreviewed-language", checklist)
        self.assertIn("high-risk unreviewed gate", checklist)
        self.assertIn("--fail-on-high-risk-unreviewed", benchmark_design)
        self.assertIn("--fail-on-high-risk-unreviewed-language", benchmark_design)
        self.assertIn("audit_gate", benchmark_design)
        self.assertIn("high-risk test packet", benchmark_design)
        self.assertIn("--case-type", benchmark_design)
        self.assertIn("--case-id", benchmark_design)
        self.assertIn("--lang", benchmark_design)
        self.assertIn("--limit", benchmark_design)
        self.assertIn("--limit 3", checklist)
        self.assertIn("--unreviewed-only", combined)
        self.assertIn("--review-status", combined)
        self.assertIn("single_annotator", combined)
        self.assertIn("--limit-per-language", combined)
        self.assertIn("--limit-per-case-type", combined)
        self.assertIn("--limit-per-evidence-scope", combined)
        self.assertIn("language/case-type/evidence-scope reviewer batches", checklist)
        self.assertIn("packet_id", combined)
        self.assertIn("packet_digest", combined)
        self.assertIn("packet_summary", combined)
        self.assertIn("review_protocol", combined)
        self.assertIn("packet_role", combined)
        self.assertIn("independent_labeling_required", combined)
        self.assertIn("benchmark_target_annotator_count", combined)
        self.assertIn("adjudication_required_on_disagreement", combined)
        self.assertIn("merge_report.source_packet_ids", combined)
        self.assertIn("source_packet_metadata", combined)
        self.assertIn("recommended_packets", combined)
        self.assertIn("review_plan", combined)
        self.assertIn("review_plan_smoke", checklist)
        self.assertIn("review_plan.next_phase", combined)
        self.assertIn("first-review, second-review, adjudication", combined)
        self.assertIn("release-gate tightening", combined)
        self.assertIn("full_text_required_unreviewed", combined)
        self.assertIn("full-text-boundary first review", combined)
        self.assertIn("--fail-on-full-text-required-unreviewed", combined)
        self.assertIn("--fail-on-policy-boundary-unreviewed", combined)
        self.assertIn("case_count_by_language", combined)
        self.assertIn("case_count_by_evidence_scope", combined)
        self.assertIn("case_count_by_review_status", combined)
        self.assertIn("label_maturity", combined)
        self.assertIn("sidecar_case_provenance", combined)
        self.assertIn("missing_count", combined)
        self.assertIn("missing_case_ids", combined)
        self.assertIn("high_risk_unreviewed_by_language", combined)
        self.assertIn("raw_dual_agreement_rate", combined)
        self.assertIn("unresolved_disagreement_count", combined)
        self.assertIn("dual_disagreement_label_pair_counts", combined)
        self.assertIn("supported_disagreement_case_ids", combined)
        self.assertIn("high_risk_review", combined)
        self.assertIn("case_count_by_language", combined)
        self.assertIn("reviewed_by_language", combined)
        self.assertIn("unreviewed_by_language", combined)
        self.assertIn("high_risk_case_count_by_language", combined)
        self.assertIn("high_risk_reviewed_by_language", combined)
        self.assertIn("high_risk_unreviewed_by_language", combined)
        self.assertIn("high_risk_case_count_by_language_case_type", combined)
        self.assertIn("high_risk_reviewed_by_language_case_type", combined)
        self.assertIn("high_risk_unreviewed_by_language_case_type", combined)
        self.assertIn("reviewed_case_ids_by_language", combined)
        self.assertIn("unreviewed_case_ids_by_language", combined)
        self.assertIn("test_split", combined)
        self.assertIn("weak support, hard negatives, contradictions, full-text-required cases", combined)
        self.assertIn("--min-high-risk-reviewed", combined)
        self.assertIn("--min-high-risk-reviewed-by-language", combined)
        self.assertIn("--min-dual-annotated", combined)
        self.assertIn("--max-unresolved-disagreements", combined)
        self.assertIn("--min-raw-dual-agreement-rate", combined)
        self.assertIn("--max-supported-disagreements", combined)
        self.assertIn("status consistency", combined)
        self.assertIn("not_human_reviewed", combined)
        self.assertIn("dual_annotator_agreed", combined)
        self.assertIn("dual_annotator_adjudicated", combined)
        self.assertIn("published_benchmark", combined)
        self.assertIn("source locator", combined)
        self.assertIn("label_source_counts", combined)
        self.assertIn("reviewed_by_label_source", combined)
        self.assertIn("unreviewed_by_label_source", combined)
        self.assertIn("reviewed_source_locator_count", combined)
        self.assertIn("published_benchmark_source_locator_count", combined)
        self.assertIn("support_label_gate_ok", combined)
        self.assertIn("support_label_label_source_counts", combined)
        self.assertIn("support_label_human_reviewed", combined)
        self.assertIn("support_label_high_risk_case_count_by_language_case_type", combined)
        self.assertIn("support_label_high_risk_reviewed_by_language_case_type", combined)
        self.assertIn("support_label_high_risk_unreviewed_by_language_case_type", combined)
        self.assertIn("support_label_full_text_required_unreviewed", combined)
        self.assertIn("support_label_policy_boundary_unreviewed", combined)
        self.assertIn("support_label_sidecar_provenance_missing_count", combined)
        self.assertIn("support_label_sidecar_provenance_missing_case_ids", combined)
        self.assertIn("support_label_published_benchmark_source_locator_count", combined)
        self.assertIn("support_release_status", combined)
        self.assertIn("support_release_next_action", combined)
        self.assertIn("support_release_blocking_case_ids", combined)
        self.assertIn("support_release_label_high_risk_unreviewed", combined)

    def test_agent_skill_documents_product_contract(self):
        skill = (ROOT / "skills" / "citeguard-verify" / "SKILL.md").read_text(encoding="utf-8")
        examples = (ROOT / "skills" / "citeguard-verify" / "references" / "examples.md").read_text(encoding="utf-8")
        openai_yaml = (ROOT / "skills" / "citeguard-verify" / "agents" / "openai.yaml").read_text(encoding="utf-8")
        combined = f"{skill}\n{examples}"
        sidecar = json.loads((ROOT / "data" / "eval" / "support_eval_label_sidecar.json").read_text(encoding="utf-8"))
        first_review_case_types = {
            "contradiction",
            "contradiction_set",
            "full_text_required",
            "hard_negative",
            "weak_set_boundary",
        }
        first_review_candidate_count = sum(
            1
            for item in sidecar["cases"]
            if item.get("adjudication_status") == "not_human_reviewed"
            and item.get("case_type") in first_review_case_types
        )
        support_cases = [
            case for case in load_support_eval(str(ROOT / "data" / "eval" / "support_eval.json")) if case.split == "test"
        ]
        support_report = run_support_eval_report(support_cases, HeuristicSupportBackend())
        weak_support_overcall_case_ids = support_report["acceptance_guard"]["review_before_accepting_case_ids"]
        weak_support_overcall_case_ids_json = json.dumps(weak_support_overcall_case_ids)

        self.assertLessEqual(len(skill.splitlines()), 500)
        self.assertIn("references/examples.md", skill)
        self.assertIn('display_name: "CiteGuard Verify"', openai_yaml)
        self.assertIn('short_description: "Skeptical citation auditing for agents"', openai_yaml)
        self.assertIn("Use $citeguard-verify", openai_yaml)
        self.assertIn('type: "mcp"', openai_yaml)
        self.assertIn('value: "citeguard"', openai_yaml)
        self.assertIn('transport: "stdio"', openai_yaml)

        required_phrases = [
            "related work",
            "literature review",
            "bibliography",
            "pasted Markdown/LaTeX/Word-style reference section",
            "local `\\bibliography{refs}` / `\\addbibresource{refs.bib}`",
            "Do not silently change",
            "Do not translate `not_found`, `source_unavailable`, or `timeout` into \"fake\"",
            "Do not claim full-text support from an abstract-level support result",
            "local lawful text/PDF file",
            "citeguard[pdf]",
            'python -m pip install "citeguard[mcp]"',
            'python -m pip install -e ".[mcp]"',
            "Codex:",
            "Claude Code:",
            "Cursor:",
            "`support_models.engine`",
            "`support_models.next_action`",
            "`support_models.install_hint`",
            "`heuristic_fallback` mode",
            "`citeguard[models]`",
            "`.[models]` from a source checkout",
            "python3 scripts/warmup_support_models.py",
            "Support model status:",
            '"next_action": "install_or_configure_dependency"',
            "Claim-support checks are degraded",
            "verify_citation_tool",
            "audit_citations_tool",
            "check_claim_support_tool",
            "Claim support with a user-provided lawful full-text excerpt:",
            '"full_text": [',
            "Claim support with a user-provided lawful local file:",
            '"full_text_file": "/path/to/lawful-full-text-excerpt.txt"',
            "evidence.source_field=user_full_text_file_1",
            "error.code=file_error",
            "error.details.field=full_text_file",
            "error.details.filename",
            "error.next_action=repair_input",
            "evidence_scope=full_text",
            "evidence.source_field=user_full_text_excerpt_1",
            "caller-provided lawful excerpts",
            "Do not fetch gated full text, bypass paywalls",
            "## Pre-response Safety Checklist",
            "No silent edits:",
            "No fabrication overclaim:",
            "Scope is explicit:",
            "Traceability is preserved:",
            "Next action is machine-readable:",
            "`error.next_action`",
            "`error.retryable`",
            "`error.category`",
            "check_claim_support_set_tool",
            "One claim, multiple citations with one user-provided full-text file:",
            "`support_mode_details.full_text_evidence_present`",
            "Do not imply that every cited",
            "Nested claim-support audit with a full-text file:",
            "`error.details.citation_index`",
            "search_counterevidence_tool",
            "audit_claim_support_tool",
            "High-risk-only batch citation audit:",
            '"high_risk_only": true',
            "filtered.returned_indexes",
            "filtered.omitted_review_summary",
            "Malformed batch shape repair:",
            "error.details.expected=list",
            "machine-readable repair path",
            "Full-text file error repair:",
            '"code": "file_error"',
            '"filename": "/path/to/missing.txt"',
            '"errno": 2',
            "`errno=2`",
            "fetch gated full text or infer full-text",
            "Ambiguous citation:",
            "Metadata mismatch:",
            "Claim/citation batch:",
            "citeguard extract paper.tex",
            "referenced `.bib` citation item",
            "High-risk claim-support audit with counter-evidence leads:",
            '"include_counterevidence": true',
            '"counterevidence_top_k": 1',
            "review lead to inspect, not a contradiction verdict",
            "Sort or summarize by risk first",
            "Always include a next step",
            "review_summary",
            "action_queues",
            "review_summary.triage_plan",
            "review_summary.triage_plan.status",
            "review_summary.suggested_fix_summary",
            "auto_apply_allowed=false",
            "review_required_indexes",
            "source_retry_is_inconclusive_not_fabrication",
            "risk_reason",
            "suggested_fix.kind",
            "suggested_fix.requires_user_confirmation",
            "input_source_line_start",
            "input_source_line_end",
            "`source item`",
            "`path:line`",
            "no_strong_match",
            "metadata_fields_mismatch",
            "citation_identity_unresolved",
            "available_evidence_does_not_confirm_claim",
            "top risk indexes",
            "next_action",
            "review_counterevidence_leads",
            "signal=source_outage_safety_cue",
            "error.next_action",
            "error.recovery",
            "error.details.expected",
            "error.details.received",
            "error.retryable=false",
            "error.category=input_repair",
            '"retryable": false',
            '"category": "input_repair"',
            "Prefer `error.retryable` and `error.category`",
            "`source_limited` is the category",
            "MCP batch shape errors",
            "Do not quote raw validation prose",
            "metadata.evidence_harvest_failures",
            "stage=remote_evidence",
            "Do not",
            "claim full-text or landing-page support from the missing snippet",
            "failure_kind_counts",
            "failure_kind_sources",
            "rate_limited",
            "retry_after_seconds",
            "retry_after_sources",
            "final_url",
            "redirected",
            "retry_guidance=wait_before_retry",
            "source_health.summary.next_action",
            "not evidence of fabrication",
            "## Response template",
            "One-sentence bottom line",
            "Review queue summary from `review_summary.action_queues`",
            "review_summary.recommended_next_steps.steps",
            "recommended next steps",
            "`filtered.returned_indexes` / `filtered.omitted_indexes`",
            "`index`, `source item`, `citation/claim`, `verdict`, `risk`, `next_action`,",
            "`evidence source`, `why`, `next step`",
            "`examples/references.md:6`",
            "`input_source_line_start` / `input_source_line_end`",
            "Use `evidence_source_name`",
            "--review-queue-only",
            "--from-review-queue",
            "blinded annotation packet",
            "review_queue_rank",
            "annotation.evidence_scope_assessed",
            "annotation.full_text_needed",
            "judgments remain auditable after merge",
            '"evidence_scope_assessed": "abstract"',
            '"full_text_needed": "yes"',
            "not a final full-text conclusion",
            "Review-plan audit for benchmark labeling:",
            "review_plan.next_phase=first_review_high_risk",
            f"first review: {first_review_candidate_count} candidate case(s)",
            f'"review_before_accepting_case_ids": {weak_support_overcall_case_ids_json}',
            f'"weak_false_support_case_ids": {weak_support_overcall_case_ids_json}',
            f'"top_risk_slice_case_ids": {weak_support_overcall_case_ids_json}',
            "review_plan.phases[*].command_template",
            "review_plan.phases[*].annotation_packet.command_template",
            "recommended_annotation_packets",
            "release-gate tightening",
            "Do not describe this seed set as a human-reviewed benchmark",
            "--case-type full_text_required",
            "support-label-packet-full-text-required-unreviewed",
            "full-text boundary review is complete",
            "--case-type weak_set_boundary",
            "support-label-packet-policy-boundary-unreviewed",
            "policy-boundary review before claiming multi-citation support readiness",
            "Filtered high-risk response example:",
            "Ambiguous compact response example:",
            "Metadata mismatch compact response example:",
            "`disambiguate_identifier`",
            "`review_metadata`",
            "`field_diffs=year,venue`",
            "`suggested_fix.requires_user_confirmation=true`",
            "Bottom line: CiteGuard found 1 high-risk item.",
            "review_summary.triage_plan.status=review_required",
            "risk_reason=no_strong_match",
            "suggested_fix.kind=add_identifier_or_replace",
            "Two lower-risk rows were checked",
            "filtered.omitted_review_summary",
            "The hidden rows are summarized",
            "they were examined, not skipped",
            "`review_queue`",
            "`quality_gate.review_queue_case_ids`",
            "`quality_gate.critical_review_case_ids`",
            "`acceptance_guard`",
            "acceptance_guard.ok_to_accept_supported",
            "block_acceptance_case_ids",
            "review_before_accepting_case_ids",
            "supported overcalls",
            "weak support overcalls",
            "false_support_analysis.false_support_case_ids",
            "false_support_analysis.weak_false_support_case_ids",
            "false_support_analysis.high_risk_overcall_case_ids",
            "false_support_analysis.review_plan",
            "review_plan.status",
            "review_plan.status=blocked",
            "recommended_annotation_packets",
            "annotation_packet.command_template",
            "review_required",
            "supported_overcall_blockers",
            "weak_support_overcall_review",
            "highest_risk_slice_review",
            "false_support_review_plan_status",
            "false_support_review_plan_phase_ids",
            "false_support_top_overcall_review_plan_status",
            "false_support_top_overcall_review_plan_next_action",
            "false_support_top_overcall_review_plan_phase_ids",
            "false_support_analysis.risk_slices",
            "false_support_analysis.top_risk_slice",
            "contradicted_overcalled",
            "hard_negative_overcalled",
            "full_text_boundary_overcalled",
            "support-overcall `risk_slices`",
            "release-blocking triage",
            "source retry is inconclusive",
            "Scope / limitations",
            "## Scenario routing",
            "User pasted a bibliography",
            "LaTeX `\\bibitem`",
            "User is writing related work and asks for citations you generated",
            "User gives a claim with one cited paper",
            "User supplies a lawful excerpt or local full-text file",
            "User gives one claim backed by several papers",
            "User asks whether multiple weak citations jointly support a claim",
            "`support_mode_details.decision`",
            "`support_mode_details.policy`",
            "`support_mode_details.weakly_supported_indexes`",
            "Result is `not_found`, `source_unavailable`, or `timeout`",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)
        self.assertLess(
            skill.index('python -m pip install "citeguard[mcp]"'),
            skill.index('python -m pip install -e ".[mcp]"'),
        )
        self.assertLess(
            skill.index("`citeguard[models]`"),
            skill.index("`.[models]` from a source checkout"),
        )

    def test_runtime_recovery_hints_put_published_package_before_editable_checkout(self):
        checked_files = [
            ROOT / "citeguard" / "runtime.py",
            ROOT / "citeguard" / "mcp" / "server.py",
            ROOT / "scripts" / "smoke_mcp.py",
        ]
        for path in checked_files:
            with self.subTest(path=str(path.relative_to(ROOT))):
                text = path.read_text(encoding="utf-8")
                self.assertIn('python -m pip install "citeguard[mcp]"', text)
                self.assertIn('python -m pip install -e ".[mcp]"', text)
                self.assertLess(
                    text.index('python -m pip install "citeguard[mcp]"'),
                    text.index('python -m pip install -e ".[mcp]"'),
                )

        release_gate = (ROOT / "scripts" / "release_package_gate.py").read_text(encoding="utf-8")
        missing_sdk_message = release_gate.split("MCP SDK is not installed. Install published packages", 1)[1].split(
            "from a source checkout", 1
        )[0]
        self.assertIn('python -m pip install "citeguard[mcp]"', missing_sdk_message)
        self.assertIn('python -m pip install -e ".[mcp]"', missing_sdk_message)
        self.assertLess(
            missing_sdk_message.index('python -m pip install "citeguard[mcp]"'),
            missing_sdk_message.index('python -m pip install -e ".[mcp]"'),
        )

        runtime = (ROOT / "citeguard" / "runtime.py").read_text(encoding="utf-8")
        self.assertIn('python -m pip install "citeguard[models]"', runtime)
        self.assertIn('python -m pip install -e ".[models]"', runtime)
        self.assertLess(
            runtime.index('python -m pip install "citeguard[models]"'),
            runtime.index('python -m pip install -e ".[models]"'),
        )

    def test_security_compliance_boundaries_are_documented(self):
        readme = ((ROOT / "README.md").read_text(encoding="utf-8") + "\n" + (ROOT / "README.en.md").read_text(encoding="utf-8"))
        security = (ROOT / "docs" / "security_compliance.md").read_text(encoding="utf-8")
        combined = f"{readme}\n{security}"

        required_phrases = [
            "does not scrape CNKI",
            "Wanfang",
            "must not bypass paywalls",
            "local user-provided text/PDF readers",
            "robots.txt",
            "CITEGUARD_MAILTO",
            "Remote landing-page evidence harvesting is disabled by default",
            "metadata.evidence_harvest_failures",
            "stage=remote_evidence",
            "retry_after_seconds",
            "kind=non_html_response",
            "kind=no_extractable_evidence",
            "retry_after_sources",
            "retry_guidance=wait_before_retry",
            "empty values are not sent",
            "not as proof the citation is unavailable or fabricated",
            "not proof that a citation is fake",
            "not a legal authority",
            "Final decisions about research integrity",
        ]
        for phrase in required_phrases:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, combined)


if __name__ == "__main__":
    unittest.main()
