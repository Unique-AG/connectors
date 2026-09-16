"""`delete_opportunity`: hard-delete one deal. Backstop has no recycle bin."""

import logging
from typing import Annotated
from urllib.parse import quote

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import InputRequiredResult, ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopApiSingleResourceDocument, BackstopClient
from backstop_mcp.dependencies import get_backstop_client_for_current_caller
from backstop_mcp.features.elicitation_utils import elicit_entity_deletion
from backstop_mcp.features.opportunities import OpportunityResourceAttributes
from backstop_mcp.features.opportunity_writes import (
    DELETE_OPPORTUNITY_INPUT_DESCRIPTION,
    DeleteOpportunityCommand,
    DeleteOpportunityInput,
    DeleteOpportunityResponse,
    get_delete_opportunity_command_factory,
)
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)

_Document = BackstopApiSingleResourceDocument[OpportunityResourceAttributes]
_RESOURCE_TYPE = "opportunities"


@tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(DeleteOpportunityResponse),
)
async def delete_opportunity(
    ctx: Context,
    opportunity: Annotated[
        DeleteOpportunityInput, Field(description=DELETE_OPPORTUNITY_INPUT_DESCRIPTION)
    ],
    client: BackstopClient = Depends(get_backstop_client_for_current_caller),
    delete_opportunity_command: DeleteOpportunityCommand = Depends(
        get_delete_opportunity_command_factory
    ),
) -> DeleteOpportunityResponse | InputRequiredResult:
    """Permanently delete a CRM opportunity.

    Required on `opportunity`: `opportunity_id`. Never invent an id — echo a create, a
    `get_opportunities` row, or a `get_opportunities_by_ids` result. Deletion is permanent:
    Backstop has no recycle bin.

    When the client supports elicitation on MCP 2026-07-28+, this tool reads the
    opportunity first and returns `InputRequiredResult` so the client can paint the
    form. On an older protocol that still advertised elicitation it returns
    `needs_confirmation` — the model asks in chat and retries with `confirm=true`.
    When the client never advertised elicitation, it deletes immediately.
    `destructive_hint` is true because this hard-deletes the record.

    Call like: {"opportunity": {"opportunity_id": "<id from get_opportunities>"}}
    """
    logger.info(
        "opportunity_writes.delete.start",
        extra={"opportunity_id": opportunity.opportunity_id},
    )

    if not opportunity.confirm:

        async def prompt() -> str:
            return await _deletion_prompt(client=client, opportunity_id=opportunity.opportunity_id)

        gated = await elicit_entity_deletion(ctx, callback=prompt)
        if gated is not None:
            return gated
    return await delete_opportunity_command.run(opportunity=opportunity)


async def _deletion_prompt(*, client: BackstopClient, opportunity_id: str) -> str:
    """Show the user the deal they are about to hard-delete."""
    path = f"/{_RESOURCE_TYPE}/{quote(opportunity_id, safe='')}"
    document = await client.get(path, schema=_Document)
    lines = [
        "Permanently delete this opportunity from Backstop? There is no recycle bin.",
        "",
        f"id: {opportunity_id}",
    ]
    name = document.data.attributes.name
    if name:
        lines.append(f"name: {name}")
    return "\n".join(lines)
