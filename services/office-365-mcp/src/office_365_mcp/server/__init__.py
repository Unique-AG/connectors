"""Exposure that is not a tool: `/ready` and the resolved tool surface.

Layering: `tools/` must not import this package. That rule keeps a tool file's wiring inside the
tool file. This side can import freely from `shared/`, where the refusal wording lives in
`shared/seam.py` and a tool file can reach it too. This side must not talk to Microsoft Graph
itself: the SDK belongs to `graph_client/`, and the requests belong to each tool's own file.
"""

from office_365_mcp.server.manifest import surface_manifest
from office_365_mcp.server.readiness import ready_response

__all__ = ["ready_response", "surface_manifest"]
