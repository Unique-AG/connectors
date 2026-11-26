import json
from typing import cast

from fastmcp.client.client import CallToolResult
import httpx2
from mcp.types import TextContent
import pytest

from tests.conftest import CallTool
from tests.conftest import FakeKyckr

TWO_TO_53 = 2**53
CAPITAL_FIELDS = ("quantity", "unitNominalValue", "totalNominalValue")
HOLDING_FIELDS = ("count", "totalNominalValue")
ENHANCED_NUMBERS = 8
# Each tool with its arguments and a reply that has a `cost` at the top and wherever Kyckr nests
# one. Every cost is 1.0 on the wire, and every number in the reply is a cost or an id.
COSTS: dict[str, tuple[dict[str, object], str]] = {
    "search_companies": ({"name": "Acme"}, '{"cost":{"value":1.0}}'),
    "get_lite_profile": ({"kyckr_id": "GB|abc"}, '{"cost":{"value":1.0}}'),
    "get_enhanced_profile": ({"kyckr_id": "GB|abc"}, '{"cost":{"value":1.0}}'),
    "list_company_documents": (
        {"kyckr_id": "GB|abc"},
        '{"cost":{"value":1.0},"data":[{"id":"p-1","cost":{"value":1.0}}]}',
    ),
    "create_document_order": (
        {"kyckr_id": "GB|abc", "product_id": "p-1"},
        '{"cost":{"value":1.0},"data":{"orderId":1,"status":"Pending","cost":{"value":1.0}}}',
    ),
    "get_order": (
        {"order_id": "1"},
        '{"cost":{"value":1.0},"data":{"orderId":1,"status":"Pending","cost":{"value":1.0}}}',
    ),
    "list_orders": (
        {},
        '{"cost":{"value":1.0},"data":{"orders":[{"orderId":1,"cost":{"value":1.0}}]}}',
    ),
}


def numbers(value: object) -> list[object]:
    """Every number in a JSON value, nested ones included."""
    if isinstance(value, dict):
        return [n for item in cast(dict[str, object], value).values() for n in numbers(item)]
    if isinstance(value, list):
        return [n for item in cast(list[object], value) for n in numbers(item)]
    return [value] if isinstance(value, int | float) and not isinstance(value, bool) else []


def contents(result: CallToolResult) -> list[object]:
    """What a client reads: the structured content and the parsed text content."""
    (text,) = [block.text for block in result.content if isinstance(block, TextContent)]
    return [result.structured_content, json.loads(text)]


def enhanced_body(wire: str) -> str:
    capital = ",".join(f'"{name}":{wire}' for name in CAPITAL_FIELDS)
    holding = ",".join(f'"{name}":{wire}' for name in HOLDING_FIELDS)
    return (
        f'{{"cost":{{"type":"credit","value":{wire}}},'
        f'"data":{{"totalCapital":{{"totalValue":{wire},"quantity":{wire}}},'
        f'"capital":[{{{capital},"shareholdings":[{{{holding}}}]}}]}}}}'
    )


async def enhanced_numbers(call_tool: CallTool, kyckr: FakeKyckr, wire: str) -> list[list[object]]:
    """The numbers of each enhanced profile content, for a profile whose numbers are all `wire`."""
    kyckr.handler = lambda _: httpx2.Response(200, content=enhanced_body(wire))
    result = await call_tool("get_enhanced_profile", {"kyckr_id": "GB|abc"})
    found = [numbers(content) for content in contents(result)]
    assert all(len(each) == ENHANCED_NUMBERS for each in found)
    return found


@pytest.mark.parametrize("tool", list(COSTS))
async def test_a_whole_number_cost_stays_an_int_wherever_a_tool_reports_one(
    call_tool: CallTool, kyckr: FakeKyckr, tool: str
) -> None:
    arguments, body = COSTS[tool]
    kyckr.handler = lambda _: httpx2.Response(200, content=body)

    for content in contents(await call_tool(tool, arguments)):
        found = numbers(content)
        assert found == [1] * len(found)
        assert all(isinstance(n, int) for n in found)
        assert len(found) == body.count('"value"') + body.count('"orderId"')


@pytest.mark.parametrize("wire", ["18482038", "18482038.0"])
async def test_whole_numbers_in_an_enhanced_profile_stay_ints(
    call_tool: CallTool, kyckr: FakeKyckr, wire: str
) -> None:
    for found in await enhanced_numbers(call_tool, kyckr, wire):
        assert found == [18482038] * ENHANCED_NUMBERS
        assert all(isinstance(n, int) for n in found)


async def test_a_real_fraction_stays_a_float(call_tool: CallTool, kyckr: FakeKyckr) -> None:
    for found in await enhanced_numbers(call_tool, kyckr, "12.5"):
        assert found == [12.5] * ENHANCED_NUMBERS
        assert all(isinstance(n, float) for n in found)


@pytest.mark.parametrize(
    ("wire", "kind"),
    [
        (str(TWO_TO_53 - 1), int),
        (f"{TWO_TO_53 - 1}.0", int),
        (f"{TWO_TO_53}.0", float),
        (f"{TWO_TO_53 + 2}.0", float),
    ],
    ids=["int-below-limit", "float-below-limit", "float-at-limit", "float-above-limit"],
)
async def test_a_whole_float_becomes_an_int_only_below_two_to_the_53(
    call_tool: CallTool, kyckr: FakeKyckr, *, wire: str, kind: type
) -> None:
    for found in await enhanced_numbers(call_tool, kyckr, wire):
        assert found == [float(wire)] * ENHANCED_NUMBERS
        assert all(type(n) is kind for n in found)


@pytest.mark.parametrize(("wire", "kind"), [("18482038", int), ("18482038.0", int), ("5.5", float)])
async def test_numbers_inside_a_document_keep_their_kind(
    call_tool: CallTool, kyckr: FakeKyckr, *, wire: str, kind: type
) -> None:
    def answer(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/download"):
            body = f'{{"Data":{{"Capital":[{{"Quantity":{wire},"TotalNominalValue":{wire}}}]}}}}'
        else:
            body = '{"data":{"orderId":7,"status":"Success"}}'
        return httpx2.Response(200, content=body)

    kyckr.handler = answer

    for content in contents(await call_tool("get_order", {"order_id": "7"})):
        assert [type(n) for n in numbers(content)] == [int, kind, kind]
