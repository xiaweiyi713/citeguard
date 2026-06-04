"""Offline evaluation of claim-support assessment."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Dict, List, Tuple

from src.graph import CitationRecord
from src.verifiers import SupportBackend

from .support import assess_support


@dataclass(frozen=True)
class SupportCase:
    case_id: str
    claim: str
    evidence: str
    gold: str
    lang: str = ""


def load_support_eval(path: str) -> List[SupportCase]:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return [
        SupportCase(c["id"], c["claim"], c["evidence"], c["gold"], c.get("lang", ""))
        for c in data["cases"]
    ]


def run_support_eval(cases: List[SupportCase], backend: SupportBackend) -> Dict[str, float]:
    preds: List[Tuple[str, str]] = []
    for case in cases:
        paper = CitationRecord(citation_id=case.case_id, title="", abstract=case.evidence, source="eval")
        result = assess_support(case.claim, paper, backend=backend, lang=case.lang)
        preds.append((case.gold, result.verdict.value))
    return compute_support_metrics(preds)


def compute_support_metrics(preds: List[Tuple[str, str]]) -> Dict[str, float]:
    n = len(preds)
    correct = sum(1 for gold, pred in preds if gold == pred)
    supported_total = sum(1 for gold, _ in preds if gold == "supported")
    misjudged_support = sum(
        1 for gold, pred in preds if gold == "supported" and pred in ("contradicted", "insufficient_evidence")
    )
    contra_total = sum(1 for gold, _ in preds if gold == "contradicted")
    contra_hit = sum(1 for gold, pred in preds if gold == "contradicted" and pred == "contradicted")
    return {
        "n": n,
        "accuracy": round(correct / n, 4) if n else 0.0,
        "misjudged_support_rate": round(misjudged_support / supported_total, 4) if supported_total else 0.0,
        "contradiction_recall": round(contra_hit / contra_total, 4) if contra_total else 0.0,
    }
