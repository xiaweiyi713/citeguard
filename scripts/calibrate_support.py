"""Systematically calibrate support thresholds and ensemble weights."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from _bootstrap import ensure_project_root

ensure_project_root()

from citeguard.benchmark import (
    ScoredSupportExample,
    SupportCalibrationExample,
    default_support_calibration_examples,
    grid_search_support_configs,
    load_support_eval_calibration_examples,
    score_support_examples,
    write_experiment_artifacts,
)
from citeguard.verifiers import DEFAULT_NLI_MODEL, DEFAULT_RERANKER_MODEL


def load_examples(path: Path) -> List[SupportCalibrationExample]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [
        SupportCalibrationExample(
            example_id=row["example_id"],
            claim_text=row["claim_text"],
            evidence_text=row["evidence_text"],
            supported=bool(row["supported"]),
            note=row.get("note", ""),
        )
        for row in rows
    ]


def load_scored_examples(path: Path) -> List[ScoredSupportExample]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    examples = []
    for row in rows:
        example_row = row.get("example", row)
        examples.append(
            ScoredSupportExample(
                example=SupportCalibrationExample(
                    example_id=example_row["example_id"],
                    claim_text=example_row["claim_text"],
                    evidence_text=example_row["evidence_text"],
                    supported=bool(example_row["supported"]),
                    note=example_row.get("note", ""),
                ),
                heuristic_score=float(row["heuristic_score"]),
                heuristic_details=dict(row.get("heuristic_details", {})),
                reranker_score=float(row["reranker_score"]),
                reranker_details=dict(row.get("reranker_details", {})),
                nli_probabilities=dict(row.get("nli_probabilities", {})),
                nli_details=dict(row.get("nli_details", {})),
            )
        )
    return examples


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate CiteGuard support backends.")
    parser.add_argument("--dataset", help="Optional JSON dataset path.")
    parser.add_argument(
        "--support-eval-dataset",
        help="Optional support_eval.json path; converts one split into binary strong-support examples.",
    )
    parser.add_argument(
        "--split",
        default="dev",
        help="Split to use with --support-eval-dataset. Defaults to dev so calibration does not touch test.",
    )
    parser.add_argument(
        "--scored-dataset",
        help="Optional JSON file with cached component scores; avoids loading model backends.",
    )
    parser.add_argument(
        "--profile",
        default="standard",
        choices=["quick", "standard"],
        help="Grid-search size profile.",
    )
    parser.add_argument("--top-k", type=int, default=5, help="How many ranked configs to print.")
    parser.add_argument(
        "--reranker-model",
        default=DEFAULT_RERANKER_MODEL,
        help="Sentence-transformer or cross-encoder reranker model.",
    )
    parser.add_argument(
        "--nli-model",
        default=DEFAULT_NLI_MODEL,
        help="Transformers NLI model.",
    )
    parser.add_argument("--output", help="Optional JSON file to write the ranked results.")
    parser.add_argument("--output-dir", help="Optional directory for standardized experiment artifacts.")
    parser.add_argument("--run-id", help="Optional run id for standardized experiment artifacts.")
    args = parser.parse_args()

    configured_inputs = [bool(args.dataset), bool(args.support_eval_dataset), bool(args.scored_dataset)]
    if sum(configured_inputs) > 1:
        parser.error("--dataset, --support-eval-dataset, and --scored-dataset are mutually exclusive")

    if args.scored_dataset:
        scored_examples = load_scored_examples(Path(args.scored_dataset))
        examples = [row.example for row in scored_examples]
        input_mode = "scored_dataset"
    else:
        if args.support_eval_dataset:
            examples = load_support_eval_calibration_examples(args.support_eval_dataset, split=args.split)
            input_mode = "support_eval_split"
        else:
            examples = load_examples(Path(args.dataset)) if args.dataset else default_support_calibration_examples()
            input_mode = "raw_examples"
        scored_examples = score_support_examples(
            examples,
            reranker_model_name=args.reranker_model,
            nli_model_name=args.nli_model,
        )

    ranked = grid_search_support_configs(
        scored_examples,
        top_k=args.top_k,
        profile=args.profile,
    )
    payload = {
        "profile": args.profile,
        "input_mode": input_mode,
        "dataset_size": len(examples),
        "top_results": ranked,
    }
    if args.output_dir:
        payload["experiment_artifact"] = write_experiment_artifacts(
            "support_calibration",
            payload,
            {
                "script": "scripts/calibrate_support.py",
                "dataset": args.dataset or "",
                "support_eval_dataset": args.support_eval_dataset or "",
                "split": args.split if args.support_eval_dataset else "",
                "scored_dataset": args.scored_dataset or "",
                "input_mode": input_mode,
                "profile": args.profile,
                "top_k": args.top_k,
                "reranker_model": args.reranker_model,
                "nli_model": args.nli_model,
                "dataset_size": len(examples),
            },
            output_dir=args.output_dir,
            run_id=args.run_id,
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
