from collections.abc import Mapping
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.headers_collection import HeadersCollection
from mcp.types import InputRequiredResult
from msgraph.generated.models.todo_task import TodoTask
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared.calendar import zone_named
from office_365_mcp.shared.handles import task_handle
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
    day_of,
    list_audience,
    missing_time_refusal,
    named_in_question,
    no_due_date_to_repeat,
    read_task,
    repeat_refusal,
    spoken_fields,
    task_body,
    todo_request,
)
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Approval,
    Confirm,
    Question,
    Refusal,
    answer_pending,
    answered,
    approved_write,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_update_task"

PRESETS: tuple[str, ...] = ("outlook-tasks-write", "outlook-tasks-delete")

STEP_UPDATE = "update_task"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///tasks/AAMkAGI2SYNTHETIC-list-0001%3D/AAMkAGI2SYNTHETIC-task-0001%3D",
    "priority": "high",
}

_NOTHING_CHANGED = "Nothing was changed."
_CHANGE = "change"
_DO_NOT_CHANGE = "do not change"

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this task, and nothing was changed. The handle is well formed, "
    + "so this is not a bad argument. The task was most likely deleted, or moved to another "
    + "list, which gives it a new handle: find it again with outlook_list_tasks and take a fresh "
    + "`uri`. If its list was deleted or is no longer shared with the user, call "
    + f"outlook_list_task_lists again instead. {AGAIN}"
)

_DESCRIPTION = """\
Changes one Microsoft To Do task of the signed-in user, given the `uri` of an outlook_list_tasks \
row. This tool changes only the fields that the call gives, and keeps the other fields as they \
are. There is no draft and no review step. outlook_set_task_status marks a task done or reopens \
it.

Notes:
- `notes_html` replaces the whole notes of the task. To add to them, read the task with \
outlook_read_task first, and send its `notes` with the new words.
- This tool asks the user to agree before it changes a task in a list that other people share, \
because they see the change. A task in the user's own unshared list changes without a question.
- This call is safe to repeat after a timeout.
"""

_NOTHING_TO_CHANGE = (
    "outlook_update_task needs at least one field to change, besides `uri`. With none of them, "
    + f"there is nothing to change. {_NOTHING_CHANGED} Find out which change the user asked for, "
    + "and then call again."
)

_CLEARED = {
    "due_date": "due_date",
    "start_date": "start_date",
    "reminder_at": "reminder",
    "repeat": "repeat",
}


def _both(name: str) -> str:
    return (
        f"outlook_update_task takes either `{name}` or `clear_{_CLEARED[name]}`, not both: one "
        + f"sets the value and the other removes it. {_NOTHING_CHANGED} {AGAIN}"
    )


class TaskChange(TaskFields):
    clear_due_date: bool = False
    clear_start_date: bool = False
    clear_reminder: bool = False
    clear_repeat: bool = False

    @property
    def is_nothing(self) -> bool:
        return self.model_dump(exclude={"time_zone"}) == TaskChange().model_dump(
            exclude={"time_zone"}
        )

    def spoken(self, *, series_from: date | None) -> str:
        cleared = [
            *(["no due date"] if self.clear_due_date else []),
            *(["no start date"] if self.clear_start_date else []),
            *(["no reminder"] if self.clear_reminder else []),
            *(["no repeat"] if self.clear_repeat else []),
        ]
        return "; ".join([*spoken_fields(self, series_from=series_from), *cleared])

    def body(self, *, zone: ZoneInfo, series_from: date | None) -> TodoTask:
        body = task_body(self, zone=zone, series_from=series_from)
        for cleared, field in (
            (self.clear_due_date, "dueDateTime"),
            (self.clear_start_date, "startDateTime"),
            (self.clear_reminder, "reminderDateTime"),
            (self.clear_repeat, "recurrence"),
        ):
            if cleared:
                body.additional_data[field] = None
        if self.clear_reminder:
            body.is_reminder_on = False
        return body


def _refusal(change: TaskChange, zone: ZoneInfo) -> str | None:
    if change.is_nothing:
        return _NOTHING_TO_CHANGE
    for given, cleared, name in (
        (change.due_date is not None, change.clear_due_date, "due_date"),
        (change.start_date is not None, change.clear_start_date, "start_date"),
        (change.reminder_at is not None, change.clear_reminder, "reminder_at"),
        (change.repeat is not None, change.clear_repeat, "repeat"),
    ):
        if given and cleared:
            return _both(name)
    skipped = missing_time_refusal(
        TOOL_NAME, change.reminder_at, zone=zone, nothing_happened=_NOTHING_CHANGED
    )
    if skipped is not None:
        return skipped
    if change.repeat is not None:
        refusal = repeat_refusal(TOOL_NAME, change.repeat, nothing_happened=_NOTHING_CHANGED)
        if refusal is not None:
            return refusal
    if change.clear_due_date and change.repeat is not None:
        return no_due_date_to_repeat(TOOL_NAME, nothing_happened=_NOTHING_CHANGED)
    return None


async def update_task(
    client: GraphServiceClient,
    *,
    uri: str,
    change: TaskChange,
    confirm: Confirm,
    answer_pending: bool = False,
) -> TaskDetail | InputRequiredResult:
    handle = task_handle(uri)
    if handle is None:
        raise ToolError(
            bad_handle(TOOL_NAME, "task", argument="uri", nothing_happened=_NOTHING_CHANGED)
        )
    zone = zone_named(change.time_zone)
    if zone is None:
        raise ToolError(bad_zone(TOOL_NAME, nothing_happened=_NOTHING_CHANGED))
    refused = _refusal(change, zone)
    if refused is not None:
        raise ToolError(refused)
    needs_due = change.repeat is not None and change.due_date is None
    no_series = Refusal(no_due_date_to_repeat(TOOL_NAME, nothing_happened=_NOTHING_CHANGED))
    read: TodoTask | None = None

    def series_from(task: TodoTask | None) -> date | None:
        if not needs_due or task is None:
            return change.due_date
        return day_of(task.due_date_time, zone=zone)

    async def prepare(must_ask: bool) -> Question | Refusal | None:
        nonlocal read
        audience = await list_audience(client, handle.list_id)
        if not (must_ask or audience.reaches_others):
            return None
        read = await read_task(client, handle)
        first = series_from(read)
        if change.repeat is not None and first is None:
            return no_series
        named = named_in_question("task", read.title, missing="with no title")
        question = (
            f"Change {named} ({change.spoken(series_from=first)}) in {audience.named}?"
            + audience.sharing_note("see the change")
        )
        return Question(question, (audience.task_list, read), guarded=read)

    async def write(headers: HeadersCollection) -> TaskDetail | Refusal:
        task = read if read is not None or not needs_due else await read_task(client, handle)
        first = series_from(task)
        if change.repeat is not None and first is None:
            return no_series
        with graph_step(STEP_UPDATE):
            updated = (
                await client.me.todo.lists.by_todo_task_list_id(handle.list_id)
                .tasks.by_todo_task_id(handle.task_id)
                .patch(
                    change.body(zone=zone, series_from=first),
                    request_configuration=todo_request(
                        safe_to_repeat=False, task_times=True, headers=headers
                    ),
                )
            )
        assert updated is not None, "Graph answered a task update with no task"
        return TaskDetail.from_full_task(updated, list_id=handle.list_id, zone=zone)

    approval = Approval(TOOL_NAME, handle.uri, change, confirm, answer_pending, _NOTHING_CHANGED)
    with graph_errors():
        result = await approved_write(approval, prepare=prepare, write=write)
    return answered(result)


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
        ctx: Context,
        title: Annotated[
            str | None, Field(min_length=1, pattern=r"\S", description=TITLE_FIELD)
        ] = None,
        notes_html: Annotated[
            str | None, Field(min_length=1, pattern=r"\S", description=NOTES_HTML_FIELD)
        ] = None,
        due_date: Annotated[date | None, Field(description=DUE_DATE_FIELD)] = None,
        clear_due_date: Annotated[
            bool,
            Field(description="True to remove the due date. It cannot go with `due_date`."),
        ] = False,
        priority: Annotated[Priority | None, Field(description=PRIORITY_FIELD)] = None,
        start_date: Annotated[date | None, Field(description=START_DATE_FIELD)] = None,
        clear_start_date: Annotated[
            bool,
            Field(description="True to remove the start date. It cannot go with `start_date`."),
        ] = False,
        reminder_at: Annotated[datetime | None, Field(description=REMINDER_FIELD)] = None,
        clear_reminder: Annotated[
            bool,
            Field(description="True to turn the reminder off. It cannot go with `reminder_at`."),
        ] = False,
        repeat: Annotated[TaskRepeat | None, Field(description=REPEAT_FIELD)] = None,
        clear_repeat: Annotated[
            bool,
            Field(description="True to stop the task from repeating. It cannot go with `repeat`."),
        ] = False,
        categories: Annotated[list[str] | None, Field(description=CATEGORIES_FIELD)] = None,
        time_zone: Annotated[str, Field(min_length=1, description=TIME_ZONE_FIELD)] = (
            DEFAULT_TIME_ZONE
        ),
        client: GraphServiceClient = graph,
    ) -> TaskDetail | InputRequiredResult:
        return await update_task(
            client,
            uri=uri,
            change=TaskChange(
                title=title,
                notes_html=notes_html,
                due_date=due_date,
                clear_due_date=clear_due_date,
                priority=priority,
                start_date=start_date,
                clear_start_date=clear_start_date,
                reminder_at=reminder_at,
                clear_reminder=clear_reminder,
                repeat=repeat,
                clear_repeat=clear_repeat,
                categories=None if categories is None else tuple(categories),
                time_zone=time_zone,
            ),
            confirm=person_confirms(
                ctx, agree=_CHANGE, decline=_DO_NOT_CHANGE, nothing_happened=_NOTHING_CHANGED
            ),
            answer_pending=answer_pending(ctx),
        )
