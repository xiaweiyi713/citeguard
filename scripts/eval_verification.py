"""Run the offline verification evaluation and print metrics."""

from __future__ import annotations

import argparse
import json

from _bootstrap import ensure_project_root

ensure_project_root()

from citeguard.benchmark.experiments import write_experiment_artifacts
from citeguard.verification.eval import load_eval, run_eval


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate CiteGuard citation verification offline.")
    parser.add_argument("--dataset", default="data/eval/verification_eval.json")
    parser.add_argument(
        "--output-dir",
        help="Optional directory for standardized experiment artifacts, e.g. experiments/.",
    )
    parser.add_argument("--run-id", help="Optional stable run id for the experiment artifact folder.")
    args = parser.parse_args()

    corpus, cases = load_eval(args.dataset)
    metrics = run_eval(corpus, cases)
    if args.output_dir:
        metrics["experiment_artifact"] = write_experiment_artifacts(
            "verification_eval",
            metrics,
            {
                "script": "scripts/eval_verification.py",
                "dataset": args.dataset,
                "case_count": len(cases),
                "corpus_count": len(corpus),
            },
            output_dir=args.output_dir,
            run_id=args.run_id,
        )
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
