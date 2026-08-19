"""How a tool is attached to the outside: the token it calls under, and what a refusal becomes.

Everything else a tool needs is its own — its name, its arguments, its answer, its Graph request.
These two things are not, and both for the same reason: a model on the other end reads this server
as one thing. A token exchange refused for one tool has to be explained the way it is explained for
every other, and a Graph 403 has to name a permission in the same sentence shape wherever it came
from, or the surface stops sounding like one server and starts sounding like ten. This module is
therefore the seam — and it is the one file under `shared/` that imports FastMCP, which is what
keeps the framework out of the rest of the shared vocabulary (`tests/test_layering.py` rule 1).

## The token

`EntraOBOToken` is FastMCP's own On-Behalf-Of dependency: it takes the Entra token the caller
presented (audience `api://{client_id}`, useless against Graph) and exchanges it for a Graph one in
the scopes asked for. It is a dependency default, so it never appears in a tool's input schema —
the model cannot see it and cannot supply it.

`GraphToken` wraps it for one reason: a dependency is resolved *outside* the tool body, so an
exchange Entra refuses never enters the body and never reaches the mapping inside it. FastMCP
reports it as "Failed to resolve dependency 'graph_token' for get_me", which tells a model nothing
it can act on. So the wrapper raises `TokenExchangeFailed`, which carries the permissions the
exchange asked for and is deliberately NOT a `FastMCPError`: `fastmcp.server.dependencies` lets
`FastMCPError` subclasses out of dependency resolution unwrapped and wraps everything else, and
being wrapped is what lets the middleware below recognise it by type. That is what makes an
unconsented permission as fixable before the Graph call as a 403 is after it.

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

A tool that still opens its own mapping block keeps it: the message that block produced is what
reaches the client, byte for byte, because it arrives as a type the middleware leaves alone. That is
what lets a tool say something narrower than its declared tuple — `read_message` reads one surface
under one of the two permissions its token was exchanged for — while the middleware covers the rest.

One instance covers one exchange, however many permissions that exchange asks for, because Entra
redeems them together and refuses them together: a tool needing two gets one token or none. Naming
all of them is therefore the same requirement as it is for a 403 — the refusal does not say which
one was missing.

## The advice

`graph_client` classifies what Graph said; this decides what to tell the caller to do about it,
because the caller is a language model and its only options are: retry, retry later, ask the user
to sign in, ask an administrator for a permission, or stop. A message that does not name one of
those is a message it will answer by calling the same tool again.

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
administrator) — opposite remedies behind one exception class. And a 403 is only actionable if
the message says *which* permission, which Graph never does; the tool does, so every mapping
here is scoped to the permissions the failing call was made under.

The same missing permission also has an earlier, uglier shape: if it was never consented to,
Entra refuses the On-Behalf-Of exchange (AADSTS65001) and Graph is never reached at all. That
failure is worded by `_token_advice`, and it says the same thing as the 403 above — because from
the caller's side it *is* the same thing, and the remedy is identical.
"""

import re
from collections.abc import Generator, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from types import TracebackType
from typing import cast, override

from fastmcp.dependencies import Dependency
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import EntraOBOToken
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams

from office_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphThrottled,
    GraphUnavailable,
)

# A Graph delegated permission, as a scope the On-Behalf-Of exchange can ask for. Graph accepts a
# bare permission name at the authorize endpoint too, but only because it is the default resource;
# the full form is unambiguous and is what FastMCP's own examples use.
_GRAPH_SCOPE_PREFIX = "https://graph.microsoft.com/"

# What every tool here declares about itself, because every tool here is one of these: it reads,
# and what it reads is a live Microsoft 365 tenant rather than a closed world. One dict rather than
# one per tool file — a tool that differed would be saying something, and none of them does.
READ_ONLY: dict[str, bool] = {"readOnlyHint": True, "openWorldHint": True}


# Every delegated permission this connector may ask Entra for, written out once. A tool declares
# its own `GRAPH_PERMISSIONS` and the registry unions them, so nothing here is *derived* from this
# list — what it is, is the list of names that are allowed to appear in one, and `tests/test_app.py`
# holds every tool file to it.
#
# It exists because a misspelling is otherwise invisible in both directions. `Chat.Raed` reaches
# `additional_authorize_scopes` unchallenged — every test comparing tool files against the registry
# compares the typo with itself — and Entra rejects an authorize request carrying a scope it does
# not know, so every sign-in fails for every user, for a permission nobody asked for.
#
# Adding a name here is therefore a deliberate act and not bookkeeping: it widens what sign-in asks
# every user of this connector to consent to, and some of the ones still to come need an
# administrator. Adding one means a tool genuinely needs it, spelled as Microsoft spells it, and the
# README's permission table says which tool and why — which is also why this is what the connector
# asks for today rather than what it might ask for one day: a name no tool declares is a name
# nothing has checked the spelling of, and it weakens the check above by exactly the permissions it
# would wave through.
REQUESTABLE_PERMISSIONS: frozenset[str] = frozenset({"User.Read"})


def graph_scope(permission: str) -> str:
    """A delegated Graph permission as the scope sign-in and the exchange ask for it by."""
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
        # `EntraOBOToken` is annotated `-> str` (a lie for the type checker's benefit, so a tool
        # can annotate the token as the string it receives); the value is the dependency object.
        # Casting back to what it is has to go through `object` — the two types do not overlap.
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


def graph_token(*permissions: str) -> str:
    """A `GraphToken` typed as the token FastMCP will inject in its place.

    The same annotation `EntraOBOToken` uses, for the same reason: the tool body is handed a
    string and should say so, and the dependency object it never sees would otherwise have to be
    cast at every declaration site. The cast goes through `object` for the same reason it does
    above — a dependency is not a string, which is precisely why FastMCP replaces it with one.

    Build one per tool module, at module level: a call inside a parameter default rebuilds the
    descriptor on every registration and is a lint error in both of this repo's checkers. Sharing
    one instance across calls is safe — FastMCP enters it per call and it holds nothing but its
    permissions.
    """
    return cast("str", cast("object", GraphToken(*permissions)))


class Advised(ToolError):
    """A tool error whose message is already the advice below.

    The type is the whole of what stops the middleware from wording a refusal twice. A type rather
    than a mark on the message, because the two wordings are not always the same one: a tool that
    narrows the permissions of its own call reports fewer than it declares, and re-wording that from
    the table would name a permission that was never missing.

    Design decision: no leading underscore, although nothing outside this module refers to it. The
    class name reaches an operator: `unique_mcp`'s tool metrics label every failed call with
    `type(error).__name__`, and that layer sits inside this one, so a refusal a tool worded for
    itself is counted under this name. It reads `ToolError` again once no tool words its own.
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
            advised = self._advised(error, context.message.name)
            if advised is None:
                raise
            # `from error` keeps the whole chain: this is the last thing to touch the failure, but a
            # span or a log sink further out still reads the cause it was raised from.
            raise advised from error

    def _advised(self, error: BaseException, tool: str) -> ToolError | None:
        """The advice for this failure, or `None` when there is nothing here to say about it.

        `None` covers three cases that must all leave the failure exactly as it is: a refusal the
        tool already worded (`Advised`), a `ToolError` about an argument (a handle of the wrong
        shape), and anything that is not a Graph or token failure at all.
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
                return ToolError(_advice(cause, known.permissions, known.not_found))
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
    """Map any Graph failure raised in this block onto an actionable MCP tool error.

    `permissions` are the delegated Graph permissions the enclosed calls were made with, e.g.
    `Chat.Read` — they are what make a 403 fixable rather than merely reported. Where a call needs
    more than one, name them all: Graph never says which of them it refused, so an administrator
    given only one name may grant the wrong permission and see the same failure.

    `not_found` replaces the advice for a 404. The default tells the caller to check that the id it
    sent came from a tool response verbatim, which is the likeliest cause when a tool takes an id —
    and is misleading advice for one that takes a handle another tool just produced, where the
    remaining causes are deletion and lost access. Pass the sentence that is true of this call; the
    diagnostics Graph sent are appended either way.
    """
    assert permissions, "a Graph call is made under at least one permission"
    try:
        yield
    except GraphFailure as failure:
        raise Advised(_advice(failure, permissions, not_found)) from failure


# Entra puts a machine-readable code in every token-endpoint failure (`AADSTS65001` is "the user
# or administrator has not consented"). It is the one part of a multi-line azure-identity error
# worth repeating to the caller, and what an operator searches for.
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
