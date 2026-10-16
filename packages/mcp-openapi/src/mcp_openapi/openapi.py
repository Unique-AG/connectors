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


def mcp_name(operation_id: str, *, remove_prefix: str = "") -> str:
    """camelCase or kebab-case operationId as snake_case, without `remove_prefix` at the start."""
    words = re.sub(r"[^A-Za-z0-9]+", "_", operation_id).strip("_")
    snake = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", words).lower()
    return snake.removeprefix(remove_prefix)


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
