from datetime import datetime
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.upstream import Upstream

When = Annotated[
    datetime | None, Field(description="Timezone-aware timestamp. Reuse it when paging.")
]
PageSize = Annotated[int, Field(ge=1, le=1000, description="Updates per page.")]
PageReference = Annotated[str | None, Field(description="next_page from the previous page.")]


@tool(
    title="Get Ongoing Screening Updates",
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
async def get_ogs_updates(
    since: When = None,
    until: When = None,
    group_id: Annotated[str | None, Field(description="Limit updates to this group.")] = None,
    case: Annotated[
        str | None,
        Field(description="Internal caseSystemId or exact external caseId."),
    ] = None,
    limit: PageSize = 100,
    page_reference: PageReference = None,
    mode: Annotated[
        contexts.UpdateMode,
        Field(description="FULL returns match detail. SUMMARY returns counts."),
    ] = "FULL",
    upstream: Upstream = Depends(get_upstream),
) -> contexts.OgsPage:
    """Poll WATCHLIST monitoring updates. Defaults to the last 24 hours. LSEG keeps 30 days.

    No updates returns an empty list. Reuse window.since, window.until, and the other criteria
    with next_page. This does not acknowledge updates.
    """
    try:
        return await contexts.get_ogs_updates(
            upstream=upstream,
            since=since,
            until=until,
            group_id=group_id,
            case=case,
            limit=limit,
            page_reference=page_reference,
            mode=mode,
        )
    except contexts.CaseNotFoundError as error:
        raise ToolError(str(error)) from error
    except contexts.MonitoringError as error:
        raise ToolError(str(error)) from error
