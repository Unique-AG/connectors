from collections.abc import Awaitable, Callable
from typing import cast

from fastmcp import Context
from fastmcp.server.elicitation import AcceptedElicitation
from mcp.server.elicitation import CancelledElicitation, DeclinedElicitation
from pydantic import SecretStr

from backstop_mcp.auth.crypto import BackstopCredentialSecret

BASE_URL = "https://example.backstopsolutions.com"

type ElicitFn = Callable[..., Awaitable[object]]


class FakeContext:
    """Duck-typed stand-in for FastMCP Context; only `elicit` is used by the resolver."""

    _elicit: ElicitFn

    def __init__(self, elicit: ElicitFn) -> None:
        self._elicit = elicit

    async def elicit(self, *, message: str, response_type: object) -> object:
        return await self._elicit(message=message, response_type=response_type)


def as_context(fake: FakeContext) -> Context:
    return cast(Context, cast(object, fake))


def credential() -> BackstopCredentialSecret:
    return BackstopCredentialSecret(username="bob.smith", api_token=SecretStr("token"))


def resource(id: str, type: str, name: str | None = None, **attrs: object) -> dict[str, object]:
    attributes: dict[str, object] = {**attrs}
    if name is not None:
        attributes["name"] = name
    return {"type": type, "id": id, "attributes": attributes}


def collection(*resources: dict[str, object]) -> dict[str, object]:
    return {"data": list(resources)}


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
    async def elicit(*, message: str, response_type: object) -> object:
        _ = message, response_type
        raise RuntimeError("elicitation not supported")

    return as_context(FakeContext(elicit))


def ctx_never_elicit() -> Context:
    async def elicit(*, message: str, response_type: object) -> object:
        _ = message, response_type
        raise AssertionError("elicit must not be called")

    return as_context(FakeContext(elicit))
