from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations
from pydantic import Field

from polixis_mcp import contexts
from polixis_mcp.mcp.dependencies import get_upstream
from polixis_mcp.mcp.inputs.cursor import Cursor
from polixis_mcp.mcp.inputs.cursor import page_query
from polixis_mcp.mcp.inputs.pid import EntityPid
from polixis_mcp.upstream import Upstream


@tool(
    title="Get Court Decision",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("pid", "decision_id")
async def get_court_decision(
    *,
    pid: EntityPid = None,
    decision_id: Annotated[
        str | None,
        Field(
            min_length=1,
            description="The decision's id, from `find_court_decisions` on the same pid. "
            "Required unless `cursor` is.",
        ),
    ] = None,
    cursor: Cursor = None,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.CourtDecisionText:
    """The full text of one court decision, in its own language, one part of about 8,000
    tokens at a time. A decision runs to about 60,000 characters at most.

    Read it only when the snippets of `find_court_decisions` do not settle the question. When
    `next_cursor` is set, pass it back as `cursor` for the next part.
    Polixis does not document this route yet, so its answers may change without notice.
    """
    query = page_query(
        contexts.CourtDecisionTextQuery,
        cursor,
        pid=pid,
        decision_id=decision_id,
    )
    try:
        return await contexts.get_court_decision(upstream=upstream, query=query)
    except contexts.CourtDecisionNotFoundError as error:
        raise ToolError(str(error)) from error
