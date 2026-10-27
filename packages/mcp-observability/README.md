# mcp-observability

What every Python MCP server reports, the same way: Pino-JSON logs, OpenTelemetry tracing,
Prometheus metrics, and the routes Kubernetes and Prometheus call. A scaffolded MCP calls it from
`telemetry/setup.py`.

## What it gives

- `configure_logging(level)`: every log record on stderr as one Pino-JSON line, which Loki parses
  under the `pino-json` label, with the trace and span of the call and the fields passed in
  `extra`. The access log lines of the ops routes are dropped.
- `configure_tracing(settings, service_name=..., service_version=...)`: the trace provider
  `mcp_configs.TracingSettings` asks for, off unless the environment turns it on, with W3C trace
  context and baggage propagation.
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
