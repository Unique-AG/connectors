# backstop-mcp

An MCP server over the [Backstop](https://www.backstopsolutions.com/) CRM REST API.

Backstop has no OAuth, so this service *is* the OAuth 2.1 authorization server for its MCP
clients. A client registers dynamically, gets redirected to a login form hosted here, and submits
a Backstop username + personal API token. That credential is verified against Backstop, encrypted
(Fernet) and stored in Postgres; every tool call would then act as that user against
Backstop — never as a shared service account. Failed logins are rate-limited per username
(`AUTH_LOGIN_MAX_ATTEMPTS`) so the form can't be used to test credentials against Backstop.

This PR adds the shared Backstop HTTP client and the OAuth credential bridge. The service starts,
authenticates MCP clients, and lets them log in against Backstop — it still exposes no MCP tools.
The feature packages and tools that use the client land in later PRs.

## Layout

```
src/backstop_mcp/
  app.py                 composition root — every config and collaborator is built here, once
  config.py              one BaseSettings class per concern, read only at the root
  logging.py metrics.py  cross-cutting, used by both sides below
  features/              what the connector does
    auth/                  Backstop credential bridging: login form, encryption, token rotation
  server/                how it's exposed over MCP
    runtime.py             the process-wide service holder tools reach through
    tools/                 tool functions + the single registry declaring them — empty for now
    middleware/             FastMCP and ASGI middleware — empty for now
  backstop_client/       HTTP transport: auth headers, concurrency gate, retries, pagination
  db/                    SQLAlchemy models, engine, alembic migrations
```

The layering rule is that **nothing under `features/` may import from `server/`** — the server
wires features together, never the reverse. `tests/test_layering.py` enforces it, and grows as
each package arrives.

## Run locally

```bash
cd services/backstop-mcp
cp .env.example .env   # fill BACKSTOP_MCP_ENCRYPTION_KEY and DB_*
uv sync
uv run alembic upgrade head
uv run backstop-mcp
```

- MCP endpoint: `http://localhost:9010/mcp` (HTTP transport)
- Health: `GET /health` — liveness via `unique_mcp.monitoring.setup_ops`
- Probe: `GET /probe` — process-up (setup_ops)
- Ready: `GET /ready` — 503 when Postgres is unreachable
- Metrics: `GET /metrics` — Prometheus (setup_ops)

Generate an encryption key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

## Migrations

```bash
uv run alembic upgrade head                          # apply
uv run alembic revision --autogenerate -m "message"  # create
uv run alembic downgrade -1                          # roll back one
```

## Tests

Integration tests start a Postgres container and run the migrations against it, so Docker must be
running.

```bash
uv run pytest
uv run pytest tests/features/auth -k refresh   # a subset
```

## Lint & type-check

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run basedpyright .        # type check
```
