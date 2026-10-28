# mcp-observability

What every Python MCP server reports, the same way: Pino-JSON logs, OpenTelemetry tracing,
Prometheus metrics, and the routes Kubernetes and Prometheus call. A scaffolded MCP calls it from
`telemetry/setup.py`.

## What it gives

- `configure_logging(settings, own_loggers=(...))`: every log record on stderr as one Pino-JSON
  line, which Loki parses under the `pino-json` label, with the trace and span of the call and the
  fields passed in `extra`. `level` is pino's number, which the pipeline reads, and `log_level`
  its name (`debug`, `info`, `warn`, `error`, `fatal`). FastMCP and Python warnings join the same stream; run uvicorn with
  `log_config=None` so its lines do too. The access log lines of the ops routes, and of an MCP's
  own `/ready`, are dropped.
  - `LOG_LEVEL` is the level of `own_loggers` (the MCP's package). `LIBRARY_LOG_LEVELS`, a JSON
    object such as `{"httpx": "INFO"}`, sets libraries, over defaults that keep `httpx` and
    `httpcore` at WARNING (their INFO lines are request URLs) and `sse_starlette` at INFO (its
    DEBUG lines are tool results). A library not named logs at INFO.
  - A line logged with an exception names it in `error_type`. Below ERROR its stack is dropped; at
    ERROR, `err` keeps the frames and exception types but no message, which can quote a payload. A
    pydantic `ValidationError`, or one it was raised from, adds `failed_fields`: `path (error
    type, got input type)` per error, such as `data.3.title (string_type, got int)`, never the
    input itself. A tuple input is written `tuple(str, int)`, another container by the types it
    holds. At most ten are listed, and `failed_field_count` gives the total, since one broken
    field fails once per record. `ERROR_DETAILS_POLICY=disclose` keeps the message and full stack at
    ERROR.
- `configure_identifiable_values(settings, secret=...)` and `identifiable_value(value)`: a login,
  email or search term logged as `hmac-sha256:<hex>` keyed with `secret`, as plain `sha256:<hex>`
  at DEBUG, or as itself with `LOGS_DIAGNOSTICS_DATA_POLICY=disclose`. Derive `secret` from a key
  the MCP holds; never pass that key itself.
- `configure_tracing(settings, service_name=..., service_version=..., error_details_policy=...)`:
  the trace provider `mcp_configs.TracingSettings` asks for, off unless the environment turns it
  on, with W3C trace context and baggage propagation. Unless `ERROR_DETAILS_POLICY=disclose`,
  every exported span, on a provider installed before this too, loses its exception messages and
  its status description: an `exception` event keeps `exception.type` and a stack of frames and
  exception types. FastMCP records every exception a tool raises on its span, message included.
- `@traced(arguments=..., identifying=..., result=...)` opens a child span named `Class.method`,
  or the function's name, with the declared arguments as `input.<name>` and the result as
  `result.<name>`. `@trace_arguments(...)` under
  a FastMCP `@tool` puts the declared arguments on the `tools/call <tool>` span as
  `tool.argument.<name>`. An argument is a name or a dotted path into a pydantic model, checked by
  `validate_trace_declarations()` at startup, or a lambda, which is not checked. `identifying`
  values are hashed. A value that cannot go on the span is skipped with one WARNING; tracing
  never fails the call.
- `ToolCallObservabilityMiddleware(packages=(...))`: the outermost FastMCP middleware. Logs
  `Tool call started` and one of `Tool call completed`, `failed` or `cancelled` per call, with the
  values `@trace_arguments` declared, a failure at its level (an exception class can declare one
  with `DeclaresFailureLevel`) and an invalid argument as `failed_fields`. It drops FastMCP's and
  `setup_ops`'s per-call lines for a tool, which repeat it and can quote the input.
- `setup_ops(mcp)`: serves `/probe`, `/health` and `/metrics` from the server, counts, times and
  logs every tool, resource and prompt call (`mcp_calls_total`, `mcp_call_duration_seconds`), and
  returns the HTTP metrics middleware (`python_http_requests_total`,
  `python_http_requests_in_progress`, `python_http_request_duration_seconds`) for the app. The
  metric names are the ones the dashboards and alerts of every Python service read.
- `MetricNamespace(prefix)`: a metric of the MCP's own, named `<prefix>_<name>` and served at
  `/metrics`.

## Install

```toml
[project]
dependencies = ["mcp-observability==0.1.0"]

[tool.uv.sources]
mcp-observability = { path = "../../packages/mcp-observability" }
```

## Checks

```sh
uv sync
uv run poe ci     # ruff format --check, ruff check, basedpyright, pytest
```
