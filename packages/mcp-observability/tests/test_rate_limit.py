import mcp_types as mt
import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult

import mcp_observability.rate_limit as rl
from mcp_observability import RateLimitMiddleware


def _make_context() -> MiddlewareContext[mt.CallToolRequestParams]:
    return MiddlewareContext(message=mt.CallToolRequestParams(name="greet", arguments={}))


async def _noop_next(_ctx: MiddlewareContext[mt.CallToolRequestParams]) -> ToolResult:
    return ToolResult(content=[])


async def _invoke(middleware: RateLimitMiddleware, subject: str | None) -> None:
    """Call on_call_tool with a fixed subject, bypassing the real token context."""
    original = rl._subject
    rl._subject = lambda: subject  # type: ignore[assignment]
    try:
        await middleware.on_call_tool(_make_context(), _noop_next)
    finally:
        rl._subject = original  # type: ignore[assignment]


async def test_calls_within_limit_succeed() -> None:
    middleware = RateLimitMiddleware(calls_per_window=2, window_seconds=60.0)
    await _invoke(middleware, "alice")
    await _invoke(middleware, "alice")


async def test_third_call_from_same_subject_is_blocked() -> None:
    middleware = RateLimitMiddleware(calls_per_window=2, window_seconds=60.0)
    await _invoke(middleware, "bob")
    await _invoke(middleware, "bob")
    with pytest.raises(ToolError, match="Rate limit exceeded"):
        await _invoke(middleware, "bob")


async def test_different_subjects_are_throttled_independently() -> None:
    middleware = RateLimitMiddleware(calls_per_window=2, window_seconds=60.0)
    await _invoke(middleware, "subject-a")
    await _invoke(middleware, "subject-a")
    await _invoke(middleware, "subject-b")
    await _invoke(middleware, "subject-b")


async def test_calls_without_access_token_are_not_throttled() -> None:
    """Unauthenticated calls (subject=None) bypass rate limiting."""
    middleware = RateLimitMiddleware(calls_per_window=1, window_seconds=60.0)
    await _invoke(middleware, None)
    await _invoke(middleware, None)
    await _invoke(middleware, None)
