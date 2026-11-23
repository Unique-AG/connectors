from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import cast, override

from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams

from office_365_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphPagingUnending,
    GraphResponseTooLarge,
    GraphThrottled,
    GraphUnavailable,
)
from office_365_mcp.shared.seam.caller import ENTRA_CODE, TokenExchangeFailed, causes
from office_365_mcp.shared.seam.permissions import named_permissions


class Advised(ToolError):
    pass


_FORBIDDEN = 403


@contextmanager
def owner_refused(named: bool, advice: str) -> Generator[None]:
    try:
        yield
    except GraphForbidden as refusal:
        if not named or refusal.status != _FORBIDDEN:
            raise
        raise Advised(advice + _diagnostics(refusal)) from refusal


@dataclass(frozen=True, slots=True)
class ToolAdvice:
    permissions: tuple[str, ...]
    not_found: str | None = None
    shown_by: tuple[str, ...] = ()
    forbidden: str | None = None


_NARROWED_PERMISSIONS = "office_365_mcp.narrowed_permissions"


async def narrowed_to(ctx: Context, *permissions: str) -> None:
    assert permissions, "a Graph call is made under at least one permission"
    await ctx.set_state(_NARROWED_PERMISSIONS, permissions, serializable=False)


async def _narrowed_permissions(ctx: Context | None) -> tuple[str, ...] | None:
    if ctx is None:
        return None
    return cast("tuple[str, ...] | None", await ctx.get_state(_NARROWED_PERMISSIONS))


class GraphAdviceMiddleware(Middleware):
    def __init__(self, advice: Mapping[str, ToolAdvice]) -> None:
        self._advice: Mapping[str, ToolAdvice] = advice

    @override
    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next: CallNext[CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        try:
            return await call_next(context)
        except Exception as error:
            narrowed = await _narrowed_permissions(context.fastmcp_context)
            repeatable = await _repeatable(context.fastmcp_context, context.message.name)
            advised = self._advised(error, context.message.name, narrowed, repeatable=repeatable)
            if advised is None:
                raise
            raise advised from error

    def _advised(
        self,
        error: BaseException,
        tool: str,
        narrowed: tuple[str, ...] | None,
        *,
        repeatable: bool,
    ) -> ToolError | None:
        for cause in causes(error):
            if isinstance(cause, Advised):
                return None
            if isinstance(cause, TokenExchangeFailed):
                return ToolError(_token_advice(cause.cause, cause.permissions))
            if isinstance(cause, GraphFailure):
                known = self._advice[tool]
                permissions = known.permissions if narrowed is None else narrowed
                return ToolError(
                    _advice(
                        cause,
                        permissions,
                        known.not_found,
                        repeatable=repeatable,
                        shown_by=known.shown_by,
                        forbidden=known.forbidden,
                    )
                )
        return None


async def _repeatable(ctx: Context | None, tool: str) -> bool:
    found = None if ctx is None else await ctx.fastmcp.get_tool(tool)
    hints = None if found is None else found.annotations
    return hints is not None and bool(hints.read_only_hint or hints.idempotent_hint)


def _token_advice(failure: BaseException, permissions: tuple[str, ...]) -> str:
    code = ENTRA_CODE.search(str(failure))
    diagnostics = code.group() if code is not None else type(failure).__name__
    named = named_permissions(permissions)
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
        + f"{them} for the organization), then have the user sign in to this connector again. If "
        + f"{granted}, this connector's Entra configuration is broken and only an operator can "
        + "fix it. Either way, retrying will not help and no other arguments will succeed "
        + f"either. (Entra {diagnostics})"
    )


_TOO_MANY_REQUESTS = 429
_CONFLICT = 409

_TRANSCRIPT_ACCESS_DISABLED = "GraphAccessToTranscriptsDisabled"

_TRANSCRIPTS_SWITCHED_OFF = (
    "Microsoft 365 refused this request because this organization has Microsoft Graph access to "
    + "Teams transcripts switched OFF. This is a tenant-wide Teams setting, off by "
    + "default, and it blocks every transcript read regardless of which permissions this connector "
    + "holds — so it is NOT a consent problem and asking the user to sign in again will not change "
    + "it. A Microsoft Teams administrator has to turn it on: Teams admin center → Meetings → "
    + "Meeting settings → Transcript API access → Microsoft Graph access, or "
    + "`Set-CsTeamsMeetingConfiguration -EnableGraphTranscriptAccess $true -Identity Global`. "
    + "Microsoft documents no request-side workaround: until an administrator acts, every "
    + "transcript call from this connector fails identically, so do not retry this one and do not "
    + "try another meeting or another transcript. Everything else this connector does — chats, "
    + "channels, message search — is unaffected."
)


_LICENSE_INFORMATION_MISSING = "Failed to get license information for the user"

_NEEDS_A_TEAMS_LICENSE = (
    "Microsoft 365 refused this request because this user's Office 365 license does not cover "
    + "it. An administrator has to assign a license that includes the service this tool uses. A "
    + "new license can take time to apply, so trying again later may work."
)


_OUTCOME_UNKNOWN = (
    "The connection to Microsoft 365 failed, or Microsoft 365 answered with an internal error. "
    + "As a result, this connector does not know if Microsoft 365 made the change. Microsoft 365 "
    + "can make a change and then give an error. Do not call this tool again first. "
)

_NO_TOOL_SHOWS_IT = (
    "No tool of this deployment can show the change. Before you call this tool again, ask the "
    + "user if the Microsoft 365 app shows the change."
)


def _outcome_unknown(shown_by: tuple[str, ...]) -> str:
    if not shown_by:
        return _OUTCOME_UNKNOWN + _NO_TOOL_SHOWS_IT
    return (
        _OUTCOME_UNKNOWN
        + "Before you call this tool again, make sure that the change is not already there. "
        + f"To see if the change is there, use {' or '.join(shown_by)}."
    )


def _advice(
    failure: GraphFailure,
    permissions: tuple[str, ...],
    not_found: str | None,
    *,
    repeatable: bool,
    shown_by: tuple[str, ...] = (),
    forbidden: str | None = None,
) -> str:
    return _remedy(
        failure,
        permissions,
        not_found,
        repeatable=repeatable,
        shown_by=shown_by,
        forbidden=forbidden,
    ) + _diagnostics(failure)


def _remedy(
    failure: GraphFailure,
    permissions: tuple[str, ...],
    not_found: str | None,
    *,
    repeatable: bool,
    shown_by: tuple[str, ...],
    forbidden: str | None,
) -> str:
    if isinstance(failure, GraphThrottled):
        advice = failure.retry_after_seconds
        if advice is None:
            return (
                "Microsoft 365 is rate-limiting this connector. Wait before retrying, and do not "
                + "repeat the call in a loop — throttling is per tenant and retrying makes it "
                + "last longer."
            )
        if failure.status == _TOO_MANY_REQUESTS:
            return (
                "Microsoft 365 is rate-limiting this connector and asked to be left alone for "
                + f"{advice:g} seconds. Retry after that, not sooner."
            )
        return (
            "Microsoft 365 declined to serve this request now and asked to be left alone for "
            + f"{advice:g} seconds — it is either rate-limiting this connector or too busy to "
            + "answer. Retry after that, not sooner, and do not repeat the call in a loop."
        )
    if isinstance(failure, GraphForbidden):
        if failure.status == 401:
            return (
                "Microsoft 365 rejected the signed-in user's credentials. Ask the user to sign "
                + "in to this connector again; the request itself was fine, so retrying it "
                + "unchanged will fail the same way."
            )
        if failure.inner_code == _TRANSCRIPT_ACCESS_DISABLED:
            return _TRANSCRIPTS_SWITCHED_OFF
        if failure.reason is not None and _LICENSE_INFORMATION_MISSING in failure.reason:
            return _NEEDS_A_TEAMS_LICENSE
        if forbidden is not None:
            return forbidden
        named = named_permissions(permissions)
        noun = "permissions" if len(permissions) > 1 else "permission"
        return (
            f"Microsoft 365 refused this request: the connector may not use {named} on behalf of "
            + f"this user. Ask a Microsoft 365 administrator to grant the delegated {noun} "
            + f"{named} to this connector's app registration, and to consent for the "
            + "organization. Retrying will not help, and no other arguments will succeed either."
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
        if not repeatable:
            return _outcome_unknown(shown_by)
        return (
            "Microsoft 365 could not be reached or failed internally. Retry once; if it fails "
            + "again the same way, stop and report it — some Graph 500s are permanent for "
            + "particular content rather than transient."
        )
    if isinstance(failure, GraphResponseTooLarge):
        return (
            "Microsoft 365 answered, but the answer is larger than this connector can hold. "
            + f"The limit is {failure.limit} bytes. Nothing about the request is wrong. The same "
            + "request will give the same refusal, so do not retry it. Ask for less content. Use "
            + "a narrower window, fewer items, or one item instead of a collection. You can also "
            + "read the content with a tool that returns text."
        )
    if isinstance(failure, GraphPagingUnending):
        return (
            "Microsoft 365 would not finish sending this list: it answered "
            + f"{failure.empty_pages} pages in a row with nothing in them while still saying more "
            + "of the list was coming, so this connector stopped instead of following it further. "
            + "Nothing was wrong with the request and no other arguments will avoid it. Retry once "
            + "if the list matters; if it happens again, stop and report it, because the list "
            + "cannot be read while Microsoft answers this way."
        )
    if failure.status == _CONFLICT:
        return (
            "Microsoft 365 rejected this request because an item that is already there prevents "
            + "it. Most often, an item at that level already has the same name. If you call this "
            + "tool again with the same arguments, the call will fail the same way. Change the "
            + "name, or use a tool that shows a list of items to find that item."
            + _graphs_reason(failure)
        )
    return (
        "Microsoft 365 rejected this request because it is a bad request, not an outage or a "
        + "permission problem. If you call this tool again with the same arguments, the call "
        + "will fail the same way."
        + _graphs_reason(failure)
    )


def _graphs_reason(failure: GraphFailure) -> str:
    if failure.reason is None:
        return ""
    return f' Microsoft 365 gave this reason: "{failure.reason}"'


def _diagnostics(failure: GraphFailure) -> str:
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
