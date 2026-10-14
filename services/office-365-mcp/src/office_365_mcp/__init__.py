"""Office 365 MCP: FastMCP server over Microsoft 365 via Microsoft Graph."""

import importlib.util
import sys

for _name in ("unique_mcp", "unique_toolkit", "unique_toolkit.app"):
    _spec = importlib.util.find_spec(_name)
    if _spec is not None and _name not in sys.modules:
        sys.modules[_name] = importlib.util.module_from_spec(_spec)

from unique_mcp import _bootstrap as _bootstrap  # noqa: E402
