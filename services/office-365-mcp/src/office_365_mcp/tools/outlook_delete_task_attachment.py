from collections.abc import Mapping
from typing import Annotated, Literal

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.shared.handles import TaskPartHandle, task_part_handle
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

TOOL_NAME = "outlook_delete_task_attachment"

PRESETS: tuple[str, ...] = ("outlook-tasks-delete",)

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

_EXAMPLE_HANDLE = TaskPartHandle(
    "attachments",
    "AAMkAGI2SYNTHETIC-list-0001=",
    "AAMkAGI2SYNTHETIC-task-0001=",
    "AAMkAGI2SYNTHETIC-attachment-0001=",
)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"attachment": _EXAMPLE_HANDLE.uri}


_NOTHING_DELETED = "The file was not deleted."
_AGREE = "delete the file"
_DECLINE = "keep the file"


_DESCRIPTION = """\
Deletes one file from a Microsoft To Do task of the signed-in user, given the `uri` of a row in \
the `attachments` of outlook_read_task.

Notes:
- This tool always asks the user to agree, and the question names the file and the task. This \
tool cannot get a deleted file back.
- This call is safe to repeat after a timeout. A second call finds no file and answers \
`not_found`.
"""


Outcome = Literal["deleted", "not_found"]


class DeletedTaskAttachment(BaseModel):
    name: str | None = Field(
        description=(
            "The file name, as Microsoft 365 reported it immediately before the delete. Null when "
            + "the file had none, or when Microsoft 365 found no file to read."
        )
    )
    outcome: Outcome = Field(
        description=(
            "What this call did. `deleted`: Microsoft 365 accepted the delete, and this call "
            + "deleted the file. `not_found`: Microsoft 365 found no such file, before the "
            + "question or at the delete. The file was deleted before, or the user cannot see "
            + "it now. This call deleted nothing. When the value is `not_found`, do not tell the "
            + "user that this call deleted the file."
        )
    )


async def delete_task_attachment(
    client: GraphServiceClient, *, attachment: str, confirm: Confirm, answer_pending: bool = False
) -> DeletedTaskAttachment | InputRequiredResult:
    handle = task_part_handle("attachments", attachment)
    if handle is None:
        raise ToolError(
            bad_handle(TOOL_NAME, "file", argument="attachment", nothing_happened=_NOTHING_DELETED)
        )
    approval = Approval(
        TOOL_NAME, handle.uri, Deletion(), confirm, answer_pending, _NOTHING_DELETED
    )
    removed = answered(await delete_todo_item(client, handle, approval=approval))
    if isinstance(removed, InputRequiredResult):
        return removed
    return DeletedTaskAttachment(name=removed.name, outcome=removed.outcome)


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
            answer_pending=answer_pending(ctx),
        )
