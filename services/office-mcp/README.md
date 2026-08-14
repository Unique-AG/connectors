# office-mcp

An MCP server over Microsoft 365, via the Microsoft Graph API.

This PR is scaffolding only: app wiring, config, logging, and telemetry. The service starts,
reports readiness against Postgres, and exposes no MCP tools yet.
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
```

The whole database surface is one string: `DatabaseConfig.driver_dsn`, which every caller hands
to `asyncpg.connect`. There is deliberately no engine, pool or session layer here, and no second
rendering of the same settings — two shapes are two places TLS can be negotiated differently.

The layering rule is that **nothing under `features/` may import from `server/`** — the server
wires features together, never the reverse. `tests/test_layering.py` enforces it, and grows as
each package arrives.

## Run locally

```bash
cd services/office-mcp
cp .env.example .env   # fill DB_*
uv sync
uv run office-mcp
```

- MCP endpoint: `http://localhost:9544/mcp` (HTTP transport)
- Health: `GET /health` — liveness via `unique_mcp.monitoring.setup_ops`
- Probe: `GET /probe` — process-up (setup_ops)
- Ready: `GET /ready` — 503 when Postgres is unreachable
- Metrics: `GET /metrics` — Prometheus (setup_ops)

## Tests

Integration tests start a Postgres container, so Docker must be running. The service owns no
schema, so nothing is created in it.

```bash
uv run pytest
```

## Lint & type-check

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run basedpyright .        # type check
```
