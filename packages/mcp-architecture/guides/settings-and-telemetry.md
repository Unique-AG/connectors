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
