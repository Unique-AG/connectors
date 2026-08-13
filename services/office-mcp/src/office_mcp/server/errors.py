"""Turning a Graph failure into something the model on the other end can act on.

`graph_client` classifies what Graph said; this decides what to tell the caller to do about it,
because the caller is a language model and its only options are: retry, retry later, ask the user
to sign in, ask an administrator for a permission, or stop. A message that does not name one of
those is a message it will answer by calling the same tool again.

Two of them are only distinguishable with information Graph does not send. `GraphForbidden`
covers both 401 and 403 and carries `status` for exactly this reason: 401 means the token was
rejected (sign in again), 403 means the token was fine and the permission is missing (ask an
administrator) — opposite remedies behind one exception class. And a 403 is only actionable if
the message says *which* permission, which Graph never does; the tool does, so every mapping
here is scoped to the permission the failing call was made with.

The same missing permission also has an earlier, uglier shape: if it was never consented to,
Entra refuses the On-Behalf-Of exchange (AADSTS65001) and Graph is never reached at all. That
failure is `entra_token_errors`, and it says the same thing as the 403 above — because from the
caller's side it *is* the same thing, and the remedy is identical.
"""

import re
from collections.abc import Generator
from contextlib import contextmanager

from fastmcp.exceptions import ToolError

from office_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphThrottled,
    GraphUnavailable,
)


@contextmanager
def graph_tool_errors(permission: str) -> Generator[None]:
    """Map any Graph failure raised in this block onto an actionable MCP tool error.

    `permission` is the delegated Graph permission the enclosed calls were made with, e.g.
    `Chat.Read` — it is what makes a 403 fixable rather than merely reported.
    """
    try:
        yield
    except GraphFailure as failure:
        raise ToolError(_advice(failure, permission)) from failure


# Entra puts a machine-readable code in every token-endpoint failure (`AADSTS65001` is "the user
# or administrator has not consented"). It is the one part of a multi-line azure-identity error
# worth repeating to the caller, and what an operator searches for.
_ENTRA_CODE = re.compile(r"AADSTS\d+")


@contextmanager
def entra_token_errors(permission: str) -> Generator[None]:
    """Map a failed On-Behalf-Of exchange in this block onto an actionable MCP tool error.

    Wrap the *acquisition* of a Graph token, not the Graph call: this is the failure that happens
    before any request is made, and the one FastMCP would otherwise report as "Failed to resolve
    dependency 'graph_token'" — a message that names neither the missing permission nor the
    remedy, because FastMCP's dependency resolver knows neither. It re-raises `ToolError`
    untouched (`fastmcp.server.dependencies` lets `FastMCPError` subclasses out of dependency
    resolution unwrapped, which is what makes this interception point work at all).
    """
    try:
        yield
    except Exception as failure:
        raise ToolError(_token_advice(failure, permission)) from failure


def _token_advice(failure: BaseException, permission: str) -> str:
    """What to do about an On-Behalf-Of exchange that did not produce a token.

    One message for every cause, because the two the exchange can actually fail for share the
    first remedy: the permission was never consented to (AADSTS65001, overwhelmingly the common
    one), or this connector's own Entra credentials are wrong. Splitting them would mean
    classifying Entra error codes this connector has never observed, and the cost of guessing
    wrong is advice that sends the caller after the wrong fix.
    """
    code = _ENTRA_CODE.search(str(failure))
    diagnostics = code.group() if code is not None else type(failure).__name__
    return (
        "Microsoft 365 would not issue this connector a token to act for the signed-in user with "
        + f"the delegated permission {permission}, so this call never reached Microsoft Graph. "
        + f"Usually that means {permission} was never consented to: ask a Microsoft 365 "
        + f"administrator to grant the delegated permission {permission} to this connector's app "
        + "registration (and consent to it for the organisation), then have the user sign in to "
        + "this connector again. If it is already granted, this connector's Entra configuration "
        + "is broken and only an operator can fix it. Either way, retrying will not help and no "
        + f"other arguments will succeed either. (Entra {diagnostics})"
    )


def _advice(failure: GraphFailure, permission: str) -> str:
    return _remedy(failure, permission) + _diagnostics(failure)


def _remedy(failure: GraphFailure, permission: str) -> str:
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
        return (
            f"Microsoft 365 refused this request: the connector may not use {permission} on "
            + "behalf of this user. Ask a Microsoft 365 administrator to grant the delegated "
            + f"permission {permission} to this connector's app registration (and consent to it "
            + "for the organisation). Retrying will not help, and no other arguments will "
            + "succeed either."
        )
    if isinstance(failure, GraphNotFound):
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
    return (
        "Microsoft Graph rejected this request. This is a bad request rather than an outage or a "
        + "permission problem, so retrying it unchanged will fail identically."
    )


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
