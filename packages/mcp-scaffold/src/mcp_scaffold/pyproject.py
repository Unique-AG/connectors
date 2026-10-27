"""What `pyproject.toml` depends on, for the choices of a new MCP."""

from pathlib import Path

from pydantic import BaseModel

from mcp_scaffold.options import Options, Persistence, Upstream
from mcp_scaffold.pins import pinned, shared


class Dependencies(BaseModel):
    runtime: list[str]
    dev: list[str]
    shared: list[str]
    """The packages from `packages/`, each a `[tool.uv.sources]` path."""


def dependencies(options: Options, repo: Path) -> Dependencies:
    openapi = options.upstream is Upstream.OPENAPI
    # Every upstream client retries with mcp-openapi's RetryAfterPolicy.
    uses_mcp_openapi = options.opens_upstream
    runtime = [
        *pinned("service"),
        shared(repo, "mcp-configs"),
        shared(repo, "mcp-observability"),
        *([shared(repo, "mcp-openapi")] if uses_mcp_openapi else []),
        *(pinned("service-openapi") if openapi else []),
        *(dependency for store in options.stores for dependency in pinned(f"service-{store}")),
        *(pinned("service-auth") if options.auth is not None else []),
    ]
    dev = [
        *pinned("service-dev"),
        shared(repo, "mcp-architecture"),
        *([shared(repo, "mcp-openapi", "[codegen]")] if openapi else []),
        *(pinned("service-postgres-dev") if Persistence.POSTGRES in options.persistence else []),
    ]
    return Dependencies(
        runtime=sorted(runtime),
        dev=sorted(dev),
        shared=[
            "mcp-architecture",
            "mcp-configs",
            "mcp-observability",
            *(["mcp-openapi"] if uses_mcp_openapi else []),
        ],
    )
