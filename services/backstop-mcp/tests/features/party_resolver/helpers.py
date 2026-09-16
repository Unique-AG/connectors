import asyncio
from collections.abc import Awaitable, Callable
from typing import cast

from fastmcp import Context
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.server.elicitation import CancelledElicitation, DeclinedElicitation
from mcp.types import ClientCapabilities, ElicitResult

from backstop_mcp.backstop_client import BackstopClient
from backstop_mcp.features.elicitation_utils import DELETION_INPUT_KEY
from backstop_mcp.features.party_resolver import GetPartyNameQuery, ResolvePartyQuery
from tests.helpers import BASE_URL, collection, credential, resource

__all__ = [
    "BASE_URL",
    "collection",
    "credential",
    "ctx_accept",
    "ctx_cancel",
    "ctx_decline",
    "ctx_deletion_answer",
    "ctx_guard_ask",
    "ctx_handshake_era",
    "ctx_never_elicit",
    "ctx_no_elicitation_capability",
    "ctx_stalls",
    "ctx_unsupported",
    "make_get_party_name_query",
    "make_resolve_party_query",
    "resource",
]


def make_get_party_name_query(client: BackstopClient) -> GetPartyNameQuery:
    return GetPartyNameQuery(client=client)


def make_resolve_party_query(client: BackstopClient) -> ResolvePartyQuery:
    return ResolvePartyQuery(client=client, get_party_name_query=make_get_party_name_query(client))


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
    def __init__(self, session: FakeSession, *, protocol_version: str | None = None) -> None:
        self.session: FakeSession = session
        self.protocol_version: str | None = protocol_version


class FakeContext:
    """Duck-typed stand-in for FastMCP Context: a capability probe plus `elicit`."""

    def __init__(
        self,
        elicit: ElicitFn,
        *,
        supports_elicitation: bool = True,
        protocol_version: str | None = None,
        input_responses: object | None = None,
    ) -> None:
        self._elicit: ElicitFn = elicit
        self.request_context: FakeRequestContext = FakeRequestContext(
            FakeSession(supports_elicitation), protocol_version=protocol_version
        )
        self.input_responses: object | None = input_responses

    async def elicit(self, *, message: str, response_type: object) -> object:
        return await self._elicit(message=message, response_type=response_type)


def as_context(fake: FakeContext) -> Context:
    return cast("Context", cast("object", fake))


def ctx_accept(value: object) -> Context:
    async def elicit(*, message: str, response_type: object) -> AcceptedElicitation[object]:
        _ = message, response_type
        return AcceptedElicitation(data=value)

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


def ctx_stalls() -> Context:
    """A client that accepts the prompt and never answers it.

    This is the shape the production incident took: elicitation is advertised, the request is
    delivered, and no response ever comes back on its own.
    """

    async def elicit(*, message: str, response_type: object) -> object:
        _ = message, response_type
        await asyncio.Event().wait()
        raise AssertionError("unreachable: the event is never set")

    return as_context(FakeContext(elicit))


def ctx_guard_ask() -> Context:
    """A 2026-07-28 client: capability is on, but `ctx.elicit` must not be pushed."""

    async def elicit(*, message: str, response_type: object) -> object:
        _ = message, response_type
        raise AssertionError("ctx.elicit must not be called on a 2026-07-28 connection")

    return as_context(FakeContext(elicit, protocol_version="2026-07-28"))


def ctx_handshake_era() -> Context:
    """A 2025-11-25 client that advertises elicitation but cannot take InputRequiredResult."""

    async def elicit(*, message: str, response_type: object) -> object:
        _ = message, response_type
        raise AssertionError("ctx.elicit must not be called on a handshake-era connection")

    return as_context(FakeContext(elicit, protocol_version="2025-11-25"))


def ctx_no_elicitation_capability() -> Context:
    """A client that never advertised the elicitation capability at initialization."""

    async def elicit(*, message: str, response_type: object) -> object:
        _ = message, response_type
        raise AssertionError("elicit must not be called without the capability")

    return as_context(FakeContext(elicit, supports_elicitation=False))


def ctx_deletion_answer(result: ElicitResult) -> Context:
    """Retry after `InputRequiredResult`: answers are in `input_responses`, not `ctx.elicit`."""

    async def elicit(*, message: str, response_type: object) -> object:
        _ = message, response_type
        raise AssertionError("ctx.elicit must not be called when input_responses are present")

    return as_context(FakeContext(elicit, input_responses={DELETION_INPUT_KEY: result}))


def ctx_never_elicit() -> Context:
    """A 2026-07-28 client: return InputRequiredResult; never push ctx.elicit."""

    async def elicit(*, message: str, response_type: object) -> object:
        _ = message, response_type
        raise AssertionError("elicit must not be called")

    return as_context(FakeContext(elicit, protocol_version="2026-07-28"))
