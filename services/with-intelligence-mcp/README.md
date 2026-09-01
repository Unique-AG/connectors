# with-intelligence-mcp

An MCP server over the [With Intelligence](https://www.withintelligence.com/) v3 REST API —
investor data for alternative markets, built for the investor-relations use case: institutional
investors and their contacts, fund rosters, mandates, allocation intentions, funds and managers,
and editorial coverage.

With Intelligence has no OAuth of its own, so this service *is* the OAuth 2.1 authorization
server for its MCP clients: a client registers dynamically, gets redirected to a login form
hosted here, and submits the username and password `POST /v3/auth/sign-in` accepts.
The vendor session that comes back — a 1-hour access token over a 30-day refresh token — is
encrypted (Fernet) and stored in Postgres per user, so every tool call acts as that user rather
than as a shared service account.

> **Status: one vertical slice.** The transport, a vendor session and `get_investor` work
> against the live API. Authentication is **interim**: one shared account from
> `WITH_INTELLIGENCE_USERNAME`/`_PASSWORD` serves every caller, and there is no MCP-side login
> at all, so anyone who can reach `/mcp` gets that account's data. Do not deploy it outside a
> trusted network until the per-user login lands.

## Layout

```
src/with_intelligence_mcp/
  app.py                 ASGI assembly: logging, metrics, FastMCP, TOOLS, routes, lifespan
  dependencies.py        cached providers for configs, engine, session factory
  teardown.py            close_singletons(): release the pools, drop every cached provider
  config.py              one BaseSettings class per concern; read by the config providers
  logging.py metrics.py  cross-cutting
  features/              what the connector does; each may own tools/ and dependencies.py
  server/                how it's exposed over MCP
    instructions.py
    tools/registry.py    the hand-written TOOLS list create_app registers
  db/
```

The layering rule is that **nothing under `features/` may import from `server/`** — the server
wires features together, never the reverse. `tests/test_layering.py` enforces it, along with six
more rules; each rule's detector is itself tested, so the guards mean something before there are
features to guard.

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
cd services/with-intelligence-mcp
cp .env.example .env   # fill DB_* and WITH_INTELLIGENCE_USERNAME/_PASSWORD
uv sync
uv run alembic upgrade head
uv run with-intelligence-mcp
```

- MCP endpoint: `http://localhost:9011/mcp` (HTTP transport, no auth yet)
- Health: `GET /health` — liveness via `unique_mcp.monitoring.setup_ops`
- Probe: `GET /probe` — process-up (setup_ops)
- Ready: `GET /ready` — 503 when Postgres is unreachable
- Metrics: `GET /metrics` — Prometheus (setup_ops)

Point MCP Inspector (`npx @modelcontextprotocol/inspector`) at that endpoint with transport
"Streamable HTTP" to call `get_investor` by hand. Postgres is not needed for it — nothing on the
MCP path reads the database yet, so only `/ready` cares.

## Migrations

`versions/` is empty: the first migration arrives with the auth tables, which are the first
tables this service owns. `alembic upgrade head` is a no-op until then.

```bash
uv run alembic upgrade head                          # apply
uv run alembic revision --autogenerate -m "message"  # create
uv run alembic downgrade -1                          # roll back one
```

## Tests

The suite starts a Postgres container for the app and teardown tests, so Docker must be running.

```bash
uv run pytest
uv run pytest tests/test_layering.py   # a subset
```

## Lint & type-check

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run basedpyright .        # type check
```

## The vendor API

Read `.claude/skills/with-intelligence-api/` before adding a feature that touches a new entity.
Two CLIs under `agent-explore/` answer the two kinds of question:

```bash
uv run agent-explore/spec.py paths investor          # shapes, from the public OpenAPI spec
uv run agent-explore/spec.py schema InvestorExtended
uv run agent-explore/explore.py /v3/investors/2504   # behaviour, from a live GET (needs .env)
```

`spec.py` needs no credentials — the spec is public. `explore.py` signs in with the username and
password from `agent-explore/.env`, caches the token and every response, and only ever GETs.

Three things about it shape most of the code here: listings return `{id, name, updated_at}` and
the rich record lives at `GET /{id}`; filters take vocabulary **ids** (`primary_strategy_id`,
`country_id`, …) resolved from ~70 small listing endpoints; and an empty result can mean "not
licensed" rather than "nothing there".
