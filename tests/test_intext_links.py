"""Tests for Markdown/LaTeX in-text citation linking."""

from __future__ import annotations

import unittest

from citeguard.verification.extract import extract_citation_candidates
from citeguard.verification.intext import link_document_citations


class InTextLinkTests(unittest.TestCase):
    def test_markdown_numeric_citation_links_to_numbered_reference(self):
        text = (
            "Transformer-based models outperform recurrence on all tasks [1].\n\n"
            "## References\n\n"
            "1. Vaswani, A. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.\n"
        )
        bibliography = extract_citation_candidates(text, source_format="markdown")
        payload = link_document_citations(
            [{"path": "paper.md", "text": text, "source_format": "markdown"}],
            bibliography,
        )

        self.assertEqual(len(payload["body_links"]), 1)
        link = payload["body_links"][0]
        self.assertEqual(link["cite_key"], "1")
        self.assertEqual(link["link_status"], "linked")
        self.assertEqual(link["bibliography_index"], 0)
        self.assertIn("outperform recurrence on all tasks", link["sentence"])
        self.assertEqual(payload["unlinked_markers"], [])

    def test_latex_cite_key_links_to_bibtex_entry(self):
        tex = "The method outperforms all baselines \\cite{attention}.\n"
        bib = (
            "@article{attention,\n"
            "  title={Attention Is All You Need},\n"
            "  year={2017},\n"
            "  eprint={1706.03762}\n"
            "}\n"
        )
        bibliography = extract_citation_candidates(bib, source_format="bibtex")
        payload = link_document_citations(
            [
                {"path": "paper.tex", "text": tex, "source_format": "latex"},
                {"path": "refs.bib", "text": bib, "source_format": "bibtex"},
            ],
            bibliography,
        )

        self.assertEqual(payload["body_links"][0]["cite_key"], "attention")
        self.assertEqual(payload["body_links"][0]["link_status"], "linked")
        self.assertEqual(payload["unlinked_markers"], [])

    def test_missing_cite_key_is_listed_separately(self):
        tex = "We also mention an unknown paper \\cite{missing-key}.\n"
        bib = "@article{attention, title={Attention Is All You Need}, year={2017}}\n"
        bibliography = extract_citation_candidates(bib, source_format="bibtex")
        payload = link_document_citations(
            [{"path": "paper.tex", "text": tex, "source_format": "latex"}],
            bibliography,
        )

        self.assertEqual(payload["body_links"], [])
        self.assertEqual(len(payload["unlinked_markers"]), 1)
        self.assertEqual(payload["unlinked_markers"][0]["cite_key"], "missing-key")
        self.assertEqual(payload["unlinked_markers"][0]["link_status"], "unlinked")

    def test_multi_key_cite_emits_one_link_per_key(self):
        tex = "Both results are cited \\cite{attention,bert}.\n"
        bib = (
            "@article{attention, title={Attention Is All You Need}, year={2017}}\n"
            "@article{bert, title={BERT}, year={2019}}\n"
        )
        bibliography = extract_citation_candidates(bib, source_format="bibtex")
        payload = link_document_citations(
            [{"path": "paper.tex", "text": tex, "source_format": "latex"}],
            bibliography,
        )

        keys = [item["cite_key"] for item in payload["body_links"]]
        self.assertEqual(keys, ["attention", "bert"])

    def test_latex_comments_are_not_treated_as_citations(self):
        tex = "Visible claim \\cite{attention}.\n% hidden \\cite{ghost}\n"
        bib = "@article{attention, title={Attention Is All You Need}, year={2017}}\n"
        bibliography = extract_citation_candidates(bib, source_format="bibtex")
        payload = link_document_citations(
            [{"path": "paper.tex", "text": tex, "source_format": "latex"}],
            bibliography,
        )

        self.assertEqual([item["cite_key"] for item in payload["body_links"]], ["attention"])
        self.assertEqual(payload["unlinked_markers"], [])


if __name__ == "__main__":
    unittest.main()
