"""Benchmarking utilities."""

from .baselines import DirectWriteBaseline, RAGWriteBaseline
from .dataset_builder import BenchmarkExample, CiteGuardBenchBuilder
from .metrics import EvaluationRecord, MetricsCalculator
from .support_calibration import (
    ScoredSupportExample,
    SupportCalibrationConfig,
    SupportCalibrationExample,
    SupportCalibrationMetrics,
    default_support_calibration_examples,
    evaluate_support_config,
    grid_search_support_configs,
    score_support_examples,
)

__all__ = [
    "BenchmarkExample",
    "CiteGuardBenchBuilder",
    "DirectWriteBaseline",
    "EvaluationRecord",
    "MetricsCalculator",
    "RAGWriteBaseline",
    "ScoredSupportExample",
    "SupportCalibrationConfig",
    "SupportCalibrationExample",
    "SupportCalibrationMetrics",
    "default_support_calibration_examples",
    "evaluate_support_config",
    "grid_search_support_configs",
    "score_support_examples",
]
