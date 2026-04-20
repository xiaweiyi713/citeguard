"""Systematic calibration helpers for support thresholds and ensemble weights."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from itertools import product
from typing import Dict, Iterable, List, Optional

from src.verifiers import (
    DEFAULT_NLI_MODEL,
    DEFAULT_RERANKER_MODEL,
    EnsembleSupportPolicy,
    HeuristicSupportBackend,
    SentenceTransformerRerankerBackend,
    SupportAssessment,
    TransformersNLIBackend,
    combine_support_assessments,
)


@dataclass(frozen=True)
class SupportCalibrationExample:
    """Binary support-label example used during threshold calibration."""

    example_id: str
    claim_text: str
    evidence_text: str
    supported: bool
    note: str = ""


@dataclass(frozen=True)
class ScoredSupportExample:
    """Cached component scores for one support example."""

    example: SupportCalibrationExample
    heuristic_score: float
    heuristic_details: Dict[str, object]
    reranker_score: float
    reranker_details: Dict[str, object]
    nli_probabilities: Dict[str, float]
    nli_details: Dict[str, object]


@dataclass(frozen=True)
class SupportCalibrationConfig:
    """One full calibration setting spanning component thresholds and ensemble policy."""

    heuristic_threshold: float
    reranker_threshold: float
    nli_threshold: float
    nli_margin: float
    ensemble_policy: EnsembleSupportPolicy

    def to_dict(self) -> Dict[str, object]:
        payload = asdict(self)
        payload["ensemble_policy"]["weights"] = {
            key: round(value, 4)
            for key, value in self.ensemble_policy.normalized_weights().items()
        }
        return payload


@dataclass(frozen=True)
class SupportCalibrationMetrics:
    """Metrics reported for each calibration setting."""

    accuracy: float
    precision: float
    recall: float
    f1: float
    false_support_rate: float
    false_reject_rate: float
    true_positive: int
    true_negative: int
    false_positive: int
    false_negative: int

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def default_support_calibration_examples() -> List[SupportCalibrationExample]:
    """Small built-in dev set with positives, hard negatives, and near-miss paraphrases."""

    return [
        SupportCalibrationExample(
            example_id="pos-ghostcite-core",
            claim_text="Recent work analyzes phantom references and fabricated metadata in large language models.",
            evidence_text="We analyze citation validity, phantom references, and fabricated bibliographic metadata across many large language models.",
            supported=True,
            note="Direct support",
        ),
        SupportCalibrationExample(
            example_id="pos-openscholar-rag",
            claim_text="Retrieval-augmented language models have been used to synthesize scientific literature.",
            evidence_text="OpenScholar synthesizes scientific literature with retrieval-augmented language models and studies citation hallucinations in academic writing.",
            supported=True,
            note="Strong paraphrase",
        ),
        SupportCalibrationExample(
            example_id="pos-reasons-benchmark",
            claim_text="Benchmarks exist for retrieval and automated citations of scientific sentences.",
            evidence_text="REASONS is a benchmark for retrieval and automated citations of scientific sentences.",
            supported=True,
            note="Exact benchmark claim",
        ),
        SupportCalibrationExample(
            example_id="pos-sentence-attribution",
            claim_text="Scientific sentence attribution is a target task in recent citation benchmarks.",
            evidence_text="This benchmark studies retrieval, citation selection, and scientific sentence attribution.",
            supported=True,
            note="Partial lexical overlap but true support",
        ),
        SupportCalibrationExample(
            example_id="pos-large-scale-validity",
            claim_text="Citation validity has been measured at scale across many language models.",
            evidence_text="We measure phantom references, fabricated metadata, and citation validity across many large language models.",
            supported=True,
            note="Abstractive restatement",
        ),
        SupportCalibrationExample(
            example_id="pos-literature-synthesis",
            claim_text="Recent systems study citation hallucinations during scientific literature synthesis.",
            evidence_text="This work studies scientific literature synthesis and citation hallucinations.",
            supported=True,
            note="Short evidence snippet",
        ),
        SupportCalibrationExample(
            example_id="neg-overclaim-eliminates",
            claim_text="OpenScholar proves retrieval completely eliminates citation hallucinations.",
            evidence_text="OpenScholar synthesizes scientific literature with retrieval-augmented language models and studies citation hallucinations in academic writing.",
            supported=False,
            note="Overclaim from related evidence",
        ),
        SupportCalibrationExample(
            example_id="neg-domain-mismatch",
            claim_text="GhostCite studies protein folding datasets.",
            evidence_text="We analyze citation validity, phantom references, and fabricated bibliographic metadata across many large language models.",
            supported=False,
            note="Off-domain mismatch",
        ),
        SupportCalibrationExample(
            example_id="neg-topic-mismatch",
            claim_text="The benchmark focuses on multilingual translation quality.",
            evidence_text="REASONS is a benchmark for retrieval and automated citations of scientific sentences.",
            supported=False,
            note="Benchmark but wrong task",
        ),
        SupportCalibrationExample(
            example_id="neg-frequency-overclaim",
            claim_text="Recent work shows phantom references are rare in large language models.",
            evidence_text="We measure phantom references, fabricated metadata, and citation validity across many large language models.",
            supported=False,
            note="Frequency claim unsupported by evidence",
        ),
        SupportCalibrationExample(
            example_id="neg-causal-overclaim",
            claim_text="Citation hallucinations are mainly caused by tokenizer bugs.",
            evidence_text="This work studies scientific literature synthesis and citation hallucinations.",
            supported=False,
            note="Causal overclaim",
        ),
        SupportCalibrationExample(
            example_id="neg-method-overclaim",
            claim_text="The citation validity paper introduces a theorem prover for mathematics competitions.",
            evidence_text="We analyze citation validity, phantom references, and fabricated bibliographic metadata across many large language models.",
            supported=False,
            note="Method mismatch",
        ),
    ]


def score_support_examples(
    examples: Iterable[SupportCalibrationExample],
    reranker_model_name: str = DEFAULT_RERANKER_MODEL,
    nli_model_name: str = DEFAULT_NLI_MODEL,
) -> List[ScoredSupportExample]:
    """Compute raw component scores once so grid search can be analytical afterwards."""

    heuristic_backend = HeuristicSupportBackend()
    reranker_backend = SentenceTransformerRerankerBackend(
        model_name=reranker_model_name,
        threshold=0.0,
    )
    nli_backend = TransformersNLIBackend(
        model_name=nli_model_name,
        threshold=0.0,
        margin=-1.0,
    )
    if not reranker_backend.is_available():
        raise RuntimeError("Sentence-transformers reranker backend is unavailable.")
    if not nli_backend.is_available():
        raise RuntimeError("Transformers NLI backend is unavailable.")

    scored: List[ScoredSupportExample] = []
    for example in examples:
        heuristic = heuristic_backend.assess(example.claim_text, example.evidence_text)
        reranker = reranker_backend.assess(example.claim_text, example.evidence_text)
        nli = nli_backend.assess(example.claim_text, example.evidence_text)
        scored.append(
            ScoredSupportExample(
                example=example,
                heuristic_score=heuristic.score,
                heuristic_details=heuristic.details,
                reranker_score=reranker.score,
                reranker_details=reranker.details,
                nli_probabilities=dict(nli.details.get("probabilities", {})),
                nli_details=nli.details,
            )
        )
    return scored


def evaluate_support_config(
    scored_examples: Iterable[ScoredSupportExample],
    config: SupportCalibrationConfig,
) -> SupportCalibrationMetrics:
    """Evaluate one configuration against the cached example scores."""

    tp = tn = fp = fn = 0
    for example in scored_examples:
        assessment = combine_support_assessments(
            _rebuild_component_assessments(example, config),
            policy=config.ensemble_policy,
        )
        predicted = assessment.passed
        gold = example.example.supported
        if predicted and gold:
            tp += 1
        elif predicted and not gold:
            fp += 1
        elif not predicted and gold:
            fn += 1
        else:
            tn += 1

    total = max(tp + tn + fp + fn, 1)
    positives = max(tp + fn, 1)
    negatives = max(tn + fp, 1)
    precision = tp / max(tp + fp, 1)
    recall = tp / positives
    accuracy = (tp + tn) / total
    false_support_rate = fp / negatives
    false_reject_rate = fn / positives
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return SupportCalibrationMetrics(
        accuracy=round(accuracy, 4),
        precision=round(precision, 4),
        recall=round(recall, 4),
        f1=round(f1, 4),
        false_support_rate=round(false_support_rate, 4),
        false_reject_rate=round(false_reject_rate, 4),
        true_positive=tp,
        true_negative=tn,
        false_positive=fp,
        false_negative=fn,
    )


def grid_search_support_configs(
    scored_examples: Iterable[ScoredSupportExample],
    top_k: int = 10,
    profile: str = "standard",
) -> List[Dict[str, object]]:
    """Search threshold and weight combinations and return the strongest configurations."""

    scored_rows = list(scored_examples)
    if profile not in {"quick", "standard"}:
        raise ValueError("profile must be 'quick' or 'standard'")

    grids = {
        "quick": {
            "heuristic_thresholds": [0.16, 0.18, 0.22],
            "reranker_thresholds": [0.45, 0.48, 0.52],
            "nli_thresholds": [0.50, 0.55, 0.60],
            "nli_margins": [0.03, 0.05, 0.08],
            "pair_nli_floors": [0.25, 0.30, 0.35],
            "pair_combined_thresholds": [0.24, 0.28, 0.32],
            "contradiction_maxes": [0.08, 0.10, 0.12],
            "fallback_combined_thresholds": [0.42, 0.48, 0.54],
            "weight_pairs": [
                (0.45, 0.35),
                (0.55, 0.30),
                (0.65, 0.20),
            ],
        },
        "standard": {
            "heuristic_thresholds": [0.14, 0.18, 0.22, 0.26],
            "reranker_thresholds": [0.42, 0.48, 0.54, 0.60],
            "nli_thresholds": [0.48, 0.55, 0.62],
            "nli_margins": [0.02, 0.05, 0.08],
            "pair_nli_floors": [0.24, 0.30, 0.36],
            "pair_combined_thresholds": [0.24, 0.28, 0.32, 0.36],
            "contradiction_maxes": [0.08, 0.10, 0.12],
            "fallback_combined_thresholds": [0.40, 0.48, 0.56],
            "weight_pairs": [
                (0.45, 0.35),
                (0.50, 0.30),
                (0.55, 0.30),
                (0.60, 0.25),
                (0.65, 0.20),
            ],
        },
    }[profile]

    results = []
    for heuristic_threshold, reranker_threshold, nli_threshold, nli_margin in product(
        grids["heuristic_thresholds"],
        grids["reranker_thresholds"],
        grids["nli_thresholds"],
        grids["nli_margins"],
    ):
        for pair_nli_floor, pair_combined_threshold, contradiction_max, fallback_combined_threshold in product(
            grids["pair_nli_floors"],
            grids["pair_combined_thresholds"],
            grids["contradiction_maxes"],
            grids["fallback_combined_thresholds"],
        ):
            for nli_weight, reranker_weight in grids["weight_pairs"]:
                heuristic_weight = round(1.0 - nli_weight - reranker_weight, 4)
                if heuristic_weight <= 0:
                    continue
                config = SupportCalibrationConfig(
                    heuristic_threshold=heuristic_threshold,
                    reranker_threshold=reranker_threshold,
                    nli_threshold=nli_threshold,
                    nli_margin=nli_margin,
                    ensemble_policy=EnsembleSupportPolicy(
                        weights={
                            "transformers_nli": nli_weight,
                            "sentence_transformer_reranker": reranker_weight,
                            "heuristic_support": heuristic_weight,
                        },
                        pair_nli_floor=pair_nli_floor,
                        pair_combined_threshold=pair_combined_threshold,
                        contradiction_max=contradiction_max,
                        fallback_combined_threshold=fallback_combined_threshold,
                    ),
                )
                metrics = evaluate_support_config(scored_rows, config)
                results.append(
                    {
                        "config": config.to_dict(),
                        "metrics": metrics.to_dict(),
                    }
                )

    ranked = sorted(
        results,
        key=lambda item: (
            item["metrics"]["f1"],
            item["metrics"]["precision"],
            1.0 - item["metrics"]["false_support_rate"],
            item["metrics"]["accuracy"],
            item["metrics"]["recall"],
        ),
        reverse=True,
    )
    return ranked[:top_k]


def _rebuild_component_assessments(
    scored_example: ScoredSupportExample,
    config: SupportCalibrationConfig,
) -> List[SupportAssessment]:
    overlap_terms = scored_example.heuristic_details.get("overlap_terms", [])
    entailment = float(scored_example.nli_probabilities.get("entailment", 0.0))
    contradiction = float(scored_example.nli_probabilities.get("contradiction", 0.0))
    return [
        SupportAssessment(
            backend_name="transformers_nli",
            score=entailment,
            passed=entailment >= config.nli_threshold and entailment >= contradiction + config.nli_margin,
            rationale="Calibrated NLI assessment.",
            details={
                "probabilities": dict(scored_example.nli_probabilities),
                **dict(scored_example.nli_details),
            },
        ),
        SupportAssessment(
            backend_name="sentence_transformer_reranker",
            score=scored_example.reranker_score,
            passed=scored_example.reranker_score >= config.reranker_threshold,
            rationale="Calibrated reranker assessment.",
            details=dict(scored_example.reranker_details),
        ),
        SupportAssessment(
            backend_name="heuristic_support",
            score=scored_example.heuristic_score,
            passed=scored_example.heuristic_score >= config.heuristic_threshold and len(overlap_terms) >= 2,
            rationale="Calibrated heuristic assessment.",
            details=dict(scored_example.heuristic_details),
        ),
    ]
