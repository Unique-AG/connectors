from collections.abc import Mapping
from contextlib import suppress
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.todo_task import TodoTask
from msgraph.generated.users.item.todo.lists.item.tasks.item.todo_task_item_request_builder import (  # noqa: E501
    TodoTaskItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import (
    GraphNotFound,
    graph_errors,
    graph_step,
    no_retry,
    not_graph,
)
from office_365_mcp.shared.handles import task_handle
from office_365_mcp.shared.outlook.tasks import ListAudience, bad_task_handle, list_audience
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    confirmation_digest,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_delete_task"

PRESETS: tuple[str, ...] = ("outlook-tasks-delete",)

STEP_TASK = "task"

STEP_DELETE = "delete_task"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///tasks/AAMkAGI2SYNTHETIC-list-0001%3D/AAMkAGI2SYNTHETIC-task-0001%3D",
}

_AGREE = "delete the task"
_DECLINE = "keep the task"
_NOTHING_DELETED = "The task was not deleted."

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."


_DESCRIPTION = """\
Deletes one Microsoft To Do task of the signed-in user, given the `uri` of an outlook_list_tasks \
row. The task goes away with its steps, links, and attached files. To mark a task done and keep \
it, use outlook_set_task_status.

Notes:
- This tool always asks the user to agree, because this connector cannot bring a deleted task \
back. The question names the task and its list, and it says when other people share the list and \
lose the task too.
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
    client: GraphServiceClient, *, uri: str, confirm: Confirm
) -> DeletedTask | InputRequiredResult:
    handle = task_handle(uri)
    if handle is None:
        raise ToolError(bad_task_handle(TOOL_NAME, nothing_happened=_NOTHING_DELETED))

    task_builder = client.me.todo.lists.by_todo_task_list_id(handle.list_id).tasks.by_todo_task_id(
        handle.task_id
    )
    asked: InputRequiredResult | None = None
    refused: str | None = None
    outcome: Outcome = "not_found"
    with graph_errors():
        try:
            audience = await list_audience(client, handle.list_id)
        except GraphNotFound:
            return DeletedTask(title=None, outcome="not_found")
        task = await _task(task_builder)
        if task is None:
            return DeletedTask(title=None, outcome="not_found")
        question = _question(task.title, audience)
        about = confirmation_digest(TOOL_NAME, handle.uri, question, task.title or "")
        with not_graph():
            answer = await confirm(question, about)
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with suppress(GraphNotFound), graph_step(STEP_DELETE):
                await task_builder.delete(
                    request_configuration=RequestConfiguration[QueryParameters](options=no_retry())
                )
                outcome = "deleted"

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return DeletedTask(title=task.title, outcome=outcome)


async def _task(task_builder: TodoTaskItemRequestBuilder) -> TodoTask | None:
    try:
        with graph_step(STEP_TASK):
            task = await task_builder.get()
    except GraphNotFound:
        return None
    assert task is not None, "Graph answered a task read with no task"
    return task


def _question(title: str | None, audience: ListAudience) -> str:
    named = repr(cut_for_a_question(title)) if title else "with no title"
    listed = f" from the list {cut_for_a_question(audience.name)!r}" if audience.name else ""
    shared = (
        ""
        if not audience.reaches_others
        else (
            " Other people share this list, and they lose the task too."
            if audience.is_shared
            else " Microsoft 365 did not report this list as private. Other people can lose the "
            + "task too."
        )
    )
    return (
        f"Delete the task {named}{listed}?{shared} Its steps, links, and files go with it. This "
        + "connector cannot undo the delete."
    )


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
        return await delete_task(client, uri=uri, confirm=a_person_agrees(ctx))
