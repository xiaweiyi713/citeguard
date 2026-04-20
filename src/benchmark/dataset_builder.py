"""Simple benchmark dataset construction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from src.graph import CitationRecord


@dataclass(frozen=True)
class BenchmarkExample:
    """A small benchmark example for evaluating cite-safe generation."""

    example_id: str
    topic: str
    claim: str
    expected_action: str
    candidate_titles: List[str]


class CiteGuardBenchBuilder:
    """Creates a lightweight prototype benchmark from citation records."""

    def build_from_records(self, topic: str, records: List[CitationRecord]) -> List[BenchmarkExample]:
        examples: List[BenchmarkExample] = []
        for index, record in enumerate(records, start=1):
            examples.append(
                BenchmarkExample(
                    example_id=f"example-{index}",
                    topic=topic,
                    claim=f"Prior work on {topic} studies {record.title.lower()}.",
                    expected_action="cite",
                    candidate_titles=[record.title],
                )
            )
        return examples
