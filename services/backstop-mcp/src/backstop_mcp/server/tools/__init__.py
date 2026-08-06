"""The MCP tools this server exposes.

`registry.py` is the one list; this is how the rest of the process reads it. Individual tool
modules are not part of the surface — a tool is reached by being registered, never by import.
"""

from backstop_mcp.server.tools.registry import TOOLS

__all__ = ["TOOLS"]
