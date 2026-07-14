"""Tests for extracting citation candidates from manuscript files."""

from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree

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
        self.assertEqual(candidates[0]["source_format"], "markdown")
        self.assertEqual(candidates[0]["source_index"], 1)
        self.assertEqual(candidates[0]["source_locator"], "citation-1")

    def test_extracts_reference_line_ranges_for_auditable_traceability(self):
        text = "\n".join(
            [
                "Intro text.",
                "",
                "References",
                "",
                "1. Vaswani, A. et al. Attention Is All You Need.",
                "   Advances in Neural Information Processing Systems, 2017. arXiv:1706.03762.",
                "2. Xu, Zhe and Wang, Lin. GhostCite: A Large-Scale Analysis of Citation Validity. arXiv, 2026.",
            ]
        )

        candidates = extract_citation_candidates(text, source_format="markdown")

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["source_line_start"], 5)
        self.assertEqual(candidates[0]["source_line_end"], 6)
        self.assertEqual(candidates[1]["source_line_start"], 7)
        self.assertEqual(candidates[1]["source_line_end"], 7)

    def test_extracts_markdown_doi_without_sentence_punctuation(self):
        text = """
        ## References

        1. Xu, Zhe and Wang, Lin. GhostCite: A Large-Scale Analysis of Citation Validity. arXiv, 2026. DOI: 10.48550/arxiv.2602.06718.
        """

        candidates = extract_citation_candidates(text, source_format="markdown")

        self.assertEqual(candidates[0]["doi"], "10.48550/arxiv.2602.06718")

    def test_extracts_pasted_numbered_reference_list_without_heading(self):
        text = """
        1. Vaswani, A. et al. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.
        2. Xu, Zhe and Wang, Lin. GhostCite: A Large-Scale Analysis of Citation Validity. arXiv, 2026. DOI: 10.48550/arxiv.2602.06718.
        """

        candidates = extract_citation_candidates(text, source_format="text")

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["source_type"], "reference_list")
        self.assertEqual(candidates[0]["arxiv_id"], "1706.03762")
        self.assertEqual(candidates[1]["doi"], "10.48550/arxiv.2602.06718")

    def test_extracts_pasted_reference_list_with_indented_continuation(self):
        text = "\n".join(
            [
                "1. Vaswani, A. et al. Attention Is All You Need.",
                "   Advances in Neural Information Processing Systems, 2017. arXiv:1706.03762.",
                "2. Xu, Zhe and Wang, Lin. GhostCite: A Large-Scale Analysis of Citation Validity.",
                "   arXiv, 2026. DOI: 10.48550/arxiv.2602.06718.",
            ]
        )

        candidates = extract_citation_candidates(text, source_format="text")

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["source_type"], "reference_list")
        self.assertIn("Advances in Neural Information Processing Systems", candidates[0]["raw_text"])
        self.assertEqual(candidates[0]["arxiv_id"], "1706.03762")
        self.assertEqual(candidates[1]["doi"], "10.48550/arxiv.2602.06718")

    def test_extracts_pasted_unnumbered_reference_list_without_heading(self):
        text = "\n".join(
            [
                "Vaswani, A. et al. Attention Is All You Need. Advances in Neural Information Processing Systems, 2017. arXiv:1706.03762.",
                "Xu, Zhe and Wang, Lin. GhostCite: A Large-Scale Analysis of Citation Validity. arXiv, 2026. DOI: 10.48550/arxiv.2602.06718.",
            ]
        )

        candidates = extract_citation_candidates(text, source_format="text")

        self.assertEqual(len(candidates), 2)
        self.assertEqual(candidates[0]["source_type"], "reference_list")
        self.assertEqual(candidates[0]["arxiv_id"], "1706.03762")
        self.assertEqual(candidates[1]["doi"], "10.48550/arxiv.2602.06718")

    def test_does_not_extract_plain_numbered_notes_without_citation_signals(self):
        text = """
        1. Revise the introduction before sending the draft.
        2. Ask a collaborator to check the figures.
        """

        self.assertEqual(extract_citation_candidates(text, source_format="text"), [])

    def test_does_not_extract_plain_numbered_notes_with_indented_continuation(self):
        text = "\n".join(
            [
                "1. Revise the introduction before sending the draft.",
                "   Keep the note in the shared checklist.",
                "2. Ask a collaborator to check the figures.",
                "   Follow up after the next meeting.",
            ]
        )

        self.assertEqual(extract_citation_candidates(text, source_format="text"), [])

    def test_does_not_extract_plain_unnumbered_notes_with_years(self):
        text = "\n".join(
            [
                "The team will prepare the conference checklist in 2026 before submission.",
                "Ask Zhe and Lin to review the draft after the next meeting.",
            ]
        )

        self.assertEqual(extract_citation_candidates(text, source_format="text"), [])

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

    def test_extracts_bibtex_fields_with_nested_braces(self):
        text = r"""
        @article{vaswani2017,
          title={Attention {Is} All You Need},
          author="Vaswani, Ashish and Shazeer, Noam",
          journal={NeurIPS},
          year={2017},
          doi={10.5555/3295222.3295349}
        }
        """

        candidates = extract_citation_candidates(text, source_format="bibtex")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_type"], "bibtex")
        self.assertEqual(candidates[0]["source_id"], "vaswani2017")
        self.assertEqual(candidates[0]["title"], "Attention Is All You Need")
        self.assertEqual(candidates[0]["year"], 2017)
        self.assertEqual(candidates[0]["doi"], "10.5555/3295222.3295349")
        self.assertIn("Attention Is All You Need", candidates[0]["raw_text"])

    def test_extracts_bibtex_concatenated_field_values(self):
        text = r"""
        @inproceedings{vaswani2017,
          title = {Attention} # { {Is} All You Need},
          author = {Vaswani, Ashish and Shazeer, Noam},
          booktitle = {NeurIPS},
          year = {2017},
          doi = {10.5555/3295222.3295349},
          month = jan
        }
        """

        candidates = extract_citation_candidates(text, source_format="bibtex")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["title"], "Attention Is All You Need")
        self.assertEqual(candidates[0]["year"], 2017)
        self.assertEqual(candidates[0]["doi"], "10.5555/3295222.3295349")
        self.assertIn("Attention Is All You Need", candidates[0]["raw_text"])
        self.assertIn("NeurIPS", candidates[0]["raw_text"])

    def test_extracts_bibtex_string_macros_in_fields(self):
        text = r"""
        @string{nipsconf = {NeurIPS}}

        @inproceedings{vaswani2017,
          title = {Attention Is All You Need},
          author = {Vaswani, Ashish and Shazeer, Noam},
          booktitle = nipsconf,
          year = {2017},
          doi = {10.5555/3295222.3295349}
        }
        """

        candidates = extract_citation_candidates(text, source_format="bibtex")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["title"], "Attention Is All You Need")
        self.assertIn("NeurIPS", candidates[0]["raw_text"])
        self.assertNotIn("nipsconf", candidates[0]["raw_text"])

    def test_extracts_bibtex_parenthesized_entries_and_strings(self):
        text = r"""
        @string(nipsconf = {NeurIPS})

        @inproceedings(vaswani2017,
          title = {Attention} # {{Is} All You Need},
          author = {Vaswani, Ashish and Shazeer, Noam},
          booktitle = nipsconf,
          year = {2017},
          doi = {10.5555/3295222.3295349}
        )
        """

        candidates = extract_citation_candidates(text, source_format="bibtex")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_id"], "vaswani2017")
        self.assertEqual(candidates[0]["title"], "Attention Is All You Need")
        self.assertEqual(candidates[0]["year"], 2017)
        self.assertEqual(candidates[0]["doi"], "10.5555/3295222.3295349")
        self.assertIn("NeurIPS", candidates[0]["raw_text"])
        self.assertNotIn("nipsconf", candidates[0]["raw_text"])

    def test_loads_latex_bibliography_files(self):
        with tempfile.TemporaryDirectory() as directory:
            tex_path = os.path.join(directory, "paper.tex")
            bib_path = os.path.join(directory, "refs.bib")
            with open(tex_path, "w", encoding="utf-8") as handle:
                handle.write(
                    r"""
                    \documentclass{article}
                    \begin{document}
                    Prior work matters \cite{ghostcite2026}.
                    \bibliography{refs}
                    \addbibresource{refs.bib}
                    \end{document}
                    """
                )
            with open(bib_path, "w", encoding="utf-8") as handle:
                handle.write(
                    r"""
                    @article{ghostcite2026,
                      title={GhostCite: A Large-Scale Analysis of Citation Validity},
                      author={Xu, Zhe and Wang, Lin},
                      journal={arXiv},
                      year={2026},
                      doi={10.48550/arxiv.2602.06718}
                    }
                    """
                )

            candidates = load_citation_candidates(tex_path)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_type"], "bibtex")
        self.assertEqual(candidates[0]["source_id"], "ghostcite2026")
        self.assertEqual(candidates[0]["title"], "GhostCite: A Large-Scale Analysis of Citation Validity")
        self.assertEqual(candidates[0]["source_path"], bib_path)
        self.assertEqual(candidates[0]["source_format"], "bibtex")
        self.assertEqual(candidates[0]["source_locator"], f"{bib_path}#citation-1")
        self.assertEqual(candidates[0]["doi"], "10.48550/arxiv.2602.06718")

    def test_loads_latex_bibliography_from_input_file(self):
        with tempfile.TemporaryDirectory() as directory:
            tex_path = os.path.join(directory, "paper.tex")
            sections_dir = os.path.join(directory, "sections")
            os.mkdir(sections_dir)
            refs_tex_path = os.path.join(sections_dir, "references.tex")
            bib_path = os.path.join(sections_dir, "refs.bib")
            with open(tex_path, "w", encoding="utf-8") as handle:
                handle.write(
                    r"""
                    \documentclass{article}
                    \begin{document}
                    Prior work matters \cite{ghostcite2026}.
                    \input{sections/references}
                    \end{document}
                    """
                )
            with open(refs_tex_path, "w", encoding="utf-8") as handle:
                handle.write(r"\bibliography{refs}")
            with open(bib_path, "w", encoding="utf-8") as handle:
                handle.write(
                    r"""
                    @article{ghostcite2026,
                      title={GhostCite: A Large-Scale Analysis of Citation Validity},
                      author={Xu, Zhe and Wang, Lin},
                      journal={arXiv},
                      year={2026},
                      doi={10.48550/arxiv.2602.06718}
                    }
                    """
                )

            candidates = load_citation_candidates(tex_path)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_type"], "bibtex")
        self.assertEqual(candidates[0]["source_id"], "ghostcite2026")
        self.assertEqual(candidates[0]["source_path"], bib_path)
        self.assertEqual(candidates[0]["source_format"], "bibtex")
        self.assertEqual(candidates[0]["source_locator"], f"{bib_path}#citation-1")
        self.assertEqual(candidates[0]["doi"], "10.48550/arxiv.2602.06718")

    def test_loads_latex_bibitems_from_nested_include_without_looping(self):
        with tempfile.TemporaryDirectory() as directory:
            tex_path = os.path.join(directory, "paper.tex")
            refs_path = os.path.join(directory, "refs.tex")
            more_refs_path = os.path.join(directory, "more_refs.tex")
            with open(tex_path, "w", encoding="utf-8") as handle:
                handle.write(r"\include{refs}")
            with open(refs_path, "w", encoding="utf-8") as handle:
                handle.write(
                    r"""
                    \input{more_refs}
                    \begin{thebibliography}{9}
                    \bibitem{vaswani2017} Vaswani, A. et al. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.
                    \end{thebibliography}
                    """
                )
            with open(more_refs_path, "w", encoding="utf-8") as handle:
                handle.write(r"\input{refs}")

            candidates = load_citation_candidates(tex_path)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_type"], "bibitem")
        self.assertEqual(candidates[0]["source_id"], "vaswani2017")
        self.assertEqual(candidates[0]["source_path"], refs_path)
        self.assertEqual(candidates[0]["source_format"], "latex")
        self.assertEqual(candidates[0]["source_locator"], f"{refs_path}#citation-1")
        self.assertEqual(candidates[0]["arxiv_id"], "1706.03762")

    def test_loads_bbl_bibitems_with_source_format(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".bbl", delete=False) as handle:
            handle.write(
                r"""
                \begin{thebibliography}{1}
                \bibitem{vaswani2017} Vaswani, A. et al. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.
                \end{thebibliography}
                """
            )
            path = handle.name

        try:
            candidates = load_citation_candidates(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["source_type"], "bibitem")
        self.assertEqual(candidates[0]["source_id"], "vaswani2017")
        self.assertEqual(candidates[0]["source_path"], path)
        self.assertEqual(candidates[0]["source_format"], "bbl")
        self.assertEqual(candidates[0]["source_locator"], f"{path}#citation-1")
        self.assertEqual(candidates[0]["arxiv_id"], "1706.03762")

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
        self.assertEqual(candidates[0]["source_path"], path)
        self.assertEqual(candidates[0]["source_format"], "docx")
        self.assertEqual(candidates[0]["source_index"], 1)
        self.assertEqual(candidates[0]["source_locator"], f"{path}#citation-1")
        self.assertEqual(candidates[0]["arxiv_id"], "1706.03762")

    def test_malformed_docx_bad_zip_raises_os_error(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".docx", delete=False) as handle:
            handle.write(b"not a zip")
            path = handle.name

        try:
            with self.assertRaises(OSError) as raised:
                load_citation_candidates(path)
        finally:
            os.unlink(path)

        self.assertIsInstance(raised.exception.__cause__, zipfile.BadZipFile)
        self.assertIn("Could not read DOCX file", str(raised.exception))
        self.assertIn(path, str(raised.exception))

    def test_malformed_docx_missing_document_xml_raises_os_error(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".docx", delete=False) as handle:
            with zipfile.ZipFile(handle, "w") as archive:
                archive.writestr("[Content_Types].xml", "<Types />")
            path = handle.name

        try:
            with self.assertRaises(OSError) as raised:
                load_citation_candidates(path)
        finally:
            os.unlink(path)

        self.assertIsInstance(raised.exception.__cause__, KeyError)
        self.assertIn("Could not read DOCX file", str(raised.exception))
        self.assertIn(path, str(raised.exception))

    def test_malformed_docx_invalid_document_xml_raises_os_error(self):
        with tempfile.NamedTemporaryFile("wb", suffix=".docx", delete=False) as handle:
            with zipfile.ZipFile(handle, "w") as archive:
                archive.writestr("word/document.xml", "<w:document>")
            path = handle.name

        try:
            with self.assertRaises(OSError) as raised:
                load_citation_candidates(path)
        finally:
            os.unlink(path)

        self.assertIsInstance(raised.exception.__cause__, ElementTree.ParseError)
        self.assertIn("Could not read DOCX file", str(raised.exception))
        self.assertIn(path, str(raised.exception))

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
        self.assertEqual(payload[0]["source_path"], path)
        self.assertEqual(payload[0]["source_format"], "markdown")
        self.assertEqual(payload[0]["source_index"], 1)
        self.assertEqual(payload[0]["source_locator"], f"{path}#citation-1")

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
        self.assertEqual(payload["risk_ranking"][0]["input_source_path"], path)
        self.assertEqual(payload["risk_ranking"][0]["input_source_format"], "markdown")
        self.assertEqual(payload["risk_ranking"][0]["input_source_index"], 1)
        self.assertEqual(payload["risk_ranking"][0]["input_source_locator"], f"{path}#citation-1")
        self.assertEqual(payload["risk_ranking"][0]["input_source_line_start"], 3)
        self.assertEqual(payload["risk_ranking"][0]["input_source_line_end"], 3)
        self.assertEqual(payload["results"][0]["input"]["metadata"]["input_source_path"], path)
        self.assertEqual(payload["results"][0]["input"]["metadata"]["input_source_line_start"], 3)
        self.assertEqual(payload["results"][0]["input"]["metadata"]["input_source_line_end"], 3)

    def test_audit_can_read_latex_external_bibliography_directly(self):
        record = CitationRecord(
            citation_id="ghostcite",
            title="GhostCite: A Large-Scale Analysis of Citation Validity",
            authors=["Zhe Xu"],
            year=2026,
            venue="arXiv",
            doi="10.48550/arxiv.2602.06718",
            arxiv_id="2602.06718",
            source="memory",
        )
        source = InMemoryMetadataSource([record])
        with tempfile.TemporaryDirectory() as directory:
            tex_path = os.path.join(directory, "paper.tex")
            bib_path = os.path.join(directory, "refs.bib")
            with open(tex_path, "w", encoding="utf-8") as handle:
                handle.write(
                    r"""
                    \documentclass{article}
                    \begin{document}
                    We cite GhostCite here \cite{ghostcite2026}.
                    \bibliography{refs}
                    \end{document}
                    """
                )
            with open(bib_path, "w", encoding="utf-8") as handle:
                handle.write(
                    r"""
                    @article{ghostcite2026,
                      title={GhostCite: A Large-Scale Analysis of Citation Validity},
                      author={Xu, Zhe and Wang, Lin},
                      journal={arXiv},
                      year={2026},
                      doi={10.48550/arxiv.2602.06718}
                    }
                    """
                )
            stdout = io.StringIO()

            code = run(["audit", tex_path], source=source, stdout=stdout)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["summary"]["verified"], 1)
        self.assertEqual(payload["risk_ranking"][0]["input_source_path"], bib_path)
        self.assertEqual(payload["risk_ranking"][0]["input_source_format"], "bibtex")
        self.assertEqual(payload["risk_ranking"][0]["input_source_locator"], f"{bib_path}#citation-1")


if __name__ == "__main__":
    unittest.main()
