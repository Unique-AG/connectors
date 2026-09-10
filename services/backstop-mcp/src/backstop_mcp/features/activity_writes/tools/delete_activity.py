"""`delete_activity`: hard-delete a note, meeting, call, task, email, or document."""

import logging
from typing import Annotated

from fastmcp.dependencies import Depends
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.features.activity_writes import (
    DELETE_ACTIVITY_INPUT_DESCRIPTION,
    DeleteActivityCommand,
    DeleteActivityInput,
    DeletedActivityResponse,
    get_delete_activity_command_factory,
)
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)


@tool(
    annotations=ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=False,
        open_world_hint=False,
    ),
    output_schema=published_output_schema(DeletedActivityResponse),
)
async def delete_activity(
    activity: Annotated[DeleteActivityInput, Field(description=DELETE_ACTIVITY_INPUT_DESCRIPTION)],
    delete_activity_command: DeleteActivityCommand = Depends(get_delete_activity_command_factory),
) -> DeletedActivityResponse:
    """Permanently delete a CRM note, meeting, call, task, email, or document.

    Required on `activity`: `kind` and `activity_id`. Never invent an id — echo a create, a
    `search_activities` row, or a `get_activity_history` handle. Deletion is permanent:
    Backstop has no recycle bin. Use this to undo a wrongly logged activity or an
    `attach_file` upload.

    Call like: {"activity": {"kind": "note", "activity_id": "<id from a create echo>"}}
    """
    logger.info(
        "activity_writes.delete.start",
        extra={"kind": activity.kind, "activity_id": activity.activity_id},
    )
    return await delete_activity_command.run(activity=activity)
