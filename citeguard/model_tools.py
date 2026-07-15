"""Installed-package utilities for model-backed claim-support checks."""

from __future__ import annotations

from typing import Optional


def warmup_support_models(reranker_model: Optional[str] = None, nli_model: Optional[str] = None) -> dict:
    """Download/load the configured support models and run a deterministic probe."""

    from citeguard.verifiers import (
        DEFAULT_NLI_MODEL,
        DEFAULT_RERANKER_MODEL,
        SentenceTransformerRerankerBackend,
        TransformersNLIBackend,
    )

    claim = "The literature analyzes phantom references and fabricated metadata in large language models."
    evidence = "This paper analyzes phantom references and fabricated bibliographic metadata in large language models."
    reranker_name = reranker_model or DEFAULT_RERANKER_MODEL
    nli_name = nli_model or DEFAULT_NLI_MODEL
    reranker = SentenceTransformerRerankerBackend(model_name=reranker_name)
    nli = TransformersNLIBackend(model_name=nli_name)
    return {
        "ok": True,
        "reranker_model": reranker_name,
        "nli_model": nli_name,
        "reranker": reranker.assess(claim, evidence).__dict__,
        "nli": nli.assess(claim, evidence).__dict__,
    }
