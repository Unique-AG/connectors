from mcp_observability import MetricNamespace

# OpenTelemetry's default millisecond buckets, which the NestJS service used, up to the
# longest timeout the chart allows.
_DURATION_BUCKETS_MS = (
    *(0, 5, 10, 25, 50, 75, 100, 250, 500, 750, 1000, 2500, 5000, 7500, 10000),
    *(30000, 60000, 120000),
)

_metrics = MetricNamespace("kyckr")
upstream_requests = _metrics.counter(
    "api_requests_total", "Kyckr API requests", ["method", "path", "status"]
)
upstream_duration_ms = _metrics.histogram(
    "api_request_duration_ms",
    "Kyckr API request duration in milliseconds",
    ["method", "path"],
    buckets=_DURATION_BUCKETS_MS,
)
upstream_retries = _metrics.counter(
    "api_retries_total", "Kyckr API requests sent again after a failed attempt", ["method", "path"]
)
credits_consumed = _metrics.counter(
    "credits_consumed_total", "Kyckr credits consumed, by the tool that paid", ["tool"]
)
