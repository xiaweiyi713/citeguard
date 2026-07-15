"""Topic-level outline planning for scientific writing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class OutlineSection:
    """A planned section in the generated academic text."""

    section_id: str
    title: str
    purpose: str


class OutlinePlanner:
    """Builds a deterministic outline for the first prototype."""

    DEFAULT_SECTION_TEMPLATES = (
        ("Background", "Introduce the task landscape and motivate why the topic matters."),
        (
            "Recent Advances",
            "Summarize representative technical progress, with emphasis on methods and evaluation.",
        ),
        (
            "Open Challenges",
            "Describe unresolved weaknesses, risks, and research opportunities.",
        ),
    )

    def plan(self, topic: str, section_count: int = 3) -> List[OutlineSection]:
        if section_count <= 0:
            raise ValueError("section_count must be positive")

        sections: List[OutlineSection] = []
        for index, (title, purpose) in enumerate(self.DEFAULT_SECTION_TEMPLATES[:section_count], start=1):
            sections.append(
                OutlineSection(
                    section_id=f"section-{index}",
                    title=f"{topic}: {title}",
                    purpose=purpose,
                )
            )
        return sections
