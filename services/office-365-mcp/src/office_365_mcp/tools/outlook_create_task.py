from collections.abc import Mapping
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
from office_365_mcp.shared.handles import task_list_handle
from office_365_mcp.shared.outlook.tasks import (
    BODY_FIELD,
    DEFAULT_TIME_ZONE,
    DUE_DATE_FIELD,
    PRIORITY_FIELD,
    TIME_ZONE_FIELD,
    TITLE_FIELD,
    Priority,
    TaskDetail,
    bad_zone,
    due_moment,
    graph_importance,
    html_body,
)
from office_365_mcp.shared.seam import WRITE_ADDITIVE, graph_client_for_caller

TOOL_NAME = "outlook_create_task"

PRESETS: tuple[str, ...] = ("outlook-tasks-write",)

STEP_CREATE = "create_task"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("outlook_list_tasks",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "task_list": "outlook:///tasklists/AAMkAGI2SYNTHETIC-list-0001%3D",
    "title": "Synthetic task",
}

_NOTHING_CREATED = "No task was created."

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find this task list, and no task was created. The handle is well "
    + "formed, so this is not a bad argument. The list was most likely deleted, or its owner "
    + "stopped sharing it. Call outlook_list_task_lists again and take a fresh `uri`. "
    + _AGAIN
)

_DESCRIPTION = """\
Creates one new task in a Microsoft To Do task list of the signed-in user, given the `uri` of an \
outlook_list_task_lists row. Outlook shows the same task. There is no draft and no review step. \
The task goes into the user's own To Do, so this tool does not ask anybody to agree. \
outlook_update_task changes a task later, and outlook_complete_task marks it done.

Notes:
- If a call times out, do not call this tool again first. Before you call again, make sure that \
outlook_list_tasks does not show the new task.
- In a list that is shared, every person who shares it sees the new task.
- The built-in list of flagged messages can refuse a new task. Use the Tasks list instead.
"""

_NOT_A_LIST_HANDLE = (
    "outlook_create_task takes the `uri` of a task list in `task_list`, and this is not one. "
    + "Take the `uri` of a row that outlook_list_task_lists returned, and copy it word for word. "
    + "A task list handle looks like outlook:///tasklists/AAMkAGI2SYNTHETIC-list-0001%3D. A list "
    + f"name is not a handle. {_NOTHING_CREATED} {_AGAIN}"
)


async def create_task(
    client: GraphServiceClient,
    *,
    task_list: str,
    title: str,
    notes: str | None = None,
    due_date: date | None = None,
    priority: Priority | None = None,
    time_zone: str = DEFAULT_TIME_ZONE,
) -> TaskDetail:
    handle = task_list_handle(task_list)
    if handle is None:
        raise ToolError(_NOT_A_LIST_HANDLE)
    zone = zone_named(time_zone)
    if zone is None:
        raise ToolError(bad_zone(TOOL_NAME, nothing_happened=_NOTHING_CREATED))
    body = TodoTask(
        title=title,
        body=None if notes is None else html_body(notes),
        due_date_time=None if due_date is None else due_moment(due_date, zone=zone),
        importance=None if priority is None else graph_importance(priority),
    )

    with graph_errors(), graph_step(STEP_CREATE):
        created = await client.me.todo.lists.by_todo_task_list_id(handle.list_id).tasks.post(
            body,
            request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
        )

    assert created is not None, "Graph answered a task create with no task"
    return TaskDetail.from_full_task(created, list_id=handle.list_id, zone=zone)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Create a Task",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def outlook_create_task(
        task_list: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the list for the new task, from the `uri` of an "
                    + "outlook_list_task_lists row. Copy it word for word."
                ),
            ),
        ],
        title: Annotated[str, Field(min_length=1, pattern=r"\S", description=TITLE_FIELD)],
        notes: Annotated[
            str | None, Field(min_length=1, pattern=r"\S", description=BODY_FIELD)
        ] = None,
        due_date: Annotated[date | None, Field(description=DUE_DATE_FIELD)] = None,
        priority: Annotated[Priority | None, Field(description=PRIORITY_FIELD)] = None,
        time_zone: Annotated[str, Field(min_length=1, description=TIME_ZONE_FIELD)] = (
            DEFAULT_TIME_ZONE
        ),
        client: GraphServiceClient = graph,
    ) -> TaskDetail:
        return await create_task(
            client,
            task_list=task_list,
            title=title,
            notes=notes,
            due_date=due_date,
            priority=priority,
            time_zone=time_zone,
        )
