from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from mcp.types import InputRequiredResult
from msgraph.generated.models.todo_task_list import TodoTaskList
from msgraph.generated.models.wellknown_list_name import WellknownListName
from msgraph.generated.users.item.todo.lists.item.todo_task_list_item_request_builder import (
    TodoTaskListItemRequestBuilder,
)
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_errors, graph_step, no_retry, not_graph
from office_365_mcp.shared.confirmation import write_state_for
from office_365_mcp.shared.handles import task_list_handle
from office_365_mcp.shared.outlook.tasks import ListAudience, TaskListSummary
from office_365_mcp.shared.prose import cut_for_a_question
from office_365_mcp.shared.seam import (
    WRITE_DESTRUCTIVE_IDEMPOTENT,
    Confirm,
    answer_pending,
    graph_client_for_caller,
    person_confirms,
)

TOOL_NAME = "outlook_rename_task_list"

PRESETS: tuple[str, ...] = ("outlook-tasks-write", "outlook-tasks-delete")

STEP_TASK_LIST = "task_list"
STEP_RENAME = "rename_task_list"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {
    "task_list": "outlook:///tasklists/AAMkAGI2SYNTHETIC-list-0001%3D",
    "name": "Synthetic list",
}

_NOTHING_CHANGED = "Nothing was changed."
_RENAME = "rename the list"
_DO_NOT_RENAME = "keep the name"

_AGAIN = "If you call this tool again with the same arguments, the call will fail the same way."

GRAPH_NOT_FOUND = (
    "Microsoft 365 did not find this task list, and nothing was changed. The handle is well "
    + "formed, so this is not a bad argument. The list was most likely deleted, or its owner "
    + "stopped sharing it. Call outlook_list_task_lists again and take a fresh `uri`. The same "
    + "handle fails the same way, so do not retry it."
)

_LIST_FIELDS: tuple[str, ...] = ("id", "displayName", "isShared", "isOwner", "wellknownListName")

_ListQuery = TodoTaskListItemRequestBuilder.TodoTaskListItemRequestBuilderGetQueryParameters

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

_NOT_A_LIST_HANDLE = (
    f"{TOOL_NAME} takes the `uri` of a task list in `task_list`, and this is not one. Take the "
    + "`uri` of a row that outlook_list_task_lists returned, and copy it word for word. A task "
    + "list handle looks like outlook:///tasklists/AAMkAGI2SYNTHETIC-list-0001%3D. A list name "
    + f"and a task handle are not task list handles. {_NOTHING_CHANGED} {_AGAIN}"
)

_BUILT_IN = (
    "This handle names a built-in list of To Do: the Tasks list or the list of flagged messages. "
    + "Microsoft To Do does not rename these lists. Pick a list that a person made. "
    + f"{_NOTHING_CHANGED} {_AGAIN}"
)


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
        raise ToolError(_NOT_A_LIST_HANDLE)

    about = write_state_for(STEP_RENAME, handle.uri, name)

    renamed: TodoTaskList | None = None
    asked: InputRequiredResult | None = None
    refused: str | None = None
    with graph_errors():
        found = await _task_list(client, handle.list_id)
        if _is_built_in(found):
            refused = _BUILT_IN
        else:
            audience = ListAudience(name=found.display_name or "", is_shared=found.is_shared)
            if answer_pending or audience.reaches_others:
                with not_graph():
                    answer = await confirm(_question(audience, name), about)
                asked = answer if isinstance(answer, InputRequiredResult) else None
                refused = answer if isinstance(answer, str) else None
        if refused is None and asked is None:
            with graph_step(STEP_RENAME):
                renamed = await client.me.todo.lists.by_todo_task_list_id(handle.list_id).patch(
                    TodoTaskList(display_name=name),
                    request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
                )

    if asked is not None:
        return asked
    if refused is not None:
        raise ToolError(refused)
    assert renamed is not None, "Graph answered a task list rename with no list"
    return TaskListSummary.from_list(renamed)


async def _task_list(client: GraphServiceClient, list_id: str) -> TodoTaskList:
    with graph_step(STEP_TASK_LIST):
        found = await client.me.todo.lists.by_todo_task_list_id(list_id).get(
            request_configuration=RequestConfiguration[_ListQuery](
                query_parameters=_ListQuery(select=list(_LIST_FIELDS))
            )
        )
    assert found is not None, "Graph answered a task list read with no list"
    return found


def _is_built_in(found: TodoTaskList) -> bool:
    return found.wellknown_list_name not in (None, WellknownListName.None_)


def _question(audience: ListAudience, name: str) -> str:
    old = f"the list {cut_for_a_question(audience.name)!r}" if audience.name else "a list"
    asked = f"Rename {old} to {cut_for_a_question(name)!r}?"
    if audience.is_shared is None:
        return (
            f"{asked} Microsoft 365 did not report this list as private. Other people can see "
            + "the new name."
        )
    return f"{asked} Other people share this list. They see the new name."


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
