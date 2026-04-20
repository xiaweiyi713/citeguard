"""Tests for multi-source scholarly adapters."""

import unittest

from src.graph import CitationRecord
from src.retrieval import MetadataSourceRetriever
from src.retrieval.scholarly_clients import (
    InMemoryMetadataSource,
    MultiSourceMetadataSource,
    OpenAlexMetadataSource,
)


class FakeHTTPClient:
    def get_json(self, url, params=None, headers=None, use_cache=True, timeout=None):
        return {
            "results": [
                {
                    "id": "https://openalex.org/W123",
                    "display_name": "GhostCite: Citation Validity in the Age of Large Language Models",
                    "authorships": [{"author": {"display_name": "Zhe Xu"}}],
                    "publication_year": 2026,
                    "primary_location": {
                        "landing_page_url": "https://example.org/paper",
                        "source": {"display_name": "arXiv"},
                    },
                    "abstract_inverted_index": {
                        "phantom": [0],
                        "references": [1],
                        "and": [2],
                        "fabricated": [3],
                        "metadata": [4],
                    },
                }
            ]
        }

    def get_text(self, url, params=None, headers=None, use_cache=True, timeout=None):
        if url == "https://example.org/paper":
            return """
            <html>
              <head><meta name="description" content="This paper measures citation validity in large language models." /></head>
              <body>
                <p>We analyze phantom references and fabricated metadata in large language models.</p>
              </body>
            </html>
            """
        return ""


class ScholarlySourceTests(unittest.TestCase):
    def test_multi_source_search_deduplicates_and_merges_records(self):
        left = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="left-1",
                    title="GhostCite: Citation Validity in the Age of Large Language Models",
                    authors=["Zhe Xu"],
                    year=2026,
                    doi="10.1000/ghostcite",
                )
            ]
        )
        right = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="right-1",
                    title="GhostCite: Citation Validity in the Age of Large Language Models",
                    authors=["Zhe Xu"],
                    year=2026,
                    doi="10.1000/ghostcite",
                    abstract="This paper studies phantom references and fabricated metadata.",
                    venue="arXiv",
                )
            ]
        )

        source = MultiSourceMetadataSource([left, right])
        results = source.search("phantom references fabricated metadata", top_k=3)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].doi, "10.1000/ghostcite")
        self.assertTrue(results[0].abstract)

    def test_metadata_source_retriever_scores_source_search_results(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="match",
                    title="OpenScholar: Synthesizing Scientific Literature with Retrieval-Augmented Language Models",
                    authors=["Akari Asai"],
                    year=2024,
                    abstract="Scientific literature synthesis and citation hallucinations.",
                ),
                CitationRecord(
                    citation_id="other",
                    title="Generic Language Model Paper",
                    authors=["Other Author"],
                    year=2023,
                    abstract="General language modeling work.",
                ),
            ]
        )
        retriever = MetadataSourceRetriever(source)
        results = retriever.search("scientific literature citation hallucinations", top_k=2)
        self.assertEqual(results[0].citation.citation_id, "match")

    def test_multi_source_lookup_merges_evidence_chunks(self):
        left = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="left-1",
                    title="GhostCite: Citation Validity in the Age of Large Language Models",
                    authors=["Zhe Xu"],
                    year=2026,
                    doi="10.1000/ghostcite",
                    metadata={
                        "evidence_chunks": [
                            {
                                "text": "We analyze phantom references in large language models.",
                                "source_field": "openalex_remote_1_paragraph_1",
                                "source_url": "https://openalex.example/paper",
                            }
                        ]
                    },
                )
            ]
        )
        right = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="right-1",
                    title="GhostCite: Citation Validity in the Age of Large Language Models",
                    authors=["Zhe Xu"],
                    year=2026,
                    doi="10.1000/ghostcite",
                    metadata={
                        "evidence_chunks": [
                            {
                                "text": "The study also measures fabricated metadata across many models.",
                                "source_field": "crossref_remote_1_paragraph_1",
                                "source_url": "https://crossref.example/paper",
                            }
                        ]
                    },
                )
            ]
        )
        source = MultiSourceMetadataSource([left, right])
        match = source.lookup(
            CitationRecord(
                citation_id="candidate",
                title="GhostCite: Citation Validity in the Age of Large Language Models",
                authors=["Zhe Xu"],
                year=2026,
                doi="10.1000/ghostcite",
            )
        )
        self.assertIsNotNone(match)
        self.assertEqual(len(match.metadata["evidence_chunks"]), 2)
        self.assertEqual(len(match.metadata["evidence_spans"]), 2)

    def test_openalex_search_harvests_remote_evidence_chunks(self):
        source = OpenAlexMetadataSource(http_client=FakeHTTPClient())
        results = source.search("phantom references fabricated metadata", top_k=1)
        self.assertEqual(len(results), 1)
        chunks = results[0].metadata.get("evidence_chunks", [])
        self.assertTrue(chunks)
        self.assertTrue(any("phantom references" in chunk["text"].lower() for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
