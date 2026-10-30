# Settings and telemetry

[`ARCHITECTURE.md`](../ARCHITECTURE.md) holds the rules this guide works within.

## Settings

What every MCP configures the same way comes from `packages/mcp-configs`, with the defaults we
always use: the server, Postgres, Redis, Zitadel, upstream retries, logging, tracing and
elicitation.
Never write your own class for these. [The mcp-configs README](../../mcp-configs/README.md) lists
each class with its env variables and defaults.

Build a settings class with a required field as `from_environment(UpstreamSettings)`, from
`mcp_configs`, rather than `UpstreamSettings()`: the type check cannot see that the environment
gives the field, and rejects the call.

A tool that elicits reads `ElicitationSettings` before it asks. It skips the question when the
toggle for its kind (`for_disambiguation`, `for_data_modification` or `for_data_removal`) is
`disabled`, and stops waiting after `timeout_before_cancel_seconds`.

What is particular to one MCP stays in the layer that owns it, such as `UpstreamSettings` in
`upstream`, built on `shared_config` so it reads the environment the same way. `.env.example`
documents every variable. `main.py` builds the settings and passes them in, so tests pass their
own.

## Telemetry

`telemetry/setup.py` sets it up under the MCP's name, with `packages/mcp-observability`:

- `init_telemetry(settings)` runs first in `main`, before anything logs: JSON logs in the format
  Loki expects, with trace ids, and OpenTelemetry tracing, off unless `mcp_configs.TracingSettings`
  finds it turned on in the environment.
- `instrument(mcp)` mounts the `/probe`, `/health` and `/metrics` routes and returns the
  metrics middleware that `http_middleware` lists. Every tool, resource and prompt call gets a
  counter, a duration and a log line.

A metric of the MCP's own, such as upstream calls by route, is defined here with
`mcp_observability.MetricNamespace` and exported from `telemetry/__init__.py`.

## Tracing and logging in the code

Nothing goes on a span or in a log line unless the code declares it, and nothing that names a
person or quotes a payload goes there in clear. `mcp_observability` has every piece below; its
[README](../../mcp-observability/README.md) says what each one writes.

- A tool declares the arguments worth seeing with `@trace_arguments` under its `@tool`, as
  `get_price_performance` does with `@trace_arguments("ticker", "start_date", "end_date")`. They go
  on FastMCP's `tools/call <tool>` span as `tool.argument.<name>`, and on the `Tool call started`
  and `completed`, `failed` or `cancelled` lines of `ToolCallObservabilityMiddleware`, the
  outermost middleware `create_server` installs. A tool logs no start or end of its own.
- A context with a step worth its own span gets `@traced`: a child span named after the function,
  with `arguments` as `input.<name>` and what `result` computes as `result.<name>`. The demo's
  `get_price_performance` context traces its period and the number of trading days it found.
- An argument is a name or a dotted path into a pydantic input, such as `"order.order_id"` for
  an `order` argument. `create_server` runs `validate_trace_declarations()`, so a name that does
  not exist fails at startup. A lambda computes a value, such as a count, and is not checked.
  Declare ids, dates, enums and counts, never free text, a note or a payload.
- A value that names a person, such as a login, an email or a search term, goes in
  `identifying=` on a span, or through `identifiable_value(value)` in a log line, which hashes it.
  Until `telemetry/setup.py` calls `configure_identifiable_values` with a secret the MCP derives
  from a key it holds, the hash is plain SHA-256, which a list of guesses can match.
- A log line is a fixed sentence, and its values go in `extra`, so every occurrence has the same
  message to search and count: `_logger.warning("Left a position unpriced: Tiingo did not answer
  its latest close", extra={"ticker": ticker}, exc_info=True)`. Never put `str(error)` in the
  message or in `extra`, where it can quote the upstream's response. Pass `exc_info=True`, and the
  output adds `error_type`.
- An upstream error or a timeout the code copes with is a WARNING, a bug an ERROR. Log once per
  call, not once per row: count the rows that failed in `extra`.
