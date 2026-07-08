"""Tests for citation parsing."""

import unittest

from citeguard.verification.parse import extract_arxiv_id, extract_doi, extract_year, parse_citation


class ParseTests(unittest.TestCase):
    def test_extract_doi_from_free_text(self):
        text = "Some Paper. https://doi.org/10.1145/3539618.3591708 (2023)"
        self.assertEqual(extract_doi(text), "10.1145/3539618.3591708")

    def test_extract_doi_strips_sentence_trailing_punctuation(self):
        text = "Some Paper. DOI: 10.48550/arxiv.2602.06718."
        self.assertEqual(extract_doi(text), "10.48550/arxiv.2602.06718")

    def test_extract_arxiv_id_from_free_text(self):
        self.assertEqual(extract_arxiv_id("See arXiv:2411.14199 for details"), "2411.14199")

    def test_extract_arxiv_id_from_common_url_forms(self):
        cases = {
            "See https://arxiv.org/pdf/1706.03762.pdf.": "1706.03762",
            "Mirror: arxiv.org/abs/1706.03762v5": "1706.03762v5",
            "HTML preview HTTPS://ARXIV.ORG/HTML/2401.01234V2": "2401.01234v2",
            "Classic preprint arXiv:hep-th/9901001v2.": "hep-th/9901001v2",
            "Category URL https://arxiv.org/abs/math.AG/0601001": "math.ag/0601001",
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(extract_arxiv_id(text), expected)

    def test_extract_year(self):
        self.assertEqual(extract_year("Published in 2024 at NeurIPS"), 2024)
        self.assertIsNone(extract_year("no year here"))

    def test_parse_structured_fields(self):
        record = parse_citation(
            title="OpenScholar",
            authors=["Akari Asai"],
            year=2024,
            doi="https://doi.org/10.1000/XYZ",
        )
        self.assertEqual(record.title, "OpenScholar")
        self.assertEqual(record.doi, "10.1000/xyz")
        self.assertEqual(record.authors, ["Akari Asai"])
        self.assertTrue(record.metadata["title_explicit"])

    def test_parse_structured_doi_accepts_common_resolver_prefixes(self):
        for value in (
            "DOI: 10.1000/XYZ.",
            "HTTPS://DOI.ORG/10.1000/XYZ",
            "https://dx.doi.org/10.1000/XYZ;",
            "doi: https://doi.org/10.1000/XYZ",
        ):
            with self.subTest(value=value):
                record = parse_citation(title="OpenScholar", doi=value)
                self.assertEqual(record.doi, "10.1000/xyz")

    def test_parse_structured_arxiv_accepts_common_resolver_prefixes(self):
        cases = {
            "arXiv: 1706.03762V5.": "1706.03762v5",
            "HTTPS://ARXIV.ORG/ABS/1706.03762V5.": "1706.03762v5",
            "https://arxiv.org/pdf/1706.03762.pdf;": "1706.03762",
            "arxiv.org/html/2401.01234V2": "2401.01234v2",
            "arXiv: hep-th/9901001V2.": "hep-th/9901001v2",
            "https://arxiv.org/pdf/math.AG/0601001.pdf": "math.ag/0601001",
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                record = parse_citation(title="Attention Is All You Need", arxiv_id=value)
                self.assertEqual(record.arxiv_id, expected)

    def test_parse_carries_user_provided_support_evidence(self):
        record = parse_citation(
            title="A Real Paper",
            abstract="The abstract describes the setup.",
            evidence_chunks=[
                {
                    "text": "The lawful full-text excerpt reports the main result.",
                    "source_field": "user_full_text_excerpt_1",
                    "evidence_scope": "full_text",
                }
            ],
        )

        self.assertEqual(record.abstract, "The abstract describes the setup.")
        self.assertEqual(record.metadata["evidence_chunks"][0]["evidence_scope"], "full_text")

    def test_parse_raw_text_uses_text_as_query_not_explicit_title(self):
        record = parse_citation(raw_text="Asai et al., OpenScholar, arXiv:2411.14199, 2024")
        self.assertEqual(record.arxiv_id, "2411.14199")
        self.assertEqual(record.year, 2024)
        self.assertFalse(record.metadata["title_explicit"])
        self.assertEqual(record.metadata["raw_text"], "Asai et al., OpenScholar, arXiv:2411.14199, 2024")


if __name__ == "__main__":
    unittest.main()
