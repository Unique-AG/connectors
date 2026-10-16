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

- `mcp_openapi.upstream`: `OperationClient(spec, http)` calls an operation by its operationId. It builds the request from the spec (path, query, header and body arguments), rejects unknown or missing arguments with a `ValueError`, and parses the JSON body into a given type. `Operation(operation_id, adapter)` ties an operationId to that type. `UpstreamError` is a `ToolError`, so its text reaches the client. It carries the status, method, URL without the query string and the first 200 characters of the error body, or the path of the field that does not fit.
- `mcp_openapi.headers`: `only_headers(allowed, fixed, origin=...)` is an httpx request hook. It drops every header not in `allowed` (plus the ones a request cannot go without) and sets `fixed` only on requests to `origin`, so a redirect to another host never receives an `Authorization` header.
- `mcp_openapi.openapi`: `route_map(exposed)` exposes the listed operationIds and hides the rest, `set_tool_hints` marks generated tools read-only (GET) and open-world, `TOOL_HINTS` is the same annotation for hand-written tools, and `mcp_name(operation_id, remove_prefix="")` turns a camelCase or kebab-case operationId (`getDailyPrices`, `get-companies-kyckrId`) into a snake_case tool name. `remove_prefix` is keyword-only.
- `mcp_openapi.codegen` (needs the `codegen` extra): `generate_response_models` writes pydantic models for the responses of the listed operations, with the spec's field descriptions. `fields` trims a model to the fields a tool returns. `allow_extra_fields=True` keeps the fields the spec does not declare instead of dropping them; a field cut by `fields` then stays in the data as an untyped extra, so only the schema is trimmed. A success response written in place as an object (with fields or a map, or `allOf`/`oneOf`/`anyOf`) gets a model named after its operation (`get-companies` gives `GetCompaniesResponse`). `generate_operations` writes one `Operation` constant per operationId (`GET_COMPANIES`), typed with its model, and sorts the imports of the file it writes. The spec comes from a path or a URL. Both functions reject specs that are not valid YAML or JSON or are not OpenAPI 3.0, operationIds that are not in the spec, and operationIds that would make an invalid, non-ASCII or repeated name. `generate_operations` also rejects an operation whose success response has no JSON body, or is not an object, a named schema or an array of one. `generate_response_models` also rejects a `fields` key that names a model it does not generate.

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
