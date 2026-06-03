"""Run the offline verification evaluation and print metrics."""

from __future__ import annotations

import argparse
import json

from _bootstrap import ensure_project_root

ensure_project_root()

from src.verification.eval import load_eval, run_eval


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate CiteGuard citation verification offline.")
    parser.add_argument("--dataset", default="data/eval/verification_eval.json")
    args = parser.parse_args()

    corpus, cases = load_eval(args.dataset)
    metrics = run_eval(corpus, cases)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
