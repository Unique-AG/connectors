import json
from typing import Annotated, cast

import pytest
from fastmcp import FastMCP
from pydantic import Field

from mcp_architecture import PASSTHROUGH_TAG, tool_surface, undescribed_tools


@pytest.fixture
def server() -> FastMCP:
    mcp = FastMCP(name="Shop")

    @mcp.tool
    def get_product(product_id: Annotated[str, Field(description="From search_products.")]) -> str:
        """Read one product."""
        return product_id

    @mcp.tool
    def place_order(product_id: str) -> str:
        return product_id

    @mcp.tool(tags={PASSTHROUGH_TAG})
    def get_order(order_id: str) -> str:
        return order_id

    return mcp


async def surface_of(server: FastMCP) -> dict[str, dict[str, object]]:
    tools = cast(list[dict[str, object]], json.loads(await tool_surface(server)))
    return {str(tool["name"]): tool for tool in tools}


async def test_undescribed_tools_lists_tools_and_parameters_but_skips_passthrough_ones(
    server: FastMCP,
) -> None:
    assert await undescribed_tools(server) == ["place_order", "place_order(product_id)"]


async def test_tool_surface_lists_every_tool_sorted_by_name(server: FastMCP) -> None:
    assert list(await surface_of(server)) == ["get_order", "get_product", "place_order"]


async def test_tool_surface_keeps_the_parameter_descriptions(server: FastMCP) -> None:
    get_product = (await surface_of(server))["get_product"]

    assert get_product["description"] == "Read one product."
    assert get_product["inputSchema"] == {
        "additionalProperties": False,
        "properties": {
            "product_id": {"description": "From search_products.", "type": "string"},
        },
        "required": ["product_id"],
        "type": "object",
    }


async def test_tool_surface_keeps_only_the_tags_of_meta(server: FastMCP) -> None:
    surface = await surface_of(server)

    assert surface["get_order"]["_meta"] == {"fastmcp": {"tags": [PASSTHROUGH_TAG]}}
    assert "_meta" not in surface["get_product"]
