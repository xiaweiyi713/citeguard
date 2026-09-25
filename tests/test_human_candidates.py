"""Tests for the unlabeled real-source support candidate workflow."""

from __future__ import annotations

import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from citeguard.benchmark.human_candidates import (
    HumanSupportCandidateError,
    build_blinded_candidate_packet,
    build_human_support_candidate_dataset,
    merge_candidate_annotation_packets,
    validate_blinded_candidate_packet,
    validate_candidate_dataset,
)
from scripts.build_human_support_candidates import main as build_candidate_main
from scripts.release_package_gate import _record_human_candidate_packet_contract_gate


def _retrieval_dataset():
    return {
        "schema_version": 1,
        "campaign_id": "citeguard-live-retrieval-v1",
        "cases": [
            {
                "id": "real-1",
                "ground_truth_locator": "https://doi.org/10.1000/real",
                "lang": "en",
                "domain": "computer_science",
                "curation": {"source": "arxiv"},
                "metadata_snapshot": {
                    "title": "Real Paper",
                    "abstract": "The method improves accuracy on the task.",
                    "source": "arxiv",
                    "retrieved_at": "2026-08-07T12:00:00Z",
                },
            }
        ],
    }


def _claims():
    return {
        "campaign_id": "citeguard-human-support-v1",
        "claims": [
            {
                "id": "candidate-1",
                "source_case_id": "real-1",
                "claim": "The method improves accuracy on the task.",
                "lang": "en",
                "domain": "computer_science",
                "writing_context": "research_article",
                "evidence_scope": "abstract",
                "rights_basis": "public_abstract",
                "case_type": "direct_support",
                "split": "test",
            }
        ],
    }


class HumanCandidateTests(unittest.TestCase):
    def test_builder_omits_gold_and_packet_is_blinded(self):
        dataset = build_human_support_candidate_dataset(
            _retrieval_dataset(), _claims(), collected_at="2026-08-07T12:00:00Z"
        )
        validate_candidate_dataset(dataset)
        row = dataset["cases"][0]
        self.assertNotIn("gold", row)
        self.assertEqual(row["evidence"], "The method improves accuracy on the task.")

        packet = build_blinded_candidate_packet(dataset)
        self.assertEqual(packet["schema_version"], 3)
        self.assertEqual(packet["case_count"], 1)
        self.assertNotIn("gold", packet)
        packet_row = packet["cases"][0]
        self.assertTrue(packet_row["case_id"].startswith("review-"))
        self.assertNotEqual(packet_row["case_id"], row["id"])
        self.assertNotIn("case_type", packet_row)
        self.assertNotIn("split", packet_row)
        self.assertTrue(packet["candidate_digest"].startswith("sha256:"))
        self.assertEqual(packet_row["annotation"]["annotator_label"], "")

    def test_packet_rejects_label_clues_even_when_rest_of_packet_is_intact(self):
        dataset = build_human_support_candidate_dataset(_retrieval_dataset(), _claims(), collected_at="2026-08-07T12:00:00Z")
        packet = build_blinded_candidate_packet(dataset)
        packet["cases"][0]["case_type"] = "direct_support"
        with self.assertRaisesRegex(HumanSupportCandidateError, "exposes internal candidate metadata"):
            validate_blinded_candidate_packet(dataset, packet)

        old_packet = build_blinded_candidate_packet(dataset)
        old_packet["schema_version"] = 2
        del old_packet["candidate_digest"]
        with self.assertRaisesRegex(HumanSupportCandidateError, "packet schema_version mismatch"):
            validate_blinded_candidate_packet(dataset, old_packet)

    def test_packet_rejects_hidden_candidate_metadata_drift(self):
        dataset = build_human_support_candidate_dataset(
            _retrieval_dataset(), _claims(), collected_at="2026-08-07T12:00:00Z"
        )
        packet = build_blinded_candidate_packet(dataset)
        for field, changed in (
            ("split", "dev"),
            ("case_type", "weak_support"),
            ("rights_basis", "open_access"),
            ("source_case_id", "different-source"),
        ):
            tampered = copy.deepcopy(dataset)
            tampered["cases"][0][field] = changed
            if field == "source_case_id":
                tampered["cases"][0]["candidate_provenance"]["source_case_id"] = changed
            with self.subTest(field=field), self.assertRaisesRegex(
                HumanSupportCandidateError, "candidate_digest does not match"
            ):
                validate_blinded_candidate_packet(tampered, packet)

        tampered = copy.deepcopy(dataset)
        tampered["cases"][0]["candidate_provenance"]["metadata_snapshot_sha256"] = "a" * 64
        with self.assertRaisesRegex(HumanSupportCandidateError, "candidate_digest does not match"):
            validate_blinded_candidate_packet(tampered, packet)

    def test_existing_candidate_dataset_can_regenerate_packet_without_rewriting_candidates(self):
        dataset = build_human_support_candidate_dataset(_retrieval_dataset(), _claims(), collected_at="2026-08-07T12:00:00Z")
        with tempfile.TemporaryDirectory() as directory:
            candidate_path = Path(directory) / "candidates.json"
            packet_path = Path(directory) / "packet.json"
            candidate_path.write_text(json.dumps(dataset), encoding="utf-8")
            original = candidate_path.read_bytes()
            with redirect_stdout(io.StringIO()):
                code = build_candidate_main(["--candidates", str(candidate_path), "--packet-output", str(packet_path)])
            self.assertEqual(code, 0)
            self.assertEqual(candidate_path.read_bytes(), original)
            validate_blinded_candidate_packet(dataset, json.loads(packet_path.read_text(encoding="utf-8")))

    def test_two_independent_agreeing_packets_are_recorded(self):
        dataset = build_human_support_candidate_dataset(_retrieval_dataset(), _claims(), collected_at="2026-08-07T12:00:00Z")
        packet = build_blinded_candidate_packet(dataset)
        packets = []
        for reviewer in ("reviewer-a", "reviewer-b"):
            completed = copy.deepcopy(packet)
            completed["cases"][0]["annotation"].update(
                {
                    "annotator_id": reviewer,
                    "annotator_label": "supported",
                    "rationale": "The abstract states the same proposition.",
                }
            )
            packets.append(completed)
        merged, report = merge_candidate_annotation_packets(dataset, packets)
        self.assertTrue(report["ok"])
        self.assertEqual(report["counts"], {"dual_annotator_agreed": 1})
        self.assertEqual(merged["cases"][0]["annotation_status"], "dual_annotator_agreed")
        self.assertEqual(len(merged["cases"][0]["annotations"]), 2)
        self.assertNotIn("gold", merged["cases"][0])

    def test_disagreement_is_preserved_for_adjudication(self):
        dataset = build_human_support_candidate_dataset(_retrieval_dataset(), _claims(), collected_at="2026-08-07T12:00:00Z")
        packet = build_blinded_candidate_packet(dataset)
        packets = []
        for reviewer, label in (("reviewer-a", "supported"), ("reviewer-b", "insufficient_evidence")):
            completed = copy.deepcopy(packet)
            completed["cases"][0]["annotation"].update(
                {"annotator_id": reviewer, "annotator_label": label, "rationale": "Independent rationale."}
            )
            packets.append(completed)
        merged, report = merge_candidate_annotation_packets(dataset, packets)
        self.assertFalse(report["ok"])
        self.assertEqual(merged["cases"][0]["annotation_status"], "dual_annotator_disagreement")
        self.assertEqual(report["conflicts"][0]["case_id"], "candidate-1")

    def test_tampered_packet_cannot_contribute_to_human_review_status(self):
        dataset = build_human_support_candidate_dataset(_retrieval_dataset(), _claims(), collected_at="2026-08-07T12:00:00Z")
        completed = build_blinded_candidate_packet(dataset)
        completed["cases"][0]["claim"] = "Tampered claim text."
        completed["cases"][0]["annotation"].update(
            {
                "annotator_id": "reviewer-a",
                "annotator_label": "supported",
                "rationale": "A label from a changed packet must not count.",
            }
        )

        with self.assertRaises(HumanSupportCandidateError):
            validate_blinded_candidate_packet(dataset, completed)
        merged, report = merge_candidate_annotation_packets(dataset, [completed])

        self.assertFalse(report["ok"])
        self.assertEqual(report["skipped"][0]["code"], "packet_not_blinded_or_intact")
        self.assertEqual(merged["cases"][0]["annotation_status"], "not_human_reviewed")
        self.assertEqual(merged["cases"][0]["annotations"], [])

    def test_packet_from_a_stale_candidate_dataset_is_rejected_before_merge(self):
        dataset = build_human_support_candidate_dataset(_retrieval_dataset(), _claims(), collected_at="2026-08-07T12:00:00Z")
        completed = build_blinded_candidate_packet(dataset)
        completed["cases"][0]["annotation"].update(
            {
                "annotator_id": "reviewer-a",
                "annotator_label": "supported",
                "rationale": "The original evidence entails the original claim.",
            }
        )
        refreshed_dataset = copy.deepcopy(dataset)
        refreshed_dataset["cases"][0]["evidence"] = "Refreshed evidence from a different source snapshot."

        merged, report = merge_candidate_annotation_packets(refreshed_dataset, [completed])

        self.assertFalse(report["ok"])
        self.assertEqual(report["skipped"][0]["code"], "packet_not_blinded_or_intact")
        self.assertIn("evidence differs from candidate", report["skipped"][0]["error"])
        self.assertEqual(merged["cases"][0]["annotation_status"], "not_human_reviewed")

    def test_candidate_contract_rejects_count_policy_and_nested_gold_drift(self):
        dataset = build_human_support_candidate_dataset(
            _retrieval_dataset(), _claims(), collected_at="2026-08-07T12:00:00Z"
        )

        bad_count = copy.deepcopy(dataset)
        bad_count["collection"]["case_count"] = 99
        with self.assertRaisesRegex(HumanSupportCandidateError, "collection.case_count"):
            validate_candidate_dataset(bad_count)

        bad_policy = copy.deepcopy(dataset)
        bad_policy["label_policy"]["gold_labels_included"] = True
        with self.assertRaisesRegex(HumanSupportCandidateError, "gold_labels_included"):
            validate_candidate_dataset(bad_policy)

        nested_gold = copy.deepcopy(dataset)
        nested_gold["cases"][0]["candidate_provenance"]["source_record"]["gold"] = "leaked"
        with self.assertRaisesRegex(HumanSupportCandidateError, "forbidden label field"):
            validate_candidate_dataset(nested_gold)

    def test_packet_contract_rejects_case_index_drift(self):
        dataset = build_human_support_candidate_dataset(
            _retrieval_dataset(), _claims(), collected_at="2026-08-07T12:00:00Z"
        )
        packet = build_blinded_candidate_packet(dataset)
        packet["cases"][0]["packet_case_index"] = 7

        with self.assertRaisesRegex(HumanSupportCandidateError, "packet_case_index"):
            validate_blinded_candidate_packet(dataset, packet)

    def test_checked_in_pilot_artifacts_remain_gold_free_and_intact(self):
        root = Path(__file__).resolve().parents[1]
        dataset = json.loads((root / "data/eval/human_support_candidates.json").read_text(encoding="utf-8"))
        packet = json.loads((root / "experiments/human-support-pilot-packet.json").read_text(encoding="utf-8"))

        validate_candidate_dataset(dataset)
        summary = validate_blinded_candidate_packet(dataset, packet)

        self.assertTrue(summary["ok"])
        self.assertTrue(all("gold" not in row for row in dataset["cases"]))
        self.assertTrue(all("gold" not in row for row in packet["cases"]))

    def test_release_gate_records_checked_in_packet_integrity(self):
        root = Path(__file__).resolve().parents[1]
        summary = {"ok": True, "steps": []}

        _record_human_candidate_packet_contract_gate(
            summary,
            project_root=root,
            dataset="data/eval/human_support_candidates.json",
            packet="experiments/human-support-pilot-packet.json",
        )

        self.assertTrue(summary["ok"])
        self.assertEqual(summary["steps"][-1]["name"], "human_candidate_packet_contract")
        self.assertEqual(summary["steps"][-1]["status"], "passed")
        self.assertEqual(summary["human_candidate_packet_contract"]["packet_case_count"], 12)
        self.assertEqual(summary["human_candidate_packet_contract"]["packet_schema_version"], 3)
        self.assertTrue(summary["human_candidate_packet_contract"]["candidate_digest"].startswith("sha256:"))
        self.assertTrue(summary["human_candidate_packet_contract"]["opaque_case_ids"])

    def test_release_gate_rejects_tampered_candidate_packet(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            packet_path = Path(directory) / "tampered-packet.json"
            packet = json.loads((root / "experiments/human-support-pilot-packet.json").read_text(encoding="utf-8"))
            packet["cases"][0]["claim"] = "Tampered after packet generation."
            packet_path.write_text(json.dumps(packet), encoding="utf-8")
            summary = {"ok": True, "steps": []}

            _record_human_candidate_packet_contract_gate(
                summary,
                project_root=root,
                dataset="data/eval/human_support_candidates.json",
                packet=str(packet_path),
            )

        self.assertFalse(summary["ok"])
        self.assertEqual(summary["steps"][-1]["name"], "human_candidate_packet_contract")
        self.assertEqual(summary["steps"][-1]["status"], "failed")
        self.assertIn("packet_digest", summary["steps"][-1]["message"])


if __name__ == "__main__":
    unittest.main()
