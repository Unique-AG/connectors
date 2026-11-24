from collections.abc import Mapping
from contextlib import suppress
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.generated.models.todo_task_list import TodoTaskList
from msgraph.generated.models.wellknown_list_name import WellknownListName
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphNotFound, graph_errors, graph_step, not_graph
from office_365_mcp.shared.handles import task_list_handle
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    confirmation_digest,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_delete_task_list"

PRESETS: tuple[str, ...] = ("outlook-tasks-delete",)

STEP_TASK_LIST = "task_list"
STEP_DELETE = "delete_task_list"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "task_list": "outlook:///tasklists/AAMkAGI2SYNTHETIC-list-0001%3D",
}

_NOTHING_DELETED = "Nothing was deleted."
_AGREE = "delete the list"
_DECLINE = "keep the list"

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find this task list, and nothing was deleted. The handle is well "
    + "formed, so this is not a bad argument. A person or an earlier call of this tool probably "
    + "deleted the list, or its owner stopped sharing it. Call outlook_list_task_lists again. If "
    + "the list is not in that result, it is already gone and nothing is left to delete. The "
    + "same handle fails the same way, so do not retry it."
)


_DESCRIPTION = """\
Deletes one Microsoft To Do task list of the signed-in user and every task in it, given the \
`uri` of an outlook_list_task_lists row. Outlook and To Do no longer show the list. This tool \
always asks the user to agree, and the question names the list.

Notes:
- This tool refuses the built-in Tasks list and the built-in list of flagged messages, because \
Microsoft To Do does not delete them.
- No tool of this connector can bring back a deleted list or its tasks.
- This call is safe to repeat after a timeout. A second call finds no list and reports that.
"""

_NOT_A_LIST_HANDLE = (
    f"{TOOL_NAME} takes the `uri` of a task list in `task_list`, and this is not one. Take the "
    + "`uri` of a row that outlook_list_task_lists returned, and copy it word for word. A task "
    + "list handle looks like outlook:///tasklists/AAMkAGI2SYNTHETIC-list-0001%3D. A list name "
    + f"and a task handle are not task list handles. {_NOTHING_DELETED} {_AGAIN}"
)

_BUILT_IN = (
    "This handle names a built-in list of To Do: the Tasks list or the list of flagged messages. "
    + "Microsoft To Do does not delete these lists. To remove tasks from it, delete each task "
    + f"with outlook_delete_task. {_NOTHING_DELETED} {_AGAIN}"
)


class DeletedTaskList(BaseModel):
    uri: str = Field(
        description=(
            "The handle that this call was given, echoed back. The list that this handle named "
            + "is deleted, so do not pass this handle to another tool."
        )
    )
    name: str | None = Field(
        description=(
            "The name of the list, as Microsoft 365 reported it immediately before the delete. "
            + "The value is null when Microsoft 365 reported no name."
        )
    )
    deleted: Literal[True] = Field(
        description=(
            "Always true, because this tool answers only when the list is gone. It is also true "
            + "when the list was there at the start of this call, but Graph then found no list "
            + "to delete."
        )
    )


async def delete_task_list(
    client: GraphServiceClient, *, task_list: str, confirm: Confirm
) -> DeletedTaskList | InputRequiredResult:
    handle = task_list_handle(task_list)
    if handle is None:
        raise ToolError(_NOT_A_LIST_HANDLE)

    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors():
        found = await _task_list(client, handle.list_id)
        if _is_built_in(found):
            refused = _BUILT_IN
        else:
            question = _question(found)
            about = confirmation_digest(TOOL_NAME, handle.list_id, question)
            with not_graph():
                answer = await confirm(question, about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with suppress(GraphNotFound), graph_step(STEP_DELETE):
                await client.me.todo.lists.by_todo_task_list_id(handle.list_id).delete()

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return DeletedTaskList(uri=handle.uri, name=found.display_name, deleted=True)


async def _task_list(client: GraphServiceClient, list_id: str) -> TodoTaskList:
    with graph_step(STEP_TASK_LIST):
        found = await client.me.todo.lists.by_todo_task_list_id(list_id).get()
    assert found is not None, "Graph answered a task list read with no list"
    return found


def _is_built_in(found: TodoTaskList) -> bool:
    return found.wellknown_list_name not in (None, WellknownListName.None_)


def _question(found: TodoTaskList) -> str:
    named = (
        f"the task list {cut_for_a_question(found.display_name)!r}"
        if found.display_name
        else "a task list with no name"
    )
    asked = f"Delete {named} and every task in it? This connector cannot undo the delete."
    if found.is_shared is False:
        return asked
    if found.is_shared is None:
        return (
            f"{asked} Microsoft 365 did not report this list as private. Other people can lose "
            + "it too."
        )
    if found.is_owner is True:
        return f"{asked} Other people share this list. They lose it too."
    return (
        f"{asked} Another person shared this list with you. Microsoft does not document what "
        + "this delete does for that person."
    )


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
        return await delete_task_list(client, task_list=task_list, confirm=a_person_agrees(ctx))
