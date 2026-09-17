"""`update_organization`: PATCH one organization and optionally edit postal addresses."""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import InputRequiredResult, ToolAnnotations
from pydantic import Field

from backstop_mcp.features.org_people_writes import (
    UPDATE_ORGANIZATION_INPUT_DESCRIPTION,
    UpdateOrganizationCommand,
    UpdateOrganizationInput,
    UpdateOrganizationResponse,
    get_update_organization_command_factory,
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
    output_schema=published_output_schema(UpdateOrganizationResponse),
)
async def update_organization(
    ctx: Context,
    organization: Annotated[
        UpdateOrganizationInput, Field(description=UPDATE_ORGANIZATION_INPUT_DESCRIPTION)
    ],
    resolve_party_query: ResolvePartyQuery = Depends(get_resolve_party_query_factory),
    update_organization_command: UpdateOrganizationCommand = Depends(
        get_update_organization_command_factory
    ),
) -> UpdateOrganizationResponse | InputRequiredResult:
    """Patch one CRM organization and, optionally, its postal addresses.

    `search_type` plus exactly one of `party_id` or `search` — same identity as
    `get_organization`. `name` cannot be cleared and is at most 50 characters. Custom
    fields go through `update_custom_field_values`. Email corrections go through `email` /
    `email2` / `email3`; `contact-emails` has no write endpoint. Category ids come from
    `list_contact_categories`. Location ids come from
    `get_organization` with `include=contactLocations`, not `include=locations`.
    `locations` creates or patches each address; `delete_location_ids` removes them.
    Creating an address is folded into this tool: `destructive_hint` is already true, which
    over-warns rather than under-warns. The response `organization` is the record READ
    BACK — same top-level fields as `get_organization`. Omit a field to leave it
    unchanged. Never invent an id.

    Call like: {"organization": {"search_type": "organizations",
    "party_id": "<id from get_organization>", "website": "https://example.com"}}
    """
    result = await resolve_party_query.run(
        search_type=organization.search_type,
        party_id=organization.party_id,
        search=organization.search,
    )
    result = await elicit_if_ambiguous(ctx, result)
    if input_required(result):
        return result
    if not isinstance(result, Resolved):
        return unresolved_party_response(result)
    party = result.value
    logger.info(
        "org_people_writes.update_organization.start",
        extra={"search_type": party.search_type, "party_id": party.id},
    )
    return await update_organization_command.run(
        new_organization_fields=organization, party_id=party.id
    )
