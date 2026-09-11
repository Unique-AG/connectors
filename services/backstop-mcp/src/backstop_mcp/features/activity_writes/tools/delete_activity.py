"""`delete_activity`: hard-delete a note, meeting, call, task, email, or document."""

import logging
from http import HTTPStatus
from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import Depends
from fastmcp.exceptions import ToolError
from fastmcp.tools import tool
from mcp.types import ToolAnnotations
from pydantic import Field

from backstop_mcp.backstop_client import BackstopApiError
from backstop_mcp.features.activity_history import (
    ActivityDetailResponse,
    GetActivityDetailQuery,
    ResourceIdentifierDto,
    get_activity_detail_query_factory,
)
from backstop_mcp.features.activity_writes import (
    DELETE_ACTIVITY_INPUT_DESCRIPTION,
    DeleteActivityCommand,
    DeleteActivityInput,
    DeletedActivityResponse,
    get_delete_activity_command_factory,
)
from backstop_mcp.features.elicitation_utils import EntityDeletion, elicit_entity_deletion
from backstop_mcp.models import published_output_schema

logger = logging.getLogger(__name__)

_BODY_PREVIEW_CHARS = 500
_DETAIL_OPTIONAL_KINDS = frozenset({"email", "task"})
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
    output_schema=published_output_schema(DeletedActivityResponse),
)
async def delete_activity(
    ctx: Context,
    activity: Annotated[DeleteActivityInput, Field(description=DELETE_ACTIVITY_INPUT_DESCRIPTION)],
    get_activity_detail_query: GetActivityDetailQuery = Depends(get_activity_detail_query_factory),
    delete_activity_command: DeleteActivityCommand = Depends(get_delete_activity_command_factory),
) -> DeletedActivityResponse:
    """Permanently delete a CRM note, meeting, call, task, email, or document.

    Required on `activity`: `kind` and `activity_id`. Never invent an id — echo a create, a
    `search_activities` row, or a `get_activity_history` handle. Deletion is permanent:
    Backstop has no recycle bin. Use this to undo a wrongly logged activity or an
    `attach_file` upload.

    When the client supports elicitation, this tool reads the activity first and asks the
    user to confirm the title and body before deleting. When the client cannot elicit, it
    deletes immediately.

    Call like: {"activity": {"kind": "note", "activity_id": "<id from a create echo>"}}
    """
    logger.info(
        "activity_writes.delete.start",
        extra={"kind": activity.kind, "activity_id": activity.activity_id},
    )
    prompt = await _deletion_prompt(
        activity=activity, get_activity_detail_query=get_activity_detail_query
    )
    outcome = await elicit_entity_deletion(ctx, prompt)
    if outcome is EntityDeletion.DECLINED:
        logger.info(
            "activity_writes.delete.not_confirmed",
            extra={"kind": activity.kind, "activity_id": activity.activity_id},
        )
        raise ToolError(_NOT_CONFIRMED)
    if outcome is EntityDeletion.NOT_AVAILABLE:
        logger.info(
            "activity_writes.delete.elicit.not_available",
            extra={"kind": activity.kind, "activity_id": activity.activity_id},
        )
    return await delete_activity_command.run(activity=activity)


async def _deletion_prompt(
    *, activity: DeleteActivityInput, get_activity_detail_query: GetActivityDetailQuery
) -> str:
    """Show the user the record they are about to hard-delete."""
    try:
        handle = ResourceIdentifierDto.from_activity_id(activity.activity_id)
    except ToolError:
        logger.info(
            "activity_writes.delete.detail.skipped",
            extra={
                "kind": activity.kind,
                "activity_id": activity.activity_id,
                "reason": "handle is not a detail id",
            },
        )
        return _format_deletion_prompt(kind=activity.kind, activity_id=activity.activity_id)
    try:
        detail = await get_activity_detail_query.run(
            activity_id=activity.activity_id, handle=handle
        )
    except BackstopApiError as exc:
        if exc.status_code == HTTPStatus.NOT_FOUND and activity.kind in _DETAIL_OPTIONAL_KINDS:
            logger.info(
                "activity_writes.delete.detail.skipped",
                extra={
                    "kind": activity.kind,
                    "activity_id": activity.activity_id,
                    "reason": "detail endpoint has no record",
                },
            )
            return _format_deletion_prompt(kind=activity.kind, activity_id=activity.activity_id)
        raise
    return _format_deletion_prompt(
        kind=activity.kind, activity_id=activity.activity_id, detail=detail
    )


def _format_deletion_prompt(
    *,
    kind: str,
    activity_id: str,
    detail: ActivityDetailResponse | None = None,
) -> str:
    lines = [
        f"Permanently delete this {kind} from Backstop? There is no recycle bin.",
        "",
        f"id: {activity_id}",
    ]
    if detail is None:
        return "\n".join(lines)
    if detail.type:
        lines.append(f"type: {detail.type}")
    if detail.title:
        lines.append(f"title: {detail.title}")
    if detail.start is not None:
        lines.append(f"start: {detail.start.isoformat()}")
    if detail.stop is not None:
        lines.append(f"stop: {detail.stop.isoformat()}")
    if detail.location:
        lines.append(f"location: {detail.location}")
    if detail.time_zone:
        lines.append(f"time_zone: {detail.time_zone}")
    attendee_names = tuple(attendee.name for attendee in detail.attendees if attendee.name)
    if attendee_names:
        lines.append(f"attendees: {', '.join(attendee_names)}")
    preview = _preview(detail.body)
    if preview:
        lines.extend(("", preview))
    return "\n".join(lines)


def _preview(text: str) -> str:
    stripped = text.strip()
    if len(stripped) <= _BODY_PREVIEW_CHARS:
        return stripped
    return stripped[: _BODY_PREVIEW_CHARS - 3].rstrip() + "..."
