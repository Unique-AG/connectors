import inspect
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)
from fastmcp.tools import Tool
from mcp.types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    InputResponse,
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.generated.models.message import Message
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE, Confirmed
from office_365_mcp.tools import outlook_send_draft as sender
from office_365_mcp.tools.outlook_send_draft import MailSent, a_person_agrees, send_draft

_DRAFT_ID = "AAMkAGI2SYNTHETIC-draft-0001="

_DRAFT_REF = "outlook:///drafts/AAMkAGI2SYNTHETIC-draft-0001%3D"

_DRAFT_PATH = "/me/messages/AAMkAGI2SYNTHETIC-draft-0001%3D"
_SEND_PATH = f"{_DRAFT_PATH}/send"

_SEND_MAIL_PATH = "/me/sendMail"

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"
_PAM = "pam@example.invalid"

_SUBJECT = "Invoice 4471"

_NOTHING_SENT = "Nothing was sent, and the draft is untouched and still in Drafts."


def _refusal_of(answer: Confirmed) -> str:
    assert isinstance(answer, str) and answer, f"the confirmation answered {answer!r}"
    return answer


def _recipient(name: str, address: str) -> dict[str, object]:
    return {"emailAddress": {"name": name, "address": address}}


def _draft(
    *,
    to: Sequence[Mapping[str, object]] = (),
    cc: Sequence[Mapping[str, object]] = (),
    subject: str | None = _SUBJECT,
    is_draft: bool | None = True,
) -> dict[str, object]:
    return {
        "id": _DRAFT_ID,
        "isDraft": is_draft,
        "subject": subject,
        "toRecipients": [dict(one) for one in (to or [_recipient("Ada Lovelace", _ADA)])],
        "ccRecipients": [dict(one) for one in cc],
    }


def _reads(graph: respx.MockRouter, payload: dict[str, object]) -> respx.Route:
    return graph.get(_DRAFT_PATH).mock(return_value=httpx.Response(200, json=payload))


async def _agrees(draft: Message) -> Confirmed:
    assert draft is not None
    return None


async def _refuses(draft: Message) -> Confirmed:
    assert draft is not None
    return "Nothing was sent."


def _mail_sent(answer: MailSent | InputRequiredResult) -> MailSent:
    assert isinstance(answer, MailSent), "the send was answered with a question rather than made"
    return answer


def _sends(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_SEND_PATH).mock(return_value=httpx.Response(202))


def _ready(graph: respx.MockRouter, payload: dict[str, object] | None = None) -> respx.Route:
    _ = _reads(graph, payload if payload is not None else _draft())
    return _sends(graph)


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    sender.register(mcp, transport)
    tool = await mcp.get_tool(sender.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestThePersonBetweenTheDraftAndTheSend:
    async def test_a_refusal_sends_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        send = _ready(graph)

        with pytest.raises(ToolError, match="Nothing was sent"):
            _ = await send_draft(client, confirm=_refuses, draft_ref=_DRAFT_REF)

        assert send.call_count == 0, "a declined send still reached the mailbox"

    async def test_the_question_comes_after_the_read_and_before_the_send(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        send = _ready(graph)
        calls_when_asked: list[int] = []

        async def watching(draft: Message) -> None:
            assert draft is not None
            calls_when_asked.append(len(graph.calls))

        _ = await send_draft(client, confirm=watching, draft_ref=_DRAFT_REF)

        assert calls_when_asked == [1], "asked before the read, or after the send"
        assert send.call_count == 1

    async def test_the_question_names_every_recipient_and_the_subject(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        asked: list[Message] = []

        async def capturing(draft: Message) -> None:
            asked.append(draft)

        _ = await send_draft(client, confirm=capturing, draft_ref=_DRAFT_REF)

        assert len(asked) == 1
        addresses = {
            one.email_address.address
            for one in (asked[0].to_recipients or []) + (asked[0].cc_recipients or [])
            if one.email_address is not None
        }
        assert addresses, "the question was asked about a draft with nobody on it"
        assert asked[0].subject is not None


class TestHowTheQuestionReachesAPerson:
    @staticmethod
    def _context(answer: object) -> Context:

        class _Client:
            request_context: object = None

            async def elicit(self, message: str, response_type: object = None) -> object:
                assert message
                assert response_type is not None, "the caller must say what it expects back"
                if isinstance(answer, Exception):
                    raise answer
                return answer

        return cast("Context", cast("object", _Client()))

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(self._context(AcceptedElicitation(data=sender.SEND)))

        assert await confirm(Message(subject="Invoice 4471")) is None

    async def test_declining_refuses_and_says_the_draft_survives(self) -> None:
        confirm = a_person_agrees(self._context(DeclinedElicitation()))

        refusal = await confirm(Message(subject="Invoice 4471"))

        assert isinstance(refusal, str)
        assert refusal.startswith(_NOTHING_SENT), refusal

    async def test_cancelling_refuses_too(self) -> None:
        confirm = a_person_agrees(self._context(CancelledElicitation()))

        assert "did not agree" in _refusal_of(await confirm(Message(subject="Invoice 4471")))

    async def test_answering_anything_but_send_refuses(self) -> None:
        confirm = a_person_agrees(self._context(AcceptedElicitation(data="do not send")))

        assert "did not agree" in _refusal_of(await confirm(Message(subject="Invoice 4471")))

    async def test_a_client_that_cannot_ask_sends_nothing(self) -> None:
        confirm = a_person_agrees(self._context(RuntimeError("elicitation not supported")))

        answer = _refusal_of(await confirm(Message(subject="Invoice 4471")))

        assert "does not support elicitation" in answer
        assert answer.startswith(_NOTHING_SENT), answer

    @pytest.mark.parametrize(
        "answer",
        [
            DeclinedElicitation(),
            CancelledElicitation(),
            AcceptedElicitation(data="do not send"),
            RuntimeError("elicitation not supported"),
            ToolError("the client refused the request"),
        ],
        ids=["declined", "cancelled", "another-answer", "cannot-ask", "client-error"],
    )
    async def test_no_refusal_is_ever_raised(self, answer: object) -> None:
        confirm = a_person_agrees(self._context(answer))

        refusal = await confirm(Message(subject="Invoice 4471"))

        assert isinstance(refusal, str) and refusal


class _ModernRequest:
    protocol_version: str = LATEST_MODERN_VERSION


def _modern_context(
    *, answers: Mapping[str, InputResponse] | None = None, state: str | None = None
) -> Context:

    class _Client:
        request_context: _ModernRequest = _ModernRequest()
        input_responses: Mapping[str, InputResponse] | None = answers
        request_state: str | None = state

        async def elicit(self, message: str, response_type: object = None) -> object:
            raise AssertionError(
                f"a connection with no back-channel was asked {message!r} over it, "
                + f"expecting {response_type!r} back"
            )

    return cast("Context", cast("object", _Client()))


def _the_question(answer: MailSent | InputRequiredResult) -> tuple[str, str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    params = request.params
    assert isinstance(params, ElicitRequestFormParams), "the question is not one a client can fill"
    assert params.message, "the person is asked nothing at all"
    schema = cast("Mapping[str, object]", params.requested_schema)
    properties = cast("Mapping[str, object]", schema["properties"])
    choices = cast("Sequence[str]", cast("Mapping[str, object]", properties["value"])["enum"])
    assert list(choices) == [sender.SEND, "do not send"], f"the answers offered were {choices}"
    assert answer.request_state == params.message, (
        "the answer is bound to the question, so an edited draft cannot be sent on a stale accept"
    )
    return key, params.message, choices[0]


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_reaches_the_send(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _draft())
        send = _sends(graph)

        answer = await send_draft(
            client, confirm=a_person_agrees(_modern_context()), draft_ref=_DRAFT_REF
        )

        _key, _state, _agrees_with = _the_question(answer)
        assert read.call_count == 1
        assert send.call_count == 0, "an unanswered question sent the mail anyway"

    async def test_the_first_round_asks_the_question_this_tool_words(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(
            graph,
            _draft(to=[_recipient("Ada Lovelace", _ADA)], cc=[_recipient("Pam Beesly", _PAM)]),
        )

        answer = await send_draft(
            client, confirm=a_person_agrees(_modern_context()), draft_ref=_DRAFT_REF
        )

        _key, question, _agrees_with = _the_question(answer)
        assert _SUBJECT in question
        assert _ADA in question
        assert _PAM in question
        assert "cannot be undone" in question

    async def test_the_second_round_sends_the_draft_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        send = _ready(graph)
        key, state, agrees_with = _the_question(
            await send_draft(
                client, confirm=a_person_agrees(_modern_context()), draft_ref=_DRAFT_REF
            )
        )

        answer = await send_draft(
            client,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                )
            ),
            draft_ref=_DRAFT_REF,
        )

        posted = [
            call.request.url.path
            for call in cast("Sequence[Call]", graph.calls)
            if call.request.method == "POST"
        ]

        assert _mail_sent(answer).subject == _SUBJECT
        assert send.call_count == 1, "the confirmed send did not happen exactly once"
        assert len(posted) == 1, f"the two rounds together posted {posted}"

    async def test_an_answer_bound_to_another_question_sends_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        send = _ready(graph)
        key, _state, agrees_with = _the_question(
            await send_draft(
                client, confirm=a_person_agrees(_modern_context()), draft_ref=_DRAFT_REF
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await send_draft(
                client,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state="Send the draft 'something else' to nobody?",
                    )
                ),
                draft_ref=_DRAFT_REF,
            )

        assert send.call_count == 0, "mail went out under an answer nobody gave for this draft"

    async def test_a_second_round_the_person_declined_sends_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        send = _ready(graph)
        key, state, _agrees_with = _the_question(
            await send_draft(
                client, confirm=a_person_agrees(_modern_context()), draft_ref=_DRAFT_REF
            )
        )

        with pytest.raises(ToolError, match="did not agree") as raised:
            _ = await send_draft(
                client,
                confirm=a_person_agrees(
                    _modern_context(answers={key: ElicitResult(action="decline")}, state=state)
                ),
                draft_ref=_DRAFT_REF,
            )

        assert str(raised.value).startswith(_NOTHING_SENT)
        assert send.call_count == 0

    async def test_a_draft_that_went_out_between_the_rounds_is_refused_before_anybody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _draft())
        send = _sends(graph)
        key, state, agrees_with = _the_question(
            await send_draft(
                client, confirm=a_person_agrees(_modern_context()), draft_ref=_DRAFT_REF
            )
        )
        _ = read.mock(return_value=httpx.Response(200, json=_draft(is_draft=False)))

        with pytest.raises(ToolError, match="NOTHING WAS SENT BY THIS CALL"):
            _ = await send_draft(
                client,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    )
                ),
                draft_ref=_DRAFT_REF,
            )

        assert send.call_count == 0, "a message that was no longer a draft was sent anyway"


class TestWhatItAsksGraphFor:
    async def test_it_reads_the_draft_and_then_sends_it_and_makes_no_other_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _draft())
        send = _sends(graph)

        _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert read.call_count == 1
        assert send.call_count == 1
        assert len(graph.calls) == 2, "a send costs the pre-read and the send, and nothing else"
        made = cast("Sequence[Call]", graph.calls)
        assert [call.request.method for call in made] == ["GET", "POST"]

    async def test_the_pre_read_selects_the_recipients_the_subject_and_whether_it_is_a_draft(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _draft())
        _ = _sends(graph)

        _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        selected = read.calls.last.request.url.params["$select"]
        assert "toRecipients" in selected
        assert "ccRecipients" in selected
        assert "subject" in selected
        assert "isDraft" in selected

    async def test_the_pre_read_never_asks_for_the_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _draft())
        _ = _sends(graph)

        _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        selected = read.calls.last.request.url.params["$select"]
        assert "body" not in selected.casefold()

    async def test_both_requests_declare_the_immutable_id_space(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _draft())
        send = _sends(graph)

        _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert read.calls.last.request.headers["prefer"] == 'IdType="ImmutableId"'
        assert send.calls.last.request.headers["prefer"] == 'IdType="ImmutableId"'

    async def test_the_send_carries_no_request_body_at_all(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        send = _ready(graph)

        _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert send.calls.last.request.content == b""


class TestTheSendThatIsNeverMade:
    async def test_it_never_calls_the_one_shot_send(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        one_shot = graph.post(_SEND_MAIL_PATH).mock(return_value=httpx.Response(202))

        _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert one_shot.call_count == 0

    def test_the_flag_that_leaves_no_trace_is_not_spellable_in_this_file(self) -> None:
        source = inspect.getsource(sender).casefold()

        assert "savetosent" not in source


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_send_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _draft())
        send = graph.post(_SEND_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert send.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_send_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _draft())
        send = graph.post(_SEND_PATH).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "12"})
        )

        with pytest.raises(Exception):  # noqa: B017, PT011
            _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert send.call_count == 1


class TestTheMessagesItRefusesToSend:
    async def test_a_message_that_is_no_longer_a_draft_is_never_sent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _draft(is_draft=False))
        send = _sends(graph)

        with pytest.raises(ToolError):
            _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert send.call_count == 0, "the pre-read is what stops the send, so nothing went out"

    async def test_a_draft_graph_does_not_say_is_one_is_refused_rather_than_assumed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _draft(is_draft=None))
        send = _sends(graph)

        with pytest.raises(ToolError):
            _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert send.call_count == 0

    async def test_the_refusal_says_the_mail_may_already_have_gone(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _draft(is_draft=False))

        with pytest.raises(ToolError, match="NOTHING WAS SENT BY THIS CALL"):
            _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

    async def test_a_message_handle_is_refused_and_told_why(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)

        with pytest.raises(ToolError, match="COMPOSED"):
            _ = await send_draft(
                client,
                confirm=_agrees,
                draft_ref="outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D",
            )

        assert len(graph.calls) == 0, "a refused argument never reaches the mailbox"

    async def test_the_message_refusal_points_at_the_drafting_tools(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(ToolError, match="outlook_draft_reply"):
            _ = await send_draft(
                client,
                confirm=_agrees,
                draft_ref="outlook:///messages/AAMkAGI2SYNTHETIC-immutable-0001%3D",
            )

    @pytest.mark.parametrize(
        "draft_ref",
        [
            "outlook:///folders/AQMkADAwSYNTHETIC-folder",
            "outlook:///rules/SYNTHETIC-rule-0001",
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000",
            "outlook:///drafts/",
            "outlook:///drafts/%20",
            "AAMkAGI2SYNTHETIC-draft-0001=",
            "https://outlook.office365.invalid/owa/?ItemID=synthetic-draft",
            _SUBJECT,
            _ADA,
        ],
    )
    async def test_anything_that_is_not_a_draft_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, draft_ref: str
    ) -> None:
        _ = _ready(graph)

        with pytest.raises(ToolError):
            _ = await send_draft(client, confirm=_agrees, draft_ref=draft_ref)

        assert len(graph.calls) == 0


class TestWhatItAnswers:
    async def test_the_recipients_are_read_off_the_draft_microsoft_held(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(
            graph,
            _draft(
                to=[_recipient("Ada Lovelace", _ADA), _recipient("Grace Hopper", _GRACE)],
                cc=[_recipient("Pam Beesly", _PAM)],
            ),
        )

        answer = _mail_sent(await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF))

        assert [address.address for address in answer.to] == [_ADA, _GRACE]
        assert [address.address for address in answer.cc] == [_PAM]

    async def test_the_subject_is_read_off_the_draft_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _draft(subject="Invoice 4471 (final)"))

        answer = _mail_sent(await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF))

        assert answer.subject == "Invoice 4471 (final)"

    async def test_a_draft_with_no_subject_answers_null_rather_than_an_invented_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _draft(subject=None))

        answer = _mail_sent(await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF))

        assert answer.subject is None

    async def test_an_empty_cc_comes_back_empty_rather_than_absent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _draft(cc=[]))

        answer = _mail_sent(await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF))

        assert answer.cc == []

    async def test_it_answers_when_the_send_was_accepted_as_an_instant_in_utc(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph)
        before = datetime.now(UTC)

        answer = _mail_sent(await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF))

        sent_at = datetime.fromisoformat(answer.sent_at)
        assert sent_at.utcoffset() == UTC.utcoffset(None)
        assert before <= sent_at <= datetime.now(UTC)

    def test_no_blind_copy_is_addressable_in_the_answer_at_all(self) -> None:
        assert not [name for name in MailSent.model_fields if "bcc" in name.casefold()]


class TestTheFailuresItPassesOn:
    async def test_a_refused_pre_read_sends_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_DRAFT_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )
        send = _sends(graph)

        with pytest.raises(GraphForbidden):
            _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert send.call_count == 0

    async def test_a_draft_graph_will_not_return_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_DRAFT_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "Not Found"}}
            )
        )
        send = _sends(graph)

        with pytest.raises(GraphNotFound):
            _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert send.call_count == 0

    async def test_a_refused_send_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph, _draft())
        _ = graph.post(_SEND_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

    def test_its_not_found_advice_never_reports_the_mail_as_sent(self) -> None:
        assert "Never report the mail as sent" in sender.GRAPH_NOT_FOUND
        assert "outlook_draft_mail" in sender.GRAPH_NOT_FOUND


class TestTheSchemaItPublishes:
    async def test_it_takes_two_arguments_and_only_one_is_required(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"draft_ref", "mailbox"}
        assert cast("Sequence[str]", parameters["required"]) == ["draft_ref"]

    @pytest.mark.parametrize(
        "word",
        ["to", "cc", "bcc", "recipient", "subject", "body", "attach", "html", "file", "save"],
    )
    async def test_no_argument_can_change_the_message_that_goes_out(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]


class TestMailboxTargeting:
    async def test_no_mailbox_reads_and_sends_from_the_signed_in_users_own_mailbox(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = _reads(graph, _draft())
        send = _sends(graph)

        _ = _mail_sent(await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF))

        assert read.called
        assert send.called

    async def test_a_mailbox_reads_and_sends_from_that_mailbox_instead_of_me(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        read = graph.get(
            "/users/alex@example.invalid/messages/AAMkAGI2SYNTHETIC-draft-0001%3D"
        ).mock(return_value=httpx.Response(200, json=_draft()))
        send = graph.post(
            "/users/alex@example.invalid/messages/AAMkAGI2SYNTHETIC-draft-0001%3D/send"
        ).mock(return_value=httpx.Response(202))

        sent = _mail_sent(
            await send_draft(
                client,
                confirm=_agrees,
                draft_ref=_DRAFT_REF,
                mailbox="alex@example.invalid",
            )
        )

        assert read.called
        assert send.called
        assert sent.to


class TestHowItDeclaresItself:
    def test_the_permissions_are_the_least_privileged_ones_for_the_two_calls_it_makes(
        self,
    ) -> None:
        assert sender.GRAPH_PERMISSIONS == (
            "Mail.Send",
            "Mail.ReadBasic",
            "Mail.Send.Shared",
            "Mail.Read.Shared",
        )

    def test_its_two_steps_are_the_two_calls_it_makes(self) -> None:
        assert sender.STEP_READ_DRAFT == "read_draft"
        assert sender.STEP_SEND_DRAFT == "send_draft"

    async def test_it_announces_itself_as_a_write_that_cannot_be_taken_back(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None, (
            "a tool with no annotations joins the write surface by omission"
        )
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE["idempotentHint"]

    async def test_the_description_says_it_sends_as_the_mailbox_and_cannot_be_undone(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert "cannot be undone" in lowered

    async def test_the_description_says_a_person_is_asked_before_anything_is_sent(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert "approve" in lowered
        assert "outlook_draft_mail" in lowered
