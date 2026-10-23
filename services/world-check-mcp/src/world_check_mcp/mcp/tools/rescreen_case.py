from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import CaseArgument
from world_check_mcp.upstream import Upstream

PageSize = Annotated[int, Field(ge=1, le=100, description="Matches to return.")]


@tool(
    title="Rescreen Case",
    annotations=ToolAnnotations(
        read_only_hint=False, idempotent_hint=True, destructive_hint=False, open_world_hint=True
    ),
)
async def rescreen_case(
    case: CaseArgument,
    delta: Annotated[
        bool,
        Field(description="True screens changes since the last run. False screens fully."),
    ] = False,
    limit: PageSize = 20,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.ScreeningOutcome:
    """Rescreen a case by internal caseSystemId or external caseId without editing its fields.

    WATCHLIST and Passport Check only. Media Check is unsupported.
    """
    try:
        return await contexts.rescreen_case(upstream=upstream, case=case, delta=delta, limit=limit)
    except contexts.CaseNotFoundError as error:
        raise ToolError(str(error)) from error
    except contexts.ScreeningError as error:
        raise ToolError(str(error)) from error
