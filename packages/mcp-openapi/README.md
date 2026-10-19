# mcp-openapi

Shared building blocks for MCP servers that expose a third-party API described by an OpenAPI spec, built on `FastMCP.from_openapi`. Nothing in it is specific to one vendor. [`exp-tiingo-mcp`](../../services/exp-tiingo-mcp) is the reference consumer.

## Install

In a service's `pyproject.toml`:

```toml
dependencies = ["mcp-openapi==0.1.0"]

[dependency-groups]
dev = ["mcp-openapi[codegen]==0.1.0"]  # only the script that regenerates models needs the extra

[tool.uv.sources]
mcp-openapi = { path = "../../packages/mcp-openapi" }
```

A service Dockerfile has to `COPY packages/mcp-openapi` before `uv sync`, like `backstop-mcp` does for `mcp-credential-auth`.

## Modules

- `mcp_openapi.upstream`: `OperationClient(spec, http)` calls an operation by its operationId. It builds the request from the spec (path, query, header and body arguments), rejects unknown or missing arguments with a `ValueError`, and parses the JSON body into a given type. `Operation(operation_id, adapter)` ties an operationId to that type. `UpstreamError` is a `ToolError`, so its text reaches the client. It carries the status, method, URL without the query string and the first 200 characters of the error body, or the path of the field that does not fit. `request_raw(method, path, schema, params=..., json=...)` is only for endpoints the spec does not document: it sends a path relative to the base URL through the same client, so auth, hooks, retries, locks and error mapping are the same, and parses the body into `schema`. Nothing checks its arguments, and anything but a path is a `ValueError`. `retry_policy=` (keyword-only, default `None`) takes any `RetryPolicy`. Without one each request is sent once. `lock_policy=` (keyword-only, default `None`) takes a `LockPolicy`. Its lock is held around each attempt and released while a retry waits. Only acquiring the lock is timed: a request that does not get it within `acquire_timeout_seconds` fails with `LockTimeoutError`, an `UpstreamError`.
- `mcp_openapi.retry`: `RetryPolicy` is a protocol with one method, `retrying()`, which returns a new tenacity `AsyncRetrying` for each request. `RetryAfterPolicy()` is a ready-made one. It retries a 429 or 503 (`statuses`) after the delay `Retry-After` asks for, in seconds or as an HTTP-date. Without the header it waits for `backoff` (default: exponential with jitter, starting at 1s), capped at `max_wait_seconds` (default 30). It does not retry a response that asks for more than that ceiling, and it stops after `max_attempts` (default 5). It only sees errors raised by `raise_for_status`, so a response hook that raises its own exception skips retries.
- `mcp_openapi.lock`: `RequestLock` is a protocol with one method, `hold(request)`, which returns an async context manager. `request` is the outgoing `httpx2.Request`, with the method, URL, query, body and the client's default headers, so a lock can be keyed on the caller's `Authorization` header or read the caller from a context variable. The client cancels entering it when it outlasts the timeout, so an implementation must not leave the lock taken then. `LockPolicy(lock=..., acquire_timeout_seconds=...)` pairs a lock with that timeout. The package ships no lock. An `asyncio.Semaphore`, a Postgres advisory lock or a Redis lock each fits behind `hold`.
- `mcp_openapi.headers`: `only_headers(allowed, fixed, origin=...)` is an httpx request hook. It drops every header not in `allowed` (plus the ones a request cannot go without) and sets `fixed` only on requests to `origin`, so a redirect to another host never receives an `Authorization` header.
- `mcp_openapi.openapi`: `route_map(exposed)` exposes the listed operationIds and hides the rest, `set_tool_hints` marks generated tools read-only (GET) and open-world, `TOOL_HINTS` is the same annotation for hand-written tools, and `mcp_name(operation_id, remove_prefix="")` turns a camelCase or kebab-case operationId (`getDailyPrices`, `get-companies-kyckrId`) into a snake_case tool name. `remove_prefix` is keyword-only.
- `mcp_openapi.codegen` (needs the `codegen` extra): `generate_response_models` writes pydantic models for the responses of the listed operations, with the spec's field descriptions. `fields` trims a model to the fields a tool returns. `allow_extra_fields=True` keeps the fields the spec does not declare instead of dropping them; a field cut by `fields` then stays in the data as an untyped extra, so only the schema is trimmed. A success response written in place as an object (with fields or a map, or `allOf`/`oneOf`/`anyOf`) gets a model named after its operation (`get-companies` gives `GetCompaniesResponse`). `generate_operations` writes one `Operation` constant per operationId (`GET_COMPANIES`), typed with its model, and sorts the imports of the file it writes. The spec comes from a path or a URL. Both functions reject specs that are not valid YAML or JSON or are not OpenAPI 3.0, operationIds that are not in the spec, and operationIds that would make an invalid, non-ASCII or repeated name. `generate_operations` also rejects an operation whose success response has no JSON body, or is not an object, a named schema or an array of one. `generate_response_models` also rejects a `fields` key that names a model it does not generate.

## Codegen command

`uv run mcp-openapi-codegen [project-dir]` (needs the `codegen` extra) runs both generators from the `[tool.mcp-openapi]` table of the service's `pyproject.toml`. Paths are relative to the folder that holds it, and an unknown key is an error. `operation-ids`, `response-operation-ids` and `fields` can be written out or be a `"module:NAME"` reference to a value in the service's code, which is imported, so it lives in one place. `fields` written out is a `[tool.mcp-openapi.fields]` sub-table of `Model = ["field", ...]`.

```toml
[tool.mcp-openapi]
spec = "src/my_mcp/openapi/spec.yml"  # or spec-url = "https://..."
operation-ids = ["getThing"]          # one Operation constant each
response-operation-ids = "my_mcp.openapi.routes:RESPONSE_MODELS"  # optional, models for these; defaults to operation-ids
allow-extra-fields = true             # optional, default false
operation-module = "mcp_openapi.upstream"
models-module = "my_mcp.models.vendor_responses"
models-output = "src/my_mcp/models/vendor_responses.py"
operations-output = "src/my_mcp/models/operations.py"
fields = "my_mcp.openapi.fields:RESPONSE_FIELDS"  # optional, trims a model to these fields
```

## Working on the package from a service

A service installs the package as a copy, so an edit in `packages/mcp-openapi` is not seen until `uv sync --reinstall-package mcp-openapi`. To run a service against the live source without changing any config, use `uv run --with-editable ../../packages/mcp-openapi pytest` from the service folder.

## Checks

```sh
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run basedpyright
```

CI runs the same sequence in this folder, and also runs every service that depends on the package.
