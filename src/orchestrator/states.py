"""Shared orchestration state models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from src.graph import CCEG


@dataclass(frozen=True)
class AgentTask:
    """User request processed by CiteGuard."""

    topic: str
    section_count: int = 3
    retrieval_top_k: int = 5
    candidate_top_k: int = 3


@dataclass(frozen=True)
class SectionDraft:
    """Final section content."""

    section_id: str
    title: str
    text: str


@dataclass(frozen=True)
class AgentRunResult:
    """Structured result returned by the orchestrator."""

    sections: List[SectionDraft]
    references: List[str]
    audit_report: Dict[str, object]
    graph: CCEG
