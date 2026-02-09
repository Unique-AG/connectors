from typing import override

import structlog
from opentelemetry import trace
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response


class TraceContextMiddleware(BaseHTTPMiddleware):
    EXCLUDED_PATHS: list[str] = ["/probe", "/health", "/metrics"]

    @override
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if request.url.path in self.EXCLUDED_PATHS:
            return await call_next(request)

        structlog.contextvars.clear_contextvars()

        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            # 32-character zero-padded hex string
            structlog.contextvars.bind_contextvars(trace_id=format(ctx.trace_id, "032x"))

        return await call_next(request)
