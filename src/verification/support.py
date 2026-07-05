"""Backward-compatible claim-support shim.

The stable public implementation lives in :mod:`citeguard.verification.support`.
"""

from citeguard.verification.support import *  # noqa: F401,F403
from citeguard.verification.support import _extract_nli  # noqa: F401
