"""`update_activity`: PATCH a note, meeting, call, task, email, or document."""

import logging
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.activity_writes import (
    UPDATE_ACTIVITY_INPUT_DESCRIPTION,
    UpdateActivityCommand,
    UpdateActivityInput,
    UpdatedActivityResponse,
    get_update_activity_command_factory,
)
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)


@tool(
    # PATCH overwrites or clears fields with no prior value returned; the host
    # approval prompt is driven by these hints. Same patch is a no-op.
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(UpdatedActivityResponse),
)
async def update_activity(
    activity: Annotated[UpdateActivityInput, Field(description=UPDATE_ACTIVITY_INPUT_DESCRIPTION)],
    update_activity_command: UpdateActivityCommand = Depends(get_update_activity_command_factory),
) -> UpdatedActivityResponse:
    """Patch a CRM note, meeting, call, task, email, or document.

    Required on `activity`: `kind`, `activity_id`, and at least one field to change. Omit a
    field to leave it unchanged. Never invent an id — echo a create, a `search_activities`
    row, or a `get_activity_history` handle. Author is not a parameter. Email PATCH accepts
    only `display_subject` and `activity_tag_ids`; parsed subject/from/to are not editable.
    The document file blob is not replaced here.

    Call like: {"activity": {"kind": "note", "activity_id": "<id from a create echo>",
    "title": "Corrected title"}}
    """
    logger.info(
        "activity_writes.update.start",
        extra={"kind": activity.kind, "activity_id": activity.activity_id},
    )
    return await update_activity_command.run(activity=activity)
