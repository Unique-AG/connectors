# architecture-demo-mcp

An MCP that `packages/mcp-scaffold` generated with every option, an OpenAPI upstream, Postgres
and Redis, and a small worked example on top against Tiingo's market data API. It is the reference for writing code in any of our Python MCPs.
[`ARCHITECTURE.md`](../../packages/mcp-architecture/ARCHITECTURE.md) is the contract, and every
example it names lives here.

It is never released or deployed. Its Dockerfile and chart are still built and linted in CI, so
they prove the scaffold's are sound.

## The example

| Tool | Shows |
|---|---|
| `get_daily_prices` | An operation served straight from the spec, listed in `upstream/routes.py` |
| `search_assets` | A query over a typed operation, dropping what the vendor sends half-filled |
| `get_asset` | A query that renames the vendor's fields, and the shared `Ticker` input |
| `get_quote` | A query cached in Redis for a minute, raising its own error for the tool to turn into a `ToolError` |
| `add_to_watchlist` | A command in a folder that checks a business rule through another feature's query, then writes to Postgres |
| `get_watchlist` | A query that reads Postgres and prices each row through the `quotes` feature |
| `remove_from_watchlist` | A destructive, idempotent command over Postgres alone |

The features are `contexts/assets`, `contexts/quotes` and `contexts/watchlists`. The storage
they call is `persistence/watchlists.py`, `persistence/quote_cache.py` and the first migration
in `persistence/migrations/versions/`. Everything else is what the scaffold wrote, owned by this
service like any other: when the skeleton changes in a way the reference should show, change it
here by hand.

It has no auth, so it only serves on loopback, and every user of a running server shares the
watchlists.

## Environment

`.env.example` lists every variable. The ones without a working default:

| Variable | What |
|---|---|
| `UPSTREAM_API_KEY` | The Tiingo API token, sent as `Authorization: Token <key>` |
| `DATABASE_URL` | Postgres, `postgresql://user:password@host:5432/db`. The chart injects it |
| `REDIS_URL` | Redis, `redis://host:6379/0` |

## Run it locally

```bash
docker run -d --rm --name demo-pg -e POSTGRES_USER=demo -e POSTGRES_PASSWORD=demo \
    -e POSTGRES_DB=architecture_demo_mcp -p 5432:5432 postgres:17-alpine
docker run -d --rm --name demo-redis -p 6379:6379 redis:7-alpine
cp .env.example .env   # then set UPSTREAM_API_KEY and DATABASE_URL=postgresql://demo:demo@...
uv sync
uv run alembic upgrade head
uv run architecture-demo-mcp   # http://127.0.0.1:8000/mcp
```

`uv run pytest` needs neither database: the tests open SQLite and an in-memory store in their
place, behind a fake Tiingo.
