#!/usr/bin/env python3
"""Audit readiness of a real, independently double-annotated support benchmark."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from citeguard.verification.support_eval import load_support_label_cases
from citeguard.verification.support_eval_labels import validate_support_label_sidecar


HUMAN_BENCHMARK_CAMPAIGN_SCHEMA_VERSION = 1
HUMAN_BENCHMARK_TEST_SPLIT_MANIFEST_SCHEMA_VERSION = 1
DEFAULT_TEST_SPLIT_MANIFEST = "data/eval/human_support_benchmark_test_manifest.json"
REQUIRED_REAL_CASE_FIELDS = (
    "benchmark_origin",
    "domain",
    "writing_context",
    "source_locator",
    "evidence_locator",
    "rights_basis",
)
DOUBLE_ANNOTATION_STATUSES = {
    "dual_annotator_agreed",
    "dual_annotator_adjudicated",
}


class HumanBenchmarkCampaignError(ValueError):
    """Raised when the campaign configuration or benchmark inputs are malformed."""


def load_json(path: str) -> Dict[str, Any]:
    try:
        with Path(path).open(encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise HumanBenchmarkCampaignError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HumanBenchmarkCampaignError(f"invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(data, dict):
        raise HumanBenchmarkCampaignError(f"{path} must contain a JSON object")
    return data


def validate_campaign(campaign: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate the target and allowed values for one human-review campaign."""

    errors: List[str] = []
    if campaign.get("schema_version") != HUMAN_BENCHMARK_CAMPAIGN_SCHEMA_VERSION:
        errors.append(f"schema_version must be {HUMAN_BENCHMARK_CAMPAIGN_SCHEMA_VERSION}")
    if not str(campaign.get("campaign_id", "")).strip():
        errors.append("campaign_id is required")
    targets = campaign.get("targets")
    if not isinstance(targets, dict):
        errors.append("targets must be an object")
        targets = {}

    minimum_case_count = targets.get("minimum_case_count")
    maximum_case_count = targets.get("maximum_case_count")
    if not isinstance(minimum_case_count, int) or not 200 <= minimum_case_count <= 300:
        errors.append("targets.minimum_case_count must be an integer from 200 to 300")
    if not isinstance(maximum_case_count, int) or not isinstance(minimum_case_count, int) or maximum_case_count < minimum_case_count:
        errors.append("targets.maximum_case_count must be an integer greater than or equal to minimum_case_count")

    for field in (
        "minimum_by_language",
        "minimum_by_domain",
        "minimum_by_writing_context",
        "minimum_by_evidence_scope",
    ):
        values = targets.get(field)
        if not isinstance(values, dict) or not values:
            errors.append(f"targets.{field} must be a non-empty object")
            continue
        for key, value in values.items():
            if not str(key).strip() or not isinstance(value, int) or value < 1:
                errors.append(f"targets.{field} values must be positive integer quotas")
                break

    test_split = campaign.get("test_split")
    if not isinstance(test_split, dict):
        errors.append("test_split must be an object")
        test_split = {}
    minimum_test_case_count = test_split.get("minimum_case_count")
    if not isinstance(minimum_test_case_count, int) or minimum_test_case_count < 1:
        errors.append("test_split.minimum_case_count must be a positive integer")
    elif isinstance(maximum_case_count, int) and minimum_test_case_count > maximum_case_count:
        errors.append("test_split.minimum_case_count must not exceed targets.maximum_case_count")
    if test_split.get("freeze_required_for_readiness") is not True:
        errors.append("test_split.freeze_required_for_readiness must be true")

    allowed_values = campaign.get("allowed_values")
    if not isinstance(allowed_values, dict):
        errors.append("allowed_values must be an object")
        allowed_values = {}
    for field in ("benchmark_origin", "domain", "writing_context", "rights_basis"):
        values = allowed_values.get(field)
        if not isinstance(values, list) or not all(str(value).strip() for value in values):
            errors.append(f"allowed_values.{field} must be a non-empty list of strings")

    if errors:
        raise HumanBenchmarkCampaignError("; ".join(errors))
    return {"schema_version": campaign["schema_version"], "campaign_id": str(campaign["campaign_id"]), **campaign}


def audit_human_benchmark(
    dataset: Mapping[str, Any],
    sidecar: Mapping[str, Any],
    campaign: Mapping[str, Any],
    *,
    dataset_path: str = "",
    test_split_manifest: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return strict readiness evidence without treating unreviewed rows as labels."""

    valid_campaign = validate_campaign(campaign)
    cases = load_support_label_cases(dataset_path) if dataset_path else []
    if not cases:
        raise HumanBenchmarkCampaignError("dataset_path is required to validate the support-eval dataset")
    validate_support_label_sidecar(dict(sidecar), cases)

    raw_cases = _raw_cases_by_id(dataset)
    sidecar_by_id = {
        str(item.get("case_id", "")).strip(): item
        for item in sidecar.get("cases", [])
        if isinstance(item, dict) and str(item.get("case_id", "")).strip()
    }
    allowed = valid_campaign["allowed_values"]
    target = valid_campaign["targets"]

    cataloged_case_ids: List[str] = []
    qualified_case_ids: List[str] = []
    invalid_cases: List[Dict[str, Any]] = []
    disagreement_case_ids: List[str] = []
    qualified_rows: List[Dict[str, Any]] = []

    for case in cases:
        raw = raw_cases.get(case.case_id, {})
        if str(raw.get("benchmark_origin", "")).strip() not in set(allowed["benchmark_origin"]):
            continue
        cataloged_case_ids.append(case.case_id)
        issues = _case_issues(raw, sidecar_by_id.get(case.case_id, {}), allowed)
        if issues:
            invalid_cases.append({"case_id": case.case_id, "issues": issues})
            continue
        qualified_case_ids.append(case.case_id)
        qualified_rows.append(raw)
        if str(sidecar_by_id[case.case_id].get("adjudication_status", "")) == "dual_annotator_adjudicated":
            disagreement_case_ids.append(case.case_id)

    counts = {
        "cataloged_real_cases": len(cataloged_case_ids),
        "qualified_double_annotated_cases": len(qualified_case_ids),
        "invalid_real_cases": len(invalid_cases),
        "adjudicated_disagreement_cases": len(disagreement_case_ids),
        "qualified_by_language": _count(qualified_rows, "lang"),
        "qualified_by_domain": _count(qualified_rows, "domain"),
        "qualified_by_writing_context": _count(qualified_rows, "writing_context"),
        "qualified_by_evidence_scope": _count(qualified_rows, "evidence_scope"),
        "qualified_by_rights_basis": _count(qualified_rows, "rights_basis"),
    }
    deficits = _quota_deficits(counts, target)
    test_split = audit_test_split_manifest(
        dataset=dataset,
        sidecar=sidecar,
        campaign=valid_campaign,
        qualified_case_ids=qualified_case_ids,
        manifest=test_split_manifest,
    )
    if test_split["qualified_case_count"] < test_split["minimum_case_count"]:
        deficits.append(
            {
                "metric": "test_split.minimum_case_count",
                "actual": test_split["qualified_case_count"],
                "threshold": test_split["minimum_case_count"],
                "direction": "at_least",
            }
        )
    if not test_split["frozen"]:
        deficits.append(
            {
                "metric": "test_split.freeze_manifest",
                "actual": test_split["manifest_status"],
                "threshold": "frozen_and_matching",
                "direction": "equals",
            }
        )
    if counts["qualified_double_annotated_cases"] > int(target["maximum_case_count"]):
        deficits.append(
            {
                "metric": "maximum_case_count",
                "actual": counts["qualified_double_annotated_cases"],
                "threshold": target["maximum_case_count"],
                "direction": "at_most",
            }
        )

    ready = not invalid_cases and not deficits
    if ready:
        next_action = "freeze_test_split_and_run_model_evaluation"
    elif not cataloged_case_ids:
        next_action = "collect_real_sourced_cases_before_labeling"
    elif invalid_cases:
        next_action = "repair_provenance_or_independent_review_records"
    elif test_split["qualified_case_count"] >= test_split["minimum_case_count"] and not test_split["frozen"]:
        next_action = "freeze_heldout_test_split"
    else:
        next_action = "continue_independent_double_annotation"

    return {
        "schema_version": HUMAN_BENCHMARK_CAMPAIGN_SCHEMA_VERSION,
        "ok": True,
        "campaign_id": valid_campaign["campaign_id"],
        "status": "ready" if ready else "collection_incomplete",
        "benchmark_claim_safe": ready,
        "next_action": next_action,
        "targets": target,
        "counts": counts,
        "deficits": deficits,
        "invalid_cases": invalid_cases,
        "cataloged_case_ids": cataloged_case_ids,
        "qualified_case_ids": qualified_case_ids,
        "adjudicated_disagreement_case_ids": disagreement_case_ids,
        "test_split": test_split,
        "policy": {
            "human_labels_required": True,
            "minimum_distinct_annotators_per_case": 2,
            "real_source_provenance_required": True,
            "full_text_requires_lawful_rights_basis": True,
            "synthetic_or_model_labels_do_not_count": True,
            "frozen_heldout_test_split_required": True,
        },
    }


def build_test_split_manifest(
    dataset: Mapping[str, Any],
    sidecar: Mapping[str, Any],
    campaign: Mapping[str, Any],
    *,
    frozen_at: str,
) -> Dict[str, Any]:
    """Build a content-addressed manifest for the campaign's held-out test rows."""

    valid_campaign = validate_campaign(campaign)
    frozen_at = str(frozen_at).strip()
    if not _is_iso_timestamp(frozen_at):
        raise HumanBenchmarkCampaignError("frozen_at must be an ISO-8601 timestamp with a timezone")

    raw_cases = _raw_cases_by_id(dataset)
    sidecar_by_id = {
        str(item.get("case_id", "")).strip(): dict(item)
        for item in sidecar.get("cases", [])
        if isinstance(item, dict) and str(item.get("case_id", "")).strip()
    }
    case_ids = sorted(
        case_id
        for case_id, row in raw_cases.items()
        if str(row.get("benchmark_origin", "")).strip() == "real_source"
        and str(row.get("split", "")).strip() == "test"
    )
    return _test_split_manifest_payload(
        campaign_id=valid_campaign["campaign_id"],
        frozen_at=frozen_at,
        raw_cases=raw_cases,
        sidecar_by_id=sidecar_by_id,
        case_ids=case_ids,
    )


def audit_test_split_manifest(
    *,
    dataset: Mapping[str, Any],
    sidecar: Mapping[str, Any],
    campaign: Mapping[str, Any],
    qualified_case_ids: Iterable[str],
    manifest: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Check that a held-out split has a stable, content-addressed freeze record."""

    raw_cases = _raw_cases_by_id(dataset)
    sidecar_by_id = {
        str(item.get("case_id", "")).strip(): dict(item)
        for item in sidecar.get("cases", [])
        if isinstance(item, dict) and str(item.get("case_id", "")).strip()
    }
    qualified = set(str(case_id) for case_id in qualified_case_ids)
    case_ids = sorted(
        case_id
        for case_id, row in raw_cases.items()
        if case_id in qualified and str(row.get("split", "")).strip() == "test"
    )
    test_config = campaign["test_split"]
    expected = _test_split_manifest_payload(
        campaign_id=str(campaign["campaign_id"]),
        frozen_at=str(manifest.get("frozen_at", "")) if isinstance(manifest, Mapping) else "",
        raw_cases=raw_cases,
        sidecar_by_id=sidecar_by_id,
        case_ids=case_ids,
    )
    errors: List[str] = []
    if manifest is None:
        manifest_status = "not_frozen"
    elif not isinstance(manifest, Mapping):
        manifest_status = "invalid"
        errors.append("manifest must be an object")
    else:
        manifest_status = "frozen"
        if manifest.get("schema_version") != HUMAN_BENCHMARK_TEST_SPLIT_MANIFEST_SCHEMA_VERSION:
            errors.append(f"schema_version must be {HUMAN_BENCHMARK_TEST_SPLIT_MANIFEST_SCHEMA_VERSION}")
        if str(manifest.get("campaign_id", "")).strip() != str(campaign["campaign_id"]):
            errors.append("campaign_id does not match campaign")
        if not _is_iso_timestamp(str(manifest.get("frozen_at", ""))):
            errors.append("frozen_at must be an ISO-8601 timestamp with a timezone")
        for field in ("test_case_count", "test_case_ids", "test_cases_sha256", "test_sidecar_sha256"):
            if manifest.get(field) != expected[field]:
                errors.append(f"{field} does not match current qualified test split")
    if errors:
        manifest_status = "invalid"
    return {
        "minimum_case_count": int(test_config["minimum_case_count"]),
        "qualified_case_count": len(case_ids),
        "qualified_case_ids": case_ids,
        "freeze_required_for_readiness": bool(test_config["freeze_required_for_readiness"]),
        "frozen": bool(manifest is not None and not errors),
        "manifest_status": manifest_status,
        "manifest_errors": errors,
        "manifest": dict(manifest) if isinstance(manifest, Mapping) else None,
    }


def _test_split_manifest_payload(
    *,
    campaign_id: str,
    frozen_at: str,
    raw_cases: Mapping[str, Mapping[str, Any]],
    sidecar_by_id: Mapping[str, Mapping[str, Any]],
    case_ids: Iterable[str],
) -> Dict[str, Any]:
    stable_case_ids = sorted(str(case_id) for case_id in case_ids)
    case_rows = [raw_cases[case_id] for case_id in stable_case_ids if case_id in raw_cases]
    sidecar_rows = [sidecar_by_id.get(case_id, {}) for case_id in stable_case_ids]
    return {
        "schema_version": HUMAN_BENCHMARK_TEST_SPLIT_MANIFEST_SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "frozen_at": frozen_at,
        "test_case_count": len(stable_case_ids),
        "test_case_ids": stable_case_ids,
        "test_cases_sha256": _canonical_json_sha256(case_rows),
        "test_sidecar_sha256": _canonical_json_sha256(sidecar_rows),
    }


def _canonical_json_sha256(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _is_iso_timestamp(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _raw_cases_by_id(dataset: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for key in ("cases", "set_cases"):
        for item in dataset.get(key, []) if isinstance(dataset.get(key), list) else []:
            if isinstance(item, dict) and str(item.get("id", "")).strip():
                rows[str(item["id"]).strip()] = item
    return rows


def _case_issues(raw: Mapping[str, Any], sidecar: Mapping[str, Any], allowed: Mapping[str, Any]) -> List[str]:
    issues = [field for field in REQUIRED_REAL_CASE_FIELDS if not str(raw.get(field, "")).strip()]
    for field in ("benchmark_origin", "domain", "writing_context", "rights_basis"):
        value = str(raw.get(field, "")).strip()
        if value and value not in set(str(item) for item in allowed[field]):
            issues.append(f"unsupported_{field}:{value}")

    scope = str(raw.get("evidence_scope", "")).strip()
    rights_basis = str(raw.get("rights_basis", "")).strip()
    if scope == "full_text" and rights_basis not in {"open_access", "user_provided", "licensed"}:
        issues.append("full_text_requires_open_access_user_provided_or_licensed_rights")

    status = str(sidecar.get("adjudication_status", "")).strip()
    if status not in DOUBLE_ANNOTATION_STATUSES:
        issues.append("requires_dual_annotation_status")
    annotator_ids = [str(value).strip() for value in sidecar.get("annotator_ids", []) if str(value).strip()]
    if len(annotator_ids) < 2 or len(set(annotator_ids)) != len(annotator_ids):
        issues.append("requires_two_distinct_annotator_ids")
    if int(sidecar.get("annotator_count", 0) or 0) < 2:
        issues.append("requires_annotator_count_at_least_two")
    if len(sidecar.get("annotator_labels", []) or []) < 2:
        issues.append("requires_two_annotator_labels")
    review_locator = str(sidecar.get("source_locator", "")).strip()
    if not review_locator:
        issues.append("requires_review_source_locator")
    elif review_locator != str(raw.get("source_locator", "")).strip():
        issues.append("review_source_locator_mismatch")
    return sorted(set(issues))


def _count(rows: Iterable[Mapping[str, Any]], field: str) -> Dict[str, int]:
    return dict(sorted(Counter(str(row.get(field, "")).strip() or "unknown" for row in rows).items()))


def _quota_deficits(counts: Mapping[str, Any], target: Mapping[str, Any]) -> List[Dict[str, Any]]:
    deficits: List[Dict[str, Any]] = []
    total = int(counts["qualified_double_annotated_cases"])
    if total < int(target["minimum_case_count"]):
        deficits.append(
            {
                "metric": "minimum_case_count",
                "actual": total,
                "threshold": target["minimum_case_count"],
                "direction": "at_least",
            }
        )
    mapping = {
        "minimum_by_language": "qualified_by_language",
        "minimum_by_domain": "qualified_by_domain",
        "minimum_by_writing_context": "qualified_by_writing_context",
        "minimum_by_evidence_scope": "qualified_by_evidence_scope",
    }
    for target_key, count_key in mapping.items():
        actual_counts = counts[count_key]
        for value, threshold in target[target_key].items():
            actual = int(actual_counts.get(value, 0))
            if actual < int(threshold):
                deficits.append(
                    {
                        "metric": target_key,
                        "value": value,
                        "actual": actual,
                        "threshold": threshold,
                        "direction": "at_least",
                    }
                )
    return deficits


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Audit readiness of CiteGuard's real human support benchmark campaign.")
    parser.add_argument("--dataset", default="data/eval/support_eval.json")
    parser.add_argument("--label-sidecar", default="data/eval/support_eval_label_sidecar.json")
    parser.add_argument("--campaign", default="data/eval/human_support_benchmark_campaign.json")
    parser.add_argument(
        "--test-split-manifest",
        default=DEFAULT_TEST_SPLIT_MANIFEST,
        help="Optional content-addressed held-out test-split manifest created after independent review.",
    )
    parser.add_argument("--strict", action="store_true", help="Exit non-zero until the campaign is truly ready.")
    args = parser.parse_args(argv)

    try:
        dataset = load_json(args.dataset)
        sidecar = load_json(args.label_sidecar)
        campaign = load_json(args.campaign)
        manifest_path = Path(args.test_split_manifest)
        test_split_manifest = load_json(str(manifest_path)) if manifest_path.exists() else None
        report = audit_human_benchmark(
            dataset,
            sidecar,
            campaign,
            dataset_path=args.dataset,
            test_split_manifest=test_split_manifest,
        )
        report["test_split"]["manifest_path"] = str(manifest_path)
    except HumanBenchmarkCampaignError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["status"] == "ready" or not args.strict else 1


if __name__ == "__main__":
    raise SystemExit(main())
