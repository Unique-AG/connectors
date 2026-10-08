from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from with_intelligence_mcp.features.managers.dependencies import get_manager_query_factory
from with_intelligence_mcp.features.managers.queries import GetManagerQuery
from with_intelligence_mcp.features.managers.responses import (
    ManagerAmbiguousResponse,
    ManagerNotEntitledResponse,
    ManagerNotFoundResponse,
    ManagerProfileResponse,
)
from with_intelligence_mcp.models import published_output_schema

type GetManagerResult = (
    ManagerProfileResponse
    | ManagerAmbiguousResponse
    | ManagerNotEntitledResponse
    | ManagerNotFoundResponse
)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(GetManagerResult),
)
async def get_manager(
    name: Annotated[
        str | None,
        Field(
            description=(
                "Manager name. Matching is partial, so a short name returns candidates to "
                "choose between. Omit when passing manager_id."
            )
        ),
    ] = None,
    manager_id: Annotated[
        int | None,
        Field(description="With Intelligence manager id, when it is already known."),
    ] = None,
    get_manager_query: GetManagerQuery = Depends(get_manager_query_factory),
) -> GetManagerResult:
    """Profile one management company: location, AUM, the strategies it runs, and its service
    providers.

    Pass a name and it is resolved first; several matches come back as candidates to choose
    between. Every AUM figure is in MILLIONS. `is_estimate` marks a figure With Intelligence
    did not take from a filing.
    """
    return await get_manager_query.run(name=name, manager_id=manager_id)
