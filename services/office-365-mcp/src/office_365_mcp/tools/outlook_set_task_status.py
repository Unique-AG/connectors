from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.todo_task import TodoTask
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.calendar import zone_named
from office_365_mcp.shared.confirmation import write_state_for
from office_365_mcp.shared.handles import task_handle
from office_365_mcp.shared.outlook.tasks import (
    DEFAULT_TIME_ZONE,
    TIME_ZONE_FIELD,
    Status,
    TaskDetail,
    bad_task_handle,
    bad_zone,
    graph_status,
    list_audience,
    shared_list_reason,
)
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    answer_pending,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_set_task_status"

PRESETS: tuple[str, ...] = ("outlook-tasks-write", "outlook-tasks-delete")

STEP_SET_STATUS = "set_task_status"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///tasks/AAMkAGI2SYNTHETIC-list-0001%3D/AAMkAGI2SYNTHETIC-task-0001%3D",
    "status": "completed",
}

_NOTHING_CHANGED = "Nothing was changed."
_CHANGE = "change the status"
_DO_NOT_CHANGE = "keep the status"

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this task, and nothing was changed. The handle is well formed, "
    + "so this is not a bad argument. The task was most likely deleted, or moved to another "
    + "list, which gives it a new handle: find it again with outlook_list_tasks and take a fresh "
    + "`uri`. If its list was deleted or is no longer shared with the user, call "
    + f"outlook_list_task_lists again instead. {_AGAIN}"
)

_DESCRIPTION = """\
Sets the status of one Microsoft To Do task of the signed-in user, given the `uri` of an \
outlook_list_tasks row. `completed` marks the task done, and `not_started` reopens it. Outlook \
and To Do show the new status.

Notes:
- When the user completes a repeating task, To Do makes the next task of the series.
- This tool asks the user to agree before it changes a task in a list that other people share, \
because they see the change. A task in the user's own unshared list changes without a question.
- This call is safe to repeat after a timeout.
"""

_SPOKEN: Mapping[Status, str] = {
    "not_started": "not started",
    "in_progress": "in progress",
    "completed": "completed",
    "waiting_on_others": "waiting on others",
    "deferred": "deferred",
}


async def set_task_status(
    client: GraphServiceClient,
    *,
    uri: str,
    status: Status,
    time_zone: str = DEFAULT_TIME_ZONE,
    confirm: Confirm,
    answer_pending: bool = False,
) -> TaskDetail | InputRequiredResult:
    handle = task_handle(uri)
    if handle is None:
        raise ToolError(bad_task_handle(TOOL_NAME, nothing_happened=_NOTHING_CHANGED))
    zone = zone_named(time_zone)
    if zone is None:
        raise ToolError(bad_zone(TOOL_NAME, nothing_happened=_NOTHING_CHANGED))

    about = write_state_for(STEP_SET_STATUS, handle.uri, status)

    updated: TodoTask | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors():
        audience = await list_audience(client, handle.list_id)
        if answer_pending or audience.reaches_others:
            with not_graph():
                question = f"Set a task to {_SPOKEN[status]} {shared_list_reason(audience)}?"
                answer = await confirm(question, about)
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_SET_STATUS):
                updated = (
                    await client.me.todo.lists.by_todo_task_list_id(handle.list_id)
                    .tasks.by_todo_task_id(handle.task_id)
                    .patch(
                        TodoTask(status=graph_status(status)),
                        request_configuration=RequestConfiguration[QueryParameters](
                            options=no_retry()
                        ),
                    )
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert updated is not None, "Graph answered a task update with no task"
    return TaskDetail.from_full_task(updated, list_id=handle.list_id, zone=zone)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Set the Status of a Task",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_set_task_status(
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
        status: Annotated[
            Status,
            Field(
                description=(
                    "The new status: `not_started`, `in_progress`, `waiting_on_others`, "
                    + "`deferred`, or `completed`. To Do shows `completed` as done and every "
                    + "other status as open."
                )
            ),
        ],
        ctx: Context,
        time_zone: Annotated[str, Field(min_length=1, description=TIME_ZONE_FIELD)] = (
            DEFAULT_TIME_ZONE
        ),
        client: GraphServiceClient = graph,
    ) -> TaskDetail | InputRequiredResult:
        return await set_task_status(
            client,
            uri=uri,
            status=status,
            time_zone=time_zone,
            confirm=person_confirms(
                ctx, agree=_CHANGE, decline=_DO_NOT_CHANGE, nothing_happened=_NOTHING_CHANGED
            ),
            answer_pending=answer_pending(ctx),
        )
