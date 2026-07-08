"""Backward-compatible MCP server shim.

The stable public implementation lives in :mod:`citeguard.mcp.server`.
"""

import sys

from citeguard.mcp import server as _public_server
from citeguard.mcp.server import *  # noqa: F401,F403

sys.modules[__name__] = _public_server


if __name__ == "__main__":
    _public_server.main()
