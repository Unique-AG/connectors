import logging
from typing import ClassVar

import httpx
from fastmcp.exceptions import ToolError
from fastmcp.exceptions import ValidationError

from mcp_observability import DeclaresFailureLevel
from mcp_observability.failures import failure_level


class Revoked(Exception, DeclaresFailureLevel):
    failure_level: ClassVar[int] = logging.INFO


class UnreadableReceipt(ToolError):
    pass


def test_a_tool_error_is_a_warning() -> None:
    assert failure_level(ToolError("No till")) == logging.WARNING


def test_a_tool_error_wrapping_a_bug_is_an_error() -> None:
    try:
        raise ToolError("Error calling tool 'sell'") from KeyError("till")
    except ToolError as error:
        assert failure_level(error) == logging.ERROR


def test_a_tool_error_subclass_keeps_its_level_whatever_it_was_raised_from() -> None:
    try:
        raise UnreadableReceipt("Receipt failed our schema") from KeyError("total")
    except UnreadableReceipt as error:
        assert failure_level(error) == logging.WARNING


def test_invalid_arguments_and_a_transport_error_are_warnings() -> None:
    assert failure_level(ValidationError("bad")) == logging.WARNING
    assert failure_level(httpx.ReadTimeout("slow")) == logging.WARNING


def test_anything_else_is_an_error() -> None:
    assert failure_level(RuntimeError("bug")) == logging.ERROR


def test_a_declared_level_wins_even_behind_a_tool_error() -> None:
    try:
        raise ToolError("Error calling tool 'sell'") from Revoked()
    except ToolError as error:
        assert failure_level(error) == logging.INFO
