"""Pluggable support scoring backends."""

from __future__ import annotations

import math
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional

from src.citation import tokenize_text

DEFAULT_RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DEFAULT_NLI_MODEL = "cross-encoder/nli-distilroberta-base"
DEFAULT_ENSEMBLE_WEIGHTS = {
    "transformers_nli": 0.55,
    "sentence_transformer_reranker": 0.30,
    "heuristic_support": 0.15,
}


@dataclass(frozen=True)
class SupportAssessment:
    """Support score returned by a backend."""

    backend_name: str
    score: float
    passed: bool
    rationale: str
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EnsembleSupportPolicy:
    """Calibration-friendly policy controlling ensemble aggregation and gating."""

    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_ENSEMBLE_WEIGHTS))
    pair_nli_floor: float = 0.30
    pair_combined_threshold: float = 0.28
    contradiction_max: float = 0.10
    fallback_combined_threshold: float = 0.48

    def normalized_weights(self) -> Dict[str, float]:
        return _normalize_weights(self.weights)


DEFAULT_PRODUCTION_ENSEMBLE_POLICY = EnsembleSupportPolicy(
    weights={
        "transformers_nli": 0.45,
        "sentence_transformer_reranker": 0.35,
        "heuristic_support": 0.20,
    },
    pair_nli_floor=0.25,
    pair_combined_threshold=0.24,
    contradiction_max=0.08,
    fallback_combined_threshold=0.42,
)


class SupportBackend(ABC):
    """Interface for support scoring backends."""

    backend_name = "support_backend"

    def is_available(self) -> bool:
        return True

    @abstractmethod
    def assess(self, claim_text: str, evidence_text: str) -> SupportAssessment:
        """Return a support score for the claim/evidence pair."""


class HeuristicSupportBackend(SupportBackend):
    """Improved lexical baseline with phrase- and coverage-aware scoring."""

    backend_name = "heuristic_support"

    def __init__(self, threshold: float = 0.18) -> None:
        self.threshold = threshold

    def assess(self, claim_text: str, evidence_text: str) -> SupportAssessment:
        claim_tokens = set(tokenize_text(claim_text))
        evidence_tokens = set(tokenize_text(evidence_text))
        overlap = claim_tokens & evidence_tokens
        claim_coverage = len(overlap) / max(len(claim_tokens), 1)
        evidence_precision = len(overlap) / max(len(evidence_tokens), 1)
        phrase_bonus = self._phrase_bonus(claim_text, evidence_text)
        score = min(1.0, 0.55 * claim_coverage + 0.25 * evidence_precision + 0.20 * phrase_bonus)
        passed = score >= self.threshold and len(overlap) >= 2
        return SupportAssessment(
            backend_name=self.backend_name,
            score=score,
            passed=passed,
            rationale=(
                "Lexical overlap and phrase alignment indicate adequate support."
                if passed
                else "Lexical alignment remains too weak for reliable support."
            ),
            details={
                "overlap_terms": sorted(overlap),
                "claim_coverage": round(claim_coverage, 4),
                "evidence_precision": round(evidence_precision, 4),
                "phrase_bonus": round(phrase_bonus, 4),
            },
        )

    def _phrase_bonus(self, claim_text: str, evidence_text: str) -> float:
        claim_bigrams = self._ngrams(tokenize_text(claim_text), 2)
        evidence_bigrams = self._ngrams(tokenize_text(evidence_text), 2)
        if not claim_bigrams:
            return 0.0
        overlap = len(claim_bigrams & evidence_bigrams)
        return overlap / len(claim_bigrams)

    def _ngrams(self, tokens: List[str], size: int) -> set:
        return {tuple(tokens[index : index + size]) for index in range(len(tokens) - size + 1)}


class SentenceTransformerRerankerBackend(SupportBackend):
    """Optional semantic reranker based on sentence-transformers or cross-encoders."""

    backend_name = "sentence_transformer_reranker"

    def __init__(self, model_name: str = "", threshold: float = 0.48) -> None:
        self.model_name = model_name
        self.threshold = threshold
        self._model = None
        self._cross_encoder = None

    def is_available(self) -> bool:
        if not self.model_name:
            return False
        try:
            import sentence_transformers  # noqa: F401
        except Exception:
            return False
        return True

    def assess(self, claim_text: str, evidence_text: str) -> SupportAssessment:
        if not self.is_available():
            return SupportAssessment(
                backend_name=self.backend_name,
                score=0.0,
                passed=False,
                rationale="Sentence-transformers backend is unavailable in the current environment.",
                details={"available": False},
            )

        score = self._predict_score(claim_text, evidence_text)
        passed = score >= self.threshold
        return SupportAssessment(
            backend_name=self.backend_name,
            score=score,
            passed=passed,
            rationale=(
                "Semantic reranker assigned a strong relevance score."
                if passed
                else "Semantic reranker did not find enough evidence support."
            ),
            details={"model_name": self.model_name},
        )

    def _predict_score(self, claim_text: str, evidence_text: str) -> float:
        from sentence_transformers import SentenceTransformer, CrossEncoder, util

        if "cross-encoder" in self.model_name:
            if self._cross_encoder is None:
                self._cross_encoder = CrossEncoder(self.model_name)
            raw_score = float(self._cross_encoder.predict([(claim_text, evidence_text)])[0])
            return 1.0 / (1.0 + math.exp(-raw_score))

        if self._model is None:
            self._model = SentenceTransformer(self.model_name)
        embeddings = self._model.encode([claim_text, evidence_text], convert_to_tensor=True)
        score = float(util.cos_sim(embeddings[0], embeddings[1]).item())
        return (score + 1.0) / 2.0


class TransformersNLIBackend(SupportBackend):
    """Optional entailment backend using a transformers NLI classifier."""

    backend_name = "transformers_nli"

    def __init__(self, model_name: str = "", threshold: float = 0.55, margin: float = 0.05) -> None:
        self.model_name = model_name
        self.threshold = threshold
        self.margin = margin
        self._tokenizer = None
        self._model = None

    def is_available(self) -> bool:
        if not self.model_name:
            return False
        try:
            import transformers  # noqa: F401
        except Exception:
            return False
        return True

    def assess(self, claim_text: str, evidence_text: str) -> SupportAssessment:
        if not self.is_available():
            return SupportAssessment(
                backend_name=self.backend_name,
                score=0.0,
                passed=False,
                rationale="Transformers NLI backend is unavailable in the current environment.",
                details={"available": False},
            )

        probabilities = self._predict_probabilities(claim_text, evidence_text)
        entailment = probabilities.get("entailment", 0.0)
        contradiction = probabilities.get("contradiction", 0.0)
        passed = entailment >= self.threshold and entailment >= contradiction + self.margin
        return SupportAssessment(
            backend_name=self.backend_name,
            score=entailment,
            passed=passed,
            rationale=(
                "NLI model predicts entailment between the evidence and the claim."
                if passed
                else "NLI model does not assign sufficient entailment probability."
            ),
            details={"probabilities": probabilities, "model_name": self.model_name},
        )

    def _predict_probabilities(self, claim_text: str, evidence_text: str) -> Dict[str, float]:
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        if self._tokenizer is None or self._model is None:
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = AutoModelForSequenceClassification.from_pretrained(self.model_name)

        encoded = self._tokenizer(
            evidence_text,
            claim_text,
            return_tensors="pt",
            truncation=True,
        )
        output = self._model(**encoded)
        logits = output.logits[0].tolist()
        probabilities = _softmax(logits)
        label_map = {
            str(label).lower(): probabilities[index]
            for index, label in self._model.config.id2label.items()
        }
        return {
            "entailment": label_map.get("entailment", label_map.get("entails", 0.0)),
            "contradiction": label_map.get("contradiction", 0.0),
            "neutral": label_map.get("neutral", 0.0),
        }


class EnsembleSupportBackend(SupportBackend):
    """Weighted fusion over all available support backends."""

    backend_name = "ensemble_support"

    def __init__(
        self,
        backends: Iterable[SupportBackend],
        policy: Optional[EnsembleSupportPolicy] = None,
    ) -> None:
        self.backends = list(backends)
        self.policy = policy or EnsembleSupportPolicy()

    def is_available(self) -> bool:
        return any(backend.is_available() for backend in self.backends)

    def assess(self, claim_text: str, evidence_text: str) -> SupportAssessment:
        assessments = []
        for backend in self.backends:
            if backend.is_available() or backend.backend_name == "heuristic_support":
                assessments.append(backend.assess(claim_text, evidence_text))
        return combine_support_assessments(assessments, policy=self.policy)


def build_default_support_backend(
    reranker_model_name: str = "",
    nli_model_name: str = "",
    heuristic_threshold: float = 0.18,
    reranker_threshold: float = 0.48,
    nli_threshold: float = 0.55,
    nli_margin: float = 0.05,
    ensemble_policy: Optional[EnsembleSupportPolicy] = None,
) -> EnsembleSupportBackend:
    """Create the default backend stack."""

    backends: List[SupportBackend] = [
        TransformersNLIBackend(
            model_name=nli_model_name,
            threshold=nli_threshold,
            margin=nli_margin,
        ),
        SentenceTransformerRerankerBackend(
            model_name=reranker_model_name,
            threshold=reranker_threshold,
        ),
        HeuristicSupportBackend(threshold=heuristic_threshold),
    ]
    return EnsembleSupportBackend(backends, policy=ensemble_policy)


def build_production_support_backend(
    reranker_model_name: str = DEFAULT_RERANKER_MODEL,
    nli_model_name: str = DEFAULT_NLI_MODEL,
    heuristic_threshold: float = 0.16,
    reranker_threshold: float = 0.45,
    nli_threshold: float = 0.50,
    nli_margin: float = 0.03,
    ensemble_policy: Optional[EnsembleSupportPolicy] = None,
) -> EnsembleSupportBackend:
    """Create a model-backed backend stack intended for CLI and real runs."""

    return build_default_support_backend(
        reranker_model_name=reranker_model_name,
        nli_model_name=nli_model_name,
        heuristic_threshold=heuristic_threshold,
        reranker_threshold=reranker_threshold,
        nli_threshold=nli_threshold,
        nli_margin=nli_margin,
        ensemble_policy=ensemble_policy or DEFAULT_PRODUCTION_ENSEMBLE_POLICY,
    )


def split_evidence_text(text: str) -> List[str]:
    """Break long evidence into rerankable candidate spans."""

    cleaned = " ".join(text.split())
    if not cleaned:
        return []
    pieces = re.split(r"(?<=[.!?])\s+", cleaned)
    candidates = [piece.strip() for piece in pieces if piece.strip()]
    if cleaned not in candidates:
        candidates.append(cleaned)
    return candidates


def _softmax(values: List[float]) -> List[float]:
    offset = max(values)
    exp_values = [math.exp(value - offset) for value in values]
    total = sum(exp_values) or 1.0
    return [value / total for value in exp_values]


def combine_support_assessments(
    assessments: Iterable[SupportAssessment],
    policy: Optional[EnsembleSupportPolicy] = None,
) -> SupportAssessment:
    """Fuse precomputed component assessments into the production ensemble decision."""

    rows = list(assessments)
    if not rows:
        return SupportAssessment(
            backend_name=EnsembleSupportBackend.backend_name,
            score=0.0,
            passed=False,
            rationale="No support backend is available.",
        )

    active_policy = policy or EnsembleSupportPolicy()
    weights = active_policy.normalized_weights()
    total_weight = 0.0
    weighted_score = 0.0
    for assessment in rows:
        weight = weights.get(assessment.backend_name, 0.0)
        weighted_score += assessment.score * weight
        total_weight += weight
    combined_score = weighted_score / total_weight if total_weight else 0.0

    strongest = max(rows, key=lambda assessment: assessment.score)
    nli = next(
        (assessment for assessment in rows if assessment.backend_name == "transformers_nli"),
        None,
    )
    reranker = next(
        (assessment for assessment in rows if assessment.backend_name == "sentence_transformer_reranker"),
        None,
    )
    heuristic = next(
        (assessment for assessment in rows if assessment.backend_name == "heuristic_support"),
        None,
    )

    decision_path = "strongest_component"
    passed = strongest.passed
    contradiction_score = 0.0
    if nli is not None:
        contradiction_score = float(
            nli.details.get("probabilities", {}).get("contradiction", 0.0)
        )
        if nli.passed:
            passed = True
            decision_path = "nli_pass"
        elif reranker is not None:
            paired_support = reranker.passed and (
                (nli.score >= active_policy.pair_nli_floor and combined_score >= active_policy.pair_combined_threshold)
                or (
                    heuristic is not None
                    and heuristic.passed
                    and contradiction_score <= active_policy.contradiction_max
                    and combined_score >= active_policy.pair_combined_threshold
                )
            )
            passed = paired_support
            decision_path = "paired_reranker_nli" if paired_support else "paired_reranker_nli_reject"
    elif combined_score >= active_policy.fallback_combined_threshold:
        passed = True
        decision_path = "combined_fallback"
    else:
        decision_path = "combined_fallback_reject"

    return SupportAssessment(
        backend_name=EnsembleSupportBackend.backend_name,
        score=combined_score,
        passed=passed,
        rationale=(
            "Ensemble support scoring found evidence strong enough for citation."
            if passed
            else "Ensemble support scoring still considers the evidence too weak."
        ),
        details={
            "decision_path": decision_path,
            "weights": {name: round(value, 4) for name, value in weights.items()},
            "policy": {
                "pair_nli_floor": active_policy.pair_nli_floor,
                "pair_combined_threshold": active_policy.pair_combined_threshold,
                "contradiction_max": active_policy.contradiction_max,
                "fallback_combined_threshold": active_policy.fallback_combined_threshold,
            },
            "components": [
                {
                    "backend": assessment.backend_name,
                    "score": round(assessment.score, 4),
                    "passed": assessment.passed,
                    "details": assessment.details,
                }
                for assessment in rows
            ],
        },
    )


def _normalize_weights(weights: Mapping[str, float]) -> Dict[str, float]:
    cleaned = {
        name: max(float(value), 0.0)
        for name, value in weights.items()
        if value is not None
    }
    total = sum(cleaned.values()) or 1.0
    return {name: value / total for name, value in cleaned.items()}
