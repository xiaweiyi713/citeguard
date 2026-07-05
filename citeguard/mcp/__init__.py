"""Public MCP server package."""

__all__ = ["main"]


def __getattr__(name):
    if name == "main":
        from .server import main

        return main
    raise AttributeError(name)
