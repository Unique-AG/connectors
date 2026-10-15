import re

from fastmcp.server.providers.openapi import (
    MCPType,
    OpenAPIResource,
    OpenAPIResourceTemplate,
    OpenAPITool,
    RouteMapFn,
)
from fastmcp.utilities.openapi import HTTPRoute
from mcp_types import ToolAnnotations

TOOL_HINTS = ToolAnnotations(read_only_hint=True, open_world_hint=True)


def mcp_name(operation_id: str) -> str:
    """camelCase operationId as snake_case, without the leading get_."""
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", operation_id).lower()
    return snake.removeprefix("get_")  # this is specific here but could be generalized


def route_map(exposed: dict[str, MCPType]) -> RouteMapFn:
    """A `route_map_fn` that exposes the listed operationIds as given and hides the rest."""

    def route_map_fn(route: HTTPRoute, _default: MCPType) -> MCPType:
        return exposed.get(route.operation_id or "", MCPType.EXCLUDE)

    return route_map_fn


def set_tool_hints(
    route: HTTPRoute, component: OpenAPITool | OpenAPIResource | OpenAPIResourceTemplate
) -> None:
    """Sets readOnlyHint (true for GET) and openWorldHint on a generated tool."""
    if isinstance(component, OpenAPITool):
        component.annotations = ToolAnnotations(
            read_only_hint=route.method.upper() == "GET", open_world_hint=True
        )
