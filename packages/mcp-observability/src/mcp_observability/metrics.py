"""Prometheus metrics in a registry of their own, which `/metrics` serves."""

import time
from collections.abc import Sequence
from typing import cast

from prometheus_client import CollectorRegistry
from prometheus_client import Counter
from prometheus_client import Gauge
from prometheus_client import Histogram
from prometheus_client import generate_latest
from starlette.types import ASGIApp
from starlette.types import Message
from starlette.types import Receive
from starlette.types import Scope
from starlette.types import Send

REGISTRY = CollectorRegistry()


class MetricNamespace:
    """Metrics named `<prefix>_<name>`, in `REGISTRY`.

    `MetricNamespace("weather").counter("forecasts_total", "Forecasts served", ["region"])`
    """

    def __init__(self, prefix: str) -> None:
        self._prefix: str = prefix

    def counter(self, name: str, description: str, labels: Sequence[str]) -> Counter:
        return Counter(f"{self._prefix}_{name}", description, labels, registry=REGISTRY)

    def histogram(
        self,
        name: str,
        description: str,
        labels: Sequence[str],
        buckets: Sequence[float] = Histogram.DEFAULT_BUCKETS,
    ) -> Histogram:
        """The default buckets end at 10 seconds. Pass buckets that cover anything slower, or
        `histogram_quantile` cannot resolve its tail."""
        return Histogram(
            f"{self._prefix}_{name}", description, labels, registry=REGISTRY, buckets=buckets
        )

    def gauge(self, name: str, description: str, labels: Sequence[str]) -> Gauge:
        return Gauge(f"{self._prefix}_{name}", description, labels, registry=REGISTRY)


def metrics_text() -> bytes:
    """Every metric in `REGISTRY`, in the Prometheus text format."""
    return generate_latest(REGISTRY)


# The names the dashboards and alerts of every Python service read.
_requests = Counter(
    "python_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status_code"],
    registry=REGISTRY,
)
_in_progress = Gauge(
    "python_http_requests_in_progress", "In-flight HTTP requests", ["method"], registry=REGISTRY
)
_duration = Histogram(
    "python_http_request_duration_seconds",
    "HTTP request duration",
    ["method", "path"],
    registry=REGISTRY,
)


class HttpMetricsMiddleware:
    """Counts, times and tracks in flight every HTTP request but those to `excluded_paths`. A
    request whose handler raises counts as a 500."""

    def __init__(self, app: ASGIApp, excluded_paths: frozenset[str]) -> None:
        self._app: ASGIApp = app
        self._excluded_paths: frozenset[str] = excluded_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = cast(str, scope.get("path", "/"))
        if cast(str, scope["type"]) != "http" or path in self._excluded_paths:
            await self._app(scope, receive, send)
            return
        method = cast(str, scope.get("method", "UNKNOWN"))
        status_code = "500"

        async def send_with_status(message: Message) -> None:
            nonlocal status_code
            if cast(str, message["type"]) == "http.response.start":
                status_code = str(cast(int, message["status"]))
            await send(message)

        _in_progress.labels(method=method).inc()
        start = time.perf_counter()
        try:
            await self._app(scope, receive, send_with_status)
        finally:
            _in_progress.labels(method=method).dec()
            _duration.labels(method=method, path=path).observe(time.perf_counter() - start)
            _requests.labels(method=method, path=path, status_code=status_code).inc()
