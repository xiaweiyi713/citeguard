"""Promotion tests use invented labels solely as code fixtures, not benchmark data."""

from __future__ import annotations

import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from citeguard.benchmark.human_candidates import (
    HumanSupportCandidateError,
    build_blinded_candidate_packet,
    build_human_support_candidate_dataset,
)
from citeguard.benchmark.human_adjudication import (
    build_candidate_adjudication_packet,
    validate_candidate_adjudication_packet,
)
from citeguard.benchmark.human_promotion import promote_human_support_candidates
from scripts.prepare_human_support_adjudications import main as prepare_adjudication_main
from scripts.promote_human_support_candidates import main as promote_main


ROOT = Path(__file__).resolve().parents[1]


def _inputs():
    retrieval = {
        "schema_version": 1,
        "cases": [{
            "id": "source-1",
            "ground_truth_locator": "https://doi.org/10.1000/promotion-test",
            "lang": "en",
            "domain": "computer_science",
            "curation": {"source": "public"},
            "metadata_snapshot": {"abstract": "A measured result was observed."},
        }],
    }
    claims = {
        "campaign_id": "promotion-test",
        "claims": [{
            "id": "promotion-case-1",
            "source_case_id": "source-1",
            "claim": "A measured result was observed.",
            "lang": "en",
            "domain": "computer_science",
            "writing_context": "research_article",
            "evidence_scope": "abstract",
            "rights_basis": "public_abstract",
            "case_type": "direct_support",
            "split": "test",
        }],
    }
    candidates = build_human_support_candidate_dataset(retrieval, claims, collected_at="2026-08-07T12:00:00Z")
    dataset = json.loads((ROOT / "data/eval/support_eval.json").read_text(encoding="utf-8"))
    sidecar = json.loads((ROOT / "data/eval/support_eval_label_sidecar.json").read_text(encoding="utf-8"))
    return candidates, dataset, sidecar


def _packets(candidates, second_label="supported"):
    packet = build_blinded_candidate_packet(candidates)
    packets = []
    for reviewer, label in (("reviewer-a", "supported"), ("reviewer-b", second_label)):
        completed = copy.deepcopy(packet)
        completed["cases"][0]["annotation"].update({
            "annotator_id": reviewer,
            "annotator_label": label,
            "rationale": "The supplied abstract states the claim.",
        })
        packets.append(completed)
    return packets


class HumanPromotionTests(unittest.TestCase):
    def test_two_intact_packets_promote_with_provenance(self):
        candidates, dataset, sidecar = _inputs()
        updated, labels, report = promote_human_support_candidates(
            candidates, _packets(candidates), dataset, sidecar, curator_id="curator-1"
        )
        self.assertEqual(report["promoted_case_ids"], ["promotion-case-1"])
        self.assertFalse(report["benchmark_ready"])
        row = updated["cases"][-1]
        self.assertEqual(row["gold"], "supported")
        self.assertEqual(row["benchmark_origin"], "real_source")
        self.assertEqual(row["source_case_id"], "source-1")
        self.assertEqual(labels["cases"][-1]["annotator_ids"], ["reviewer-a", "reviewer-b"])
        self.assertEqual(len(labels["cases"][-1]["review_provenance"]), 2)
        self.assertNotIn("The supplied abstract", json.dumps(updated))
        self.assertNotIn("The supplied abstract", json.dumps(labels))
        self.assertTrue(labels["cases"][-1]["review_provenance"][0]["completed_packet_digest"].startswith("sha256:"))
        self.assertEqual(len(dataset["cases"]) + 1, len(updated["cases"]))
        self.assertNotIn("gold", candidates["cases"][0])

    def test_single_disagreement_and_curator_collision_do_not_promote(self):
        candidates, dataset, sidecar = _inputs()
        for packets, curator, code in (
            (_packets(candidates)[:1], "curator-1", None),
            (_packets(candidates, "insufficient_evidence"), "curator-1", "requires_independent_adjudication"),
            (_packets(candidates), "reviewer-a", "reviewers_must_be_distinct_from_curator"),
        ):
            if code is None:
                with self.assertRaisesRegex(HumanSupportCandidateError, "at least two"):
                    promote_human_support_candidates(candidates, packets, dataset, sidecar, curator_id=curator)
            else:
                updated, _, report = promote_human_support_candidates(
                    candidates, packets, dataset, sidecar, curator_id=curator
                )
                self.assertEqual(report["promoted_count"], 0)
                self.assertEqual(report["skipped"][0]["code"], code)
                self.assertEqual(updated, dataset)
                if code == "requires_independent_adjudication":
                    self.assertEqual(report["unresolved_disagreement_case_ids"], ["promotion-case-1"])
                    self.assertEqual(report["next_action"], "obtain_independent_adjudication")

    def test_independent_adjudication_preserves_original_disagreement(self):
        candidates, dataset, sidecar = _inputs()
        packets = _packets(candidates, "insufficient_evidence")
        adjudications = build_candidate_adjudication_packet(candidates, packets)
        self.assertEqual(adjudications["case_count"], 1)
        row = adjudications["cases"][0]
        self.assertTrue(row["case_id"].startswith("review-"))
        self.assertNotIn("case_type", row)
        self.assertNotIn("split", row)
        row["decision"].update({
            "adjudicator_id": "reviewer-c",
            "adjudicated_label": "weakly_supported",
            "rationale": "Both original readings overstated the evidence boundary.",
        })
        verified = validate_candidate_adjudication_packet(candidates, packets, adjudications)
        self.assertEqual(verified["completed_count"], 1)

        updated, labels, report = promote_human_support_candidates(
            candidates, packets, dataset, sidecar, curator_id="curator-1", adjudications=adjudications
        )
        self.assertEqual(report["adjudicated_case_ids"], ["promotion-case-1"])
        self.assertEqual(updated["cases"][-1]["gold"], "weakly_supported")
        sidecar_row = labels["cases"][-1]
        self.assertEqual(sidecar_row["adjudication_status"], "dual_annotator_adjudicated")
        self.assertEqual(sidecar_row["annotator_labels"], ["supported", "insufficient_evidence"])
        self.assertEqual(sidecar_row["disagreement"], "resolved")
        self.assertEqual(sidecar_row["adjudicator"], "reviewer-c")
        self.assertTrue(sidecar_row["adjudication_provenance"]["completed_packet_digest"].startswith("sha256:"))
        self.assertNotIn("Both original readings", json.dumps(updated))
        self.assertNotIn("Both original readings", json.dumps(labels))

    def test_adjudication_rejects_tampering_and_self_review(self):
        candidates, dataset, sidecar = _inputs()
        packets = _packets(candidates, "insufficient_evidence")
        adjudications = build_candidate_adjudication_packet(candidates, packets)
        adjudications["cases"][0]["decision"].update({
            "adjudicator_id": "reviewer-c",
            "adjudicated_label": "weakly_supported",
            "rationale": "A distinct decision based on the supplied excerpt.",
        })

        changed = copy.deepcopy(adjudications)
        changed["cases"][0]["annotations"][0]["annotator_label"] = "contradicted"
        with self.assertRaisesRegex(HumanSupportCandidateError, "differs from the reviewed"):
            validate_candidate_adjudication_packet(candidates, packets, changed)

        changed = copy.deepcopy(adjudications)
        changed["cases"][0]["evidence"] = "Altered evidence."
        with self.assertRaisesRegex(HumanSupportCandidateError, "differs from the reviewed"):
            validate_candidate_adjudication_packet(candidates, packets, changed)

        self_review = copy.deepcopy(adjudications)
        self_review["cases"][0]["decision"]["adjudicator_id"] = "reviewer-a"
        with self.assertRaisesRegex(HumanSupportCandidateError, "third reviewer"):
            validate_candidate_adjudication_packet(candidates, packets, self_review)

        updated, _, report = promote_human_support_candidates(
            candidates, packets, dataset, sidecar, curator_id="reviewer-c", adjudications=adjudications
        )
        self.assertEqual(updated, dataset)
        self.assertEqual(report["skipped"][0]["code"], "curator_must_be_distinct_from_adjudicator")

    def test_adjudication_template_is_private_and_fails_closed_on_partial_decision(self):
        candidates, _, _ = _inputs()
        packets = _packets(candidates, "insufficient_evidence")
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            candidate_path = base / "candidates.json"
            packet_paths = [base / "a.json", base / "b.json"]
            output = base / "adjudications.json"
            for path, value in zip([candidate_path, *packet_paths], [candidates, *packets]):
                path.write_text(json.dumps(value), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                code = prepare_adjudication_main([
                    "--candidates", str(candidate_path), "--packet", str(packet_paths[0]),
                    "--packet", str(packet_paths[1]), "--output", str(output),
                ])
            self.assertEqual(code, 0)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            template = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(template["cases"][0]["decision"]["adjudicated_label"], "")
            template["cases"][0]["decision"]["adjudicator_id"] = "reviewer-c"
            with self.assertRaisesRegex(HumanSupportCandidateError, "partial decision"):
                validate_candidate_adjudication_packet(candidates, packets, template)

    def test_cli_promotes_completed_third_party_adjudication(self):
        candidates, dataset, sidecar = _inputs()
        packets = _packets(candidates, "insufficient_evidence")
        adjudications = build_candidate_adjudication_packet(candidates, packets)
        adjudications["cases"][0]["decision"].update({
            "adjudicator_id": "reviewer-c",
            "adjudicated_label": "weakly_supported",
            "rationale": "The excerpt justifies a narrower claim.",
        })
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = [base / name for name in (
                "candidates.json", "a.json", "b.json", "dataset.json", "sidecar.json", "adjudications.json"
            )]
            for path, value in zip(paths, (candidates, *packets, dataset, sidecar, adjudications)):
                path.write_text(json.dumps(value), encoding="utf-8")
            updated_dataset = base / "proposed-dataset.json"
            updated_sidecar = base / "proposed-sidecar.json"
            with redirect_stdout(io.StringIO()):
                code = promote_main([
                    "--candidates", str(paths[0]), "--packet", str(paths[1]), "--packet", str(paths[2]),
                    "--dataset", str(paths[3]), "--label-sidecar", str(paths[4]),
                    "--adjudications", str(paths[5]), "--curator-id", "curator-1", "--approve",
                    "--dataset-output", str(updated_dataset), "--sidecar-output", str(updated_sidecar),
                ])
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(updated_dataset.read_text())["cases"][-1]["gold"], "weakly_supported")
            self.assertEqual(
                json.loads(updated_sidecar.read_text())["cases"][-1]["adjudication_status"],
                "dual_annotator_adjudicated",
            )

    def test_rejected_packet_and_forged_merged_status_cannot_promote(self):
        candidates, dataset, sidecar = _inputs()
        packets = _packets(candidates)
        packets[1]["cases"][0]["claim"] = "Tampered after review."
        with self.assertRaisesRegex(HumanSupportCandidateError, "packet rows were rejected"):
            promote_human_support_candidates(candidates, packets, dataset, sidecar, curator_id="curator-1")

        forged = copy.deepcopy(candidates)
        forged["cases"][0]["annotation_status"] = "dual_annotator_agreed"
        with self.assertRaisesRegex(HumanSupportCandidateError, "original unlabeled"):
            promote_human_support_candidates(forged, _packets(forged), dataset, sidecar, curator_id="curator-1")

        reassigned = copy.deepcopy(candidates)
        reassigned["cases"][0]["split"] = "dev"
        with self.assertRaisesRegex(HumanSupportCandidateError, "packet rows were rejected"):
            promote_human_support_candidates(reassigned, _packets(candidates), dataset, sidecar, curator_id="curator-1")

    def test_existing_id_and_cross_split_source_are_skipped(self):
        candidates, dataset, sidecar = _inputs()
        duplicate = copy.deepcopy(candidates)
        duplicate["cases"][0]["id"] = dataset["cases"][0]["id"]
        _, _, report = promote_human_support_candidates(
            duplicate, _packets(duplicate), dataset, sidecar, curator_id="curator-1"
        )
        self.assertEqual(report["skipped"][0]["code"], "already_in_dataset")

        crossed = copy.deepcopy(dataset)
        crossed["cases"][0]["source_locator"] = candidates["cases"][0]["source_locator"]
        crossed["cases"][0]["split"] = "train"
        _, _, report = promote_human_support_candidates(
            candidates, _packets(candidates), crossed, sidecar, curator_id="curator-1"
        )
        self.assertEqual(report["skipped"][0]["code"], "source_crosses_splits")

        crossed_by_id = copy.deepcopy(dataset)
        crossed_by_id["cases"][0]["source_case_id"] = "source-1"
        crossed_by_id["cases"][0]["split"] = "train"
        _, _, report = promote_human_support_candidates(
            candidates, _packets(candidates), crossed_by_id, sidecar, curator_id="curator-1"
        )
        self.assertEqual(report["skipped"][0]["code"], "source_crosses_splits")

    def test_cli_previews_then_writes_new_outputs_only_with_approval(self):
        candidates, dataset, sidecar = _inputs()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            paths = [base / name for name in ("candidates.json", "a.json", "b.json", "dataset.json", "sidecar.json")]
            for path, payload in zip(paths, (candidates, *_packets(candidates), dataset, sidecar)):
                path.write_text(json.dumps(payload), encoding="utf-8")
            arguments = [
                "--candidates", str(paths[0]), "--packet", str(paths[1]), "--packet", str(paths[2]),
                "--dataset", str(paths[3]), "--label-sidecar", str(paths[4]), "--curator-id", "curator-1",
            ]
            staged_dataset = base / "staged-dataset.json"
            staged_sidecar = base / "staged-sidecar.json"
            with redirect_stdout(io.StringIO()):
                self.assertEqual(promote_main(arguments), 0)
            self.assertFalse(staged_dataset.exists())
            with redirect_stdout(io.StringIO()):
                self.assertEqual(promote_main(arguments + [
                    "--approve", "--dataset-output", str(staged_dataset),
                    "--sidecar-output", str(staged_sidecar),
                ]), 0)
            self.assertEqual(json.loads(staged_dataset.read_text())["cases"][-1]["gold"], "supported")
            self.assertEqual(json.loads(staged_sidecar.read_text())["cases"][-1]["curator_id"], "curator-1")
            self.assertEqual(staged_dataset.stat().st_mode & 0o777, 0o600)
            self.assertEqual(staged_sidecar.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(paths[3].read_text()), dataset)

    def test_promotion_publish_failure_leaves_no_partial_bundle(self):
        candidates, dataset, sidecar = _inputs()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            inputs = [base / name for name in ("candidates.json", "a.json", "b.json", "dataset.json", "sidecar.json")]
            for path, value in zip(inputs, (candidates, *_packets(candidates), dataset, sidecar)):
                path.write_text(json.dumps(value), encoding="utf-8")
            output_dataset = base / "proposed-dataset.json"
            output_sidecar = base / "proposed-sidecar.json"
            report_path = base / "report.json"
            args = [
                "--candidates", str(inputs[0]), "--packet", str(inputs[1]), "--packet", str(inputs[2]),
                "--dataset", str(inputs[3]), "--label-sidecar", str(inputs[4]),
                "--curator-id", "curator-1", "--approve",
                "--dataset-output", str(output_dataset), "--sidecar-output", str(output_sidecar),
                "--report", str(report_path),
            ]
            real_link = os.link
            calls = 0

            def fail_second(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected publish failure")
                return real_link(source, target)

            with patch("scripts.promote_human_support_candidates.os.link", side_effect=fail_second):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = promote_main(args)
            self.assertEqual(code, 2)
            self.assertFalse(output_dataset.exists())
            self.assertFalse(output_sidecar.exists())
            self.assertFalse(report_path.exists())
            self.assertFalse(list(base.glob(".*.tmp")))
            self.assertEqual(json.loads(inputs[3].read_text()), dataset)

            calls = 0

            def fail_report(source, target):
                nonlocal calls
                calls += 1
                if calls == 3:
                    raise OSError("injected report failure")
                return real_link(source, target)

            with patch("scripts.promote_human_support_candidates.os.link", side_effect=fail_report):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = promote_main(args)
            self.assertEqual(code, 2)
            self.assertFalse(output_dataset.exists())
            self.assertFalse(output_sidecar.exists())
            self.assertFalse(report_path.exists())
            self.assertFalse(list(base.glob(".*.tmp")))

            calls = 0

            def modify_first_then_fail(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    output_dataset.write_text("external in-place edit", encoding="utf-8")
                    raise OSError("injected concurrent edit")
                return real_link(source, target)

            with patch("scripts.promote_human_support_candidates.os.link", side_effect=modify_first_then_fail):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = promote_main(args)
            self.assertEqual(code, 2)
            self.assertEqual(output_dataset.read_text(encoding="utf-8"), "external in-place edit")
            self.assertFalse(output_sidecar.exists())
            self.assertFalse(report_path.exists())
            self.assertFalse(list(base.glob(".*.tmp")))
            output_dataset.unlink()

            calls = 0

            def replace_first_then_fail(source, target):
                nonlocal calls
                calls += 1
                if calls == 2:
                    output_dataset.unlink()
                    output_dataset.write_text("external replacement", encoding="utf-8")
                    raise OSError("injected concurrent replacement")
                return real_link(source, target)

            with patch("scripts.promote_human_support_candidates.os.link", side_effect=replace_first_then_fail):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = promote_main(args)
            self.assertEqual(code, 2)
            self.assertEqual(output_dataset.read_text(encoding="utf-8"), "external replacement")
            self.assertFalse(output_sidecar.exists())
            self.assertFalse(report_path.exists())
            self.assertFalse(list(base.glob(".*.tmp")))


if __name__ == "__main__":
    unittest.main()
