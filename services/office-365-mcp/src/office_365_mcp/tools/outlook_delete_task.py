from collections.abc import Mapping
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.shared.handles import task_handle
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

TOOL_NAME = "outlook_delete_task"

PRESETS: tuple[str, ...] = ("outlook-tasks-delete",)

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///tasks/AAMkAGI2SYNTHETIC-list-0001%3D/AAMkAGI2SYNTHETIC-task-0001%3D",
}

_AGREE = "delete the task"
_DECLINE = "keep the task"
_NOTHING_DELETED = "The task was not deleted."

_DESCRIPTION = """\
Deletes one Microsoft To Do task of the signed-in user, given the `uri` of an outlook_list_tasks \
row. To mark a task done and keep it, use outlook_set_task_status.

Notes:
- This tool always asks the user to agree, because this connector cannot bring a deleted task \
back. The question names the task and its list, and it says when other people share the list.
- This call is safe to repeat after a timeout. A second call finds no task and answers \
`not_found`.
"""


Outcome = Literal["deleted", "not_found"]


class DeletedTask(BaseModel):
    title: str | None = Field(
        description=(
            "The title of the task, as this tool read it just before the delete. The value is "
            + "null when the task had no title, or when Microsoft 365 found no task to read."
        )
    )
    outcome: Outcome = Field(
        description=(
            "What this call did. `deleted`: Microsoft 365 accepted the delete, and this call "
            + "deleted the task. `not_found`: Microsoft 365 found no such task, before the "
            + "question or at the delete. The task was deleted before, or the user cannot see "
            + "it now. This call deleted nothing. When the value is `not_found`, do not tell the "
            + "user that this call deleted the task."
        )
    )


async def delete_task(
    client: GraphServiceClient, *, uri: str, confirm: Confirm, answer_pending: bool = False
) -> DeletedTask | InputRequiredResult:
    handle = task_handle(uri)
    if handle is None:
        raise ToolError(
            bad_handle(TOOL_NAME, "task", argument="uri", nothing_happened=_NOTHING_DELETED)
        )
    approval = Approval(
        TOOL_NAME, handle.uri, Deletion(), confirm, answer_pending, _NOTHING_DELETED
    )
    removed = answered(await delete_todo_item(client, handle, approval=approval))
    if isinstance(removed, InputRequiredResult):
        return removed
    return DeletedTask(title=removed.name, outcome=removed.outcome)


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_DELETED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Delete a Task",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_delete_task(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the task to delete, from the `uri` of an outlook_list_tasks "
                    + "row. Copy it word for word."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedTask | InputRequiredResult:
        return await delete_task(
            client, uri=uri, confirm=a_person_agrees(ctx), answer_pending=answer_pending(ctx)
        )
