"""Preload and validate the production reranker and NLI models."""

from __future__ import annotations

import argparse
import json

from _bootstrap import ensure_project_root

ensure_project_root()

from src.verifiers import (  # noqa: E402
    DEFAULT_NLI_MODEL,
    DEFAULT_RERANKER_MODEL,
    SentenceTransformerRerankerBackend,
    TransformersNLIBackend,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Warm up CiteGuard support models.")
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--nli-model", default=DEFAULT_NLI_MODEL)
    args = parser.parse_args()

    claim = "The literature analyzes phantom references and fabricated metadata in large language models."
    evidence = "This paper analyzes phantom references and fabricated bibliographic metadata in large language models."

    reranker = SentenceTransformerRerankerBackend(model_name=args.reranker_model)
    nli = TransformersNLIBackend(model_name=args.nli_model)

    output = {
        "reranker": reranker.assess(claim, evidence).__dict__,
        "nli": nli.assess(claim, evidence).__dict__,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
