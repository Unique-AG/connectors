from collections.abc import Mapping
from typing import cast

from fastmcp import Context
from mcp.types import ElicitResult, InputRequiredResult, InputResponse
from mcp.types.version import LATEST_MODERN_VERSION


class _ModernRequest:
    protocol_version: str = LATEST_MODERN_VERSION


def modern_context(
    *, answers: Mapping[str, InputResponse] | None = None, state: str | None = None
) -> Context:
    class _Client:
        request_context: _ModernRequest = _ModernRequest()
        input_responses: Mapping[str, InputResponse] | None = answers
        request_state: str | None = state

        async def elicit(self, message: str, _response_type: object = None) -> object:
            raise AssertionError(f"a connection with no back-channel was asked {message!r}")

    return cast("Context", cast("object", _Client()))


def accepted(first: object, choice: str) -> Context:
    """The context of a second call after the person accepted `choice` for the first."""
    assert isinstance(first, InputRequiredResult), "the question was never put to anybody"
    (key,) = first.input_requests or {}
    answer = ElicitResult(action="accept", content={"value": choice})
    return modern_context(answers={key: answer}, state=first.request_state)
