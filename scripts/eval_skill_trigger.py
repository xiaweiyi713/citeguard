#!/usr/bin/env python3
"""Validate and score CiteGuard skill-trigger decisions from real client runs."""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from citeguard.skill_install import skill_digest


SUPPORTED_DATASET_VERSIONS = {1, 2}
SUPPORTED_CLIENTS = ("codex", "claude", "cursor")
PREDICTION_SCHEMA_VERSION = 2
FORBIDDEN_PREDICTION_FIELDS = frozenset(
    {"adjudicated_label", "expected", "expected_triggered", "gold", "gold_label", "should_trigger"}
)
REQUIRED_BUNDLED_CATEGORIES = {
    "citation_identity",
    "metadata_audit",
    "document_audit",
    "claim_support",
    "counterevidence",
    "format_only",
    "prose_edit",
    "general_discussion",
    "citation_generation",
    "research_planning",
}


class TriggerEvalError(ValueError):
    """Raised when the dataset or prediction contract is invalid."""


def _is_sha256_digest(value: str) -> bool:
    return len(value) == 71 and value.startswith("sha256:") and all(
        char in "0123456789abcdef" for char in value[7:]
    )


def _request_digest(request: str) -> str:
    return "sha256:" + hashlib.sha256(request.encode("utf-8")).hexdigest()


def _valid_timestamp(value: str) -> bool:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    return parsed.tzinfo is not None


def load_dataset(path: str) -> Dict[str, Any]:
    """Load a versioned trigger suite and validate its non-model metadata."""

    data = _load_json(Path(path))
    if not isinstance(data, dict) or data.get("schema_version") not in SUPPORTED_DATASET_VERSIONS:
        raise TriggerEvalError("trigger dataset must be a schema_version=1 or schema_version=2 JSON object")
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
        case = {"id": case_id, "request": request, "should_trigger": should_trigger}
        for field in ("language", "category"):
            value = raw.get(field)
            if value is None:
                if data["schema_version"] >= 2:
                    raise TriggerEvalError(f"case {case_id!r} is missing required {field}")
                continue
            value = str(value).strip()
            if not value:
                raise TriggerEvalError(f"case {case_id!r} {field} must be a non-empty string when supplied")
            case[field] = value
        seen.add(case_id)
        cases.append(case)

    if not any(case["should_trigger"] for case in cases):
        raise TriggerEvalError("trigger dataset must contain at least one positive case")
    if not any(not case["should_trigger"] for case in cases):
        raise TriggerEvalError("trigger dataset must contain at least one negative case")

    suite = {
        "schema_version": data["schema_version"],
        "suite_id": str(data.get("suite_id", "citeguard-skill-trigger")),
        "minimum_case_count": data.get("minimum_case_count"),
        "target_clients": data.get("target_clients", []),
        "cases": cases,
    }
    _validate_suite_metadata(suite)
    return suite


def load_cases(path: str) -> List[Dict[str, Any]]:
    """Return cases for compatibility with existing evaluator callers."""

    return list(load_dataset(path)["cases"])


def dataset_summary(cases: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize coverage without making any claim about client performance."""

    rows = list(cases)
    by_language: Dict[str, int] = {}
    by_category: Dict[str, int] = {}
    for case in rows:
        language = str(case.get("language", "unspecified"))
        category = str(case.get("category", "unspecified"))
        by_language[language] = by_language.get(language, 0) + 1
        by_category[category] = by_category.get(category, 0) + 1
    return {
        "case_count": len(rows),
        "positive_count": sum(1 for case in rows if case["should_trigger"]),
        "negative_count": sum(1 for case in rows if not case["should_trigger"]),
        "by_language": dict(sorted(by_language.items())),
        "by_category": dict(sorted(by_category.items())),
    }


def load_prediction_artifact(
    path: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Optional[int]]:
    """Load decisions, run metadata, and the optional top-level schema version."""

    prediction_path = Path(path)
    run: Dict[str, Any] = {}
    artifact_schema_version: Optional[int] = None
    rows: Any
    if prediction_path.suffix.lower() == ".jsonl":
        rows = []
        for line_number, line in enumerate(prediction_path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise TriggerEvalError(f"invalid prediction JSONL at line {line_number}: {exc}") from exc
    else:
        data = _load_json(prediction_path)
        if isinstance(data, dict):
            rows = data.get("predictions")
            raw_schema_version = data.get("schema_version")
            if raw_schema_version is not None:
                if not isinstance(raw_schema_version, int) or isinstance(raw_schema_version, bool):
                    raise TriggerEvalError("prediction schema_version must be an integer when supplied")
                artifact_schema_version = raw_schema_version
            for field in ("adjudicated_labels", "expected", "gold", "labels"):
                if field in data:
                    raise TriggerEvalError(f"prediction artifact must not contain gold-like field: {field}")
            raw_run = data.get("run", {})
            if raw_run is None:
                raw_run = {}
            if not isinstance(raw_run, dict):
                raise TriggerEvalError("prediction run metadata must be an object")
            run = {str(key): value for key, value in raw_run.items()}
        else:
            rows = data
    if not isinstance(rows, list) or not rows:
        raise TriggerEvalError("predictions must be a non-empty JSON list or object with predictions")

    predictions: List[Dict[str, Any]] = []
    seen = set()
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise TriggerEvalError(f"prediction {index} must be an object")
        if artifact_schema_version == PREDICTION_SCHEMA_VERSION and "id" not in row:
            raise TriggerEvalError(f"schema_version=2 prediction {index} must use an id field")
        forbidden = sorted(FORBIDDEN_PREDICTION_FIELDS.intersection(row))
        if forbidden:
            raise TriggerEvalError(
                f"prediction {index} contains gold-like field(s): {', '.join(forbidden)}"
            )
        case_id = str(row.get("id", row.get("case_id", ""))).strip()
        triggered = row.get("triggered")
        if not case_id or case_id in seen:
            raise TriggerEvalError(f"prediction {index} has a missing or duplicate id")
        if not isinstance(triggered, bool):
            raise TriggerEvalError(f"prediction {case_id!r} triggered must be boolean")
        seen.add(case_id)
        normalized = {"id": case_id, "triggered": triggered}
        if "request" in row:
            request = row.get("request")
            if not isinstance(request, str) or not request.strip():
                raise TriggerEvalError(f"prediction {case_id!r} request must be a non-empty string when supplied")
            normalized["request"] = request
        if "request_digest" in row:
            request_digest = str(row.get("request_digest", "")).strip()
            if not _is_sha256_digest(request_digest):
                raise TriggerEvalError(f"prediction {case_id!r} request_digest must use a sha256: digest")
            normalized["request_digest"] = request_digest
        predictions.append(normalized)
    return predictions, run, artifact_schema_version


def load_prediction_run(path: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Return prediction rows and run metadata for compatibility callers."""

    predictions, run, _ = load_prediction_artifact(path)
    return predictions, run


def load_predictions(path: str) -> List[Dict[str, Any]]:
    """Return prediction rows for compatibility with existing callers."""

    return load_prediction_run(path)[0]


def score_predictions(
    cases: List[Dict[str, Any]],
    predictions: List[Dict[str, Any]],
    *,
    allow_partial: bool = False,
    require_request_provenance: bool = False,
) -> Dict[str, Any]:
    prediction_ids = [row.get("id") for row in predictions]
    if len(prediction_ids) != len(set(prediction_ids)):
        raise TriggerEvalError("predictions contain duplicate case ids")
    by_id = {case["id"]: case for case in cases}
    predicted = {row["id"]: row["triggered"] for row in predictions}
    unknown = sorted(set(predicted) - set(by_id))
    missing = sorted(set(by_id) - set(predicted))
    if unknown:
        raise TriggerEvalError(f"predictions contain unknown case ids: {', '.join(unknown)}")
    if missing and not allow_partial:
        raise TriggerEvalError(f"predictions are missing case ids: {', '.join(missing)}")

    for prediction in predictions:
        case = by_id[prediction["id"]]
        request = prediction.get("request")
        request_digest = prediction.get("request_digest")
        if request is not None and request != case["request"]:
            raise TriggerEvalError(f"prediction {prediction['id']!r} request does not match the evaluation suite")
        if request_digest is not None and request_digest != _request_digest(case["request"]):
            raise TriggerEvalError(f"prediction {prediction['id']!r} request_digest does not match the evaluation suite")
        if require_request_provenance and request_digest != _request_digest(case["request"]):
            raise TriggerEvalError(
                f"prediction {prediction['id']!r} must include the exact request_digest from the evaluation suite"
            )

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
        "request_provenance_checked": bool(require_request_provenance or any("request_digest" in row for row in predictions)),
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


def prediction_template(
    cases: Iterable[Dict[str, Any]],
    *,
    client: str = "",
    suite_id: str = "",
    dataset_digest: str = "",
    skill_digest_value: str = "",
) -> Dict[str, Any]:
    """Build a label-blind capture template for one actual client run."""

    if client and client not in SUPPORTED_CLIENTS:
        raise TriggerEvalError("template client must be one of: " + ", ".join(SUPPORTED_CLIENTS))
    suite_id = suite_id.strip()
    dataset_digest = dataset_digest.strip()
    skill_digest_value = skill_digest_value.strip()
    for field, value in (("dataset_digest", dataset_digest), ("skill_digest", skill_digest_value)):
        if value and not _is_sha256_digest(value):
            raise TriggerEvalError(f"template {field} must use a sha256: digest when supplied")

    return {
        "schema_version": 2,
        "run": {
            "client": client,
            "client_version": "",
            "suite_id": suite_id,
            "skill_digest": skill_digest_value,
            "recorded_at": "",
            "dataset_digest": dataset_digest,
        },
        "instructions": (
            "Run every request through the named target client, replace triggered with true or false, "
            "and fill run metadata from the actual environment. Do not infer labels from this template."
        ),
        "predictions": [
            {
                "id": case["id"],
                "request": case["request"],
                "request_digest": _request_digest(case["request"]),
                "triggered": None,
            }
            for case in cases
        ],
    }


def validate_run_metadata(
    run: Dict[str, Any],
    *,
    expected_client: str = "",
    expected_suite_id: str = "",
    expected_dataset_digest: str = "",
    expected_skill_digest: str = "",
) -> Dict[str, str]:
    """Require enough provenance to call predictions a real client run."""

    for field, value in (("dataset_digest", expected_dataset_digest), ("skill_digest", expected_skill_digest)):
        if value and not _is_sha256_digest(value):
            raise TriggerEvalError(f"expected {field} must use a sha256: digest")
    required = ("client", "client_version", "skill_digest", "recorded_at", "dataset_digest")
    normalized = {field: str(run.get(field, "")).strip() for field in required}
    normalized["suite_id"] = str(run.get("suite_id", "")).strip()
    missing = [field for field in required if not normalized[field]]
    if expected_suite_id and not normalized["suite_id"]:
        missing.append("suite_id")
    if missing:
        raise TriggerEvalError("prediction run metadata is missing: " + ", ".join(missing))
    if normalized["client"] not in SUPPORTED_CLIENTS:
        raise TriggerEvalError("prediction run client must be one of: " + ", ".join(SUPPORTED_CLIENTS))
    if expected_client and normalized["client"] != expected_client:
        raise TriggerEvalError(
            f"prediction run client {normalized['client']!r} does not match --client {expected_client!r}"
        )
    if expected_suite_id and normalized["suite_id"] != expected_suite_id:
        raise TriggerEvalError("prediction run suite_id does not match the evaluation suite")
    for field in ("skill_digest", "dataset_digest"):
        if not _is_sha256_digest(normalized[field]):
            raise TriggerEvalError(f"prediction run {field} must use a sha256: digest")
    if not _valid_timestamp(normalized["recorded_at"]):
        raise TriggerEvalError("prediction run recorded_at must be an ISO-8601 timestamp with a timezone")
    if expected_dataset_digest and normalized["dataset_digest"] != expected_dataset_digest:
        raise TriggerEvalError("prediction run dataset_digest does not match the evaluation suite")
    if expected_skill_digest and normalized["skill_digest"] != expected_skill_digest:
        raise TriggerEvalError("prediction run skill_digest does not match the evaluated Skill bundle")
    return normalized


def _validate_suite_metadata(suite: Dict[str, Any]) -> None:
    if suite["schema_version"] < 2:
        return
    minimum_case_count = suite["minimum_case_count"]
    if not isinstance(minimum_case_count, int) or isinstance(minimum_case_count, bool) or minimum_case_count < 1:
        raise TriggerEvalError("schema_version=2 trigger dataset requires a positive integer minimum_case_count")
    if len(suite["cases"]) < minimum_case_count:
        raise TriggerEvalError(
            f"trigger dataset has {len(suite['cases'])} cases, below its minimum_case_count {minimum_case_count}"
        )
    clients = suite["target_clients"]
    if not isinstance(clients, list) or set(clients) != set(SUPPORTED_CLIENTS):
        raise TriggerEvalError("schema_version=2 trigger dataset target_clients must list codex, claude, and cursor")
    summary = dataset_summary(suite["cases"])
    if not {"en", "zh"}.issubset(summary["by_language"]):
        raise TriggerEvalError("schema_version=2 trigger dataset must include both en and zh cases")
    missing_categories = sorted(REQUIRED_BUNDLED_CATEGORIES - set(summary["by_category"]))
    if missing_categories:
        raise TriggerEvalError("schema_version=2 trigger dataset is missing categories: " + ", ".join(missing_categories))


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise TriggerEvalError(f"could not read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise TriggerEvalError(f"invalid JSON in {path}: {exc}") from exc


def _dataset_digest(path: str) -> str:
    try:
        payload = Path(path).read_bytes()
    except OSError as exc:
        raise TriggerEvalError(f"could not read {path}: {exc}") from exc
    return "sha256:" + hashlib.sha256(payload).hexdigest()


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


def _expected_skill_digest(*, skill_path: str = "", explicit_digest: str = "") -> str:
    if skill_path and explicit_digest:
        raise TriggerEvalError("use either --skill-path or --expected-skill-digest, not both")
    if explicit_digest:
        normalized = explicit_digest.strip()
        if not _is_sha256_digest(normalized):
            raise TriggerEvalError("--expected-skill-digest must use a sha256: digest")
        return normalized
    if not skill_path:
        return ""
    try:
        return skill_digest(skill_path)
    except (OSError, ValueError) as exc:
        raise TriggerEvalError(f"could not calculate --skill-path digest: {exc}") from exc


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate and score CiteGuard skill-trigger decisions.")
    parser.add_argument("--dataset", default="data/eval/skill_trigger_eval.json")
    parser.add_argument("--predictions", help="JSON or JSONL agent trigger decisions to score.")
    parser.add_argument("--client", choices=SUPPORTED_CLIENTS, help="Expected client for a real prediction run.")
    parser.add_argument(
        "--require-run-metadata",
        action="store_true",
        help="Require client/version/skill/dataset/time provenance before scoring a client run.",
    )
    parser.add_argument(
        "--skill-path",
        help="Exact installed Skill directory to hash and bind to a real-client prediction artifact.",
    )
    parser.add_argument(
        "--expected-skill-digest",
        help="Pre-recorded sha256 Skill tree digest when the evaluated installation is unavailable locally.",
    )
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--write-template", help="Write a label-blind prediction template for one target client.")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--min-accuracy", type=_rate, default=1.0)
    parser.add_argument("--min-positive-recall", type=_rate, default=1.0)
    parser.add_argument("--min-negative-recall", type=_rate, default=1.0)
    args = parser.parse_args(argv)

    try:
        if args.write_template and args.predictions:
            raise TriggerEvalError("--write-template cannot be combined with --predictions")
        suite = load_dataset(args.dataset)
        cases = suite["cases"]
        coverage = dataset_summary(cases)
        dataset_digest = _dataset_digest(args.dataset)
        expected_skill_digest = _expected_skill_digest(
            skill_path=args.skill_path or "",
            explicit_digest=args.expected_skill_digest or "",
        )
        if args.write_template:
            Path(args.write_template).write_text(
                json.dumps(
                    prediction_template(
                        cases,
                        client=args.client or "",
                        suite_id=suite["suite_id"],
                        dataset_digest=dataset_digest,
                        skill_digest_value=expected_skill_digest,
                    ),
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n",
                encoding="utf-8",
            )
        if args.validate_only or not args.predictions:
            payload = {
                "schema_version": 2,
                "ok": True,
                "dataset": args.dataset,
                "suite_id": suite["suite_id"],
                "target_clients": suite["target_clients"],
                "coverage": coverage,
                "dataset_digest": dataset_digest,
                "expected_skill_digest": expected_skill_digest or None,
                "prediction_artifact_schema_version": PREDICTION_SCHEMA_VERSION,
                "prediction_template": args.write_template or None,
                "next_action": "collect_real_client_predictions" if not args.predictions else "continue",
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0

        predictions, run, artifact_schema_version = load_prediction_artifact(args.predictions)
        strict_provenance = bool(
            args.client or args.require_run_metadata or expected_skill_digest
        )
        if strict_provenance:
            if not expected_skill_digest:
                raise TriggerEvalError(
                    "strict prediction scoring requires --skill-path or --expected-skill-digest"
                )
            if artifact_schema_version != PREDICTION_SCHEMA_VERSION:
                raise TriggerEvalError(
                    "strict prediction runs require a top-level schema_version=2 JSON artifact"
                )
            run = validate_run_metadata(
                run,
                expected_client=args.client or "",
                expected_suite_id=suite["suite_id"],
                expected_dataset_digest=dataset_digest,
                expected_skill_digest=expected_skill_digest,
            )
        report = score_predictions(
            cases,
            predictions,
            allow_partial=args.allow_partial,
            require_request_provenance=strict_provenance,
        )
        gate = evaluate_gate(
            report,
            min_accuracy=args.min_accuracy,
            min_positive_recall=args.min_positive_recall,
            min_negative_recall=args.min_negative_recall,
        )
        payload = {
            "schema_version": 2,
            "ok": gate["ok"],
            "dataset": args.dataset,
            "suite_id": suite["suite_id"],
            "coverage": coverage,
            "dataset_digest": dataset_digest,
            "expected_skill_digest": expected_skill_digest or None,
            "prediction_artifact_schema_version": PREDICTION_SCHEMA_VERSION,
            "strict_provenance": strict_provenance,
            "agent_run": run or None,
            **report,
            "gate": gate,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if gate["ok"] else 1
    except (OSError, TriggerEvalError) as exc:
        print(json.dumps({"schema_version": 2, "ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
