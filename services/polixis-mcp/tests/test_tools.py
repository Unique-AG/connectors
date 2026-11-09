import json

from fastmcp import Client
from fastmcp import FastMCP
import httpx2
import pytest

ALL_POLIXIS_TOOLS = {
    "search_entities",
    "get_corporate_profile",
    "get_smart_graph",
    "get_subgraph",
    "get_top_down_ownership",
    "get_ultimate_beneficial_owners",
    "list_completion_fields",
    "get_profile_fields",
    "get_basic_identifiers",
    "get_key_identifiers",
    "resolve_permanent_id",
}


async def test_every_polixis_operation_is_a_read_only_tool(server: FastMCP) -> None:
    async with Client(server) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools} == ALL_POLIXIS_TOOLS
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools)


async def test_search_entities_returns_matches_in_our_own_shape(server: FastMCP) -> None:
    async with Client(server) as client:
        result = await client.call_tool("search_entities", {"name": "Example Holdings"})

    assert result.structured_content == {
        "matches": [
            {
                "pid": "P100",
                "entity_type": "ORGANIZATION",
                "names": ["Example Holdings AG", "Example Holdings SA"],
                "sanctioned": True,
                "politically_exposed": False,
                "sanction_statuses": {"Example Sanctions List": "ACTIVE"},
                "alerts": ["Listed company"],
                "identifiers": {"Registration Number": ["CHE-000.000.001"]},
            }
        ],
        "page": 1,
        "total_matches": 2,
    }


async def test_search_entities_sends_polixis_its_own_field_names(
    server: FastMCP, upstream_requests: list[httpx2.Request]
) -> None:
    async with Client(server) as client:
        await client.call_tool(
            "search_entities",
            {
                "name": "Example Holdings",
                "entity_type": "ORGANIZATION",
                "countries": ["CH", "li"],
                "page": 2,
                "page_size": 25,
            },
        )

    search = upstream_requests[-1]
    assert search.url.path == "/search/api"
    assert json.loads(search.content) == {
        "name": "Example Holdings",
        "entityType": "ORGANIZATION",
        "countries": ["ch", "li"],
        "page": 2,
        "size": 25,
    }
    assert search.headers["Authorization"] == "Bearer fake-token"
    assert search.headers["x-api-key"] == "dummy-api-key"


@pytest.mark.parametrize("page_size", [0, 51])
async def test_search_entities_refuses_a_page_size_polixis_does_not_serve(
    server: FastMCP, page_size: int
) -> None:
    async with Client(server) as client:
        result = await client.call_tool(
            "search_entities",
            {"name": "Example Holdings", "page_size": page_size},
            raise_on_error=False,
        )

    assert result.is_error
