from collections.abc import Mapping
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.shared.handles import task_list_handle
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

TOOL_NAME = "outlook_delete_task_list"

PRESETS: tuple[str, ...] = ("outlook-tasks-delete",)

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "task_list": "outlook:///tasklists/AAMkAGI2SYNTHETIC-list-0001%3D",
}

_NOTHING_DELETED = "Nothing was deleted."
_AGREE = "delete the list"
_DECLINE = "keep the list"


_DESCRIPTION = """\
Deletes one Microsoft To Do task list of the signed-in user and every task in it, given the \
`uri` of an outlook_list_task_lists row. Outlook and To Do no longer show the list. This tool \
always asks the user to agree, and the question names the list.

Notes:
- This tool refuses the built-in Tasks list and the built-in list of flagged messages, because \
Microsoft To Do does not delete them.
- No tool of this connector can bring back a deleted list or its tasks.
- This call is safe to repeat after a timeout. A second call finds no list and answers \
`not_found`.
"""


Outcome = Literal["deleted", "not_found"]


class DeletedTaskList(BaseModel):
    uri: str = Field(
        description=(
            "The handle that this call was given, echoed back. Microsoft 365 finds no list for "
            + "this handle now, so do not pass it to another tool."
        )
    )
    name: str | None = Field(
        description=(
            "The name of the list, as Microsoft 365 reported it immediately before the delete. "
            + "The value is null when Microsoft 365 reported no name, or when Microsoft 365 "
            + "found no list to read."
        )
    )
    outcome: Outcome = Field(
        description=(
            "What this call did. `deleted`: Microsoft 365 accepted the delete, and this call "
            + "deleted the list. `not_found`: Microsoft 365 found no such list, before the "
            + "question or at the delete. The list was deleted before, or the user cannot see "
            + "it now, for example because its owner stopped sharing it. This call deleted "
            + "nothing. When the value is `not_found`, do not tell the user that this call "
            + "deleted the list."
        )
    )


async def delete_task_list(
    client: GraphServiceClient, *, task_list: str, confirm: Confirm, answer_pending: bool = False
) -> DeletedTaskList | InputRequiredResult:
    handle = task_list_handle(task_list)
    if handle is None:
        raise ToolError(
            bad_handle(
                TOOL_NAME, "task list", argument="task_list", nothing_happened=_NOTHING_DELETED
            )
        )
    approval = Approval(
        TOOL_NAME, handle.uri, Deletion(), confirm, answer_pending, _NOTHING_DELETED
    )
    removed = answered(await delete_todo_item(client, handle, approval=approval))
    if isinstance(removed, InputRequiredResult):
        return removed
    return DeletedTaskList(uri=handle.uri, name=removed.name, outcome=removed.outcome)


def a_person_agrees(ctx: Context) -> Confirm:
    return person_confirms(ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_DELETED)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Delete a Task List",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_delete_task_list(
        task_list: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the task list to delete, from the `uri` of an "
                    + "outlook_list_task_lists row. Copy it word for word. Every task in the "
                    + "list is deleted with it."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedTaskList | InputRequiredResult:
        return await delete_task_list(
            client,
            task_list=task_list,
            confirm=a_person_agrees(ctx),
            answer_pending=answer_pending(ctx),
        )
