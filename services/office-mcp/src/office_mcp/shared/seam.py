"""How a tool talks to the outside world: the token and error messages.

A model reads this server as one thing. Token refusals must be explained consistently and 403 errors
must name the permission wherever they come from—or the surface sounds like ten servers. This module
is the seam (the only file in `shared/` that imports FastMCP—keeps the framework away from shared
vocabulary, enforced by tests/test_layering.py).

Token Exchange

`EntraOBOToken` is FastMCP's On-Behalf-Of dependency. It takes Entra's token (audience `api://{client_id}`,
useless against Graph) and exchanges it for a Graph token in the requested scopes. It is a dependency
default—models never see it.

`GraphToken` wraps it: dependency resolution happens outside the tool body, so an Entra refusal
never reaches the `graph_tool_errors` block inside. FastMCP reports "Failed to resolve dependency"
(unhelpful to models). Raising `ToolError` here makes an unconsented permission as fixable as a 403
after the Graph call. One instance covers one exchange, however many permissions, because Entra
redeems them together. The refusal does not say which permission was missing, so all are named.

Error Messages

Models' only options are: retry, retry later, sign in, ask administrator, or stop. Every message
names one. `Microsoft 365` comes first (not "Graph"—models don't call Graph). Then remedy and
whether retrying helps. Then operator evidence in parentheses. Graph details only where they explain
(404 means three things) or operators need their own label (`Graph request id` for support).

TRAP: `GraphForbidden` covers 401 and 403. Only status separates them: 401 means sign in again,
403 means ask administrator. 403 is only actionable if it names the permission. Graph never does.
The tool does—every mapping here is scoped to the permissions the failing call used.

The same missing permission appears earlier as Entra refusal (AADSTS65001) if never consented.
Graph is never reached. `entra_token_errors` reports the same remedy: ask administrator to grant
the permission and consent for the organization.
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

REQUESTABLE_PERMISSIONS: frozenset[str] = frozenset({"User.Read", "Chat.Read"})


def graph_scope(permission: str) -> str:
    """Permission as scope for sign-in and exchange."""
    return f"{_GRAPH_SCOPE_PREFIX}{permission}"


class GraphToken(Dependency[str]):
    """Wrap EntraOBOToken: explain the refusal in terms of permissions."""

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
    """GraphToken typed as string for tool injection. Build once at module level."""
    return cast("str", cast("object", GraphToken(*permissions)))


@contextmanager
def graph_tool_errors(*permissions: str, not_found: str | None = None) -> Generator[None]:
    """Map Graph failures onto actionable tool errors. Name all permissions—Graph doesn't."""
    assert permissions, "a Graph call is made under at least one permission"
    try:
        yield
    except GraphFailure as failure:
        raise ToolError(_advice(failure, permissions, not_found)) from failure


@contextmanager
def entra_token_errors(*permissions: str) -> Generator[None]:
    """Map token acquisition failures onto actionable tool errors. Name all permissions."""
    assert permissions, "a token exchange asks for at least one permission"
    try:
        yield
    except Exception as failure:
        raise ToolError(_token_advice(failure, permissions)) from failure


_ENTRA_CODE = re.compile(r"AADSTS\d+")


def _token_advice(failure: BaseException, permissions: tuple[str, ...]) -> str:
    """What to do about an On-Behalf-Of exchange that did not produce a token.

    One message for every cause, because the two the exchange can actually fail for share the
    first remedy: a permission was never consented to (AADSTS65001, overwhelmingly the common
    one), or this connector's own Entra credentials are wrong. Splitting them would mean
    classifying Entra error codes this connector has never observed, and the cost of guessing
    wrong is advice that sends the caller after the wrong fix.
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
    """The permissions as a phrase, so the message reads as a sentence rather than a list."""
    if len(permissions) == 1:
        return permissions[0]
    return " and ".join((", ".join(permissions[:-1]), permissions[-1]))


def _diagnostics(failure: GraphFailure) -> str:
    """The evidence an operator needs, appended once rather than woven into every message.

    `request_id` is what Microsoft support asks for first, and it is only ever in this response —
    losing it means the failure cannot be traced afterwards.
    """
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
