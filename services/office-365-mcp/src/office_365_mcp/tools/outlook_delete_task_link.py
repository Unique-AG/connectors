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

TOOL_NAME = "outlook_delete_task_link"

PRESETS: tuple[str, ...] = ("outlook-tasks-delete",)

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

_EXAMPLE_HANDLE = TaskPartHandle(
    "links", "AAMkAGI2SYNTHETIC-list-0001=", "AAMkAGI2SYNTHETIC-task-0001=", "SYNTHETIC-link-0001"
)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"link": _EXAMPLE_HANDLE.uri}


_NOTHING_DELETED = "The link was not deleted."
_AGREE = "delete the link"
_DECLINE = "keep the link"


_DESCRIPTION = """\
Deletes one link from a Microsoft To Do task of the signed-in user, given the `uri` of a row in \
the `links` of outlook_read_task. The item that the link opens does not change.

Notes:
- This tool always asks the user to agree, and the question names the link, its address, and \
the task.
- This call is safe to repeat after a timeout. A second call finds no link and answers \
`not_found`.
"""


Outcome = Literal["deleted", "not_found"]


class DeletedTaskLink(BaseModel):
    title: str | None = Field(
        description=(
            "The words that To Do showed for the link, as Microsoft 365 reported them immediately "
            + "before the delete. Null when the link had none, or when Microsoft 365 found no "
            + "link to read."
        )
    )
    outcome: Outcome = Field(
        description=(
            "What this call did. `deleted`: Microsoft 365 accepted the delete, and this call "
            + "deleted the link. `not_found`: Microsoft 365 found no such link, before the "
            + "question or at the delete. The link was deleted before, or the user cannot see "
            + "it now. This call deleted nothing. When the value is `not_found`, do not tell the "
            + "user that this call deleted the link."
        )
    )


async def delete_task_link(
    client: GraphServiceClient, *, link: str, confirm: Confirm, answer_pending: bool = False
) -> DeletedTaskLink | InputRequiredResult:
    handle = task_part_handle("links", link)
    if handle is None:
        raise ToolError(
            bad_handle(TOOL_NAME, "link", argument="link", nothing_happened=_NOTHING_DELETED)
        )
    approval = Approval(
        TOOL_NAME, handle.uri, Deletion(), confirm, answer_pending, _NOTHING_DELETED
    )
    removed = answered(await delete_todo_item(client, handle, approval=approval))
    if isinstance(removed, InputRequiredResult):
        return removed
    return DeletedTaskLink(title=removed.name, outcome=removed.outcome)


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
            answer_pending=answer_pending(ctx),
        )
