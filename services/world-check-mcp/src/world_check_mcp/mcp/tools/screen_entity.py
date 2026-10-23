from datetime import date
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

Name = Annotated[str, Field(min_length=1, max_length=1000, description="Name to screen.")]
Country = Annotated[str, Field(pattern=r"^[A-Za-z]{3}$", description="ISO alpha-3 country code.")]
ExternalId = Annotated[
    str, Field(min_length=1, description="Stable external caseId. An existing id is refused.")
]
PageSize = Annotated[int, Field(ge=1, le=100, description="Matches to return.")]


@tool(
    title="Screen Entity",
    annotations=ToolAnnotations(
        read_only_hint=False, idempotent_hint=False, destructive_hint=False, open_world_hint=True
    ),
)
async def screen_entity(
    name: Name,
    entity_type: Annotated[contexts.EntityType, Field(description="INDIVIDUAL or ORGANISATION.")],
    group_id: GroupId,
    case_id: Annotated[
        ExternalId | None, Field(description="External caseId. Existing ids are refused.")
    ] = None,
    dob: Annotated[date | None, Field(description="Date of birth. Individuals only.")] = None,
    nationality: Annotated[
        Country | None, Field(description="Individual nationality, ISO alpha-3.")
    ] = None,
    country_of_residence: Annotated[
        Country | None, Field(description="Individual country of residence, ISO alpha-3.")
    ] = None,
    place_of_birth: Annotated[
        Country | None, Field(description="Individual place of birth, ISO alpha-3.")
    ] = None,
    registered_country: Annotated[
        Country | None, Field(description="Organization registered country, ISO alpha-3.")
    ] = None,
    gender: Annotated[
        contexts.Gender | None, Field(description="MALE, FEMALE, or UNSPECIFIED.")
    ] = None,
    secondary_fields: Annotated[
        list[contexts.FieldValue] | None,
        Field(description="Extra secondary fields by typeId from get_group_settings."),
    ] = None,
    custom_fields: Annotated[
        list[contexts.FieldValue] | None,
        Field(description="Custom fields by typeId from the group template."),
    ] = None,
    limit: PageSize = 20,
    upstream: Upstream = Depends(get_upstream),
) -> contexts.ScreeningOutcome:
    """Create a persistent WATCHLIST case and screen it synchronously.

    This writes a case. Repeated calls without case_id create new cases. An existing case_id is
    refused, not rescreened. Matches are candidates, not confirmed identities.
    """
    try:
        return await contexts.screen_entity(
            upstream=upstream,
            name=name,
            entity_type=entity_type,
            group_id=group_id,
            case_id=case_id,
            dob=dob,
            nationality=nationality,
            country_of_residence=country_of_residence,
            place_of_birth=place_of_birth,
            registered_country=registered_country,
            gender=gender,
            secondary_fields=secondary_fields,
            custom_fields=custom_fields,
            limit=limit,
        )
    except contexts.ScreeningError as error:
        raise ToolError(str(error)) from error
