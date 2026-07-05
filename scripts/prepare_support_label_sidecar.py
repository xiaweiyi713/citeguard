#!/usr/bin/env python3
"""Generate or complete a support-label provenance sidecar."""

from __future__ import annotations

import argparse
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
        "--case-id",
        action="append",
        default=None,
        help="Only include this stable case id; repeat for multiple cases.",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        help="Maximum number of filtered cases to include in the packet.",
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
        "--instructions-output",
        default="",
        help="With --annotation-packet, also write a Markdown instruction sheet for independent annotators.",
    )
    parser.add_argument(
        "--fail-on-high-risk-unreviewed",
        action="store_true",
        help="With --audit, exit non-zero when contradiction, hard_negative, or full_text_required cases remain unreviewed.",
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

    all_cases = load_support_label_cases(args.dataset)
    _validate_case_ids(args.case_id, all_cases, parser)
    existing = None
    if args.existing_sidecar:
        with open(args.existing_sidecar, encoding="utf-8") as handle:
            existing = json.load(handle)
        validate_support_label_sidecar(existing, all_cases)

    cases = all_cases if (args.merge_annotation_packet or args.apply_adjudications) else _filter_cases(
        all_cases,
        priorities=args.priority,
        splits=args.split,
        case_types=args.case_type,
        case_ids=args.case_id,
        limit=args.limit,
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
            include_context=args.include_context,
            filters=_filter_summary(args),
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
        if args.fail_on_high_risk_unreviewed and report["high_risk_unreviewed_count"] > 0:
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
            return cases
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
    for index, row in enumerate(annotation_rows, start=1):
        if not isinstance(row, dict):
            skipped.append({"index": index, "code": "invalid_row", "message": "Annotation row must be an object."})
            continue
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
    for case_id, annotations in sorted(grouped.items()):
        case = cases_by_id[case_id]
        labels = [item["label"] for item in annotations]
        annotator_ids = [item["annotator_id"] for item in annotations]
        duplicate_annotator_ids = sorted(
            {annotator_id for annotator_id in annotator_ids if annotator_ids.count(annotator_id) > 1}
        )
        if duplicate_annotator_ids:
            conflicts.append(
                {
                    "case_id": case_id,
                    "code": "duplicate_annotator",
                    "message": "The same annotator appears more than once for this case.",
                    "annotator_ids": duplicate_annotator_ids,
                    "annotator_labels": labels,
                }
            )
            continue
        unique_labels = sorted(set(labels))
        if len(unique_labels) > 1:
            conflicts.append(
                {
                    "case_id": case_id,
                    "code": "annotator_disagreement",
                    "message": "Annotation packet contains unresolved annotator disagreement.",
                    "dataset_gold": case.gold,
                    "annotator_labels": labels,
                }
            )
            continue
        label = unique_labels[0]
        if label != case.gold:
            conflicts.append(
                {
                    "case_id": case_id,
                    "code": "label_mismatch",
                    "message": "Annotation label does not match the current dataset gold label.",
                    "dataset_gold": case.gold,
                    "annotator_labels": labels,
                }
            )
            continue
        item = sidecar_by_id[case_id]
        item["annotator_count"] = len(annotations)
        item["annotator_labels"] = labels
        item["adjudicated_label"] = case.gold
        item["adjudication_status"] = "dual_annotator_agreed" if len(annotations) >= 2 else "single_annotator"
        item["disagreement"] = "none"
        if annotations[0].get("source_locator"):
            item["source_locator"] = annotations[0]["source_locator"]
        item["notes"] = _merged_annotation_notes(annotations)
        applied_case_ids.append(case_id)

    return {
        "ok": not conflicts and not skipped,
        "annotation_count": len(annotation_rows),
        "applied_count": len(applied_case_ids),
        "conflict_count": len(conflicts),
        "skipped_count": len(skipped),
        "applied_case_ids": applied_case_ids,
        "conflicts": conflicts,
        "skipped": skipped,
        "next_actions": _merge_next_actions(conflicts, skipped),
    }


def _annotation_summary(row: dict, annotation: dict, label: str) -> dict:
    return {
        "label": label,
        "annotator_id": str(annotation.get("annotator_id") or row.get("annotator_id") or "").strip(),
        "rationale": str(annotation.get("rationale") or row.get("rationale") or "").strip(),
        "confidence": str(annotation.get("confidence") or row.get("confidence") or "").strip(),
        "notes": str(annotation.get("notes") or row.get("notes") or "").strip(),
        "source_locator": str(row.get("source_locator", "")).strip(),
    }


def _merged_annotation_notes(annotations: list) -> str:
    parts = ["Merged from blinded annotation packet."]
    for index, item in enumerate(annotations, start=1):
        annotator = item.get("annotator_id") or f"annotator_{index}"
        details = []
        if item.get("rationale"):
            details.append(item["rationale"])
        if item.get("confidence"):
            details.append(f"confidence={item['confidence']}")
        if item.get("notes"):
            details.append(f"notes={item['notes']}")
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
        item["notes"] = _adjudication_notes(row, annotator_labels)
        applied_case_ids.append(case_id)

    return {
        "ok": not conflicts and not skipped,
        "adjudication_count": len(adjudication_rows),
        "applied_count": len(applied_case_ids),
        "conflict_count": len(conflicts),
        "skipped_count": len(skipped),
        "applied_case_ids": applied_case_ids,
        "conflicts": conflicts,
        "skipped": skipped,
        "next_actions": _adjudication_next_actions(conflicts, skipped),
    }


def _adjudication_annotator_labels(row: dict, existing_item: dict) -> list:
    labels = row.get("annotator_labels", existing_item.get("annotator_labels", []))
    if not isinstance(labels, list):
        return []
    return [str(label) for label in labels if str(label) in ALLOWED_SUPPORT_LABELS]


def _adjudication_notes(row: dict, annotator_labels: list) -> str:
    rationale = str(row.get("rationale", "") or row.get("notes", "")).strip()
    parts = [
        "Resolved adjudication from blinded annotation workflow.",
        "annotator_labels=" + ", ".join(annotator_labels),
    ]
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
) -> dict:
    """Build a blinded packet for independent support-label annotation."""

    sidecar_by_id = {
        str(item.get("case_id")): item
        for item in (existing_sidecar or {}).get("cases", [])
        if isinstance(item, dict) and item.get("case_id")
    }
    packet_cases = []
    for case in sorted(cases, key=_annotation_priority):
        sidecar_item = sidecar_by_id.get(case.case_id, {})
        packet_cases.append(
            {
                "case_id": case.case_id,
                "priority": _case_priority_label(case),
                "claim": case.claim,
                "evidence": case.evidence,
                "evidence_scope": case.evidence_scope,
                "case_type": case.case_type,
                "split": case.split,
                "lang": case.lang,
                "review_status": sidecar_item.get("adjudication_status", "not_human_reviewed"),
                "source_locator": sidecar_item.get("source_locator", ""),
                "annotation": {
                    "annotator_id": "",
                    "annotator_label": "",
                    "rationale": "",
                    "confidence": "",
                    "notes": "",
                },
            }
        )

    return {
        "ok": True,
        "schema_version": 1,
        "packet_type": "support_label_annotation_packet",
        "dataset": dataset_name,
        "filters": filters or {},
        "n": len(packet_cases),
        "label_options": [
            "supported",
            "weakly_supported",
            "insufficient_evidence",
            "contradicted",
        ],
        "instructions": [
            "Label independently before discussion.",
            "Use only the evidence text and evidence_scope shown in this packet.",
            "Prefer conservative labels when support is uncertain.",
            "Do not infer support from citation fame, source outage, or topical similarity alone.",
        ],
        "cases": packet_cases,
    }


def _format_annotation_packet(packet: dict, packet_format: str) -> str:
    if packet_format == "jsonl":
        return "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in packet.get("cases", []))
    return json.dumps(packet, indent=2, ensure_ascii=False) + "\n"


def _format_annotation_instructions(packet: dict) -> str:
    label_options = ", ".join(f"`{label}`" for label in packet.get("label_options", []))
    filters = json.dumps(packet.get("filters", {}), ensure_ascii=False, sort_keys=True)
    return "\n".join(
        [
            "# CiteGuard Support Annotation Instructions",
            "",
            f"- Dataset: `{packet.get('dataset', '')}`",
            f"- Packet type: `{packet.get('packet_type', '')}`",
            f"- Case count: `{packet.get('n', 0)}`",
            f"- Filters: `{filters}`",
            "",
            "## Task",
            "",
            "Label each claim/evidence pair using only the evidence text and evidence_scope in the packet.",
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
            "- `annotation.notes`: optional ambiguity, scope, or full-text notes.",
            "",
            "## Do Not Modify",
            "",
            "Do not edit `case_id`, `claim`, `evidence`, `evidence_scope`, `case_type`, `split`, `priority`, or `source_locator`.",
            "The packet intentionally omits dataset gold labels and adjudicated labels; do not request or reconstruct them before labeling.",
            "",
            "## Return Checklist",
            "",
            "- Every returned row has `annotation.annotator_id`.",
            "- Every returned row has one valid `annotation.annotator_label`.",
            "- Rationale is present for every `supported`, `weakly_supported`, or `contradicted` label.",
            "- Claims needing unavailable full text are labeled `insufficient_evidence`, not guessed.",
            "",
        ]
    )


def _build_audit_report(
    sidecar: dict,
    cases: list,
    summary: dict,
    dataset_name: str,
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
            "split": case.split,
            "label_notes": case.label_notes,
        }
        if include_context:
            entry["claim"] = case.claim
            entry["evidence"] = case.evidence
        unreviewed.append(entry)
        if entry["priority"] == "high":
            high_risk_unreviewed.append(entry)

    reviewed_count = sum(
        1
        for item in sidecar_by_id.values()
        if item.get("case_id") in cases_by_id and item.get("adjudication_status") != "not_human_reviewed"
    )
    return {
        "ok": True,
        "dataset": dataset_name,
        "filters": filters or {},
        "summary": summary,
        "label_maturity": summary.get("label_maturity", {}),
        "reviewed_count": reviewed_count,
        "unreviewed_count": len(unreviewed),
        "high_risk_unreviewed_count": len(high_risk_unreviewed),
        "unreviewed_by_case_type": _count_by(unreviewed, "case_type"),
        "unreviewed_by_split": _count_by(unreviewed, "split"),
        "high_risk_unreviewed": high_risk_unreviewed,
        "unreviewed": unreviewed,
        "next_actions": _next_actions(unreviewed),
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
    case_ids: Optional[list[str]] = None,
    limit: Optional[int] = None,
) -> list:
    selected = []
    priorities_set = set(priorities or [])
    splits_set = set(splits or [])
    case_types_set = set(case_types or [])
    case_ids_set = set(case_ids or [])
    for case in cases:
        if priorities_set and _case_priority_label(case) not in priorities_set:
            continue
        if splits_set and case.split not in splits_set:
            continue
        if case_types_set and case.case_type not in case_types_set:
            continue
        if case_ids_set and case.case_id not in case_ids_set:
            continue
        selected.append(case)
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


def _filter_summary(args: argparse.Namespace) -> dict:
    filters = {}
    if args.priority:
        filters["priority"] = list(args.priority)
    if args.split:
        filters["split"] = list(args.split)
    if args.case_type:
        filters["case_type"] = list(args.case_type)
    if args.case_id:
        filters["case_id"] = list(args.case_id)
    if args.limit is not None:
        filters["limit"] = args.limit
    return filters


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


def _count_by(items: list, field: str) -> dict:
    counts = {}
    for item in items:
        key = str(item.get(field, ""))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _next_actions(unreviewed: list) -> list:
    if not unreviewed:
        return ["All sidecar cases have human-review provenance."]
    actions = [
        "Review high-priority contradiction, hard_negative, and full_text_required cases first.",
        "Record annotator_labels before discussion, then update adjudication_status and adjudicated_label.",
    ]
    if any(item.get("split") == "test" for item in unreviewed):
        actions.append("Resolve test split provenance before using the benchmark for release claims.")
    return actions


if __name__ == "__main__":
    raise SystemExit(main())
