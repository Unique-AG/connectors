import json
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated, cast, override

import httpx2
import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.server.providers.openapi import MCPType, OpenAPIProvider, RouteMap
from fastmcp.tools import Tool, ToolResult
from mcp_types import CallToolRequestParams
from pydantic import Field

from mcp_architecture import (
    masks_error_details,
    tool_surface,
    tools_with_a_root_combinator,
    undescribed_tools,
)

# An operation without a summary or a parameter description, as many vendor specs have.
ORDERS_SPEC: dict[str, object] = {
    "openapi": "3.0.3",
    "info": {"title": "Orders", "version": "1"},
    "paths": {
        "/orders/{order_id}": {
            "get": {
                "operationId": "get_order",
                "parameters": [
                    {
                        "name": "order_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
                "responses": {"200": {"description": "The order."}},
            }
        }
    },
}


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

    @mcp.tool(tags={"passthrough"})
    def cancel_order(order_id: str) -> str:
        return order_id

    mcp.add_provider(
        OpenAPIProvider(
            ORDERS_SPEC, httpx2.AsyncClient(), route_maps=[RouteMap(mcp_type=MCPType.TOOL)]
        )
    )
    return mcp


async def surface_of(server: FastMCP) -> dict[str, dict[str, object]]:
    tools = cast(list[dict[str, object]], json.loads(await tool_surface(server)))
    return {str(tool["name"]): tool for tool in tools}


async def test_undescribed_tools_lists_tools_and_parameters_but_skips_spec_operations(
    server: FastMCP,
) -> None:
    assert sorted(await undescribed_tools(server)) == [
        "cancel_order",
        "cancel_order(order_id)",
        "place_order",
        "place_order(product_id)",
    ]


async def test_tool_surface_lists_every_tool_sorted_by_name(server: FastMCP) -> None:
    assert list(await surface_of(server)) == [
        "cancel_order",
        "get_order",
        "get_product",
        "place_order",
    ]


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

    assert surface["cancel_order"]["_meta"] == {"fastmcp": {"tags": ["passthrough"]}}
    assert "_meta" not in surface["get_product"]


def find_product(sku: str) -> str:
    return sku


async def test_a_tool_whose_input_schema_combines_schemas_at_its_root_is_listed(
    server: FastMCP,
) -> None:
    either_key = {
        "type": "object",
        "anyOf": [{"required": ["sku"]}, {"required": ["product_id"]}],
        "properties": {"sku": {"type": "string"}, "product_id": {"type": "string"}},
    }
    server.add_tool(Tool.from_function(find_product).model_copy(update={"parameters": either_key}))

    assert await tools_with_a_root_combinator(server) == ["find_product: anyOf"]


async def test_tools_with_plain_object_schemas_are_not_listed(server: FastMCP) -> None:
    assert await tools_with_a_root_combinator(server) == []


@pytest.mark.parametrize("masked", [True, False])
async def test_masks_error_details_tells_whether_an_error_message_reaches_the_client(
    masked: bool,
) -> None:
    @asynccontextmanager
    async def factory() -> AsyncGenerator[FastMCP]:
        yield FastMCP(name="Shop", mask_error_details=masked)

    assert await masks_error_details(factory) is masked


async def test_masks_error_details_does_not_pass_a_server_that_never_runs_the_tool() -> None:
    class RejectEveryCall(Middleware):
        @override
        async def on_call_tool(
            self,
            context: MiddlewareContext[CallToolRequestParams],
            call_next: CallNext[CallToolRequestParams, ToolResult],
        ) -> ToolResult:
            raise ToolError("Unknown tool")

    @asynccontextmanager
    async def factory() -> AsyncGenerator[FastMCP]:
        mcp = FastMCP(name="Shop", mask_error_details=False)
        mcp.add_middleware(RejectEveryCall())
        yield mcp

    assert await masks_error_details(factory) is False
