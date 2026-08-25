# backstop-mcp

An MCP server over the [Backstop](https://www.backstopsolutions.com/) CRM REST API.

Backstop has no OAuth, so this service *is* the OAuth 2.1 authorization server for its MCP
clients. A client registers dynamically, gets redirected to a login form hosted here, and submits
a Backstop username + personal API token. That credential is verified against Backstop, encrypted
(Fernet) and stored in Postgres; every tool call will act as that user against Backstop —
never as a shared service account. Failed logins are rate-limited per username
(`AUTH_LOGIN_MAX_ATTEMPTS`) so the form can't be used to test credentials against Backstop.

Tools resolve parties by name rather than by ID: "Capstone" is looked up against the live
instance, and an ambiguous match asks the user to pick one.

## Layout

```
src/backstop_mcp/
  app.py                 ASGI assembly: logging, metrics, FastMCP, TOOLS, routes, lifespan
  dependencies.py        cached providers for configs, engine, client factory, auth
  teardown.py            close_singletons(): release the pools, drop every cached provider
  config.py              one BaseSettings class per concern; read by the config providers
  logging.py metrics.py  cross-cutting
  features/              what the connector does; each may own tools/ and dependencies.py
    resolution.py
    entity_types.py
    auth/
    custom_fields/
    party_resolver/
    accounts/
    data_hygiene/
    activity_history/
    opportunities/
    org_people/
    includes/
  server/                how it's exposed over MCP
    instructions.py
    tools/registry.py    the hand-written TOOLS list create_app registers
  backstop_client/       HTTP transport
  db/
```

The layering rule is that **nothing under `features/` may import from `server/`** — the server
wires features together, never the reverse. `tests/test_layering.py` enforces it (and rule 7:
every tool file appears in `TOOLS`).

## Adding a feature or tool

1. Create `features/<name>/` with the model layers `api_responses` → `internal_dto` → `responses`.
2. Put the fetch in a module named after the function it defines.
3. Add `dependencies.py` with an `@lru_cache(maxsize=1)` provider only if the feature owns a
   long-lived service, exported through `__init__` and listed in `teardown.PROVIDERS`.
4. Add `tools/<tool_name>.py` defining exactly one `FunctionTool` bound to a symbol matching the
   filename.
5. Declare collaborators as `Depends(...)` parameters, which stay out of the published schema.
6. Write the test under `tests/features/<name>/tools/`, passing collaborators as kwargs rather
   than standing up a database.

Three rules an agent will otherwise break, each enforced by a test: a tool is registered by being
added to `server/tools/registry.py` as well as written, and nothing under `features/` may import
`server/` (both `tests/test_layering.py`); a cached provider is torn down by being listed in
`teardown.PROVIDERS` as well as written (`tests/test_teardown.py`).

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

Tool tests pass a fake or real client as kwargs and do not need Postgres. The suite still starts
a container for app, auth, and db tests, so Docker must be running.

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
