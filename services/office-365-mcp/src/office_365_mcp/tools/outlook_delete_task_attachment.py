from collections.abc import Mapping
from contextlib import suppress
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from mcp.types import InputRequiredResult
from msgraph.generated.users.item.todo.lists.item.tasks.item.attachments.item.attachment_base_item_request_builder import (  # noqa: E501
    AttachmentBaseItemRequestBuilder,
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

TOOL_NAME = "outlook_delete_task_attachment"

PRESETS: tuple[str, ...] = ("outlook-tasks-delete",)

STEP_ATTACHMENT = "task_attachment_to_delete"
STEP_TASK = "task_of_attachment"
STEP_DELETE = "delete_task_attachment"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

_EXAMPLE_HANDLE = TaskPartHandle(
    "attachments",
    "AAMkAGI2SYNTHETIC-list-0001=",
    "AAMkAGI2SYNTHETIC-task-0001=",
    "AAMkAGI2SYNTHETIC-attachment-0001=",
)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"attachment": _EXAMPLE_HANDLE.uri}

_AttachmentQuery = (
    AttachmentBaseItemRequestBuilder.AttachmentBaseItemRequestBuilderGetQueryParameters
)

_NOTHING_DELETED = "The file was not deleted."
_AGREE = "delete the file"
_DECLINE = "keep the file"

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this file or its task, and nothing was deleted. The handle is "
    + "well formed, so this is not a bad argument. The file was most likely deleted already, or "
    + "its task was deleted or moved to another list. Read the task again with outlook_read_task "
    + f"and take a fresh `uri` from its `attachments`. {_AGAIN}"
)

_BAD_HANDLE = (
    "outlook_delete_task_attachment takes the `uri` of a file on a task, and this is not one. "
    + "Take the `uri` of a row in the `attachments` that outlook_read_task returned, and copy it "
    + f"word for word. A file handle looks like {_EXAMPLE_HANDLE.uri}. A task handle and a file "
    + f"name are not file handles. {_NOTHING_DELETED} {_AGAIN}"
)

_DESCRIPTION = """\
Deletes one file from a Microsoft To Do task of the signed-in user, given the `uri` of a row in \
the `attachments` of outlook_read_task.

Notes:
- This tool always asks the user to agree, and the question names the file and the task. This \
tool cannot get a deleted file back.
- This call is safe to repeat after a timeout.
"""


class DeletedTaskAttachment(BaseModel):
    name: str | None = Field(
        description=(
            "The file name, as Microsoft 365 reported it immediately before the delete. Null when "
            + "the file had none."
        )
    )
    deleted: Literal[True] = Field(
        description=(
            "Always true, because this tool answers only when the file is gone. It is also true "
            + "when Graph found no file to delete after this call read it."
        )
    )


async def delete_task_attachment(
    client: GraphServiceClient, *, attachment: str, confirm: Confirm
) -> DeletedTaskAttachment | InputRequiredResult:
    handle = task_part_handle("attachments", attachment)
    if handle is None:
        raise ToolError(_BAD_HANDLE)

    task = client.me.todo.lists.by_todo_task_list_id(handle.list_id).tasks.by_todo_task_id(
        handle.task_id
    )
    found = task.attachments.by_attachment_base_id(handle.part_id)

    name: str | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors():
        with graph_step(STEP_ATTACHMENT):
            described = await found.get(
                request_configuration=RequestConfiguration[_AttachmentQuery](
                    query_parameters=_AttachmentQuery(select=["id", "name"])
                )
            )
        assert described is not None, "Graph answered a task attachment read with no attachment"
        name = described.name
        with graph_step(STEP_TASK):
            owner = await task.get()
        assert owner is not None, "Graph answered a task read with no task"
        question = _question(name, owner.title)
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
    return DeletedTaskAttachment(name=name, deleted=True)


def _question(name: str | None, task_title: str | None) -> str:
    file = f"the file {cut_for_a_question(name)!r}" if name else "a file with no name"
    task = f"the task {cut_for_a_question(task_title)!r}" if task_title else "a task with no title"
    return f"Delete {file} from {task}? This tool cannot get the file back."


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Delete a Task Attachment",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_delete_task_attachment(
        attachment: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the file, from the `uri` of a row in the `attachments` of "
                    + "outlook_read_task. Copy it word for word."
                ),
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> DeletedTaskAttachment | InputRequiredResult:
        return await delete_task_attachment(
            client,
            attachment=attachment,
            confirm=person_confirms(
                ctx, agree=_AGREE, decline=_DECLINE, nothing_happened=_NOTHING_DELETED
            ),
        )
