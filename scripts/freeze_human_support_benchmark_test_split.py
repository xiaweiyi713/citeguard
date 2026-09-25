#!/usr/bin/env python3
"""Create the immutable manifest for CiteGuard's real held-out support test split."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

try:
    from _bootstrap import ensure_project_root
except ModuleNotFoundError:
    from scripts._bootstrap import ensure_project_root

ensure_project_root()

from scripts.audit_human_support_benchmark import (
    DEFAULT_TEST_SPLIT_MANIFEST,
    HumanBenchmarkCampaignError,
    audit_human_benchmark,
    build_test_split_manifest,
    load_json,
    validate_campaign,
)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Freeze CiteGuard's independently reviewed human benchmark test split.")
    parser.add_argument("--dataset", default="data/eval/support_eval.json")
    parser.add_argument("--label-sidecar", default="data/eval/support_eval_label_sidecar.json")
    parser.add_argument("--campaign", default="data/eval/human_support_benchmark_campaign.json")
    parser.add_argument("--output", default=DEFAULT_TEST_SPLIT_MANIFEST)
    parser.add_argument("--frozen-at", required=True, help="ISO-8601 timestamp with timezone, for example 2026-08-07T12:00:00Z.")
    args = parser.parse_args(argv)

    try:
        dataset = load_json(args.dataset)
        sidecar = load_json(args.label_sidecar)
        campaign = load_json(args.campaign)
        valid_campaign = validate_campaign(campaign)
        preflight = audit_human_benchmark(
            dataset,
            sidecar,
            valid_campaign,
            dataset_path=args.dataset,
        )
        manifest = build_test_split_manifest(dataset, sidecar, valid_campaign, frozen_at=args.frozen_at)
        minimum = int(valid_campaign["test_split"]["minimum_case_count"])
        if int(manifest["test_case_count"]) < minimum:
            raise HumanBenchmarkCampaignError(
                f"refusing to freeze {manifest['test_case_count']} test cases; campaign requires at least {minimum}"
            )
        if int(preflight["test_split"]["qualified_case_count"]) != int(manifest["test_case_count"]):
            raise HumanBenchmarkCampaignError(
                "refusing to freeze test rows with incomplete provenance or independent-review records"
            )
    except HumanBenchmarkCampaignError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 2

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(output), "manifest": manifest}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
