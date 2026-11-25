import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.todo_task import TodoTask
from msgraph.generated.users.item.todo.lists.item.tasks.item.todo_task_item_request_builder import (  # noqa: E501
    TodoTaskItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.calendar import zone_named
from office_365_mcp.shared.confirmation import write_state_for
from office_365_mcp.shared.handles import TaskHandle, task_handle
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
    bad_task_handle,
    bad_zone,
    day_of,
    due_moment,
    graph_importance,
    html_body,
    list_audience,
    missing_time_refusal,
    moment_in,
    no_due_date_to_repeat,
    recurrence_for,
    repeat_refusal,
    shared_list_reason,
    task_for_a_question,
    utc_times,
)
from office_365_mcp.shared.prose import body_opening, cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    answer_pending,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_update_task"

PRESETS: tuple[str, ...] = ("outlook-tasks-write", "outlook-tasks-delete")

STEP_UPDATE = "update_task"

STEP_DUE_DATE = "task_due_date"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///tasks/AAMkAGI2SYNTHETIC-list-0001%3D/AAMkAGI2SYNTHETIC-task-0001%3D",
    "priority": "high",
}

_NOTHING_CHANGED = "Nothing was changed."
_CHANGE = "change"
_DO_NOT_CHANGE = "do not change"

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this task, and nothing was changed. The handle is well formed, "
    + "so this is not a bad argument. The task was most likely deleted, or moved to another "
    + "list, which gives it a new handle: find it again with outlook_list_tasks and take a fresh "
    + "`uri`. If its list was deleted or is no longer shared with the user, call "
    + f"outlook_list_task_lists again instead. {_AGAIN}"
)

_DESCRIPTION = """\
Changes one Microsoft To Do task of the signed-in user, given the `uri` of an outlook_list_tasks \
row. This tool changes only the fields that the call gives, and keeps the other fields as they \
are. There is no draft and no review step. outlook_set_task_status marks a task done or reopens \
it.

Notes:
- `notes` replaces the whole notes of the task. To add to them, read the task with \
outlook_read_task first. If `notes_format` is `html`, write the old notes again as Markdown, \
without HTML tags, because `notes` shows a tag as text. Then send the old notes with the new \
words.
- This tool asks the user to agree before it changes a task in a list that other people share, \
because they see the change. A task in the user's own unshared list changes without a question.
- This call is safe to repeat after a timeout.
"""

_TaskQuery = TodoTaskItemRequestBuilder.TodoTaskItemRequestBuilderGetQueryParameters

_NOTHING_TO_CHANGE = (
    "outlook_update_task needs at least one field to change, besides `uri`. With none of them, "
    + f"there is nothing to change. {_NOTHING_CHANGED} Find out which change the user asked for, "
    + "and then call again."
)


def _changes(change: TaskChange, *, series_from: date | None) -> str:
    parts = [
        *([f"title {cut_for_a_question(change.title)!r}"] if change.title else []),
        *([f"notes that open with {body_opening(change.notes)!r}"] if change.notes else []),
        *([f"due {change.due_date}"] if change.due_date else []),
        *(["no due date"] if change.clear_due_date else []),
        *([f"start {change.start_date}"] if change.start_date else []),
        *(["no start date"] if change.clear_start_date else []),
        *([f"reminder {change.reminder_at.isoformat()}"] if change.reminder_at else []),
        *(["no reminder"] if change.clear_reminder else []),
        *([f"{_series(change.repeat)} from {series_from}"] if change.repeat else []),
        *(["no repeat"] if change.clear_repeat else []),
        *([f"priority {change.priority}"] if change.priority else []),
        *(
            [f"categories {cut_for_a_question(', '.join(change.categories))!r}"]
            if change.categories
            else []
        ),
        *(["no categories"] if change.categories == () else []),
    ]
    return "; ".join(parts)


def _series(repeat: TaskRepeat) -> str:
    every = (
        f"every {repeat.every}"
        if repeat.interval == 1
        else f"every {repeat.interval} {repeat.every}s"
    )
    days = f" on {', '.join(repeat.weekdays)}" if repeat.weekdays else ""
    return f"repeats {every}{days}"


def _both(name: str) -> str:
    return (
        f"outlook_update_task takes either `{name}` or `clear_{_CLEARED[name]}`, not both: one "
        + f"sets the value and the other removes it. {_NOTHING_CHANGED} {_AGAIN}"
    )


_CLEARED = {
    "due_date": "due_date",
    "start_date": "start_date",
    "reminder_at": "reminder",
    "repeat": "repeat",
}


async def _due_date(
    client: GraphServiceClient, handle: TaskHandle, *, zone: ZoneInfo
) -> date | None:
    with graph_step(STEP_DUE_DATE):
        task = (
            await client.me.todo.lists.by_todo_task_list_id(handle.list_id)
            .tasks.by_todo_task_id(handle.task_id)
            .get(
                request_configuration=RequestConfiguration[_TaskQuery](
                    headers=utc_times(), query_parameters=_TaskQuery(select=["id", "dueDateTime"])
                )
            )
        )
    assert task is not None, "Graph answered a task read with no task"
    return day_of(task.due_date_time, zone=zone)


@dataclass(frozen=True, slots=True)
class TaskChange:
    title: str | None = None
    notes: str | None = None
    due_date: date | None = None
    clear_due_date: bool = False
    priority: Priority | None = None
    start_date: date | None = None
    clear_start_date: bool = False
    reminder_at: datetime | None = None
    clear_reminder: bool = False
    repeat: TaskRepeat | None = None
    clear_repeat: bool = False
    categories: tuple[str, ...] | None = None

    @property
    def is_nothing(self) -> bool:
        return self == TaskChange()


async def update_task(
    client: GraphServiceClient,
    *,
    uri: str,
    change: TaskChange,
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
    if change.is_nothing:
        raise ToolError(_NOTHING_TO_CHANGE)
    for given, cleared, name in (
        (change.due_date is not None, change.clear_due_date, "due_date"),
        (change.start_date is not None, change.clear_start_date, "start_date"),
        (change.reminder_at is not None, change.clear_reminder, "reminder_at"),
        (change.repeat is not None, change.clear_repeat, "repeat"),
    ):
        if given and cleared:
            raise ToolError(_both(name))
    skipped = missing_time_refusal(
        TOOL_NAME, change.reminder_at, zone=zone, nothing_happened=_NOTHING_CHANGED
    )
    if skipped is not None:
        raise ToolError(skipped)
    if change.repeat is not None:
        refusal = repeat_refusal(TOOL_NAME, change.repeat, nothing_happened=_NOTHING_CHANGED)
        if refusal is not None:
            raise ToolError(refusal)
    if change.clear_due_date and change.repeat is not None:
        raise ToolError(no_due_date_to_repeat(TOOL_NAME, nothing_happened=_NOTHING_CHANGED))

    body = TodoTask(
        title=change.title,
        body=None if change.notes is None else html_body(change.notes),
        due_date_time=None if change.due_date is None else due_moment(change.due_date, zone=zone),
        importance=None if change.priority is None else graph_importance(change.priority),
        start_date_time=(
            None if change.start_date is None else due_moment(change.start_date, zone=zone)
        ),
        reminder_date_time=(
            None if change.reminder_at is None else moment_in(change.reminder_at, zone=zone)
        ),
        is_reminder_on=True if change.reminder_at is not None else None,
        categories=None if change.categories is None else list(change.categories),
    )
    for cleared, field in (
        (change.clear_due_date, "dueDateTime"),
        (change.clear_start_date, "startDateTime"),
        (change.clear_reminder, "reminderDateTime"),
        (change.clear_repeat, "recurrence"),
    ):
        if cleared:
            body.additional_data[field] = None
    if change.clear_reminder:
        body.is_reminder_on = False

    about = write_state_for(
        STEP_UPDATE,
        handle.uri,
        change.title or "",
        change.notes or "",
        "" if change.due_date is None else change.due_date.isoformat(),
        str(change.clear_due_date),
        change.priority or "",
        "" if change.start_date is None else change.start_date.isoformat(),
        str(change.clear_start_date),
        "" if change.reminder_at is None else change.reminder_at.isoformat(),
        str(change.clear_reminder),
        "" if change.repeat is None else change.repeat.model_dump_json(),
        str(change.clear_repeat),
        json.dumps(None if change.categories is None else list(change.categories)),
        time_zone,
    )

    updated: TodoTask | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors():
        due = change.due_date
        if change.repeat is not None and due is None:
            due = await _due_date(client, handle, zone=zone)
        if change.repeat is not None and due is None:
            refused = no_due_date_to_repeat(TOOL_NAME, nothing_happened=_NOTHING_CHANGED)
        elif change.repeat is not None and due is not None:
            body.recurrence = recurrence_for(change.repeat, due=due)
            about = write_state_for(about, due.isoformat())
        if refused is None:
            audience = await list_audience(client, handle.list_id)
            if answer_pending or audience.reaches_others:
                title = (await task_for_a_question(client, handle)).title or ""
                with not_graph():
                    question = (
                        f"Change the task {cut_for_a_question(title)!r} "
                        + f"({_changes(change, series_from=due)}) "
                        + f"{shared_list_reason(audience)}?"
                    )
                    answer = await confirm(question, about)
                asked = answer if isinstance(answer, InputRequiredResult) else None
                refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_UPDATE):
                updated = (
                    await client.me.todo.lists.by_todo_task_list_id(handle.list_id)
                    .tasks.by_todo_task_id(handle.task_id)
                    .patch(
                        body,
                        request_configuration=RequestConfiguration[QueryParameters](
                            headers=utc_times(), options=no_retry()
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
        notes: Annotated[
            str | None, Field(min_length=1, pattern=r"\S", description=BODY_FIELD)
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
                notes=notes,
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
            ),
            time_zone=time_zone,
            confirm=person_confirms(
                ctx, agree=_CHANGE, decline=_DO_NOT_CHANGE, nothing_happened=_NOTHING_CHANGED
            ),
            answer_pending=answer_pending(ctx),
        )
