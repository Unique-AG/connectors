# office-mcp

An MCP server over Microsoft 365 via Microsoft Graph API.

This PR is scaffolding: app wiring, config, logging, and telemetry. The service starts and reports Postgres readiness.
Entra auth, the Graph client, and features land in later PRs.

## Layout

```
src/office_mcp/
  app.py                 composition root — all config and collaborators built here, once
  config.py              one BaseSettings per concern, read only at root
  logging.py metrics.py  cross-cutting infrastructure
  features/              connector logic (empty until first feature)
  server/                MCP exposure (empty until first tool)
```

Database surface: one string `DatabaseConfig.driver_dsn` passed to `asyncpg.connect`.
Deliberately no engine, pool or session layer. Two shapes are two places TLS can be negotiated differently.

Layering rule: **`features/` must not import `server/`**. Server wires features; the reverse is a violation.
`tests/test_layering.py` enforces this rule. The test grows as each new package arrives.

## Run locally

```bash
cd services/office-mcp
cp .env.example .env   # fill DB_*
uv sync
uv run office-mcp
```

Endpoints:
- MCP: `http://localhost:9544/mcp` (HTTP transport)
- Health: `GET /health` (liveness check)
- Probe: `GET /probe` (process-up check)
- Ready: `GET /ready` (503 if Postgres unreachable)
- Metrics: `GET /metrics` (Prometheus format)
- Traces: off unless an `OTEL_*` variable says where to send them. `OTEL_TRACES_EXPORTER=console`
  prints spans to stderr; an `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` sends them to a collector and
  needs nothing else. `.env.example` lists the knobs, the chart wires them from
  `internalServices.dependencies.otelTraces.enabled`. Latency stays on `/metrics` only: the ASGI
  instrumentation's own duration histogram is switched off so one series measures it.

## Tests

Integration tests start a Postgres container via Docker. The service owns no schema, so the
tests create nothing in it.

```bash
uv run pytest
```

## Lint & type-check

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run basedpyright .        # type check
```
