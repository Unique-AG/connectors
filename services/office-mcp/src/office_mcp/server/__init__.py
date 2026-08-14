"""MCP server concerns: how the features are exposed, not what they do.

Tool declarations (`tools`), FastMCP/ASGI middleware (`middleware`), and the process-wide
service holder (`runtime`) that exists only because FastMCP calls tool functions with a plain
signature and so denies them constructor injection. None of those exist yet — the one thing
this package exposes today is `readiness`, the `/ready` route body, which is an
exposure concern in exactly the same sense: an HTTP endpoint over what the service can reach.

This side may import freely from `features/`. The reverse is a layering violation — see
`features/__init__.py`. This package is entered through this `__init__`, never through its
modules; `tests/test_layering.py` enforces that too.
"""

from office_mcp.server.readiness import ready_response

__all__ = ["ready_response"]
