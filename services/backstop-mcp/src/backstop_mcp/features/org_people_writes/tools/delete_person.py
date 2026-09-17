"""`delete_person`: hard-delete one person after removing contact-locations."""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import InputRequiredResult, ToolAnnotations
from pydantic import Field

from backstop_mcp.features.elicitation_utils import elicit_entity_deletion
from backstop_mcp.features.org_people_writes import (
    DELETE_PERSON_INPUT_DESCRIPTION,
    DeletedPersonResponse,
    DeletePartyWithLocationsCommand,
    DeletePersonInput,
    DeletePersonResponse,
    get_delete_party_with_locations_command_factory,
)
from backstop_mcp.features.org_people_writes.commands.delete_party_with_locations_command import (
    as_person_collection,
)
from backstop_mcp.features.party_resolver import (
    ResolvePartyQuery,
    get_resolve_party_query_factory,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import Resolved
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(DeletePersonResponse),
)
async def delete_person(
    ctx: Context,
    person: Annotated[DeletePersonInput, Field(description=DELETE_PERSON_INPUT_DESCRIPTION)],
    resolve_party_query: ResolvePartyQuery = Depends(get_resolve_party_query_factory),
    delete_party_with_locations_command: DeletePartyWithLocationsCommand = Depends(
        get_delete_party_with_locations_command_factory
    ),
) -> DeletePersonResponse | InputRequiredResult:
    """Permanently delete a CRM person and their contact-locations.

    `search_type` plus exactly one of `party_id` or `search` — same identity as
    `update_person`. Never invent an id. Deletion is permanent: Backstop has no recycle
    bin. Refuse bulk wipes, "all test records", and any search-then-delete sweep.
    Locations are removed first (`include=contactLocations`, never
    `include=locations`); deleting the person without that cascade strands those
    addresses. `destructive_hint` is true because this hard-deletes the record.

    When the client supports elicitation on MCP 2026-07-28+, this tool reads the person
    first and returns `InputRequiredResult` so the client can paint the form. On an
    older protocol that still advertised elicitation it returns `needs_confirmation`
    — the model asks in chat and retries with `confirm=true`. When the client never
    advertised elicitation, it deletes immediately.

    Call like: {"person": {"search_type": "people", "party_id": "<id from get_person>"}}
    """
    result = await resolve_party_query.run(
        search_type=person.search_type,
        party_id=person.party_id,
        search=person.search,
    )
    if not isinstance(result, Resolved):
        return unresolved_party_response(result)
    party = result.value
    collection = as_person_collection(party.search_type)
    logger.info(
        "org_people_writes.delete_person.start",
        extra={"search_type": collection, "party_id": party.id},
    )

    if not person.confirm:

        async def prompt() -> str:
            return await delete_party_with_locations_command.preview(
                collection=collection, party_id=party.id
            )

        gated = await elicit_entity_deletion(ctx, callback=prompt)
        if gated is not None:
            return gated
    deleted_location_ids = await delete_party_with_locations_command.run(
        collection=collection, party_id=party.id
    )
    return DeletedPersonResponse(
        id=party.id,
        resource_type=collection,
        deleted_location_ids=deleted_location_ids,
    )
