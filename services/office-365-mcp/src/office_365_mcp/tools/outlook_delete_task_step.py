from collections.abc import Mapping
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.shared.handles import task_part_handle
from office_365_mcp.shared.outlook.task_deletes import Deletion, delete_todo_item
from office_365_mcp.shared.outlook.tasks import bad_handle
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Approval,
    Confirm,
    answer_pending,
    answered,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_delete_task_step"

PRESETS: tuple[str, ...] = ("outlook-tasks-delete",)


GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "step": (
        "outlook:///tasks/AAMkAGI2SYNTHETIC-list-0001%3D/AAMkAGI2SYNTHETIC-task-0001%3D"
        + "/steps/SYNTHETIC-step-0001"
    ),
}

_AGREE = "delete the step"
_DECLINE = "keep the step"
_NOTHING_DELETED = "The step was not deleted."


_DESCRIPTION = """\
Deletes one checklist step from a Microsoft To Do task, given the `steps[].uri` of an \
outlook_read_task answer. The task and its other steps stay. To check a step off and keep it, \
use outlook_update_task_step.

Notes:
- This tool always asks the user to agree, because this connector cannot bring a deleted step \
back. The question names the step and its task.
- This call is safe to repeat after a timeout. A second call finds no step and answers \
`not_found`.
"""


Outcome = Literal["deleted", "not_found"]


class DeletedTaskStep(BaseModel):
    text: str | None = Field(
        description=(
            "The words of the step, as this tool read them just before the delete. The value is "
            + "null when the step had no words, or when Microsoft 365 found no step to read."
        )
    )
    outcome: Outcome = Field(
        description=(
            "What this call did. `deleted`: Microsoft 365 accepted the delete, and this call "
            + "deleted the step. `not_found`: Microsoft 365 found no such step, before the "
            + "question or at the delete. The step was deleted before, or the user cannot see "
            + "it now. This call deleted nothing. When the value is `not_found`, do not tell the "
            + "user that this call deleted the step."
        )
    )


async def delete_task_step(
    client: GraphServiceClient, *, step: str, confirm: Confirm, answer_pending: bool = False
) -> DeletedTaskStep | InputRequiredResult:
    handle = task_part_handle("steps", step)
    if handle is None:
        raise ToolError(
            bad_handle(TOOL_NAME, "step", argument="step", nothing_happened=_NOTHING_DELETED)
        )
    approval = Approval(
        TOOL_NAME, handle.uri, Deletion(), confirm, answer_pending, _NOTHING_DELETED
    )
    removed = answered(await delete_todo_item(client, handle, approval=approval))
    if isinstance(removed, InputRequiredResult):
        return removed
    return DeletedTaskStep(text=removed.name, outcome=removed.outcome)


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_DELETED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Delete a Step of a Task",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_delete_task_step(
        step: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the step to delete, from a `steps[].uri` of an "
                    + "outlook_read_task answer. Copy it word for word."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedTaskStep | InputRequiredResult:
        return await delete_task_step(
            client,
            step=step,
            confirm=a_person_agrees(ctx),
            answer_pending=answer_pending(ctx),
        )
