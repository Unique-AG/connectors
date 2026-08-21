"""How a tool is attached to the outside: the Graph client it calls with, the token in it, and what
a refusal becomes.

A model reads this server as one thing, so every token refusal is worded the same way and every 403
names its permission. This module is the seam, and it is the only file in `shared/` that imports
FastMCP. That keeps the framework out of shared vocabulary, and tests/test_layering.py enforces it.

## Token exchange

`EntraOBOToken` is FastMCP's On-Behalf-Of dependency. It exchanges Entra's token (audience
`api://{client_id}`, useless against Graph) for a Graph token in the requested scopes. It is a
dependency default, so models never see it.

`GraphToken` wraps it for one reason: a dependency is resolved *outside* the tool body, so an
exchange Entra refuses never enters the body and never reaches the mapping inside it. FastMCP
reports it as "Failed to resolve dependency 'client' for get_me" — the parameter it could not
resolve, which tells a model nothing it can act on. So the wrapper raises `TokenExchangeFailed`,
which carries the permissions the exchange asked for and is deliberately NOT a `FastMCPError`:
`fastmcp.server.dependencies` lets `FastMCPError` subclasses out of dependency resolution
unwrapped and wraps everything else, and being wrapped is what lets the middleware below recognise
it by type. That is what makes an unconsented permission as fixable before the Graph call as a 403
is after it.

One instance covers one exchange, however many permissions that exchange asks for. Entra redeems
them together and refuses them together, so a tool needing two gets one token or none, and the
refusal never says which one was missing. The message therefore names all of them, exactly as a 403
does.

## The client a tool is handed

`graph_client_for_caller` is the whole of what a tool needs to reach Graph, and it is built in
`register` because that is where the process-wide transport is in scope. A tool that read the
transport out of ambient state could be registered against nothing at all, and nothing would say so
until its first call.

## One mapping, not one per tool

`GraphAdviceMiddleware` is where a failure becomes advice. It wraps every `tools/call`, so it covers
the tool body and the dependency resolution that runs before it, and it is the outermost middleware
so the operations layer below still logs the untranslated failure with its cause chain intact.

It words a Graph refusal from a table its constructor is handed: one entry per registered tool,
built in `tools/__init__.py` from each tool module's own `GRAPH_PERMISSIONS` so it cannot drift from
the registered surface. The permissions travel that way rather than on the tool itself, because a
tool's `tags` are a set and the order the names are read in is prose, which a set loses, and because
a tool's `meta` would publish this connector's permission names to every client in `tools/list`.

Every refusal here is written to one shape: the thing that refused, then the remedy, then the
evidence an operator needs in a trailing parenthesis. It is always "Microsoft 365", never
"Microsoft Graph" — the caller is not calling that API. Graph is named only where it is the
explanation, or as `Graph request id`, which is what Microsoft support asks for by that name.

Trap: the middleware never sees a `GraphFailure`. FastMCP re-raises whatever leaves a tool as
`ToolError` (fastmcp 3.4.5, `fastmcp/server/server.py:1356`), and the dependency engine wraps a
failed dependency in a `RuntimeError` before that, so what has to be recognised is two links down a
`__cause__` chain, matched on type. Matching FastMCP's own message text would break on a wording
change nobody here would review.

The advice table is built in `tools/__init__.py` from each tool module's own `GRAPH_PERMISSIONS`.
The permissions travel that way rather than on the tool: `tags` is a set and loses the order the
message names them in, and `meta` would publish them to every client in `tools/list`.
"""

import re
from collections.abc import Generator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import cast, override

import httpx
from fastmcp import Context
from fastmcp.dependencies import Dependency, Depends
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import EntraOBOToken
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphPagingUnending,
    GraphThrottled,
    GraphUnavailable,
    graph_client_for,
)

_GRAPH_SCOPE_PREFIX = "https://graph.microsoft.com/"

READ_ONLY: dict[str, bool] = {"readOnlyHint": True, "openWorldHint": True}

# What a tool file's own permissions are checked against. Without it a misspelling like `Chat.Raed`
# is only ever compared with itself: Entra rejects an unknown scope at the authorize endpoint, and
# one typo stops sign-in for every user of this connector.
REQUESTABLE_PERMISSIONS: frozenset[str] = frozenset(
    {
        "User.Read",
        "Chat.Read",
        "Team.ReadBasic.All",
        "Channel.ReadBasic.All",
        "ChannelMessage.Read.All",
        "OnlineMeetings.Read",
        "OnlineMeetingTranscript.Read.All",
        "OnlineMeetingRecording.Read.All",
    }
)


def graph_scope(permission: str) -> str:
    return f"{_GRAPH_SCOPE_PREFIX}{permission}"


class TokenExchangeFailed(Exception):
    """The On-Behalf-Of exchange produced no token.

    Not a `FastMCPError`: dependency resolution lets those out unwrapped and wraps everything else
    in a `RuntimeError`, and that wrapping is what `GraphAdviceMiddleware` finds this by.
    """

    def __init__(self, *, permissions: tuple[str, ...], cause: BaseException) -> None:
        super().__init__(f"Microsoft 365 issued no token for {_named(permissions)}")
        self.permissions: tuple[str, ...] = permissions
        self.cause: BaseException = cause


class GraphToken(Dependency[str]):
    """`EntraOBOToken` for a tool's permissions, reporting a refusal as one that knows them."""

    def __init__(self, *permissions: str) -> None:
        assert permissions, "a token is exchanged for at least one permission"
        self._permissions: tuple[str, ...] = permissions
        # `EntraOBOToken` is annotated `-> str`, and the real value is the dependency object; the
        # two types do not overlap, so the cast goes through `object`.
        self._exchange: Dependency[str] = cast(
            "Dependency[str]",
            cast("object", EntraOBOToken([graph_scope(permission) for permission in permissions])),
        )

    @override
    async def __aenter__(self) -> str:
        try:
            return await self._exchange.__aenter__()
        except Exception as failure:
            # Every exception, not a type: azure-identity reports a refused exchange as
            # `ClientAuthenticationError`, and `_EntraOBOToken.__aenter__` raises plain
            # `RuntimeError`s of its own first (fastmcp 3.4.5,
            # `fastmcp/server/auth/providers/azure.py:838,848`).
            raise TokenExchangeFailed(permissions=self._permissions, cause=failure) from failure

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._exchange.__aexit__(exc_type, exc_value, traceback)


def _graph_token(*permissions: str) -> str:
    """The exchange for these permissions, as the string a tool signature can hold it by.

    `Depends` is annotated to unwrap a factory returning an async context manager, and
    `GraphToken.__aenter__` produces a `str`, so the parameter default is typed as the token a
    dependent actually receives.

    The exchange is bound outside the factory deliberately: one `GraphToken` per registration.
    Constructing it inside the lambda would build a new one on every call.
    """
    exchange = GraphToken(*permissions)
    return Depends(lambda: exchange)


def graph_client_for_caller(transport: httpx.AsyncClient, *permissions: str) -> GraphServiceClient:
    """A Graph client that calls as this call's signed-in user. Build inside `register`.

    Trap: the result goes in a parameter default by NAME, `client: GraphServiceClient = graph`,
    never as the call itself. A call in a default is ruff's B008, and it would build a second
    exchange on every registration.
    """
    token = _graph_token(*permissions)

    def client_for_this_call(access_token: str = token) -> GraphServiceClient:
        return graph_client_for(transport, access_token)

    return Depends(client_for_this_call)


class Advised(ToolError):
    """A tool error whose message is already the advice below, so the middleware leaves it alone.

    Public despite having no importer: `unique_mcp`'s tool metrics label every failed call with
    `type(error).__name__`, so renaming this renames an operator-facing metric.
    """


@dataclass(frozen=True, slots=True)
class ToolAdvice:
    """What one tool's failures are worded from: `permissions` in the order the message names them,
    and the sentence its 404 needs instead of the default one."""

    permissions: tuple[str, ...]
    not_found: str | None = None


_NARROWED_PERMISSIONS = "office_mcp.narrowed_permissions"


async def narrowed_to(ctx: Context, *permissions: str) -> None:
    """Say that this call reached Graph under fewer permissions than its tool declares, so its 403
    names none that was never missing.

    `serializable=False` makes this request state rather than session state, which outlives the call
    by a day and would word a second call to the same tool from the first call's handle.
    """
    assert permissions, "a Graph call is made under at least one permission"
    await ctx.set_state(_NARROWED_PERMISSIONS, permissions, serializable=False)


async def _narrowed_permissions(ctx: Context | None) -> tuple[str, ...] | None:
    """What `narrowed_to` said about this call, or `None` when it said nothing."""
    if ctx is None:
        return None
    return cast("tuple[str, ...] | None", await ctx.get_state(_NARROWED_PERMISSIONS))


class GraphAdviceMiddleware(Middleware):
    """Answer every refused tool call with the remedy for it, wherever in the call it happened."""

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
            advised = self._advised(error, context.message.name, narrowed)
            if advised is None:
                raise
            raise advised from error

    def _advised(
        self, error: BaseException, tool: str, narrowed: tuple[str, ...] | None
    ) -> ToolError | None:
        """The advice for this failure, or `None` to leave the failure exactly as it is.

        A token refusal ignores `narrowed`: the exchange happens before the argument is parsed and
        asks for every permission, so naming one of them would hide the one that was refused.
        """
        for cause in _causes(error):
            if isinstance(cause, Advised):
                return None
            if isinstance(cause, TokenExchangeFailed):
                return ToolError(_token_advice(cause.cause, cause.permissions))
            if isinstance(cause, GraphFailure):
                known = self._advice.get(tool)
                # Left as it arrived rather than asserted: an assertion would replace a refusal a
                # model could act on with one nobody can.
                if known is None:
                    return None
                permissions = known.permissions if narrowed is None else narrowed
                return ToolError(_advice(cause, permissions, known.not_found))
        return None


def _causes(error: BaseException) -> Iterator[BaseException]:
    """`error` and everything it was raised from, outermost first. Cycle-safe because `raise X from
    Y` accepts a loop, which would hang the request instead of answering it."""
    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        yield cause
        cause = cause.__cause__


@contextmanager
def graph_tool_errors(*permissions: str, not_found: str | None = None) -> Generator[None]:
    """Map Graph failures onto actionable tool errors. Name every permission: Graph names none.

    No tool opens one — `GraphAdviceMiddleware` covers every registered tool from this same function
    — so this is the escape for a wording the table cannot carry. It arrives as `Advised`, which the
    middleware leaves alone, and `tests/shared/test_seam.py` compares the two wordings message for
    message. `not_found` replaces the default 404 advice, which assumes the id came verbatim from a
    tool response rather than being a handle another tool minted.
    """
    assert permissions, "a Graph call is made under at least one permission"
    try:
        yield
    except GraphFailure as failure:
        raise Advised(_advice(failure, permissions, not_found)) from failure


_ENTRA_CODE = re.compile(r"AADSTS\d+")


def _token_advice(failure: BaseException, permissions: tuple[str, ...]) -> str:
    """One message for every way the On-Behalf-Of exchange can fail to produce a token: a permission
    was never consented to (AADSTS65001, overwhelmingly the common one), or this connector's own
    Entra credentials are wrong. Splitting them would mean classifying Entra error codes this
    connector has never observed."""
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


_TOO_MANY_REQUESTS = 429

# Graph's inner error code for the tenant switch, branched on rather than the message text, as
# Microsoft's transcript reference instructs twice. `services/teams-mcp` met this switch first
# (PR #762).
_TRANSCRIPT_ACCESS_DISABLED = "GraphAccessToTranscriptsDisabled"

_TRANSCRIPTS_SWITCHED_OFF = (
    "Microsoft 365 refused this request because this organisation has Microsoft Graph access to "
    + "Teams meeting transcripts switched OFF. This is a tenant-wide Teams setting, off by "
    + "default, and it blocks every transcript read regardless of which permissions this connector "
    + "holds — so it is NOT a consent problem and asking the user to sign in again will not change "
    + "it. A Microsoft Teams administrator has to turn it on: Teams admin centre → Meetings → "
    + "Meeting settings → Transcript API access → Microsoft Graph access, or "
    + "`Set-CsTeamsMeetingConfiguration -EnableGraphTranscriptAccess $true -Identity Global`. "
    + "Microsoft documents no request-side workaround: until an administrator acts, every "
    + "transcript call from this connector fails identically, so do not retry this one and do not "
    + "try another meeting or another transcript. Everything else this connector does — chats, "
    + "channels, message search — is unaffected."
)


def _advice(failure: GraphFailure, permissions: tuple[str, ...], not_found: str | None) -> str:
    return _remedy(failure, permissions, not_found) + _diagnostics(failure)


def _remedy(failure: GraphFailure, permissions: tuple[str, ...], not_found: str | None) -> str:
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
        # A 5xx that named a delay, which `errors.py` reads as throttling because the delay is the
        # remedy either way. Quota spent or a service shedding load is not knowable from here, so
        # the sentence claims only what Graph actually said.
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
        # No request failed, so `_diagnostics` has nothing to append and the page count, which is
        # the whole of the evidence, goes in the sentence.
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
    if len(permissions) == 1:
        return permissions[0]
    return " and ".join((", ".join(permissions[:-1]), permissions[-1]))


def _diagnostics(failure: GraphFailure) -> str:
    """The evidence an operator needs. `request_id` is what Microsoft support asks for first, and it
    is only ever in this one response."""
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
