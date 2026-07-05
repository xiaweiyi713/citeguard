"""Tests for verification data models."""

import unittest

from citeguard.verification import CitationRecord
from citeguard.verification.models import (
    AuditReport,
    FieldDiff,
    STABLE_NEXT_ACTIONS,
    VerificationResult,
    Verdict,
    available_sources,
    classify_source_failure_mode,
    stable_next_action,
    source_failure_recovery_code,
    verification_next_action,
    verification_recovery_code,
)


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
        self.assertEqual(data["sources_available"], ["openalex"])
        self.assertEqual(data["source_failure_details"], [])
        self.assertEqual(data["source_failure_mode"], "none")
        self.assertFalse(data["outage_limited"])
        self.assertEqual(data["recovery_code"], "")
        self.assertEqual(data["next_action"], "review_metadata")
        self.assertEqual(data["alternatives"], [])

    def test_available_sources_preserves_checked_order_and_excludes_failed(self):
        self.assertEqual(available_sources(["openalex", "crossref", "arxiv"], ["crossref"]), ["openalex", "arxiv"])
        self.assertEqual(available_sources(["openalex"], ["openalex"]), [])

    def test_source_failure_mode_treats_any_response_as_partial_outage(self):
        self.assertEqual(classify_source_failure_mode(["openalex"], ["openalex"]), "all_sources_failed")
        self.assertEqual(
            classify_source_failure_mode(["openalex"], ["openalex"], responded=["openalex"]),
            "partial_outage",
        )

    def test_recovery_codes_are_stable_for_agents(self):
        self.assertIn("rewrite_or_replace_evidence", STABLE_NEXT_ACTIONS)
        self.assertEqual(stable_next_action("keep"), "keep")
        with self.assertRaises(ValueError):
            stable_next_action("private_unregistered_action")
        self.assertEqual(source_failure_recovery_code([{"code": "source_unavailable"}, {"code": "timeout"}]), "timeout")
        self.assertEqual(verification_recovery_code(Verdict.AMBIGUOUS, []), "ambiguous_citation")
        self.assertEqual(verification_recovery_code(Verdict.NOT_FOUND, [{"code": "source_unavailable"}]), "source_unavailable")
        self.assertEqual(verification_next_action(Verdict.AMBIGUOUS), "disambiguate_identifier")
        self.assertEqual(
            verification_next_action(Verdict.NOT_FOUND, source_failure_mode="all_sources_failed"),
            "retry_or_check_source_health",
        )
        self.assertEqual(
            verification_next_action(Verdict.VERIFIED, sources_failed=["crossref"]),
            "inspect_source_health",
        )

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
