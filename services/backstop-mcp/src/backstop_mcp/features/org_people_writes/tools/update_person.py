"""`update_person`: PATCH one person and optionally edit a location."""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.party_resolver import (
    ResolvePartyQuery,
    get_resolve_party_query_factory,
    unresolved_party_response,
)
from backstop_mcp.features.org_people_writes import (
    UPDATE_PERSON_INPUT_DESCRIPTION,
    UpdatePersonCommand,
    UpdatePersonInput,
    UpdatePersonResponse,
    get_update_person_command_factory,
)
from backstop_mcp.features.resolution import Resolved, elicit_if_ambiguous
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(UpdatePersonResponse),
)
async def update_person(
    ctx: Context,
    person: Annotated[UpdatePersonInput, Field(description=UPDATE_PERSON_INPUT_DESCRIPTION)],
    resolve_party_query: ResolvePartyQuery = Depends(get_resolve_party_query_factory),
    update_person_command: UpdatePersonCommand = Depends(get_update_person_command_factory),
) -> UpdatePersonResponse:
    """Patch one CRM person and, optionally, one of their postal addresses.

    `search_type` plus exactly one of `party_id` or `search` — same identity as `get_person`.
    `last_name` cannot be cleared. `job_title` is at most 140 characters. Custom fields go
    through `update_custom_field_values`. Email corrections go through `email` / `email2` /
    `email3`; `contact-emails` has no write endpoint. Location ids come from `get_person`
    with `include=contactLocations`, not `include=locations`. Creating an address is folded
    into this tool: `destructive_hint` is already true, which over-warns rather than
    under-warns. Omit a field to leave it unchanged. Never invent an id.

    Call like: {"person": {"search_type": "people", "party_id": "<id from get_person>",
    "job_title": "Managing Director"}}
    """
    result = await resolve_party_query.run(
        search_type=person.search_type,
        party_id=person.party_id,
        search=person.search,
    )
    result = await elicit_if_ambiguous(ctx, result)
    if not isinstance(result, Resolved):
        return unresolved_party_response(result)
    party = result.value
    logger.info(
        "org_people_writes.update_person.start",
        extra={"search_type": party.search_type, "party_id": party.id},
    )
    return await update_person_command.run(person=person, party_id=party.id)
