"""_rank must not let a raw source relevance score dominate ranking."""

import unittest

from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource, MultiSourceMetadataSource


class RankNormalizationTests(unittest.TestCase):
    def test_huge_raw_relevance_does_not_beat_strong_title_match(self):
        strong_title = CitationRecord(
            citation_id="good", title="Attention Is All You Need",
            authors=["A"], year=2017, source="memory",
            metadata={"source_score": 5.0},
        )
        junk_high_score = CitationRecord(
            citation_id="junk", title="A Totally Different Survey of Networks",
            authors=["B"], year=2025, source="memory",
            metadata={"source_score": 15329.672},
        )
        multi = MultiSourceMetadataSource(
            [InMemoryMetadataSource([strong_title]), InMemoryMetadataSource([junk_high_score])]
        )
        ranked = multi._rank("Attention Is All You Need", [junk_high_score, strong_title])
        self.assertEqual(ranked[0].citation_id, "good")


if __name__ == "__main__":
    unittest.main()
