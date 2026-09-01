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

> **Status: authenticated, two tools.** Every MCP client logs in through the hosted form and
> is served as itself. `get_investor` and `get_people_for_investor` answer against the live API.

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
cp .env.example .env   # fill DB_* and WITH_INTELLIGENCE_MCP_ENCRYPTION_KEY
uv sync
uv run alembic upgrade head
uv run with-intelligence-mcp
```

- MCP endpoint: `http://localhost:9011/mcp` (HTTP transport, OAuth required)
- Login form: `GET /login?request_id=...` — reached by redirect, not by hand
- Health: `GET /health` — liveness via `unique_mcp.monitoring.setup_ops`
- Probe: `GET /probe` — process-up (setup_ops)
- Ready: `GET /ready` — 503 when Postgres is unreachable
- Metrics: `GET /metrics` — Prometheus (setup_ops)

Generate the encryption key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Point MCP Inspector (`npx @modelcontextprotocol/inspector`) at the endpoint with transport
"Streamable HTTP" and press Connect: an anonymous call is refused with 401 plus the OAuth
metadata, so the client registers itself, runs PKCE and opens the login form in a browser. Submit
the username and password the With Intelligence platform accepts — not the one-time passcode from
their onboarding mail, which sets a password on their site and is never seen by this service. The
credential is verified by signing in, encrypted, and stored against your user id; tool calls then
query With Intelligence as you.

Postgres is required: OAuth token validation reads it on every request.

## Migrations

```bash
uv run alembic upgrade head                          # apply
uv run alembic revision --autogenerate -m "message"  # create
uv run alembic downgrade -1                          # roll back one
```

## Tests

```bash
uv run pytest
uv run pytest tests/features/auth -q   # a subset
```

The suite needs a Postgres. It starts a container by default, so Docker must be running; set
`TEST_DB_URL` to use one that is already running instead:

```bash
TEST_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/wi_test uv run pytest
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

The wire models under `features/*/api_responses.py` are hand-written, and
`tests/test_spec_conformance.py` checks every field they declare against the vendor's own
schemas — a field that no longer exists, or one whose type is an object where we wrote a string,
fails the suite. The schemas it compares against are pruned into
`tests/spec/vendor_schemas.json`; refresh them, as a deliberate and readable diff, with:

```bash
uv run agent-explore/spec.py snapshot
```

Add a schema name to `SNAPSHOT_ROOTS` in `agent-explore/spec.py` when a feature starts modelling
a new entity. What conformance cannot tell you is whether a field is ever populated — for that,
record a real response with `explore.py`.

Three things about it shape most of the code here: listings return `{id, name, updated_at}` and
the rich record lives at `GET /{id}`; filters take vocabulary **ids** (`primary_strategy_id`,
`country_id`, …) resolved from ~70 small listing endpoints; and an empty result can mean "not
licensed" rather than "nothing there".
