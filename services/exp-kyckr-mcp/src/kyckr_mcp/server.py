from importlib.metadata import version
from typing import Any, cast

import httpx2
from fastmcp import FastMCP

from kyckr_mcp.client import create_client
from kyckr_mcp.instructions import INSTRUCTIONS
from kyckr_mcp.openapi.routes import EXPOSED, MCP_NAMES, annotate_component, route_map_fn
from kyckr_mcp.openapi.spec import load_spec
from kyckr_mcp.settings import Settings


def _operation_ids(spec: dict[str, object]) -> set[str]:
    paths = spec.get("paths")
    assert isinstance(paths, dict), "Kyckr OpenAPI spec has no paths object"
    return {
        operation["operationId"]
        for path_item in paths.values()
        if isinstance(path_item, dict)
        for operation in path_item.values()
        if isinstance(operation, dict) and isinstance(operation.get("operationId"), str)
    }


def create_server(
    settings: Settings,
    spec: dict[str, object] | None = None,
    client: httpx2.AsyncClient | None = None,
) -> FastMCP:
    loaded_spec = spec or load_spec(str(settings.kyckr_openapi_url))
    missing = EXPOSED.keys() - _operation_ids(loaded_spec)
    assert not missing, f"Kyckr OpenAPI spec is missing operationIds: {sorted(missing)}"

    upstream = client or create_client(settings)
    return FastMCP.from_openapi(
        openapi_spec=cast(dict[str, Any], loaded_spec),
        client=upstream,
        name="Kyckr MCP",
        version=version("kyckr-mcp"),
        instructions=INSTRUCTIONS,
        route_map_fn=route_map_fn,
        mcp_names=MCP_NAMES,
        mcp_component_fn=annotate_component,
        validate_output=False,
    )
