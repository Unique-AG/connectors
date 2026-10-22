"""How loud a failure is: WARNING when the service coped or the caller caused it, ERROR when a
developer has to act.
"""

import logging
from typing import ClassVar

import httpx
from fastmcp.exceptions import ToolError, ValidationError


class DeclaresFailureLevel:
    """Mixin for an exception whose level the default rule gets wrong."""

    failure_level: ClassVar[int]


def failure_level(exc: BaseException) -> int:
    if isinstance(exc, DeclaresFailureLevel):
        return exc.failure_level
    if isinstance(exc, ValidationError | httpx.TransportError):
        return logging.WARNING
    if isinstance(exc, ToolError):
        # FastMCP wraps an unexpected exception as `ToolError(...) from exc`.
        cause = exc.__cause__
        if cause is None or isinstance(cause, ToolError):
            return logging.WARNING
        return failure_level(cause)
    return logging.ERROR
