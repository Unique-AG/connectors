"""`update_opportunity`: PATCH one deal. The only write that moves a deal's stage."""

import logging
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.opportunity_writes import (
    UPDATE_OPPORTUNITY_INPUT_DESCRIPTION,
    UpdatedOpportunityResponse,
    UpdateOpportunityCommand,
    UpdateOpportunityInput,
    get_update_opportunity_command_factory,
)
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(UpdatedOpportunityResponse),
)
async def update_opportunity(
    opportunity: Annotated[
        UpdateOpportunityInput, Field(description=UPDATE_OPPORTUNITY_INPUT_DESCRIPTION)
    ],
    update_opportunity_command: UpdateOpportunityCommand = Depends(
        get_update_opportunity_command_factory
    ),
) -> UpdatedOpportunityResponse:
    """Patch one CRM opportunity. This is the only way to move a deal's stage.

    `stage` is a **name** resolved against this instance's vocabulary, not an id. `probability`
    is a fraction (0.3 is 30%) and is **not** changed by setting a stage — pass it explicitly
    if the deal's probability should move. A `closed` stage closes the deal automatically.
    Custom fields go through `update_custom_field_values`; writing them here skips picklist and
    time-series validation. Omit a field to leave it unchanged. Never invent an id.

    Moving several deals means calling this once per deal. There is no bulk stage-move tool.
    `backfill_opportunity_stage_history` appends historical rows and does not move anything.

    Call like: {"opportunity": {"opportunity_id": "<id from get_opportunities>",
    "stage": "IDD", "probability": 0.3}}
    """
    logger.info(
        "opportunity_writes.update.start",
        extra={"opportunity_id": opportunity.opportunity_id},
    )
    return await update_opportunity_command.run(new_opportunity=opportunity)
