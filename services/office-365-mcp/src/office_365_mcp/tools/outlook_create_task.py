from collections.abc import Mapping
from datetime import date, datetime
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
from office_365_mcp.shared.handles import task_list_handle
from office_365_mcp.shared.outlook.tasks import (
    BODY_FIELD,
    CATEGORIES_FIELD,
    DEFAULT_TIME_ZONE,
    DUE_DATE_FIELD,
    PRIORITY_FIELD,
    REMINDER_FIELD,
    REPEAT_FIELD,
    START_DATE_FIELD,
    TIME_ZONE_FIELD,
    TITLE_FIELD,
    Priority,
    TaskDetail,
    TaskRepeat,
    bad_zone,
    due_moment,
    graph_importance,
    html_body,
    list_audience,
    moment_in,
    no_due_date_to_repeat,
    recurrence_for,
    repeat_refusal,
    shared_list_reason,
)
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Confirm,
    answer_pending,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_create_task"

PRESETS: tuple[str, ...] = ("outlook-tasks-write", "outlook-tasks-delete")

STEP_CREATE = "create_task"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("outlook_list_tasks",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "task_list": "outlook:///tasklists/AAMkAGI2SYNTHETIC-list-0001%3D",
    "title": "Synthetic task",
}

_NOTHING_CREATED = "No task was created."
_CREATE = "create"
_DO_NOT_CREATE = "do not create"

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
outlook_update_task changes a task later, and outlook_set_task_status marks it done.

Notes:
- If a call times out, do not call this tool again first. Before you call again, make sure that \
outlook_list_tasks does not show the new task.
- This tool asks the user to agree before it writes into a list that other people share, \
because they see the new task. A task in the user's own unshared list is written without a \
question.
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
    start_date: date | None = None,
    reminder_at: datetime | None = None,
    repeat: TaskRepeat | None = None,
    categories: list[str] | None = None,
    time_zone: str = DEFAULT_TIME_ZONE,
    confirm: Confirm,
    answer_pending: bool = False,
) -> TaskDetail | InputRequiredResult:
    handle = task_list_handle(task_list)
    if handle is None:
        raise ToolError(_NOT_A_LIST_HANDLE)
    zone = zone_named(time_zone)
    if zone is None:
        raise ToolError(bad_zone(TOOL_NAME, nothing_happened=_NOTHING_CREATED))
    if repeat is not None:
        refusal = repeat_refusal(TOOL_NAME, repeat, nothing_happened=_NOTHING_CREATED)
        if refusal is not None:
            raise ToolError(refusal)
        if due_date is None:
            raise ToolError(no_due_date_to_repeat(TOOL_NAME, nothing_happened=_NOTHING_CREATED))
    body = TodoTask(
        title=title,
        body=None if notes is None else html_body(notes),
        due_date_time=None if due_date is None else due_moment(due_date, zone=zone),
        importance=None if priority is None else graph_importance(priority),
        start_date_time=None if start_date is None else due_moment(start_date, zone=zone),
        reminder_date_time=None if reminder_at is None else moment_in(reminder_at, zone=zone),
        is_reminder_on=None if reminder_at is None else True,
        recurrence=(
            None if repeat is None or due_date is None else recurrence_for(repeat, due=due_date)
        ),
        categories=categories,
    )

    about = write_state_for(
        STEP_CREATE,
        handle.uri,
        title,
        notes or "",
        "" if due_date is None else due_date.isoformat(),
        priority or "",
        "" if start_date is None else start_date.isoformat(),
        "" if reminder_at is None else reminder_at.isoformat(),
        "" if repeat is None else repeat.model_dump_json(),
        "" if categories is None else "\n".join(categories),
        time_zone,
    )

    created: TodoTask | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors():
        audience = await list_audience(client, handle.list_id)
        if answer_pending or audience.reaches_others:
            with not_graph():
                answer = await confirm(
                    f"Create the task {title!r} {shared_list_reason(audience)}?", about
                )
            asked = answer if isinstance(answer, InputRequiredResult) else None
            refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_CREATE):
                created = await client.me.todo.lists.by_todo_task_list_id(
                    handle.list_id
                ).tasks.post(
                    body,
                    request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
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
        ctx: Context,
        notes: Annotated[
            str | None, Field(min_length=1, pattern=r"\S", description=BODY_FIELD)
        ] = None,
        due_date: Annotated[date | None, Field(description=DUE_DATE_FIELD)] = None,
        priority: Annotated[Priority | None, Field(description=PRIORITY_FIELD)] = None,
        start_date: Annotated[date | None, Field(description=START_DATE_FIELD)] = None,
        reminder_at: Annotated[datetime | None, Field(description=REMINDER_FIELD)] = None,
        repeat: Annotated[TaskRepeat | None, Field(description=REPEAT_FIELD)] = None,
        categories: Annotated[list[str] | None, Field(description=CATEGORIES_FIELD)] = None,
        time_zone: Annotated[str, Field(min_length=1, description=TIME_ZONE_FIELD)] = (
            DEFAULT_TIME_ZONE
        ),
        client: GraphServiceClient = graph,
    ) -> TaskDetail | InputRequiredResult:
        return await create_task(
            client,
            task_list=task_list,
            title=title,
            notes=notes,
            due_date=due_date,
            priority=priority,
            start_date=start_date,
            reminder_at=reminder_at,
            repeat=repeat,
            categories=categories,
            time_zone=time_zone,
            confirm=person_confirms(
                ctx, agree=_CREATE, decline=_DO_NOT_CREATE, nothing_happened=_NOTHING_CREATED
            ),
            answer_pending=answer_pending(ctx),
        )
