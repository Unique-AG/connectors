# architecture-demo-mcp

An MCP that `packages/mcp-scaffold` generated with every option (an OpenAPI upstream, Postgres
and Redis), with Zitadel sign-in and a small worked example on top, against Tiingo's market data
API. It is the reference for writing code in any of our Python MCPs:
[`ARCHITECTURE.md`](../../packages/mcp-architecture/ARCHITECTURE.md) is the contract, and this
service shows each part of it.

It is not released: the scaffold ran with `--no-release`.

## The example

| Tool | Shows |
|---|---|
| `search_assets`, `get_daily_meta`, `get_daily_prices`, `get_iex_top_of_book`, `list_news`, `get_forex_top_of_book`, `get_crypto_top_of_book`, `get_crypto_prices`, `get_fundamentals_meta`, `get_fundamentals_daily`, `get_fundamentals_statements`, `get_ticker_distributions`, `get_ticker_splits` | Operations served straight from the spec, listed in `upstream/routes.py`, with no code of our own |
| `get_price_performance` | A feature function that turns a typed operation into figures of its own (total return, annualized volatility, maximum drawdown), cached in Redis, raising its own error for the tool to turn into a `ToolError` |
| `record_position` | A feature function that checks a business rule upstream, writes to Postgres under the signed-in user, then values the whole portfolio through another feature's function |

The features are `contexts/prices` and `contexts/portfolios`. The storage they call is
`persistence/price_cache.py`, `persistence/positions.py` and the first migration in
`persistence/migrations/versions/`. Sign-in lives in `mcp/auth/`, and `get_owner` in
`mcp/dependencies.py` hands the caller's Zitadel subject to the contexts as a plain string.
Everything else is what the scaffold wrote, owned by this service like any other.

## Environment

`.env.example` lists every variable. The ones without a working default:

| Variable | What |
|---|---|
| `UPSTREAM_API_KEY` | The Tiingo API token, sent as `Authorization: Token <key>` |
| `DATABASE_URL` | Postgres, `postgresql://user:password@host:5432/db`. The chart injects it |
| `REDIS_URL` | Redis, `redis://host:6379/0`: the price cache and the sign-in state |
| `ZITADEL_BASE_URL`, `ZITADEL_CLIENT_ID`, `ZITADEL_JWT_SIGNING_KEY` | The Zitadel instance, its PKCE client, and the key that signs the MCP's tokens (32 characters or more) |
| `MCP_AUTH_MODE` | `zitadel` (default) or `none`. Without sign-in the server only binds to loopback and every caller owns the same portfolios |

## Run it locally

```bash
docker run -d --rm --name demo-pg -e POSTGRES_USER=demo -e POSTGRES_PASSWORD=demo \
    -e POSTGRES_DB=architecture_demo_mcp -p 5432:5432 postgres:17-alpine
docker run -d --rm --name demo-redis -p 6379:6379 redis:7-alpine
cp .env.example .env   # then set UPSTREAM_API_KEY, DATABASE_URL and the ZITADEL_* values,
                       # or MCP_AUTH_MODE=none to skip sign-in
uv sync
uv run alembic upgrade head
uv run architecture-demo-mcp   # http://127.0.0.1:8000/mcp
```

`uv run pytest` needs neither database nor Zitadel: the tests open SQLite and an in-memory store
in their place, behind a fake Tiingo, and sign a caller in with a static token.
