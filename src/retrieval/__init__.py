"""Backward-compatible retrieval package shim.

The stable public implementation lives in :mod:`citeguard.retrieval`.
"""

from citeguard.retrieval import *  # noqa: F401,F403
from citeguard.retrieval import __all__  # noqa: F401
