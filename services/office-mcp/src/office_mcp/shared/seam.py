"""How a tool is attached to the outside: the Graph client it calls with, the token in it,
and what a refusal becomes.

A model reads this server as one thing. Token refusals must be explained consistently and 403 errors
must name the permission wherever they come from—or the surface sounds like ten servers. This module
is the seam (the only file in `shared/` that imports FastMCP—keeps the framework away from shared
vocabulary, enforced by tests/test_layering.py).

Token Exchange

`EntraOBOToken` is FastMCP's On-Behalf-Of dependency. It takes Entra's token (audience
`api://{client_id}`, useless against Graph) and exchanges it for a Graph token in the requested
scopes. It is a dependency default—models never see it.

`GraphToken` wraps it for one reason: a dependency is resolved *outside* the tool body, so an
exchange Entra refuses never enters the body and never reaches the mapping inside it. FastMCP
reports it as "Failed to resolve dependency 'client' for get_me" — the parameter it could not
resolve, which tells a model nothing it can act on. So the wrapper raises `TokenExchangeFailed`,
which carries the permissions the exchange asked for and is deliberately NOT a `FastMCPError`:
`fastmcp.server.dependencies` lets `FastMCPError` subclasses out of dependency resolution
unwrapped and wraps everything else, and being wrapped is what lets the middleware below recognise
it by type. That is what makes an unconsented permission as fixable before the Graph call as a 403
is after it.

One instance covers one exchange, however many permissions that exchange asks for, because Entra
redeems them together and refuses them together: a tool needing two gets one token or none. Naming
all of them is therefore the same requirement as it is for a 403 — the refusal does not say which
one was missing.

The Client A Tool Is Handed

`graph_client_for_caller` is the whole of what a tool needs to reach Graph. It is built in
`register`, where the process-wide transport is in scope, and it resolves per call to a client that
already carries the caller's token. The token above is its own dependency, so the exchange still
happens once per call, and still inside the resolution FastMCP wraps a failure from. A tool that
read the transport out of ambient state instead could be registered against nothing at all, and
nothing would say so until its first call.

One Mapping, Not One Per Tool

`GraphAdviceMiddleware` is where a failure becomes advice. It wraps every `tools/call`, so it covers
the tool body and the dependency resolution that runs before it, and it is the outermost middleware
so the operations layer below still logs the untranslated failure with its cause chain intact.

It words a Graph refusal from a table its constructor is handed: one entry per registered tool,
built in `tools/__init__.py` from each tool module's own `GRAPH_PERMISSIONS` so it cannot drift from
the registered surface. The permissions travel that way rather than on the tool itself, because a
tool's `tags` are a set — the order the names are read in is prose, and a set loses it — and a
tool's `meta` is published to every client in `tools/list`, which would put this connector's
permission names on the wire for nobody to read.

Trap: the middleware never sees a `GraphFailure`. FastMCP re-raises whatever leaves a tool as
`ToolError` (fastmcp 3.4.5, `fastmcp/server/server.py:1356`), and the dependency engine wraps a
failed dependency in a `RuntimeError` before that, so what has to be recognised is two links down a
`__cause__` chain. The chain is walked and matched on type. Matching FastMCP's own message text
instead would break on a wording change nobody here would review.

A tool says something narrower than its declared tuple by saying so. `read_message` reads one
surface under one of the two permissions its token was exchanged for, and `narrowed_to` carries that
to the middleware on the call's own state, because the tool learns which surface it is reading from
its argument — per call, and long after the table was built.

No tool opens its own mapping block any more, and one still may: what `graph_tool_errors` produces
reaches the client byte for byte, because it arrives as a type the middleware leaves alone. That is
the escape a tool needs to say something the table cannot be taught, and it is what the middleware's
own wording is compared against, message for message, in `tests/shared/test_seam.py`.

Error Messages

Every message here is written to one shape. The thing that refused comes first and is always
"Microsoft 365" — not "Microsoft Graph", which is the name of an API the caller is not calling.
Then the remedy, and whether retrying could possibly help. Then, in a parenthesis at the end rather
than woven through the advice, the evidence an operator needs. Graph is named after that opening
only where it is the explanation (one 404 meaning three different things, a 500 that recurs) or
where an operator needs its own label — `Graph request id` is what Microsoft support asks for, by
that name.

Two failures are only distinguishable with information Graph does not send. `GraphForbidden`
covers both 401 and 403 and carries `status` for exactly this reason: 401 means the token was
rejected (sign in again), 403 means the token was fine and the permission is missing (ask an
administrator) — opposite remedies behind one exception class. `GraphThrottled` reads its own
`status` for a milder version of the same thing: a 429 is this connector's quota, while a 5xx that
carried `Retry-After` may be that or a service shedding load, and only the first can be named as
rate limiting. The remedy — wait exactly as long as Graph asked — is what makes them one class.

And a 403 is only actionable if the message says *which* permission, which Graph never does; the
tool does, so every mapping here is scoped to the permissions the failing call was made under.

The same missing permission also has an earlier, uglier shape: if it was never consented to,
Entra refuses the On-Behalf-Of exchange (AADSTS65001) and Graph is never reached at all. That
failure is worded by `_token_advice`, and it says the same thing as the 403 above — because from
the caller's side it *is* the same thing, and the remedy is identical.

One 403 is not about a permission at all, and naming one would send an administrator after
something that was never missing. Microsoft Graph access to Teams meeting transcripts is a
*tenant* switch, off by default, that "no app can access meeting transcripts, regardless of
app-level permissions" until a Teams administrator turns it on — and Microsoft is explicit that
there is "no request-side workaround". Graph marks it with an inner error code, which is the only
thing distinguishing it from an ordinary refusal, so that is what it is recognised by (never the
message text, which Microsoft documents as subject to change). This connector already learned this
lesson once, in `services/teams-mcp` (PR #762) and in `docs/recordings-and-transcripts/`; the
remedy names a person in the Teams admin centre and explicitly rules out re-consent.
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

# Every permission this connector may request, listed once. A tool file names its own
# permissions. Every check compares a tool file against this list. A misspelled permission, like
# `Chat.Raed`, passes every check. Each check compares the typo against itself, never against the
# correct name. Entra rejects an unknown scope at the authorize endpoint. One typo here stops
# sign-in for every user of this connector.
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
    """Permission as scope for sign-in and exchange."""
    return f"{_GRAPH_SCOPE_PREFIX}{permission}"


class TokenExchangeFailed(Exception):
    """The On-Behalf-Of exchange produced no token, carrying what it asked for and what went wrong.

    Deliberately not a `FastMCPError`, which is what makes it findable: FastMCP wraps every other
    exception a dependency raises in a `RuntimeError` naming the parameter, and that wrapping is the
    signal a `FastMCPError` would skip. So this arrives at `GraphAdviceMiddleware` as a link in a
    `__cause__` chain, recognised by type, and the wording lives in one place with every other
    remedy rather than at the point of failure.
    """

    def __init__(self, *, permissions: tuple[str, ...], cause: BaseException) -> None:
        super().__init__(f"Microsoft 365 issued no token for {_named(permissions)}")
        self.permissions: tuple[str, ...] = permissions
        # The exception the exchange actually failed with. Kept as a field as well as on
        # `__cause__`, because it is an input to the advice — Entra's own `AADSTS` code is in its
        # message — and reading it off `__cause__` would depend on how this was raised.
        self.cause: BaseException = cause


class GraphToken(Dependency[str]):
    """`EntraOBOToken` for a tool's permissions, reporting a refusal as one that knows them.

    The exchange itself is untouched: `__aenter__` delegates to FastMCP's dependency, which owns
    the credential cache, and `__aexit__` delegates so any cleanup it grows is not dropped.
    """

    def __init__(self, *permissions: str) -> None:
        assert permissions, "a token is exchanged for at least one permission"
        self._permissions: tuple[str, ...] = permissions
        # `EntraOBOToken` is annotated `-> str`. This is a lie for the type checker's benefit.
        # The lie lets a tool body treat the injected value as a string. The real value here
        # is the dependency object, not a string. The two types do not overlap. So the cast
        # goes through `object`.
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
            # `RuntimeError`s of its own before it ever gets that far — no access token in context,
            # or an auth provider that is not Entra's (fastmcp 3.4.5,
            # `fastmcp/server/auth/providers/azure.py:838,848`). Nothing that arrives here produced
            # a token, and the remedy starts the same way for all of them, so a type check on the
            # innermost cause would only be a way to miss two of them.
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

    The two lifetimes a tool would otherwise hold apart itself: `transport` is process-wide and is
    passed once, at registration, which is the only place that holds it; the token is per call and
    is a dependency of this dependency, so FastMCP exchanges one per call and the tool body receives
    a client that is already the caller's.

    Trap: the result goes in a parameter default by NAME — `client: GraphServiceClient = graph` —
    never as the call itself. A call in a default is ruff's B008, and it would build a second
    exchange on every registration.
    """
    token = _graph_token(*permissions)

    def client_for_this_call(access_token: str = token) -> GraphServiceClient:
        return graph_client_for(transport, access_token)

    return Depends(client_for_this_call)


class Advised(ToolError):
    """A tool error whose message is already the advice below.

    The type is the whole of what stops the middleware from wording a refusal twice. A type rather
    than a mark on the message, because the two wordings are not always the same one: a tool that
    narrows the permissions of its own call reports fewer than it declares, and re-wording that from
    the table would name a permission that was never missing.

    Design decision: no leading underscore, although nothing outside this module refers to it. The
    class name reaches an operator: `unique_mcp`'s tool metrics label every failed call with
    `type(error).__name__`, and that layer sits inside this one. No tool words its own refusal
    today, so what an operator reads is `ToolError`; the day one needs to again, the count moves to
    this name rather than becoming invisible.
    """


@dataclass(frozen=True, slots=True)
class ToolAdvice:
    """What one tool's failures are worded from.

    `permissions` is the tuple the tool's own Graph calls are made under, in the order the message
    names them. `not_found` is the sentence its 404 needs instead of the default one, which assumes
    the id was a caller's to check; a tool whose argument is a handle another tool minted needs its
    own, and it is that tool's to write.
    """

    permissions: tuple[str, ...]
    not_found: str | None = None


# The state key one tool writes and the middleware below reads. Namespaced, because the state store
# is shared with every other writer in the process; these two are its only writer and reader.
_NARROWED_PERMISSIONS = "office_mcp.narrowed_permissions"


async def narrowed_to(ctx: Context, *permissions: str) -> None:
    """Say that this call reached Graph under fewer permissions than its tool declares.

    A tool whose token was exchanged for two permissions and whose call uses one has to say which,
    or its 403 names a permission that was never missing and an administrator grants it for nothing.
    The table cannot say it: which surface is being read is learned from the argument, per call, and
    the table is built once at startup.

    Request state rather than session state, which is what `serializable=False` buys: the narrowing
    is about this one call. Session state outlives the call by a day, so a second call to the same
    tool would be worded from the first call's handle.
    """
    assert permissions, "a Graph call is made under at least one permission"
    await ctx.set_state(_NARROWED_PERMISSIONS, permissions, serializable=False)


async def _narrowed_permissions(ctx: Context | None) -> tuple[str, ...] | None:
    """What `narrowed_to` said about this call, or `None` when it said nothing.

    `None` for nine tools out of ten, and for every call that never reached Graph. There is no
    context at all on a path with no request behind it, which is a middleware driven directly by a
    test rather than anything in production.

    `get_state` is typed `Any`, because the store holds whatever any writer put there. The cast
    asserts what `narrowed_to` guarantees about this one key rather than what the store promises.
    """
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
            # `from error` keeps the whole chain: this is the last thing to touch the failure, but a
            # span or a log sink further out still reads the cause it was raised from.
            raise advised from error

    def _advised(
        self, error: BaseException, tool: str, narrowed: tuple[str, ...] | None
    ) -> ToolError | None:
        """The advice for this failure, or `None` when there is nothing here to say about it.

        `None` covers three cases that must all leave the failure exactly as it is: a refusal the
        tool already worded (`Advised`), a `ToolError` about an argument (a handle of the wrong
        shape), and anything that is not a Graph or token failure at all.

        `narrowed` wins over the table when the tool said its call used fewer permissions than it
        declares. A token refusal ignores it: the exchange happens before the argument is parsed and
        asked for every permission, so naming one of them would hide the one that was refused.
        """
        for cause in _causes(error):
            if isinstance(cause, Advised):
                return None
            if isinstance(cause, TokenExchangeFailed):
                return ToolError(_token_advice(cause.cause, cause.permissions))
            if isinstance(cause, GraphFailure):
                known = self._advice.get(tool)
                # A tool with no entry cannot be worded, and cannot happen: the table and the
                # registration both come from one resolved selection. Left as it arrived rather than
                # asserted, because an assertion here would replace a refusal a model could act on
                # with one nobody can.
                if known is None:
                    return None
                permissions = known.permissions if narrowed is None else narrowed
                return ToolError(_advice(cause, permissions, known.not_found))
        return None


def _causes(error: BaseException) -> Iterator[BaseException]:
    """`error` and everything it was raised from, outermost first.

    Cycle-safe rather than trusting the chain: `raise X from Y` accepts a loop, and a loop here
    would hang the request instead of answering it.
    """
    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        yield cause
        cause = cause.__cause__


@contextmanager
def graph_tool_errors(*permissions: str, not_found: str | None = None) -> Generator[None]:
    """Map Graph failures onto actionable tool errors. Name all permissions—Graph doesn't.

    The mapping applied where the failure happens, rather than at `tools/call`. No tool opens one:
    `GraphAdviceMiddleware` covers every registered tool, including the dependency resolution a
    block never could, and it words a refusal from this same function. What is left here is the one
    route a tool would take to say something the table cannot carry, and the reference the
    middleware is compared against message for message — a comparison worth having precisely
    because the two are reached differently.

    `not_found` replaces the default advice for a 404. The default advice assumes the id comes
    verbatim from a tool response. That assumption is wrong for a handle that another tool
    creates. For a handle, the remaining causes are deletion and lost access. Override
    `not_found` with the sentence true of this call.
    """
    assert permissions, "a Graph call is made under at least one permission"
    try:
        yield
    except GraphFailure as failure:
        raise Advised(_advice(failure, permissions, not_found)) from failure


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


# The one throttling status that is only ever rate limiting. `GraphThrottled` also covers a 5xx that
# carried `Retry-After`, which reaches a caller with the same remedy and cannot claim the same cause
# — see `_remedy`.
_TOO_MANY_REQUESTS = 429

# Graph's inner error code for the tenant switch, and the advice for it. Branched on rather than the
# message, as Microsoft's transcript reference instructs twice.
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
        # A 5xx that named a delay. `errors.py` reads that as throttling rather than as an outage
        # because the delay is the remedy either way, but which of the two it is — quota spent, or
        # a service shedding load — is not knowable from here. So the sentence claims only what
        # Graph actually said, and the wait is the same advice a 429 gets.
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
