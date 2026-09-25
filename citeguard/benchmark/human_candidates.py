"""Candidate collection and blinded annotation contracts for human support data.

Candidate rows intentionally have no gold label.  They are a staging format
between lawful public evidence collection and the existing double-annotation
benchmark sidecar; keeping the formats separate prevents an unreviewed model
or maintainer label from being mistaken for a human benchmark label.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from citeguard.verification.support_eval import ALLOWED_SUPPORT_LABELS


HUMAN_SUPPORT_CANDIDATE_SCHEMA_VERSION = 1
HUMAN_SUPPORT_CANDIDATE_PACKET_SCHEMA_VERSION = 3
HUMAN_SUPPORT_CANDIDATE_DATASET_TYPE = "human_support_candidates"
HUMAN_SUPPORT_CANDIDATE_PACKET_TYPE = "human_support_candidate_annotation_packet"
ALLOWED_EVIDENCE_SCOPES = {"title", "abstract", "metadata", "full_text", "mixed"}
ALLOWED_CASE_TYPES = {
    "direct_support",
    "weak_support",
    "hard_negative",
    "unrelated_negative",
    "contradiction",
    "full_text_required",
    "metadata_only",
}
ALLOWED_WRITING_CONTEXTS = {"research_article", "literature_review"}
ALLOWED_RIGHTS_BASES = {"public_abstract", "open_access", "user_provided", "licensed"}
ALLOWED_SPLITS = {"train", "dev", "test"}
ALLOWED_ANNOTATION_STATUSES = {
    "not_human_reviewed",
    "single_annotator",
    "dual_annotator_agreed",
    "dual_annotator_disagreement",
}
FORBIDDEN_LABEL_KEYS = {"gold", "dataset_gold", "predicted", "adjudicated_label"}
BLINDED_PACKET_FIELDS = {
    "schema_version", "packet_type", "dataset_type", "review_phase", "packet_purpose",
    "case_count", "label_options", "hidden_fields", "instructions", "cases",
    "packet_id", "packet_digest", "candidate_digest",
}
BLINDED_PACKET_ROW_FIELDS = {
    "case_id", "claim", "evidence", "evidence_scope", "evidence_locator",
    "source_locator", "lang", "domain", "writing_context", "packet_case_index",
    "annotation", "packet_id", "packet_digest",
}


class HumanSupportCandidateError(ValueError):
    """Raised when candidate or annotation packet data violates its contract."""


def build_human_support_candidate_dataset(
    retrieval_dataset: Mapping[str, Any],
    claim_manifest: Mapping[str, Any],
    *,
    collected_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build unlabeled support candidates from live-record metadata snapshots."""

    cases_by_id = _retrieval_cases_by_id(retrieval_dataset)
    raw_claims = claim_manifest.get("claims")
    if not isinstance(raw_claims, list) or not raw_claims:
        raise HumanSupportCandidateError("claim manifest must contain a non-empty claims list")
    timestamp = collected_at or _utc_now()
    if not _is_iso_timestamp(timestamp):
        raise HumanSupportCandidateError("collected_at must be an ISO-8601 timestamp with a timezone")

    output_cases: List[Dict[str, Any]] = []
    seen_ids = set()
    for index, raw in enumerate(raw_claims, start=1):
        if not isinstance(raw, Mapping):
            raise HumanSupportCandidateError(f"claims[{index}] must be an object")
        case_id = str(raw.get("id", "")).strip()
        source_case_id = str(raw.get("source_case_id", "")).strip()
        claim = str(raw.get("claim", "")).strip()
        if not case_id or case_id in seen_ids:
            raise HumanSupportCandidateError(f"claims[{index}] requires a unique id")
        if not source_case_id or source_case_id not in cases_by_id:
            raise HumanSupportCandidateError(f"claims[{index}] references an unknown source_case_id")
        if not claim:
            raise HumanSupportCandidateError(f"claims[{index}].claim is required")
        source_case = cases_by_id[source_case_id]
        snapshot = source_case.get("metadata_snapshot")
        if not isinstance(snapshot, Mapping):
            raise HumanSupportCandidateError(
                f"source case {source_case_id} has no metadata_snapshot; refresh the live catalog first"
            )
        evidence_scope = str(raw.get("evidence_scope", "abstract")).strip()
        rights_basis = str(raw.get("rights_basis", "public_abstract")).strip()
        evidence, evidence_locator = _resolve_evidence(raw, snapshot, source_case, evidence_scope, rights_basis)
        language = str(raw.get("lang", source_case.get("lang", ""))).strip()
        domain = str(raw.get("domain", source_case.get("domain", ""))).strip()
        writing_context = str(raw.get("writing_context", "")).strip()
        case_type = str(raw.get("case_type", "")).strip()
        split = str(raw.get("split", "")).strip()
        _validate_candidate_dimensions(
            language=language,
            domain=domain,
            writing_context=writing_context,
            case_type=case_type,
            split=split,
            evidence_scope=evidence_scope,
            rights_basis=rights_basis,
        )
        source_locator = str(raw.get("source_locator", source_case.get("ground_truth_locator", ""))).strip()
        if not source_locator:
            raise HumanSupportCandidateError(f"claims[{index}] requires a source_locator")
        candidate = {
            "id": case_id,
            "benchmark_origin": "real_source",
            "claim": claim,
            "evidence": evidence,
            "source_case_id": source_case_id,
            "source_locator": source_locator,
            "evidence_locator": evidence_locator,
            "rights_basis": rights_basis,
            "lang": language,
            "domain": domain,
            "writing_context": writing_context,
            "evidence_scope": evidence_scope,
            "case_type": case_type,
            "split": split,
            "label_source": "pending_human_review",
            "annotation_status": "not_human_reviewed",
            "annotations": [],
            "candidate_provenance": {
                "source_case_id": source_case_id,
                "source_record": source_case.get("curation", {}),
                "metadata_snapshot_sha256": _json_digest(snapshot),
                "collected_at": timestamp,
                "public_metadata_only": rights_basis == "public_abstract",
            },
        }
        output_cases.append(candidate)
        seen_ids.add(case_id)

    return {
        "schema_version": HUMAN_SUPPORT_CANDIDATE_SCHEMA_VERSION,
        "dataset_type": HUMAN_SUPPORT_CANDIDATE_DATASET_TYPE,
        "campaign_id": str(claim_manifest.get("campaign_id", "citeguard-human-support-v1")),
        "label_policy": {
            "gold_labels_included": False,
            "label_source": "pending_human_review",
            "human_double_annotation_required": True,
            "synthetic_or_model_labels_do_not_count": True,
            "lawful_evidence_only": True,
        },
        "collection": {
            "collected_at": timestamp,
            "source_dataset": str(claim_manifest.get("source_dataset", "")),
            "case_count": len(output_cases),
        },
        "cases": output_cases,
    }


def build_blinded_candidate_packet(
    candidate_dataset: Mapping[str, Any],
    *,
    review_phase: str = "first_review",
    packet_purpose: str = "independent support annotation",
    case_ids: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Build a packet that contains evidence but no candidate labels or gold."""

    validate_candidate_dataset(candidate_dataset)
    selected = set(str(case_id).strip() for case_id in case_ids or [] if str(case_id).strip())
    rows = [
        row
        for row in candidate_dataset["cases"]
        if not selected or str(row["id"]) in selected
    ]
    if selected and selected != {str(row["id"]) for row in rows}:
        raise HumanSupportCandidateError("selected case_ids include unknown candidates")
    rows = sorted(rows, key=lambda row: _blinded_case_id(candidate_dataset, row))
    packet_cases = []
    for index, row in enumerate(rows, start=1):
        packet_cases.append(
            {
                "case_id": _blinded_case_id(candidate_dataset, row),
                "claim": row["claim"],
                "evidence": row["evidence"],
                "evidence_scope": row["evidence_scope"],
                "evidence_locator": row["evidence_locator"],
                "source_locator": row["source_locator"],
                "lang": row["lang"],
                "domain": row["domain"],
                "writing_context": row["writing_context"],
                "packet_case_index": index,
                "annotation": _empty_annotation(),
            }
        )
    packet = {
        "schema_version": HUMAN_SUPPORT_CANDIDATE_PACKET_SCHEMA_VERSION,
        "packet_type": HUMAN_SUPPORT_CANDIDATE_PACKET_TYPE,
        "dataset_type": HUMAN_SUPPORT_CANDIDATE_DATASET_TYPE,
        "candidate_digest": _candidate_content_digest(candidate_dataset, rows),
        "review_phase": str(review_phase).strip() or "first_review",
        "packet_purpose": str(packet_purpose).strip() or "independent support annotation",
        "case_count": len(packet_cases),
        "label_options": sorted(ALLOWED_SUPPORT_LABELS),
        "hidden_fields": [
            "gold", "dataset_gold", "candidate.id", "candidate.case_type",
            "candidate.split", "candidate.annotations", "annotation_status",
        ],
        "instructions": [
            "Label independently before discussion.",
            "Use only the claim, evidence, evidence_scope, and evidence_locator shown.",
            "Do not infer support from citation fame, venue, topical similarity, or source availability.",
            "Use insufficient_evidence when the claim needs evidence outside the supplied lawful scope.",
            "Return one annotation object per case and preserve all packet identity fields.",
        ],
        "cases": packet_cases,
    }
    packet["packet_id"] = _packet_id(packet)
    packet["packet_digest"] = _packet_digest(packet)
    for row in packet_cases:
        row["packet_id"] = packet["packet_id"]
        row["packet_digest"] = packet["packet_digest"]
    return packet


def validate_candidate_dataset(dataset: Mapping[str, Any]) -> Dict[str, Any]:
    """Validate the unlabeled candidate staging format."""

    errors: List[str] = []
    if dataset.get("schema_version") != HUMAN_SUPPORT_CANDIDATE_SCHEMA_VERSION:
        errors.append("schema_version mismatch")
    if dataset.get("dataset_type") != HUMAN_SUPPORT_CANDIDATE_DATASET_TYPE:
        errors.append("dataset_type mismatch")
    if not str(dataset.get("campaign_id", "")).strip():
        errors.append("campaign_id is required")
    label_policy = dataset.get("label_policy")
    required_policy = {
        "gold_labels_included": False,
        "human_double_annotation_required": True,
        "synthetic_or_model_labels_do_not_count": True,
        "lawful_evidence_only": True,
    }
    if not isinstance(label_policy, Mapping):
        errors.append("label_policy must be an object")
    else:
        for field, expected in required_policy.items():
            if label_policy.get(field) is not expected:
                errors.append(f"label_policy.{field} must be {str(expected).lower()}")
        if str(label_policy.get("label_source", "")).strip() != "pending_human_review":
            errors.append("label_policy.label_source must be pending_human_review")
    collection = dataset.get("collection")
    if not isinstance(collection, Mapping):
        errors.append("collection must be an object")
    else:
        collected_at = str(collection.get("collected_at", "")).strip()
        if not _is_iso_timestamp(collected_at):
            errors.append("collection.collected_at must be an ISO-8601 timestamp with a timezone")
    raw_cases = dataset.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        errors.append("cases must be a non-empty list")
        raw_cases = []
    if isinstance(collection, Mapping) and collection.get("case_count") != len(raw_cases):
        errors.append("collection.case_count must match cases")
    seen = set()
    for index, row in enumerate(raw_cases, start=1):
        if not isinstance(row, Mapping):
            errors.append(f"cases[{index}] must be an object")
            continue
        case_id = str(row.get("id", "")).strip()
        if not case_id or case_id in seen:
            errors.append(f"cases[{index}] requires a unique id")
        seen.add(case_id)
        if row.get("benchmark_origin") != "real_source":
            errors.append(f"cases[{case_id or index}] benchmark_origin must be real_source")
        if row.get("label_source") != "pending_human_review":
            errors.append(f"cases[{case_id or index}] label_source must be pending_human_review")
        if str(row.get("annotation_status", "")).strip() not in ALLOWED_ANNOTATION_STATUSES:
            errors.append(f"cases[{case_id or index}] has an unsupported annotation_status")
        if not isinstance(row.get("annotations"), list):
            errors.append(f"cases[{case_id or index}] annotations must be a list")
        provenance = row.get("candidate_provenance")
        if not isinstance(provenance, Mapping):
            errors.append(f"cases[{case_id or index}] candidate_provenance must be an object")
        else:
            if str(provenance.get("source_case_id", "")).strip() != str(row.get("source_case_id", "")).strip():
                errors.append(f"cases[{case_id or index}] provenance source_case_id differs from candidate")
            if not _is_unprefixed_sha256(str(provenance.get("metadata_snapshot_sha256", "")).strip()):
                errors.append(f"cases[{case_id or index}] metadata_snapshot_sha256 is missing or malformed")
            if not _is_iso_timestamp(str(provenance.get("collected_at", "")).strip()):
                errors.append(f"cases[{case_id or index}] provenance collected_at is invalid")
            if not isinstance(provenance.get("source_record"), Mapping):
                errors.append(f"cases[{case_id or index}] provenance source_record must be an object")
            if not isinstance(provenance.get("public_metadata_only"), bool):
                errors.append(f"cases[{case_id or index}] provenance public_metadata_only must be boolean")
        for field_name in (
            "claim",
            "evidence",
            "source_locator",
            "evidence_locator",
            "lang",
            "domain",
            "writing_context",
            "evidence_scope",
            "case_type",
            "split",
            "rights_basis",
        ):
            if not str(row.get(field_name, "")).strip():
                errors.append(f"cases[{case_id or index}] missing {field_name}")
        if "gold" in row or "dataset_gold" in row:
            errors.append(f"cases[{case_id or index}] must not contain a gold label")
        try:
            _validate_candidate_dimensions(
                language=str(row.get("lang", "")),
                domain=str(row.get("domain", "")),
                writing_context=str(row.get("writing_context", "")),
                case_type=str(row.get("case_type", "")),
                split=str(row.get("split", "")),
                evidence_scope=str(row.get("evidence_scope", "")),
                rights_basis=str(row.get("rights_basis", "")),
            )
        except HumanSupportCandidateError as exc:
            errors.append(f"cases[{case_id or index}] {exc}")
    errors.extend(f"forbidden label field at {path}" for path in _forbidden_label_key_paths(dataset))
    if errors:
        raise HumanSupportCandidateError("; ".join(errors))
    return {"ok": True, "case_count": len(raw_cases), "case_ids": sorted(seen)}


def validate_blinded_candidate_packet(
    candidate_dataset: Mapping[str, Any],
    packet: Mapping[str, Any],
    *,
    allow_completed_annotations: bool = False,
) -> Dict[str, Any]:
    """Validate a packet against its candidate set before assignment or merge."""

    validate_candidate_dataset(candidate_dataset)
    errors: List[str] = []
    if packet.get("schema_version") != HUMAN_SUPPORT_CANDIDATE_PACKET_SCHEMA_VERSION:
        errors.append("packet schema_version mismatch")
    if packet.get("packet_type") != HUMAN_SUPPORT_CANDIDATE_PACKET_TYPE:
        errors.append("packet_type mismatch")
    if "gold" in packet or "dataset_gold" in packet:
        errors.append("packet contains a gold label")
    unexpected_packet_fields = set(packet) - BLINDED_PACKET_FIELDS
    if unexpected_packet_fields:
        errors.append("packet exposes unexpected fields: " + ", ".join(sorted(unexpected_packet_fields)))
    if not str(packet.get("review_phase", "")).strip():
        errors.append("packet review_phase is required")
    if not str(packet.get("packet_purpose", "")).strip():
        errors.append("packet packet_purpose is required")
    candidate_digest = str(packet.get("candidate_digest", "")).strip()
    if not candidate_digest.startswith("sha256:") or not _is_unprefixed_sha256(candidate_digest[7:]):
        errors.append("packet candidate_digest must be a SHA-256 digest")
    label_options = packet.get("label_options")
    if (
        not isinstance(label_options, list)
        or not all(isinstance(option, str) for option in label_options)
        or set(label_options) != set(ALLOWED_SUPPORT_LABELS)
    ):
        errors.append("packet label_options must exactly match the support label vocabulary")
    hidden_fields = packet.get("hidden_fields")
    required_hidden_fields = {
        "gold", "dataset_gold", "candidate.id", "candidate.case_type",
        "candidate.split", "candidate.annotations", "annotation_status",
    }
    if (
        not isinstance(hidden_fields, list)
        or not all(isinstance(field, str) for field in hidden_fields)
        or not required_hidden_fields.issubset(set(hidden_fields))
    ):
        errors.append("packet hidden_fields must declare all blinded label fields")
    if not isinstance(packet.get("instructions"), list) or not packet.get("instructions"):
        errors.append("packet instructions must be a non-empty list")
    packet_id = str(packet.get("packet_id", "")).strip()
    expected_digest = str(packet.get("packet_digest", "")).strip()
    if not packet_id or packet_id != _packet_id(packet):
        errors.append("packet_id does not match blinded packet content")
    packet_cases = packet.get("cases")
    if not isinstance(packet_cases, list):
        errors.append("packet cases must be a list")
        packet_cases = []
    elif (
        not isinstance(packet.get("case_count"), int)
        or isinstance(packet.get("case_count"), bool)
        or packet.get("case_count") != len(packet_cases)
    ):
        errors.append("packet case_count does not match cases")
    candidate_by_id = {
        _blinded_case_id(candidate_dataset, row): row for row in candidate_dataset["cases"]
    }
    if len(candidate_by_id) != len(candidate_dataset["cases"]):
        errors.append("blinded case id collision")
    packet_ids = []
    for index, row in enumerate(packet_cases, start=1):
        if not isinstance(row, Mapping):
            errors.append(f"packet cases[{index}] must be an object")
            continue
        case_id = str(row.get("case_id", "")).strip()
        packet_ids.append(case_id)
        unexpected_row_fields = set(row) - BLINDED_PACKET_ROW_FIELDS
        if unexpected_row_fields:
            errors.append(
                f"packet cases[{case_id or index}] exposes internal candidate metadata: "
                + ", ".join(sorted(unexpected_row_fields))
            )
        if (
            not isinstance(row.get("packet_case_index"), int)
            or isinstance(row.get("packet_case_index"), bool)
            or row.get("packet_case_index") != index
        ):
            errors.append(f"packet cases[{case_id or index}] packet_case_index must be {index}")
        candidate = candidate_by_id.get(case_id)
        if candidate is None:
            errors.append(f"packet cases[{index}] references unknown candidate {case_id!r}")
            continue
        for field_name in (
            "claim",
            "evidence",
            "evidence_scope",
            "evidence_locator",
            "source_locator",
            "lang",
            "domain",
            "writing_context",
        ):
            if row.get(field_name) != candidate.get(field_name):
                errors.append(f"packet cases[{case_id or index}] {field_name} differs from candidate")
        annotation = row.get("annotation")
        if not isinstance(annotation, Mapping):
            errors.append(f"packet cases[{case_id or index}] annotation must be an object")
        elif not allow_completed_annotations and any(str(value).strip() for value in annotation.values()):
            errors.append(f"packet cases[{case_id or index}] is already annotated")
        if str(row.get("packet_id", "")).strip() != packet_id:
            errors.append(f"packet cases[{case_id or index}] packet_id differs from packet")
        if str(row.get("packet_digest", "")).strip() != expected_digest:
            errors.append(f"packet cases[{case_id or index}] packet_digest differs from packet")
        if "gold" in row or "dataset_gold" in row:
            errors.append(f"packet cases[{case_id or index}] contains a gold label")
    if len(packet_ids) != len(set(packet_ids)):
        errors.append("packet case ids must be unique")
    if packet_ids != sorted(packet_ids):
        errors.append("packet case ids must be in deterministic blinded order")
    matched_candidates = [candidate_by_id[case_id] for case_id in packet_ids if case_id in candidate_by_id]
    if candidate_digest != _candidate_content_digest(candidate_dataset, matched_candidates):
        errors.append("candidate_digest does not match candidate metadata")
    if not expected_digest or expected_digest != _packet_digest(packet):
        errors.append("packet_digest does not match blinded packet content")
    errors.extend(f"forbidden label field at {path}" for path in _forbidden_label_key_paths(packet))
    if errors:
        raise HumanSupportCandidateError("; ".join(sorted(set(errors))))
    return {
        "ok": True,
        "packet_id": packet_id,
        "packet_digest": expected_digest,
        "candidate_digest": candidate_digest,
        "case_count": len(packet_cases),
        "case_ids": sorted(packet_ids),
    }


def merge_candidate_annotation_packets(
    candidate_dataset: Mapping[str, Any],
    packets: Sequence[Mapping[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Merge independent annotations while preserving disagreements for adjudication."""

    validate_candidate_dataset(candidate_dataset)
    output = deepcopy(dict(candidate_dataset))
    by_blinded_id = {_blinded_case_id(output, row): row for row in output["cases"]}
    applied = []
    skipped = []
    conflicts = []
    for packet_index, packet in enumerate(packets, start=1):
        rows = _packet_rows(packet)
        packet_id = str(packet.get("packet_id", "")).strip() if isinstance(packet, Mapping) else ""
        packet_digest = str(packet.get("packet_digest", "")).strip() if isinstance(packet, Mapping) else ""
        packet_verified = False
        packet_error = ""
        if isinstance(packet, Mapping) and packet_id:
            try:
                validate_blinded_candidate_packet(
                    candidate_dataset,
                    packet,
                    allow_completed_annotations=True,
                )
            except HumanSupportCandidateError as exc:
                packet_error = str(exc)
            else:
                packet_verified = True
        if not packet_verified:
            skipped.append(
                {
                    "packet_index": packet_index,
                    "packet_id": packet_id,
                    "row_count": len(rows),
                    "code": "packet_not_blinded_or_intact",
                    "error": packet_error,
                }
            )
            continue
        for row_index, raw_row in enumerate(rows, start=1):
            if not isinstance(raw_row, Mapping):
                skipped.append({"packet_index": packet_index, "row_index": row_index, "code": "row_not_object"})
                continue
            blinded_case_id = str(raw_row.get("case_id", "")).strip()
            candidate = by_blinded_id.get(blinded_case_id)
            if candidate is None:
                skipped.append({"packet_index": packet_index, "row_index": row_index, "case_id": blinded_case_id, "code": "unknown_case"})
                continue
            case_id = str(candidate["id"])
            annotation = raw_row.get("annotation")
            if not isinstance(annotation, Mapping):
                skipped.append({"packet_index": packet_index, "row_index": row_index, "case_id": case_id, "code": "missing_annotation"})
                continue
            label = str(annotation.get("annotator_label", "")).strip()
            annotator_id = str(annotation.get("annotator_id", "")).strip()
            if label not in ALLOWED_SUPPORT_LABELS:
                skipped.append({"packet_index": packet_index, "row_index": row_index, "case_id": case_id, "code": "invalid_label", "label": label})
                continue
            if not annotator_id:
                skipped.append({"packet_index": packet_index, "row_index": row_index, "case_id": case_id, "code": "missing_annotator_id"})
                continue
            if label in {"supported", "weakly_supported", "contradicted"} and not str(annotation.get("rationale", "")).strip():
                skipped.append({"packet_index": packet_index, "row_index": row_index, "case_id": case_id, "code": "rationale_required"})
                continue
            normalized = {
                "annotator_id": annotator_id,
                "annotator_label": label,
                "rationale": str(annotation.get("rationale", "")).strip(),
                "confidence": str(annotation.get("confidence", "")).strip(),
                "evidence_scope_assessed": str(annotation.get("evidence_scope_assessed", "")).strip(),
                "full_text_needed": str(annotation.get("full_text_needed", "")).strip(),
                "notes": str(annotation.get("notes", "")).strip(),
                "packet_id": str(raw_row.get("packet_id", packet_id)).strip(),
                "packet_digest": str(raw_row.get("packet_digest", packet_digest)).strip(),
                "packet_verified": packet_verified,
                "completed_packet_digest": "sha256:" + _json_digest(packet),
            }
            existing = candidate.setdefault("annotations", [])
            if any(
                str(item.get("annotator_id", "")) == annotator_id
                and str(item.get("packet_id", "")) == normalized["packet_id"]
                for item in existing
                if isinstance(item, Mapping)
            ):
                skipped.append({"packet_index": packet_index, "row_index": row_index, "case_id": case_id, "code": "duplicate_annotation"})
                continue
            existing.append(normalized)
            candidate["annotation_status"] = _annotation_status(existing)
            applied.append(case_id)
            if candidate["annotation_status"] == "dual_annotator_disagreement":
                conflicts.append({"case_id": case_id, "labels": sorted({item["annotator_label"] for item in existing})})

    report = {
        "ok": not skipped and not conflicts,
        "packet_count": len(packets),
        "applied_annotation_count": len(applied),
        "skipped_count": len(skipped),
        "conflict_count": len(conflicts),
        "applied_case_ids": sorted(set(applied)),
        "skipped": skipped,
        "conflicts": conflicts,
        "counts": _candidate_annotation_counts(output["cases"]),
        "next_action": (
            "adjudicate_disagreements_before_promotion"
            if conflicts
            else "obtain_second_independent_annotation"
            if reportable_single_count(output["cases"])
            else "promote_only_dual_agreed_cases_after_contract_review"
        ),
    }
    return output, report


def _resolve_evidence(
    raw: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    source_case: Mapping[str, Any],
    evidence_scope: str,
    rights_basis: str,
) -> Tuple[str, str]:
    supplied = str(raw.get("evidence", "")).strip()
    if supplied:
        locator = str(raw.get("evidence_locator", "user_provided_excerpt")).strip()
        return supplied, locator
    if evidence_scope == "abstract":
        abstract = str(snapshot.get("abstract", "")).strip()
        if not abstract:
            raise HumanSupportCandidateError(
                f"source case {source_case.get('id', '')} has no public abstract; provide lawful evidence explicitly"
            )
        return abstract, str(raw.get("evidence_locator", "abstract")).strip() or "abstract"
    raise HumanSupportCandidateError("explicit evidence is required for non-abstract candidate scopes")


def _validate_candidate_dimensions(
    *,
    language: str,
    domain: str,
    writing_context: str,
    case_type: str,
    split: str,
    evidence_scope: str,
    rights_basis: str,
) -> None:
    if not language.strip() or not domain.strip():
        raise HumanSupportCandidateError("lang and domain are required")
    if writing_context not in ALLOWED_WRITING_CONTEXTS:
        raise HumanSupportCandidateError(f"unsupported writing_context {writing_context!r}")
    if case_type not in ALLOWED_CASE_TYPES:
        raise HumanSupportCandidateError(f"unsupported case_type {case_type!r}")
    if split not in ALLOWED_SPLITS:
        raise HumanSupportCandidateError(f"unsupported split {split!r}")
    if evidence_scope not in ALLOWED_EVIDENCE_SCOPES:
        raise HumanSupportCandidateError(f"unsupported evidence_scope {evidence_scope!r}")
    if rights_basis not in ALLOWED_RIGHTS_BASES:
        raise HumanSupportCandidateError(f"unsupported rights_basis {rights_basis!r}")
    if evidence_scope == "full_text" and rights_basis not in {"open_access", "user_provided", "licensed"}:
        raise HumanSupportCandidateError("full_text requires open_access, user_provided, or licensed rights")


def _retrieval_cases_by_id(dataset: Mapping[str, Any]) -> Dict[str, Mapping[str, Any]]:
    rows = dataset.get("cases")
    if not isinstance(rows, list):
        raise HumanSupportCandidateError("retrieval dataset cases must be a list")
    output = {str(row.get("id", "")).strip(): row for row in rows if isinstance(row, Mapping) and str(row.get("id", "")).strip()}
    if not output:
        raise HumanSupportCandidateError("retrieval dataset has no cases")
    return output


def _empty_annotation() -> Dict[str, str]:
    return {
        "annotator_id": "",
        "annotator_label": "",
        "rationale": "",
        "confidence": "",
        "evidence_scope_assessed": "",
        "full_text_needed": "",
        "notes": "",
    }


def _annotation_status(annotations: Sequence[Mapping[str, Any]]) -> str:
    labels = [str(item.get("annotator_label", "")) for item in annotations if isinstance(item, Mapping)]
    annotators = {str(item.get("annotator_id", "")) for item in annotations if isinstance(item, Mapping)}
    if len(annotators) < 1:
        return "not_human_reviewed"
    if len(annotators) < 2:
        return "single_annotator"
    if len(set(labels)) == 1:
        return "dual_annotator_agreed"
    return "dual_annotator_disagreement"


def _candidate_annotation_counts(cases: Sequence[Mapping[str, Any]]) -> Dict[str, int]:
    statuses = [str(row.get("annotation_status", "not_human_reviewed")) for row in cases]
    return {status: statuses.count(status) for status in sorted(set(statuses))}


def reportable_single_count(cases: Sequence[Mapping[str, Any]]) -> bool:
    return any(str(row.get("annotation_status", "")) == "single_annotator" for row in cases)


def _packet_rows(packet: Mapping[str, Any]) -> List[Any]:
    rows = packet.get("cases") if isinstance(packet, Mapping) else None
    if isinstance(rows, list):
        return rows
    if isinstance(packet, Mapping) and packet.get("case_id"):
        return [packet]
    return []


def _blinded_case_id(dataset: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    identity = f"{dataset.get('campaign_id', '')}\0{row['id']}"
    return "review-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def _packet_is_blinded_and_intact(packet: Mapping[str, Any]) -> bool:
    if packet.get("packet_type") != HUMAN_SUPPORT_CANDIDATE_PACKET_TYPE:
        return False
    if "gold" in packet or "dataset_gold" in packet:
        return False
    packet_id = str(packet.get("packet_id", "")).strip()
    if not packet_id or packet_id != _packet_id(packet):
        return False
    expected = str(packet.get("packet_digest", "")).strip()
    rows = packet.get("cases")
    return bool(
        isinstance(rows, list)
        and packet.get("case_count") == len(rows)
        and expected
        and expected == _packet_digest(packet)
    )


def _packet_id(packet: Mapping[str, Any]) -> str:
    signature = {
        "packet_type": packet.get("packet_type"),
        "candidate_digest": packet.get("candidate_digest"),
        "review_phase": packet.get("review_phase"),
        "packet_purpose": packet.get("packet_purpose"),
        "cases": [
            {
                key: row.get(key)
                for key in (
                    "case_id",
                    "claim",
                    "evidence",
                    "evidence_scope",
                    "evidence_locator",
                    "source_locator",
                )
            }
            for row in packet.get("cases", [])
            if isinstance(row, Mapping)
        ],
    }
    return "human-support-packet-" + _json_digest(signature)[:16]


def _packet_digest(packet: Mapping[str, Any]) -> str:
    payload = deepcopy(dict(packet))
    payload.pop("packet_digest", None)
    for row in payload.get("cases", []) if isinstance(payload.get("cases"), list) else []:
        if isinstance(row, dict):
            row.pop("packet_digest", None)
            row.pop("packet_id", None)
            row.pop("annotation", None)
    return "sha256:" + _json_digest(payload)


def _candidate_content_digest(dataset: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> str:
    """Bind hidden assignment and source metadata without exposing it to reviewers."""

    immutable_fields = (
        "id", "benchmark_origin", "claim", "evidence", "source_case_id",
        "source_locator", "evidence_locator", "rights_basis", "lang", "domain",
        "writing_context", "evidence_scope", "case_type", "split", "label_source",
        "candidate_provenance",
    )
    content = {
        "campaign_id": dataset.get("campaign_id"),
        "cases": [
            {field: row.get(field) for field in immutable_fields}
            for row in sorted(rows, key=lambda row: _blinded_case_id(dataset, row))
        ],
    }
    return "sha256:" + _json_digest(content)


def _json_digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _is_unprefixed_sha256(value: str) -> bool:
    """Accept the unprefixed digest used by candidate provenance snapshots."""

    return len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


def _forbidden_label_key_paths(value: Any, prefix: str = "") -> List[str]:
    paths: List[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if key_text in FORBIDDEN_LABEL_KEYS:
                paths.append(path)
            paths.extend(_forbidden_label_key_paths(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            paths.extend(_forbidden_label_key_paths(child, f"{prefix}[{index}]"))
    return paths


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _is_iso_timestamp(value: str) -> bool:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except (TypeError, ValueError):
        return False
