"""Exposure that is not a tool: `/ready`, the resolved tool surface, and nothing else.

This package used to be described as the place tool declarations would land, over a `features/`
package holding what the tools did. Neither happened, and neither will: a tool is a file under
`tools/` that owns its name, its description, its Graph permissions, its arguments, its answer
shape, its request and its own refusals, so there is nothing for a declaration module to declare —
and no process-wide service holder either, because `create_app` hands each tool the transport it
borrows. `features/` is gone with them. What remains are exposure concerns in exactly the sense a
tool declaration would have been: `readiness` is the `/ready` route body, an HTTP endpoint over
what the service can reach, and `manifest` is what an operator is told this deployment resolved to
— which tools registered, which delegated permissions sign-in therefore asks every user for, and
which of those need an administrator. The refusal wording that would have lived here is
`shared/seam.py`, because a tool file needs it as much as these files would and a model reads every
refusal on this server as one voice.

Both read the tool surface and neither is read by it: `tools/` may not import this package, which is
what keeps a tool file's wiring inside the tool file.

This side may import freely from `shared/`. What it must not do is talk to Microsoft Graph itself:
the Graph SDK belongs to `graph_client/` and the requests belong to each tool's own file.
"""

from office_mcp.server.manifest import surface_manifest
from office_mcp.server.readiness import ready_response

__all__ = ["ready_response", "surface_manifest"]
