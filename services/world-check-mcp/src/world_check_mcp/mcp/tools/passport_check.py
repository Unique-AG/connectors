from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp_types import ToolAnnotations
from pydantic import Field

from world_check_mcp import contexts
from world_check_mcp.mcp.dependencies import get_upstream
from world_check_mcp.mcp.inputs.identifiers import GroupId
from world_check_mcp.upstream import Upstream

ExternalId = Annotated[
    str, Field(min_length=1, description="Stable external caseId. An existing id is refused.")
]
PageSize = Annotated[int, Field(ge=1, le=100, description="WATCHLIST matches to return.")]


@tool(
    title="Passport Check",
    annotations=ToolAnnotations(
        read_only_hint=False, idempotent_hint=False, destructive_hint=False, open_world_hint=True
    ),
)
async def passport_check(
    passport: Annotated[contexts.Passport, Field(description="Document details as printed.")],
    group_id: GroupId,
    case_id: Annotated[
        ExternalId | None, Field(description="External caseId. Existing ids are refused.")
    ] = None,
    name: Annotated[
        str | None, Field(description="Case name. Defaults to the given and last names.")
    ] = None,
    include_watchlist: Annotated[
        bool,
        Field(description="Also screen the name against WATCHLIST."),
    ] = True,
    secondary_fields: Annotated[
        list[contexts.FieldValue] | None,
        Field(description="Extra secondary fields. Passport fields do not fill WATCHLIST fields."),
    ] = None,
    custom_fields: Annotated[
        list[contexts.FieldValue] | None,
        Field(description="Custom fields from the group template."),
    ] = None,
    limit: PageSize = 20,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.PassportCheck:
    """Create a Passport Check case and screen it synchronously, returning its MRZ.

    This writes a case. It does not record a human document comparison. limit truncates
    WATCHLIST matches only.
    """
    try:
        return await contexts.passport_check(
            upstream=upstream,
            passport=passport,
            group_id=group_id,
            case_id=case_id,
            name=name,
            include_watchlist=include_watchlist,
            secondary_fields=secondary_fields,
            custom_fields=custom_fields,
            limit=limit,
        )
    except contexts.PassportError as error:
        raise ToolError(str(error)) from error
    except contexts.ScreeningError as error:
        raise ToolError(str(error)) from error
