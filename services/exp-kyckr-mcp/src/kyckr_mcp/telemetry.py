import re
import time
from collections.abc import Mapping

import httpx2
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from unique_toolkit.monitoring import MetricNamespace

ROUTES = (
    (re.compile(r"/companies/[^/]+/enhanced$"), "/companies/:kyckrId/enhanced"),
    (re.compile(r"/companies/[^/]+/lite$"), "/companies/:kyckrId/lite"),
    (re.compile(r"/companies/[^/]+/documents$"), "/companies/:kyckrId/documents"),
    (re.compile(r"/companies$"), "/companies"),
    (re.compile(r"/orders/[^/]+/download$"), "/orders/:orderId/download"),
    (re.compile(r"/orders/[^/]+$"), "/orders/:orderId"),
    (re.compile(r"/orders$"), "/orders"),
)
PAID_ROUTES = frozenset(
    {
        ("GET", "/companies/:kyckrId/lite"),
        ("GET", "/companies/:kyckrId/enhanced"),
        ("POST", "/orders"),
    }
)
START = "kyckr_start"

_metrics = MetricNamespace("kyckr")
_requests = _metrics.counter(
    "api_requests_total", "Kyckr API requests", ["method", "path", "status"]
)
_duration = _metrics.histogram(
    "api_request_duration_seconds", "Kyckr API request duration", ["method", "path"]
)
_credits = _metrics.counter(
    "credits_consumed_total", "Kyckr credits consumed by paid calls", ["method", "path"]
)
_tracer = trace.get_tracer("kyckr_mcp")


def route_template(path: str) -> str:
    return next((template for pattern, template in ROUTES if pattern.search(path)), "[unknown]")


def credit_cost(body: object) -> float:
    if not isinstance(body, Mapping):
        return 0
    data = body.get("data")
    for holder in (body, data if isinstance(data, Mapping) else {}):
        cost = holder.get("cost")
        value = cost.get("value") if isinstance(cost, Mapping) else None
        if isinstance(value, int | float):
            return value
    return 0


async def start_upstream_call(request: httpx2.Request) -> None:
    request.extensions[START] = time.perf_counter()


async def record_upstream_call(response: httpx2.Response) -> None:
    request = response.request
    method = request.method
    route = route_template(request.url.path)
    status = response.status_code
    elapsed = time.perf_counter() - request.extensions[START]
    _requests.labels(method=method, path=route, status=str(status)).inc()
    _duration.labels(method=method, path=route).observe(elapsed)
    end_ns = time.time_ns()
    span = _tracer.start_span(
        f"{method} {route}",
        kind=SpanKind.CLIENT,
        attributes={
            "http.request.method": method,
            "url.template": route,
            "http.response.status_code": status,
        },
        start_time=end_ns - int(elapsed * 1e9),
    )
    if status >= 400:
        span.set_status(Status(StatusCode.ERROR))
    span.end(end_time=end_ns)
    if response.is_success and (method, route) in PAID_ROUTES:
        await response.aread()
        try:
            cost = credit_cost(response.json())
        except ValueError:
            return
        _credits.labels(method=method, path=route).inc(cost)
