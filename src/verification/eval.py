"""Offline, reproducible evaluation of the verification pipeline."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Tuple

from src.graph import CitationRecord
from src.retrieval.scholarly_clients import InMemoryMetadataSource

from .parse import parse_citation
from .verify import verify_citation


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    expected: str
    fields: Dict
    note: str = ""


def load_eval(path: str) -> Tuple[List[CitationRecord], List[EvalCase]]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    corpus = [CitationRecord(**record) for record in data["corpus"]]
    cases = [
        EvalCase(case["id"], case["expected"], case["fields"], case.get("note", ""))
        for case in data["cases"]
    ]
    return corpus, cases


def run_eval(corpus: List[CitationRecord], cases: List[EvalCase]) -> Dict[str, float]:
    source = InMemoryMetadataSource(corpus)
    preds: List[Tuple[str, str]] = []
    for case in cases:
        candidate = parse_citation(**case.fields)
        result = verify_citation(candidate, source)
        preds.append((case.expected, result.verdict.value))
    return compute_metrics(preds)


def _precision_recall(preds: List[Tuple[str, str]], label: str) -> Tuple[float, float]:
    tp = sum(1 for expected, predicted in preds if expected == label and predicted == label)
    fp = sum(1 for expected, predicted in preds if expected != label and predicted == label)
    fn = sum(1 for expected, predicted in preds if expected == label and predicted != label)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    return precision, recall


def compute_metrics(preds: List[Tuple[str, str]]) -> Dict[str, float]:
    n = len(preds)
    correct = sum(1 for expected, predicted in preds if expected == predicted)
    fab_p, fab_r = _precision_recall(preds, "not_found")
    meta_p, meta_r = _precision_recall(preds, "metadata_mismatch")
    verified_total = sum(1 for expected, _ in preds if expected == "verified")
    false_accusations = sum(
        1 for expected, predicted in preds if expected == "verified" and predicted == "not_found"
    )
    far = false_accusations / verified_total if verified_total else 0.0
    return {
        "n": n,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "fabrication_precision": round(fab_p, 4),
        "fabrication_recall": round(fab_r, 4),
        "metadata_error_precision": round(meta_p, 4),
        "metadata_error_recall": round(meta_r, 4),
        "false_accusation_rate": round(far, 4),
    }
