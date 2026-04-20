"""Policy knobs for orchestration and safety decisions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RiskPolicy:
    """Configurable thresholds for the uncertainty gate."""

    cite_threshold: float = 0.35
    rewrite_threshold: float = 0.55
