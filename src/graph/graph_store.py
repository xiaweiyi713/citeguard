"""Storage adapter for CCEG graphs."""

from __future__ import annotations

from copy import deepcopy

from .cceg import CCEG


class InMemoryGraphStore:
    """Simple graph store used by the initial prototype and tests."""

    def __init__(self) -> None:
        self._graph = CCEG()

    @property
    def graph(self) -> CCEG:
        return self._graph

    def reset(self) -> None:
        self._graph = CCEG()

    def snapshot(self) -> CCEG:
        return deepcopy(self._graph)
