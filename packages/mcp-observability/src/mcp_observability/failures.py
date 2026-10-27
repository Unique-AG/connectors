"""How loud a failure is: WARNING when the caller or an upstream caused it, ERROR when a developer
has to act."""

import logging
from typing import ClassVar

import httpx
from fastmcp.exceptions import ToolError
from fastmcp.exceptions import ValidationError


class DeclaresFailureLevel:
    """Mixin for an exception whose level the default rule gets wrong."""

    failure_level: ClassVar[int]


def failure_level(error: BaseException) -> int:
    if isinstance(error, DeclaresFailureLevel):
        return error.failure_level
    if isinstance(error, ValidationError | httpx.TransportError):
        return logging.WARNING
    if isinstance(error, ToolError):
        # FastMCP wraps an unexpected exception as a plain `ToolError(...) from error`; a subclass
        # was raised on purpose, whatever it was raised from.
        cause = error.__cause__
        if type(error) is not ToolError or cause is None or isinstance(cause, ToolError):
            return logging.WARNING
        return failure_level(cause)
    return logging.ERROR
