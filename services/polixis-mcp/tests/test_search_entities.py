import json

import httpx2
import pytest

from polixis_mcp import contexts
from tests import polixis_responses
from tests.tool_calls import call_tool
from tests.tool_calls import McpClient
from tests.tool_calls import tool_error

ALL_TOOLS = {
    "search_entities",
    "get_entity_profiles",
    "get_related_parties",
    "get_ultimate_beneficial_owners",
    "get_top_down_ownership",
    "find_linked_companies",
    "find_connections",
    "find_flagged_parties",
    "get_sanctions_exposure",
    "find_court_decisions",
    "get_court_decision",
    "resolve_permanent_id",
}


async def test_every_tool_is_read_only(mcp_client: McpClient) -> None:
    tools = await mcp_client.list_tools()

    assert {tool.name for tool in tools} == ALL_TOOLS
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools)


async def test_search_entities_returns_matches_in_our_own_shape(mcp_client: McpClient) -> None:
    results = await call_tool(
        mcp_client,
        "search_entities",
        {"name": "Example Holdings"},
        returns=contexts.EntitySearchResults,
    )

    assert [match.model_dump() for match in results.results] == [
        {
            "pid": "O00000000000000000000000000000100",
            "entity_type": "ORGANIZATION",
            "name": "Example Holdings AG",
            "name_count": 3,
            "name_records": [
                {
                    "name": "Example Holdings SA",
                    "original": None,
                    "language": None,
                    "kind": "ALIAS",
                },
                {
                    "name": "Example Holdings AG",
                    "original": None,
                    "language": "de",
                    "kind": "CURRENT_NAME",
                },
            ],
            "other_names": ["Example Holdings Ltd"],
            "dates": {"Registration Date": ["1998-02", "1998-02-03"]},
            "countries": ["ch", "li"],
            "addresses": ["1 Example Street", "2 Example Street", "3 Example Street"],
            "sanctioned": True,
            "politically_exposed": False,
            "sanction_statuses": {"Example Sanctions List": "ACTIVE"},
            "alerts": ["Listed company"],
            "identifiers": {"Registration Number": ["CHE-000.000.001"]},
        }
    ]
    assert results.total_matches == 12


async def test_search_entities_sends_polixis_its_own_field_names(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    await mcp_client.call_tool(
        "search_entities",
        {
            "name": "Example Holdings",
            "entity_type": "ORGANIZATION",
            "countries": ["CH", "li"],
            "dates": ["1978", "1978-02", "1978-02-03"],
            "page_size": 5,
        },
    )

    search = upstream_requests[-1]
    assert search.url.path == "/search/api"
    assert json.loads(search.content) == {
        "name": "Example Holdings",
        "entityType": "ORGANIZATION",
        "countries": ["ch", "li"],
        "dates": [19780000, 19780200, 19780203],
        "page": 1,
        "size": 5,
    }
    assert search.headers["Authorization"] == "Bearer fake-token"
    assert search.headers["x-api-key"] == "dummy-api-key"


async def test_search_entities_cursor_asks_for_the_next_page_of_the_same_search(
    mcp_client: McpClient, upstream_requests: list[httpx2.Request]
) -> None:
    first = await call_tool(
        mcp_client,
        "search_entities",
        {"name": "Example Holdings", "countries": ["ch"], "page_size": 5},
        returns=contexts.EntitySearchResults,
    )

    await mcp_client.call_tool("search_entities", {"cursor": first.next_cursor, "name": "Ignored"})

    assert json.loads(upstream_requests[-1].content) == {
        "name": "Example Holdings",
        "countries": ["ch"],
        "page": 2,
        "size": 5,
    }


async def test_search_entities_names_a_match_by_a_current_name_past_the_records_listed(
    mcp_client: McpClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    aliases = [{"en": f"Example Alias {number}", "type": "ALIAS"} for number in range(11)]
    current = {"en": "Example Holdings AG", "type": "CURRENT_NAME"}
    hit = {"pid": "O00000000000000000000000000000100", "nameRecords": [*aliases, current]}
    monkeypatch.setattr(polixis_responses, "SEARCH", {"hits": [hit]})

    results = await call_tool(
        mcp_client,
        "search_entities",
        {"name": "Example Holdings"},
        returns=contexts.EntitySearchResults,
    )

    match = results.results[0]
    assert (match.name, match.name_count, len(match.name_records), match.other_names) == (
        "Example Holdings AG",
        12,
        10,
        [],
    )


@pytest.mark.parametrize(
    "arguments",
    [
        {"name": "Example Holdings", "page_size": 0},
        {"name": "Example Holdings", "page_size": 51},
        {"name": "Example Holdings", "dates": ["03/1971"]},
        {},
    ],
)
async def test_search_entities_refuses_arguments_polixis_does_not_take(
    mcp_client: McpClient, arguments: dict[str, object]
) -> None:
    await tool_error(mcp_client, "search_entities", arguments)
