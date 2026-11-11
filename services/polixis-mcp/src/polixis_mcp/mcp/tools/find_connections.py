from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations
from pydantic import Field

from polixis_mcp import contexts
from polixis_mcp.mcp.dependencies import get_persistence
from polixis_mcp.mcp.dependencies import get_upstream
from polixis_mcp.mcp.inputs.pid import PID_PATTERN
from polixis_mcp.persistence import Persistence
from polixis_mcp.upstream import Upstream


@tool(
    title="Find Connections",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("from_pid", "to_pid")
async def find_connections(
    *,
    from_pid: Annotated[
        str, Field(pattern=PID_PATTERN, description="The pid to start from, such as the client.")
    ],
    to_pid: Annotated[
        str,
        Field(pattern=PID_PATTERN, description="The pid to look for, such as a sanctioned party."),
    ],
    upstream: Upstream = Depends(get_upstream),
    persistence: Persistence = Depends(get_persistence),
) -> contexts.Connections:
    """How two organizations or people are connected: the shortest path Polixis finds between
    them across its whole graph, with no hop limit, and the role, share and dates of each link
    along it, and the flags of every party on it. Polixis finds the path; this MCP puts its
    links in order from the first entity to the second.

    Polixis does not document this route yet, so its answers may change without notice.
    """
    return await contexts.find_connections(
        upstream=upstream, persistence=persistence, from_pid=from_pid, to_pid=to_pid
    )
