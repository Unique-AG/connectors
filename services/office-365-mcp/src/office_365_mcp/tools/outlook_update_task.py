from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Annotated

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from msgraph.generated.models.todo_task import TodoTask
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry
from office_365_mcp.shared.calendar import zone_named
from office_365_mcp.shared.handles import task_handle
from office_365_mcp.shared.outlook.tasks import (
    BODY_FIELD,
    DEFAULT_TIME_ZONE,
    DUE_DATE_FIELD,
    PRIORITY_FIELD,
    TIME_ZONE_FIELD,
    TITLE_FIELD,
    Priority,
    Status,
    TaskDetail,
    bad_task_handle,
    bad_zone,
    due_moment,
    graph_importance,
    graph_status,
    html_body,
)
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, graph_client_for_caller

TOOL_NAME = "outlook_update_task"

PRESETS: tuple[str, ...] = ("outlook-tasks-write",)

STEP_UPDATE = "update_task"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///tasks/AAMkAGI2SYNTHETIC-list-0001%3D/AAMkAGI2SYNTHETIC-task-0001%3D",
    "priority": "high",
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
Changes one Microsoft To Do task of the signed-in user, given the `uri` of an outlook_list_tasks \
row. This tool changes only the fields that the call gives, and keeps the other fields as they \
are. There is no draft and no review step. The task is in the user's own To Do, so this tool does \
not ask anybody to agree. outlook_complete_task marks a task done.

Notes:
- `notes` replaces the whole notes of the task. To add to them, read the task with \
outlook_read_task first and send the old notes with the new words.
- To reopen a completed task, pass `status="not_started"`.
- In a list that is shared, every person who shares it sees the change.
- This call is safe to repeat after a timeout.
"""

_NOTHING_TO_CHANGE = (
    "outlook_update_task needs at least one field to change, besides `uri`. With none of them, "
    + f"there is nothing to change. {_NOTHING_CHANGED} Find out which change the user asked for, "
    + "and then call again."
)

_DUE_DATE_AND_CLEAR = (
    "outlook_update_task takes either `due_date` or `clear_due_date`, not both: one sets a due "
    + f"date and the other removes it. {_NOTHING_CHANGED} {_AGAIN}"
)


@dataclass(frozen=True, slots=True)
class TaskChange:
    title: str | None = None
    notes: str | None = None
    due_date: date | None = None
    clear_due_date: bool = False
    priority: Priority | None = None
    status: Status | None = None

    @property
    def is_nothing(self) -> bool:
        return self == TaskChange()


async def update_task(
    client: GraphServiceClient,
    *,
    uri: str,
    change: TaskChange,
    time_zone: str = DEFAULT_TIME_ZONE,
) -> TaskDetail:
    handle = task_handle(uri)
    if handle is None:
        raise ToolError(bad_task_handle(TOOL_NAME, nothing_happened=_NOTHING_CHANGED))
    zone = zone_named(time_zone)
    if zone is None:
        raise ToolError(bad_zone(TOOL_NAME, nothing_happened=_NOTHING_CHANGED))
    if change.is_nothing:
        raise ToolError(_NOTHING_TO_CHANGE)
    if change.due_date is not None and change.clear_due_date:
        raise ToolError(_DUE_DATE_AND_CLEAR)

    body = TodoTask(
        title=change.title,
        body=None if change.notes is None else html_body(change.notes),
        due_date_time=None if change.due_date is None else due_moment(change.due_date, zone=zone),
        importance=None if change.priority is None else graph_importance(change.priority),
        status=None if change.status is None else graph_status(change.status),
    )
    if change.clear_due_date:
        body.additional_data["dueDateTime"] = None

    with graph_errors(), graph_step(STEP_UPDATE):
        updated = (
            await client.me.todo.lists.by_todo_task_list_id(handle.list_id)
            .tasks.by_todo_task_id(handle.task_id)
            .patch(
                body,
                request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
            )
        )

    assert updated is not None, "Graph answered a task update with no task"
    return TaskDetail.from_full_task(updated, list_id=handle.list_id, zone=zone)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Update a Task",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_update_task(
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
        title: Annotated[
            str | None, Field(min_length=1, pattern=r"\S", description=TITLE_FIELD)
        ] = None,
        notes: Annotated[
            str | None, Field(min_length=1, pattern=r"\S", description=BODY_FIELD)
        ] = None,
        due_date: Annotated[date | None, Field(description=DUE_DATE_FIELD)] = None,
        clear_due_date: Annotated[
            bool,
            Field(description="True to remove the due date. It cannot go with `due_date`."),
        ] = False,
        priority: Annotated[Priority | None, Field(description=PRIORITY_FIELD)] = None,
        status: Annotated[
            Status | None,
            Field(
                description=(
                    "Where the task stands: `not_started`, `in_progress`, `waiting_on_others`, "
                    + "`deferred`, or `completed`. Pass `not_started` to reopen a completed task."
                )
            ),
        ] = None,
        time_zone: Annotated[str, Field(min_length=1, description=TIME_ZONE_FIELD)] = (
            DEFAULT_TIME_ZONE
        ),
        client: GraphServiceClient = graph,
    ) -> TaskDetail:
        return await update_task(
            client,
            uri=uri,
            change=TaskChange(
                title=title,
                notes=notes,
                due_date=due_date,
                clear_due_date=clear_due_date,
                priority=priority,
                status=status,
            ),
            time_zone=time_zone,
        )
