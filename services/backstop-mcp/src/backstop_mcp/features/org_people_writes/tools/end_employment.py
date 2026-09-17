"""`end_employment`: write `endDate` on the person↔organization employment row."""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import InputRequiredResult, ToolAnnotations
from pydantic import Field

from backstop_mcp.features.org_people_writes import (
    END_EMPLOYMENT_INPUT_DESCRIPTION,
    EndEmploymentCommand,
    EndEmploymentInput,
    EndEmploymentResponse,
    get_end_employment_command_factory,
)
from backstop_mcp.features.party_resolver import (
    ResolvePartyQuery,
    get_resolve_party_query_factory,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import Resolved, elicit_if_ambiguous, input_required
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(EndEmploymentResponse),
)
async def end_employment(
    ctx: Context,
    employment: Annotated[EndEmploymentInput, Field(description=END_EMPLOYMENT_INPUT_DESCRIPTION)],
    resolve_party_query: ResolvePartyQuery = Depends(get_resolve_party_query_factory),
    end_employment_command: EndEmploymentCommand = Depends(get_end_employment_command_factory),
) -> EndEmploymentResponse | InputRequiredResult:
    """End one CRM employment by writing `endDate` on the relationship.

    Person identity is the same as `get_person`. Organization identity is exactly one of
    `organization_id` or `organization_search`. There is no relationship-id parameter.
    One PATCH is enough — end-dating either direction propagates to the reverse. Never
    send `entityRelationshipType`; it cannot be modified. An `end_date` that is not
    strictly before today is stored, but the person still reads as a current contact
    until that date has passed.

    Call like: {"employment": {"search_type": "people", "party_id": "<id from get_person>",
    "organization_id": "<id from get_organization>", "end_date": "2026-01-15"}}
    """
    person_result = await resolve_party_query.run(
        search_type=employment.search_type,
        party_id=employment.party_id,
        search=employment.search,
    )
    person_result = await elicit_if_ambiguous(ctx, person_result)
    if input_required(person_result):
        return person_result
    if not isinstance(person_result, Resolved):
        return unresolved_party_response(person_result)
    organization_result = await resolve_party_query.run(
        search_type="organizations",
        party_id=employment.organization_id,
        search=employment.organization_search,
    )
    organization_result = await elicit_if_ambiguous(ctx, organization_result)
    if input_required(organization_result):
        return organization_result
    if not isinstance(organization_result, Resolved):
        return unresolved_party_response(organization_result)
    person = person_result.value
    organization = organization_result.value
    logger.info(
        "org_people_writes.end_employment.start",
        extra={
            "person_id": person.id,
            "person_search_type": person.search_type,
            "organization_id": organization.id,
        },
    )
    return await end_employment_command.run(
        person_id=person.id,
        person_search_type=person.search_type,
        organization_id=organization.id,
        end_date=employment.end_date,
    )
