"""Preload and validate the production reranker and NLI models."""

from __future__ import annotations

import argparse
import json

from _bootstrap import ensure_project_root

ensure_project_root()

from citeguard.model_tools import warmup_support_models  # noqa: E402
from citeguard.verifiers import DEFAULT_NLI_MODEL, DEFAULT_RERANKER_MODEL  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="Warm up CiteGuard support models.")
    parser.add_argument("--reranker-model", default=DEFAULT_RERANKER_MODEL)
    parser.add_argument("--nli-model", default=DEFAULT_NLI_MODEL)
    args = parser.parse_args()

    output = warmup_support_models(args.reranker_model, args.nli_model)
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
