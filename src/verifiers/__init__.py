"""Verification modules."""

from .contradiction_verifier import ContradictionVerifier
from .existence_verifier import ExistenceVerifier
from .metadata_verifier import MetadataVerifier
from .risk_fusion import RiskFusion, RiskProfile
from .support_backends import (
    DEFAULT_NLI_MODEL,
    DEFAULT_PRODUCTION_ENSEMBLE_POLICY,
    DEFAULT_RERANKER_MODEL,
    EnsembleSupportPolicy,
    EnsembleSupportBackend,
    HeuristicSupportBackend,
    SentenceTransformerRerankerBackend,
    SupportAssessment,
    SupportBackend,
    TransformersNLIBackend,
    build_default_support_backend,
    build_production_support_backend,
    combine_support_assessments,
)
from .support_verifier import SupportVerifier
from .uncertainty_gate import GateDecision, UncertaintyGate

__all__ = [
    "ContradictionVerifier",
    "DEFAULT_NLI_MODEL",
    "DEFAULT_PRODUCTION_ENSEMBLE_POLICY",
    "DEFAULT_RERANKER_MODEL",
    "EnsembleSupportBackend",
    "EnsembleSupportPolicy",
    "ExistenceVerifier",
    "GateDecision",
    "HeuristicSupportBackend",
    "MetadataVerifier",
    "RiskFusion",
    "RiskProfile",
    "SentenceTransformerRerankerBackend",
    "SupportAssessment",
    "SupportBackend",
    "SupportVerifier",
    "TransformersNLIBackend",
    "UncertaintyGate",
    "build_default_support_backend",
    "build_production_support_backend",
    "combine_support_assessments",
]
