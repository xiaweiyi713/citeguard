"""Sweep uncalibrated support thresholds on the real-source hard-case slice."""

from __future__ import annotations

import argparse
import json
import sys

from _bootstrap import ensure_project_root

ensure_project_root()

from citeguard.verification.support_calibration import evaluate_hard_case_thresholds


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report false-support vs recall tradeoffs. Does not change production thresholds."
    )
    parser.add_argument("--dataset", default="data/eval/support_hard_cases_v1.json")
    parser.add_argument("--output", default="", help="Optional JSON output path.")
    args = parser.parse_args()
    report = evaluate_hard_case_thresholds(args.dataset)
    payload = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    else:
        sys.stdout.write(payload + "\n")


if __name__ == "__main__":
    main()
