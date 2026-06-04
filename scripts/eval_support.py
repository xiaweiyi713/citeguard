"""Run the claim-support evaluation. Needs the [models] extra for the deep engine."""

from __future__ import annotations

import argparse
import json

from _bootstrap import ensure_project_root

ensure_project_root()

from src.verifiers import build_production_support_backend
from src.verification.support_eval import load_support_eval, run_support_eval


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate CiteGuard claim-support assessment.")
    parser.add_argument("--dataset", default="data/eval/support_eval.json")
    args = parser.parse_args()
    cases = load_support_eval(args.dataset)
    metrics = run_support_eval(cases, build_production_support_backend())
    print(json.dumps(metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
