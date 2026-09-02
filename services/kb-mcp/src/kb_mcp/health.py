"""Expose latched outbound-pool exhaustion through the health endpoints."""

import logging
from collections.abc import Callable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from kb_mcp.http_client import pool_is_exhausted

_LOGGER = logging.getLogger(__name__)

_PROBE_PATHS = frozenset({"/probe", "/health"})


class PoolHealthMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        *,
        is_unhealthy: Callable[[], bool] = pool_is_exhausted,
    ) -> None:
        self.app = app
        self._is_unhealthy = is_unhealthy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        is_probe = (
            scope["type"] == "http" and self._normalize(scope["path"]) in _PROBE_PATHS
        )
        if is_probe:
            try:
                unhealthy = self._is_unhealthy()
            except Exception:
                _LOGGER.warning(
                    "Health check raised; treating pod as healthy", exc_info=True
                )
                unhealthy = False
            if unhealthy:
                response = JSONResponse(
                    {"status": "unhealthy", "reason": "connection pool exhausted"},
                    status_code=503,
                )
                await response(scope, receive, send)
                return

        await self.app(scope, receive, send)

    @staticmethod
    def _normalize(path: str) -> str:
        return path.rstrip("/") or "/"
