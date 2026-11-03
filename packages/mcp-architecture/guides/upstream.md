# upstream

The system the MCP fronts: its client, settings and, for OpenAPI, the spec and generated code.
[`ARCHITECTURE.md`](../ARCHITECTURE.md) holds the rules this guide works within, and the names
every `upstream/__init__.py` exports.

Empty when the MCP calls no system of its own: an `__init__.py` with an empty `__all__`, so the
layers contract still sees the layer. Otherwise what is inside depends on what the MCP talks to,
and `settings.py` reads the `UPSTREAM_` env variables either way. Adding an upstream later
means writing the client here, opening it in `server.py` and adding `get_upstream` to
`dependencies.py`.

## OpenAPI

The vendor's spec is vendored as `upstream/openapi.yml`. An operation becomes a tool in one of
two ways:

- **Served from the spec.** List its operationId in `EXPOSED` in `upstream/routes.py`.
  `upstream_tools` serves it with the name, arguments and output schema the spec gives
  (`getDailyPrices` becomes `get_daily_prices`), with no context and no code. It says what the
  spec says, so the description check skips it, and retries do not apply to it.
- **A tool of our own.** List the operationId under `operation-ids` in `[tool.mcp-openapi]`
  and run `uv run poe codegen`. It writes `vendor_responses.py` and `operations.py`
  in `upstream/generated/`; never edit that package by hand. The models name each field in
  snake_case, with the vendor's name as its alias, so they validate the vendor's JSON and read
  as Python; `snake-case-fields = false` in `[tool.mcp-openapi]` keeps the vendor's names. Export the operation's constant
  from `upstream/__init__.py`, then write a context that calls `upstream.call(GET_X, ...)` and a
  tool over it. `Upstream` is mcp-openapi's `OperationClient`, which validates arguments
  against the spec and parses each response into its generated model. On an error status it
  raises `UpstreamError` with the status, method and URL, followed by the first 200 characters
  of the error body, which reach the client.

Generate before you write. Before writing an `Operation` or a response model by hand, list the
operationId under `operation-ids` and run `uv run poe codegen`. `codegen --check` sees only what
the codegen writes, so a hand-written operation drifts from the spec unnoticed when the vendor
changes it. Write a model by hand only where the generated one does not parse what the vendor
sends. Keep it in `upstream/`, and name in its docstring the field the spec gets wrong.

A new MCP starts with its spec's first JSON operation, a GET if there is one, in both lists:
served, and typed for when it is promoted. Serve more operations to grow the first version.
Promote one when its output needs trimming or renaming, or a business rule, or when several
operations make one tool: remove it from `EXPOSED` and write the tool. An operation may also
stay served while a tool of our own builds on it: the demo serves `get_daily_prices` for the
raw bars, and `get_price_performance` turns the same `getDailyPrices` into a summary.
`upstream_http` builds the one client both kinds share, so they send the same auth: the
`UPSTREAM_API_KEY` bearer token, or with `--auth credentials` the caller's own credentials (see
[auth](auth.md)).

When the vendor changes the spec:

1. `uv run poe codegen --refresh-spec` fetches it again from `spec-source` in
   `[tool.mcp-openapi]`, writes it over `upstream/openapi.yml`, lists the operationIds added
   and removed, and regenerates. Set `spec-source` first if the MCP has none.
2. `uv run poe typecheck` names each context a changed response model breaks. Fix the
   mapping there, so the change stops at `contexts/`.
3. `uv run poe architecture` fails on `tests/tool_surface.generated.json` when a served tool's
   arguments or output changed. Read the diff, then accept it with `uv run poe surface`.

CI runs `uv run poe codegen --check`, which fails when the generated code is not what
the spec and the table generate.

## Custom

`upstream/client.py` starts as a small HTTP client, ours to change: `Upstream` has one
`request(method, path, adapter, params=..., json=...)` for any method and path. It validates
every body with the `TypeAdapter` it is given, so a context only ever receives a pydantic model,
and raises `UpstreamError` on an error status, a transport error or a body that does not fit.
The error names the status, method and URL without its query, and the start of an error body
goes to the server log only.

It sends `UPSTREAM_API_KEY` as a bearer token on every request. With `--auth credentials` it
signs each request with the caller's credentials instead (see [auth](auth.md)).

It retries with mcp-openapi's `RetryAfterPolicy`, built from `RetrySettings`: a status in
`statuses` after its `Retry-After` or a backoff, within `max_wait_seconds`, any request on a 429
and only an idempotent one on another status. For a status or header of the upstream's own,
pass `Upstream` another `RetryPolicy`.

Put the response models in `upstream/` and export them from `upstream/__init__.py`. For another
protocol (SOAP, gRPC, a vendor SDK), replace the client behind the same four names. When the
upstream limits concurrent requests, hold a lock around each attempt and release it while a
retry waits, as mcp-openapi's `LockConfig` does.
