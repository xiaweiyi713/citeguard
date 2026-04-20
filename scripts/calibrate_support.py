"""Systematically calibrate support thresholds and ensemble weights."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

from _bootstrap import ensure_project_root

ensure_project_root()

from src.benchmark import (
    SupportCalibrationExample,
    default_support_calibration_examples,
    grid_search_support_configs,
    score_support_examples,
)
from src.verifiers import DEFAULT_NLI_MODEL, DEFAULT_RERANKER_MODEL


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


def main() -> None:
    parser = argparse.ArgumentParser(description="Calibrate CiteGuard support backends.")
    parser.add_argument("--dataset", help="Optional JSON dataset path.")
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
    args = parser.parse_args()

    examples = load_examples(Path(args.dataset)) if args.dataset else default_support_calibration_examples()
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
        "dataset_size": len(examples),
        "top_results": ranked,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
