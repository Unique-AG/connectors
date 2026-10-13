import re

from fastmcp.server.providers.openapi import (
    MCPType,
    OpenAPIResource,
    OpenAPIResourceTemplate,
    OpenAPITool,
)
from fastmcp.utilities.openapi import HTTPRoute
from mcp_types import ToolAnnotations

# operationIds from the spec and how they are exposed. Everything else is hidden.
# Resources are for GETs without query params only.
EXPOSED: dict[str, MCPType] = {
    **dict.fromkeys(
        [
            "testConnection",
            "searchAssets",
            "getDailyMeta",
            "getDailyPrices",
            "getFundamentalsMeta",
            "getFundamentalsStatements",
            "getFundamentalsDaily",
            "getIexTopOfBook",
            "getCryptoPrices",
            "getCryptoTopOfBook",
            "getForexPrices",
            "getForexTopOfBook",
        ],
        MCPType.TOOL,
    ),
    **dict.fromkeys(["getFundamentalsDefinitions"], MCPType.RESOURCE),
}


def mcp_name(operation_id: str) -> str:
    """camelCase operationId as snake_case, without the leading get_."""
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", operation_id).lower()
    return snake.removeprefix("get_")


MCP_NAMES: dict[str, str] = {operation_id: mcp_name(operation_id) for operation_id in EXPOSED}


def route_map_fn(route: HTTPRoute, _default: MCPType) -> MCPType:
    return EXPOSED.get(route.operation_id or "", MCPType.EXCLUDE)


def annotate_component(
    route: HTTPRoute, component: OpenAPITool | OpenAPIResource | OpenAPIResourceTemplate
) -> None:
    if isinstance(component, OpenAPITool):
        component.annotations = ToolAnnotations(
            read_only_hint=route.method.upper() == "GET", open_world_hint=True
        )
