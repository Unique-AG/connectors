"""`delete_person`: hard-delete one person after removing contact-locations."""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.elicitation_utils import EntityDeletion, elicit_entity_deletion
from backstop_mcp.features.org_people_writes import (
    DELETE_PERSON_INPUT_DESCRIPTION,
    DeletedPersonResponse,
    DeletePartyWithLocationsCommand,
    DeletePersonInput,
    DeletePersonResponse,
    get_delete_party_with_locations_command_factory,
)
from backstop_mcp.features.party_resolver import (
    ResolvePartyQuery,
    get_resolve_party_query_factory,
    unresolved_party_response,
)
from backstop_mcp.features.resolution import Resolved, elicit_if_ambiguous
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)

_COLLECTION = "people"
_NOT_CONFIRMED = (
    "Deletion was not confirmed. Nothing was deleted. Do not retry unless the user asks again."
)


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
) -> DeletePersonResponse:
    """Permanently delete a CRM person and their contact-locations.

    `search_type` plus exactly one of `party_id` or `search` — same identity as
    `update_person`. Never invent an id. Deletion is permanent: Backstop has no recycle
    bin. Locations are removed first (`include=contactLocations`, never
    `include=locations`); deleting the person without that cascade strands those
    addresses. `destructive_hint` is true because this hard-deletes the record.

    When the client supports elicitation, this tool reads the person first and asks the
    user to confirm the name and location count before deleting. When the client cannot
    elicit, it deletes immediately.

    Call like: {"person": {"search_type": "people", "party_id": "<id from get_person>"}}
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
        "org_people_writes.delete_person.start",
        extra={"search_type": party.search_type, "party_id": party.id},
    )

    async def prompt() -> str:
        return await delete_party_with_locations_command.preview(
            collection=_COLLECTION, party_id=party.id
        )

    outcome = await elicit_entity_deletion(ctx, callback=prompt)
    if outcome is EntityDeletion.DECLINED:
        logger.info(
            "org_people_writes.delete_person.not_confirmed",
            extra={"party_id": party.id},
        )
        raise ToolError(_NOT_CONFIRMED)
    if outcome is EntityDeletion.NOT_AVAILABLE:
        logger.info(
            "org_people_writes.delete_person.elicit.not_available",
            extra={"party_id": party.id},
        )
    deleted_location_ids = await delete_party_with_locations_command.run(
        collection=_COLLECTION, party_id=party.id
    )
    return DeletedPersonResponse(
        id=party.id,
        resource_type=_COLLECTION,
        deleted_location_ids=deleted_location_ids,
    )
