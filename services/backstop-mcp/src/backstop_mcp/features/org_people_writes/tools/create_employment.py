"""`create_employment`: POST one person↔organization employment."""

from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import InputRequiredResult, ToolAnnotations
from mcp_observability import trace_arguments
from pydantic import Field

from backstop_mcp.features.org_people_writes import (
    CREATE_EMPLOYMENT_INPUT_DESCRIPTION,
    CreateEmploymentCommand,
    CreateEmploymentInput,
    CreateEmploymentResponse,
    get_create_employment_command_factory,
)
from backstop_mcp.features.party_resolver import (
    ResolvePartyQuery,
    get_resolve_party_query_factory,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import Resolved, elicit_if_ambiguous, input_required
from backstop_mcp.models import published_output_schema


@tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(CreateEmploymentResponse),
)
@trace_arguments(
    "employment.search_type",
    "employment.party_id",
    "employment.organization_id",
    "employment.start_date",
    identifying=("employment.search", "employment.organization_search"),
)
async def create_employment(
    ctx: Context,
    employment: Annotated[
        CreateEmploymentInput, Field(description=CREATE_EMPLOYMENT_INPUT_DESCRIPTION)
    ],
    resolve_party_query: ResolvePartyQuery = Depends(get_resolve_party_query_factory),
    create_employment_command: CreateEmploymentCommand = Depends(
        get_create_employment_command_factory
    ),
) -> CreateEmploymentResponse | InputRequiredResult:
    """Create one CRM employment between a person and an organization.

    Person identity is the same as `get_person`. Organization identity is exactly one of
    `organization_id` or `organization_search`. Do not pass a relationship-type id — the
    command resolves it from the catalog. One POST also creates the reverse mirror row
    (person→org and org→person). A repeated call creates a second pair of records.
    `is_key_employee` is rejected; set Key employee in the CRM UI.

    Call like: {"employment": {"search_type": "people", "party_id": "<id from get_person>",
    "organization_id": "<id from get_organization>", "start_date": "2026-01-15"}}
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
    return await create_employment_command.run(
        person_id=person.id,
        person_search_type=person.search_type,
        organization_id=organization.id,
        start_date=employment.start_date,
    )
