import json
from collections.abc import Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.tools import Tool
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphUnavailable
from office_365_mcp.shared.seam import WRITE_ADDITIVE
from office_365_mcp.tools import outlook_create_task_list as creator
from office_365_mcp.tools.outlook_create_task_list import create_task_list

_PATH = "/me/todo/lists"

_CREATED = {
    "id": "list-0001",
    "displayName": "Q4 launch",
    "isShared": False,
    "isOwner": True,
    "wellknownListName": "none",
}


class TestWhatItSendsToGraph:
    async def test_it_posts_the_name_and_returns_the_new_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = graph.post(_PATH).mock(return_value=httpx.Response(201, json=_CREATED))

        answer = await create_task_list(client, name="Q4 launch")

        assert post.call_count == 1
        made = cast("Sequence[Call]", graph.calls)
        assert json.loads(made[0].request.content) == {"displayName": "Q4 launch"}
        assert answer.uri == "outlook:///tasklists/list-0001"
        assert (answer.name, answer.kind, answer.is_shared, answer.is_owner) == (
            "Q4 launch",
            None,
            False,
            True,
        )

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_post_that_graph_declines_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = graph.post(_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await create_task_list(client, name="Q4 launch")

        assert post.call_count == 1


class TestWhatItAdvertises:
    async def test_it_is_an_additive_write_that_requires_a_name(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        creator.register(mcp, transport)
        tool = cast("Tool", await mcp.get_tool(creator.TOOL_NAME))

        assert tool.annotations is not None
        assert tool.annotations.model_dump(exclude_none=True, by_alias=True) == WRITE_ADDITIVE
        assert cast("dict[str, object]", tool.parameters)["required"] == ["name"]
