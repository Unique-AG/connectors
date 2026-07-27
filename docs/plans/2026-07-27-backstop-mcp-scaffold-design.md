# Design: backstop-mcp scaffold

**Ticket:** UN-22647

## Problem

UN-22647 is the investigation/concept spike for a Backstop MCP wrapper: Capstone's Backstop CRM exposes a REST API (bidirectional, read + write-back, Party ID as the universal join key across Organizations/Persons/Accounts). Before the domain tools can be designed, we need a new service, `backstop-mcp`, scaffolded in `services/` with the same operational baseline (logging, config, metrics, health checks, deployment) that the rest of the MCP fleet uses, so that whichever engineer picks up the follow-up ticket can start writing Backstop tools immediately instead of re-solving app-shell plumbing.

## Solution

### Overview

Build directly on FastMCP's own idioms — a single `FastMCP` instance, `@mcp.tool` for future domain tools, `@mcp.custom_route` for operational HTTP endpoints — rather than wrapping it in FastAPI. `services/edgar-mcp` (an unmerged branch, `edgar-mcp/feat/UN-16706-initial-setup`) is the only local precedent for structlog logging + OpenTelemetry/Prometheus metrics + dotenv config in this repo, but it was never merged and isn't an established pattern to mirror wholesale. We reuse the *pattern* from it — not the FastAPI-mounting approach, and not the Postgres/RabbitMQ pieces, which nothing in backstop-mcp needs yet.

### Architecture

- `config.py` — `AppConfig` via `pydantic-settings`: `app_env` (development/production/test), `port`, `log_level`, `version` (from package metadata). No `DatabaseConfig`/`RabbitMqConfig` — nothing to connect to yet.
- `logging.py` — structlog configured for JSON output in production, console (colored) in development, driven by `AppConfig.log_level`/`app_env`. Same shape as edgar-mcp's, renamed/generalized, no edgar-specific naming.
- `metrics.py` — OpenTelemetry `MeterProvider` with `PrometheusMetricReader`; exposed via `prometheus_client.generate_latest` behind an `@mcp.custom_route("/metrics")`.
- `middleware.py` — trace-context middleware that clears structlog contextvars per request and binds the current OTel trace ID, so logs and traces correlate. Added to the ASGI app via `mcp.http_app(middleware=[...])`.
- `app.py` — builds the `FastMCP("Backstop MCP")` instance, registers `/health` (liveness — static "ok") and `/probe` (readiness — no dependencies to check yet, always healthy) via `@mcp.custom_route`, configures logging + metrics, and returns `mcp.http_app(middleware=[OTel ASGI middleware, TraceContextMiddleware])`.
- `main.py` — loads `.env` via `python-dotenv`, builds the app, runs it with `uvicorn` on `AppConfig.port`.

No FastAPI dependency. No database, no message queue, no Terraform secrets (no Backstop credentials wired up yet — that's part of the follow-up implementation ticket once the API investigation concludes).

### Error Handling

`AppConfig` validation happens at import/startup time via pydantic — invalid env vars fail fast before the server starts. `/probe` returns `200`/"healthy" unconditionally for now since there are no dependencies to check; the shape (a `checks` dict, `503` on failure) mirrors what edgar-mcp does so that adding a real check later (e.g. Backstop API reachability) is a small diff, not a redesign. No custom domain exception hierarchy yet — there's no I/O against Backstop in this scaffold.

### Testing Strategy

Mirror edgar-mcp's test shape for the pieces we keep:
- `test_config.py` — env var parsing/validation for `AppConfig`.
- `test_logging.py` — renderer selection (console vs JSON) by `app_env`.
- `test_probes.py` — `/health` and `/probe` responses via `httpx.AsyncClient` against the ASGI app directly (no FastAPI `TestClient` needed).
- `test_metrics.py` — `/metrics` returns Prometheus exposition format.

No integration/testcontainers setup — there's no DB or queue to spin up.

## Out of Scope

- Any Backstop domain tools (contacts, opportunities, accounts, activities, targeting).
- Auth against the Backstop REST API.
- Party-ID data model / any Backstop-specific schema.
- RabbitMQ or any event/write-back queue plumbing.
- Postgres or any caching/staleness-tracking layer.
- Terraform-managed secrets (no credentials to store yet).
- CI wiring beyond what's needed to lint/test the new package (assumed to follow the repo's existing per-service CI pattern).

## Tasks

1. **Scaffold `pyproject.toml` and package layout** - Create `services/backstop-mcp/pyproject.toml` (name `backstop-mcp`, FastMCP + OTel/Prometheus + structlog + pydantic-settings + python-dotenv deps, ruff + basedpyright + pytest dev deps) and `src/backstop_mcp/` package skeleton (`__init__.py`, `py.typed`).
2. **Add `AppConfig`** - Implement `config.py` with `AppEnv`/`LogLevel` enums and the `AppConfig` settings class (env, port, log_level, version from package metadata).
3. **Add structlog logging setup** - Implement `logging.py` with `configure_logging(config)` and `get_logger(name)`, JSON in production / console in development.
4. **Add OTel + Prometheus metrics** - Implement `metrics.py`: `MeterProvider` with `PrometheusMetricReader`, and a `/metrics` handler returning `generate_latest(REGISTRY)`.
5. **Add trace-context middleware** - Implement `middleware.py`: binds OTel trace ID into structlog contextvars per request, excluding `/health`, `/probe`, `/metrics`.
6. **Build the FastMCP app** - Implement `app.py`: `FastMCP("Backstop MCP")` instance, `/health` and `/probe` custom routes, wires logging + metrics, returns the ASGI app with OTel ASGI instrumentation + trace-context middleware attached.
7. **Add entrypoint** - Implement `main.py`: `load_dotenv()`, build the app, run via `uvicorn` on `AppConfig.port`. Add `.env.example` documenting `APP_ENV`, `PORT`, `LOG_LEVEL`.
8. **Add tests** - `test_config.py`, `test_logging.py`, `test_probes.py`, `test_metrics.py` per the testing strategy above.
9. **Add deployment scaffolding** - `deploy/Dockerfile` and a minimal Helm chart skeleton (`Chart.yaml`, `values.yaml`, templates) under `services/backstop-mcp/deploy/`, generic (no Backstop-specific secrets/env baked in).
10. **Register the new service scope** - Add `backstop-mcp = services/backstop-mcp/**` to `.gitcommitizen`'s `[scopes]` section so commits/PRs for this service validate correctly.
