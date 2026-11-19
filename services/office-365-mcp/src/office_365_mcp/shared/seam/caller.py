import re
from collections.abc import Iterator
from types import TracebackType
from typing import cast, override

import httpx
from fastmcp.dependencies import Dependency, Depends
from fastmcp.server.auth.providers.azure import EntraOBOToken
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import (
    current_graph_operation,
    graph_client_for,
    record_token_acquisition,
)
from office_365_mcp.shared.seam.permissions import graph_scope, named_permissions

ENTRA_CODE = re.compile(r"AADSTS\d+")


def causes(error: BaseException) -> Iterator[BaseException]:
    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        yield cause
        cause = cause.__cause__


class TokenExchangeFailed(Exception):
    def __init__(self, *, permissions: tuple[str, ...], cause: BaseException) -> None:
        super().__init__(f"Microsoft 365 issued no token for {named_permissions(permissions)}")
        self.permissions: tuple[str, ...] = permissions
        self.cause: BaseException = cause


class GraphToken(Dependency[str]):
    def __init__(self, *permissions: str) -> None:
        assert permissions, "a token is exchanged for at least one permission"
        self._permissions: tuple[str, ...] = permissions
        self._exchange: Dependency[str] = cast(
            "Dependency[str]",
            cast("object", EntraOBOToken([graph_scope(permission) for permission in permissions])),
        )

    @override
    async def __aenter__(self) -> str:
        try:
            token = await self._exchange.__aenter__()
        except Exception as failure:
            refused = any(ENTRA_CODE.search(str(cause)) for cause in causes(failure))
            record_token_acquisition(
                current_graph_operation(), result="refused" if refused else "failed"
            )
            raise TokenExchangeFailed(permissions=self._permissions, cause=failure) from failure
        record_token_acquisition(current_graph_operation(), result="ok")
        return token

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._exchange.__aexit__(exc_type, exc_value, traceback)


def _graph_token(*permissions: str) -> str:
    exchange = GraphToken(*permissions)
    return Depends(lambda: exchange)


def graph_client_for_caller(transport: httpx.AsyncClient, *permissions: str) -> GraphServiceClient:
    token = _graph_token(*permissions)

    def client_for_this_call(access_token: str = token) -> GraphServiceClient:
        return graph_client_for(transport, access_token)

    return Depends(client_for_this_call)


def graph_mailbox(client: GraphServiceClient, mailbox: str | None) -> UserItemRequestBuilder:
    if mailbox is None:
        return client.me
    return client.users.by_user_id(mailbox)


MAILBOX_FIELD: str = (
    "A shared or delegated mailbox to act on, as its user principal name or Entra object id, "
    + "instead of the signed-in user's own mailbox. Omit for the signed-in user's own mailbox."
)
