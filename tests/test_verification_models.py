"""Tests for verification data models."""

import unittest

from citeguard.verification import CitationRecord
from citeguard.verification.models import (
    AuditReport,
    FieldDiff,
    REVIEW_ACTION_QUEUE_BY_NEXT_ACTION,
    REVIEW_ACTION_QUEUE_KEYS,
    STABLE_NEXT_ACTIONS,
    VerificationResult,
    Verdict,
    available_sources,
    classify_source_failure_mode,
    filter_high_risk_payload,
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

    def test_review_action_queue_mapping_covers_stable_next_actions(self):
        self.assertEqual(set(REVIEW_ACTION_QUEUE_BY_NEXT_ACTION), STABLE_NEXT_ACTIONS)
        self.assertEqual(set(REVIEW_ACTION_QUEUE_BY_NEXT_ACTION.values()), set(REVIEW_ACTION_QUEUE_KEYS))
        self.assertEqual(REVIEW_ACTION_QUEUE_BY_NEXT_ACTION["keep"], "safe_to_keep_indexes")
        self.assertEqual(REVIEW_ACTION_QUEUE_BY_NEXT_ACTION["keep_claim"], "safe_to_keep_indexes")
        self.assertEqual(REVIEW_ACTION_QUEUE_BY_NEXT_ACTION["rewrite_or_replace_evidence"], "rewrite_or_replace_indexes")
        self.assertEqual(REVIEW_ACTION_QUEUE_BY_NEXT_ACTION["resolve_identifier_or_replace"], "identity_resolution_indexes")
        self.assertEqual(REVIEW_ACTION_QUEUE_BY_NEXT_ACTION["resolve_citation_identity"], "identity_resolution_indexes")
        self.assertEqual(REVIEW_ACTION_QUEUE_BY_NEXT_ACTION["review_metadata"], "metadata_review_indexes")
        self.assertEqual(REVIEW_ACTION_QUEUE_BY_NEXT_ACTION["inspect_full_text_or_find_stronger_citation"], "evidence_review_indexes")
        self.assertEqual(REVIEW_ACTION_QUEUE_BY_NEXT_ACTION["retry_or_check_source_health"], "source_retry_indexes")
        self.assertEqual(REVIEW_ACTION_QUEUE_BY_NEXT_ACTION["repair_input"], "input_repair_indexes")

    def test_audit_report_to_dict_carries_summary(self):
        report = AuditReport(
            results=[self._result(Verdict.VERIFIED)],
            summary={"verified": 1, "not_found": 0},
        )
        data = report.to_dict()
        self.assertEqual(data["summary"]["verified"], 1)
        self.assertEqual(len(data["results"]), 1)

    def test_filter_high_risk_payload_preserves_original_indexes(self):
        payload = {
            "results": [{"id": "low"}, {"id": "high"}, {"id": "medium"}],
            "risk_ranking": [
                {"index": 1, "risk": "high"},
                {"index": 2, "risk": "medium"},
                {"index": 0, "risk": "low"},
            ],
            "review_summary": {"total": 3},
        }
        filtered = filter_high_risk_payload(payload)

        self.assertEqual(filtered["results"], [{"id": "high"}])
        self.assertEqual(filtered["risk_ranking"], [{"index": 1, "risk": "high"}])
        self.assertEqual(filtered["review_summary"], {"total": 3})
        self.assertEqual(filtered["filtered"]["returned_indexes"], [1])
        self.assertEqual(filtered["filtered"]["omitted_indexes"], [0, 2])

    def test_filter_high_risk_payload_ignores_invalid_risk_indexes(self):
        payload = {
            "results": [{"id": "first"}, {"id": "second"}],
            "risk_ranking": [
                "not an object",
                {"risk": "high"},
                {"index": "1", "risk": "high"},
                {"index": -1, "risk": "high"},
                {"index": 99, "risk": "high"},
                {"index": 1, "risk": "high"},
            ],
        }
        filtered = filter_high_risk_payload(payload)

        self.assertEqual(filtered["results"], [{"id": "second"}])
        self.assertEqual(filtered["risk_ranking"], [{"index": 1, "risk": "high"}])
        self.assertEqual(filtered["filtered"]["returned_indexes"], [1])
        self.assertEqual(filtered["filtered"]["omitted_indexes"], [0])


if __name__ == "__main__":
    unittest.main()
