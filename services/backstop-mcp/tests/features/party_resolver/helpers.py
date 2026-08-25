from collections.abc import Awaitable, Callable
from typing import cast

from fastmcp import Context
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.server.elicitation import CancelledElicitation, DeclinedElicitation
from mcp.types import ClientCapabilities

from tests.helpers import BASE_URL, collection, credential, resource

__all__ = [
    "BASE_URL",
    "collection",
    "credential",
    "ctx_accept",
    "ctx_cancel",
    "ctx_decline",
    "ctx_never_elicit",
    "ctx_no_elicitation_capability",
    "ctx_unsupported",
    "resource",
]

type ElicitFn = Callable[..., Awaitable[object]]


class FakeSession:
    """Stands in for the MCP `ServerSession`'s capability probe.

    `resolution.client_supports_elicitation` goes through FastMCP's public `request_context`
    → `session.check_client_capability`, so the fake has to provide that rather than rely on
    the resolver defaulting to "try it and see".
    """

    _supports_elicitation: bool

    def __init__(self, supports_elicitation: bool) -> None:
        self._supports_elicitation = supports_elicitation

    def check_client_capability(self, capability: ClientCapabilities) -> bool:
        if capability.elicitation is not None:
            return self._supports_elicitation
        return True


class FakeRequestContext:
    def __init__(self, session: FakeSession) -> None:
        self.session: FakeSession = session


class FakeContext:
    """Duck-typed stand-in for FastMCP Context: a capability probe plus `elicit`."""

    def __init__(self, elicit: ElicitFn, *, supports_elicitation: bool = True) -> None:
        self._elicit: ElicitFn = elicit
        self.request_context: FakeRequestContext = FakeRequestContext(
            FakeSession(supports_elicitation)
        )

    async def elicit(self, *, message: str, response_type: object) -> object:
        return await self._elicit(message=message, response_type=response_type)


def as_context(fake: FakeContext) -> Context:
    return cast("Context", cast("object", fake))


def ctx_accept(label: str) -> Context:
    async def elicit(*, message: str, response_type: object) -> AcceptedElicitation[str]:
        _ = message, response_type
        return AcceptedElicitation(data=label)

    return as_context(FakeContext(elicit))


def ctx_decline() -> Context:
    async def elicit(*, message: str, response_type: object) -> DeclinedElicitation:
        _ = message, response_type
        return DeclinedElicitation()

    return as_context(FakeContext(elicit))


def ctx_cancel() -> Context:
    async def elicit(*, message: str, response_type: object) -> CancelledElicitation:
        _ = message, response_type
        return CancelledElicitation()

    return as_context(FakeContext(elicit))


def ctx_unsupported() -> Context:
    """A client that advertises elicitation but blows up when actually asked."""

    async def elicit(*, message: str, response_type: object) -> object:
        _ = message, response_type
        raise RuntimeError("elicitation not supported")

    return as_context(FakeContext(elicit))


def ctx_no_elicitation_capability() -> Context:
    """A client that never advertised the elicitation capability at initialization."""

    async def elicit(*, message: str, response_type: object) -> object:
        _ = message, response_type
        raise AssertionError("elicit must not be called without the capability")

    return as_context(FakeContext(elicit, supports_elicitation=False))


def ctx_never_elicit() -> Context:
    async def elicit(*, message: str, response_type: object) -> object:
        _ = message, response_type
        raise AssertionError("elicit must not be called")

    return as_context(FakeContext(elicit))
