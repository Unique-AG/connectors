"""`AGENTS.md`: a pointer to the architecture in mcp-architecture, followed by what this MCP
chose."""

from pathlib import Path

from mcp_scaffold.options import Options, Persistence, Upstream


def describe_mcp(options: Options, target: Path) -> None:
    persistence = " ".join(_PERSISTENCE_DESCRIBED[store] for store in options.stores) or "None."
    with (target / "AGENTS.md").open("a") as agents:
        agents.write(
            f"""
## This MCP

{options.description}

- Upstream: {_UPSTREAM_DESCRIBED[options.upstream] if options.upstream else _NO_UPSTREAM}
- Persistence: {persistence}
- Auth: {_AUTH}
"""
        )


_UPSTREAM_DESCRIBED = {
    Upstream.OPENAPI: "OpenAPI, from the vendor's spec in `upstream/openapi.yml`. "
    "`upstream/routes.py` lists the operations served as tools straight from the spec, and "
    "`operation-ids` in `[tool.mcp-openapi]` the ones our tools call through `Upstream`.",
    Upstream.CUSTOM: "A client of our own in `upstream/client.py`, started from the scaffold's "
    "HTTP client: one `request` for any method and path, retried by `RetrySettings`, parsing "
    "every body into a pydantic model. The `new-mcp` skill's rules for coding a client apply.",
}
_NO_UPSTREAM = (
    "None. `upstream/` stays empty until the MCP calls a system of its own; the `new-mcp` "
    "skill's rules for coding a client say how to add one."
)
_PERSISTENCE_DESCRIBED = {
    Persistence.POSTGRES: "Postgres through SQLAlchemy, as `Persistence.database`. Models subclass "
    "`persistence.Base`; `uv run alembic revision --autogenerate -m '...'` writes a "
    "migration, which the chart's migration hook applies.",
    Persistence.REDIS: "Redis as a key-value store (`py-key-value-aio`), as `Persistence.store`.",
}
_AUTH = (
    "Not implemented. `run_server` refuses to serve beyond loopback until the server has an "
    "auth provider, `FastMCP(auth=...)`. The `new-mcp` skill's rules for coding auth say how to "
    "add one."
)
