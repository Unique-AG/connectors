"""Per-user tool call rate limiter for FastMCP servers."""

import asyncio
import time
from collections import defaultdict
from typing import override

import mcp_types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext
from fastmcp.server.middleware import Middleware
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult


class RateLimitMiddleware(Middleware):
    """Sliding-window per-user tool call rate limiter.

    Keyed on the access token's ``subject`` claim. Calls without an access
    token (e.g. a dev server running without auth) are passed through
    unthrottled so local development is not affected.
    """

    _calls_per_window: int
    _window_seconds: float
    _buckets: dict[str, list[float]]
    _lock: asyncio.Lock

    def __init__(
        self,
        *,
        calls_per_window: int = 60,
        window_seconds: float = 60.0,
    ) -> None:
        super().__init__()
        self._calls_per_window = calls_per_window
        self._window_seconds = window_seconds
        self._buckets = defaultdict(list)
        self._lock = asyncio.Lock()

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        subject = _subject()
        if subject is not None:
            await self._check(subject)
        return await call_next(context)

    async def _check(self, subject: str) -> None:
        now = time.monotonic()
        window_start = now - self._window_seconds
        async with self._lock:
            recent = [t for t in self._buckets[subject] if t > window_start]
            if len(recent) >= self._calls_per_window:
                raise ToolError(
                    f"Rate limit exceeded: {self._calls_per_window} tool calls per "
                    f"{int(self._window_seconds)} seconds"
                )
            recent.append(now)
            self._buckets[subject] = recent


def _subject() -> str | None:
    try:
        token = get_access_token()
    except RuntimeError:
        return None
    return token.subject if token is not None else None
