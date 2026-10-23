# mcp-scaffold-version: 0.0.1, timestamp: 2026-10-22T06:27:45+00:00

from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from datetime import UTC
from pathlib import Path
from typing import cast

from fastmcp.server.providers.openapi import MCPType
from fastmcp.server.providers.openapi import OpenAPIProvider
import httpx2
from mcp_openapi.openapi import mcp_name
from mcp_openapi.openapi import route_map
from mcp_openapi.openapi import set_tool_hints
from mcp_openapi.retry import RetryAfterPolicy
from mcp_openapi.upstream import OperationClient
import yaml

from world_check_mcp.upstream.routes import EXPOSED
from world_check_mcp.upstream.settings import UpstreamSettings
from world_check_mcp.upstream.token import ServiceAccountAuth

# The name the contexts and tools import the client by, kept the same in every MCP whatever
# the client is. It is an alias, not an abstraction: its API is the client's own.
Upstream = OperationClient


def upstream_http(
    settings: UpstreamSettings,
    transport: httpx2.AsyncBaseTransport | None = None,
    *,
    now: Callable[[], datetime] | None = None,
) -> httpx2.AsyncClient:
    """Every request to the upstream goes through it, from `Upstream` and the generated tools.

    `now` is the clock the service-account token's expiry is read against.
    """
    return httpx2.AsyncClient(
        base_url=str(settings.api_url).rstrip("/"),
        timeout=settings.timeout_seconds,
        transport=transport,
        auth=ServiceAccountAuth(
            settings.api_key,
            settings.api_secret,
            str(settings.token_url).rstrip("/"),
            timeout=settings.timeout_seconds,
            transport=transport,
            now=now or _utc_now,
        ),
        headers={"Accept": "application/json"},
    )


@asynccontextmanager
async def open_upstream(
    http: httpx2.AsyncClient, settings: UpstreamSettings
) -> AsyncGenerator[Upstream]:
    """Open the client the contexts receive, over `http`.

    Leaves `http` open: it lives as long as the server, and an httpx client never reopens,
    while every in-memory client enters the lifespan again.
    """
    retry = settings.retry
    policy = RetryAfterPolicy(
        max_attempts=retry.max_attempts,
        max_wait_seconds=retry.max_wait_seconds,
        statuses=retry.statuses,
    )
    yield Upstream(SPEC, http, retry_policy=policy)


def upstream_tools(http: httpx2.AsyncClient) -> OpenAPIProvider:
    """The operations in `EXPOSED`, served as tools straight from the spec. Retries do not apply."""
    missing = set(EXPOSED) - Upstream(SPEC, http).operation_ids
    assert not missing, f"operationIds in EXPOSED but not in the spec: {sorted(missing)}"
    return OpenAPIProvider(
        SPEC,
        http,
        route_map_fn=route_map(dict.fromkeys(EXPOSED, MCPType.TOOL)),
        mcp_names={operation_id: mcp_name(operation_id) for operation_id in EXPOSED},
        mcp_component_fn=set_tool_hints,
    )


def _utc_now() -> datetime:
    return datetime.now(UTC)


_METHODS = frozenset({"delete", "get", "head", "options", "patch", "post", "put", "trace"})
_SIGNED_HEADER_REFS = frozenset(
    {
        "#/components/parameters/Authorization",
        "#/components/parameters/ContentLength",
        "#/components/parameters/ContentType",
        "#/components/parameters/Date",
    }
)
_SIGNED_HEADER_NAMES = frozenset({"Authorization", "Content-Length", "Content-Type", "Date"})


def _without_signed_headers(spec: dict[str, object]) -> dict[str, object]:
    """Drop the headers the client sets, so a tool does not ask the caller for them."""
    paths = spec.get("paths")
    if not isinstance(paths, dict):
        return spec
    items = cast(dict[object, object], paths)
    return {
        **spec,
        "paths": {_callable_path(str(path)): _path_item(item) for path, item in items.items()},
    }


def _callable_path(path: str) -> str:
    """Drop the catch-all marker so `{*caseId}` lines up with the parameter `caseId`."""
    return path.replace("{*", "{")


def _path_item(item: object) -> object:
    if not isinstance(item, dict):
        return item
    fields = cast(dict[str, object], item)
    copied: dict[str, object] = {}
    for key, value in fields.items():
        if key == "parameters":
            copied[key] = _without_signed_parameters(value)
        elif key in _METHODS and isinstance(value, dict):
            copied[key] = _operation(cast(dict[str, object], value))
        else:
            copied[key] = value
    return copied


def _operation(operation: dict[str, object]) -> dict[str, object]:
    parameters = operation.get("parameters")
    if parameters is None:
        return operation
    return {**operation, "parameters": _without_signed_parameters(parameters)}


def _without_signed_parameters(parameters: object) -> object:
    if not isinstance(parameters, list):
        return parameters
    items = cast(list[object], parameters)
    return [parameter for parameter in items if not _is_signed_header(parameter)]


def _is_signed_header(parameter: object) -> bool:
    if not isinstance(parameter, dict):
        return False
    fields = cast(dict[str, object], parameter)
    ref = fields.get("$ref")
    name = fields.get("name")
    return (isinstance(ref, str) and ref in _SIGNED_HEADER_REFS) or (
        fields.get("in") == "header" and isinstance(name, str) and name in _SIGNED_HEADER_NAMES
    )


SPEC = _without_signed_headers(
    cast(
        dict[str, object],
        yaml.safe_load((Path(__file__).parent / "openapi.yml").read_text()),
    )
)
