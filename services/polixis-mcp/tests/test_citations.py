"""Each tool's records come titled under `results`, without a link, in one JSON text item."""

import json

from fastmcp.client.client import CallToolResult
from mcp_types import TextContent
from pydantic import TypeAdapter
import pytest

from tests.tool_calls import McpClient

ORGANIZATION = "O00000000000000000000000000000100"
_TITLE_KEYS = ("title", "name")
_LINK_KEYS = ("url", "uri", "href", "webUrl", "web_url", "webLink", "web_link", "link")
_OBJECT = TypeAdapter(dict[str, object])
_RECORDS = TypeAdapter(list[dict[str, object]])

# Each tool's arguments, and the titles of the records it returns for them, in order.
_TITLED_RECORDS: dict[str, tuple[dict[str, object], list[object]]] = {
    "search_entities": ({"name": "Example Holdings"}, ["Example Holdings AG"]),
    "get_entity_profiles": ({"pids": ["P00000000000000000000000000000200"]}, ["Anna Example"]),
    "get_related_parties": ({"pid": ORGANIZATION}, ["Anna Example", "Pat Signatory"]),
    "get_ultimate_beneficial_owners": (
        {"pid": ORGANIZATION},
        ["Example Parent AG", "Carla Sample", "Anna Example"],
    ),
    "get_top_down_ownership": ({"pid": ORGANIZATION}, ["Example Shipping Ltd", None]),
    "find_linked_companies": (
        {"pid": ORGANIZATION},
        ["Example Shipping Ltd", "Example Consulting GmbH"],
    ),
    "find_connections": (
        {
            "from_pid": "P00000000000000000000000000000200",
            "to_pid": "P00000000000000000000000000000400",
        },
        ["Anna Example", "Example Holdings AG", "Example Shipping Ltd", "Boris Sample"],
    ),
    "find_flagged_parties": (
        {"pid": ORGANIZATION},
        ["Boris Sample", "Anna Example", None, "Example Consulting GmbH"],
    ),
    "get_sanctions_exposure": (
        {"pid": ORGANIZATION},
        ["Example Trading FZE", "Boris Sample", "A party without a pid"],
    ),
    "find_court_decisions": (
        {"pid": ORGANIZATION},
        ["Federal Court, CH, 2019 (ch_2019_1)", "Regional Court, DE, 2023 (de_2023_7)"],
    ),
}


@pytest.mark.parametrize("tool", _TITLED_RECORDS)
async def test_tool_lists_its_records_under_results_titled_and_without_a_link(
    mcp_client: McpClient, tool: str
) -> None:
    arguments, titles = _TITLED_RECORDS[tool]

    result = await mcp_client.call_tool(tool, arguments)

    page = _OBJECT.validate_python(result.structured_content)
    records = _RECORDS.validate_python(page["results"])
    assert [_title(record) for record in records] == titles
    assert not any(key in page for key in (*_TITLE_KEYS, *_LINK_KEYS))
    assert not any(key in record for record in records for key in _LINK_KEYS)


async def test_get_court_decision_is_one_record_titled_by_its_court_country_year_and_id(
    mcp_client: McpClient,
) -> None:
    result = await mcp_client.call_tool(
        "get_court_decision", {"pid": ORGANIZATION, "decision_id": "ch_2019_1"}
    )

    decision = _OBJECT.validate_python(result.structured_content)
    assert decision["title"] == "Federal Court, CH, 2019 (ch_2019_1)"
    assert not any(key in decision for key in _LINK_KEYS)


@pytest.mark.parametrize("tool", _TITLED_RECORDS)
async def test_tool_sends_its_result_as_one_json_text_item(
    mcp_client: McpClient, tool: str
) -> None:
    arguments, _ = _TITLED_RECORDS[tool]

    result = await mcp_client.call_tool(tool, arguments)

    (item,) = _texts(result)
    assert item.meta is None
    assert json.loads(item.text) == result.structured_content


def _title(record: dict[str, object]) -> object:
    return next((record[key] for key in _TITLE_KEYS if key in record), None)


def _texts(result: CallToolResult) -> list[TextContent]:
    assert all(isinstance(item, TextContent) for item in result.content)
    return [item for item in result.content if isinstance(item, TextContent)]
