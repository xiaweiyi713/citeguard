"""Real-source retrieval observation contracts and conservative metrics."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from citeguard.benchmark.experiments import EXPERIMENT_ARTIFACT_SCHEMA_VERSION
from citeguard.citation.normalizer import normalize_text
from citeguard.retrieval.scholarly_clients.base import MetadataSource
from citeguard.retrieval.scholarly_clients.utils import base_arxiv_id, normalize_doi
from citeguard.version import __version__
from citeguard.verification.parse import parse_citation
from citeguard.verification.verify import verify_citation


LIVE_RETRIEVAL_BENCHMARK_SCHEMA_VERSION = 1
LIVE_RETRIEVAL_CAMPAIGN_SCHEMA_VERSION = 1
LIVE_RETRIEVAL_OBSERVATION_EXPERIMENT_NAME = "live_retrieval_observation"
LIVE_RETRIEVAL_SOURCE_NAMES = ("openalex", "crossref", "arxiv", "semantic_scholar")
LIVE_RETRIEVAL_QUERY_KINDS = ("doi", "arxiv_id", "title")
REQUIRED_CASE_FIELDS = (
    "id",
    "benchmark_origin",
    "query_kind",
    "fields",
    "expected_identity",
    "ground_truth_locator",
    "rights_basis",
    "lang",
    "domain",
)


class LiveRetrievalBenchmarkError(ValueError):
    """Raised when a real-source retrieval dataset or observation is malformed."""


@dataclass(frozen=True)
class LiveRetrievalCase:
    case_id: str
    query_kind: str
    fields: Dict[str, Any]
    expected_identity: Dict[str, str]
    ground_truth_locator: str
    lang: str
    domain: str
    rights_basis: str


def live_retrieval_case_digest(case: LiveRetrievalCase) -> str:
    """Return a stable provenance digest for one real known-record probe."""

    return "sha256:" + _stable_sha256(
        {
            "id": case.case_id,
            "query_kind": case.query_kind,
            "fields": case.fields,
            "expected_identity": case.expected_identity,
            "ground_truth_locator": case.ground_truth_locator,
            "lang": case.lang,
            "domain": case.domain,
            "rights_basis": case.rights_basis,
        }
    )


def validate_live_retrieval_campaign(campaign: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate a campaign that collects real known-record retrieval probes."""

    errors: List[str] = []
    if campaign.get("schema_version") != LIVE_RETRIEVAL_CAMPAIGN_SCHEMA_VERSION:
        errors.append(f"schema_version must be {LIVE_RETRIEVAL_CAMPAIGN_SCHEMA_VERSION}")
    if not str(campaign.get("campaign_id", "")).strip():
        errors.append("campaign_id is required")
    targets = campaign.get("targets")
    if not isinstance(targets, dict):
        errors.append("targets must be an object")
        targets = {}
    minimum_case_count = targets.get("minimum_case_count")
    if not isinstance(minimum_case_count, int) or minimum_case_count < 1:
        errors.append("targets.minimum_case_count must be a positive integer")
    minimum_by_query_kind = targets.get("minimum_by_query_kind")
    if not isinstance(minimum_by_query_kind, dict) or set(minimum_by_query_kind) != set(LIVE_RETRIEVAL_QUERY_KINDS):
        errors.append("targets.minimum_by_query_kind must include doi, arxiv_id, and title")
    elif any(not isinstance(value, int) or value < 1 for value in minimum_by_query_kind.values()):
        errors.append("targets.minimum_by_query_kind values must be positive integers")
    minimum_observations = targets.get("minimum_observations_per_case")
    if not isinstance(minimum_observations, int) or minimum_observations < 1:
        errors.append("targets.minimum_observations_per_case must be a positive integer")
    allowed = campaign.get("allowed_values")
    if not isinstance(allowed, dict):
        errors.append("allowed_values must be an object")
        allowed = {}
    for field in ("benchmark_origin", "rights_basis"):
        values = allowed.get(field)
        if not isinstance(values, list) or not values or not all(str(value).strip() for value in values):
            errors.append(f"allowed_values.{field} must be a non-empty list of strings")
    if errors:
        raise LiveRetrievalBenchmarkError("; ".join(errors))
    return {"schema_version": campaign["schema_version"], "campaign_id": str(campaign["campaign_id"]), **campaign}


def audit_live_retrieval_collection(
    dataset: Mapping[str, Any], campaign: Mapping[str, Any]
) -> Dict[str, Any]:
    """Report whether a collection can support a live-source quality claim."""

    valid_campaign = validate_live_retrieval_campaign(campaign)
    if dataset.get("schema_version") != LIVE_RETRIEVAL_BENCHMARK_SCHEMA_VERSION:
        raise LiveRetrievalBenchmarkError(f"dataset schema_version must be {LIVE_RETRIEVAL_BENCHMARK_SCHEMA_VERSION}")
    if str(dataset.get("campaign_id", "")).strip() != valid_campaign["campaign_id"]:
        raise LiveRetrievalBenchmarkError("dataset campaign_id must match the campaign")
    raw_cases = dataset.get("cases")
    if not isinstance(raw_cases, list):
        raise LiveRetrievalBenchmarkError("dataset cases must be a list")

    seen_ids = set()
    cataloged_case_ids: List[str] = []
    qualified_case_ids: List[str] = []
    invalid_cases: List[Dict[str, Any]] = []
    qualified_rows: List[Mapping[str, Any]] = []
    allowed = valid_campaign["allowed_values"]
    for raw in raw_cases:
        if not isinstance(raw, dict):
            invalid_cases.append({"case_id": "", "issues": ["case_must_be_an_object"]})
            continue
        case_id = str(raw.get("id", "")).strip()
        if not case_id:
            invalid_cases.append({"case_id": "", "issues": ["id_required"]})
            continue
        if case_id in seen_ids:
            invalid_cases.append({"case_id": case_id, "issues": ["duplicate_id"]})
            continue
        seen_ids.add(case_id)
        if str(raw.get("benchmark_origin", "")).strip() not in set(allowed["benchmark_origin"]):
            continue
        cataloged_case_ids.append(case_id)
        issues = _case_issues(raw, allowed)
        if issues:
            invalid_cases.append({"case_id": case_id, "issues": issues})
            continue
        qualified_case_ids.append(case_id)
        qualified_rows.append(raw)

    counts = {
        "cataloged_real_cases": len(cataloged_case_ids),
        "qualified_real_cases": len(qualified_case_ids),
        "invalid_real_cases": len(invalid_cases),
        "qualified_by_query_kind": _count(qualified_rows, "query_kind"),
        "qualified_by_language": _count(qualified_rows, "lang"),
        "qualified_by_domain": _count(qualified_rows, "domain"),
    }
    deficits = _collection_deficits(counts, valid_campaign["targets"])
    ready = not invalid_cases and not deficits
    if ready:
        next_action = "run_timestamped_source_observations"
    elif not cataloged_case_ids:
        next_action = "collect_real_known_record_cases"
    elif invalid_cases:
        next_action = "repair_ground_truth_or_query_provenance"
    else:
        next_action = "continue_balanced_case_collection"
    return {
        "schema_version": LIVE_RETRIEVAL_CAMPAIGN_SCHEMA_VERSION,
        "ok": True,
        "campaign_id": valid_campaign["campaign_id"],
        "status": "ready" if ready else "collection_incomplete",
        "benchmark_claim_safe": ready,
        "next_action": next_action,
        "targets": valid_campaign["targets"],
        "counts": counts,
        "deficits": deficits,
        "cataloged_case_ids": cataloged_case_ids,
        "qualified_case_ids": qualified_case_ids,
        "invalid_cases": invalid_cases,
        "policy": {
            "known_real_records_only": True,
            "not_found_is_not_fabrication_evidence": True,
            "source_outages_are_inconclusive": True,
            "permanent_source_ranking_forbidden": True,
        },
    }


def load_live_retrieval_cases(dataset: Mapping[str, Any], campaign: Mapping[str, Any]) -> List[LiveRetrievalCase]:
    """Return only valid real-source cases; callers can inspect audit deficits separately."""

    audit = audit_live_retrieval_collection(dataset, campaign)
    by_id = {
        str(row.get("id", "")).strip(): row
        for row in dataset.get("cases", [])
        if isinstance(row, dict) and str(row.get("id", "")).strip()
    }
    cases = []
    for case_id in audit["qualified_case_ids"]:
        row = by_id[case_id]
        cases.append(
            LiveRetrievalCase(
                case_id=case_id,
                query_kind=str(row["query_kind"]),
                fields=dict(row["fields"]),
                expected_identity={key: str(value) for key, value in dict(row["expected_identity"]).items()},
                ground_truth_locator=str(row["ground_truth_locator"]),
                lang=str(row["lang"]),
                domain=str(row["domain"]),
                rights_basis=str(row["rights_basis"]),
            )
        )
    return cases


def load_live_retrieval_observation_artifact(path: str) -> Dict[str, Any]:
    """Load one standard observation artifact without contacting scholarly sources."""

    supplied = Path(path).expanduser()
    if supplied.is_dir():
        artifact_dir = supplied
    elif supplied.name in {"manifest.json", "result.json", "config.json"}:
        artifact_dir = supplied.parent
    else:
        raise LiveRetrievalBenchmarkError(
            "observation artifact path must be a run directory or its manifest.json/result.json/config.json"
        )
    manifest_path = artifact_dir / "manifest.json"
    manifest = _load_json_object(manifest_path)
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        raise LiveRetrievalBenchmarkError(f"{manifest_path} must contain a files object")
    result_path = _artifact_member_path(artifact_dir, files.get("result"), "result")
    config_path = _artifact_member_path(artifact_dir, files.get("config"), "config")
    return {
        "artifact_path": str(artifact_dir.resolve()),
        "manifest": manifest,
        "result": _load_json_object(result_path),
        "config": _load_json_object(config_path),
    }


def audit_live_retrieval_observations(
    dataset: Mapping[str, Any],
    campaign: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Aggregate archived observations while preserving time and failure boundaries.

    This function only reads supplied artifact payloads. It deliberately does not
    issue live requests, turn outages into misses, or generate a source ranking.
    """

    valid_campaign = validate_live_retrieval_campaign(campaign)
    collection = audit_live_retrieval_collection(dataset, valid_campaign)
    cases = {case.case_id: case for case in load_live_retrieval_cases(dataset, valid_campaign)}

    candidates: List[Dict[str, Any]] = []
    invalid_artifacts: List[Dict[str, Any]] = []
    for index, artifact in enumerate(artifacts):
        candidate, issues = _validate_observation_artifact(
            artifact,
            index=index,
            campaign_id=valid_campaign["campaign_id"],
            cases=cases,
        )
        if issues:
            invalid_artifacts.append(
                {
                    "artifact_path": _artifact_label(artifact, index),
                    "issues": issues,
                }
            )
        elif candidate is not None:
            candidates.append(candidate)

    valid_artifacts, duplicate_artifacts, conflicting_artifacts = _deduplicate_observation_artifacts(candidates)
    invalid_artifacts.extend(conflicting_artifacts)
    rows = [row for artifact in valid_artifacts for row in artifact["rows"]]
    coverage = _observation_coverage(
        collection["qualified_case_ids"],
        rows,
        minimum_observations=int(valid_campaign["targets"]["minimum_observations_per_case"]),
    )

    if collection["status"] != "ready":
        status = "collection_incomplete"
        next_action = collection["next_action"]
    elif invalid_artifacts:
        status = "observation_invalid"
        next_action = "repair_or_rearchive_invalid_observation_artifacts"
    elif coverage["case_ids_below_minimum_eligible_observations"]:
        status = "observation_incomplete"
        next_action = "capture_more_eligible_timestamped_observations"
    else:
        status = "ready"
        next_action = "monitor_time_bounded_observations"

    return {
        "schema_version": LIVE_RETRIEVAL_BENCHMARK_SCHEMA_VERSION,
        "ok": True,
        "campaign_id": valid_campaign["campaign_id"],
        "status": status,
        "benchmark_claim_safe": status == "ready",
        "next_action": next_action,
        "collection": collection,
        "artifacts": {
            "supplied_count": len(artifacts),
            "valid_count": len(valid_artifacts),
            "invalid_count": len(invalid_artifacts),
            "invalid_artifacts": invalid_artifacts,
            "duplicate_artifacts": duplicate_artifacts,
            "valid_run_ids": [artifact["run_id"] for artifact in valid_artifacts],
        },
        "counts": {
            "observation_row_count": len(rows),
            "observation_run_count": len(valid_artifacts),
            "distinct_observed_at_count": len({row["observed_at"] for row in rows}),
        },
        "coverage": coverage,
        "summary": _summarize_attempts(rows),
        "by_source": {
            source: _summarize_attempts([row for row in rows if row["source"] == source])
            for source in sorted({str(row["source"]) for row in rows})
        },
        "by_query_kind": {
            query_kind: _summarize_attempts([row for row in rows if row["query_kind"] == query_kind])
            for query_kind in LIVE_RETRIEVAL_QUERY_KINDS
            if any(row["query_kind"] == query_kind for row in rows)
        },
        "by_region": {
            region: _summarize_attempts([row for row in rows if row["observer_region"] == region])
            for region in sorted({str(row["observer_region"]) for row in rows})
        },
        "by_observation_date": {
            date: _summarize_attempts([row for row in rows if _utc_date(row["observed_at"]) == date])
            for date in sorted({_utc_date(row["observed_at"]) for row in rows})
        },
        "source_version_snapshots": _source_version_snapshots(valid_artifacts),
        "permanent_source_ranking_allowed": False,
        "interpretation": (
            "This is a time-bounded, region-labelled observation aggregate. Identity accuracy excludes source-limited "
            "attempts, and not_found for a known record remains a retrieval issue to investigate rather than "
            "fabrication evidence."
        ),
        "policy": {
            "observation_artifacts_only": True,
            "minimum_coverage_uses_distinct_eligible_timestamps": True,
            "source_limited_attempts_excluded_from_identity_accuracy": True,
            "source_outages_are_inconclusive": True,
            "permanent_source_ranking_forbidden": True,
        },
    }


def observe_live_retrieval(
    cases: Sequence[LiveRetrievalCase],
    sources: Mapping[str, MetadataSource],
    *,
    observer_region: str,
    source_versions: Optional[Mapping[str, Mapping[str, str]]] = None,
    observed_at: Optional[str] = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> Dict[str, Any]:
    """Run timestamped known-record observations without treating outages as misses."""

    region = str(observer_region).strip()
    if not region:
        raise LiveRetrievalBenchmarkError("observer_region is required for a live observation")
    if not cases:
        raise LiveRetrievalBenchmarkError("at least one qualified real-source case is required for live observation")
    if not sources:
        raise LiveRetrievalBenchmarkError("at least one live source is required for observation")
    timestamp = observed_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    if not _is_iso_timestamp(timestamp):
        raise LiveRetrievalBenchmarkError("observed_at must be an ISO-8601 timestamp with a timezone")

    rows: List[Dict[str, Any]] = []
    source_metadata: Dict[str, Dict[str, str]] = {}
    for source_name, source in sources.items():
        normalized_source = str(source_name).strip()
        if normalized_source not in LIVE_RETRIEVAL_SOURCE_NAMES:
            raise LiveRetrievalBenchmarkError(f"unsupported live observation source: {normalized_source}")
        source_metadata[normalized_source] = _source_version_metadata(
            normalized_source, source_versions.get(normalized_source) if source_versions else None
        )
        for case in cases:
            rows.append(_observe_case(case, normalized_source, source, monotonic))

    by_source = {
        source_name: _summarize_attempts([row for row in rows if row["source"] == source_name])
        for source_name in sorted(source_metadata)
    }
    by_query_kind = {
        query_kind: _summarize_attempts([row for row in rows if row["query_kind"] == query_kind])
        for query_kind in LIVE_RETRIEVAL_QUERY_KINDS
        if any(row["query_kind"] == query_kind for row in rows)
    }
    return {
        "schema_version": LIVE_RETRIEVAL_BENCHMARK_SCHEMA_VERSION,
        "observation": {
            "observed_at": timestamp,
            "observer_region": region,
            "observer_region_source": "operator_supplied",
            "source_versions": source_metadata,
            "case_count": len(cases),
            "source_count": len(source_metadata),
        },
        "summary": _summarize_attempts(rows),
        "by_source": by_source,
        "by_query_kind": by_query_kind,
        "rows": rows,
        "permanent_source_ranking_allowed": False,
        "interpretation": (
            "Identity accuracy excludes source-limited attempts. A known record returning not_found is a retrieval "
            "failure to investigate, not evidence that a citation is fabricated."
        ),
        "policy": (
            "timestamped_observations_are_environment_specific; source_outages_and_rate_limits_are_inconclusive; "
            "do_not_convert_not_found_into_fabrication_claims"
        ),
    }


def _case_issues(raw: Mapping[str, Any], allowed: Mapping[str, Any]) -> List[str]:
    issues = [field for field in REQUIRED_CASE_FIELDS if not _present(raw.get(field))]
    query_kind = str(raw.get("query_kind", "")).strip()
    if query_kind and query_kind not in LIVE_RETRIEVAL_QUERY_KINDS:
        issues.append(f"unsupported_query_kind:{query_kind}")
    if str(raw.get("rights_basis", "")).strip() not in set(str(value) for value in allowed["rights_basis"]):
        issues.append("unsupported_rights_basis")
    fields = raw.get("fields")
    if not isinstance(fields, dict):
        issues.append("fields_must_be_an_object")
    elif query_kind and not str(fields.get(query_kind, "")).strip():
        issues.append(f"query_kind_requires_fields_{query_kind}")
    identity = raw.get("expected_identity")
    if not isinstance(identity, dict) or not any(
        str(identity.get(key, "")).strip() for key in ("doi", "arxiv_id", "title")
    ):
        issues.append("expected_identity_requires_doi_arxiv_id_or_title")
    return sorted(set(issues))


def _collection_deficits(counts: Mapping[str, Any], targets: Mapping[str, Any]) -> List[Dict[str, Any]]:
    deficits: List[Dict[str, Any]] = []
    total = int(counts["qualified_real_cases"])
    if total < int(targets["minimum_case_count"]):
        deficits.append(
            {
                "metric": "minimum_case_count",
                "actual": total,
                "threshold": targets["minimum_case_count"],
                "direction": "at_least",
            }
        )
    actual_by_kind = counts["qualified_by_query_kind"]
    for query_kind, threshold in targets["minimum_by_query_kind"].items():
        actual = int(actual_by_kind.get(query_kind, 0))
        if actual < int(threshold):
            deficits.append(
                {
                    "metric": "minimum_by_query_kind",
                    "value": query_kind,
                    "actual": actual,
                    "threshold": threshold,
                    "direction": "at_least",
                }
            )
    return deficits


def _observe_case(
    case: LiveRetrievalCase,
    source_name: str,
    source: MetadataSource,
    monotonic: Callable[[], float],
) -> Dict[str, Any]:
    started = monotonic()
    try:
        result = verify_citation(parse_citation(**case.fields), source).to_dict()
        elapsed_ms = round((monotonic() - started) * 1000, 3)
    except Exception as exc:
        elapsed_ms = round((monotonic() - started) * 1000, 3)
        result = {
            "verdict": "",
            "canonical_record": None,
            "sources_checked": [source_name],
            "sources_responded": [],
            "sources_failed": [source_name],
            "source_failure_mode": "all_sources_failed",
            "source_failure_details": [
                {"source": source_name, "kind": "client_exception", "message": str(exc)}
            ],
            "outage_limited": True,
        }

    failures = [item for item in result.get("source_failure_details", []) if isinstance(item, dict)]
    source_limited = bool(
        result.get("outage_limited")
        or result.get("source_failure_mode") not in {None, "", "none"}
        or result.get("sources_failed")
    )
    identity_matches = _identity_matches(case.expected_identity, result.get("canonical_record"))
    verdict = str(result.get("verdict", ""))
    if source_limited:
        status = "source_limited"
    elif identity_matches:
        status = "resolved_correct"
    elif verdict == "not_found":
        status = "not_found"
    elif verdict == "ambiguous":
        status = "ambiguous"
    else:
        status = "resolved_incorrect"
    return {
        "case_id": case.case_id,
        "source": source_name,
        "query_kind": case.query_kind,
        "query_fields": dict(case.fields),
        "ground_truth_locator": case.ground_truth_locator,
        "lang": case.lang,
        "domain": case.domain,
        "rights_basis": case.rights_basis,
        "status": status,
        "verdict": verdict,
        "identity_match": identity_matches if not source_limited else None,
        "expected_identity": dict(case.expected_identity),
        "case_sha256": live_retrieval_case_digest(case),
        "canonical_record": result.get("canonical_record"),
        "elapsed_ms": elapsed_ms,
        "source_limited": source_limited,
        "outage_limited": bool(result.get("outage_limited")),
        "source_failure_mode": result.get("source_failure_mode", "none"),
        "source_failure_details": failures,
        "sources_checked": list(result.get("sources_checked", []) or []),
        "sources_responded": list(result.get("sources_responded", []) or []),
        "sources_failed": list(result.get("sources_failed", []) or []),
        "rate_limited": _is_rate_limited(failures),
    }


def _validate_observation_artifact(
    artifact: Mapping[str, Any],
    *,
    index: int,
    campaign_id: str,
    cases: Mapping[str, LiveRetrievalCase],
) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    if not isinstance(artifact, Mapping):
        return None, ["artifact_must_be_an_object"]
    load_error = str(artifact.get("load_error", "")).strip()
    if load_error:
        return None, [f"artifact_load_error:{load_error}"]

    errors: List[str] = []
    manifest = artifact.get("manifest")
    result = artifact.get("result")
    config = artifact.get("config")
    if not isinstance(manifest, Mapping):
        errors.append("manifest_must_be_an_object")
        manifest = {}
    if not isinstance(result, Mapping):
        errors.append("result_must_be_an_object")
        result = {}
    if not isinstance(config, Mapping):
        errors.append("config_must_be_an_object")
        config = {}

    run_id = str(manifest.get("run_id", "")).strip()
    if manifest.get("schema_version") != EXPERIMENT_ARTIFACT_SCHEMA_VERSION:
        errors.append("manifest_schema_version_mismatch")
    if manifest.get("experiment_name") != LIVE_RETRIEVAL_OBSERVATION_EXPERIMENT_NAME:
        errors.append("manifest_experiment_name_mismatch")
    if not run_id:
        errors.append("manifest_run_id_required")
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        errors.append("manifest_files_must_be_an_object")
    elif any(files.get(name) != f"{name}.json" for name in ("result", "config", "manifest")):
        errors.append("manifest_files_must_reference_standard_artifact_names")
    if config.get("script") != "scripts/observe_live_retrieval_benchmark.py":
        errors.append("config_script_mismatch")
    if result.get("schema_version") != LIVE_RETRIEVAL_BENCHMARK_SCHEMA_VERSION:
        errors.append("result_schema_version_mismatch")
    if result.get("benchmark_claim_safe") is not False:
        errors.append("single_observation_must_not_claim_benchmark_safety")
    collection = result.get("collection")
    if not isinstance(collection, Mapping) or str(collection.get("campaign_id", "")).strip() != campaign_id:
        errors.append("result_collection_campaign_id_mismatch")

    observation_payload = result.get("observation")
    if not isinstance(observation_payload, Mapping):
        return None, sorted(set(errors + ["result_observation_must_be_an_object"]))
    if observation_payload.get("schema_version") != LIVE_RETRIEVAL_BENCHMARK_SCHEMA_VERSION:
        errors.append("observation_schema_version_mismatch")
    if observation_payload.get("permanent_source_ranking_allowed") is not False:
        errors.append("observation_must_forbid_permanent_source_ranking")

    metadata = observation_payload.get("observation")
    if not isinstance(metadata, Mapping):
        return None, sorted(set(errors + ["observation_metadata_must_be_an_object"]))
    observed_at = _canonical_timestamp(str(metadata.get("observed_at", "")))
    if observed_at is None:
        errors.append("observation_observed_at_invalid")
    region = str(metadata.get("observer_region", "")).strip()
    if not region:
        errors.append("observation_observer_region_required")
    if metadata.get("observer_region_source") != "operator_supplied":
        errors.append("observation_region_must_be_operator_supplied")
    if str(config.get("observer_region", "")).strip() != region:
        errors.append("config_observer_region_mismatch")

    source_versions = metadata.get("source_versions")
    if not isinstance(source_versions, Mapping):
        errors.append("observation_source_versions_must_be_an_object")
        source_versions = {}
    source_names = sorted(str(name).strip() for name in source_versions if str(name).strip())
    if not source_names or any(name not in LIVE_RETRIEVAL_SOURCE_NAMES for name in source_names):
        errors.append("observation_source_versions_contain_unsupported_source")
    for source_name in source_names:
        source_metadata = source_versions.get(source_name)
        if not isinstance(source_metadata, Mapping):
            errors.append(f"source_version_metadata_must_be_an_object:{source_name}")
            continue
        if source_metadata.get("source") != source_name:
            errors.append(f"source_version_source_mismatch:{source_name}")
        if not str(source_metadata.get("adapter_version", "")).strip():
            errors.append(f"source_version_adapter_version_required:{source_name}")
        if not str(source_metadata.get("source_api_version", "")).strip():
            errors.append(f"source_version_api_version_required:{source_name}")
    configured_sources = config.get("sources")
    if not isinstance(configured_sources, list) or sorted(str(name).strip() for name in configured_sources) != source_names:
        errors.append("config_sources_mismatch")

    case_count = metadata.get("case_count")
    source_count = metadata.get("source_count")
    if not isinstance(case_count, int) or isinstance(case_count, bool) or case_count < 1:
        errors.append("observation_case_count_invalid")
    if not isinstance(source_count, int) or isinstance(source_count, bool) or source_count != len(source_names):
        errors.append("observation_source_count_mismatch")
    rows = observation_payload.get("rows")
    if not isinstance(rows, list):
        return None, sorted(set(errors + ["observation_rows_must_be_a_list"]))

    normalized_rows: List[Dict[str, Any]] = []
    seen_row_keys = set()
    for row_index, raw_row in enumerate(rows):
        prefix = f"rows[{row_index}]"
        if not isinstance(raw_row, Mapping):
            errors.append(f"{prefix}_must_be_an_object")
            continue
        case_id = str(raw_row.get("case_id", "")).strip()
        source_name = str(raw_row.get("source", "")).strip()
        case = cases.get(case_id)
        if case is None:
            errors.append(f"{prefix}_unknown_or_unqualified_case")
            continue
        if source_name not in source_names:
            errors.append(f"{prefix}_source_not_in_source_versions")
            continue
        row_key = (case_id, source_name)
        if row_key in seen_row_keys:
            errors.append(f"{prefix}_duplicate_case_source_row")
            continue
        seen_row_keys.add(row_key)
        row_errors_before = len(errors)
        if raw_row.get("query_kind") != case.query_kind:
            errors.append(f"{prefix}_query_kind_mismatch")
        if raw_row.get("query_fields") != case.fields:
            errors.append(f"{prefix}_query_fields_mismatch")
        if raw_row.get("expected_identity") != case.expected_identity:
            errors.append(f"{prefix}_expected_identity_mismatch")
        if raw_row.get("case_sha256") != live_retrieval_case_digest(case):
            errors.append(f"{prefix}_case_sha256_mismatch")
        for field, expected in (
            ("ground_truth_locator", case.ground_truth_locator),
            ("lang", case.lang),
            ("domain", case.domain),
            ("rights_basis", case.rights_basis),
        ):
            if raw_row.get(field) != expected:
                errors.append(f"{prefix}_{field}_mismatch")
        if raw_row.get("status") not in {
            "resolved_correct",
            "resolved_incorrect",
            "ambiguous",
            "not_found",
            "source_limited",
        }:
            errors.append(f"{prefix}_status_invalid")
        source_limited = raw_row.get("source_limited")
        if not isinstance(source_limited, bool):
            errors.append(f"{prefix}_source_limited_must_be_boolean")
        elif source_limited and raw_row.get("identity_match") is not None:
            errors.append(f"{prefix}_source_limited_identity_match_must_be_null")
        elif not source_limited and not isinstance(raw_row.get("identity_match"), bool):
            errors.append(f"{prefix}_identity_match_must_be_boolean_when_eligible")
        elapsed_ms = raw_row.get("elapsed_ms")
        if not isinstance(elapsed_ms, (int, float)) or isinstance(elapsed_ms, bool) or elapsed_ms < 0:
            errors.append(f"{prefix}_elapsed_ms_invalid")
        if not isinstance(raw_row.get("rate_limited"), bool):
            errors.append(f"{prefix}_rate_limited_must_be_boolean")
        if observed_at is not None and len(errors) == row_errors_before:
            normalized = dict(raw_row)
            normalized.update(
                {
                    "observed_at": observed_at,
                    "observer_region": region,
                    "observation_run_id": run_id,
                    "observation_artifact_path": _artifact_label(artifact, index),
                    "source_version": dict(source_versions[source_name]),
                }
            )
            normalized_rows.append(normalized)

    expected_row_count = case_count * source_count if isinstance(case_count, int) and isinstance(source_count, int) else -1
    if len(rows) != expected_row_count:
        errors.append("observation_row_count_mismatch")
    if isinstance(case_count, int) and len({str(row.get("case_id", "")).strip() for row in rows if isinstance(row, Mapping)}) != case_count:
        errors.append("observation_case_count_does_not_match_rows")
    if errors:
        return None, sorted(set(errors))
    return {
        "artifact_path": _artifact_label(artifact, index),
        "run_id": run_id,
        "artifact_sha256": "sha256:" + _stable_sha256(
            {"manifest": manifest, "config": config, "result": result}
        ),
        "rows": normalized_rows,
        "source_versions": {source: dict(source_versions[source]) for source in source_names},
    }, []


def _deduplicate_observation_artifacts(
    candidates: Sequence[Mapping[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    by_run_id: Dict[str, List[Mapping[str, Any]]] = defaultdict(list)
    for candidate in candidates:
        by_run_id[str(candidate["run_id"])].append(candidate)

    valid: List[Dict[str, Any]] = []
    duplicates: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []
    for run_id in sorted(by_run_id):
        group = sorted(by_run_id[run_id], key=lambda item: str(item["artifact_path"]))
        digests = {str(item["artifact_sha256"]) for item in group}
        if len(digests) != 1:
            for item in group:
                conflicts.append(
                    {
                        "artifact_path": str(item["artifact_path"]),
                        "issues": ["conflicting_artifacts_share_run_id"],
                    }
                )
            continue
        primary = dict(group[0])
        valid.append(primary)
        if len(group) > 1:
            duplicates.append(
                {
                    "run_id": run_id,
                    "kept_artifact_path": str(primary["artifact_path"]),
                    "duplicate_artifact_paths": [str(item["artifact_path"]) for item in group[1:]],
                }
            )
    return valid, duplicates, conflicts


def _observation_coverage(
    qualified_case_ids: Sequence[str], rows: Sequence[Mapping[str, Any]], *, minimum_observations: int
) -> Dict[str, Any]:
    rows_by_case_timestamp: Dict[Tuple[str, str], List[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        rows_by_case_timestamp[(str(row["case_id"]), str(row["observed_at"]))].append(row)

    by_case: Dict[str, Dict[str, Any]] = {}
    below_minimum: List[str] = []
    for case_id in sorted(str(case_id) for case_id in qualified_case_ids):
        timestamps = sorted(timestamp for current_case, timestamp in rows_by_case_timestamp if current_case == case_id)
        eligible_timestamps = [
            timestamp
            for timestamp in timestamps
            if any(not bool(row.get("source_limited")) for row in rows_by_case_timestamp[(case_id, timestamp)])
        ]
        source_limited_only_timestamps = [
            timestamp
            for timestamp in timestamps
            if all(bool(row.get("source_limited")) for row in rows_by_case_timestamp[(case_id, timestamp)])
        ]
        if len(eligible_timestamps) < minimum_observations:
            below_minimum.append(case_id)
        by_case[case_id] = {
            "recorded_observation_count": len(timestamps),
            "eligible_observation_count": len(eligible_timestamps),
            "source_limited_only_observation_count": len(source_limited_only_timestamps),
            "observed_at": timestamps,
            "eligible_observed_at": eligible_timestamps,
        }
    return {
        "minimum_eligible_observations_per_case": minimum_observations,
        "qualified_case_count": len(qualified_case_ids),
        "cases_meeting_minimum_eligible_observations": len(qualified_case_ids) - len(below_minimum),
        "case_ids_below_minimum_eligible_observations": below_minimum,
        "by_case": by_case,
    }


def _source_version_snapshots(artifacts: Sequence[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    snapshots: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)
    for artifact in artifacts:
        for source, metadata in artifact.get("source_versions", {}).items():
            if isinstance(metadata, Mapping):
                snapshots[str(source)][_stable_json(metadata)] = dict(metadata)
    return {
        source: [snapshots[source][key] for key in sorted(snapshots[source])]
        for source in sorted(snapshots)
    }


def _load_json_object(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise LiveRetrievalBenchmarkError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LiveRetrievalBenchmarkError(f"invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise LiveRetrievalBenchmarkError(f"{path} must contain a JSON object")
    return payload


def _artifact_member_path(artifact_dir: Path, name: Any, label: str) -> Path:
    relative = Path(str(name or "").strip())
    if not str(name or "").strip() or relative.is_absolute() or len(relative.parts) != 1 or relative.name != str(name).strip():
        raise LiveRetrievalBenchmarkError(f"artifact {label} filename must be a local filename")
    return artifact_dir / relative


def _artifact_label(artifact: Any, index: int) -> str:
    if isinstance(artifact, Mapping):
        for key in ("artifact_path", "path"):
            value = str(artifact.get(key, "")).strip()
            if value:
                return value
    return f"artifact-{index + 1}"


def _canonical_timestamp(value: str) -> Optional[str]:
    if not _is_iso_timestamp(value):
        return None
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_date(value: str) -> str:
    canonical = _canonical_timestamp(value)
    return canonical[:10] if canonical else "invalid"


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_sha256(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _identity_matches(expected: Mapping[str, str], canonical: Any) -> bool:
    if not isinstance(canonical, Mapping):
        return False
    expected_doi = normalize_doi(str(expected.get("doi", "")))
    if expected_doi and expected_doi == normalize_doi(str(canonical.get("doi", ""))):
        return True
    expected_arxiv = base_arxiv_id(str(expected.get("arxiv_id", "")))
    if expected_arxiv and expected_arxiv == base_arxiv_id(str(canonical.get("arxiv_id", ""))):
        return True
    expected_title = normalize_text(str(expected.get("title", "")))
    return bool(expected_title and expected_title == normalize_text(str(canonical.get("title", ""))))


def _summarize_attempts(rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    latencies = sorted(float(row["elapsed_ms"]) for row in rows if isinstance(row.get("elapsed_ms"), (int, float)))
    eligible = [row for row in rows if not row.get("source_limited")]
    correct = sum(row.get("identity_match") is True for row in eligible)
    failure_kinds = Counter(
        str(detail.get("kind", "unknown"))
        for row in rows
        for detail in row.get("source_failure_details", []) or []
        if isinstance(detail, Mapping)
    )
    return {
        "attempt_count": len(rows),
        "identity_accuracy_eligible_count": len(eligible),
        "identity_correct_count": correct,
        "identity_accuracy": round(correct / len(eligible), 4) if eligible else None,
        "not_found_count": sum(row.get("status") == "not_found" for row in rows),
        "ambiguous_count": sum(row.get("status") == "ambiguous" for row in rows),
        "resolved_incorrect_count": sum(row.get("status") == "resolved_incorrect" for row in rows),
        "source_limited_count": sum(bool(row.get("source_limited")) for row in rows),
        "outage_limited_count": sum(bool(row.get("outage_limited")) for row in rows),
        "rate_limited_count": sum(bool(row.get("rate_limited")) for row in rows),
        "failure_kind_counts": dict(sorted(failure_kinds.items())),
        "latency_ms": {
            "count": len(latencies),
            "mean": round(sum(latencies) / len(latencies), 3) if latencies else None,
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": round(max(latencies), 3) if latencies else None,
        },
    }


def _source_version_metadata(source_name: str, supplied: Optional[Mapping[str, str]]) -> Dict[str, str]:
    metadata = {
        "source": source_name,
        "adapter_version": __version__,
        "source_api_version": "not_disclosed",
    }
    if supplied:
        for key in ("adapter_version", "source_api_version", "endpoint_version"):
            value = str(supplied.get(key, "")).strip()
            if value:
                metadata[key] = value
    return metadata


def _is_rate_limited(failures: Iterable[Mapping[str, Any]]) -> bool:
    for detail in failures:
        if str(detail.get("kind", "")).lower() == "rate_limited":
            return True
        if detail.get("status_code") == 429:
            return True
    return False


def _percentile(values: Sequence[float], fraction: float) -> Optional[float]:
    if not values:
        return None
    index = max(0, math.ceil(len(values) * fraction) - 1)
    return round(float(values[index]), 3)


def _count(rows: Iterable[Mapping[str, Any]], field: str) -> Dict[str, int]:
    return dict(sorted(Counter(str(row.get(field, "")).strip() or "unknown" for row in rows).items()))


def _present(value: Any) -> bool:
    if isinstance(value, Mapping):
        return bool(value)
    return bool(str(value).strip())


def _is_iso_timestamp(value: str) -> bool:
    text = value.strip()
    if not text:
        return False
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None
