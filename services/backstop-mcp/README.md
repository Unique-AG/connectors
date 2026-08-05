# backstop-mcp

An MCP server over the [Backstop](https://www.backstopsolutions.com/) CRM REST API.

Backstop has no OAuth, so this service *is* the OAuth 2.1 authorization server for its MCP
clients. A client registers dynamically, gets redirected to a login form hosted here, and submits
a Backstop username + personal API token. That credential is verified against Backstop, encrypted
(AES-256-GCM) and stored in Postgres; every tool call then acts as that user against Backstop —
never as a shared service account.

Tools resolve records by name rather than by ID: "Capstone" or "Investor Status" is looked up
against the live instance, and an ambiguous match asks the user to pick one.

## Run locally

```bash
cd services/backstop-mcp
cp .env.example .env   # fill BACKSTOP_MCP_ENCRYPTION_KEY and DB_*
uv sync
uv run alembic upgrade head
uv run backstop-mcp
```

- MCP endpoint: `http://localhost:9010/mcp` (HTTP transport)
- Health: `GET /health` — liveness, always 200 while the process is up
- Readiness: `GET /probe` — 503 when Postgres is unreachable
- Metrics: `GET /metrics` — Prometheus

Generate an encryption key with:

```bash
python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
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
uv run pytest tests/auth -k refresh   # a subset
```

## Lint & type-check

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run basedpyright .        # type check
```
