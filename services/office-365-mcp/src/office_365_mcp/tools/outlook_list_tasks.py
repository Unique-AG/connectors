from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.models.todo_task import TodoTask
from msgraph.generated.users.item.todo.lists.item.tasks.tasks_request_builder import (
    TasksRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, collect_pages, graph_errors, graph_step
from office_365_mcp.shared.calendar import zone_named
from office_365_mcp.shared.handles import task_list_handle
from office_365_mcp.shared.outlook.tasks import (
    DEFAULT_TIME_ZONE,
    SUMMARY_FIELDS,
    TIME_ZONE_FIELD,
    TaskSummary,
    bad_zone,
    day_of,
)
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller
from office_365_mcp.shared.window import DayOrMoment, closes_at, opens_at, runs_backwards

TOOL_NAME = "outlook_list_tasks"

PRESETS: tuple[str, ...] = ("outlook-tasks", "outlook-tasks-write", "outlook-tasks-delete")

STEP = "tasks"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "task_list": "outlook:///tasklists/AAMkAGI2SYNTHETIC-list-0001%3D"
}

_PAGE_SIZE = 100

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this task list. The handle is well formed, so this is not a "
    + "bad argument. The list was most likely deleted, or it was shared with the user and the "
    + "owner stopped the share. Call outlook_list_task_lists again and take a fresh `uri`. "
    + _AGAIN
)

_TasksQuery = TasksRequestBuilder.TasksRequestBuilderGetQueryParameters

Shown = Literal["open", "completed", "any"]

_STATUS_FILTER: Mapping[Shown, str | None] = {
    "open": "status ne 'completed'",
    "completed": "status eq 'completed'",
    "any": None,
}

_DESCRIPTION = """\
Lists the tasks in one Microsoft To Do task list of the signed-in user, given the `uri` of an \
outlook_list_task_lists row. Each row gives the title, the status, the priority, and the due date \
of one task. To read the notes of a task, give the `uri` of its row to outlook_read_task.

Notes:
- By default this tool lists only open tasks. Pass `show="completed"` or `show="any"` to see \
completed tasks.
- This tool narrows by words in the title and by due date. It reads up to 1000 tasks of the list \
to do so. It cannot search the notes of a task.
- If `capped` is true, more tasks can match beyond this result. Before you decide that no task \
matches, make sure that `capped` is false.
"""

_NOT_A_LIST_HANDLE = (
    "outlook_list_tasks takes the `uri` of a task list in `task_list`, and this is not one. Take "
    + "the `uri` of a row that outlook_list_task_lists returned, and copy it word for word. A "
    + "task list handle looks like outlook:///tasklists/AAMkAGI2SYNTHETIC-list-0001%3D. A list "
    + f"name is not a handle. This tool read nothing. {_AGAIN}"
)

_BACKWARDS = (
    "outlook_list_tasks found nothing, because `due_before` falls before `due_after`, so no day "
    + "lies between them. Put the earlier day in `due_after` and the later day in `due_before`, "
    + "then call again. This tool read nothing."
)


class Tasks(BaseModel):
    tasks: list[TaskSummary] = Field(
        description=(
            "The tasks that matched, in the order that Microsoft 365 returns them. The list is "
            + "empty when no task matched. Read `capped` before you report that the list is "
            + "complete."
        )
    )
    capped: bool = Field(
        description=(
            "True when the listing stopped early and more tasks can match. To see more, raise "
            + "`limit` or narrow the call. False means that the answer holds every task that "
            + "matched."
        )
    )


async def list_tasks(
    client: GraphServiceClient,
    *,
    task_list: str,
    show: Shown = "open",
    title_contains: str | None = None,
    due_after: date | datetime | None = None,
    due_before: date | datetime | None = None,
    time_zone: str = DEFAULT_TIME_ZONE,
    limit: int,
) -> Tasks:
    assert 1 <= limit <= MAX_SCANNED_ITEMS, (
        f"limit must be within 1..{MAX_SCANNED_ITEMS}, got {limit}"
    )
    handle = task_list_handle(task_list)
    if handle is None:
        raise ToolError(_NOT_A_LIST_HANDLE)
    zone = zone_named(time_zone)
    if zone is None:
        raise ToolError(bad_zone(TOOL_NAME, nothing_happened="This tool read nothing."))
    if runs_backwards(due_after, due_before, zone=zone):
        raise ToolError(_BACKWARDS)
    matches = _matcher(title_contains, due_after, due_before, zone)

    with graph_errors(), graph_step(STEP):
        first_page = await client.me.todo.lists.by_todo_task_list_id(handle.list_id).tasks.get(
            request_configuration=RequestConfiguration[_TasksQuery](
                query_parameters=_TasksQuery(
                    filter=_STATUS_FILTER[show], select=list(SUMMARY_FIELDS), top=_PAGE_SIZE
                )
            )
        )
        assert first_page is not None, "Graph answered a task listing with no collection"
        collected = await collect_pages(first_page, client, limit=limit, matches=matches)

    return Tasks(
        tasks=[
            TaskSummary.from_task(task, list_id=handle.list_id, zone=zone)
            for task in collected.items
        ],
        capped=collected.capped,
    )


def _matcher(
    title_contains: str | None,
    due_after: date | datetime | None,
    due_before: date | datetime | None,
    zone: ZoneInfo,
) -> Callable[[TodoTask], bool]:
    words = None if title_contains is None else title_contains.strip().casefold()

    def matches(task: TodoTask) -> bool:
        if words and words not in (task.title or "").casefold():
            return False
        if due_after is None and due_before is None:
            return True
        due = day_of(task.due_date_time, zone=zone)
        if due is None:
            return False
        if due_after is not None and closes_at(due, zone=zone) < opens_at(due_after, zone=zone):
            return False
        return due_before is None or opens_at(due, zone=zone) <= closes_at(due_before, zone=zone)

    return matches


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: List Tasks",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_tasks(
        task_list: Annotated[
            str,
            Field(
                min_length=1,
                description=(
                    "The handle of the task list, from the `uri` of an outlook_list_task_lists "
                    + "row. Copy it word for word."
                ),
            ),
        ],
        show: Annotated[
            Shown,
            Field(
                description=(
                    "Which tasks to list: `open` for the tasks that are not completed, "
                    + "`completed` for the completed tasks, or `any` for both."
                )
            ),
        ] = "open",
        title_contains: Annotated[
            str | None,
            Field(
                min_length=1,
                pattern=r"\S",
                description=(
                    "Words that the title must hold, such as `report`. Case does not matter. "
                    + "This does not search the notes of a task."
                ),
            ),
        ] = None,
        due_after: Annotated[
            DayOrMoment | None,
            Field(
                description=(
                    "List only the tasks due on or after this point. A date, such as "
                    + "`2026-11-23`, opens at midnight of that day in `time_zone`. A moment, "
                    + "such as `2026-11-23T12:00:00+01:00`, opens at that instant. A due date is "
                    + "a whole day in `time_zone`, so a task matches when any part of its due day "
                    + "is on or after this point: a task due on 2026-11-23 matches a moment at "
                    + "noon of that day. A task with no due date never matches a due bound."
                )
            ),
        ] = None,
        due_before: Annotated[
            DayOrMoment | None,
            Field(
                description=(
                    "List only the tasks due on or before this point. It takes the same two "
                    + "shapes as `due_after`. A date closes at the end of that day in `time_zone`."
                )
            ),
        ] = None,
        time_zone: Annotated[str, Field(min_length=1, description=TIME_ZONE_FIELD)] = (
            DEFAULT_TIME_ZONE
        ),
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_SCANNED_ITEMS,
                description=(
                    "How many tasks to return. The answer is the whole result of this call. A "
                    + "second call with the same `limit` returns the same tasks, not the next "
                    + "tasks. Raise `limit` to see more."
                ),
            ),
        ] = 50,
        client: GraphServiceClient = graph,
    ) -> Tasks:
        return await list_tasks(
            client,
            task_list=task_list,
            show=show,
            title_contains=title_contains,
            due_after=due_after,
            due_before=due_before,
            time_zone=time_zone,
            limit=limit,
        )
