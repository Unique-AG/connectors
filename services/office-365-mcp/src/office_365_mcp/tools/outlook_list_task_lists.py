from collections.abc import Mapping
from typing import Annotated

import httpx
from fastmcp import FastMCP
from kiota_abstractions.base_request_configuration import RequestConfiguration
from msgraph.generated.users.item.todo.lists.lists_request_builder import ListsRequestBuilder
from msgraph.graph_service_client import GraphServiceClient
from pydantic import BaseModel, Field

from office_365_mcp.graph_client import MAX_SCANNED_ITEMS, collect_pages, graph_step
from office_365_mcp.shared.outlook.tasks import TaskListSummary
from office_365_mcp.shared.seam import READ_ONLY, graph_client_for_caller

TOOL_NAME = "outlook_list_task_lists"

PRESETS: tuple[str, ...] = ("outlook-tasks", "outlook-tasks-write")

STEP = "task_lists"

GRAPH_PERMISSIONS: tuple[str, ...] = ("Tasks.Read",)

GRAPH_CALL_EXAMPLE: Mapping[str, object] = {}

_ListsQuery = ListsRequestBuilder.ListsRequestBuilderGetQueryParameters

_DESCRIPTION = """\
Lists the Microsoft To Do task lists of the signed-in user: the built-in Tasks list, the list of \
flagged messages, the lists that the user made, and the lists that other people shared with the \
user. Outlook shows the same tasks. To see the tasks in one list, give the `uri` of its row to \
outlook_list_tasks.

Notes:
- This tool reads the user's own To Do only. It cannot read the tasks of another person or of a \
shared mailbox.
- If `capped` is true, more lists exist beyond this result. Raise `limit` to see them.
"""


class TaskLists(BaseModel):
    task_lists: list[TaskListSummary] = Field(
        description=(
            "The task lists, in the order that Microsoft 365 returns them. Read `capped` before "
            + "you report that the list is complete."
        )
    )
    capped: bool = Field(
        description=(
            "True when the listing stopped early and more lists remain. To see more, raise "
            + "`limit`. False means that the answer holds every list."
        )
    )


async def list_task_lists(client: GraphServiceClient, *, limit: int) -> TaskLists:
    assert 1 <= limit <= MAX_SCANNED_ITEMS, (
        f"limit must be within 1..{MAX_SCANNED_ITEMS}, got {limit}"
    )
    with graph_step(STEP):
        first_page = await client.me.todo.lists.get(
            request_configuration=RequestConfiguration[_ListsQuery](
                query_parameters=_ListsQuery(top=limit)
            )
        )
        assert first_page is not None, "Graph answered a task list listing with no collection"
        collected = await collect_pages(first_page, client, limit=limit)

    return TaskLists(
        task_lists=[TaskListSummary.from_list(item) for item in collected.items],
        capped=collected.capped,
    )


def register(mcp: FastMCP, transport: httpx.AsyncClient) -> None:
    graph = graph_client_for_caller(transport, *GRAPH_PERMISSIONS)

    @mcp.tool(
        name=TOOL_NAME,
        title="Outlook: List Task Lists",
        description=_DESCRIPTION,
        annotations=READ_ONLY,
    )
    async def outlook_list_task_lists(
        limit: Annotated[
            int,
            Field(
                ge=1,
                le=MAX_SCANNED_ITEMS,
                description=(
                    "How many task lists to return. The answer is the whole result of this call. "
                    + "Raise `limit` to see more."
                ),
            ),
        ] = 100,
        client: GraphServiceClient = graph,
    ) -> TaskLists:
        return await list_task_lists(client, limit=limit)
