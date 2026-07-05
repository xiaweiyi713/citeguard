"""Legacy CiteGuard compatibility package.

New code should import from :mod:`citeguard` instead. This package remains as a
temporary bridge for older notebooks, scripts, and agents that imported the
early prototype namespace.
"""

from __future__ import annotations

import warnings

from citeguard.version import __version__


warnings.warn(
    "The `src` compatibility package is deprecated; import from `citeguard` "
    "or its public subpackages instead.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ["__version__"]
