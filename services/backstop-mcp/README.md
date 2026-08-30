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

**Current standard:** copy [`features/opportunities/`](src/backstop_mcp/features/opportunities/).
The full agent guide is [AGENT_README.md](./AGENT_README.md) — read it before adding or
refactoring a feature.

1. Create `features/<name>/` with `api_responses` → `responses` (add `internal_dto` only when
   you have real `*Dto` classes, not type aliases). Either file can become a package if it
   grows too big.
2. Put one logical read in `queries/<name>_query.py`, one logical write in
   `commands/<name>_command.py`, and reusable helpers in `utils/`. File / class / factory
   names use those suffixes and should read as the same symbol. Export each through that
   package's `__init__`. The feature `__init__` is the public door. Keep data flow
   simple unless a measured bottleneck justifies the complexity. Span and log inside the
   feature; add a metric only when the series would change a decision.
3. Put published `*Response` models in `responses`. A tool may keep only a small union
   (resolved | not-found | ambiguous).
4. Add `dependencies.py` providers. `@lru_cache(maxsize=1)` only for long-lived services;
   export those through `__init__` and list them in `teardown.PROVIDERS`.
5. Add `tools/<tool_name>.py` — the MCP endpoint. It structures elicitation and party
   resolve, then ideally calls one query or command. Register it on `server/tools/registry.py`.
6. Declare collaborators as `Depends(...)` parameters. Import them from the feature package,
   not a file inside it.
7. Write query/command tests under `tests/features/<name>/` and tool tests under
   `tests/features/<name>/tools/`, passing collaborators as kwargs. Test only the public
   interface: mock the Backstop API, call the tool/query/command, assert on the output.
   Do not promote a private method just so a test can reach it.

**Deprecated — do not copy.** Most other features (`org_people`, `accounts`,
`activity_history`, …) still use the older layout: a `fetch_*.py` function at the feature
root, large `*ResolvedResponse` models living in the tool file, and type aliases dumped in
`internal_dto.py`. Leave those features as they are unless you are migrating one. Do not use
them as a template for new work.

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

Feature tests mock the Backstop API (the external boundary), call the public tool / query /
command, and assert on the returned shape. They do not lock internals in place and they do
not make a method public just to test it. Tool tests pass a client as kwargs and do not
need Postgres. The suite still starts a container for app, auth, and db tests, so Docker
must be running.

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
