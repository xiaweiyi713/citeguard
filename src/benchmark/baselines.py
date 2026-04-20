"""Simple baselines used for comparison."""

from __future__ import annotations

from typing import Dict, List

from src.citation import CitationFormatter
from src.orchestrator import AgentTask
from src.retrieval import HybridRetriever
from src.retrieval.scholarly_clients import MetadataSource


class DirectWriteBaseline:
    """Generates plain text without evidence validation."""

    def generate(self, task: AgentTask) -> Dict[str, List[str]]:
        paragraph = (
            f"{task.topic} has attracted broad attention, and many recent papers report progress "
            "across retrieval, verification, and evaluation."
        )
        return {"sections": [paragraph], "references": []}


class RAGWriteBaseline:
    """Retrieves papers and cites them without running verifiers."""

    def __init__(self, metadata_source: MetadataSource) -> None:
        self.retriever = HybridRetriever(metadata_source.all_records())
        self.formatter = CitationFormatter()

    def generate(self, task: AgentTask) -> Dict[str, List[str]]:
        results = self.retriever.search(task.topic, top_k=min(3, task.retrieval_top_k))
        references = [self.formatter.format_reference(result.citation) for result in results]
        inline = " ".join(self.formatter.format_inline(result.citation) for result in results)
        section = f"Recent work on {task.topic} spans several representative studies. {inline}".strip()
        return {"sections": [section], "references": references}
