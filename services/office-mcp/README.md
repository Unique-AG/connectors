# office-mcp

An MCP server over Microsoft 365, via the Microsoft Graph API.

This PR is scaffolding only: app wiring, config, logging, telemetry, database engine, and Alembic
migrations. The service starts, reports readiness against Postgres, and exposes no MCP tools yet.
Entra auth, the Microsoft Graph client, and the feature packages and tools that use them land in
later PRs, stacked on top of this.

## Layout

```
src/office_mcp/
  app.py                 composition root — every config and collaborator is built here, once
  config.py              one BaseSettings class per concern, read only at the root
  logging.py metrics.py  cross-cutting, used by both sides below
  features/              what the connector does — empty until the first feature lands
  server/                how it's exposed over MCP — empty until the first tool lands
  db/                    SQLAlchemy engine/session helpers, alembic migrations
```

The layering rule is that **nothing under `features/` may import from `server/`** — the server
wires features together, never the reverse. `tests/test_layering.py` enforces it, and grows as
each package arrives.

## Run locally

```bash
cd services/office-mcp
cp .env.example .env   # fill DB_*
uv sync
uv run alembic upgrade head
uv run office-mcp
```

- MCP endpoint: `http://localhost:9010/mcp` (HTTP transport)
- Health: `GET /health` — liveness via `unique_mcp.monitoring.setup_ops`
- Probe: `GET /probe` — process-up (setup_ops)
- Ready: `GET /ready` — 503 when Postgres is unreachable
- Metrics: `GET /metrics` — Prometheus (setup_ops)

## Migrations

```bash
uv run alembic upgrade head                          # apply
uv run alembic revision --autogenerate -m "message"  # create
uv run alembic downgrade -1                          # roll back one
```

There are no versions under `db/migrations/versions/` yet — `upgrade head` is a no-op until the
first feature adds tables.

## Tests

Integration tests start a Postgres container and run the migrations against it, so Docker must be
running.

```bash
uv run pytest
```

## Lint & type-check

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run basedpyright .        # type check
```
