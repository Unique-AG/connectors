"""Exposure that is not a tool: `/ready`, and nothing else.

This package used to be described as the place tool declarations would land, over a `features/`
package holding what the tools did. Neither happened, and neither will: a tool is a file under
`tools/` that owns its name, its description, its Graph permissions, its arguments, its answer
shape, its request and its own refusals, so there is nothing for a declaration module to declare —
and no process-wide service holder either, because `create_app` hands each tool the transport it
borrows. `features/` is gone with them. What remains is an exposure concern in exactly the sense a
tool declaration would have been: `readiness` is the `/ready` route body, an HTTP endpoint over
what the service can reach. The refusal wording that would have lived here is `shared/seam.py`,
because a tool file needs it as much as this file would and a model reads every refusal on this
server as one voice.

This side may import freely from `shared/`. What it must not do is talk to Microsoft Graph itself:
the Graph SDK belongs to `graph_client/` and the requests belong to each tool's own file.
"""

from office_mcp.server.readiness import ready_response

__all__ = ["ready_response"]
