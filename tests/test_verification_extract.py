"""Tests for extracting citation candidates from manuscript files."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import zipfile

from citeguard.cli import run
from citeguard.verification import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.verification.extract import extract_citation_candidates, load_citation_candidates


class CitationExtractionTests(unittest.TestCase):
    def test_extracts_markdown_reference_section(self):
        text = """
        # Related Work

        This section cites prior work.

        ## References

        1. Vaswani, A. et al. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.
        2. Xu, Z. and Wang, L. GhostCite: A Large-Scale Analysis of Citation Validity. arXiv, 2026.
        """

        candidates = extract_citation_candidates(text, source_format="markdown")

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["arxiv_id"], "1706.03762")
        self.assertEqual(candidates[0]["year"], 2017)
        self.assertIn("Attention Is All You Need", candidates[0]["raw_text"])

    def test_extracts_latex_bibitems_and_bibtex_entries(self):
        text = r"""
        \begin{thebibliography}{9}
        \bibitem{vaswani2017} Vaswani, A. et al. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.
        \end{thebibliography}

        @article{ghostcite2026,
          title={GhostCite: A Large-Scale Analysis of Citation Validity},
          author={Xu, Zhe and Wang, Lin},
          journal={arXiv},
          year={2026},
          doi={10.48550/arxiv.2602.06718}
        }
        """

        candidates = extract_citation_candidates(text, source_format="latex")

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["source_type"], "bibtex")
        self.assertEqual(candidates[0]["title"], "GhostCite: A Large-Scale Analysis of Citation Validity")
        self.assertEqual(candidates[1]["source_type"], "bibitem")

    def test_loads_docx_reference_text_without_external_dependencies(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".docx", delete=False) as handle:
            with zipfile.ZipFile(handle, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    """<?xml version="1.0" encoding="UTF-8"?>
                    <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
                      <w:body>
                        <w:p><w:r><w:t>References</w:t></w:r></w:p>
                        <w:p><w:r><w:t>1. Vaswani, A. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.</w:t></w:r></w:p>
                      </w:body>
                    </w:document>
                    """,
                )
            path = handle.name

        try:
            candidates = load_citation_candidates(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_type"], "reference_section")
        self.assertEqual(candidates[0]["arxiv_id"], "1706.03762")

    def test_cli_extract_outputs_auditable_json_list(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
            handle.write(
                "## References\n\n"
                "1. Vaswani, A. et al. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.\n"
            )
            path = handle.name
        stdout = io.StringIO()

        try:
            code = run(["extract", path], stdout=stdout)
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload[0]["arxiv_id"], "1706.03762")

    def test_audit_can_read_markdown_references_directly(self):
        record = CitationRecord(
            citation_id="attention",
            title="Attention Is All You Need",
            authors=["Ashish Vaswani"],
            year=2017,
            venue="NeurIPS",
            arxiv_id="1706.03762",
            source="memory",
        )
        source = InMemoryMetadataSource([record])
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".md", delete=False) as handle:
            handle.write(
                "## References\n\n"
                "1. Vaswani, A. et al. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.\n"
            )
            path = handle.name
        stdout = io.StringIO()

        try:
            code = run(["audit", path], source=source, stdout=stdout)
        finally:
            os.unlink(path)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["verified"], 1)


if __name__ == "__main__":
    unittest.main()
