"""Tests for retrieval components."""

import unittest

from src.graph import CitationRecord
from src.retrieval import HybridRetriever
from src.retrieval.scholarly_clients import InMemoryMetadataSource


class RetrievalTests(unittest.TestCase):
    def setUp(self):
        self.records = [
            CitationRecord(
                citation_id="ghostcite",
                title="GhostCite: Citation Validity in the Age of Large Language Models",
                authors=["Zhe Xu"],
                year=2026,
                abstract="Phantom references and fabricated metadata in language models.",
            ),
            CitationRecord(
                citation_id="openscholar",
                title="OpenScholar: Synthesizing Scientific Literature with Retrieval-Augmented Language Models",
                authors=["Akari Asai"],
                year=2024,
                abstract="Scientific literature synthesis and citation hallucinations.",
            ),
            CitationRecord(
                citation_id="generic",
                title="Reliable Evaluation for Language Agents",
                authors=["Jane Doe"],
                year=2023,
                abstract="Evaluation and tool use for language agents.",
            ),
        ]

    def test_hybrid_retriever_surfaces_relevant_paper(self):
        retriever = HybridRetriever(self.records)
        results = retriever.search("phantom references fabricated metadata", top_k=2)
        self.assertEqual(results[0].citation.citation_id, "ghostcite")

    def test_metadata_source_lookup_handles_small_title_variation(self):
        source = InMemoryMetadataSource(self.records)
        candidate = CitationRecord(
            citation_id="candidate",
            title="GhostCite Citation Validity in the Age of Large Language Models",
            authors=["Zhe Xu"],
        )
        canonical = source.lookup(candidate)
        self.assertIsNotNone(canonical)
        self.assertEqual(canonical.citation_id, "ghostcite")


if __name__ == "__main__":
    unittest.main()
