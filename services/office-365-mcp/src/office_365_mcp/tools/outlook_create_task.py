from collections.abc import Mapping
from datetime import date, datetime
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.headers_collection import HeadersCollection
from mcp.types import InputRequiredResult
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared.calendar import zone_named
from office_365_mcp.shared.handles import task_list_handle
from office_365_mcp.shared.outlook.tasks import (
    AGAIN,
    CATEGORIES_FIELD,
    DEFAULT_TIME_ZONE,
    DUE_DATE_FIELD,
    NOTES_HTML_FIELD,
    PRIORITY_FIELD,
    REMINDER_FIELD,
    REPEAT_FIELD,
    START_DATE_FIELD,
    TIME_ZONE_FIELD,
    TITLE_FIELD,
    Priority,
    TaskDetail,
    TaskFields,
    TaskRepeat,
    bad_handle,
    bad_zone,
    list_audience,
    missing_time_refusal,
    no_due_date_to_repeat,
    repeat_refusal,
    spoken_fields,
    task_body,
    todo_request,
)
from office_365_mcp.shared.seam import (
    WRITE_ADDITIVE,
    Approval,
    Confirm,
    Question,
    answer_pending,
    answered,
    approved_write,
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

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find this task list, and no task was created. The handle is well "
    + "formed, so this is not a bad argument. The list was most likely deleted, or its owner "
    + "stopped sharing it. Call outlook_list_task_lists again and take a fresh `uri`. "
    + AGAIN
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
"""


async def create_task(
    client: GraphServiceClient,
    *,
    task_list: str,
    fields: TaskFields,
    confirm: Confirm,
    answer_pending: bool = False,
) -> TaskDetail | InputRequiredResult:
    handle = task_list_handle(task_list)
    if handle is None:
        raise ToolError(
            bad_handle(
                TOOL_NAME, "task list", argument="task_list", nothing_happened=_NOTHING_CREATED
            )
        )
    assert fields.title, "outlook_create_task takes a title, and its schema requires one"
    zone = zone_named(fields.time_zone)
    if zone is None:
        raise ToolError(bad_zone(TOOL_NAME, nothing_happened=_NOTHING_CREATED))
    skipped = missing_time_refusal(
        TOOL_NAME, fields.reminder_at, zone=zone, nothing_happened=_NOTHING_CREATED
    )
    if skipped is not None:
        raise ToolError(skipped)
    if fields.repeat is not None:
        refusal = repeat_refusal(TOOL_NAME, fields.repeat, nothing_happened=_NOTHING_CREATED)
        if refusal is not None:
            raise ToolError(refusal)
        if fields.due_date is None:
            raise ToolError(no_due_date_to_repeat(TOOL_NAME, nothing_happened=_NOTHING_CREATED))

    async def prepare(must_ask: bool) -> Question | None:
        audience = await list_audience(client, handle.list_id)
        if not (must_ask or audience.reaches_others):
            return None
        spoken = "; ".join(spoken_fields(fields, series_from=fields.due_date))
        question = f"Create a task in {audience.named} ({spoken})?" + audience.sharing_note(
            "see the new task"
        )
        return Question(question, (audience.task_list,))

    async def write(headers: HeadersCollection) -> TaskDetail:
        with graph_step(STEP_CREATE):
            created = await client.me.todo.lists.by_todo_task_list_id(handle.list_id).tasks.post(
                task_body(fields, zone=zone, series_from=fields.due_date),
                request_configuration=todo_request(
                    safe_to_repeat=False, task_times=True, headers=headers
                ),
            )
        assert created is not None, "Graph answered a task create with no task"
        return TaskDetail.from_full_task(created, list_id=handle.list_id, zone=zone)

    approval = Approval(TOOL_NAME, handle.uri, fields, confirm, answer_pending, _NOTHING_CREATED)
    with graph_errors():
        result = await approved_write(approval, prepare=prepare, write=write)
    return answered(result)


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
        notes_html: Annotated[
            str | None, Field(min_length=1, pattern=r"\S", description=NOTES_HTML_FIELD)
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
            fields=TaskFields(
                title=title,
                notes_html=notes_html,
                due_date=due_date,
                priority=priority,
                start_date=start_date,
                reminder_at=reminder_at,
                repeat=repeat,
                categories=None if categories is None else tuple(categories),
                time_zone=time_zone,
            ),
            confirm=person_confirms(
                ctx, agree=_CREATE, decline=_DO_NOT_CREATE, nothing_happened=_NOTHING_CREATED
            ),
            answer_pending=answer_pending(ctx),
        )
