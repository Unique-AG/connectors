from collections.abc import Mapping
from contextlib import suppress
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from mcp.types import InputRequiredResult
from msgraph.generated.users.item.todo.lists.item.tasks.item.todo_task_item_request_builder import (  # noqa: E501
    TodoTaskItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import GraphNotFound, graph_errors, graph_step, not_graph
from office_365_mcp.shared.handles import TaskPartHandle, task_part_handle
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    confirmation_digest,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_delete_task_link"

PRESETS: tuple[str, ...] = ("outlook-tasks-delete",)

STEP_LINK = "task_link_to_delete"
STEP_TASK = "task_of_link"
STEP_DELETE = "delete_task_link"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

_EXAMPLE_HANDLE = TaskPartHandle(
    "links", "AAMkAGI2SYNTHETIC-list-0001=", "AAMkAGI2SYNTHETIC-task-0001=", "SYNTHETIC-link-0001"
)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"link": _EXAMPLE_HANDLE.uri}

_TaskQuery = TodoTaskItemRequestBuilder.TodoTaskItemRequestBuilderGetQueryParameters

_NOTHING_DELETED = "The link was not deleted."
_AGREE = "delete the link"
_DECLINE = "keep the link"

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this link or its task, and nothing was deleted. The handle is "
    + "well formed, so this is not a bad argument. The link was most likely deleted already, or "
    + "its task was deleted or moved to another list. Read the task again with outlook_read_task "
    + f"and take a fresh `uri` from its `links`. {_AGAIN}"
)

_BAD_HANDLE = (
    "outlook_delete_task_link takes the `uri` of a link on a task, and this is not one. Take the "
    + "`uri` of a row in the `links` that outlook_read_task returned, and copy it word for word. "
    + f"A link handle looks like {_EXAMPLE_HANDLE.uri}. A task handle, a title, and a web "
    + f"address are not link handles. {_NOTHING_DELETED} {_AGAIN}"
)

_DESCRIPTION = """\
Deletes one link from a Microsoft To Do task of the signed-in user, given the `uri` of a row in \
the `links` of outlook_read_task. The item that the link opens does not change.

Notes:
- This tool always asks the user to agree, and the question names the link and the task.
- This call is safe to repeat after a timeout.
"""


class DeletedTaskLink(BaseModel):
    title: str | None = Field(
        description=(
            "The words that To Do showed for the link, as Microsoft 365 reported them immediately "
            + "before the delete. Null when the link had none."
        )
    )
    deleted: Literal[True] = Field(
        description=(
            "Always true, because this tool answers only when the link is gone. It is also true "
            + "when Graph found no link to delete after this call read it."
        )
    )


async def delete_task_link(
    client: GraphServiceClient, *, link: str, confirm: Confirm
) -> DeletedTaskLink | InputRequiredResult:
    handle = task_part_handle("links", link)
    if handle is None:
        raise ToolError(_BAD_HANDLE)

    task = client.me.todo.lists.by_todo_task_list_id(handle.list_id).tasks.by_todo_task_id(
        handle.task_id
    )
    found = task.linked_resources.by_linked_resource_id(handle.part_id)

    title: str | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors():
        with graph_step(STEP_LINK):
            resource = await found.get()
        assert resource is not None, "Graph answered a task link read with no link"
        title = resource.display_name
        with graph_step(STEP_TASK):
            owner = await task.get(
                request_configuration=RequestConfiguration[_TaskQuery](
                    query_parameters=_TaskQuery(select=["id", "title"])
                )
            )
        assert owner is not None, "Graph answered a task read with no task"
        question = _question(title, owner.title)
        with not_graph():
            answer = await confirm(question, confirmation_digest(TOOL_NAME, handle.uri, question))
        asked = answer if isinstance(answer, InputRequiredResult) else None
        refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with suppress(GraphNotFound), graph_step(STEP_DELETE):
                await found.delete()

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    return DeletedTaskLink(title=title, deleted=True)


def _question(title: str | None, task_title: str | None) -> str:
    link = f"the link {cut_for_a_question(title)!r}" if title else "a link with no title"
    task = f"the task {cut_for_a_question(task_title)!r}" if task_title else "a task with no title"
    return (
        f"Delete {link} from {task}? The item that the link opens does not change. To get the "
        + "link back, someone must add it again."
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Delete a Link from a Task",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_delete_task_link(
        link: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the link, from the `uri` of a row in the `links` of "
                    + "outlook_read_task. Copy it word for word."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedTaskLink | InputRequiredResult:
        return await delete_task_link(
            client,
            link=link,
            confirm=person_confirms(
                ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_DELETED
            ),
        )
