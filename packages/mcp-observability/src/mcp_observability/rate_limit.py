"""Per-key tool call rate limiter for FastMCP servers."""

import asyncio
import time
from collections import defaultdict
from collections.abc import Callable
from typing import override

import mcp_types as mt
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_access_token
from fastmcp.server.middleware import CallNext
from fastmcp.server.middleware import Middleware
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from mcp_configs import RateLimitSettings

type RequestKey = Callable[[MiddlewareContext[mt.CallToolRequestParams]], str]


def access_token_subject(context: MiddlewareContext[mt.CallToolRequestParams]) -> str:
    """The `subject` of the access token FastMCP's auth provider verified for this call."""
    del context
    token = get_access_token()
    subject = token.subject if token is not None else None
    if subject is None:
        raise RuntimeError("A rate-limited tool call reached the server without a verified token")
    return subject


class RateLimitMiddleware(Middleware):
    """Sliding-window limit on the tool calls made under one key, held in this process."""

    _settings: RateLimitSettings
    _get_request_key: RequestKey
    _buckets: dict[str, list[float]]
    _lock: asyncio.Lock

    def __init__(self, settings: RateLimitSettings, *, get_request_key: RequestKey) -> None:
        super().__init__()
        self._settings = settings
        self._get_request_key = get_request_key
        self._buckets = defaultdict(list)
        self._lock = asyncio.Lock()

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        if self._settings.tool_calls_per_window > 0:
            await self._check(self._get_request_key(context))
        return await call_next(context)

    async def _check(self, key: str) -> None:
        limit = self._settings.tool_calls_per_window
        window = self._settings.window_seconds
        now = time.monotonic()
        async with self._lock:
            recent = [t for t in self._buckets[key] if t > now - window]
            if len(recent) >= limit:
                raise ToolError(
                    f"Rate limit exceeded: {limit} tool calls per {int(window)} seconds"
                )
            recent.append(now)
            self._buckets[key] = recent
