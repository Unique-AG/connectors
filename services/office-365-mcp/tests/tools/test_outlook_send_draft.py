"""Every payload here is synthesised. No message in this file was ever sent from a real mailbox."""

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
from msgraph.generated.models.message import Message
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE
from office_365_mcp.tools import outlook_send_draft as sender
from office_365_mcp.tools.outlook_send_draft import MailSent, a_person_agrees, send_draft

_DRAFT_ID = "AAMkAGI2SYNTHETIC-draft-0001="

_DRAFT_REF = "outlook:///drafts/AAMkAGI2SYNTHETIC-draft-0001%3D"

# The SDK re-encodes the id for the URL, so this is what the decoded handle comes back as.
_DRAFT_PATH = "/me/messages/AAMkAGI2SYNTHETIC-draft-0001%3D"
_SEND_PATH = f"{_DRAFT_PATH}/send"

_SEND_MAIL_PATH = "/me/sendMail"

_ADA = "ada@example.invalid"
_GRACE = "grace@example.invalid"
_PAM = "pam@example.invalid"

_SUBJECT = "Invoice 4471"


def _recipient(name: str, address: str) -> dict[str, object]:
    return {"emailAddress": {"name": name, "address": address}}


def _draft(
    *,
    to: Sequence[Mapping[str, object]] = (),
    cc: Sequence[Mapping[str, object]] = (),
    subject: str | None = _SUBJECT,
    is_draft: bool | None = True,
) -> dict[str, object]:
    """Graph's answer to the pre-read: the projection this tool asks for, and nothing else."""
    return {
        "id": _DRAFT_ID,
        "isDraft": is_draft,
        "subject": subject,
        "toRecipients": [dict(one) for one in (to or [_recipient("Ada Lovelace", _ADA)])],
        "ccRecipients": [dict(one) for one in cc],
    }


def _reads(graph: respx.MockRouter, payload: dict[str, object]) -> respx.Route:
    return graph.get(_DRAFT_PATH).mock(return_value=httpx.Response(200, json=payload))


async def _agrees(draft: Message) -> str | None:
    """A person who said yes. Named rather than a lambda, because every call below states which
    side of the gate it is testing."""
    assert draft is not None
    return None


async def _refuses(draft: Message) -> str | None:
    """A person who said no, in the shape the tool's own refusal takes: answered, never raised."""
    assert draft is not None
    return "Nothing was sent."


def _sends(graph: respx.MockRouter) -> respx.Route:
    """Microsoft answers this route 202 with an empty body, which is why nothing is echoed."""
    return graph.post(_SEND_PATH).mock(return_value=httpx.Response(202))


def _ready(graph: respx.MockRouter, payload: dict[str, object] | None = None) -> respx.Route:
    """The read mocked and the send mocked, answering the send route for a test about the read."""
    _ = _reads(graph, payload if payload is not None else _draft())
    return _sends(graph)


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    """The published schema and annotations, which is the surface a client actually reads."""
    mcp: FastMCP = FastMCP(name="schema-under-test")
    sender.register(mcp, transport)
    tool = await mcp.get_tool(sender.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


class TestThePersonBetweenTheDraftAndTheSend:
    """The tool description used to ask the model to show the draft to somebody. This is the
    mechanism that replaced that request."""

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
        """The read is what makes the question answerable, and the send is what it gates, so the
        confirmation has to sit between them rather than beside them."""
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
        """`Mail.ReadBasic` excludes the body, so recipients and subject are the whole of what
        this tool can put to a person. All of it has to be in the question."""
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
    """`a_person_agrees` is the adapter from this tool to the caller's own client. Everything a
    client can answer, and everything it can fail to answer, decides whether mail goes out."""

    @staticmethod
    def _context(answer: object) -> Context:
        class _Client:
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

        assert "still in Drafts" in (await confirm(Message(subject="Invoice 4471")) or "")

    async def test_cancelling_refuses_too(self) -> None:
        confirm = a_person_agrees(self._context(CancelledElicitation()))

        assert "did not agree" in (await confirm(Message(subject="Invoice 4471")) or "")

    async def test_answering_anything_but_send_refuses(self) -> None:
        confirm = a_person_agrees(self._context(AcceptedElicitation(data="do not send")))

        assert "did not agree" in (await confirm(Message(subject="Invoice 4471")) or "")

    async def test_a_client_that_cannot_ask_sends_nothing(self) -> None:
        """The risk this whole gate carries: a client with no elicitation support can no longer
        send. It has to fail closed, and it has to say why, because the operator cannot tell a
        broken mailbox from a client limitation otherwise."""
        confirm = a_person_agrees(self._context(RuntimeError("elicitation not supported")))

        answer = await confirm(Message(subject="Invoice 4471"))
        assert "does not support elicitation" in (answer or "")

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
        """Every refusal answers with a string. A raise here crosses `graph_errors`, and the seam
        then records a person saying no as a Graph failure with the whole wait as its latency."""
        confirm = a_person_agrees(self._context(answer))

        refusal = await confirm(Message(subject="Invoice 4471"))

        assert isinstance(refusal, str) and refusal


class TestWhatItAsksGraphFor:
    async def test_it_reads_the_draft_and_then_sends_it_and_makes_no_other_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Two requests, in this order. Counting every call is the check that survives somebody
        adding a third under a path this test did not think to name."""
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
        """Graph returns nothing a projection does not name, and all three are load-bearing: the
        first two are the record of what was sent, the third is what stops an already-sent message.
        """
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
        """The words are already in the conversation; reading them back would spend context and
        ask for more than the least privileged permission this tool declares covers."""
        read = _reads(graph, _draft())
        _ = _sends(graph)

        _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        selected = read.calls.last.request.url.params["$select"]
        assert "body" not in selected.casefold()

    async def test_both_requests_declare_the_immutable_id_space(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Every handle this connector mints carries an immutable id, and Graph reads an id in the
        path in whichever space the request declares — so the header travels with both calls."""
        read = _reads(graph, _draft())
        send = _sends(graph)

        _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert read.calls.last.request.headers["prefer"] == 'IdType="ImmutableId"'
        assert send.calls.last.request.headers["prefer"] == 'IdType="ImmutableId"'

    async def test_the_send_carries_no_request_body_at_all(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A body is where a flag suppressing the copy in Sent Items would have to go, and there
        is no body to put one in."""
        send = _ready(graph)

        _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert send.calls.last.request.content == b""


class TestTheSendThatIsNeverMade:
    async def test_it_never_calls_the_one_shot_send(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`/me/sendMail` composes from arguments with no draft anybody could have read, and it is
        the one send that can leave no copy in Sent Items."""
        _ = _ready(graph)
        one_shot = graph.post(_SEND_MAIL_PATH).mock(return_value=httpx.Response(202))

        _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert one_shot.call_count == 0

    def test_the_flag_that_leaves_no_trace_is_not_spellable_in_this_file(self) -> None:
        """Not declaring the identifier is the control: a refusal at runtime would still leave the
        name in the file for the next edit to reach for."""
        source = inspect.getsource(sender).casefold()

        assert "savetosent" not in source


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_send_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The single most important line in the tool. The SDK retries POST on 429, 503 and 504
        three times by default and Graph publishes no idempotency key for sending mail, so an
        unguarded send delivers the same message up to four times.
        `tests/graph_client/test_client.py::TestANonIdempotentCallIsNotRetried` proves the default
        this overrides."""
        _ = _reads(graph, _draft())
        send = graph.post(_SEND_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert send.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_send_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """429 is on the same retry list, and a throttled send that already reached Exchange is as
        undoable as any other."""
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
        """Graph documents this route as sending an existing draft and says nothing about what it
        does to one that has already gone. An irreversible act does not rest on that."""
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
        """What the model tells the user next depends on this: 'nothing was sent by this call' and
        'the mail never went' are different claims, and only the first is true."""
        _ = _ready(graph, _draft(is_draft=False))

        with pytest.raises(ToolError, match="NOTHING WAS SENT BY THIS CALL"):
            _ = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

    async def test_a_message_handle_is_refused_and_told_why(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The draft family is this tool's defence: a message a reader found must not be spellable
        as something a sender accepts."""
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
        """The transcript is the record of who now has the mail, and only the mailbox knows that:
        this call was told an id and nothing else, so there is nothing here to echo."""
        _ = _ready(
            graph,
            _draft(
                to=[_recipient("Ada Lovelace", _ADA), _recipient("Grace Hopper", _GRACE)],
                cc=[_recipient("Pam Beesly", _PAM)],
            ),
        )

        answer = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert [address.address for address in answer.to] == [_ADA, _GRACE]
        assert [address.address for address in answer.cc] == [_PAM]

    async def test_the_subject_is_read_off_the_draft_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _draft(subject="Invoice 4471 (final)"))

        answer = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert answer.subject == "Invoice 4471 (final)"

    async def test_a_draft_with_no_subject_answers_null_rather_than_an_invented_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _draft(subject=None))

        answer = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert answer.subject is None

    async def test_an_empty_cc_comes_back_empty_rather_than_absent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _ready(graph, _draft(cc=[]))

        answer = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        assert answer.cc == []

    async def test_it_answers_when_the_send_was_accepted_as_an_instant_in_utc(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft answers a send with an empty body, so the time is clocked here. It is still
        the record of when the mail left, so it has to parse as an instant rather than read as
        prose."""
        _ = _ready(graph)
        before = datetime.now(UTC)

        answer = await send_draft(client, confirm=_agrees, draft_ref=_DRAFT_REF)

        sent_at = datetime.fromisoformat(answer.sent_at)
        assert sent_at.utcoffset() == UTC.utcoffset(None)
        assert before <= sent_at <= datetime.now(UTC)

    def test_no_blind_copy_is_addressable_in_the_answer_at_all(self) -> None:
        assert not [name for name in MailSent.model_fields if "bcc" in name.casefold()]

    @pytest.mark.parametrize("field", ["to", "cc", "sent_at"])
    def test_the_answer_says_the_send_cannot_be_taken_back(self, field: str) -> None:
        """A model reading the answer has to know there is no second call that undoes this one."""
        description = MailSent.model_fields[field].description or ""

        assert "recall" in description.casefold()


class TestTheFailuresItPassesOn:
    async def test_a_refused_pre_read_sends_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The read is first precisely so that a permission problem is met before the mail goes."""
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
        """The default 404 advice tells a caller to check the id came from a tool response, which
        this one did. What a model needs instead is that this call sent nothing and that whether
        an earlier one did is not knowable from here."""
        assert "Never report the mail as sent" in sender.GRAPH_NOT_FOUND
        assert "outlook_draft_mail" in sender.GRAPH_NOT_FOUND


class TestTheSchemaItPublishes:
    async def test_it_takes_one_argument_and_no_others(self, transport: httpx.AsyncClient) -> None:
        """One argument is the whole safety story: what is sent is what the user can already read
        in their Drafts folder, because nothing here can change it."""
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"draft_ref"}
        assert cast("Sequence[str]", parameters["required"]) == ["draft_ref"]

    @pytest.mark.parametrize(
        "word",
        ["to", "cc", "bcc", "recipient", "subject", "body", "attach", "html", "file", "save"],
    )
    async def test_no_argument_can_change_the_message_that_goes_out(
        self, transport: httpx.AsyncClient, word: str
    ) -> None:
        """The absence of the argument is the control: a published argument is an invitation the
        model takes, whatever a runtime refusal would then do with it."""
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert not [name for name in properties if word in name.casefold()]


class TestHowItDeclaresItself:
    def test_the_permissions_are_the_least_privileged_ones_for_the_two_calls_it_makes(
        self,
    ) -> None:
        """Mail.Send is the only delegated permission Microsoft publishes for the send, and
        Mail.ReadBasic is the least privileged one for the pre-read. The token is minted for
        exactly these, so declaring Mail.Send alone would 403 on the tool's own read."""
        assert sender.GRAPH_PERMISSIONS == ("Mail.Send", "Mail.ReadBasic")

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

    async def test_the_description_says_it_sends_as_the_user_and_cannot_be_undone(
        self, transport: httpx.AsyncClient
    ) -> None:
        """What a model is told is the only place these limits exist for it: nothing downstream
        re-reads the tool file."""
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert "user's own address" in lowered
        assert "cannot be undone" in lowered

    async def test_the_description_says_a_person_is_asked_before_anything_is_sent(
        self, transport: httpx.AsyncClient
    ) -> None:
        """The description used to ask the model to arrange a review. The tool arranges it now, so
        the description has to say that instead: a model told to get agreement itself would read a
        refusal as its own failure to ask."""
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert "confirm the send" in lowered
        assert "sends nothing unless they agree" in lowered
        assert "outlook_draft_mail" in lowered
