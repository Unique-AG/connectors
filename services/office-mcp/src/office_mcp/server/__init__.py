"""MCP server concerns: how the features are exposed, not what they do.

Three things, all entered here. `tools` declares the MCP tools over the features and states the
Graph permissions sign-in must ask for; `errors` turns a Graph failure into advice a language
model can act on, which every tool shares; `readiness` is the `/ready` route body, an exposure
concern in exactly the same sense — an HTTP endpoint over what the service can reach.

This side may import freely from `features/`. The reverse is a layering violation — see
`features/__init__.py`. What this side must not do is talk to Microsoft Graph itself: the Graph
SDK belongs to `graph_client/` and the requests belong to `features/`. This package is entered
through this `__init__`, never through its modules; `tests/test_layering.py` enforces all of that.
"""

from office_mcp.server.readiness import ready_response
from office_mcp.server.tools import GRAPH_SCOPES, register_tools

__all__ = ["GRAPH_SCOPES", "ready_response", "register_tools"]
