from collections.abc import Mapping
from typing import Annotated, ClassVar

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.headers_collection import HeadersCollection
from mcp.types import InputRequiredResult
from msgraph.generated.models.todo_task_list import TodoTaskList
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, ConfigDict, Field

from office_365_mcp.graph_client import graph_errors, graph_step
from office_365_mcp.shared.handles import task_list_handle
from office_365_mcp.shared.outlook.tasks import (
    AGAIN,
    TaskListSummary,
    bad_handle,
    list_audience,
    todo_request,
)
from office_365_mcp.shared.prose import cut_for_a_question
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

TOOL_NAME = "outlook_rename_task_list"

PRESETS: tuple[str, ...] = ("outlook-tasks-write", "outlook-tasks-delete")

STEP_RENAME = "rename_task_list"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "task_list": "outlook:///tasklists/AAMkAGI2SYNTHETIC-list-0001%3D",
    "name": "Synthetic list",
}

_NOTHING_CHANGED = "Nothing was changed."
_RENAME = "rename the list"
_DO_NOT_RENAME = "keep the name"

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find this task list, and nothing was changed. The handle is well "
    + "formed, so this is not a bad argument. The list was most likely deleted, or its owner "
    + "stopped sharing it. Call outlook_list_task_lists again and take a fresh `uri`. The same "
    + "handle fails the same way, so do not retry it."
)


_DESCRIPTION = """\
Gives a new name to one Microsoft To Do task list of the signed-in user, given the `uri` of an \
outlook_list_task_lists row. Outlook and To Do show the new name. The tasks in the list do not \
change.

Notes:
- This tool refuses the built-in Tasks list and the built-in list of flagged messages, because \
Microsoft To Do does not rename them.
- This tool asks the user to agree before it renames a list that other people share, because \
they see the new name. The user's own unshared list changes without a question.
- This call is safe to repeat after a timeout.
"""

_BUILT_IN = (
    "This handle names a built-in list of To Do: the Tasks list or the list of flagged messages. "
    + "Microsoft To Do does not rename these lists. Pick a list that a person made. "
    + f"{_NOTHING_CHANGED} {AGAIN}"
)


class _NewName(BaseModel):
    model_config: ClassVar[ConfigDict] = ConfigDict(frozen=True)

    name: str


async def rename_task_list(
    client: GraphServiceClient,
    *,
    task_list: str,
    name: str,
    confirm: Confirm,
    answer_pending: bool = False,
) -> TaskListSummary | InputRequiredResult:
    handle = task_list_handle(task_list)
    if handle is None:
        raise ToolError(
            bad_handle(
                TOOL_NAME, "task list", argument="task_list", nothing_happened=_NOTHING_CHANGED
            )
        )

    async def prepare(must_ask: bool) -> Question | Refusal | None:
        audience = await list_audience(client, handle.list_id)
        if audience.is_built_in:
            return Refusal(_BUILT_IN)
        if not (must_ask or audience.reaches_others):
            return None
        question = (
            f"Rename {audience.named} to {cut_for_a_question(name)!r}?"
            + audience.sharing_note("see the new name")
        )
        return Question(question, (audience.task_list,))

    async def write(headers: HeadersCollection) -> TaskListSummary:
        with graph_step(STEP_RENAME):
            renamed = await client.me.todo.lists.by_todo_task_list_id(handle.list_id).patch(
                TodoTaskList(display_name=name),
                request_configuration=todo_request(
                    safe_to_repeat=False, task_times=False, headers=headers
                ),
            )
        assert renamed is not None, "Graph answered a task list rename with no list"
        return TaskListSummary.from_list(renamed)

    approval = Approval(
        TOOL_NAME, handle.uri, _NewName(name=name), confirm, answer_pending, _NOTHING_CHANGED
    )
    with graph_errors():
        result = await approved_write(approval, prepare=prepare, write=write)
    return answered(result)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Rename a Task List",
        description=_DESCRIPTION,
        annotations=WRITE_DESTRUCTIVE_IDEMPOTENT,
    )
    async def outlook_rename_task_list(
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
        name: Annotated[
            str,
            Field(
                min_length=1,
                description="The new name of the list, such as `Q4 launch`, as the user writes it.",
            ),
        ],
        ctx: Context,
        client: GraphServiceClient = graph,
    ) -> TaskListSummary | InputRequiredResult:
        return await rename_task_list(
            client,
            task_list=task_list,
            name=name,
            confirm=person_confirms(
                ctx, agree=_RENAME, decline=_DO_NOT_RENAME, nothing_happened=_NOTHING_CHANGED
            ),
            answer_pending=answer_pending(ctx),
        )
