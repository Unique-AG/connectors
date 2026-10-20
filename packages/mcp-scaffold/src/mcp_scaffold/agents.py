"""`AGENTS.md`: a pointer to the architecture in mcp-architecture, followed by what this MCP
chose."""

from pathlib import Path

from mcp_scaffold.options import Auth, Options, Persistence, Upstream


def describe_mcp(options: Options, target: Path) -> None:
    persistence = " ".join(_PERSISTENCE_DESCRIBED[store] for store in options.stores) or "None."
    with (target / "AGENTS.md").open("a") as agents:
        agents.write(
            f"""
## This MCP

{options.description}

- Upstream: {_UPSTREAM_DESCRIBED[options.upstream]}
- Persistence: {persistence}
- Auth: {_AUTH_DESCRIBED[options.auth]}
"""
        )


_UPSTREAM_DESCRIBED = {
    Upstream.OPENAPI: "OpenAPI, from the vendor's spec in `upstream/openapi.yml`. "
    "`upstream/routes.py` lists the operations served as tools straight from the spec, and "
    "`operation-ids` in `[tool.mcp-openapi]` the ones our tools call through `Upstream`.",
    Upstream.HTTP: "Plain HTTP without a spec. `upstream/client.py` is an `httpx2.AsyncClient` "
    "with the base URL and auth set.",
    Upstream.CUSTOM: "Written by hand. `upstream/__init__.py` lists the interface to provide.",
}
_PERSISTENCE_DESCRIBED = {
    Persistence.POSTGRES: "Postgres through SQLAlchemy, as `Persistence.database`. Models subclass "
    "`persistence.Base`; `uv run alembic revision --autogenerate -m '...'` writes a "
    "migration, which the chart's migration hook applies.",
    Persistence.REDIS: "Redis as a key-value store (`py-key-value-aio`), as `Persistence.store`.",
}
_AUTH_DESCRIBED = {
    Auth.NONE: "None.",
    Auth.UNIQUE: "Wanted, pending the Unique auth package. Wire it in once the package exists.",
}
