"""This module defines how a tool connects to the outside: the Graph client, the token inside
it, and what a refusal becomes. This is the only file in `shared/` that imports FastMCP.

Trap: the middleware never sees a `GraphFailure`. FastMCP re-raises a tool failure as
`ToolError` (fastmcp 4.0.2, `fastmcp/server/server.py:1554-1555`), over the dependency engine's
`RuntimeError`. So causes are matched two links down `__cause__`, by type, and never on message
text.

`person_confirms` is the one place where a person is asked before a write, and the one place
where the protocol era decides how (`tests/test_layering.py` rule 9).
"""

import re
from collections.abc import Awaitable, Callable, Generator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import cast, override

import httpx
from fastmcp import Context
from fastmcp.dependencies import Dependency, Depends
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import EntraOBOToken
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    handle_elicit_accept,
    parse_elicit_response_type,
)
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from fastmcp.utilities.types import File
from mcp.types import (
    CallToolRequestParams,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
)
from mcp.types.version import MODERN_PROTOCOL_VERSIONS
from msgraph.generated.users.item.user_item_request_builder import UserItemRequestBuilder
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphPagingUnending,
    GraphResponseTooLarge,
    GraphThrottled,
    GraphUnavailable,
    graph_client_for,
)

_GRAPH_SCOPE_PREFIX = "https://graph.microsoft.com/"

READ_ONLY: dict[str, bool] = {"readOnlyHint": True, "openWorldHint": True}

# This states what a tool that changes a mailbox says about itself. This file writes out every
# hint, instead of leaving one to a default, because MCP's defaults are the permissive ones.
# `destructiveHint` defaults to true, and `idempotentHint` defaults to false. So an omitted hint
# reads as the worst case for a tool that is not one, and as nothing at all for a tool that is.
#
# TRAP: these are hints, and they gate nothing. MCP's own specification says a client "should
# never make tool use decisions based on ToolAnnotations received from untrusted servers". The
# real stop on a write is different. The Terraform module derives the permissions of the Entra
# registration from the same tool selection that the pod runs. So a tool that the selection does
# not name gets an On-Behalf-Of exchange that fails before its body runs. The annotations exist
# for a client that wants to prompt a human.
WRITE_ADDITIVE: dict[str, bool] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": False,
    "openWorldHint": True,
}
WRITE_IDEMPOTENT: dict[str, bool] = {
    "readOnlyHint": False,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}
WRITE_DESTRUCTIVE: dict[str, bool] = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": True,
}
WRITE_DESTRUCTIVE_IDEMPOTENT: dict[str, bool] = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": True,
    "openWorldHint": True,
}

# A tool file's own permissions are compared against this list. Without this list, a
# misspelling like `Chat.Raed` is only ever compared with itself. Entra rejects an unknown
# scope at the authorize endpoint, so one typo stops sign-in for every user of this connector.
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
        "Mail.Read",
        "Mail.Read.Shared",
        "People.Read",
        "MailboxSettings.Read",
        "Mail.ReadWrite",
        "Mail.ReadWrite.Shared",
        "Mail.Send",
        "Mail.Send.Shared",
        "Mail.ReadBasic",
        "MailboxSettings.ReadWrite",
        "Calendars.Read",
        "Calendars.Read.Shared",
        "Calendars.ReadBasic",
        "Calendars.ReadWrite",
        "Calendars.ReadWrite.Shared",
        "Files.Read.All",
        "Notes.Read",
        "Notes.Create",
        "Notes.ReadWrite",
    }
)


def graph_scope(permission: str) -> str:
    return f"{_GRAPH_SCOPE_PREFIX}{permission}"


class TokenExchangeFailed(Exception):
    """The On-Behalf-Of exchange produced no token.

    This is not a `FastMCPError`. Dependency resolution lets a `FastMCPError` out unwrapped, and
    wraps everything else in a `RuntimeError`. `GraphAdviceMiddleware` finds this exception by
    that wrapping.
    """

    def __init__(self, *, permissions: tuple[str, ...], cause: BaseException) -> None:
        super().__init__(f"Microsoft 365 issued no token for {_named(permissions)}")
        self.permissions: tuple[str, ...] = permissions
        self.cause: BaseException = cause


class GraphToken(Dependency[str]):
    """This is `EntraOBOToken` for a tool's permissions. It reports a refusal as one that knows
    the permissions."""

    def __init__(self, *permissions: str) -> None:
        assert permissions, "a token is exchanged for at least one permission"
        self._permissions: tuple[str, ...] = permissions
        # `EntraOBOToken` is annotated `-> str`, and the real value is the dependency object. The
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
            # This except is broad on purpose. azure-identity raises `ClientAuthenticationError`,
            # and `_EntraOBOToken` raises its own `RuntimeError`
            # (fastmcp 4.0.2, `fastmcp/server/auth/providers/azure.py:851,858`).
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
    """This is the exchange for these permissions, as the string that a tool signature can hold
    it by.

    `Depends` is annotated to unwrap a factory that returns an async context manager, and
    `GraphToken.__aenter__` produces a `str`. So the parameter default is typed as the token that
    a dependent actually receives.

    The exchange is bound outside the factory on purpose, for one `GraphToken` for each
    registration. Building it inside the lambda instead makes a new one on every call.
    """
    exchange = GraphToken(*permissions)
    return Depends(lambda: exchange)


def graph_client_for_caller(transport: httpx.AsyncClient, *permissions: str) -> GraphServiceClient:
    """This is a Graph client that calls as the signed-in user of this call. Build it inside
    `register`.

    Trap: the result goes in a parameter default by NAME, `client: GraphServiceClient = graph`,
    and never as the call itself. A call in a default is ruff rule B008. Putting the call there,
    instead of the name, builds a second exchange on every registration.
    """
    token = _graph_token(*permissions)

    def client_for_this_call(access_token: str = token) -> GraphServiceClient:
        return graph_client_for(transport, access_token)

    return Depends(client_for_this_call)


def graph_mailbox(client: GraphServiceClient, mailbox: str | None) -> UserItemRequestBuilder:
    """This is the mailbox that a call reaches. It is the signed-in user's own mailbox when
    `mailbox` is `None`, or the mailbox that `mailbox` names — its user principal name or its
    Entra object id — when given.

    A `.Shared` permission lets the token name a mailbox other than `/me`. Exchange must also
    grant the signed-in user real access to it, and this connector cannot see that grant. A
    missing Exchange grant and a missing Graph permission both come back as the same 403.
    """
    if mailbox is None:
        return client.me
    return client.users.by_user_id(mailbox)


# Reused with no change by every tool that threads a mailbox through to `graph_mailbox`, so the
# text stays the same across all of them.
MAILBOX_FIELD: str = (
    "A shared or delegated mailbox to act on, instead of the signed-in user's own mailbox, as "
    + "its user principal name or its Entra object id. Omit this argument for the signed-in "
    + "user's own mailbox. This argument reaches another mailbox only where Exchange grants the "
    + "signed-in user access to it — a shared folder, a full delegation, or, to send mail, Full "
    + "Access together with Send As or Send on Behalf. A mailbox that the signed-in user cannot "
    + "reach this way answers with a permission refusal, never a wrong mailbox."
)


# This states what a refusal says last, so a model does not read "no" as "ask again." MCP gives
# a server no way to remember that a person already said no to this request.
_ASK_AGAIN = (
    "Do not call this tool again for the same request unless the user asks for it in a new message."
)

# This value is answered, never raised. A `ToolError` here would cross `graph_step` and record
# a person saying no as a Graph failure. `tests/test_graph_metrics.py` guards this.
type Confirmed = str | InputRequiredResult | None

# `(question, about)`: `about` is what the answer is bound to, and must change whenever the thing
# being confirmed changes.
type Confirm = Callable[[str, str], Awaitable[Confirmed]]

# One question for each call, so a fixed key is safe. A second question in one call would
# collide.
_CONFIRMATION = "confirm"


def _modern_protocol(ctx: Context) -> bool:
    """This is true when the negotiated era has no back-channel to elicit over.

    This mirrors the private `Context._is_modern_protocol`, and includes the "no request
    context" case.
    """
    request = ctx.request_context
    return request is not None and request.protocol_version in MODERN_PROTOCOL_VERSIONS


def _nobody_to_ask(nothing_happened: str) -> str:
    return (
        f"{nothing_happened} This connector asks a person to confirm this, and the MCP "
        + "client on the other end does not support elicitation, so there was nobody to "
        + "ask. This is a property of the client and not of the request: retrying will "
        + "fail the same way. Tell the user that their client cannot confirm this, and "
        + f"that they can do it in the Microsoft 365 app itself instead. {_ASK_AGAIN}"
    )


def _not_agreed(nothing_happened: str) -> str:
    return (
        f"{nothing_happened} The person at the other end of this conversation was asked to "
        + "confirm it and did not agree. Nothing was changed, so this is not a failure to "
        + f"report as one: say that the request was not confirmed. {_ASK_AGAIN}"
    )


def _another_request(nothing_happened: str) -> str:
    return (
        f"{nothing_happened} The confirmation that came back was given for a different request "
        + "than this one, so that agreement does not cover this request, and nothing was changed. "
        + f"Ask the user again and call this tool with exactly what they confirm. {_ASK_AGAIN}"
    )


def person_confirms(ctx: Context, *, agree: str, decline: str, nothing_happened: str) -> Confirm:
    """Ask the caller's own client to put `question` to a person. Only `agree` lets the call go
    on.

    A 2026-07-28 connection has no back-channel (SEP-2577). The question is returned and
    answered on a second call, bound to `about`.
    """
    answers = parse_elicit_response_type([agree, decline])

    async def elicited(question: str) -> str | None:
        try:
            answer = await ctx.elicit(question, response_type=[agree, decline])
        except ToolError as already_a_refusal:
            return str(already_a_refusal)
        except Exception:
            # This catches every exception. A client with no elicitation capability is reported
            # differently by different transports, and none of those reasons is a reason to
            # write anyway.
            return _nobody_to_ask(nothing_happened)
        if not isinstance(answer, AcceptedElicitation) or answer.data != agree:
            return _not_agreed(nothing_happened)
        return None

    def asked(question: str, about: str) -> Confirmed:
        answered = (ctx.input_responses or {}).get(_CONFIRMATION)
        if answered is None:
            # A client that came back without an answer is indistinguishable from a first call.
            return InputRequiredResult(
                input_requests={
                    _CONFIRMATION: ElicitRequest(
                        params=ElicitRequestFormParams(
                            message=question, requested_schema=answers.schema
                        )
                    )
                },
                request_state=about,
            )
        if not isinstance(answered, ElicitResult) or answered.action != "accept":
            return _not_agreed(nothing_happened)
        # The framework unseals `requestState` only when the re-call carries one. So an accept
        # that arrives with the field stripped is bound to nothing until this function compares
        # it.
        if ctx.request_state != about:
            return _another_request(nothing_happened)
        try:
            accepted = handle_elicit_accept(answers, answered.content)
        except Exception:
            # This catches every exception. The content belongs to the client. This function
            # compares it against the schema that this question was asked under, and an answer
            # that fails that comparison agreed to nothing.
            return _not_agreed(nothing_happened)
        chosen = cast("str", accepted.data)
        return None if chosen == agree else _not_agreed(nothing_happened)

    async def confirm(question: str, about: str) -> Confirmed:
        return asked(question, about) if _modern_protocol(ctx) else await elicited(question)

    return confirm


def answer_pending(ctx: Context) -> bool:
    """This is true when this call carries an answer to a confirmation that an earlier call
    asked.

    This function takes a fresh audience read on every call, and this read can disagree with
    the read that the question was asked from. Callers must consult `confirm` whenever an
    answer is pending, instead of trusting this call's own read to decide whether an answer is
    owed.
    """
    return (ctx.input_responses or {}).get(_CONFIRMATION) is not None


class Advised(ToolError):
    """This is a tool error whose message is already the advice below, so the middleware leaves
    it alone.

    This class is public, even though nothing here imports it. The tool metrics of
    `unique_mcp` label every failed call with `type(error).__name__`. So a rename of this class
    renames an operator-facing metric.
    """


@dataclass(frozen=True, slots=True)
class ToolAdvice:
    """This is what the words for one tool's failures come from. Permissions live here, and not
    on the tool, because `tags` is a set and loses its order, and `meta` is published to every
    client in `tools/list`."""

    permissions: tuple[str, ...]
    not_found: str | None = None


_NARROWED_PERMISSIONS = "office_365_mcp.narrowed_permissions"


async def narrowed_to(ctx: Context, *permissions: str) -> None:
    """Say that this call reached Graph under fewer permissions than its tool declares, so a 403
    from this call names no permission that was never missing.

    `serializable=False` makes this request state, instead of session state. Session state
    outlives the call by a day. If this function used session state instead, it would word a
    second, unrelated call to the same tool from the handle of the first call.
    """
    assert permissions, "a Graph call is made under at least one permission"
    await ctx.set_state(_NARROWED_PERMISSIONS, permissions, serializable=False)


async def _narrowed_permissions(ctx: Context | None) -> tuple[str, ...] | None:
    """This function returns what `narrowed_to` said about this call, or `None` when it said
    nothing."""
    if ctx is None:
        return None
    return cast("tuple[str, ...] | None", await ctx.get_state(_NARROWED_PERMISSIONS))


class GraphAdviceMiddleware(Middleware):
    """This answers every refused tool call with the remedy for it, wherever in the call the
    refusal happened."""

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
        """This function returns the advice for this failure, or `None` to leave the failure
        exactly as it is.

        A token refusal ignores `narrowed`. The exchange happens before the argument is parsed,
        and it asks for every permission. Naming just one of the permissions would hide the one
        that was refused.
        """
        for cause in _causes(error):
            if isinstance(cause, Advised):
                return None
            if isinstance(cause, TokenExchangeFailed):
                return ToolError(_token_advice(cause.cause, cause.permissions))
            if isinstance(cause, GraphFailure):
                known = self._advice.get(tool)
                # This is left as it arrived, instead of asserted. Asserting it replaces a
                # refusal that a model can act on with one that nobody can.
                if known is None:
                    return None
                permissions = known.permissions if narrowed is None else narrowed
                return ToolError(_advice(cause, permissions, known.not_found))
        return None


def _causes(error: BaseException) -> Iterator[BaseException]:
    """This function yields `error`, and everything that raised it, outermost first. This is
    cycle-safe, because `raise X from Y` accepts a loop, and an unguarded loop would hang the
    request instead of answering it."""
    seen: set[int] = set()
    cause: BaseException | None = error
    while cause is not None and id(cause) not in seen:
        seen.add(id(cause))
        yield cause
        cause = cause.__cause__


@contextmanager
def graph_tool_errors(*permissions: str, not_found: str | None = None) -> Generator[None]:
    """Map Graph failures onto tool errors that a caller can act on. Name every permission,
    because Graph names none.

    No tool opens this context manager directly. `GraphAdviceMiddleware` covers every
    registered tool from this same function, so this context manager is the escape for wording
    that the table cannot carry. The error arrives as `Advised`, which the middleware leaves
    alone, and `tests/shared/test_seam.py` compares the two wordings message for message.
    `not_found` replaces the default 404 advice, which assumes that the id came with no change
    from a tool response, instead of being a handle that another tool minted.
    """
    assert permissions, "a Graph call is made under at least one permission"
    try:
        yield
    except GraphFailure as failure:
        raise Advised(_advice(failure, permissions, not_found)) from failure


_ENTRA_CODE = re.compile(r"AADSTS\d+")


def _token_advice(failure: BaseException, permissions: tuple[str, ...]) -> str:
    """This is one message for every way that the On-Behalf-Of exchange can fail to produce a
    token. Either a permission was never consented to (AADSTS65001, by far the most common
    case), or this connector's own Entra credentials are wrong. Splitting these into separate
    messages would mean classifying Entra error codes that this connector never observed."""
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
        + f"{them} for the organization), then have the user sign in to this connector again. If "
        + f"{granted}, this connector's Entra configuration is broken and only an operator can "
        + "fix it. Either way, retrying will not help and no other arguments will succeed "
        + f"either. (Entra {diagnostics})"
    )


_TOO_MANY_REQUESTS = 429
_CONFLICT = 409

# This is Graph's inner error code for the tenant switch. The code branches on this value,
# instead of on the message text, as Microsoft's transcript reference instructs twice.
# `services/teams-mcp` met this switch first (PR #762).
_TRANSCRIPT_ACCESS_DISABLED = "GraphAccessToTranscriptsDisabled"

_TRANSCRIPTS_SWITCHED_OFF = (
    "Microsoft 365 refused this request because this organization has Microsoft Graph access to "
    + "Teams meeting transcripts switched OFF. This is a tenant-wide Teams setting, off by "
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


def _advice(failure: GraphFailure, permissions: tuple[str, ...], not_found: str | None) -> str:
    return _remedy(failure, permissions, not_found) + _diagnostics(failure)


def _remedy(failure: GraphFailure, permissions: tuple[str, ...], not_found: str | None) -> str:
    """This function returns what a caller must do about `failure`, with one branch for each
    remedy, instead of one branch for each status code."""
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
        # This is a 5xx that named a delay. `errors.py` reads this as throttling, because the
        # remedy is the same either way. From here, this function cannot know whether the quota
        # is spent or a service is shedding load. So the sentence claims only what Graph
        # actually said.
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
        # No request failed here, so `_diagnostics` has nothing to append. The page count, which
        # is all of the evidence, goes in the sentence instead.
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
            "Microsoft 365 refused this request because it conflicts with something that already "
            + "exists there, most often a name already taken at that level. The same arguments "
            + "fail the same way: change the name, or find the existing item with a listing tool "
            + "first."
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
    """This function returns the evidence that an operator needs. `request_id` is what Microsoft
    support asks for first, and it appears only in this one response."""
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


class FileFromGraph(File):
    def __init__(self, content: bytes, *, name: str | None, mime_type: str) -> None:
        self.mime_type: str = mime_type
        super().__init__(data=content, name=name)

    @override
    def _get_mime_type(self) -> str:
        return self.mime_type
