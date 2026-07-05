"""Backward-compatible CLI shim.

The stable public implementation lives in :mod:`citeguard.cli`.
"""

from citeguard.cli import *  # noqa: F401,F403


if __name__ == "__main__":
    main()
