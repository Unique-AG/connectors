# tiingo-mcp

Experimental: a demo, not a released or supported service. It is an MCP server for the Tiingo API, generated from a third-party OpenAPI spec with `FastMCP.from_openapi`. Its layout and tooling follow the other Python MCP services in this repository, such as `kb-mcp`.

## Run

Copy `.env.example` to `.env` and set `TIINGO_API_KEY` (the file is gitignored), then:

```sh
uv run tiingo-mcp   # http://localhost:8741/mcp, plus /probe, /health and /metrics
```

- `MCP_AUTH_MODE=none` (the example's default) only works for non-production servers bound to loopback. Behind a tunnel with an https `MCP_BASE_URL`, anyone with the URL can spend your Tiingo quota.
- Otherwise the server needs `ZITADEL_ISSUER_URL`, `ZITADEL_CLIENT_ID` (a public client, no secret) and `MCP_JWT_SIGNING_KEY`, and fails at startup if one is missing. OAuth state lives in memory, so sessions end when the process stops.
- `MCP_BASE_URL` defaults to `http://HOST:PORT`. Both `localhost` and `127.0.0.1` work locally.
- Browser clients must be listed in `MCP_ALLOWED_ORIGINS` (default: the MCP Inspector on port 6274 in development, none in production).
- `LOG_LEVEL` sets the log level. Logs are JSON on stderr, like the other services.

Try the chart app with `npx @modelcontextprotocol/inspector`: connect with Streamable HTTP to the URL above, open the Apps tab and run `plot_cumulative_returns`.

## What the demo covers

The server shows what OpenAPI and FastMCP give you, from a plain pass-through to a tool with its own UI, all starting from the vendored Tiingo spec.

1. Pass-through tools. Twelve operations in `EXPOSED` become tools and one becomes a resource. FastMCP builds each tool's name, arguments and output schema from the spec. Names come from the operationId, and `annotate_component` marks every tool read-only.
2. Typed models from the spec. `scripts/generate_response_models.py` generates a pydantic model for each response, with the spec's field descriptions, so a wrapped tool can return a typed list and the LLM sees its schema.
3. Wrapped tools. `recent_daily_prices`, `recent_financials` and `recent_valuation_metrics` replace three generated tools. They take a `lookback_days` or `periods` argument instead of dates, hide the vendor arguments, trim the output and validate their bounds. Prices keep seven fields per bar, and financials skip the full-year rows.
4. A composite tool with an app. `plot_cumulative_returns` calls `recent_daily_prices` for up to five tickers and returns a text summary plus structured data. A widget resource (`ui://tiingo/returns.html`) draws the chart in MCP Apps hosts.
5. The server around the tools. It sends instructions to the LLM and uses Zitadel OAuth (public client with PKCE), or no auth for local use. It checks Host and Origin on `/mcp` (the ops routes are exempt), sets CORS, runs stateless HTTP, and serves `/probe`, `/health` and `/metrics` with per-tool metrics. Logs are JSON, and settings are validated at startup.
6. Outgoing requests carry only an allow-list of headers to Tiingo, so headers a client sends to this server are not forwarded upstream.
7. Tests run the tools through an in-memory client against a mocked Tiingo transport. Ruff and basedpyright are part of the checks.

Not covered: durable OAuth storage (it is in memory, and the auth is expected to change), the deploy files (carried over from another setup and not run), a real Zitadel login (tested only against mocked discovery), and the chart in any host other than the MCP Inspector.

## Layout

- `settings.py`: pydantic settings with a security validator. `auth.py`: Zitadel OIDC proxy from `unique_mcp`. `params.py`: argument and date types shared by the tools and models.
- `server.py` builds the server (instructions), `main.py` runs it and mounts `/probe`, `/health` and `/metrics` with `unique_mcp.monitoring.setup_ops` (per-tool call counts and durations included).
- `openapi/`: the spec (loaded as `SPEC` in `server.py`) and `EXPOSED`, the allow-list of operationIds. Anything not listed is hidden. Generated tools are marked read-only (`annotate_component`).
- `tools/`: wrappers around generated tools (trimmed output, new arguments) and the chart tool, which calls a wrapper. `register_tools` registers the wrappers first and the chart tool after them.
- `models/`: pydantic output models. `vendor_responses.py` is generated from the spec, with one model per response of every operation in `EXPOSED` (all fields optional) and the spec's field descriptions. `FIELDS` in the script limits a model to the fields a tool returns, and undeclared vendor fields are dropped. Regenerate with `uv run scripts/generate_response_models.py` after changing the spec, `EXPOSED` or `FIELDS`. Only the wrapped tools use these models. The other tools get their output schema from FastMCP, which reads the spec.
- `apps/returns.html`: the MCP App widget.
- `scripts/`: `generate_response_models.py`. `tests/`: the tests.
- `deploy/`: `config.sh`, `Dockerfile` and `.env.deploy.example`, carried over from another setup. They are not adapted to this repository and have not been run.

## MCP App

`plot_cumulative_returns(tickers, lookback_days)` returns cumulative adjusted-close returns for 1 to 5 tickers and renders them as a line chart (`ui://tiingo/returns.html`). Clients without MCP Apps support get a text summary. The chart was checked in the MCP Inspector, not in other MCP Apps hosts.

## Checks

`uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` and `uv run basedpyright` (src only).

## Adding a tool

- As-is: add its operationId to the `MCPType.TOOL` group in `EXPOSED`.
- As a resource: add it to the `MCPType.RESOURCE` group (GETs without query params only; path params become a template).
- Wrapped: add it to the `MCPType.TOOL` group, then add a module in `tools/` and call it from `register_tools` with the other wrappers. `tools/prices.py` is the template. The function's name and docstring become the tool's name and description, and arguments it does not declare are hidden.
- Composite (calls other tools): add a module in `tools/` that looks up each tool it needs with `require_tool(mcp, name)`, and call it from `register_tools` after those tools. `tools/returns.py` is the template. A missing or out-of-order dependency fails at startup.

Not exposed: news, splits, distributions and fund fees returned 403 on the current plan, and `getDistributionYield` returns ~780 KB (11k rows) with no trimming. The fundamentals tools only work for Dow 30 tickers on the current plan (other tickers return a 400 from Tiingo).

The spec comes from `api-evangelist/tiingo` and is not official. FastMCP builds each tool's output schema from it, so it is patched by hand where it disagrees with real responses (found by calling every tool live):

- `CryptoTopOfBook.topOfBookData` and `CryptoPrices.priceData` are arrays of objects, not single objects.
- Every `IexTopOfBook` field except `ticker` is nullable: quotes are null outside market hours.
- `FundamentalsStatementData` is an object with one list of `DataCodeValue` pairs per statement section, not a single pair.
- `DailyMeta.startDate` and `endDate` (null when there is no price data) and `FundamentalsMeta.dailyLastUpdated` and `statementLastUpdated` are nullable.

After a spec refresh, call every tool against the live API and re-apply or drop these.
