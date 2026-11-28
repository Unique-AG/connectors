from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp_observability import trace_arguments
from mcp_types import ToolAnnotations
from pydantic import Field

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_cache
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import GroupId
from world_check_mcp.persistence import Cache
from world_check_mcp.upstream import Upstream


@tool(
    title="Get Group Settings",
    description=(
        "Get one group's case template and resolution toolkit.\n"
        "\n"
        "Secondary field type ids and resolution ids are group-specific. Read them before "
        "screening or resolving a match. Ask for section fields before screening and toolkits "
        "before resolving, and narrow the fields with entity_type or required_only. A part you "
        "did not ask for is null, not empty."
    ),
    annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=True),
)
@trace_arguments("group_id", "section", "entity_type", "required_only")
async def get_group_settings(
    group_id: GroupId,
    section: Annotated[
        contexts.SettingsSection,
        Field(description="fields for the case template, toolkits for resolutions, or all."),
    ] = "all",
    entity_type: Annotated[
        contexts.EntityType | None,
        Field(description="Only the fields of INDIVIDUAL or ORGANISATION cases."),
    ] = None,
    *,
    required_only: Annotated[bool, Field(description="Only the fields a case must carry.")] = False,
    upstream: Upstream = Depends(get_upstream),
    cache: Cache = Depends(get_cache),
) -> contexts.GroupSettings:
    return await contexts.get_group_settings(
        upstream=upstream,
        cache=cache,
        group_id=group_id,
        section=section,
        entity_type=entity_type,
        required_only=required_only,
    )
