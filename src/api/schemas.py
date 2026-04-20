"""API request and response schemas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from src.orchestrator import AgentRunResult, AgentTask


@dataclass(frozen=True)
class GenerateRequest:
    """Input payload for generation."""

    topic: str
    section_count: int = 3
    retrieval_top_k: int = 5
    candidate_top_k: int = 3

    def to_task(self) -> AgentTask:
        return AgentTask(
            topic=self.topic,
            section_count=self.section_count,
            retrieval_top_k=self.retrieval_top_k,
            candidate_top_k=self.candidate_top_k,
        )


@dataclass(frozen=True)
class GenerateResponse:
    """API response payload."""

    sections: List[Dict[str, str]]
    references: List[str]
    audit_report: Dict[str, object]

    @classmethod
    def from_result(cls, result: AgentRunResult) -> "GenerateResponse":
        return cls(
            sections=[
                {"section_id": section.section_id, "title": section.title, "text": section.text}
                for section in result.sections
            ],
            references=result.references,
            audit_report=result.audit_report,
        )
