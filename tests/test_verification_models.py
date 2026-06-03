"""Tests for verification data models."""

import unittest

from src.graph import CitationRecord
from src.verification.models import AuditReport, FieldDiff, VerificationResult, Verdict


class ModelsTests(unittest.TestCase):
    def _result(self, verdict):
        record = CitationRecord(citation_id="c1", title="A Real Paper", year=2024)
        return VerificationResult(
            verdict=verdict,
            confidence=0.91,
            input_citation=record,
            canonical_record=record,
            field_diffs=[FieldDiff("year", 2023, 2024, False)],
            suggested_citation="Doe (2024). A Real Paper.",
            explanation="ok",
            sources_checked=["openalex"],
            sources_responded=["openalex"],
        )

    def test_result_to_dict_is_json_friendly(self):
        data = self._result(Verdict.METADATA_MISMATCH).to_dict()
        self.assertEqual(data["verdict"], "metadata_mismatch")
        self.assertEqual(data["confidence"], 0.91)
        self.assertEqual(data["field_diffs"][0]["field"], "year")
        self.assertEqual(data["sources_checked"], ["openalex"])
        self.assertEqual(data["alternatives"], [])

    def test_audit_report_to_dict_carries_summary(self):
        report = AuditReport(
            results=[self._result(Verdict.VERIFIED)],
            summary={"verified": 1, "not_found": 0},
        )
        data = report.to_dict()
        self.assertEqual(data["summary"]["verified"], 1)
        self.assertEqual(len(data["results"]), 1)


if __name__ == "__main__":
    unittest.main()
