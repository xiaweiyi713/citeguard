#!/usr/bin/env python3
"""Validate and score CiteGuard skill-trigger decisions."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


class TriggerEvalError(ValueError):
    """Raised when the dataset or prediction contract is invalid."""


def load_cases(path: str) -> List[Dict[str, Any]]:
    data = _load_json(Path(path))
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise TriggerEvalError("trigger dataset must be a schema_version=1 JSON object")
    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise TriggerEvalError("trigger dataset must contain a non-empty cases list")

    cases: List[Dict[str, Any]] = []
    seen = set()
    for index, raw in enumerate(raw_cases):
        if not isinstance(raw, dict):
            raise TriggerEvalError(f"case {index} must be an object")
        case_id = str(raw.get("id", "")).strip()
        request = str(raw.get("request", "")).strip()
        should_trigger = raw.get("should_trigger")
        if not case_id or case_id in seen:
            raise TriggerEvalError(f"case {index} has a missing or duplicate id")
        if not request:
            raise TriggerEvalError(f"case {case_id!r} has an empty request")
        if not isinstance(should_trigger, bool):
            raise TriggerEvalError(f"case {case_id!r} should_trigger must be boolean")
        seen.add(case_id)
        cases.append({"id": case_id, "request": request, "should_trigger": should_trigger})

    if not any(case["should_trigger"] for case in cases):
        raise TriggerEvalError("trigger dataset must contain at least one positive case")
    if not any(not case["should_trigger"] for case in cases):
        raise TriggerEvalError("trigger dataset must contain at least one negative case")
    return cases


def load_predictions(path: str) -> List[Dict[str, Any]]:
    prediction_path = Path(path)
    if prediction_path.suffix.lower() == ".jsonl":
        rows: List[Any] = []
        for line_number, line in enumerate(prediction_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise TriggerEvalError(f"invalid prediction JSONL at line {line_number}: {exc}") from exc
    else:
        data = _load_json(prediction_path)
        rows = data.get("predictions") if isinstance(data, dict) else data
    if not isinstance(rows, list) or not rows:
        raise TriggerEvalError("predictions must be a non-empty JSON list or object with predictions")

    predictions: List[Dict[str, Any]] = []
    seen = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise TriggerEvalError(f"prediction {index} must be an object")
        case_id = str(row.get("id", row.get("case_id", ""))).strip()
        triggered = row.get("triggered")
        if not case_id or case_id in seen:
            raise TriggerEvalError(f"prediction {index} has a missing or duplicate id")
        if not isinstance(triggered, bool):
            raise TriggerEvalError(f"prediction {case_id!r} triggered must be boolean")
        seen.add(case_id)
        predictions.append({"id": case_id, "triggered": triggered})
    return predictions


def score_predictions(
    cases: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
    *,
    allow_partial: bool = False,
) -> Dict[str, Any]:
    by_id = {case["id"]: case for case in cases}
    predicted = {row["id"]: row["triggered"] for row in predictions}
    unknown = sorted(set(predicted) - set(by_id))
    missing = sorted(set(by_id) - set(predicted))
    if unknown:
        raise TriggerEvalError(f"predictions contain unknown case ids: {', '.join(unknown)}")
    if missing and not allow_partial:
        raise TriggerEvalError(f"predictions are missing case ids: {', '.join(missing)}")

    rows = []
    tp = tn = fp = fn = 0
    for case in cases:
        if case["id"] not in predicted:
            continue
        expected = bool(case["should_trigger"])
        actual = bool(predicted[case["id"]])
        if expected and actual:
            tp += 1
        elif not expected and not actual:
            tn += 1
        elif not expected and actual:
            fp += 1
        else:
            fn += 1
        rows.append(
            {
                "id": case["id"],
                "should_trigger": expected,
                "triggered": actual,
                "correct": expected == actual,
            }
        )

    evaluated = len(rows)
    positives = tp + fn
    negatives = tn + fp
    precision = _ratio(tp, tp + fp)
    positive_recall = _ratio(tp, positives)
    negative_recall = _ratio(tn, negatives)
    f1 = _ratio(2 * precision * positive_recall, precision + positive_recall)
    return {
        "evaluated_case_count": evaluated,
        "dataset_case_count": len(cases),
        "partial": evaluated != len(cases),
        "missing_case_ids": missing,
        "confusion": {"true_positive": tp, "true_negative": tn, "false_positive": fp, "false_negative": fn},
        "metrics": {
            "accuracy": _ratio(tp + tn, evaluated),
            "precision": precision,
            "positive_recall": positive_recall,
            "negative_recall": negative_recall,
            "f1": f1,
        },
        "false_positive_case_ids": [row["id"] for row in rows if row["triggered"] and not row["should_trigger"]],
        "false_negative_case_ids": [row["id"] for row in rows if not row["triggered"] and row["should_trigger"]],
        "cases": rows,
    }


def evaluate_gate(
    report: Dict[str, Any],
    *,
    min_accuracy: float,
    min_positive_recall: float,
    min_negative_recall: float,
) -> Dict[str, Any]:
    metrics = report["metrics"]
    thresholds = {
        "accuracy": min_accuracy,
        "positive_recall": min_positive_recall,
        "negative_recall": min_negative_recall,
    }
    failures = [
        {"metric": metric, "actual": metrics[metric], "threshold": threshold}
        for metric, threshold in thresholds.items()
        if metrics[metric] < threshold
    ]
    return {"ok": not failures, "thresholds": thresholds, "failures": failures}


def prediction_template(cases: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    return {
        "schema_version": 1,
        "instructions": "Run each request through the target agent and replace triggered with true or false.",
        "predictions": [
            {"id": case["id"], "request": case["request"], "triggered": None}
            for case in cases
        ],
    }


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TriggerEvalError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise TriggerEvalError(f"invalid JSON in {path}: {exc}") from exc


def _ratio(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _rate(value: str) -> float:
    try:
        rate = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected a number from 0 to 1") from exc
    if not 0.0 <= rate <= 1.0:
        raise argparse.ArgumentTypeError("expected a number from 0 to 1")
    return rate


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and score CiteGuard skill-trigger decisions.")
    parser.add_argument("--dataset", default="data/eval/skill_trigger_eval.json")
    parser.add_argument("--predictions", help="JSON or JSONL agent trigger decisions to score.")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--write-template", help="Write a prediction template for an agent evaluator.")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--min-accuracy", type=_rate, default=1.0)
    parser.add_argument("--min-positive-recall", type=_rate, default=1.0)
    parser.add_argument("--min-negative-recall", type=_rate, default=1.0)
    args = parser.parse_args(argv)

    try:
        cases = load_cases(args.dataset)
        if args.write_template:
            Path(args.write_template).write_text(
                json.dumps(prediction_template(cases), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        if args.validate_only or not args.predictions:
            payload = {
                "schema_version": 1,
                "ok": True,
                "dataset": args.dataset,
                "case_count": len(cases),
                "positive_count": sum(1 for case in cases if case["should_trigger"]),
                "negative_count": sum(1 for case in cases if not case["should_trigger"]),
                "prediction_template": args.write_template or None,
                "next_action": "score_agent_predictions" if not args.predictions else "continue",
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0

        report = score_predictions(cases, load_predictions(args.predictions), allow_partial=args.allow_partial)
        gate = evaluate_gate(
            report,
            min_accuracy=args.min_accuracy,
            min_positive_recall=args.min_positive_recall,
            min_negative_recall=args.min_negative_recall,
        )
        payload = {"schema_version": 1, "ok": gate["ok"], "dataset": args.dataset, **report, "gate": gate}
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if gate["ok"] else 1
    except TriggerEvalError as exc:
        print(json.dumps({"schema_version": 1, "ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
