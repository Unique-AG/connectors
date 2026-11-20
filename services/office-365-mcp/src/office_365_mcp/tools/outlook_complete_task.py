from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from msgraph.generated.models.task_status import TaskStatus
from msgraph.generated.models.todo_task import TodoTask
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry
from office_365_mcp.shared.calendar import zone_named
from office_365_mcp.shared.handles import task_handle
from office_365_mcp.shared.outlook.tasks import (
    DEFAULT_TIME_ZONE,
    TIME_ZONE_FIELD,
    TaskDetail,
    bad_task_handle,
    bad_zone,
)
from office_365_mcp.shared.seam import WRITE_IDEMPOTENT, graph_client_for_caller

TOOL_NAME = "outlook_complete_task"

PRESETS: tuple[str, ...] = ("outlook-tasks-write",)

STEP_COMPLETE = "complete_task"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///tasks/AAMkAGI2SYNTHETIC-list-0001%3D/AAMkAGI2SYNTHETIC-task-0001%3D"
}

_NOTHING_CHANGED = "Nothing was changed."

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this task, and nothing was changed. The handle is well formed, "
    + "so this is not a bad argument. The task was most likely deleted, or moved to another "
    + "list, which gives it a new handle. Find it again with outlook_list_tasks and take a fresh "
    + f"`uri`. {_AGAIN}"
)

_DESCRIPTION = """\
Marks one Microsoft To Do task of the signed-in user as completed, given the `uri` of an \
outlook_list_tasks row. Outlook and To Do then show the task as done. The task is in the user's \
own To Do, so this tool does not ask anybody to agree.

Notes:
- To reopen a completed task, call outlook_update_task with `status="not_started"`.
- This call is safe to repeat after a timeout.
"""


async def complete_task(
    client: GraphServiceClient, *, uri: str, time_zone: str = DEFAULT_TIME_ZONE
) -> TaskDetail:
    handle = task_handle(uri)
    if handle is None:
        raise ToolError(bad_task_handle(TOOL_NAME, nothing_happened=_NOTHING_CHANGED))
    zone = zone_named(time_zone)
    if zone is None:
        raise ToolError(bad_zone(TOOL_NAME, nothing_happened=_NOTHING_CHANGED))

    with graph_errors(), graph_step(STEP_COMPLETE):
        updated = (
            await client.me.todo.lists.by_todo_task_list_id(handle.list_id)
            .tasks.by_todo_task_id(handle.task_id)
            .patch(
                TodoTask(status=TaskStatus.Completed),
                request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
            )
        )

    assert updated is not None, "Graph answered a task update with no task"
    return TaskDetail.from_full_task(updated, list_id=handle.list_id, zone=zone)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Complete a Task",
        description=_DESCRIPTION,
        annotations=WRITE_IDEMPOTENT,
    )
    async def outlook_complete_task(
        uri: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the task, from the `uri` of an outlook_list_tasks row. Copy "
                    + "it word for word."
                ),
            ),
        ],
        time_zone: Annotated[str, Field(min_length=1, description=TIME_ZONE_FIELD)] = (
            DEFAULT_TIME_ZONE
        ),
        client: GraphServiceClient = graph,
    ) -> TaskDetail:
        return await complete_task(client, uri=uri, time_zone=time_zone)
