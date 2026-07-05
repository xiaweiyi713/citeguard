"""Backward-compatible MCP server shim.

The stable public implementation lives in :mod:`citeguard.mcp.server`.
"""

from citeguard.mcp.server import *  # noqa: F401,F403


if __name__ == "__main__":
    main()
