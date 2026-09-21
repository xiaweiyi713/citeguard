"""Tests for the bounded, suggestion-only document citation audit workflow."""

from __future__ import annotations

import io
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from jsonschema import Draft202012Validator

from citeguard.cli import run
from citeguard.contracts import load_contract_schema, with_contract_version
from citeguard.graph import CitationRecord
from citeguard.retrieval.scholarly_clients import InMemoryMetadataSource
from citeguard.verification.document_audit import BoundedDocumentReader
from citeguard.verification import DocumentAuditError, audit_document


def _source() -> InMemoryMetadataSource:
    return InMemoryMetadataSource(
        [
            CitationRecord(
                citation_id="attention",
                title="Attention Is All You Need",
                authors=["Ashish Vaswani"],
                year=2017,
                venue="NeurIPS",
                arxiv_id="1706.03762",
                source="fixture",
            )
        ]
    )


class DocumentAuditTests(unittest.TestCase):
    def test_markdown_audit_returns_line_locator_without_modifying_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "references.md"
            original = (
                "# Draft\n\n"
                "## References\n\n"
                "1. Vaswani, A. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.\n"
            )
            document.write_text(original, encoding="utf-8")

            payload = audit_document(str(document), source=_source(), allowed_roots=[str(root)])

            self.assertEqual(payload["document"]["path"], str(document.resolve()))
            self.assertEqual(payload["extraction"]["candidate_count"], 1)
            candidate = payload["extraction"]["candidates"][0]
            self.assertEqual(candidate["document_locator"], f"{document.resolve()}#line-5")
            self.assertEqual(payload["audit"]["summary"]["verified"], 1)
            self.assertEqual(payload["review_queue"], [])
            self.assertFalse(payload["edit_policy"]["document_modified"])
            self.assertFalse(payload["edit_policy"]["automatic_apply_allowed"])
            self.assertEqual(payload["review_status"]["state"], "clear")
            self.assertFalse(payload["review_status"]["review_required"])
            self.assertEqual(payload["review_status"]["queue_count"], 0)
            self.assertEqual(
                payload["review_status"]["snapshot_digest"],
                payload["document"]["snapshot"]["digest"],
            )
            snapshot = payload["document"]["snapshot"]
            self.assertTrue(snapshot["digest"].startswith("sha256:"))
            self.assertEqual(snapshot["file_count"], 1)
            self.assertEqual(snapshot["files"][0]["sha256"], "sha256:" + hashlib.sha256(original.encode()).hexdigest())
            self.assertEqual(document.read_text(encoding="utf-8"), original)

    def test_not_found_reference_has_exact_review_locator_and_requires_confirmation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "references.md"
            document.write_text(
                "## References\n\n"
                "1. Unknown, U. Ghost Citation. Imaginary Journal, 2026. DOI: 10.9999/ghost-citation.\n",
                encoding="utf-8",
            )

            payload = audit_document(str(document), source=_source(), allowed_roots=[str(root)])

            self.assertEqual(payload["audit"]["summary"]["not_found"], 1)
            self.assertEqual(payload["review_queue_summary"]["count"], 1)
            review_item = payload["review_queue"][0]
            self.assertEqual(review_item["locator"], f"{document.resolve()}#line-3")
            self.assertEqual(review_item["next_action"], "resolve_identifier_or_replace")
            self.assertTrue(review_item["requires_user_confirmation"])
            self.assertFalse(review_item["automatic_apply_allowed"])
            self.assertEqual(payload["review_status"]["state"], "review_required")
            self.assertTrue(payload["review_status"]["review_required"])
            self.assertEqual(payload["review_status"]["queue_count"], 1)
            self.assertEqual(payload["review_status"]["next_action"], "resolve_identifier_or_replace")
            self.assertEqual(
                payload["review_status"]["snapshot_digest"],
                payload["document"]["snapshot"]["digest"],
            )
            self.assertIn("does_not_modify_user_documents", payload["policy"])

    def test_latex_include_cannot_escape_allowed_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = parent / "project"
            root.mkdir()
            outside = parent / "outside.tex"
            document = root / "paper.tex"
            outside.write_text(
                "\\bibitem{outside} Unknown, U. Ghost Citation. Imaginary Journal, 2026. DOI: 10.9999/outside.\n",
                encoding="utf-8",
            )
            document.write_text("\\input{../outside}", encoding="utf-8")

            with self.assertRaises(DocumentAuditError) as raised:
                audit_document(str(document), source=_source(), allowed_roots=[str(root)])

        self.assertEqual(raised.exception.code, "file_error")
        self.assertIn("configured document-audit roots", str(raised.exception))

    def test_latex_missing_dependencies_are_explicit_and_require_input_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "paper.tex"
            document.write_text(
                "\\input{missing-section}\n"
                "\\bibliography{missing-references}\n",
                encoding="utf-8",
            )

            payload = with_contract_version(audit_document(str(document), source=_source(), allowed_roots=[str(root)]))

        missing = payload["document"]["dependencies"]["missing"]
        self.assertEqual(
            missing,
            [
                {"kind": "include", "path": str((root / "missing-section.tex").resolve())},
                {"kind": "bibliography", "path": str((root / "missing-references.bib").resolve())},
            ],
        )
        self.assertFalse(payload["document"]["dependencies"]["complete"])
        self.assertEqual(payload["review_queue"], [])
        self.assertEqual(payload["review_status"]["state"], "review_required")
        self.assertTrue(payload["review_status"]["incomplete"])
        self.assertEqual(payload["review_status"]["next_action"], "repair_input")
        self.assertEqual(payload["review_queue_summary"]["incomplete_dependency_count"], 2)

    def test_cli_fail_on_review_catches_missing_latex_dependencies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "paper.tex"
            document.write_text("\\input{missing-section}\n", encoding="utf-8")
            stdout = io.StringIO()
            code = run(
                ["audit-document", str(document), "--allowed-root", str(root), "--fail-on-review"],
                source=_source(),
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 1)
        self.assertTrue(payload["review_status"]["review_required"])
        self.assertEqual(payload["review_status"]["next_action"], "repair_input")

    def test_docx_audit_returns_paragraph_locator(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "references.docx"
            with zipfile.ZipFile(document, "w") as archive:
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

            payload = audit_document(str(document), source=_source(), allowed_roots=[str(root)])

        candidate = payload["extraction"]["candidates"][0]
        self.assertEqual(candidate["source_paragraph_start"], 2)
        self.assertEqual(candidate["document_locator"], f"{document.resolve()}#paragraph-2")

    def test_cli_exposes_same_suggestion_only_document_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "references.bib"
            document.write_text(
                """@article{attention,
  title={Attention Is All You Need},
  year={2017},
  eprint={1706.03762}
}
""",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            code = run(
                ["audit-document", str(document), "--allowed-root", str(root)],
                source=_source(),
                stdout=stdout,
            )

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(payload["tool"], "audit_document")
        self.assertFalse(payload["edit_policy"]["document_modified"])
        self.assertEqual(payload["extraction"]["candidates"][0]["document_locator"], f"{document.resolve()}#lines-1-5")

    def test_cli_can_fail_when_review_queue_is_non_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "references.md"
            document.write_text(
                "## References\n\n"
                "1. Unknown, U. Ghost Citation. Imaginary Journal, 2026. DOI: 10.9999/ghost-citation.\n",
                encoding="utf-8",
            )
            stdout = io.StringIO()
            code = run(
                ["audit-document", str(document), "--allowed-root", str(root), "--fail-on-review"],
                source=_source(),
                stdout=stdout,
            )

        self.assertEqual(code, 1)
        self.assertEqual(len(json.loads(stdout.getvalue())["review_queue"]), 1)

    def test_empty_document_is_a_schema_valid_clear_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "empty.md"
            document.write_text("", encoding="utf-8")
            payload = with_contract_version(audit_document(str(document), source=_source(), allowed_roots=[str(root)]))

        self.assertEqual(payload["extraction"]["candidate_count"], 0)
        self.assertEqual(payload["document"]["read"]["total_bytes"], 0)
        self.assertEqual(payload["review_status"]["state"], "clear")
        schema = load_contract_schema()
        validator = Draft202012Validator(
            {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/document_audit_response"}
        )
        errors = list(validator.iter_errors(payload))
        self.assertEqual([], errors, "\n".join(error.message for error in errors))

    def test_snapshot_includes_latex_includes_and_changes_when_a_dependency_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "paper.tex"
            included = root / "references.tex"
            bibliography = root / "refs.bib"
            document.write_text("\\input{references}", encoding="utf-8")
            included.write_text("\\bibliography{refs}", encoding="utf-8")
            bibliography.write_text(
                "@article{attention, title={Attention Is All You Need}, year={2017}, eprint={1706.03762}}",
                encoding="utf-8",
            )

            first = audit_document(str(document), source=_source(), allowed_roots=[str(root)])
            first_paths = {item["path"] for item in first["document"]["snapshot"]["files"]}
            bibliography.write_text(
                "@article{attention, title={Attention Is All You Need}, year={2017}, eprint={1706.03762}, note={updated}}",
                encoding="utf-8",
            )
            second = audit_document(str(document), source=_source(), allowed_roots=[str(root)])

        self.assertEqual(first_paths, {str(document.resolve()), str(included.resolve()), str(bibliography.resolve())})
        self.assertNotEqual(
            first["document"]["snapshot"]["digest"],
            second["document"]["snapshot"]["digest"],
        )

    def test_reader_enforces_actual_read_limit_after_a_file_grows(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "references.md"
            document.write_text("1234", encoding="utf-8")
            reader = BoundedDocumentReader([str(root)], max_file_bytes=4, max_total_bytes=8)
            resolved = reader.resolve(document)
            document.write_text("12345", encoding="utf-8")

            with self.assertRaises(DocumentAuditError) as raised:
                reader.read_text(resolved)

        self.assertEqual(raised.exception.code, "file_error")
        self.assertIn("grew beyond", str(raised.exception))

    @unittest.skipUnless(hasattr(os, "O_NOFOLLOW"), "platform does not expose O_NOFOLLOW")
    def test_reader_rejects_a_path_replaced_by_symlink_after_resolution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            root = parent / "project"
            root.mkdir()
            document = root / "references.md"
            outside = parent / "outside.md"
            document.write_text("safe", encoding="utf-8")
            outside.write_text("outside root", encoding="utf-8")
            reader = BoundedDocumentReader([str(root)])
            resolved = reader.resolve(document)
            document.unlink()
            document.symlink_to(outside)

            with self.assertRaises(DocumentAuditError) as raised:
                reader._read_bytes(resolved)

        self.assertEqual(raised.exception.code, "file_error")
        self.assertIn("Could not read document file", str(raised.exception))

    def test_public_document_audit_payload_matches_v1_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "references.md"
            document.write_text(
                "## References\n\n"
                "1. Unknown, U. Ghost Citation. Imaginary Journal, 2026. DOI: 10.9999/ghost-citation.\n",
                encoding="utf-8",
            )
            payload = with_contract_version(audit_document(str(document), source=_source(), allowed_roots=[str(root)]))

        schema = load_contract_schema()
        validator = Draft202012Validator(
            {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": "#/$defs/document_audit_response"}
        )
        errors = list(validator.iter_errors(payload))
        self.assertEqual([], errors, "\n".join(error.message for error in errors))

    def test_markdown_in_text_citation_is_linked_and_html_report_shows_the_sentence(self):
        from citeguard.verification.document_report import render_document_audit_html

        abstract = (
            "We propose a new simple network architecture, the Transformer, based solely on "
            "attention mechanisms, dispensing with recurrence and convolutions entirely. "
            "Experiments on two machine translation tasks show these models to be superior in quality."
        )
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="attention",
                    title="Attention Is All You Need",
                    authors=["Ashish Vaswani"],
                    year=2017,
                    venue="NeurIPS",
                    arxiv_id="1706.03762",
                    abstract=abstract,
                    source="fixture",
                )
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "paper.md"
            document.write_text(
                "Transformer-based models outperform recurrence on all tasks [1].\n\n"
                "## References\n\n"
                "1. Vaswani, A. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.\n",
                encoding="utf-8",
            )
            payload = audit_document(str(document), source=source, allowed_roots=[str(root)])
            html_path = root / "report.html"
            stdout = io.StringIO()
            code = run(
                ["audit-document", str(document), "--allowed-root", str(root), "--html", str(html_path)],
                source=source,
                stdout=stdout,
            )
            html_text = html_path.read_text(encoding="utf-8")

        self.assertEqual(code, 0)
        self.assertEqual(len(payload["body_links"]), 1)
        self.assertEqual(payload["body_links"][0]["link_status"], "linked")
        self.assertTrue(payload["claim_reviews"])
        self.assertIn("outperform recurrence on all tasks", payload["claim_reviews"][0]["sentence"])
        html = render_document_audit_html(payload)
        self.assertIn("outperform recurrence on all tasks", html)
        self.assertIn("Check these first", html)
        self.assertIn("Metadata / identity", html)
        self.assertIn("Insufficient evidence", html)
        self.assertIn("outperform recurrence on all tasks", html_text)

    def test_semicolon_clauses_are_reviewed_separately(self):
        source = InMemoryMetadataSource(
            [
                CitationRecord(
                    citation_id="attention",
                    title="Attention Is All You Need",
                    authors=["Ashish Vaswani"],
                    year=2017,
                    arxiv_id="1706.03762",
                    abstract=(
                        "We propose a new simple network architecture, the Transformer, "
                        "based solely on attention mechanisms, dispensing with recurrence "
                        "and convolutions entirely. Experiments on two machine translation "
                        "tasks show these models to be superior in quality."
                    ),
                    source="fixture",
                )
            ]
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "paper.md"
            document.write_text(
                "The Transformer is based solely on attention mechanisms; "
                "it outperforms recurrence on all tasks [1].\n\n"
                "## References\n\n"
                "1. Vaswani, A. Attention Is All You Need. NeurIPS, 2017. arXiv:1706.03762.\n",
                encoding="utf-8",
            )
            payload = audit_document(str(document), source=source, allowed_roots=[str(root)])

        sentences = [item["sentence"] for item in payload["claim_reviews"]]
        self.assertGreaterEqual(len(sentences), 2)
        self.assertTrue(any("based solely on attention" in sentence for sentence in sentences))
        self.assertTrue(any("outperforms recurrence on all tasks" in sentence for sentence in sentences))

    def test_unlinked_latex_marker_stays_visible_in_the_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            document = root / "paper.tex"
            bibliography = root / "refs.bib"
            document.write_text(
                "Visible work \\cite{attention} and a missing key \\cite{ghost}.\n\\bibliography{refs}\n",
                encoding="utf-8",
            )
            bibliography.write_text(
                "@article{attention, title={Attention Is All You Need}, year={2017}, eprint={1706.03762}}\n",
                encoding="utf-8",
            )
            payload = audit_document(str(document), source=_source(), allowed_roots=[str(root)])

        keys = {item["cite_key"] for item in payload["unlinked_markers"]}
        self.assertIn("ghost", keys)
        self.assertTrue(any(item.get("issue") == "unlinked_citation" for item in payload["claim_reviews"]))
        self.assertTrue(payload["review_status"]["review_required"])


if __name__ == "__main__":
    unittest.main()
