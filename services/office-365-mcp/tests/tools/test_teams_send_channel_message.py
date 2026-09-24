"""Every payload in this file is synthetic. No message in this file was ever posted to a real
channel."""

import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from fastmcp.tools import Tool
from mcp.types import (
    ElicitRequest,
    ElicitRequestFormParams,
    ElicitResult,
    InputRequiredResult,
    InputResponse,
)
from mcp.types.version import LATEST_MODERN_VERSION
from msgraph.graph_service_client import GraphServiceClient
from respx.models import Call

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.messages import TeamsMessage
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm, Confirmed
from office_365_mcp.tools import teams_send_channel_message as sender
from office_365_mcp.tools.teams_send_channel_message import a_person_agrees, send_channel_message

from .conftest import TEAMS_SENDER, message_payload

_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"
_SEND_PATH = f"/teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages"

_MESSAGE = "Ship it Friday."
_SENT_MESSAGE_ID = "1770000000002"
_SENT_WEB_URL = f"https://teams.microsoft.invalid/l/message/{_CHANNEL_ID}/{_SENT_MESSAGE_ID}"

_NOTHING_SENT = "Nothing was posted."


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_SENT


def _sent_payload(
    *, message_id: str = _SENT_MESSAGE_ID, content: str = _MESSAGE
) -> Mapping[str, object]:
    """This function returns the Graph response for a successful post. It uses the same
    `chatMessage` shape that a read returns. Graph fills in the `webUrl` field for a channel post,
    but leaves it null for a chat message."""
    return message_payload(
        message_id=message_id,
        content=content,
        content_type="text",
        sender=TEAMS_SENDER,
        web_url=_SENT_WEB_URL,
    )


def _posts(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    return graph.post(_SEND_PATH).mock(
        return_value=httpx.Response(201, json=payload if payload is not None else _sent_payload())
    )


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    sender.register(mcp, transport)
    tool = await mcp.get_tool(sender.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


async def _send(
    client: GraphServiceClient, *, message: str = _MESSAGE, confirm: Confirm
) -> TeamsMessage | InputRequiredResult:
    return await send_channel_message(
        client, team_id=_TEAM_ID, channel_id=_CHANNEL_ID, message=message, confirm=confirm
    )


class TestThePersonBeforeThePost:
    """There is no draft for review here. The confirmation question is the only place where a
    person sees the words before the tool sends them, so the question must carry the message
    text."""

    async def test_a_refusal_posts_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        with pytest.raises(ToolError, match=_NOTHING_SENT):
            _ = await _send(client, confirm=_refuses)

        assert post.call_count == 0, "a declined post still reached the channel"

    async def test_the_question_carries_the_message_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            assert about == question
            return None

        _ = await _send(client, confirm=capturing)

        assert len(asked) == 1
        assert _MESSAGE in asked[0]
        assert "cannot be recalled" in asked[0]

    async def test_the_question_carries_the_destination(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A person approving a post must see WHERE it goes, not just the text: approving "post
        this" in a multi-channel conversation should not silently approve the wrong channel."""
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _send(client, confirm=capturing)

        assert len(asked) == 1
        assert _TEAM_ID in asked[0]
        assert _CHANNEL_ID in asked[0]

    async def test_the_confirmation_happens_before_the_post(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await _send(client, confirm=watching)

        assert calls_when_asked == [0], "asked after the post already went out"
        assert post.call_count == 1


class TestHowTheQuestionReachesAPerson:
    """`a_person_agrees` is this tool's own adapter onto `person_confirms`. The tests in
    `tests/shared/test_seam.py` prove the mechanics of the seam itself: both protocol eras, and
    every way that a client can fail to answer. This file tests only that this tool's wiring gates
    the post on the answer."""

    @staticmethod
    def _context(answer: object) -> Context:
        class _Client:
            request_context: object = None

            async def elicit(self, message: str, response_type: object = None) -> object:
                assert message
                assert response_type is not None
                if isinstance(answer, Exception):
                    raise answer
                return answer

        return cast("Context", cast("object", _Client()))

    async def test_agreeing_answers_with_no_refusal(self) -> None:
        confirm = a_person_agrees(self._context(AcceptedElicitation(data="post")))

        assert await confirm("Post it?", "Post it?") is None

    async def test_declining_refuses_and_says_nothing_was_posted(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        confirm = a_person_agrees(self._context(DeclinedElicitation()))

        with pytest.raises(ToolError, match=_NOTHING_SENT):
            _ = await _send(client, confirm=confirm)

        assert post.call_count == 0


class _ModernRequest:
    protocol_version: str = LATEST_MODERN_VERSION


def _modern_context(
    *, answers: Mapping[str, InputResponse] | None = None, state: str | None = None
) -> Context:
    """This models a connection at protocol version 2026-07-28. The `elicit` call raises an
    exception, so a leak back onto the back-channel fails."""

    class _Client:
        request_context: _ModernRequest = _ModernRequest()
        input_responses: Mapping[str, InputResponse] | None = answers
        request_state: str | None = state

        async def elicit(self, message: str, response_type: object = None) -> object:
            raise AssertionError(
                f"a connection with no back-channel was asked {message!r} over it, expecting "
                + f"{response_type!r} back"
            )

    return cast("Context", cast("object", _Client()))


def _the_question(answer: object) -> tuple[str, str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    params = request.params
    assert isinstance(params, ElicitRequestFormParams)
    assert params.message
    schema = cast("Mapping[str, object]", params.requested_schema)
    properties = cast("Mapping[str, object]", schema["properties"])
    choices = cast("Sequence[str]", cast("Mapping[str, object]", properties["value"])["enum"])
    assert answer.request_state == params.message, (
        "the answer is bound to the question, so an edited message cannot be posted on a stale "
        + "accept"
    )
    return key, params.message, choices[0]


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_posts(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        answer = await _send(client, confirm=a_person_agrees(_modern_context()))

        _key, _state, _agrees_with = _the_question(answer)
        assert post.call_count == 0, "an unanswered question posted the message anyway"

    async def test_the_second_round_sends_the_message_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        key, state, agrees_with = _the_question(
            await _send(client, confirm=a_person_agrees(_modern_context()))
        )

        answer = await _send(
            client,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                )
            ),
        )

        assert post.call_count == 1, "the confirmed post did not happen exactly once"
        assert not isinstance(answer, InputRequiredResult)

    async def test_an_answer_bound_to_another_message_posts_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        key, _state, agrees_with = _the_question(
            await _send(client, confirm=a_person_agrees(_modern_context()))
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await _send(
                client,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state="Post something else entirely?",
                    )
                ),
            )

        assert post.call_count == 0, "a message went out under an answer nobody gave for it"


class TestWhatItAsksGraphFor:
    async def test_it_makes_exactly_one_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await _send(client, confirm=_agrees)

        assert post.call_count == 1
        assert len(graph.calls) == 1, "posting one message costs one Graph call, and nothing else"
        made = cast("Sequence[Call]", graph.calls)
        assert made[0].request.method == "POST"

    async def test_the_post_body_carries_the_message_as_plain_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await _send(client, confirm=_agrees)

        body = cast("Mapping[str, object]", json.loads(post.calls.last.request.content))
        sent = cast("Mapping[str, object]", body["body"])
        assert sent["content"] == _MESSAGE
        assert sent["contentType"] == "text"

    async def test_the_channel_id_is_only_ever_read_together_with_its_team_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await _send(client, confirm=_agrees)

        assert post.call_count == 1


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_post_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """This is the single most important line in the tool. By default, the SDK retries a POST
        request three times on a 429, 503, or 504 response. Graph publishes no idempotency key for
        a channel message post, so an unguarded post can deliver the same message up to four
        times. `tests/graph_client/test_client.py::TestANonIdempotentCallIsNotRetried` proves the
        default retry behavior that this test overrides."""
        post = graph.post(_SEND_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(Exception):  # noqa: B017, PT011
            _ = await _send(client, confirm=_agrees)

        assert post.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_post_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = graph.post(_SEND_PATH).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "12"})
        )

        with pytest.raises(Exception):  # noqa: B017, PT011
            _ = await _send(client, confirm=_agrees)

        assert post.call_count == 1


class TestWhatItAnswers:
    async def test_the_answer_carries_a_handle_teams_read_message_can_read_back(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)

        answer = await _send(client, confirm=_agrees)

        assert not isinstance(answer, InputRequiredResult)
        assert answer.message_id == _SENT_MESSAGE_ID
        assert answer.team_id == _TEAM_ID
        assert answer.channel_id == _CHANNEL_ID
        assert answer.uri == (
            f"teams:///teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages/"
            + _SENT_MESSAGE_ID
        )

    async def test_the_answer_carries_the_web_url_graph_gave_the_post(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)

        answer = await _send(client, confirm=_agrees)

        assert not isinstance(answer, InputRequiredResult)
        assert answer.web_url == _SENT_WEB_URL

    async def test_the_answer_reports_the_text_microsoft_actually_stored(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph, _sent_payload(content="Ship it Friday, cc @Ada"))

        answer = await _send(client, confirm=_agrees)

        assert not isinstance(answer, InputRequiredResult)
        assert answer.text == "Ship it Friday, cc @Ada"


class TestTheFailuresItPassesOn:
    async def test_a_refused_post_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_SEND_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "ErrorAccessDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _send(client, confirm=_agrees)

    async def test_a_channel_graph_will_not_post_to_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_SEND_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _send(client, confirm=_agrees)


class TestHowItDeclaresItself:
    def test_the_permission_is_channel_message_send(self) -> None:
        """Unlike the chat route, both of Graph's reference pages agree on this permission name.
        See the module docstring for more information."""
        assert sender.GRAPH_PERMISSIONS == ("ChannelMessage.Send",)

    def test_its_one_step_is_the_one_call_it_makes(self) -> None:
        assert sender.STEP_SEND == "send_channel_message"

    async def test_it_announces_itself_as_an_addition_rather_than_a_destructive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        """This tool creates a new message. It does not consume or overwrite anything that already
        existed. This differs from `outlook_send_draft`, which turns an existing draft into a sent
        message."""
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    async def test_the_description_says_it_asks_before_posting_and_cannot_be_undone(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert "asks the user to approve the message" in lowered
        assert "posts nothing unless they agree" in lowered
        assert "cannot be undone" in lowered

    async def test_the_three_arguments_are_team_id_channel_id_and_message(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"team_id", "channel_id", "message"}
        assert set(cast("Sequence[str]", parameters["required"])) == {
            "team_id",
            "channel_id",
            "message",
        }
