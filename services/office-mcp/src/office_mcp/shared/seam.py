"""How a tool talks to the outside world: the token and error messages.

A model reads this server as one voice. 403 errors must name the permission wherever they come from.

Token Exchange

`EntraOBOToken` is FastMCP's On-Behalf-Of dependency. Entra's own token has audience
`api://{client_id}`. Graph rejects that audience. The exchange trades it for a token Graph
accepts, in the requested scopes.

`GraphToken` wraps it: dependency resolution happens outside the tool body, so Entra refusals
don't hit `graph_tool_errors` inside. FastMCP would report "Failed to resolve dependency"
(unhelpful). Wrapping makes unconsented permissions as actionable as Graph 403s. One exchange
covers every permission at once. Entra's refusal does not name the missing permission, so this
message names them all.

Error Messages

Models' only remedies are retry, retry later, sign in, ask administrator, or stop. Every message
names one. Each message opens with `Microsoft 365`, not `Graph`. Models never call Graph directly.

Each message states the remedy first. Operator evidence follows, in parentheses. Graph details
appear only to resolve an ambiguity, such as a 404. Graph details also appear when an operator
needs a support label, such as a request id.

TRAP: `GraphForbidden` covers 401 and 403 (401 = sign in; 403 = ask administrator). Graph never
names the permission on 403. The tool does, scoped to the permissions used.

The same missing permission appears first as Entra refusal (AADSTS65001) if never consented.
"""

import re
from collections.abc import Generator
from contextlib import contextmanager
from types import TracebackType
from typing import cast, override

from fastmcp.dependencies import Dependency
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import EntraOBOToken

from office_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphPagingUnending,
    GraphThrottled,
    GraphUnavailable,
)

_GRAPH_SCOPE_PREFIX = "https://graph.microsoft.com/"

READ_ONLY: dict[str, bool] = {"readOnlyHint": True, "openWorldHint": True}

REQUESTABLE_PERMISSIONS: frozenset[str] = frozenset(
    {"User.Read", "Chat.Read", "Team.ReadBasic.All", "ChannelMessage.Read.All"}
)


def graph_scope(permission: str) -> str:
    """Turn permission into scope format."""
    return f"{_GRAPH_SCOPE_PREFIX}{permission}"


class GraphToken(Dependency[str]):
    """Wrap EntraOBOToken to explain refusals as permission problems."""

    def __init__(self, *permissions: str) -> None:
        assert permissions, "a token is exchanged for at least one permission"
        self._permissions: tuple[str, ...] = permissions
        self._exchange: Dependency[str] = cast(
            "Dependency[str]",
            cast("object", EntraOBOToken([graph_scope(permission) for permission in permissions])),
        )

    @override
    async def __aenter__(self) -> str:
        with entra_token_errors(*self._permissions):
            return await self._exchange.__aenter__()

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._exchange.__aexit__(exc_type, exc_value, traceback)


def graph_token(*permissions: str) -> str:
    """Build GraphToken for tool injection."""
    return cast("str", cast("object", GraphToken(*permissions)))


@contextmanager
def graph_tool_errors(*permissions: str, not_found: str | None = None) -> Generator[None]:
    """Map Graph failures to actionable errors. Name the permissions."""
    assert permissions
    try:
        yield
    except GraphFailure as failure:
        raise ToolError(_advice(failure, permissions, not_found)) from failure


@contextmanager
def entra_token_errors(*permissions: str) -> Generator[None]:
    """Map token failures to actionable errors. Name the permissions."""
    assert permissions
    try:
        yield
    except Exception as failure:
        raise ToolError(_token_advice(failure, permissions)) from failure


_ENTRA_CODE = re.compile(r"AADSTS\d+")


def _token_advice(failure: BaseException, permissions: tuple[str, ...]) -> str:
    """Map On-Behalf-Of failures to actionable advice.

    Both causes (missing consent, wrong Entra config) share the first remedy: ask the administrator.
    Splitting would mean classifying Entra codes we may never see.
    """
    code = _ENTRA_CODE.search(str(failure))
    diagnostics = code.group() if code is not None else type(failure).__name__
    named = _named(permissions)
    several = len(permissions) > 1
    noun = "permissions" if several else "permission"
    consented = "were never consented to" if several else "was never consented to"
    them = "them" if several else "it"
    granted = "they are already granted" if several else "it is already granted"
    return (
        "Microsoft 365 would not issue this connector a token to act for the signed-in user with "
        + f"the delegated {noun} {named}, so this call never reached Microsoft Graph. "
        + f"Usually that means {named} {consented}: ask a Microsoft 365 administrator to grant "
        + f"the delegated {noun} {named} to this connector's app registration (and consent to "
        + f"{them} for the organisation), then have the user sign in to this connector again. If "
        + f"{granted}, this connector's Entra configuration is broken and only an operator can "
        + "fix it. Either way, retrying will not help and no other arguments will succeed "
        + f"either. (Entra {diagnostics})"
    )


def _advice(failure: GraphFailure, permissions: tuple[str, ...], not_found: str | None) -> str:
    return _remedy(failure, permissions, not_found) + _diagnostics(failure)


def _remedy(failure: GraphFailure, permissions: tuple[str, ...], not_found: str | None) -> str:
    if isinstance(failure, GraphThrottled):
        if failure.retry_after_seconds is None:
            return (
                "Microsoft 365 is rate-limiting this connector. Wait before retrying, and do not "
                + "repeat the call in a loop — throttling is per tenant and retrying makes it "
                + "last longer."
            )
        return (
            "Microsoft 365 is rate-limiting this connector and asked to be left alone for "
            + f"{failure.retry_after_seconds:g} seconds. Retry after that, not sooner."
        )
    if isinstance(failure, GraphForbidden):
        if failure.status == 401:
            return (
                "Microsoft 365 rejected the signed-in user's credentials. Ask the user to sign "
                + "in to this connector again; the request itself was fine, so retrying it "
                + "unchanged will fail the same way."
            )
        named = _named(permissions)
        noun = "permissions" if len(permissions) > 1 else "permission"
        return (
            f"Microsoft 365 refused this request: the connector may not use {named} on behalf of "
            + f"this user. Ask a Microsoft 365 administrator to grant the delegated {noun} "
            + f"{named} to this connector's app registration, and to consent for the "
            + "organisation. Retrying will not help, and no other arguments will succeed either."
        )
    if isinstance(failure, GraphNotFound):
        if not_found is not None:
            return not_found
        return (
            "Microsoft 365 has no such item — or the signed-in user is not allowed to know it "
            + "exists, which Graph reports identically. Check the id came from a tool response "
            + "verbatim rather than being constructed."
        )
    if isinstance(failure, GraphUnavailable):
        return (
            "Microsoft 365 could not be reached or failed internally. Retry once; if it fails "
            + "again the same way, stop and report it — some Graph 500s are permanent for "
            + "particular content rather than transient."
        )
    if isinstance(failure, GraphPagingUnending):
        # The only failure here that arrived without a status code, because no request failed: it
        # is what a run of successful, empty, "there is more" pages means. The count is the whole
        # of the evidence, so it goes in the sentence rather than in `_diagnostics`, which has
        # nothing to append.
        return (
            "Microsoft 365 would not finish sending this list: it answered "
            + f"{failure.empty_pages} pages in a row with nothing in them while still saying more "
            + "of the list was coming, so this connector stopped instead of following it further. "
            + "Nothing was wrong with the request and no other arguments will avoid it. Retry once "
            + "if the list matters; if it happens again, stop and report it, because the list "
            + "cannot be read while Microsoft answers this way."
        )
    return (
        "Microsoft 365 rejected this request. This is a bad request rather than an outage or a "
        + "permission problem, so retrying it unchanged will fail identically."
    )


def _named(permissions: tuple[str, ...]) -> str:
    """Format permissions as a readable phrase."""
    if len(permissions) == 1:
        return permissions[0]
    return " and ".join((", ".join(permissions[:-1]), permissions[-1]))


def _diagnostics(failure: GraphFailure) -> str:
    """Add operator details: request_id is what Microsoft support asks for first."""
    parts = [
        f"{label} {value}"
        for label, value in (
            ("HTTP", failure.status),
            ("Graph error code", failure.code),
            ("Graph request id", failure.request_id),
        )
        if value is not None
    ]
    return f" ({', '.join(parts)})" if parts else ""
