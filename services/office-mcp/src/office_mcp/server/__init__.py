"""Exposure that is not a tool: `/ready`, the resolved tool surface, and nothing else.

No tool declarations land here, and no `features/` package holds what the tools do. A tool is a file
under `tools/` that owns its name, its description, its Graph permissions, its arguments, its answer
shape, its request and its own refusals, so a declaration module would have nothing to declare, and
`create_app` hands each tool the transport it borrows, so there is no process-wide service holder
either.

What remains are exposure concerns. `readiness` is the `/ready` route body, an HTTP endpoint over
what the service can reach. `manifest` is what an operator is told this deployment resolved to:
which tools registered, which delegated permissions sign-in therefore asks every user for, and which
of those need an administrator. The refusal wording that would have lived here is in
`shared/seam.py`, because a tool file needs it as much as these files would and a model reads every
refusal on this server as one voice.

Both read the tool surface and neither is read by it: `tools/` may not import this package, which is
what keeps a tool file's wiring inside the tool file. This side may import freely from `shared/`.
What it must not do is talk to Microsoft Graph itself: the Graph SDK belongs to `graph_client/` and
the requests belong to each tool's own file.
"""

from office_mcp.server.manifest import surface_manifest
from office_mcp.server.readiness import ready_response

__all__ = ["ready_response", "surface_manifest"]
