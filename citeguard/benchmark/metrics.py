"""Evaluation metrics for citation integrity."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List


@dataclass(frozen=True)
class EvaluationRecord:
    """Per-claim evaluation outcome."""

    phantom_citation: bool
    metadata_error: bool
    claim_supported: bool
    unsupported_citation: bool
    abstained: bool


class MetricsCalculator:
    """Computes the first-pass CiteGuard metrics."""

    def compute(self, records: Iterable[EvaluationRecord]) -> Dict[str, float]:
        rows: List[EvaluationRecord] = list(records)
        if not rows:
            return {
                "PCR": 0.0,
                "MCR": 0.0,
                "CSR": 0.0,
                "UCR": 0.0,
                "AU": 0.0,
                "RIS": 0.0,
            }

        count = len(rows)
        pcr = sum(record.phantom_citation for record in rows) / count
        mcr = sum(record.metadata_error for record in rows) / count
        csr = sum(record.claim_supported for record in rows) / count
        ucr = sum(record.unsupported_citation for record in rows) / count
        au = sum(record.abstained for record in rows) / count
        ris = 0.25 * (1 - pcr) + 0.2 * (1 - mcr) + 0.3 * csr + 0.15 * (1 - ucr) + 0.1 * au
        return {
            "PCR": round(pcr, 4),
            "MCR": round(mcr, 4),
            "CSR": round(csr, 4),
            "UCR": round(ucr, 4),
            "AU": round(au, 4),
            "RIS": round(ris, 4),
        }
