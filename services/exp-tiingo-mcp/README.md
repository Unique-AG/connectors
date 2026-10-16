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

1. Pass-through tools. Nine operations in `EXPOSED` become tools and one becomes a resource. FastMCP builds each tool's name, arguments and output schema from the spec. Names come from the operationId, and `set_tool_hints` marks each generated GET tool read-only, and every generated tool open-world.
2. Typed models from the spec. `uv run mcp-openapi-codegen` generates a pydantic model for each response, with the spec's field descriptions. The three tools that call the API themselves parse every response into them, so a field that does not fit fails on the server with an error naming it, and the LLM sees the model as the tool's output schema. The generated pass-through tools do not use the models; their output schema comes from FastMCP.
3. Tools that call the API themselves. `recent_daily_prices`, `recent_financials` and `recent_valuation_metrics` are standalone `@tool` functions. They get an `OperationClient` through `Depends(get_api)`, take a `lookback_days` or `periods` argument instead of dates, trim the output and get their argument checks from FastMCP. Prices keep seven fields per bar, and financials skip the full-year rows. The trimming is plain functions over the models, and a tool can be called directly with a fake client, without an MCP client.
4. A composite tool with an app. `plot_cumulative_returns` calls `recent_daily_prices` as a function for up to five tickers and returns a text summary plus structured data. A widget resource (`ui://tiingo/returns.html`) draws the chart in MCP Apps hosts.
5. The server around the tools. It sends instructions to the LLM and uses Zitadel OAuth (public client with PKCE), or no auth for local use. It checks Host and Origin on `/mcp` (the ops routes are exempt), sets CORS, runs stateless HTTP, and serves `/probe`, `/health` and `/metrics` with per-tool metrics. Logs are JSON, and settings are validated at startup.
6. Outgoing requests carry only an allow-list of headers to Tiingo (plus the ones a request cannot go without), so headers a client sends to this server, such as `Origin` or `X-Forwarded-For`, are not forwarded upstream. `Authorization` is the Tiingo key, set only on requests to the Tiingo origin, so a redirect elsewhere never receives it.
7. Tests run the tools through an in-memory client against a mocked Tiingo transport, and call the tools directly with a fake client. Ruff and basedpyright are part of the checks.

Not covered: durable OAuth storage (it is in memory, and the auth is expected to change), a deployment (there are no deploy files, container image or Helm chart), a real Zitadel login (tested only against mocked discovery), and the chart in any host other than the MCP Inspector.

## Layout

- `settings.py`: pydantic settings with a security validator. `auth.py`: Zitadel OIDC proxy from `unique_mcp`. `params.py`: argument and date types shared by the tools and models.
- `server.py` builds the server (instructions, the HTTP client and the lifespan). It fails at startup if an operationId it uses is not in the spec or a tool file cannot be loaded. `main.py` runs it and mounts `/probe`, `/health` and `/metrics` with `unique_mcp.monitoring.setup_ops` (per-tool call counts and durations included).
- `openapi/`: the spec (loaded as `SPEC` in `server.py`) and `EXPOSED`, the allow-list of operationIds served as generated tools. Anything not listed is hidden. `CLIENT_BACKED` lists the operations the tools call through `OperationClient`.
- `deps.py`: the dependencies tools declare with `Depends`: `get_api` (the `OperationClient`, which `create_server` builds and the server lifespan hands out and closes with the HTTP client). `tools/`: the tools and the widget resource. `FileSystemProvider` imports every `.py` file there and registers each `@tool` and `@resource` it finds, so there is no list to update. `fundamentals.py` holds two tools, and `returns.py` holds the chart tool and its widget.
- `models/`: pydantic output models. `vendor_responses.py` is generated from the spec, with one model per response of every operation in `EXPOSED` and `CLIENT_BACKED` (all fields optional) and the spec's field descriptions. A response the spec writes in place gets a model named after its operation (`TestConnectionResponse`). `operations.py` is generated too: one `Operation` constant per `CLIENT_BACKED` operation (`GET_DAILY_PRICES`), typed with its response model. The `[tool.mcp-openapi]` table in `pyproject.toml` holds the codegen settings, and `RESPONSE_FIELDS` in `openapi/fields.py` limits a model to the fields a tool returns (undeclared vendor fields are dropped). Regenerate with `uv run mcp-openapi-codegen` after changing the spec, `EXPOSED` or `CLIENT_BACKED`. The table reads `CLIENT_BACKED` and `RESPONSE_MODELS` from `openapi/routes.py`. The generated pass-through tools get their output schema from FastMCP, which reads the spec.
- [`mcp-openapi`](../../packages/mcp-openapi) (`packages/mcp-openapi`, a path dependency): the shared part that knows nothing about Tiingo. `OperationClient` and `Operation` call the API, `only_headers` builds the request header allow-list, `route_map`, `set_tool_hints` and `mcp_name` serve `from_openapi`, and `mcp_openapi.codegen` generates the models and `Operation` constants. Bad arguments raise a `ValueError` and a failed call raises an `UpstreamError`; the chart tool prefixes either error with the ticker.
- `apps/returns.html`: the MCP App widget.
- `tests/`: the tests.

## MCP App

`plot_cumulative_returns(tickers, lookback_days)` returns cumulative adjusted-close returns for 1 to 5 tickers and renders them as a line chart (`ui://tiingo/returns.html`). Clients without MCP Apps support get a text summary. The chart was checked in the MCP Inspector, not in other MCP Apps hosts.

## Checks

`uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .` and `uv run basedpyright` (src only).

CI also runs `pnpm exec biome check . --no-errors-on-unmatched` from this folder, which covers the widget in `apps/returns.html`. Run `pnpm install` at the repository root first, or biome is not found.

## Adding a tool

- As-is: add its operationId to the `MCPType.TOOL` group in `EXPOSED`.
- As a resource: add it to the `MCPType.RESOURCE` group (GETs without query params only; path params become a template).
- Through the API caller: add its operationId to `CLIENT_BACKED`, regenerate the models, then add a file in `tools/` with a standalone `@tool` that takes `api: OperationClient = Depends(get_api)` and calls `api.call(operations.GET_X, **arguments)`, where `GET_X` is the constant generated into `models/operations.py` (the operationId in UPPER_SNAKE_CASE). `tools/prices.py` is the template. Annotate it with `TOOL_HINTS`. The function's name and docstring become the tool's name and description.
- Names: a generated tool is named after its operationId in snake_case without a leading `get_` (`mcp_name(..., remove_prefix="get_")`), and `tests/test_routes.py` checks that the names are unique. A tool you write is named after its function.
- Composite (uses several operations): call `api.call` more than once, or call another tool's function and pass `api` yourself, because a direct call does not resolve `Depends`. Combine the results. `tools/returns.py` is the template.

Not exposed: news, splits, distributions and fund fees returned 403 on the current plan, and `getDistributionYield` returns ~780 KB (11k rows) with no trimming. The fundamentals tools only work for Dow 30 tickers on the current plan (other tickers return a 400 from Tiingo).

The spec comes from `api-evangelist/tiingo` and is not official. FastMCP builds each tool's output schema from it, so it is patched by hand where it disagrees with real responses (found by calling every tool live):

- `CryptoTopOfBook.topOfBookData` and `CryptoPrices.priceData` are arrays of objects, not single objects.
- Every `IexTopOfBook` field except `ticker` is nullable: quotes are null outside market hours.
- `FundamentalsStatementData` is an object with one list of `DataCodeValue` pairs per statement section, not a single pair.
- `DailyMeta.startDate` and `endDate` (null when there is no price data) and `FundamentalsMeta.dailyLastUpdated` and `statementLastUpdated` are nullable.

After a spec refresh, call every tool against the live API and re-apply or drop these.
