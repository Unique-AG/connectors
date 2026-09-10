"""Starlette 20 MB request-body cap for `attach_file`."""

from mcp.server.transport_security import RequestBodyLimitMiddleware

REQUEST_BODY_MAX_BYTES = 20 * 1024 * 1024

__all__ = [
    "REQUEST_BODY_MAX_BYTES",
    "RequestBodyLimitMiddleware",
]
