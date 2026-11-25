from collections.abc import Mapping
import logging
import math
import re
import time
from typing import cast, override
import weakref

import httpx2
from opentelemetry import trace
from opentelemetry.trace import SpanKind
from opentelemetry.trace import Status
from opentelemetry.trace import StatusCode

from kyckr_mcp.telemetry import credits_consumed
from kyckr_mcp.telemetry import upstream_duration_ms
from kyckr_mcp.telemetry import upstream_requests
from kyckr_mcp.telemetry import upstream_retries

# The labels the NestJS kyckr-mcp wrote, so its dashboards keep working. Matched against the raw
# path, so an id with an encoded slash stays one segment, after the optional `/v2` of `api_url`.
_ROUTES = (
    (re.compile(r"^(?:/v\d+)?/companies/[^/]+/enhanced$"), "/companies/:kyckrId/enhanced"),
    (re.compile(r"^(?:/v\d+)?/companies/[^/]+/lite$"), "/companies/:kyckrId/lite"),
    (re.compile(r"^(?:/v\d+)?/companies/[^/]+/documents$"), "/companies/:kyckrId/documents"),
    (re.compile(r"^(?:/v\d+)?/companies$"), "/companies"),
    (re.compile(r"^(?:/v\d+)?/orders/[^/]+/download$"), "/orders/:orderId/download"),
    (re.compile(r"^(?:/v\d+)?/orders/[^/]+$"), "/orders/:orderId"),
    (re.compile(r"^(?:/v\d+)?/orders$"), "/orders"),
)
# The tool each paid call serves, the label the credits counter had in the NestJS service.
_PAID_TOOLS = {
    ("GET", "/companies/:kyckrId/lite"): "get_lite_profile",
    ("GET", "/companies/:kyckrId/enhanced"): "get_enhanced_profile",
    ("POST", "/orders"): "create_document_order",
    ("GET", "/orders/:orderId"): "get_order",
}
_tracer = trace.get_tracer("kyckr_mcp")
_log = logging.getLogger(__name__)


def route_template(path: str) -> str:
    return next((template for pattern, template in _ROUTES if pattern.match(path)), "[unknown]")


def _route(request: httpx2.Request) -> str:
    return route_template(request.url.raw_path.partition(b"?")[0].decode("ascii"))


def _mapping(value: object) -> Mapping[str, object]:
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else {}


def credit_cost(body: object) -> float:
    """The `cost.value` of an answer. A value that is not a finite number of at least 0 is no
    cost, since a counter rejects it and the call has been paid.
    """
    top = _mapping(body)
    for holder in (top, _mapping(top.get("data"))):
        value = _mapping(holder.get("cost")).get("value")
        if isinstance(value, int | float) and not isinstance(value, bool):
            return value if 0 <= value < math.inf else 0
    return 0


class RecordedTransport(httpx2.AsyncBaseTransport):
    """Counts, times and traces each request to Kyckr, a retry included. One that gets no
    answer, such as a timeout, counts with status `0`.
    """

    def __init__(self, transport: httpx2.AsyncBaseTransport) -> None:
        self._transport: httpx2.AsyncBaseTransport = transport
        # The retry loop sends one request object again, so a second sight of it is a retry.
        self._sent: weakref.WeakSet[httpx2.Request] = weakref.WeakSet()

    @override
    async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
        method = request.method
        route = _route(request)
        if request in self._sent:
            upstream_retries.labels(method=method, path=route).inc()
        self._sent.add(request)
        status = 0
        started = time.perf_counter()
        with _tracer.start_as_current_span(
            f"{method} {route}",
            kind=SpanKind.CLIENT,
            attributes={"http.request.method": method, "url.template": route},
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                response = await self._transport.handle_async_request(request)
                status = response.status_code
                span.set_attribute("http.response.status_code", status)
                if status >= 400:
                    _log.warning(
                        "Kyckr answered with an error",
                        extra={"method": method, "path": route, "status": status},
                    )
                return response
            except httpx2.HTTPError:
                _log.warning(
                    "Kyckr request failed",
                    extra={"method": method, "path": route, "status": status},
                    exc_info=True,
                )
                raise
            finally:
                if status == 0 or status >= 400:
                    span.set_status(Status(StatusCode.ERROR))
                elapsed_ms = (time.perf_counter() - started) * 1000
                upstream_requests.labels(method=method, path=route, status=str(status)).inc()
                upstream_duration_ms.labels(method=method, path=route).observe(elapsed_ms)

    @override
    async def aclose(self) -> None:
        await self._transport.aclose()


async def record_credits(response: httpx2.Response) -> None:
    """Adds the `cost.value` of a successful paid call to the credits counter."""
    tool = _PAID_TOOLS.get((response.request.method, _route(response.request)))
    if tool is None or not response.is_success:
        return
    await response.aread()
    try:
        body = cast(object, response.json())
    except ValueError:
        return
    credits_consumed.labels(tool=tool).inc(credit_cost(body))
