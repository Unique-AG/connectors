from collections.abc import Mapping
from typing import Annotated, ClassVar

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.headers_collection import HeadersCollection
from mcp.types import InputRequiredResult
from msgraph.generated.models.todo_task import TodoTask
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, ConfigDict, Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared.calendar import zone_named
from office_365_mcp.shared.handles import task_handle
from office_365_mcp.shared.outlook.tasks import (
    AGAIN,
    DEFAULT_TIME_ZONE,
    TIME_ZONE_FIELD,
    Status,
    TaskDetail,
    bad_handle,
    bad_zone,
    graph_status,
    list_audience,
    named_in_question,
    read_task,
    todo_request,
)
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE,
    Approval,
    Confirm,
    Question,
    answer_pending,
    answered,
    approved_write,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_set_task_status"

PRESETS: tuple[str, ...] = ("outlook-tasks-write", "outlook-tasks-delete")

STEP_SET_STATUS = "set_task_status"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("outlook_list_tasks",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "uri": "outlook:///tasks/AAMkAGI2SYNTHETIC-list-0001%3D/AAMkAGI2SYNTHETIC-task-0001%3D",
    "status": "completed",
}

_NOTHING_CHANGED = "Nothing was changed."
_CHANGE = "change the status"
_DO_NOT_CHANGE = "keep the status"

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not return this task, and nothing was changed. The handle is well formed, "
    + "so this is not a bad argument. The task was most likely deleted, or moved to another "
    + "list, which gives it a new handle: find it again with outlook_list_tasks and take a fresh "
    + "`uri`. If its list was deleted or is no longer shared with the user, call "
    + f"outlook_list_task_lists again instead. {AGAIN}"
)

_DESCRIPTION = """\
Sets the status of one Microsoft To Do task of the signed-in user, given the `uri` of an \
outlook_list_tasks row. `completed` marks the task done, and `not_started` reopens it. Outlook \
and To Do show the new status.

Notes:
- `completed` on a repeating task keeps the same `uri` for the next task of the series: the \
answer shows that task open, with the next due date. To Do keeps the completed task as a copy. \
A second `completed` completes the next task too.
- This tool asks the user to agree before it changes a task in a list that other people share, \
because they see the change. A task in the user's own unshared list changes without a question.
"""

_SPOKEN: Mapping[Status, str] = {
    "not_started": "not started",
    "in_progress": "in progress",
    "completed": "completed",
    "waiting_on_others": "waiting on others",
    "deferred": "deferred",
}


class _NewStatus(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    status: Status
    time_zone: str


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
        raise ToolError(
            bad_handle(TOOL_NAME, "task", argument="uri", nothing_happened=_NOTHING_CHANGED)
        )
    zone = zone_named(time_zone)
    if zone is None:
        raise ToolError(bad_zone(TOOL_NAME, nothing_happened=_NOTHING_CHANGED))

    async def prepare(must_ask: bool) -> Question | None:
        audience = await list_audience(client, handle.list_id)
        if not (must_ask or audience.reaches_others):
            return None
        task = await read_task(client, handle)
        named = named_in_question("task", task.title, missing="with no title")
        question = f"Set {named} to {_SPOKEN[status]} in {audience.named}?" + audience.sharing_note(
            "see the change"
        )
        return Question(question, (audience.task_list, task), guarded=task)

    async def write(headers: HeadersCollection) -> TaskDetail:
        with graph_step(STEP_SET_STATUS):
            updated = (
                await client.me.todo.lists.by_todo_task_list_id(handle.list_id)
                .tasks.by_todo_task_id(handle.task_id)
                .patch(
                    TodoTask(status=graph_status(status)),
                    request_configuration=todo_request(
                        safe_to_repeat=False, task_times=True, headers=headers
                    ),
                )
            )
        assert updated is not None, "Graph answered a task update with no task"
        return TaskDetail.from_full_task(updated, list_id=handle.list_id, zone=zone)

    approval = Approval(
        TOOL_NAME,
        handle.uri,
        _NewStatus(status=status, time_zone=time_zone),
        confirm,
        answer_pending,
        _NOTHING_CHANGED,
    )
    with graph_errors():
        result = await approved_write(approval, prepare=prepare, write=write)
    return answered(result)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Set the Status of a Task",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE,
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
