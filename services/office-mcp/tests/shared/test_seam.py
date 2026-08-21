"""What a model is told when Graph says no.

These assertions are about *advice*, not wording: each one pins the fact that distinguishes one
remedy from another, because getting those wrong is what makes a model retry a call that can never
succeed, or give up on one that would have worked a second later.

Both routes to a message are driven here: `graph_tool_errors`, which maps a failure where it
happens, and `GraphAdviceMiddleware`, which covers every registered tool and the dependency
resolution no block could reach. No tool opens a block any more, so the first route is the mapping
asked directly, which is what makes it worth comparing the second against. Whether the two agree end
to end is `tests/test_error_mapping.py`'s subject.
"""

import pytest
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams

from office_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphPagingUnending,
    GraphThrottled,
    GraphUnavailable,
)
from office_mcp.shared.seam import (
    GraphAdviceMiddleware,
    TokenExchangeFailed,
    ToolAdvice,
    graph_tool_errors,
)

_PERMISSION = "Chat.Read"
_CHANNELS = "ChannelMessage.Read.All"

# The tool every failure below is attributed to, and what the middleware is told about it.
_TOOL = "read_something"
_ADVICE = GraphAdviceMiddleware({_TOOL: ToolAdvice(permissions=(_PERMISSION,))})

# What azure-identity's `OnBehalfOfCredential.get_token` reports when the delegated permission was
# never consented to, trimmed of its trace ids.
_UNCONSENTED = (
    "AADSTS65001: The user or administrator has not consented to use the application with ID "
    + "'1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061'. Send an interactive authorization request for "
    + "this user and resource."
)


def _message(failure: GraphFailure) -> str:
    with pytest.raises(ToolError) as raised, graph_tool_errors(_PERMISSION):
        raise failure
    return str(raised.value)


async def _middleware_message(delivered: BaseException) -> str:
    """What the middleware answers a call that failed with `delivered`.

    Driven through `on_call_tool` rather than through a helper, because the hook is where the
    decision is: what it catches is never the failure itself, and mistaking one for the other is
    the defect this exists to catch.
    """

    async def refuse(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
        _ = context
        raise delivered

    context = MiddlewareContext(message=CallToolRequestParams(name=_TOOL, arguments={}))
    with pytest.raises(ToolError) as raised:
        _ = await _ADVICE.on_call_tool(context, refuse)
    return str(raised.value)


def _as_fastmcp_delivers_it(failure: BaseException) -> ToolError:
    """`failure` inside the two wrappers FastMCP puts between a failed dependency and a middleware.

    The dependency engine reports anything that is not a `FastMCPError` as a `RuntimeError` naming
    the parameter (fastmcp 3.4.5, `fastmcp/server/dependencies.py:686`) and the tool caller
    re-raises that as a `ToolError` naming the tool (`fastmcp/server/server.py:1357`). Built here
    rather than reached for, so that this file needs no server. That the real chain is this shape is
    pinned end to end in `tests/test_error_mapping.py` and `tests/test_mcp_tools.py`.
    """
    dependency = RuntimeError(f"Failed to resolve dependency 'client' for {_TOOL}")
    dependency.__cause__ = failure
    delivered = ToolError(f"Error calling tool '{_TOOL}': {dependency}")
    delivered.__cause__ = dependency
    return delivered


async def _token_message(failure: Exception, *permissions: str) -> str:
    return await _middleware_message(
        _as_fastmcp_delivers_it(
            TokenExchangeFailed(permissions=permissions or (_PERMISSION,), cause=failure)
        )
    )


class TestTheTwoRemediesGraphCannotTellApart:
    """401 and 403 are both `GraphForbidden`. One is fixed by the user, the other by an admin."""

    def test_a_rejected_token_asks_the_user_to_sign_in_again(self) -> None:
        message = _message(
            GraphForbidden("nope", status=401, code="InvalidAuthenticationToken", request_id=None)
        )

        assert "sign in" in message
        assert _PERMISSION not in message, "a 401 is not a missing-permission problem"

    def test_a_missing_permission_names_the_permission_and_who_must_grant_it(self) -> None:
        """The failure Graph is least helpful about: it never says which permission was missing,
        so the tool has to. Without the name, the remedy is not actionable."""
        message = _message(
            GraphForbidden("nope", status=403, code="Authorization_RequestDenied", request_id=None)
        )

        assert message.count(_PERMISSION) >= 1
        assert "administrator" in message
        assert "Retrying will not help" in message

    def test_the_transcript_tenant_switch_is_neither_of_those_and_says_so(self) -> None:
        """A third remedy behind the same status and the same outer code, and the one that is not
        a permission at all: Graph access to Teams meeting transcripts is a tenant-wide Teams
        setting, off by default, that no app can turn on. Naming a permission here would send an
        administrator after one that was never missing, and telling the user to sign in again would
        cost a re-consent that changes nothing, so the remedy names the Teams admin centre and the
        cmdlet, and rules re-consent out in as many words.
        """
        message = _message(
            GraphForbidden(
                "nope",
                status=403,
                code="Forbidden",
                request_id=None,
                inner_code="GraphAccessToTranscriptsDisabled",
            )
        )

        assert "Teams administrator" in message
        assert "Set-CsTeamsMeetingConfiguration" in message
        assert "sign in again will not change it" in message
        assert _PERMISSION not in message, (
            "no permission is missing, and naming one sends an administrator after nothing"
        )

    def test_an_ordinary_403_is_still_about_a_permission(self) -> None:
        """The negative control: recognition is by inner code and never by status alone, or every
        missing permission would be reported as a tenant setting nobody has switched off."""
        message = _message(
            GraphForbidden("nope", status=403, code="Forbidden", request_id=None, inner_code="Foo")
        )

        assert _PERMISSION in message
        assert "Teams administrator" not in message


class TestRetryAdvice:
    def test_throttling_passes_graphs_own_delay_through(self) -> None:
        """Graph's `Retry-After` is the documented fastest way out of throttling. An eager retry
        makes it last longer, so the number has to survive into the message."""
        message = _message(
            GraphThrottled(
                "slow down",
                status=429,
                code="activityLimitReached",
                request_id=None,
                retry_after_seconds=42.0,
            )
        )

        assert "42 seconds" in message

    def test_a_5xx_that_named_a_delay_passes_it_on_without_naming_a_cause(self) -> None:
        """`GraphThrottled` is not only 429: Graph holds a caller off with a 503 carrying
        `Retry-After` too, and that one may equally be a service too busy to answer. The delay is
        the remedy for both, which is why they share a class. Only the 429 can be called rate
        limiting, and a message that called the other one that would send an operator looking for a
        quota that was never spent.
        """
        message = _message(
            GraphThrottled("busy", status=503, code=None, request_id=None, retry_after_seconds=7.0)
        )

        assert "7 seconds" in message
        assert "Retry after that, not sooner" in message
        assert "Microsoft 365 is rate-limiting this connector" not in message
        assert "Retry once" not in message, "not an outage: Graph said when to come back"

    def test_throttling_without_a_delay_still_says_not_to_spin(self) -> None:
        message = _message(
            GraphThrottled(
                "slow down", status=429, code=None, request_id=None, retry_after_seconds=None
            )
        )

        assert "loop" in message
        assert "seconds" not in message, "no invented number when Graph gave no advice"

    def test_an_outage_is_worth_exactly_one_retry(self) -> None:
        message = _message(GraphUnavailable("boom", status=503, code=None, request_id=None))

        assert "Retry once" in message

    def test_a_collection_graph_will_not_end_reaches_the_caller_as_advice(self) -> None:
        """The one failure here that no request produced: Graph answering page after empty page
        while still advertising more, which `collect_pages` refuses. It is a `GraphFailure` so that
        it arrives the way a 429 or a 403 does, as a tool error a model can act on, and the count
        has to survive into the message, because it is the only evidence there is.
        """
        message = _message(
            GraphPagingUnending("11 empty pages in a row, and Graph says more", empty_pages=11)
        )

        assert "11 pages in a row" in message
        assert "nothing in them" in message
        assert "no other arguments will avoid it" in message, "not a bad-request remedy"
        assert "None" not in message, "no status, no code, nothing invented in their place"

    def test_a_bad_request_is_not_worth_retrying(self) -> None:
        message = _message(GraphFailure("bad filter", status=400, code=None, request_id=None))

        assert "retrying it unchanged will fail identically" in message

    def test_a_missing_item_does_not_claim_the_item_does_not_exist(self) -> None:
        """Graph returns 404 both for "no such thing" and for "none of your business", so a
        message that asserts absence teaches the model something false."""
        message = _message(GraphNotFound("gone", status=404, code=None, request_id=None))

        assert "not allowed to know it exists" in message

    def test_a_tool_whose_id_came_from_another_tool_can_say_so_instead(self) -> None:
        """The default advice, check the id came from a tool response verbatim, is the right first
        guess when a caller supplied an id, and wrong for a handle another tool just produced: it
        sends the model to re-check the one thing that cannot be the cause. Only the 404 advice is
        replaceable, because it is the only one whose remedy depends on where the argument came
        from.
        """
        with pytest.raises(ToolError) as raised, graph_tool_errors(_PERMISSION, not_found="Gone."):
            raise GraphNotFound("gone", status=404, code=None, request_id="req-7")

        assert str(raised.value) == "Gone. (HTTP 404, Graph request id req-7)"

    def test_it_does_not_replace_the_advice_for_any_other_failure(self) -> None:
        with pytest.raises(ToolError) as raised, graph_tool_errors(_PERMISSION, not_found="Gone."):
            raise GraphForbidden("nope", status=403, code=None, request_id=None)

        assert "Gone." not in str(raised.value)
        assert _PERMISSION in str(raised.value)


class TestDiagnostics:
    def test_the_graph_request_id_survives(self) -> None:
        """It exists only in that one response, and it is the first thing Microsoft support asks
        for. Losing it makes a production failure untraceable afterwards."""
        message = _message(
            GraphUnavailable("boom", status=500, code="internalError", request_id="req-42")
        )

        assert "HTTP 500" in message
        assert "Graph error code internalError" in message
        assert "Graph request id req-42" in message

    def test_nothing_is_invented_when_graph_sent_no_evidence(self) -> None:
        message = _message(GraphUnavailable("unreachable", status=None, code=None, request_id=None))

        assert "None" not in message

    def test_a_success_passes_through_untouched(self) -> None:
        with graph_tool_errors(_PERMISSION):
            outcome = "fine"

        assert outcome == "fine"


class TestTheRefusalThatHappensBeforeGraph:
    """A permission nobody consented to fails in the On-Behalf-Of exchange, not in Graph.

    Same remedy as the 403 above, reached a step earlier, and the step matters: this one happens
    while FastMCP is resolving the client the tool is handed, where the default report is "Failed to
    resolve dependency 'client'". The token dependency inside it raises `TokenExchangeFailed`, which
    arrives at the middleware under two wrappers. The assertions are what a model reads at the end.
    """

    async def test_an_unconsented_permission_names_the_permission_and_the_remedy(self) -> None:
        message = await _token_message(RuntimeError(_UNCONSENTED))

        assert message.count(_PERMISSION) >= 1
        assert "administrator" in message
        assert "grant the delegated permission" in message
        assert "sign in" in message, "consent granted after sign-in needs a new token"
        assert "retrying will not help" in message.lower()

    async def test_it_says_the_call_never_happened(self) -> None:
        """Unlike every Graph failure above, nothing was asked of Microsoft 365 here. A model that
        believes otherwise reports the read as attempted-and-refused."""
        message = await _token_message(RuntimeError(_UNCONSENTED))

        assert "never reached Microsoft Graph" in message

    async def test_it_says_nothing_about_resolving_a_dependency(self) -> None:
        """The wrappers are FastMCP's own vocabulary and name a parameter of a function the model
        never sees. Being the outermost thing to touch the failure is what lets the middleware
        replace that report rather than decorate it."""
        message = await _token_message(RuntimeError(_UNCONSENTED))

        assert "resolve dependency" not in message
        assert "dependency 'client'" not in message, "nor the parameter the wrapper names"

    async def test_entras_own_code_survives_for_whoever_has_to_diagnose_it(self) -> None:
        message = await _token_message(RuntimeError(_UNCONSENTED))

        assert "AADSTS65001" in message
        assert "Send an interactive authorization request" not in message, (
            "the model cannot act on Entra's prose, and it is not addressed to this connector"
        )

    async def test_a_failure_entra_never_answered_is_still_actionable(self) -> None:
        """No AADSTS code means the exchange never got as far as Entra: a broken connector, not
        a refused user. The permission is still named, because it is still what was being asked
        for, and the exception type is the only evidence there is."""
        message = await _token_message(ValueError("no access token available"))

        assert _PERMISSION in message
        assert "AADSTS" not in message, "no code was invented"
        assert "ValueError" in message

    async def test_an_exchange_for_several_permissions_names_them_all(self) -> None:
        """A tool needing two permissions gets one token or none: Entra redeems the scopes together
        and refuses them together, saying no more about which one was unconsented than a Graph 403
        does. Naming one of two would send an administrator to grant a permission that may already
        be there, and the second attempt fails identically.

        The permissions come off the failure rather than out of the middleware's table, which is why
        this reads two while the table for `_TOOL` holds one: the exchange knows what it asked for,
        and a token is exchanged once for whatever a tool declares.
        """
        message = await _token_message(RuntimeError(_UNCONSENTED), _PERMISSION, _CHANNELS)

        assert _PERMISSION in message
        assert _CHANNELS in message
        assert "grant the delegated permissions" in message, "plural, or it reads as one of them"
        assert "administrator" in message


class TestWhatTheMiddlewareLeavesAlone:
    """The middleware words a refusal *or* keeps its hands off it. There is nothing in between.

    Every case here is a failure that already says the right thing, and re-wording any of them would
    replace a message somebody wrote on purpose with one worded from a table.
    """

    async def test_it_words_a_graph_refusal_the_way_the_mapping_itself_does(self) -> None:
        """The middleware beside the mapping it delegates to, driven on its own. Byte equality
        rather than keywords: one wording for a refusal is the whole promise of moving the mapping
        out of ten tool bodies, and a wording that drifted here would drift for every tool."""
        refusal = GraphForbidden(
            "nope", status=403, code="Authorization_RequestDenied", request_id="req-7"
        )
        delivered = ToolError(f"Error calling tool '{_TOOL}': {refusal}")
        delivered.__cause__ = refusal

        assert await _middleware_message(delivered) == _message(
            GraphForbidden(
                "nope", status=403, code="Authorization_RequestDenied", request_id="req-7"
            )
        )

    async def test_a_refusal_already_worded_by_the_mapping_is_passed_through_unchanged(
        self,
    ) -> None:
        """The double mapping, and why it is harmless: whatever `graph_tool_errors` worded arrives
        as a type the middleware recognises rather than re-derives. It matters exactly where the two
        wordings would differ, a call naming fewer permissions than its tool declares."""
        with pytest.raises(ToolError) as raised, graph_tool_errors(_CHANNELS):
            raise GraphForbidden("nope", status=403, code=None, request_id=None)
        advised = raised.value

        assert await _middleware_message(advised) == str(advised)
        assert _CHANNELS in str(advised), "the tool's own permission, not the table's"
        assert _PERMISSION not in str(advised)

    async def test_a_tool_error_about_an_argument_is_not_a_graph_failure(self) -> None:
        """A handle of the wrong shape is refused before Graph is reached, and the tool that owns
        the shape is the only thing that can explain it."""
        refusal = ToolError("read_transcript takes teams:///transcripts/{a}/{b}.")

        assert await _middleware_message(refusal) == str(refusal)

    async def test_a_refusal_for_an_unknown_tool_keeps_its_own_report(self) -> None:
        """Unreachable while the table and the registration come from one resolved selection, and
        asserted anyway: the alternative was an `assert`, which would answer a caller who could have
        acted on a 403 with an internal error nobody can act on.
        """
        blind = GraphAdviceMiddleware({})
        refusal = GraphForbidden("nope", status=403, code=None, request_id=None)
        delivered = ToolError(f"Error calling tool '{_TOOL}': {refusal}")
        delivered.__cause__ = refusal

        async def refuse(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
            _ = context
            raise delivered

        context = MiddlewareContext(message=CallToolRequestParams(name=_TOOL, arguments={}))
        with pytest.raises(ToolError) as raised:
            _ = await blind.on_call_tool(context, refuse)

        assert raised.value is delivered
