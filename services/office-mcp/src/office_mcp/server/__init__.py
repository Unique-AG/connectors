"""Exposure that is not a tool: `/ready` and the resolved tool surface.

Layering: `tools/` may not import this package, which is what keeps a tool file's wiring inside the
tool file. This side may import freely from `shared/` — the refusal wording is in `shared/seam.py`,
where a tool file can reach it too — but must not talk to Microsoft Graph itself: the SDK belongs to
`graph_client/` and the requests to each tool's own file.
"""

from office_mcp.server.manifest import surface_manifest
from office_mcp.server.readiness import ready_response

__all__ = ["ready_response", "surface_manifest"]
