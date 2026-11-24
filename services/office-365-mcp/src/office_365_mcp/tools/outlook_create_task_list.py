from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from kiota_abstractions.default_query_parameters import QueryParameters
from msgraph.generated.models.todo_task_list import TodoTaskList
from msgraph.graph_service_client import GraphServiceClient
from pydantic import Field

from office_365_mcp.graph_client import graph_step, no_retry
from office_365_mcp.shared.outlook.tasks import TaskListSummary
from office_365_mcp.shared.seam import WRITE_ADDITIVE, graph_client_for_caller

TOOL_NAME = "outlook_create_task_list"

PRESETS: tuple[str, ...] = ("outlook-tasks-write", "outlook-tasks-delete")

STEP_CREATE = "create_task_list"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.ReadWrite",)

CHANGE_SHOWN_BY: tuple[str, ...] = ("outlook_list_task_lists",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {"name": "Synthetic list"}

_DESCRIPTION = """\
Creates one new Microsoft To Do task list for the signed-in user, with the name that the user \
gives. Outlook shows the same list. The new list is empty and private. To add a task to it, give \
the `uri` of the result to outlook_create_task.

Notes:
- If a call times out, do not call this tool again first. Before you call again, make sure that \
outlook_list_task_lists does not show the new list.
- This tool does not ask the user to agree, because only the user sees the new list.
"""


async def create_task_list(client: GraphServiceClient, *, name: str) -> TaskListSummary:
    with graph_step(STEP_CREATE):
        created = await client.me.todo.lists.post(
            TodoTaskList(display_name=name),
            request_configuration=RequestConfiguration[QueryParameters](options=no_retry()),
        )
    assert created is not None, "Graph answered a task list create with no list"
    return TaskListSummary.from_list(created)


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: Create a Task List",
        description=_DESCRIPTION,
        annotations=WRITE_ADDITIVE,
    )
    async def outlook_create_task_list(
        name: Annotated[
            str,
            Field(
                min_length=1,
                description="The name of the new list, such as `Q4 launch`, as the user writes it.",
            ),
        ],
        client: GraphServiceClient = graph,
    ) -> TaskListSummary:
        return await create_task_list(client, name=name)
