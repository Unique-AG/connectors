"""`delete_person`: hard-delete one person after removing contact-locations."""

import logging
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp.types import InputRequiredResult, ToolAnnotations
from pydantic import Field

from backstop_mcp.features.elicitation_utils import (
    DELETION_NOT_CONFIRMED,
    EntityDeletion,
    elicit_entity_deletion,
)
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
from backstop_mcp.features.resolution import Resolved, input_required
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
    """Permanently delete one CRM person and their locations.

    Needs a trusted `party_id` (`search_type` defaults to people). Never invent an id.
    Deletion is permanent: Backstop has no recycle bin. Locations are removed first.
    Refuse bulk wipes, "all test records", and any search-then-delete sweep.

    When the client supports elicitation, this tool reads the person first and asks the
    user to confirm before deleting. When the client cannot elicit, it deletes immediately.

    Call like: {"person": {"search_type": "people", "party_id": "<id from get_person>"}}
    """
    result = await resolve_party_query.run(
        search_type=person.search_type,
        party_id=person.party_id,
    )
    if not isinstance(result, Resolved):
        return unresolved_party_response(result)
    party = result.value
    collection = as_person_collection(party.search_type)
    logger.info(
        "org_people_writes.delete_person.start",
        extra={"search_type": collection, "party_id": party.id},
    )

    async def prompt() -> str:
        return await delete_party_with_locations_command.preview(
            collection=collection, party_id=party.id
        )

    outcome = await elicit_entity_deletion(ctx, callback=prompt)
    if input_required(outcome):
        return outcome
    if outcome is EntityDeletion.DECLINED:
        logger.info(
            "org_people_writes.delete_person.not_confirmed",
            extra={"search_type": collection, "party_id": party.id},
        )
        raise ToolError(DELETION_NOT_CONFIRMED)
    if outcome is EntityDeletion.NOT_AVAILABLE:
        logger.info(
            "org_people_writes.delete_person.elicit.not_available",
            extra={"search_type": collection, "party_id": party.id},
        )
    deleted_location_ids = await delete_party_with_locations_command.run(
        collection=collection, party_id=party.id
    )
    return DeletedPersonResponse(
        id=party.id,
        resource_type=collection,
        deleted_location_ids=deleted_location_ids,
    )
