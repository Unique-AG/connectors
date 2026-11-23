from unittest.mock import MagicMock
from unittest.mock import patch

import mcp_types as mt
import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from mcp_configs import RateLimitSettings

from mcp_observability import RateLimitMiddleware
from mcp_observability import access_token_subject


def _context(key: str) -> MiddlewareContext[mt.CallToolRequestParams]:
    return MiddlewareContext(message=mt.CallToolRequestParams(name="greet", arguments={"key": key}))


def _key_from_arguments(context: MiddlewareContext[mt.CallToolRequestParams]) -> str:
    match context.message.arguments:
        case {"key": str(key)}:
            return key
        case _:
            raise AssertionError("every test call names its key")


async def _done(context: MiddlewareContext[mt.CallToolRequestParams]) -> ToolResult:
    del context
    return ToolResult(content=[])


def _limiter() -> RateLimitMiddleware:
    settings = RateLimitSettings(tool_calls_per_window=2, window_seconds=60)
    return RateLimitMiddleware(settings, get_request_key=_key_from_arguments)


async def _call(middleware: RateLimitMiddleware, key: str) -> None:
    await middleware.on_call_tool(_context(key), _done)


async def test_calls_within_the_limit_succeed() -> None:
    middleware = _limiter()

    await _call(middleware, "alice")
    await _call(middleware, "alice")


async def test_the_call_over_the_limit_of_its_key_is_rejected() -> None:
    middleware = _limiter()
    await _call(middleware, "bob")
    await _call(middleware, "bob")

    with pytest.raises(ToolError, match="Rate limit exceeded: 2 tool calls per 60 seconds"):
        await _call(middleware, "bob")


async def test_each_key_has_its_own_limit() -> None:
    middleware = _limiter()
    await _call(middleware, "subject-a")
    await _call(middleware, "subject-a")

    await _call(middleware, "subject-b")
    await _call(middleware, "subject-b")


def test_access_token_subject_is_the_verified_token_subject() -> None:
    token = MagicMock()
    token.subject = "user-123"
    with patch("mcp_observability.rate_limit.get_access_token", return_value=token):
        assert access_token_subject(_context("ignored")) == "user-123"


def test_access_token_subject_refuses_a_call_without_a_verified_token() -> None:
    with (
        patch("mcp_observability.rate_limit.get_access_token", return_value=None),
        pytest.raises(RuntimeError, match="without a verified token"),
    ):
        access_token_subject(_context("ignored"))
