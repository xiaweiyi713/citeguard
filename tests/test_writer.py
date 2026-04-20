"""Tests for end-to-end writing behavior."""

import unittest

from src.graph import CitationRecord
from src.orchestrator import AgentTask, CiteGuardAgent
from src.retrieval.scholarly_clients import InMemoryMetadataSource


class WriterTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            CitationRecord(
                citation_id="openscholar",
                title="OpenScholar: Synthesizing Scientific Literature with Retrieval-Augmented Language Models",
                authors=["Akari Asai"],
                year=2024,
                venue="arXiv",
                abstract="Scientific literature synthesis with retrieval-augmented language models and citation hallucinations.",
            ),
            CitationRecord(
                citation_id="ghostcite",
                title="GhostCite: Citation Validity in the Age of Large Language Models",
                authors=["Zhe Xu"],
                year=2026,
                venue="arXiv",
                abstract="Phantom references, fabricated metadata, and citation validity in language models.",
            ),
        ]

    def test_agent_generates_sections_references_and_audit(self):
        agent = CiteGuardAgent(InMemoryMetadataSource(self.records))
        result = agent.run(AgentTask(topic="citation hallucination in scientific writing", section_count=2))
        self.assertEqual(len(result.sections), 2)
        self.assertTrue(result.references)
        self.assertEqual(result.audit_report["summary"]["claims"], 4)
        self.assertIn("Background", result.sections[0].title)


if __name__ == "__main__":
    unittest.main()
