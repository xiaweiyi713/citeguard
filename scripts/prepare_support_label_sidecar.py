#!/usr/bin/env python3
"""Generate or complete a support-label provenance sidecar."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Optional

from _bootstrap import ensure_project_root

ensure_project_root()

from citeguard.verification.support_eval import (  # noqa: E402
    ALLOWED_SUPPORT_LABELS,
    build_support_label_sidecar_template,
    load_support_label_cases,
    validate_support_label_sidecar,
)

HIDDEN_ANNOTATION_PACKET_FIELDS = [
    "gold",
    "predicted",
    "adjudicated_label",
    "annotator_labels",
    "label_notes",
]


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a complete support label sidecar template for annotation/adjudication."
    )
    parser.add_argument("--dataset", default="data/eval/support_eval.json")
    parser.add_argument(
        "--existing-sidecar",
        default="",
        help="Optional existing sidecar to preserve and complete.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Output path. Defaults to stdout.",
    )
    parser.add_argument(
        "--include-context",
        action="store_true",
        help="Include claim/evidence context fields for annotators.",
    )
    parser.add_argument(
        "--priority",
        action="append",
        choices=["high", "medium", "normal"],
        default=None,
        help="Only include cases with this annotation priority; repeat for multiple priorities.",
    )
    parser.add_argument(
        "--split",
        action="append",
        choices=["train", "dev", "test"],
        default=None,
        help="Only include cases from this split; repeat for multiple splits.",
    )
    parser.add_argument(
        "--case-type",
        action="append",
        default=None,
        help="Only include cases with this case_type; repeat for multiple case types.",
    )
    parser.add_argument(
        "--lang",
        action="append",
        default=None,
        help="Only include cases with this language code; repeat for multiple languages.",
    )
    parser.add_argument(
        "--case-id",
        action="append",
        default=None,
        help="Only include this stable case id; repeat for multiple cases.",
    )
    parser.add_argument(
        "--from-review-queue",
        action="store_true",
        help=(
            "Select cases from the support-eval review queue before applying other filters. "
            "Useful for turning quality-gate failures into blinded annotation packets."
        ),
    )
    parser.add_argument(
        "--review-backend",
        choices=["fixture", "heuristic", "production"],
        default="heuristic",
        help=(
            "Backend used with --from-review-queue. fixture is deterministic and usually produces "
            "an empty queue; heuristic is the local zero-model triage baseline."
        ),
    )
    parser.add_argument(
        "--unreviewed-only",
        action="store_true",
        help="Only include cases whose sidecar adjudication_status is not_human_reviewed.",
    )
    parser.add_argument(
        "--review-status",
        action="append",
        choices=[
            "not_human_reviewed",
            "single_annotator",
            "dual_annotator_agreed",
            "dual_annotator_adjudicated",
            "published_benchmark",
        ],
        default=None,
        help="Only include cases with this sidecar adjudication_status; repeat for multiple statuses.",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        help="Maximum number of filtered cases to include in the packet.",
    )
    parser.add_argument(
        "--limit-per-language",
        type=_positive_int,
        default=None,
        help="Maximum number of filtered cases to include per language code.",
    )
    parser.add_argument(
        "--limit-per-case-type",
        type=_positive_int,
        default=None,
        help="Maximum number of filtered cases to include per case_type.",
    )
    parser.add_argument(
        "--limit-per-evidence-scope",
        type=_positive_int,
        default=None,
        help="Maximum number of filtered cases to include per evidence_scope.",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Print a JSON review-readiness audit instead of a sidecar template.",
    )
    parser.add_argument(
        "--annotation-packet",
        action="store_true",
        help=(
            "Print a blinded annotation packet instead of a sidecar template. "
            "The packet includes claim/evidence context but omits gold and adjudicated labels."
        ),
    )
    parser.add_argument(
        "--merge-annotation-packet",
        default="",
        help=(
            "Merge a completed blinded annotation packet into a sidecar draft. "
            "Conflicting labels are reported and not silently applied."
        ),
    )
    parser.add_argument(
        "--apply-adjudications",
        default="",
        help=(
            "Apply resolved adjudication rows to a sidecar draft. "
            "Adjudicated labels must match the current dataset gold label."
        ),
    )
    parser.add_argument(
        "--packet-format",
        choices=["json", "jsonl"],
        default="json",
        help="Output format for --annotation-packet. JSON keeps packet metadata; JSONL writes one case per line.",
    )
    parser.add_argument(
        "--review-phase",
        default="",
        help=(
            "Optional machine-readable review phase to archive in an annotation packet, "
            "for example first_review_high_risk or second_review."
        ),
    )
    parser.add_argument(
        "--packet-purpose",
        default="",
        help="Optional human-readable reviewer assignment purpose to archive in an annotation packet.",
    )
    parser.add_argument(
        "--instructions-output",
        default="",
        help="With --annotation-packet, also write a Markdown instruction sheet for independent annotators.",
    )
    parser.add_argument(
        "--fail-on-high-risk-unreviewed",
        action="store_true",
        help="With --audit, exit non-zero when contradiction, hard_negative, or full_text_required cases remain unreviewed.",
    )
    parser.add_argument(
        "--fail-on-high-risk-unreviewed-language",
        action="append",
        default=[],
        metavar="LANG",
        help="With --audit, exit non-zero when high-risk cases in this language remain unreviewed; repeat for multiple languages.",
    )
    parser.add_argument(
        "--fail-on-full-text-required-unreviewed",
        action="store_true",
        help="With --audit, exit non-zero when abstract/full-text boundary cases remain unreviewed.",
    )
    parser.add_argument(
        "--fail-on-policy-boundary-unreviewed",
        action="store_true",
        help="With --audit, exit non-zero when weak citation-set policy-boundary cases remain unreviewed.",
    )
    args = parser.parse_args(argv)
    selected_modes = sum(
        bool(value)
        for value in (
            args.audit,
            args.annotation_packet,
            args.merge_annotation_packet,
            args.apply_adjudications,
        )
    )
    if selected_modes > 1:
        parser.error(
            "--audit, --annotation-packet, --merge-annotation-packet, and --apply-adjudications are mutually exclusive"
        )
    if args.instructions_output and not args.annotation_packet:
        parser.error("--instructions-output requires --annotation-packet")
    if args.unreviewed_only and args.review_status:
        parser.error("--unreviewed-only cannot be combined with --review-status")

    all_cases = load_support_label_cases(args.dataset)
    _validate_case_ids(args.case_id, all_cases, parser)
    review_queue_case_ids: list[str] = []
    review_queue_order: dict[str, int] = {}
    existing = None
    if args.existing_sidecar:
        with open(args.existing_sidecar, encoding="utf-8") as handle:
            existing = json.load(handle)
        validate_support_label_sidecar(existing, all_cases)
    if args.from_review_queue:
        review_queue_case_ids = _review_queue_case_ids(
            dataset_path=args.dataset,
            splits=args.split,
            backend_name=args.review_backend,
        )
        review_queue_order = {case_id: index for index, case_id in enumerate(review_queue_case_ids)}
        all_cases = [
            case
            for case in sorted(all_cases, key=lambda item: review_queue_order.get(item.case_id, 10**9))
            if case.case_id in review_queue_order
        ]
        setattr(args, "_review_queue_case_ids", review_queue_case_ids)

    review_statuses = ["not_human_reviewed"] if args.unreviewed_only else args.review_status
    candidates = (
        _filter_cases_by_review_status(all_cases, existing, review_statuses)
        if review_statuses
        else all_cases
    )
    cases = all_cases if (args.merge_annotation_packet or args.apply_adjudications) else _filter_cases(
        candidates,
        priorities=args.priority,
        splits=args.split,
        case_types=args.case_type,
        languages=args.lang,
        case_ids=args.case_id,
        limit=args.limit,
        limit_per_language=args.limit_per_language,
        limit_per_case_type=args.limit_per_case_type,
        limit_per_evidence_scope=args.limit_per_evidence_scope,
    )
    existing_for_cases = _filter_existing_sidecar(existing, cases) if existing is not None else None

    payload = build_support_label_sidecar_template(
        cases,
        existing_sidecar=existing_for_cases,
        dataset_name=Path(args.dataset).name,
        include_context=args.include_context,
    )
    if args.merge_annotation_packet:
        annotations = _load_annotation_packet(args.merge_annotation_packet)
        merge_report = _merge_annotation_packet(payload, cases, annotations)
        payload["merge_report"] = merge_report
        validate_support_label_sidecar(payload, cases)
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0 if merge_report["ok"] else 1
    if args.apply_adjudications:
        adjudications = _load_annotation_packet(args.apply_adjudications)
        adjudication_report = _apply_adjudications(payload, cases, adjudications)
        payload["adjudication_report"] = adjudication_report
        validate_support_label_sidecar(payload, cases)
        text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0 if adjudication_report["ok"] else 1
    summary = validate_support_label_sidecar(payload, cases)
    if args.annotation_packet:
        packet = _build_annotation_packet(
            cases,
            existing_sidecar=existing_for_cases,
            dataset_name=Path(args.dataset).name,
            filters=_filter_summary(args),
            review_phase=args.review_phase,
            packet_purpose=args.packet_purpose,
            preferred_case_order=review_queue_order if args.from_review_queue else None,
        )
        if args.instructions_output:
            Path(args.instructions_output).write_text(_format_annotation_instructions(packet), encoding="utf-8")
        text = _format_annotation_packet(packet, args.packet_format)
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        return 0
    if args.audit:
        report = _build_audit_report(
            payload,
            cases,
            summary,
            dataset_name=Path(args.dataset).name,
            dataset_path=args.dataset,
            existing_sidecar_path=args.existing_sidecar,
            include_context=args.include_context,
            filters=_filter_summary(args),
        )
        report["audit_gate"] = _build_audit_gate(
            report,
            fail_on_high_risk_unreviewed=args.fail_on_high_risk_unreviewed,
            fail_on_high_risk_unreviewed_languages=args.fail_on_high_risk_unreviewed_language,
            fail_on_full_text_required_unreviewed=args.fail_on_full_text_required_unreviewed,
            fail_on_policy_boundary_unreviewed=args.fail_on_policy_boundary_unreviewed,
        )
        text = json.dumps(
            report,
            indent=2,
            ensure_ascii=False,
        ) + "\n"
        if args.output:
            Path(args.output).write_text(text, encoding="utf-8")
        else:
            print(text, end="")
        if not report["audit_gate"]["ok"]:
            return 1
        return 0
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text, end="")
    return 0


def _load_annotation_packet(path: str) -> list:
    text = Path(path).read_text(encoding="utf-8")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(payload, dict):
        cases = payload.get("cases")
        if isinstance(cases, list):
            rows = [dict(item) if isinstance(item, dict) else item for item in cases]
            for row in rows:
                if not isinstance(row, dict):
                    continue
                for field in ("packet_id", "packet_digest", "review_phase", "packet_purpose"):
                    if field not in row and payload.get(field):
                        row[field] = payload.get(field)
            return rows
        if payload.get("case_id"):
            return [payload]
    if isinstance(payload, list):
        return payload
    raise ValueError("annotation packet must be a JSON packet, JSON list, JSON object row, or JSONL file")


def _merge_annotation_packet(sidecar: dict, cases: list, annotation_rows: list) -> dict:
    cases_by_id = {case.case_id: case for case in cases}
    sidecar_by_id = {
        str(item.get("case_id")): item
        for item in sidecar.get("cases", [])
        if isinstance(item, dict) and item.get("case_id")
    }
    grouped = {}
    conflicts = []
    skipped = []
    adjudication_queue = []
    source_packet_ids = []
    source_packet_metadata = []
    for index, row in enumerate(annotation_rows, start=1):
        if not isinstance(row, dict):
            skipped.append({"index": index, "code": "invalid_row", "message": "Annotation row must be an object."})
            continue
        packet_id = str(row.get("packet_id", "")).strip()
        if packet_id:
            source_packet_ids.append(packet_id)
            source_packet_metadata.append(_annotation_source_packet_metadata(row))
        case_id = str(row.get("case_id", "")).strip()
        annotation = row.get("annotation", {})
        if not isinstance(annotation, dict):
            annotation = {}
        label = str(annotation.get("annotator_label") or row.get("annotator_label") or "").strip()
        if not case_id or case_id not in cases_by_id:
            skipped.append(
                {
                    "index": index,
                    "case_id": case_id,
                    "code": "unknown_case",
                    "message": "Annotation row does not match a dataset case.",
                }
            )
            continue
        if not label:
            skipped.append(
                {
                    "index": index,
                    "case_id": case_id,
                    "code": "missing_label",
                    "message": "Annotation row is missing annotation.annotator_label.",
                }
            )
            continue
        if label not in ALLOWED_SUPPORT_LABELS:
            skipped.append(
                {
                    "index": index,
                    "case_id": case_id,
                    "code": "invalid_label",
                    "message": "Annotation label is not in the support label registry.",
                    "label": label,
                }
            )
            continue
        summary = _annotation_summary(row, annotation, label)
        if not summary["annotator_id"]:
            skipped.append(
                {
                    "index": index,
                    "case_id": case_id,
                    "code": "missing_annotator_id",
                    "message": "Annotation row must include annotation.annotator_id.",
                }
            )
            continue
        grouped.setdefault(case_id, []).append(summary)

    applied_case_ids = []
    for case_id, case_annotations in sorted(grouped.items()):
        case = cases_by_id[case_id]
        labels = [item["label"] for item in case_annotations]
        annotator_ids = [item["annotator_id"] for item in case_annotations]
        duplicate_annotator_ids = sorted(
            {annotator_id for annotator_id in annotator_ids if annotator_ids.count(annotator_id) > 1}
        )
        if duplicate_annotator_ids:
            conflicts.append(
                _merge_conflict(
                    case_id=case_id,
                    code="duplicate_annotator",
                    message="The same annotator appears more than once for this case.",
                    case=case,
                    labels=labels,
                    annotations=case_annotations,
                    extra={"annotator_ids": duplicate_annotator_ids},
                )
            )
            continue
        unique_labels = sorted(set(labels))
        if len(unique_labels) > 1:
            conflict = _merge_conflict(
                case_id=case_id,
                code="annotator_disagreement",
                message="Annotation packet contains unresolved annotator disagreement.",
                case=case,
                labels=labels,
                annotations=case_annotations,
            )
            conflicts.append(conflict)
            adjudication_queue.append(_adjudication_queue_item(conflict))
            continue
        label = unique_labels[0]
        if label != case.gold:
            conflict = _merge_conflict(
                case_id=case_id,
                code="label_mismatch",
                message="Annotation label does not match the current dataset gold label.",
                case=case,
                labels=labels,
                annotations=case_annotations,
            )
            conflicts.append(conflict)
            adjudication_queue.append(_adjudication_queue_item(conflict))
            continue
        item = sidecar_by_id[case_id]
        item["annotator_count"] = len(case_annotations)
        item["annotator_labels"] = labels
        item["adjudicated_label"] = case.gold
        item["adjudication_status"] = "dual_annotator_agreed" if len(case_annotations) >= 2 else "single_annotator"
        item["disagreement"] = "none"
        if case_annotations[0].get("source_locator"):
            item["source_locator"] = case_annotations[0]["source_locator"]
        item["notes"] = _merged_annotation_notes(case_annotations)
        applied_case_ids.append(case_id)

    return {
        "ok": not conflicts and not skipped,
        "annotation_count": len(annotation_rows),
        "applied_count": len(applied_case_ids),
        "conflict_count": len(conflicts),
        "skipped_count": len(skipped),
        "applied_case_ids": applied_case_ids,
        "source_packet_ids": sorted(set(source_packet_ids)),
        "source_packet_metadata": _unique_packet_metadata(source_packet_metadata),
        "conflicts": conflicts,
        "adjudication_queue": adjudication_queue,
        "skipped": skipped,
        "next_actions": _merge_next_actions(conflicts, skipped),
    }


def _merge_conflict(
    *,
    case_id: str,
    code: str,
    message: str,
    case,
    labels: list,
    annotations: list,
    extra: Optional[dict] = None,
) -> dict:
    conflict = {
        "case_id": case_id,
        "code": code,
        "message": message,
        "dataset_gold": case.gold,
        "annotator_labels": labels,
        "annotation_examples": _conflict_annotation_examples(annotations),
    }
    if extra:
        conflict.update(extra)
    return conflict


def _conflict_annotation_examples(annotations: list) -> list:
    examples = []
    for item in annotations:
        examples.append(
            {
                "packet_id": item.get("packet_id", ""),
                "packet_digest": item.get("packet_digest", ""),
                "packet_case_index": item.get("packet_case_index", ""),
                "annotator_id": item.get("annotator_id", ""),
                "label": item.get("label", ""),
                "rationale": item.get("rationale", ""),
                "confidence": item.get("confidence", ""),
                "evidence_scope_assessed": item.get("evidence_scope_assessed", ""),
                "full_text_needed": item.get("full_text_needed", ""),
                "notes": item.get("notes", ""),
                "source_locator": item.get("source_locator", ""),
                "review_phase": item.get("review_phase", ""),
                "packet_purpose": item.get("packet_purpose", ""),
            }
        )
    return examples


def _adjudication_queue_item(conflict: dict) -> dict:
    source_packet_ids = sorted(
        {
            str(item.get("packet_id", "")).strip()
            for item in conflict.get("annotation_examples", [])
            if str(item.get("packet_id", "")).strip()
        }
    )
    source_packet_metadata = _unique_packet_metadata(
        _annotation_source_packet_metadata(item)
        for item in conflict.get("annotation_examples", [])
    )
    return {
        "case_id": conflict.get("case_id", ""),
        "conflict_code": conflict.get("code", ""),
        "dataset_gold": conflict.get("dataset_gold", ""),
        "annotator_labels": list(conflict.get("annotator_labels", [])),
        "annotation_examples": [dict(item) for item in conflict.get("annotation_examples", [])],
        "adjudication_template": {
            "case_id": conflict.get("case_id", ""),
            "annotator_labels": list(conflict.get("annotator_labels", [])),
            "adjudicated_label": "",
            "adjudicator": "",
            "rationale": "",
            "source_locator": "",
            "source_packet_ids": source_packet_ids,
            "source_packet_metadata": source_packet_metadata,
        },
        "recommended_action": (
            "Review annotation rationales, update dataset gold if needed, then rerun "
            "--apply-adjudications with an explicit adjudicator."
        ),
    }


def _annotation_summary(row: dict, annotation: dict, label: str) -> dict:
    return {
        "packet_id": str(row.get("packet_id", "")).strip(),
        "packet_digest": str(row.get("packet_digest", "")).strip(),
        "packet_case_index": row.get("packet_case_index", ""),
        "label": label,
        "annotator_id": str(annotation.get("annotator_id") or row.get("annotator_id") or "").strip(),
        "rationale": str(annotation.get("rationale") or row.get("rationale") or "").strip(),
        "confidence": str(annotation.get("confidence") or row.get("confidence") or "").strip(),
        "evidence_scope_assessed": str(
            annotation.get("evidence_scope_assessed") or row.get("evidence_scope_assessed") or ""
        ).strip(),
        "full_text_needed": str(annotation.get("full_text_needed") or row.get("full_text_needed") or "").strip(),
        "notes": str(annotation.get("notes") or row.get("notes") or "").strip(),
        "source_locator": str(row.get("source_locator", "")).strip(),
        "review_phase": str(row.get("review_phase", "")).strip(),
        "packet_purpose": str(row.get("packet_purpose", "")).strip(),
    }


def _annotation_source_packet_metadata(row: dict) -> dict:
    return {
        "packet_id": str(row.get("packet_id", "")).strip(),
        "packet_digest": str(row.get("packet_digest", "")).strip(),
        "review_phase": str(row.get("review_phase", "")).strip(),
        "packet_purpose": str(row.get("packet_purpose", "")).strip(),
    }


def _unique_packet_metadata(rows) -> list:
    seen = set()
    unique = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        item = {
            "packet_id": str(row.get("packet_id", "")).strip(),
            "packet_digest": str(row.get("packet_digest", "")).strip(),
            "review_phase": str(row.get("review_phase", "")).strip(),
            "packet_purpose": str(row.get("packet_purpose", "")).strip(),
        }
        if not item["packet_id"]:
            continue
        key = (item["packet_id"], item["packet_digest"], item["review_phase"], item["packet_purpose"])
        if key in seen:
            continue
        seen.add(key)
        unique.append({key: value for key, value in item.items() if value})
    return sorted(
        unique,
        key=lambda item: (
            item.get("packet_id", ""),
            item.get("packet_digest", ""),
            item.get("review_phase", ""),
            item.get("packet_purpose", ""),
        ),
    )


def _merged_annotation_notes(annotations: list) -> str:
    parts = ["Merged from blinded annotation packet."]
    for index, item in enumerate(annotations, start=1):
        annotator = item.get("annotator_id") or f"annotator_{index}"
        details = []
        if item.get("rationale"):
            details.append(item["rationale"])
        if item.get("confidence"):
            details.append(f"confidence={item['confidence']}")
        if item.get("evidence_scope_assessed"):
            details.append(f"evidence_scope_assessed={item['evidence_scope_assessed']}")
        if item.get("full_text_needed"):
            details.append(f"full_text_needed={item['full_text_needed']}")
        if item.get("notes"):
            details.append(f"notes={item['notes']}")
        if item.get("review_phase"):
            details.append(f"review_phase={item['review_phase']}")
        if item.get("packet_purpose"):
            details.append(f"packet_purpose={item['packet_purpose']}")
        if item.get("packet_digest"):
            details.append(f"packet_digest={item['packet_digest']}")
        suffix = " (" + "; ".join(details) + ")" if details else ""
        parts.append(f"{annotator}: {item['label']}{suffix}")
    return " ".join(parts)


def _merge_next_actions(conflicts: list, skipped: list) -> list:
    actions = []
    if conflicts:
        actions.append("Resolve label conflicts before updating dataset gold or claiming human-reviewed coverage.")
    if skipped:
        actions.append("Fix skipped annotation rows, then rerun the merge.")
    if not actions:
        actions.append("Validate the merged sidecar with eval_support.py before release reporting.")
    return actions


def _apply_adjudications(sidecar: dict, cases: list, adjudication_rows: list) -> dict:
    cases_by_id = {case.case_id: case for case in cases}
    sidecar_by_id = {
        str(item.get("case_id")): item
        for item in sidecar.get("cases", [])
        if isinstance(item, dict) and item.get("case_id")
    }
    applied_case_ids = []
    source_packet_ids = []
    source_packet_metadata = []
    conflicts = []
    skipped = []
    for index, row in enumerate(adjudication_rows, start=1):
        if not isinstance(row, dict):
            skipped.append({"index": index, "code": "invalid_row", "message": "Adjudication row must be an object."})
            continue
        case_id = str(row.get("case_id", "")).strip()
        label = str(row.get("adjudicated_label", "")).strip()
        adjudicator = str(row.get("adjudicator", "")).strip()
        if not case_id or case_id not in cases_by_id:
            skipped.append(
                {
                    "index": index,
                    "case_id": case_id,
                    "code": "unknown_case",
                    "message": "Adjudication row does not match a dataset case.",
                }
            )
            continue
        if label not in ALLOWED_SUPPORT_LABELS:
            skipped.append(
                {
                    "index": index,
                    "case_id": case_id,
                    "code": "invalid_adjudicated_label",
                    "message": "Adjudicated label is not in the support label registry.",
                    "label": label,
                }
            )
            continue
        if not adjudicator:
            skipped.append(
                {
                    "index": index,
                    "case_id": case_id,
                    "code": "missing_adjudicator",
                    "message": "Adjudication row must include an adjudicator.",
                }
            )
            continue
        case = cases_by_id[case_id]
        annotator_labels = _adjudication_annotator_labels(row, sidecar_by_id.get(case_id, {}))
        if len(annotator_labels) < 2:
            skipped.append(
                {
                    "index": index,
                    "case_id": case_id,
                    "code": "missing_annotator_labels",
                    "message": "Adjudication requires at least two pre-adjudication annotator labels.",
                }
            )
            continue
        if label != case.gold:
            conflicts.append(
                {
                    "case_id": case_id,
                    "code": "adjudicated_label_mismatch",
                    "message": "Adjudicated label does not match the current dataset gold label.",
                    "dataset_gold": case.gold,
                    "adjudicated_label": label,
                    "annotator_labels": annotator_labels,
                }
            )
            continue
        item = sidecar_by_id[case_id]
        item["adjudication_status"] = "dual_annotator_adjudicated"
        item["annotator_count"] = len(annotator_labels)
        item["annotator_labels"] = annotator_labels
        item["adjudicated_label"] = label
        item["disagreement"] = "resolved"
        item["adjudicator"] = adjudicator
        if row.get("source_locator"):
            item["source_locator"] = str(row.get("source_locator", "")).strip()
        source_packet_ids.extend(_adjudication_source_packet_ids(row))
        source_packet_metadata.extend(_adjudication_source_packet_metadata(row))
        item["notes"] = _adjudication_notes(row, annotator_labels)
        applied_case_ids.append(case_id)

    return {
        "ok": not conflicts and not skipped,
        "adjudication_count": len(adjudication_rows),
        "applied_count": len(applied_case_ids),
        "conflict_count": len(conflicts),
        "skipped_count": len(skipped),
        "applied_case_ids": applied_case_ids,
        "source_packet_ids": sorted(set(source_packet_ids)),
        "source_packet_metadata": _unique_packet_metadata(source_packet_metadata),
        "conflicts": conflicts,
        "skipped": skipped,
        "next_actions": _adjudication_next_actions(conflicts, skipped),
    }


def _adjudication_annotator_labels(row: dict, existing_item: dict) -> list:
    labels = row.get("annotator_labels", existing_item.get("annotator_labels", []))
    if not isinstance(labels, list):
        return []
    return [str(label) for label in labels if str(label) in ALLOWED_SUPPORT_LABELS]


def _adjudication_source_packet_ids(row: dict) -> list:
    packet_ids = row.get("source_packet_ids", [])
    if isinstance(packet_ids, str):
        packet_ids = [packet_ids]
    if not isinstance(packet_ids, list):
        return []
    return [str(packet_id).strip() for packet_id in packet_ids if str(packet_id).strip()]


def _adjudication_source_packet_metadata(row: dict) -> list:
    metadata = row.get("source_packet_metadata", [])
    if isinstance(metadata, dict):
        metadata = [metadata]
    rows = []
    if isinstance(metadata, list):
        rows.extend(item for item in metadata if isinstance(item, dict))
    known_ids = {str(item.get("packet_id", "")).strip() for item in rows if isinstance(item, dict)}
    for packet_id in _adjudication_source_packet_ids(row):
        if packet_id not in known_ids:
            rows.append({"packet_id": packet_id})
    return _unique_packet_metadata(rows)


def _adjudication_notes(row: dict, annotator_labels: list) -> str:
    rationale = str(row.get("rationale", "") or row.get("notes", "")).strip()
    source_packet_ids = _adjudication_source_packet_ids(row)
    source_packet_metadata = _adjudication_source_packet_metadata(row)
    parts = [
        "Resolved adjudication from blinded annotation workflow.",
        "annotator_labels=" + ", ".join(annotator_labels),
    ]
    if source_packet_ids:
        parts.append("source_packet_ids=" + ", ".join(source_packet_ids))
    for item in source_packet_metadata:
        packet_details = []
        if item.get("review_phase"):
            packet_details.append(f"review_phase={item['review_phase']}")
        if item.get("packet_purpose"):
            packet_details.append(f"packet_purpose={item['packet_purpose']}")
        if item.get("packet_digest"):
            packet_details.append(f"packet_digest={item['packet_digest']}")
        if packet_details:
            parts.append(f"{item.get('packet_id', '')}(" + "; ".join(packet_details) + ")")
    if rationale:
        parts.append("rationale=" + rationale)
    return " ".join(parts)


def _adjudication_next_actions(conflicts: list, skipped: list) -> list:
    actions = []
    if conflicts:
        actions.append("Review adjudicated-label conflicts before changing dataset gold or sidecar provenance.")
    if skipped:
        actions.append("Fix skipped adjudication rows, then rerun adjudication apply.")
    if not actions:
        actions.append("Validate the adjudicated sidecar and raise human-review gates when appropriate.")
    return actions


def _build_annotation_packet(
    cases: list,
    existing_sidecar: Optional[dict],
    dataset_name: str,
    filters: Optional[dict] = None,
    review_phase: str = "",
    packet_purpose: str = "",
    preferred_case_order: Optional[dict[str, int]] = None,
) -> dict:
    """Build a blinded packet for independent support-label annotation."""

    review_phase = str(review_phase or "").strip()
    packet_purpose = str(packet_purpose or "").strip()
    sidecar_by_id = {
        str(item.get("case_id")): item
        for item in (existing_sidecar or {}).get("cases", [])
        if isinstance(item, dict) and item.get("case_id")
    }
    packet_cases = []
    for case in sorted(cases, key=lambda item: _annotation_packet_sort_key(item, preferred_case_order)):
        sidecar_item = sidecar_by_id.get(case.case_id, {})
        packet_item = {
            "case_id": case.case_id,
            "priority": _case_priority_label(case),
            "claim": case.claim,
            "evidence": case.evidence,
            "evidence_scope": case.evidence_scope,
            "case_type": case.case_type,
            "split": case.split,
            "lang": case.lang,
            "review_focus": _review_focus(case),
            "review_status": sidecar_item.get("adjudication_status", "not_human_reviewed"),
            "source_locator": sidecar_item.get("source_locator", ""),
            "annotation": {
                "annotator_id": "",
                "annotator_label": "",
                "rationale": "",
                "confidence": "",
                "evidence_scope_assessed": "",
                "full_text_needed": "",
                "notes": "",
            },
        }
        if review_phase:
            packet_item["review_phase"] = review_phase
        if packet_purpose:
            packet_item["packet_purpose"] = packet_purpose
        if preferred_case_order is not None and case.case_id in preferred_case_order:
            packet_item["review_queue_rank"] = preferred_case_order[case.case_id] + 1
        packet_cases.append(packet_item)

    review_protocol = _annotation_review_protocol(review_phase, packet_cases)
    for item in packet_cases:
        item["review_protocol"] = dict(review_protocol)

    packet_metadata = {
        key: value
        for key, value in {
            "review_phase": review_phase,
            "packet_purpose": packet_purpose,
        }.items()
        if value
    }
    packet_id = _annotation_packet_id(dataset_name, filters or {}, packet_cases, packet_metadata)
    for index, item in enumerate(packet_cases, start=1):
        item["packet_id"] = packet_id
        item["packet_case_index"] = index

    packet = {
        "ok": True,
        "schema_version": 1,
        "packet_type": "support_label_annotation_packet",
        "packet_id": packet_id,
        "dataset": dataset_name,
        "filters": filters or {},
        "n": len(packet_cases),
        "review_protocol": review_protocol,
        "packet_summary": {
            "case_ids": [item["case_id"] for item in packet_cases],
            "case_count_by_language": _count_by(packet_cases, "lang"),
            "case_count_by_case_type": _count_by(packet_cases, "case_type"),
            "case_count_by_evidence_scope": _count_by(packet_cases, "evidence_scope"),
            "case_count_by_split": _count_by(packet_cases, "split"),
            "case_count_by_priority": _count_by(packet_cases, "priority"),
            "case_count_by_review_status": _count_by(packet_cases, "review_status"),
        },
        "label_options": [
            "supported",
            "weakly_supported",
            "insufficient_evidence",
            "contradicted",
        ],
        "hidden_fields": list(HIDDEN_ANNOTATION_PACKET_FIELDS),
        "instructions": [
            "Label independently before discussion.",
            "Use only the evidence text and evidence_scope shown in this packet.",
            "Prefer conservative labels when support is uncertain.",
            "Record whether the packet evidence_scope was sufficient, and whether lawful full text is needed.",
            "Do not infer support from citation fame, source outage, or topical similarity alone.",
            "Use review_focus as non-gold guidance about the boundary to inspect; it is not a label hint.",
        ],
        "cases": packet_cases,
    }
    packet.update(packet_metadata)
    packet_digest = _annotation_packet_digest(packet)
    packet["packet_digest"] = packet_digest
    for item in packet_cases:
        item["packet_digest"] = packet_digest
    return packet


def _annotation_review_protocol(review_phase: str, packet_cases: list) -> dict:
    review_status_counts = _count_by(packet_cases, "review_status")
    single_annotated_count = int(review_status_counts.get("single_annotator", 0) or 0)
    packet_role = "second_review" if review_phase == "second_review" or single_annotated_count else "first_review"
    return {
        "schema_version": 1,
        "packet_role": packet_role,
        "independent_labeling_required": True,
        "reviewer_must_not_see_hidden_labels": True,
        "packet_target_annotator_count": 1,
        "benchmark_target_annotator_count": 2,
        "cases_already_single_annotated": single_annotated_count,
        "second_review_required_after_first_review": packet_role == "first_review",
        "adjudication_required_on_disagreement": True,
        "merge_policy": (
            "single_annotator_until_second_review; "
            "dual_annotator_agreed_or_adjudicated_before_benchmark_claims"
        ),
    }


def _annotation_packet_digest(packet: dict) -> str:
    """Return a stable digest of the exact packet content before annotation."""

    payload = {key: value for key, value in packet.items() if key != "packet_digest"}
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _annotation_packet_id(dataset_name: str, filters: dict, packet_cases: list, packet_metadata: dict) -> str:
    signature = {
        "schema_version": 1,
        "packet_type": "support_label_annotation_packet",
        "dataset": dataset_name,
        "filters": filters,
        "packet_metadata": packet_metadata,
        "cases": [
            {
                "case_id": item.get("case_id", ""),
                "priority": item.get("priority", ""),
                "case_type": item.get("case_type", ""),
                "split": item.get("split", ""),
                "lang": item.get("lang", ""),
                "evidence_scope": item.get("evidence_scope", ""),
                "review_status": item.get("review_status", ""),
            }
            for item in packet_cases
        ],
    }
    encoded = json.dumps(signature, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "support-packet-" + hashlib.sha256(encoded).hexdigest()[:16]


def _annotation_packet_sort_key(case, preferred_case_order: Optional[dict[str, int]]) -> tuple:
    if preferred_case_order is not None and case.case_id in preferred_case_order:
        return (0, preferred_case_order[case.case_id], case.case_id)
    if preferred_case_order is not None:
        return (1, *_annotation_priority(case))
    return _annotation_priority(case)


def _format_annotation_packet(packet: dict, packet_format: str) -> str:
    if packet_format == "jsonl":
        return "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in packet.get("cases", []))
    return json.dumps(packet, indent=2, ensure_ascii=False) + "\n"


def _format_annotation_instructions(packet: dict) -> str:
    label_options = ", ".join(f"`{label}`" for label in packet.get("label_options", []))
    filters = json.dumps(packet.get("filters", {}), ensure_ascii=False, sort_keys=True)
    review_protocol = json.dumps(packet.get("review_protocol", {}), ensure_ascii=False, sort_keys=True)
    review_phase = packet.get("review_phase", "")
    packet_purpose = packet.get("packet_purpose", "")
    review_metadata = []
    if review_phase:
        review_metadata.append(f"- Review phase: `{review_phase}`")
    if packet_purpose:
        review_metadata.append(f"- Packet purpose: {packet_purpose}")
    return "\n".join(
        [
            "# CiteGuard Support Annotation Instructions",
            "",
            f"- Dataset: `{packet.get('dataset', '')}`",
            f"- Packet type: `{packet.get('packet_type', '')}`",
            f"- Packet id: `{packet.get('packet_id', '')}`",
            f"- Case count: `{packet.get('n', 0)}`",
            f"- Filters: `{filters}`",
            f"- Review protocol: `{review_protocol}`",
            f"- Packet summary: `{json.dumps(packet.get('packet_summary', {}), ensure_ascii=False, sort_keys=True)}`",
            f"- Hidden fields: `{json.dumps(packet.get('hidden_fields', []), ensure_ascii=False)}`",
            *review_metadata,
            "",
            "## Task",
            "",
            "Label each claim/evidence pair using only the evidence text and evidence_scope in the packet.",
            "Each returned row is one independent annotation; do not discuss labels before submission.",
            "Do not infer support from citation fame, venue prestige, source outage, or topical similarity alone.",
            "",
            "## Allowed Labels",
            "",
            f"Use exactly one of: {label_options}.",
            "",
            "- `supported`: the evidence directly entails the claim.",
            "- `weakly_supported`: the evidence is relevant but weaker, narrower, or less precise than the claim.",
            "- `insufficient_evidence`: the evidence does not justify the claim or the claim requires unavailable full text.",
            "- `contradicted`: the evidence directly conflicts with the claim.",
            "",
            "When unsure, choose the more conservative label. In particular, avoid `supported` unless the evidence is explicit.",
            "",
            "## Fields To Fill",
            "",
            "- `annotation.annotator_id`: required stable reviewer id.",
            "- `annotation.annotator_label`: required label from the allowed set.",
            "- `annotation.rationale`: short explanation citing the evidence text.",
            "- `annotation.confidence`: optional low/medium/high or numeric confidence.",
            "- `annotation.evidence_scope_assessed`: optional scope actually judged, such as abstract, full_text, mixed, or insufficient_scope.",
            "- `annotation.full_text_needed`: optional yes/no/unclear flag for claims that require lawful full-text inspection.",
            "- `annotation.notes`: optional ambiguity, scope, or full-text notes.",
            "- `review_focus`: non-gold guidance about the support boundary to inspect; do not treat it as a label hint.",
            "- `review_queue_rank`, when present, is assignment priority from eval triage; do not treat it as a label hint.",
            "- `review_protocol`: machine-readable assignment protocol; do not edit it.",
            "",
            "## Do Not Modify",
            "",
            "Do not edit `case_id`, `claim`, `evidence`, `evidence_scope`, `case_type`, `split`, `priority`, `review_focus`, `review_phase`, `packet_purpose`, `review_protocol`, or `source_locator`.",
            "Also do not edit `packet_id`, `packet_digest`, `packet_case_index`, or `review_queue_rank`; they tie returned annotations back to the archived reviewer batch.",
            "The packet intentionally omits dataset gold labels and adjudicated labels; do not request or reconstruct them before labeling.",
            "",
            "## Return Checklist",
            "",
            "- Every returned row has `annotation.annotator_id`.",
            "- Every returned row has one valid `annotation.annotator_label`.",
            "- Rationale is present for every `supported`, `weakly_supported`, or `contradicted` label.",
            "- Scope-sensitive cases record `annotation.evidence_scope_assessed` and `annotation.full_text_needed` when applicable.",
            "- Claims needing unavailable full text are labeled `insufficient_evidence`, not guessed.",
            "",
        ]
    )


def _build_audit_report(
    sidecar: dict,
    cases: list,
    summary: dict,
    dataset_name: str,
    dataset_path: str,
    existing_sidecar_path: str,
    include_context: bool = False,
    filters: Optional[dict] = None,
) -> dict:
    cases_by_id = {case.case_id: case for case in cases}
    sidecar_by_id = {
        str(item.get("case_id")): item
        for item in sidecar.get("cases", [])
        if isinstance(item, dict) and item.get("case_id")
    }
    unreviewed = []
    high_risk_unreviewed = []
    full_text_required_unreviewed = []
    policy_boundary_unreviewed = []
    for case in sorted(cases, key=_annotation_priority):
        item = sidecar_by_id.get(case.case_id, {})
        if item.get("adjudication_status") != "not_human_reviewed":
            continue
        entry = {
            "case_id": case.case_id,
            "priority": _case_priority_label(case),
            "gold": case.gold,
            "case_type": case.case_type,
            "evidence_scope": case.evidence_scope,
            "lang": case.lang,
            "split": case.split,
            "label_notes": case.label_notes,
        }
        if include_context:
            entry["claim"] = case.claim
            entry["evidence"] = case.evidence
        unreviewed.append(entry)
        if entry["priority"] == "high":
            high_risk_unreviewed.append(entry)
        if case.case_type == "full_text_required":
            full_text_required_unreviewed.append(entry)
        if case.case_type == "weak_set_boundary":
            policy_boundary_unreviewed.append(entry)

    reviewed_count = sum(
        1
        for item in sidecar_by_id.values()
        if item.get("case_id") in cases_by_id and item.get("adjudication_status") != "not_human_reviewed"
    )
    active_filters = filters or {}
    high_risk_unreviewed_by_language_case_type = _count_by_two_keys(
        high_risk_unreviewed,
        "lang",
        "case_type",
    )
    report = {
        "ok": True,
        "dataset": dataset_name,
        "filters": active_filters,
        "summary": summary,
        "label_maturity": summary.get("label_maturity", {}),
        "reviewed_count": reviewed_count,
        "unreviewed_count": len(unreviewed),
        "high_risk_unreviewed_count": len(high_risk_unreviewed),
        "unreviewed_by_case_type": _count_by(unreviewed, "case_type"),
        "unreviewed_by_language": _count_by(unreviewed, "lang"),
        "unreviewed_by_split": _count_by(unreviewed, "split"),
        "high_risk_unreviewed_by_language": _count_by(high_risk_unreviewed, "lang"),
        "high_risk_unreviewed_by_language_case_type": high_risk_unreviewed_by_language_case_type,
        "full_text_required_unreviewed_count": len(full_text_required_unreviewed),
        "full_text_required_unreviewed_by_language": _count_by(full_text_required_unreviewed, "lang"),
        "full_text_required_unreviewed": full_text_required_unreviewed,
        "policy_boundary_unreviewed_count": len(policy_boundary_unreviewed),
        "policy_boundary_unreviewed_by_language": _count_by(policy_boundary_unreviewed, "lang"),
        "policy_boundary_unreviewed": policy_boundary_unreviewed,
        "high_risk_unreviewed": high_risk_unreviewed,
        "unreviewed": unreviewed,
        "next_actions": _next_actions(unreviewed),
    }
    recommended_packets = _recommended_annotation_packets(
        dataset_path=dataset_path,
        existing_sidecar_path=existing_sidecar_path,
        filters=active_filters,
        high_risk_unreviewed=high_risk_unreviewed,
        full_text_required_unreviewed=full_text_required_unreviewed,
        policy_boundary_unreviewed=policy_boundary_unreviewed,
        label_maturity=summary.get("label_maturity", {}),
    )
    report["recommended_packets"] = recommended_packets
    report["review_plan"] = _build_review_plan(
        dataset_path=dataset_path,
        existing_sidecar_path=existing_sidecar_path,
        high_risk_unreviewed=high_risk_unreviewed,
        full_text_required_unreviewed=full_text_required_unreviewed,
        policy_boundary_unreviewed=policy_boundary_unreviewed,
        label_maturity=summary.get("label_maturity", {}),
        high_risk_review=summary.get("high_risk_review", {}),
        recommended_packets=recommended_packets,
    )
    return report


def _build_review_plan(
    *,
    dataset_path: str,
    existing_sidecar_path: str,
    high_risk_unreviewed: list,
    full_text_required_unreviewed: list,
    policy_boundary_unreviewed: list,
    label_maturity: dict,
    high_risk_review: dict,
    recommended_packets: list,
) -> dict:
    """Build a machine-readable path from synthetic labels to reviewed release evidence."""

    packet_by_id = {str(item.get("id")): item for item in recommended_packets if isinstance(item, dict)}
    first_review_case_ids = _unique_case_ids([*high_risk_unreviewed, *policy_boundary_unreviewed])
    first_review_packet_ids = [
        packet_id
        for packet_id in (
            "high_risk_unreviewed_balanced",
            "full_text_required_unreviewed",
            "policy_boundary_unreviewed",
        )
        if packet_id in packet_by_id
    ]
    first_review_packet_ids.extend(
        sorted(
            packet_id
            for packet_id in packet_by_id
            if packet_id.startswith("high_risk_unreviewed_") and packet_id != "high_risk_unreviewed_balanced"
        )
    )
    first_review_packet_ids = _unique_strings(first_review_packet_ids)
    single_annotator_count = _safe_int(label_maturity.get("single_annotator_count"))
    dual_annotated_count = _safe_int(label_maturity.get("dual_annotated_count"))
    reviewed_count = _safe_int(label_maturity.get("reviewed_count"))
    unresolved_disagreement_count = _safe_int(label_maturity.get("unresolved_disagreement_count"))
    supported_disagreement_count = _safe_int(label_maturity.get("supported_disagreement_count"))
    high_risk_reviewed = _safe_int(high_risk_review.get("reviewed_count"))
    high_risk_unreviewed_count = len(high_risk_unreviewed)
    high_risk_unreviewed_by_language_case_type = _count_by_two_keys(
        high_risk_unreviewed,
        "lang",
        "case_type",
    )

    first_review_status = "ready" if first_review_case_ids else "complete"
    second_review_status = "ready" if single_annotator_count else (
        "waiting_for_first_review" if first_review_case_ids else "complete"
    )
    adjudication_status = "ready" if unresolved_disagreement_count else (
        "waiting_for_dual_annotation" if first_review_case_ids or single_annotator_count else "complete"
    )
    release_gate_status = "ready_to_raise" if (
        reviewed_count > 0 and high_risk_unreviewed_count == 0 and unresolved_disagreement_count == 0
    ) else "blocked"

    phases = [
        {
            "id": "first_review_high_risk",
            "status": first_review_status,
            "candidate_case_count": len(first_review_case_ids),
            "candidate_case_ids": first_review_case_ids,
            "candidate_case_count_by_language_case_type": high_risk_unreviewed_by_language_case_type,
            "recommended_packet_ids": first_review_packet_ids,
            "exit_criteria": "Every high-risk and policy-boundary case has at least one independent human annotation.",
        },
        {
            "id": "second_review",
            "status": second_review_status,
            "candidate_case_count": single_annotator_count,
            "recommended_packet_ids": ["single_annotator_second_reviewer"]
            if "single_annotator_second_reviewer" in packet_by_id
            else [],
            "exit_criteria": "High-risk reviewed cases have two independent annotator labels or an explicit adjudication path.",
        },
        {
            "id": "adjudication",
            "status": adjudication_status,
            "candidate_case_count": unresolved_disagreement_count,
            "supported_disagreement_count": supported_disagreement_count,
            "command_template": _adjudication_command_template(
                dataset_path=dataset_path,
                existing_sidecar_path=existing_sidecar_path,
            ),
            "exit_criteria": "All dual-annotator disagreements are resolved by an adjudicator before benchmark claims.",
        },
        {
            "id": "raise_release_gates",
            "status": release_gate_status,
            "candidate_case_count": high_risk_unreviewed_count,
            "suggested_thresholds": {
                "min_human_reviewed": max(1, reviewed_count),
                "min_high_risk_reviewed": max(1, high_risk_reviewed),
                "max_unresolved_disagreements": 0,
                "max_supported_disagreements": 0,
            },
            "command_template": _release_gate_command_template(
                dataset_path=dataset_path,
                existing_sidecar_path=existing_sidecar_path,
            ),
            "exit_criteria": "Release gates require nonzero reviewed coverage, high-risk review coverage, and zero unresolved supported-label disagreements.",
        },
    ]
    return {
        "schema_version": 1,
        "status": release_gate_status,
        "next_phase": _next_review_phase(phases),
        "human_reviewed": reviewed_count,
        "dual_annotated": dual_annotated_count,
        "high_risk_reviewed": high_risk_reviewed,
        "high_risk_unreviewed": high_risk_unreviewed_count,
        "high_risk_unreviewed_by_language_case_type": high_risk_unreviewed_by_language_case_type,
        "full_text_required_unreviewed": len(full_text_required_unreviewed),
        "policy_boundary_unreviewed": len(policy_boundary_unreviewed),
        "phases": phases,
    }


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _unique_case_ids(rows: list) -> list[str]:
    seen = set()
    case_ids = []
    for row in rows:
        case_id = str(row.get("case_id", "")).strip() if isinstance(row, dict) else ""
        if not case_id or case_id in seen:
            continue
        seen.add(case_id)
        case_ids.append(case_id)
    return case_ids


def _unique_strings(values: list[str]) -> list[str]:
    seen = set()
    unique = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _next_review_phase(phases: list[dict]) -> str:
    for phase in phases:
        if phase.get("status") in {"ready", "ready_to_raise"}:
            return str(phase.get("id", ""))
    for phase in phases:
        if str(phase.get("status", "")).startswith("waiting_"):
            return str(phase.get("id", ""))
    return "complete"


def _adjudication_command_template(*, dataset_path: str, existing_sidecar_path: str) -> list[str]:
    command = [
        "python3",
        "scripts/prepare_support_label_sidecar.py",
        "--dataset",
        dataset_path,
    ]
    if existing_sidecar_path:
        command.extend(["--existing-sidecar", existing_sidecar_path])
    command.extend(
        [
            "--apply-adjudications",
            "experiments/resolved-support-label-adjudications.json",
            "--output",
            "data/eval/support_eval_label_sidecar.adjudicated.json",
        ]
    )
    return command


def _release_gate_command_template(*, dataset_path: str, existing_sidecar_path: str) -> list[str]:
    command = [
        "python3",
        "scripts/eval_support.py",
        "--validate-only",
        "--dataset",
        dataset_path,
    ]
    if existing_sidecar_path:
        command.extend(["--label-sidecar", existing_sidecar_path])
    command.extend(
        [
            "--min-sidecar-coverage",
            "1.0",
            "--min-human-reviewed",
            "<required-count>",
            "--min-high-risk-reviewed",
            "<required-high-risk-count>",
            "--max-unresolved-disagreements",
            "0",
            "--max-supported-disagreements",
            "0",
        ]
    )
    return command


def _recommended_annotation_packets(
    *,
    dataset_path: str,
    existing_sidecar_path: str,
    filters: dict,
    high_risk_unreviewed: list,
    full_text_required_unreviewed: list,
    policy_boundary_unreviewed: list,
    label_maturity: dict,
) -> list:
    recommendations = []
    if high_risk_unreviewed:
        recommendations.append(
            _recommended_packet(
                packet_id="high_risk_unreviewed_balanced",
                purpose="Assign a balanced first-review packet for unreviewed high-risk support cases.",
                dataset_path=dataset_path,
                existing_sidecar_path=existing_sidecar_path,
                filters=filters,
                extra_args=[
                    "--priority",
                    "high",
                    "--unreviewed-only",
                    "--limit-per-language",
                    "1",
                    "--limit-per-case-type",
                    "1",
                    "--limit-per-evidence-scope",
                    "1",
                ],
                output_stem="support-label-packet-high-risk-unreviewed-balanced",
                candidate_rows=high_risk_unreviewed,
            )
        )
        for language, rows in _group_rows_by(high_risk_unreviewed, "lang").items():
            recommendations.append(
                _recommended_packet(
                    packet_id=f"high_risk_unreviewed_{language}",
                    purpose=f"Assign first-review packet for unreviewed high-risk `{language}` cases.",
                    dataset_path=dataset_path,
                    existing_sidecar_path=existing_sidecar_path,
                    filters=filters,
                    extra_args=["--priority", "high", "--lang", language, "--unreviewed-only"],
                    output_stem=f"support-label-packet-high-risk-unreviewed-{language}",
                    candidate_rows=rows,
                )
            )
            for case_type, slice_rows in _group_rows_by(rows, "case_type").items():
                slice_id = f"high_risk_unreviewed_{_packet_slug(language)}_{_packet_slug(case_type)}"
                recommendations.append(
                    _recommended_packet(
                        packet_id=slice_id,
                        purpose=(
                            "Assign first-review packet for unreviewed high-risk "
                            f"`{language}` `{case_type}` cases."
                        ),
                        dataset_path=dataset_path,
                        existing_sidecar_path=existing_sidecar_path,
                        filters=filters,
                        extra_args=[
                            "--priority",
                            "high",
                            "--lang",
                            language,
                            "--case-type",
                            case_type,
                            "--unreviewed-only",
                        ],
                        output_stem=(
                            "support-label-packet-high-risk-unreviewed-"
                            f"{_packet_slug(language)}-{_packet_slug(case_type)}"
                        ),
                        candidate_rows=slice_rows,
                    )
                )
    if full_text_required_unreviewed:
        recommendations.append(
            _recommended_packet(
                packet_id="full_text_required_unreviewed",
                purpose=(
                    "Assign first-review packet for cases where abstract-level evidence may be "
                    "insufficient and lawful full-text inspection is required."
                ),
                dataset_path=dataset_path,
                existing_sidecar_path=existing_sidecar_path,
                filters=filters,
                extra_args=["--case-type", "full_text_required", "--unreviewed-only", "--limit", "10"],
                output_stem="support-label-packet-full-text-required-unreviewed",
                candidate_rows=full_text_required_unreviewed,
            )
        )
    if policy_boundary_unreviewed:
        recommendations.append(
            _recommended_packet(
                packet_id="policy_boundary_unreviewed",
                purpose=(
                    "Assign first-review packet for citation-set policy boundaries where "
                    "multiple weak citations must stay tentative."
                ),
                dataset_path=dataset_path,
                existing_sidecar_path=existing_sidecar_path,
                filters=filters,
                extra_args=["--case-type", "weak_set_boundary", "--unreviewed-only", "--limit", "10"],
                output_stem="support-label-packet-policy-boundary-unreviewed",
                candidate_rows=policy_boundary_unreviewed,
            )
        )
    single_annotator_count = int(label_maturity.get("single_annotator_count") or 0)
    if single_annotator_count > 0:
        recommendations.append(
            _recommended_packet(
                packet_id="single_annotator_second_reviewer",
                purpose="Assign a second-reviewer packet for cases with exactly one annotator label.",
                dataset_path=dataset_path,
                existing_sidecar_path=existing_sidecar_path,
                filters=filters,
                extra_args=["--review-status", "single_annotator", "--limit", "10"],
                output_stem="support-label-packet-second-reviewer",
                candidate_rows=[],
                candidate_case_count=single_annotator_count,
                review_phase="second_review",
            )
        )
    return recommendations


def _recommended_packet(
    *,
    packet_id: str,
    purpose: str,
    dataset_path: str,
    existing_sidecar_path: str,
    filters: dict,
    extra_args: list[str],
    output_stem: str,
    candidate_rows: list,
    candidate_case_count: Optional[int] = None,
    review_phase: str = "first_review_high_risk",
) -> dict:
    output_path = f"experiments/{output_stem}.json"
    instructions_path = f"experiments/{output_stem}-instructions.md"
    command = [
        "python3",
        "scripts/prepare_support_label_sidecar.py",
        "--dataset",
        dataset_path,
    ]
    if existing_sidecar_path:
        command.extend(["--existing-sidecar", existing_sidecar_path])
    command.append("--annotation-packet")
    if review_phase:
        command.extend(["--review-phase", review_phase])
    command.extend(["--packet-purpose", purpose])
    command.extend(_selection_filter_args(filters, extra_args))
    command.extend(extra_args)
    command.extend(["--output", output_path, "--instructions-output", instructions_path])
    case_ids = [str(item.get("case_id")) for item in candidate_rows if item.get("case_id")]
    return {
        "id": packet_id,
        "purpose": purpose,
        "candidate_case_count": candidate_case_count if candidate_case_count is not None else len(case_ids),
        "candidate_case_ids": case_ids,
        "command": command,
        "output": output_path,
        "instructions_output": instructions_path,
    }


def _packet_slug(value: str) -> str:
    slug = []
    for character in str(value).strip().lower():
        if character.isalnum():
            slug.append(character)
        elif slug and slug[-1] != "_":
            slug.append("_")
    return "".join(slug).strip("_") or "unknown"


def _selection_filter_args(filters: dict, extra_args: list[str]) -> list[str]:
    args = []
    extra_flags = {value for value in extra_args if value.startswith("--")}
    for key, flag in (
        ("priority", "--priority"),
        ("split", "--split"),
        ("case_type", "--case-type"),
        ("lang", "--lang"),
        ("case_id", "--case-id"),
    ):
        if flag in extra_flags:
            continue
        values = filters.get(key)
        if not values:
            continue
        if not isinstance(values, list):
            values = [values]
        for value in values:
            args.extend([flag, str(value)])
    return args


def _group_rows_by(rows: list, field: str) -> dict:
    grouped = {}
    for row in rows:
        key = str(row.get(field, "")).strip()
        if not key:
            continue
        grouped.setdefault(key, []).append(row)
    return dict(sorted(grouped.items()))


def _build_audit_gate(
    report: dict,
    *,
    fail_on_high_risk_unreviewed: bool,
    fail_on_high_risk_unreviewed_languages: list[str],
    fail_on_full_text_required_unreviewed: bool,
    fail_on_policy_boundary_unreviewed: bool,
) -> dict:
    failures = []
    language_thresholds = sorted(
        {str(lang).strip().lower() for lang in fail_on_high_risk_unreviewed_languages if str(lang).strip()}
    )
    if fail_on_high_risk_unreviewed and report.get("high_risk_unreviewed_count", 0) > 0:
        failures.append(
            {
                "code": "high_risk_unreviewed",
                "message": "High-risk support-label cases remain unreviewed.",
                "actual": report.get("high_risk_unreviewed_count", 0),
                "case_ids": [item.get("case_id") for item in report.get("high_risk_unreviewed", [])],
            }
        )
    if fail_on_full_text_required_unreviewed and report.get("full_text_required_unreviewed_count", 0) > 0:
        failures.append(
            {
                "code": "full_text_required_unreviewed",
                "message": "Abstract/full-text boundary support-label cases remain unreviewed.",
                "actual": report.get("full_text_required_unreviewed_count", 0),
                "case_ids": [item.get("case_id") for item in report.get("full_text_required_unreviewed", [])],
            }
        )
    if fail_on_policy_boundary_unreviewed and report.get("policy_boundary_unreviewed_count", 0) > 0:
        failures.append(
            {
                "code": "policy_boundary_unreviewed",
                "message": "Weak citation-set policy-boundary cases remain unreviewed.",
                "actual": report.get("policy_boundary_unreviewed_count", 0),
                "case_ids": [item.get("case_id") for item in report.get("policy_boundary_unreviewed", [])],
            }
        )
    by_language = report.get("high_risk_unreviewed_by_language", {})
    if not isinstance(by_language, dict):
        by_language = {}
    high_risk_rows = report.get("high_risk_unreviewed", [])
    for language in language_thresholds:
        actual = int(by_language.get(language, 0))
        if actual <= 0:
            continue
        failures.append(
            {
                "code": "high_risk_unreviewed_by_language",
                "message": "High-risk support-label cases for a language remain unreviewed.",
                "language": language,
                "actual": actual,
                "case_ids": [
                    item.get("case_id")
                    for item in high_risk_rows
                    if str(item.get("lang", "")).strip().lower() == language
                ],
            }
        )
    return {
        "ok": not failures,
        "thresholds": {
            "fail_on_high_risk_unreviewed": fail_on_high_risk_unreviewed,
            "fail_on_high_risk_unreviewed_languages": language_thresholds,
            "fail_on_full_text_required_unreviewed": fail_on_full_text_required_unreviewed,
            "fail_on_policy_boundary_unreviewed": fail_on_policy_boundary_unreviewed,
        },
        "metrics": {
            "unreviewed_count": report.get("unreviewed_count", 0),
            "high_risk_unreviewed_count": report.get("high_risk_unreviewed_count", 0),
            "full_text_required_unreviewed_count": report.get("full_text_required_unreviewed_count", 0),
            "policy_boundary_unreviewed_count": report.get("policy_boundary_unreviewed_count", 0),
            "unreviewed_by_language": report.get("unreviewed_by_language", {}),
            "high_risk_unreviewed_by_language": by_language,
            "high_risk_unreviewed_by_language_case_type": report.get(
                "high_risk_unreviewed_by_language_case_type",
                {},
            ),
            "full_text_required_unreviewed_by_language": report.get("full_text_required_unreviewed_by_language", {}),
            "policy_boundary_unreviewed_by_language": report.get("policy_boundary_unreviewed_by_language", {}),
        },
        "failures": failures,
    }


def _annotation_priority(case) -> tuple:
    return (
        {
            "contradiction": 0,
            "hard_negative": 1,
            "full_text_required": 2,
            "weak_set_boundary": 3,
            "contradiction_set": 4,
            "weak_support": 5,
            "direct_support": 6,
            "set_aggregation": 7,
            "metadata_only": 8,
            "unrelated_negative": 9,
            "standard": 10,
        }.get(case.case_type, 8),
        {"test": 0, "dev": 1, "train": 2}.get(case.split, 3),
        case.case_id,
    )


def _filter_cases(
    cases: list,
    priorities: Optional[list[str]] = None,
    splits: Optional[list[str]] = None,
    case_types: Optional[list[str]] = None,
    languages: Optional[list[str]] = None,
    case_ids: Optional[list[str]] = None,
    limit: Optional[int] = None,
    limit_per_language: Optional[int] = None,
    limit_per_case_type: Optional[int] = None,
    limit_per_evidence_scope: Optional[int] = None,
) -> list:
    selected = []
    language_counts = {}
    case_type_counts = {}
    evidence_scope_counts = {}
    priorities_set = set(priorities or [])
    splits_set = set(splits or [])
    case_types_set = set(case_types or [])
    languages_set = set(languages or [])
    case_ids_set = set(case_ids or [])
    for case in cases:
        if priorities_set and _case_priority_label(case) not in priorities_set:
            continue
        if splits_set and case.split not in splits_set:
            continue
        if case_types_set and case.case_type not in case_types_set:
            continue
        if languages_set and case.lang not in languages_set:
            continue
        if case_ids_set and case.case_id not in case_ids_set:
            continue
        if limit_per_language is not None and language_counts.get(case.lang, 0) >= limit_per_language:
            continue
        if limit_per_case_type is not None and case_type_counts.get(case.case_type, 0) >= limit_per_case_type:
            continue
        if (
            limit_per_evidence_scope is not None
            and evidence_scope_counts.get(case.evidence_scope, 0) >= limit_per_evidence_scope
        ):
            continue
        selected.append(case)
        language_counts[case.lang] = language_counts.get(case.lang, 0) + 1
        case_type_counts[case.case_type] = case_type_counts.get(case.case_type, 0) + 1
        evidence_scope_counts[case.evidence_scope] = evidence_scope_counts.get(case.evidence_scope, 0) + 1
        if limit is not None and len(selected) >= limit:
            break
    return selected


def _filter_existing_sidecar(existing: dict, cases: list) -> dict:
    selected_ids = {case.case_id for case in cases}
    return {
        key: value
        for key, value in existing.items()
        if key != "cases"
    } | {
        "cases": [
            item
            for item in existing.get("cases", [])
            if isinstance(item, dict) and str(item.get("case_id", "")) in selected_ids
        ]
    }


def _filter_cases_by_review_status(cases: list, existing: Optional[dict], review_statuses: list[str]) -> list:
    status_set = set(review_statuses or [])
    if not status_set:
        return list(cases)
    if not existing:
        return list(cases) if "not_human_reviewed" in status_set else []
    sidecar_by_id = {
        str(item.get("case_id")): item
        for item in existing.get("cases", [])
        if isinstance(item, dict) and item.get("case_id")
    }
    selected = []
    for case in cases:
        item = sidecar_by_id.get(case.case_id)
        status = item.get("adjudication_status") if item is not None else "not_human_reviewed"
        if status in status_set:
            selected.append(case)
    return selected


def _filter_summary(args: argparse.Namespace) -> dict:
    filters = {}
    if args.from_review_queue:
        filters["from_review_queue"] = True
        filters["review_backend"] = args.review_backend
        filters["review_queue_case_ids"] = list(getattr(args, "_review_queue_case_ids", []))
    if args.priority:
        filters["priority"] = list(args.priority)
    if args.split:
        filters["split"] = list(args.split)
    if args.case_type:
        filters["case_type"] = list(args.case_type)
    if args.lang:
        filters["lang"] = list(args.lang)
    if args.case_id:
        filters["case_id"] = list(args.case_id)
    if args.unreviewed_only:
        filters["unreviewed_only"] = True
    if args.review_status:
        filters["review_status"] = list(args.review_status)
    if args.limit is not None:
        filters["limit"] = args.limit
    if args.limit_per_language is not None:
        filters["limit_per_language"] = args.limit_per_language
    if args.limit_per_case_type is not None:
        filters["limit_per_case_type"] = args.limit_per_case_type
    if args.limit_per_evidence_scope is not None:
        filters["limit_per_evidence_scope"] = args.limit_per_evidence_scope
    return filters


def _review_queue_case_ids(dataset_path: str, splits: Optional[list[str]], backend_name: str) -> list[str]:
    from citeguard.verification.support_eval import (
        load_support_eval,
        run_support_eval_fixture_report,
        run_support_eval_report,
    )

    cases = load_support_eval(dataset_path)
    if splits:
        split_set = set(splits)
        cases = [case for case in cases if case.split in split_set]
    if backend_name == "fixture":
        report = run_support_eval_fixture_report(cases)
    else:
        if backend_name == "heuristic":
            from citeguard.verifiers import HeuristicSupportBackend

            backend = HeuristicSupportBackend()
        else:
            from citeguard.runtime import build_configured_support_backend

            backend = build_configured_support_backend()
        report = run_support_eval_report(cases, backend)
    queue = report.get("review_queue", []) if isinstance(report, dict) else []
    return [
        str(item.get("case_id"))
        for item in queue
        if isinstance(item, dict) and str(item.get("case_id", "")).strip()
    ]


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be a positive integer") from None
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _validate_case_ids(case_ids: Optional[list[str]], cases: list, parser: argparse.ArgumentParser) -> None:
    if not case_ids:
        return
    known = {case.case_id for case in cases}
    missing = [case_id for case_id in case_ids if case_id not in known]
    if missing:
        parser.error(f"unknown --case-id value(s): {', '.join(missing)}")


def _case_priority_label(case) -> str:
    if case.case_type in {"contradiction", "hard_negative", "full_text_required", "contradiction_set"}:
        return "high"
    if case.case_type in {"weak_support", "weak_set_boundary", "direct_support", "set_aggregation"}:
        return "medium"
    return "normal"


def _review_focus(case) -> str:
    focus_by_type = {
        "contradiction": "Check whether the evidence directly conflicts with the claim.",
        "contradiction_set": "Check whether any cited evidence conflicts with the claim and should dominate the aggregate.",
        "hard_negative": "Check whether related evidence actually supports the stronger claim or only discusses a nearby topic.",
        "full_text_required": "Check whether the claim requires methods, eligibility, safety, or follow-up details absent from the shown evidence.",
        "weak_support": "Check whether topical relevance is too weak, narrow, or title-only for full support.",
        "weak_set_boundary": "Check whether multiple weak citations remain tentative instead of becoming full support.",
        "metadata_only": "Check whether metadata fields prove the claim or merely describe source/status context.",
        "unrelated_negative": "Check whether the evidence is unrelated to the claim.",
        "direct_support": "Check whether the evidence explicitly entails every important part of the claim.",
        "set_aggregation": "Check how the citation-level verdicts combine without hiding unresolved items.",
    }
    scope_suffix = {
        "title": " Treat title-only evidence as weak unless the claim is only topical.",
        "abstract": " Do not infer methods or full-text details from the abstract.",
        "metadata": " Do not infer claim support from metadata alone.",
        "metadata_snippet": " Treat source snippets as evidence only for the exact fact they state.",
        "full_text": " Use the provided lawful full-text excerpt, not unstated outside content.",
        "mixed": " Keep each citation's scope visible when aggregating.",
        "mixed_with_full_text": " Distinguish abstract evidence from the provided full-text excerpt.",
        "none": " Abstain unless another shown field supplies evidence.",
    }
    return focus_by_type.get(case.case_type, "Check whether the evidence explicitly supports the claim.") + scope_suffix.get(
        case.evidence_scope,
        "",
    )


def _count_by(items: list, field: str) -> dict:
    counts = {}
    for item in items:
        key = str(item.get(field, ""))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _count_by_two_keys(items: list, outer_field: str, inner_field: str) -> dict:
    counts = {}
    for item in items:
        outer_key = str(item.get(outer_field, "")).strip()
        inner_key = str(item.get(inner_field, "")).strip()
        if not outer_key or not inner_key:
            continue
        nested = counts.setdefault(outer_key, {})
        nested[inner_key] = nested.get(inner_key, 0) + 1
    return {
        outer_key: dict(sorted(inner_counts.items()))
        for outer_key, inner_counts in sorted(counts.items())
    }


def _next_actions(unreviewed: list) -> list:
    if not unreviewed:
        return ["All sidecar cases have human-review provenance."]
    actions = [
        "Review high-priority contradiction, hard_negative, and full_text_required cases first.",
        "Record annotator_labels before discussion, then update adjudication_status and adjudicated_label.",
    ]
    if any(item.get("split") == "test" for item in unreviewed):
        actions.append("Resolve test split provenance before using the benchmark for release claims.")
    if any(item.get("case_type") == "full_text_required" for item in unreviewed):
        actions.append("Assign full-text-boundary review before treating abstract-level support as sufficient.")
    if any(item.get("case_type") == "weak_set_boundary" for item in unreviewed):
        actions.append("Assign policy-boundary review for weak citation-set cases before claiming multi-citation support readiness.")
    return actions


if __name__ == "__main__":
    raise SystemExit(main())
