"""Data models for claim-free citation verification."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from src.graph import CitationRecord


class Verdict(str, Enum):
    """Outcome of verifying a single citation."""

    VERIFIED = "verified"
    METADATA_MISMATCH = "metadata_mismatch"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class FieldDiff:
    """Per-field comparison between the input citation and the canonical record."""

    field: str
    candidate: Any
    canonical: Any
    matches: bool


@dataclass(frozen=True)
class VerificationResult:
    """Result of verifying one citation."""

    verdict: Verdict
    confidence: float
    input_citation: CitationRecord
    canonical_record: Optional[CitationRecord]
    field_diffs: List[FieldDiff]
    suggested_citation: str
    explanation: str
    sources_checked: List[str]
    sources_responded: List[str]
    alternatives: List[CitationRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 4),
            "input": asdict(self.input_citation),
            "canonical_record": asdict(self.canonical_record) if self.canonical_record else None,
            "field_diffs": [asdict(diff) for diff in self.field_diffs],
            "suggested_citation": self.suggested_citation,
            "explanation": self.explanation,
            "sources_checked": list(self.sources_checked),
            "sources_responded": list(self.sources_responded),
            "alternatives": [asdict(record) for record in self.alternatives],
        }


@dataclass(frozen=True)
class AuditReport:
    """Result of verifying a batch of citations."""

    results: List[VerificationResult]
    summary: Dict[str, int]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": dict(self.summary),
            "results": [result.to_dict() for result in self.results],
        }
