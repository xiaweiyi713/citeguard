"""Retrieval-source ablation fixtures and conservative evaluation reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource, MultiSourceMetadataSource
from citeguard.retrieval.scholarly_clients.base import MetadataSource
from citeguard.verification.parse import parse_citation
from citeguard.verification.verify import verify_citation


RETRIEVAL_ABLATION_SCHEMA_VERSION = 1
RETRIEVAL_ABLATION_SOURCE_NAMES = (
    "in_memory",
    "openalex",
    "crossref",
    "arxiv",
    "semantic_scholar",
    "multi_source",
)
ALLOWED_EXPECTED_VERDICTS = frozenset({"verified", "metadata_mismatch", "not_found", "ambiguous"})


@dataclass(frozen=True)
class RetrievalAblationCase:
    case_id: str
    expected: str
    fields: Dict[str, Any]
    note: str = ""


@dataclass(frozen=True)
class RetrievalAblationDataset:
    schema_version: int
    snapshot_id: str
    snapshot_policy: Dict[str, Any]
    snapshot_sources: tuple[str, ...]
    multi_source_members: tuple[str, ...]
    records: tuple[Dict[str, Any], ...]
    cases: tuple[RetrievalAblationCase, ...]


class SnapshotMetadataSource(InMemoryMetadataSource):
    """Named in-memory adapter that preserves strict identifier authority paths."""

    def __init__(self, records: List[CitationRecord], name: str) -> None:
        super().__init__(records)
        self.name = name

    def lookup_identifier(self, candidate: CitationRecord) -> Optional[CitationRecord]:
        if self.name == "crossref" and candidate.doi:
            return self.lookup(candidate)
        if self.name == "arxiv" and candidate.arxiv_id:
            return self.lookup(candidate)
        return None


def load_retrieval_ablation_dataset(path: str) -> RetrievalAblationDataset:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    validate_retrieval_ablation_dataset(payload)
    return RetrievalAblationDataset(
        schema_version=int(payload["schema_version"]),
        snapshot_id=str(payload["snapshot_id"]),
        snapshot_policy=dict(payload["snapshot_policy"]),
        snapshot_sources=tuple(str(item) for item in payload["snapshot_sources"]),
        multi_source_members=tuple(str(item) for item in payload["multi_source_members"]),
        records=tuple(dict(item) for item in payload["records"]),
        cases=tuple(
            RetrievalAblationCase(
                case_id=str(item["id"]),
                expected=str(item["expected"]),
                fields=dict(item["fields"]),
                note=str(item.get("note", "")),
            )
            for item in payload["cases"]
        ),
    )


def validate_retrieval_ablation_dataset(payload: Mapping[str, Any]) -> None:
    if payload.get("schema_version") != RETRIEVAL_ABLATION_SCHEMA_VERSION:
        raise ValueError("retrieval source eval schema_version must be 1")
    if not str(payload.get("snapshot_id", "")).strip():
        raise ValueError("retrieval source eval snapshot_id is required")
    policy = payload.get("snapshot_policy")
    if not isinstance(policy, dict) or "not a captured live-source benchmark" not in str(policy.get("notes", "")):
        raise ValueError("snapshot policy must prohibit live-source benchmark claims")
    snapshot_sources = payload.get("snapshot_sources")
    if not isinstance(snapshot_sources, list) or snapshot_sources != list(RETRIEVAL_ABLATION_SOURCE_NAMES[:-1]):
        raise ValueError("snapshot_sources must contain the stable five-source offline matrix")
    multi_members = payload.get("multi_source_members")
    if not isinstance(multi_members, list) or multi_members != list(RETRIEVAL_ABLATION_SOURCE_NAMES[1:-1]):
        raise ValueError("multi_source_members must contain the four live-adapter names")
    records = payload.get("records")
    if not isinstance(records, list) or len(records) < 3:
        raise ValueError("retrieval source eval requires at least three real records")
    record_ids = [str(record.get("citation_id", "")) for record in records if isinstance(record, dict)]
    if len(record_ids) != len(records) or len(set(record_ids)) != len(record_ids) or not all(record_ids):
        raise ValueError("retrieval source eval record ids must be present and unique")
    for record in records:
        available = record.get("available_in") if isinstance(record, dict) else None
        if not isinstance(available, list) or "in_memory" not in available:
            raise ValueError("every retrieval snapshot record must be available in in_memory")
        unknown = sorted(set(str(item) for item in available) - set(snapshot_sources))
        if unknown:
            raise ValueError(f"retrieval snapshot record has unknown sources: {unknown}")
        if not record.get("title") or not record.get("authors") or record.get("year") is None:
            raise ValueError("retrieval snapshot records require title, authors, and year")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) < 8:
        raise ValueError("retrieval source eval requires at least eight cases")
    case_ids = [str(case.get("id", "")) for case in cases if isinstance(case, dict)]
    if len(case_ids) != len(cases) or len(set(case_ids)) != len(case_ids) or not all(case_ids):
        raise ValueError("retrieval source eval case ids must be present and unique")
    expected = [str(case.get("expected", "")) for case in cases]
    if any(item not in ALLOWED_EXPECTED_VERDICTS for item in expected):
        raise ValueError("retrieval source eval contains an unsupported expected verdict")
    if expected.count("not_found") < 2 or "metadata_mismatch" not in expected or "verified" not in expected:
        raise ValueError("retrieval source eval must cover verified, mismatch, and multiple not-found cases")
    for case in cases:
        fields = case.get("fields") if isinstance(case, dict) else None
        if not isinstance(fields, dict) or not any(fields.get(key) for key in ("title", "doi", "arxiv_id", "raw_text")):
            raise ValueError("every retrieval source eval case needs citation input")


def build_offline_snapshot_sources(dataset: RetrievalAblationDataset) -> Dict[str, MetadataSource]:
    sources: Dict[str, MetadataSource] = {}
    for source_name in dataset.snapshot_sources:
        records = [
            _snapshot_record(record, source_name, dataset.snapshot_id)
            for record in dataset.records
            if source_name in record.get("available_in", [])
        ]
        sources[source_name] = SnapshotMetadataSource(records, source_name)
    sources["multi_source"] = MultiSourceMetadataSource(
        [sources[name] for name in dataset.multi_source_members]
    )
    return sources


def run_retrieval_source_ablation(
    dataset: RetrievalAblationDataset,
    sources: Mapping[str, MetadataSource],
    source_names: Optional[Iterable[str]] = None,
    *,
    mode: str = "offline_snapshot",
) -> Dict[str, Any]:
    if mode not in {"offline_snapshot", "live"}:
        raise ValueError("retrieval source ablation mode must be offline_snapshot or live")
    names = _unique_source_names(source_names or RETRIEVAL_ABLATION_SOURCE_NAMES)
    runs: List[Dict[str, Any]] = []
    comparison: List[Dict[str, Any]] = []
    for name in names:
        source = sources.get(name)
        run: Dict[str, Any]
        if source is None:
            run = {
                "source": name,
                "status": "unavailable",
                "reason": "source_not_configured",
                "results": [],
                "metrics": None,
                "quality_comparison_allowed": False,
                "regression_comparison_allowed": False,
            }
        else:
            run = _run_source(dataset.cases, name, source, mode=mode)
        runs.append(run)
        comparison.append(_source_comparison_row(run))

    completed = [run["source"] for run in runs if run["status"] == "completed"]
    source_limited = [run["source"] for run in runs if run["status"] == "source_limited"]
    unavailable = [run["source"] for run in runs if run["status"] == "unavailable"]
    return {
        "schema_version": RETRIEVAL_ABLATION_SCHEMA_VERSION,
        "axis": "retrieval_sources",
        "mode": mode,
        "snapshot_id": dataset.snapshot_id,
        "snapshot_policy": dict(dataset.snapshot_policy),
        "observed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z") if mode == "live" else None,
        "requested_sources": names,
        "completed_sources": completed,
        "source_limited_sources": source_limited,
        "unavailable_sources": unavailable,
        "requested_count": len(names),
        "completed_count": len(completed),
        "source_limited_count": len(source_limited),
        "unavailable_count": len(unavailable),
        "matrix_complete": len(completed) + len(source_limited) == len(names),
        "deterministic": mode == "offline_snapshot",
        "permanent_source_ranking_allowed": False,
        "comparison": comparison,
        "runs": runs,
        "interpretation": (
            "Offline snapshots test adapter and aggregation regressions; live rows are timestamped observations. "
            "Neither mode establishes a permanent scholarly-source ranking."
        ),
        "policy": (
            "not_found_is_unresolved_not_fabrication; source_outages_are_inconclusive; "
            "live_source_metrics_are_not_reproducible_benchmark_evidence"
        ),
    }


def compute_retrieval_ablation_metrics(
    expected_and_predicted: Sequence[tuple[str, str]],
) -> Dict[str, Any]:
    total = len(expected_and_predicted)
    correct = sum(expected == predicted for expected, predicted in expected_and_predicted)
    metrics: Dict[str, Any] = {
        "case_count": total,
        "accuracy": round(correct / total, 4) if total else 0.0,
    }
    for label in ("verified", "metadata_mismatch", "not_found", "ambiguous"):
        tp = sum(expected == label and predicted == label for expected, predicted in expected_and_predicted)
        fp = sum(expected != label and predicted == label for expected, predicted in expected_and_predicted)
        fn = sum(expected == label and predicted != label for expected, predicted in expected_and_predicted)
        metrics[f"{label}_precision"] = round(tp / (tp + fp), 4) if tp + fp else 0.0
        metrics[f"{label}_recall"] = round(tp / (tp + fn), 4) if tp + fn else 0.0
    real_rows = [(expected, predicted) for expected, predicted in expected_and_predicted if expected != "not_found"]
    real_not_found = sum(predicted == "not_found" for _, predicted in real_rows)
    metrics["real_citation_not_found_rate"] = round(real_not_found / len(real_rows), 4) if real_rows else 0.0
    verified_rows = [(expected, predicted) for expected, predicted in expected_and_predicted if expected == "verified"]
    verified_not_found = sum(predicted == "not_found" for _, predicted in verified_rows)
    metrics["verified_not_found_rate"] = (
        round(verified_not_found / len(verified_rows), 4) if verified_rows else 0.0
    )
    return metrics


def _run_source(
    cases: Sequence[RetrievalAblationCase],
    name: str,
    source: MetadataSource,
    *,
    mode: str,
) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    pairs: List[tuple[str, str]] = []
    for case in cases:
        result = verify_citation(parse_citation(**case.fields), source).to_dict()
        pairs.append((case.expected, str(result.get("verdict", ""))))
        results.append(
            {
                "case_id": case.case_id,
                "expected": case.expected,
                "predicted": result.get("verdict"),
                "correct": case.expected == result.get("verdict"),
                "note": case.note,
                "sources_checked": list(result.get("sources_checked", []) or []),
                "sources_responded": list(result.get("sources_responded", []) or []),
                "sources_failed": list(result.get("sources_failed", []) or []),
                "source_failure_mode": result.get("source_failure_mode", "none"),
                "source_failure_details": list(result.get("source_failure_details", []) or []),
                "outage_limited": bool(result.get("outage_limited")),
                "confidence": result.get("confidence"),
                "identifier_lookup": result.get("identifier_lookup"),
            }
        )
    source_limited_case_ids = [
        row["case_id"]
        for row in results
        if row["source_failure_mode"] != "none" or row["outage_limited"]
    ]
    failed_sources = sorted({failed for row in results for failed in row["sources_failed"]})
    status = "source_limited" if source_limited_case_ids or failed_sources else "completed"
    return {
        "source": name,
        "status": status,
        "reason": "live_source_failures_or_timeouts" if status == "source_limited" else "",
        "metrics": compute_retrieval_ablation_metrics(pairs),
        "quality_comparison_allowed": False,
        "regression_comparison_allowed": mode == "offline_snapshot" and status == "completed",
        "source_limited_case_ids": source_limited_case_ids,
        "sources_failed": failed_sources,
        "failure_mode_counts": {
            failure_mode: sum(row["source_failure_mode"] == failure_mode for row in results)
            for failure_mode in ("none", "partial_outage", "all_sources_failed")
        },
        "not_found_case_ids": [row["case_id"] for row in results if row["predicted"] == "not_found"],
        "real_citation_not_found_case_ids": [
            row["case_id"]
            for row in results
            if row["expected"] != "not_found" and row["predicted"] == "not_found"
        ],
        "results": results,
    }


def _source_comparison_row(run: Dict[str, Any]) -> Dict[str, Any]:
    row = {
        "source": run["source"],
        "status": run["status"],
        "quality_comparison_allowed": bool(run.get("quality_comparison_allowed")),
        "regression_comparison_allowed": bool(run.get("regression_comparison_allowed")),
        "source_limited_case_ids": list(run.get("source_limited_case_ids", []) or []),
        "sources_failed": list(run.get("sources_failed", []) or []),
    }
    metrics = run.get("metrics")
    if isinstance(metrics, dict):
        row.update(metrics)
        row["real_citation_not_found_case_ids"] = list(
            run.get("real_citation_not_found_case_ids", []) or []
        )
    return row


def _snapshot_record(record: Mapping[str, Any], source_name: str, snapshot_id: str) -> CitationRecord:
    return CitationRecord(
        citation_id=f"{source_name}:{record['citation_id']}",
        title=str(record.get("title", "")),
        authors=[str(author) for author in record.get("authors", [])],
        year=int(record["year"]) if record.get("year") is not None else None,
        venue=str(record.get("venue", "")),
        abstract=str(record.get("abstract", "")),
        doi=str(record.get("doi", "")),
        arxiv_id=str(record.get("arxiv_id", "")),
        url=str(record.get("url", "")),
        source=source_name,
        metadata={
            "snapshot_id": snapshot_id,
            "snapshot_source": source_name,
            "snapshot_policy": "deterministic_adapter_fixture_not_live_source_capture",
        },
    )


def _unique_source_names(names: Iterable[str]) -> List[str]:
    result: List[str] = []
    for name in names:
        normalized = str(name).strip().lower().replace("-", "_")
        if normalized not in RETRIEVAL_ABLATION_SOURCE_NAMES:
            raise ValueError(f"unknown retrieval ablation source: {normalized}")
        if normalized not in result:
            result.append(normalized)
    if not result:
        raise ValueError("at least one retrieval ablation source is required")
    return result
