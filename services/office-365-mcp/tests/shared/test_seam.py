"""What a model is told when Graph says no, and what it is told when a person says no.

Both routes to a message are driven here: `graph_tool_errors`, the mapping asked directly, and
`GraphAdviceMiddleware`, which covers every registered tool and the dependency resolution no block
could reach. Whether the two agree end to end is `tests/test_error_mapping.py`'s subject.
"""

from collections.abc import Mapping
from typing import cast

import pytest
from fastmcp import Context
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import (
    CallToolRequestParams,
    CreateMessageResult,
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    TextContent,
)
from mcp.types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION

from office_365_mcp.graph_client import (
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphPagingUnending,
    GraphThrottled,
    GraphUnavailable,
)
from office_365_mcp.shared.seam import (
    Confirm,
    Confirmed,
    GraphAdviceMiddleware,
    TokenExchangeFailed,
    ToolAdvice,
    graph_tool_errors,
    person_confirms,
)

_PERMISSION = "Chat.Read"
_CHANNELS = "ChannelMessage.Read.All"

_TOOL = "read_something"
_ADVICE = GraphAdviceMiddleware({_TOOL: ToolAdvice(permissions=(_PERMISSION,))})

# What `OnBehalfOfCredential.get_token` reports for an unconsented permission, minus its trace ids.
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
    """Driven through `on_call_tool` and not a helper: what the hook catches is never the failure
    itself, and mistaking one for the other is the defect this exists to catch."""

    async def refuse(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
        _ = context
        raise delivered

    context = MiddlewareContext(message=CallToolRequestParams(name=_TOOL, arguments={}))
    with pytest.raises(ToolError) as raised:
        _ = await _ADVICE.on_call_tool(context, refuse)
    return str(raised.value)


def _as_fastmcp_delivers_it(failure: BaseException) -> ToolError:
    """fastmcp 4.0.2 wraps a non-`FastMCPError` in a `RuntimeError` naming the parameter
    (`fastmcp/server/dependencies.py:814`), then a `ToolError` (`fastmcp/server/server.py:1555`).
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
        """Graph never says which permission was missing, so the tool has to."""
        message = _message(
            GraphForbidden("nope", status=403, code="Authorization_RequestDenied", request_id=None)
        )

        assert message.count(_PERMISSION) >= 1
        assert "administrator" in message
        assert "Retrying will not help" in message

    def test_the_transcript_tenant_switch_is_neither_of_those_and_says_so(self) -> None:
        """A third remedy behind the same status and outer code, and not a permission at all:
        Graph access to Teams meeting transcripts is a tenant-wide Teams setting, off by default,
        that no app can turn on."""
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
        """Recognition is by inner code and never by status alone."""
        message = _message(
            GraphForbidden("nope", status=403, code="Forbidden", request_id=None, inner_code="Foo")
        )

        assert _PERMISSION in message
        assert "Teams administrator" not in message


class TestRetryAdvice:
    def test_throttling_passes_graphs_own_delay_through(self) -> None:
        """`Retry-After` is the documented fastest way out; an eager retry makes it last longer."""
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
        """`GraphThrottled` is not only 429: a 503 carrying `Retry-After` shares the class because
        the delay is the remedy for both. Only the 429 is rate limiting — calling a 503 that sends
        an operator looking for a quota that was never spent."""
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
        """The one failure no request produced: Graph answering page after empty page while still
        advertising more, which `collect_pages` refuses. The count is the only evidence there is."""
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
        """Graph returns 404 both for "no such thing" and for "none of your business"."""
        message = _message(GraphNotFound("gone", status=404, code=None, request_id=None))

        assert "not allowed to know it exists" in message

    def test_a_tool_whose_id_came_from_another_tool_can_say_so_instead(self) -> None:
        """Only the 404 advice is replaceable: it is the only one whose remedy depends on where
        the argument came from."""
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
        """It exists only in that one response, and Microsoft support asks for it first."""
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
    """A permission nobody consented to fails in the On-Behalf-Of exchange, not in Graph — while
    FastMCP resolves the client the tool is handed, where the default report is "Failed to resolve
    dependency 'client'"."""

    async def test_an_unconsented_permission_names_the_permission_and_the_remedy(self) -> None:
        message = await _token_message(RuntimeError(_UNCONSENTED))

        assert message.count(_PERMISSION) >= 1
        assert "administrator" in message
        assert "grant the delegated permission" in message
        assert "sign in" in message, "consent granted after sign-in needs a new token"
        assert "retrying will not help" in message.lower()

    async def test_it_says_the_call_never_happened(self) -> None:
        message = await _token_message(RuntimeError(_UNCONSENTED))

        assert "never reached Microsoft Graph" in message

    async def test_it_says_nothing_about_resolving_a_dependency(self) -> None:
        """Being the outermost thing to touch the failure is what lets the middleware replace
        FastMCP's report rather than decorate it."""
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
        """No AADSTS code means the exchange never got as far as Entra: a broken connector, not a
        refused user, and the exception type is the only evidence there is."""
        message = await _token_message(ValueError("no access token available"))

        assert _PERMISSION in message
        assert "AADSTS" not in message, "no code was invented"
        assert "ValueError" in message

    async def test_an_exchange_for_several_permissions_names_them_all(self) -> None:
        """Entra redeems the scopes together and refuses them together, saying no more about which
        one was unconsented than a Graph 403 does. The permissions come off the failure and not the
        middleware's table, which is why this reads two while the table for `_TOOL` holds one."""
        message = await _token_message(RuntimeError(_UNCONSENTED), _PERMISSION, _CHANNELS)

        assert _PERMISSION in message
        assert _CHANNELS in message
        assert "grant the delegated permissions" in message, "plural, or it reads as one of them"
        assert "administrator" in message


_AGREE = "create the event"
_DECLINE = "do not create it"
_NOTHING_HAPPENED = "No event was created."
_QUESTION = "Create 'Pricing review' on 2 March at 14:00 UTC and invite nobody?"


# What a create tool binds an answer to: the uuid5 `transaction_id_for` composes from the draft,
# which is also the `transactionId` that same draft's write carries.
_ABOUT = "5f5c4e19-0d6b-5a2f-9c31-8e7a4b2d1f60"
_ANOTHER_REQUEST = "3a5f9c02-1e4d-5b6a-8c7d-9e0f1a2b3c4d"


class _Era:
    """The negotiated protocol version, the only thing a request context is read for here."""

    def __init__(self, protocol_version: str) -> None:
        self.protocol_version: str = protocol_version


class _Client:
    """A stand-in for the caller's own client. `person_confirms` reaches four things on a
    `Context` — `request_context`, `elicit`, `input_responses` and `request_state` — so this is
    the whole of the surface it depends on.

    `era` is the negotiated protocol version, and `None` is a connection with no request context
    at all, which `person_confirms` treats as not modern. `responses` and `state` are what a
    client sent back on a later round.
    """

    def __init__(
        self,
        answer: object = None,
        *,
        era: str | None = None,
        responses: dict[str, object] | None = None,
        state: str | None = None,
    ) -> None:
        self.request_context: _Era | None = None if era is None else _Era(era)
        self.input_responses: dict[str, object] | None = responses
        self.request_state: str | None = state
        self._answer: object = answer

    async def elicit(self, message: str, response_type: object = None) -> object:
        assert message
        assert response_type == [_AGREE, _DECLINE], (
            "the person picks between the two answers the caller named"
        )
        if isinstance(self._answer, Exception):
            raise self._answer
        return self._answer


def _confirming(client: _Client) -> Confirm:
    """The stub as the `Context` a tool is handed. The two types do not overlap, so the cast goes
    through `object`."""
    return person_confirms(
        cast("Context", cast("object", client)),
        agree=_AGREE,
        decline=_DECLINE,
        nothing_happened=_NOTHING_HAPPENED,
    )


def _confirm_with(answer: object, era: str | None) -> Confirm:
    return _confirming(_Client(answer, era=era))


@pytest.mark.parametrize(
    "era", [None, LATEST_HANDSHAKE_VERSION], ids=["no-request-context", "handshake"]
)
class TestHowAWriteIsPutToAPerson:
    """`person_confirms` is the adapter from a tool to the caller's own client. What a client
    answers, and what it fails to answer, decides whether the write happens at all.

    Both eras here answer inside the call, over `ctx.elicit`: a connection whose request context
    is missing altogether, and one that negotiated the newest handshake version. The versions come
    off the SDK rather than being written out, so a future era moves these tests with it.
    """

    async def test_agreeing_answers_with_no_refusal(self, era: str | None) -> None:
        confirm = _confirm_with(AcceptedElicitation(data=_AGREE), era)

        assert await confirm(_QUESTION, _ABOUT) is None

    async def test_declining_refuses_and_says_nothing_happened(self, era: str | None) -> None:
        refusal = await _confirm_with(DeclinedElicitation(), era)(_QUESTION, _ABOUT)

        assert refusal is not None
        assert isinstance(refusal, str)
        assert refusal.startswith(_NOTHING_HAPPENED)
        assert "did not agree" in refusal
        assert "Do not call this tool again" in refusal

    async def test_answering_anything_but_the_agreement_refuses(self, era: str | None) -> None:
        """A client is free to send back its own text, and only the exact agreement is one."""
        refusal = await _confirm_with(AcceptedElicitation(data=_DECLINE), era)(_QUESTION, _ABOUT)

        assert isinstance(refusal, str) and "did not agree" in refusal

    async def test_a_client_that_cannot_ask_writes_nothing(self, era: str | None) -> None:
        """The risk every confirmation carries: a client with no elicitation support can no longer
        write. It has to fail closed and say why, because an operator cannot tell a broken mailbox
        from a client limitation otherwise."""
        refusal = await _confirm_with(RuntimeError("elicitation not supported"), era)(
            _QUESTION, _ABOUT
        )

        assert refusal is not None
        assert isinstance(refusal, str)
        assert refusal.startswith(_NOTHING_HAPPENED)
        assert "does not support elicitation" in refusal
        assert "Do not call this tool again" in refusal

    async def test_a_tool_error_from_the_client_is_passed_through_as_it_arrived(
        self, era: str | None
    ) -> None:
        """A `ToolError` is already a refusal worded for a caller, so re-wording it would replace
        what the client said with a guess."""
        already = ToolError("the client refused the request")

        refusal = await _confirm_with(already, era)(_QUESTION, _ABOUT)

        assert refusal == str(already)

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            AcceptedElicitation(data=_DECLINE),
            RuntimeError("elicitation not supported"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "another-answer", "cannot-ask", "client-error"],
    )
    async def test_no_refusal_is_ever_raised(self, answer: object, era: str | None) -> None:
        """Every refusal answers with a string. A raise here crosses the block that measures the
        Graph operation, which then records a person saying no as a Graph failure with the whole
        wait as its latency."""
        refusal = await _confirm_with(answer, era)(_QUESTION, _ABOUT)

        assert isinstance(refusal, str) and refusal


_ACCEPTED_AGREEMENT = ElicitResult(action="accept", content={"value": _AGREE})

# Everything a client can send back that is not this request's agreement. The off-schema pair are
# the `pydantic.ValidationError` path, and the sampling result is an answer of the wrong kind
# altogether under the right key.
_NOT_AN_AGREEMENT: list[object] = [
    ElicitResult(action="accept", content={"value": _DECLINE}),
    ElicitResult(action="decline"),
    ElicitResult(action="cancel"),
    # A dismissal that still carries the filled-in form: the action decides, never the content.
    ElicitResult(action="decline", content={"value": _AGREE}),
    ElicitResult(action="cancel", content={"value": _AGREE}),
    ElicitResult(action="accept", content={}),
    ElicitResult(action="accept", content={"value": "whatever the client felt like"}),
    CreateMessageResult(
        role="assistant", content=TextContent(type="text", text=_AGREE), model="a-model"
    ),
]
_NOT_AN_AGREEMENT_IDS = [
    "the-other-answer",
    "declined",
    "cancelled",
    "declined-but-filled-in",
    "cancelled-but-filled-in",
    "empty-content",
    "off-schema-content",
    "another-kind-of-answer",
]


def _modern(*, responses: dict[str, object] | None = None, state: str | None = None) -> Confirm:
    """A 2026-07-28 connection. Its `elicit` raises, so a question that leaked back onto the
    back-channel fails instead of quietly working."""
    return _confirming(
        _Client(
            AssertionError("a 2026-07-28 connection has no back-channel to elicit over"),
            era=LATEST_MODERN_VERSION,
            responses=responses,
            state=state,
        )
    )


async def _the_question() -> InputRequiredResult:
    """Round one, as the object the tool returns to the client."""
    question = await _modern()(_QUESTION, _ABOUT)

    assert isinstance(question, InputRequiredResult)
    return question


def _under_its_own_key(question: InputRequiredResult, answer: object) -> dict[str, object]:
    """The answer filed under the key round one minted. A literal here would let the ask and the
    answer drift apart without a test noticing."""
    assert question.input_requests is not None
    (key,) = question.input_requests
    return {key: answer}


async def _answering(answer: object, *, state: str | None = _ABOUT) -> Confirmed:
    """Round two: the same question again, with what the client says the person answered."""
    question = await _the_question()

    return await _modern(responses=_under_its_own_key(question, answer), state=state)(
        _QUESTION, _ABOUT
    )


class TestTheEraWithNoBackChannel:
    """A 2026-07-28 connection has no server-to-client channel (SEP-2577), so the question is what
    the tool answers with and the client calls the tool again with what the person said."""

    async def test_round_one_answers_with_the_question_bound_to_the_request(self) -> None:
        question = await _the_question()

        assert question.request_state == _ABOUT

    async def test_the_question_carries_the_tools_wording_and_the_two_answers(self) -> None:
        question = await _the_question()

        assert question.input_requests is not None
        (request,) = question.input_requests.values()
        assert isinstance(request, ElicitRequest)
        assert isinstance(request.params, ElicitRequestFormParams)
        assert request.params.message == _QUESTION
        schema = cast(
            "Mapping[str, Mapping[str, Mapping[str, object]]]", request.params.requested_schema
        )
        assert schema["properties"]["value"]["enum"] == [_AGREE, _DECLINE]

    async def test_an_agreement_bound_to_this_request_lets_the_write_happen(self) -> None:
        assert await _answering(_ACCEPTED_AGREEMENT) is None

    @pytest.mark.parametrize("answer", _NOT_AN_AGREEMENT, ids=_NOT_AN_AGREEMENT_IDS)
    async def test_nothing_else_a_client_can_send_is_an_agreement(self, answer: object) -> None:
        """The same refusal as the handshake era, in the same words: what a model needs first is
        that the write did not happen, and the era it was refused on is not its business."""
        refusal = await _answering(answer)

        assert isinstance(refusal, str)
        assert refusal.startswith(_NOTHING_HAPPENED)
        assert "did not agree" in refusal
        assert "Do not call this tool again" in refusal

    @pytest.mark.parametrize("state", [None, _ANOTHER_REQUEST], ids=["no-state", "another-id"])
    async def test_an_agreement_bound_to_another_request_authorizes_nothing(
        self, state: str | None
    ) -> None:
        """The whole of what `about` is for: round two composes its own draft, and an accept that
        came back for a different one was never given for the write this call would make."""
        refusal = await _answering(_ACCEPTED_AGREEMENT, state=state)

        assert isinstance(refusal, str)
        assert refusal.startswith(_NOTHING_HAPPENED)
        assert "given for a different request" in refusal
        assert "Do not call this tool again" in refusal

    async def test_a_client_that_comes_back_with_no_answer_is_asked_again(self) -> None:
        """`input_responses` is `None` again when a client retries without answering. That is a
        question still waiting to be put, and not a person who said no."""
        again = await _modern(responses=None, state=_ABOUT)(_QUESTION, _ABOUT)

        assert isinstance(again, InputRequiredResult)
        assert again.request_state == _ABOUT

    async def test_an_agreement_filed_under_another_key_is_not_this_question_answered(
        self,
    ) -> None:
        """The client answers under the key the question was minted with. An agreement under any
        other key is nobody's answer to this question, so it is asked again, never acted on."""
        question = await _modern()(_QUESTION, _ABOUT)
        assert isinstance(question, InputRequiredResult)
        (minted,) = question.input_requests or {}

        again = await _modern(responses={f"not-{minted}": _ACCEPTED_AGREEMENT}, state=_ABOUT)(
            _QUESTION, _ABOUT
        )

        assert isinstance(again, InputRequiredResult)
        assert again.request_state == _ABOUT

    async def test_no_answer_on_this_era_is_ever_raised(self) -> None:
        """Every refusal answers with a string here too. A raise crosses the block that measures
        the Graph operation, which then records a person saying no as a Graph failure."""
        for answer in _NOT_AN_AGREEMENT:
            assert isinstance(await _answering(answer), str)

        assert isinstance(await _answering(_ACCEPTED_AGREEMENT, state=_ANOTHER_REQUEST), str)
        assert await _answering(_ACCEPTED_AGREEMENT) is None
        assert isinstance(await _modern()(_QUESTION, _ABOUT), InputRequiredResult)


class TestWhatTheMiddlewareLeavesAlone:
    """The middleware words a refusal *or* keeps its hands off it. There is nothing in between."""

    async def test_it_words_a_graph_refusal_the_way_the_mapping_itself_does(self) -> None:
        """Byte equality and not keywords: one wording for a refusal is the whole promise of
        moving the mapping out of ten tool bodies."""
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
        """Whatever `graph_tool_errors` worded arrives as a type the middleware recognises rather
        than re-derives, which matters where the two wordings would differ."""
        with pytest.raises(ToolError) as raised, graph_tool_errors(_CHANNELS):
            raise GraphForbidden("nope", status=403, code=None, request_id=None)
        advised = raised.value

        assert await _middleware_message(advised) == str(advised)
        assert _CHANNELS in str(advised), "the tool's own permission, not the table's"
        assert _PERMISSION not in str(advised)

    async def test_a_tool_error_about_an_argument_is_not_a_graph_failure(self) -> None:
        refusal = ToolError("teams_read_transcript takes teams:///transcripts/{a}/{b}.")

        assert await _middleware_message(refusal) == str(refusal)

    async def test_a_refusal_for_an_unknown_tool_keeps_its_own_report(self) -> None:
        """Unreachable while the table and the registration come from one resolved selection. The
        alternative, an `assert`, answers a caller who could have acted on the 403."""
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
