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
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirmed
from office_365_mcp.tools import teams_send_chat_message as sender
from office_365_mcp.tools.teams_send_chat_message import a_person_agrees, send_chat_message

from .conftest import TEAMS_SENDER, message_payload

_CHAT_ID = "19:release@thread.v2"
_SEND_PATH = "/chats/19%3Arelease%40thread.v2/messages"

_MESSAGE = "Ship it Friday."
_SENT_MESSAGE_ID = "1770000000001"

_NOTHING_SENT = "Nothing was sent."


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_SENT


def _sent_payload(
    *, message_id: str = _SENT_MESSAGE_ID, content: str = _MESSAGE
) -> Mapping[str, object]:
    return message_payload(
        message_id=message_id,
        content=content,
        content_type="text",
        sender=TEAMS_SENDER,
        web_url=None,
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


class TestThePersonBeforeTheSend:
    async def test_a_refusal_sends_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        with pytest.raises(ToolError, match=_NOTHING_SENT):
            _ = await send_chat_message(
                client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_refuses
            )

        assert post.call_count == 0, "a declined send still reached the chat"

    async def test_the_question_carries_the_message_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            asked.append(question)
            assert about == question
            return None

        _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=capturing)

        assert len(asked) == 1
        assert _MESSAGE in asked[0]
        assert "cannot be recalled" in asked[0]

    async def test_the_question_carries_the_destination(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=capturing)

        assert len(asked) == 1
        assert _CHAT_ID in asked[0]

    async def test_the_confirmation_happens_before_the_post(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=watching)

        assert calls_when_asked == [0], "asked after the post already went out"
        assert post.call_count == 1


class TestHowTheQuestionReachesAPerson:
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
        confirm = a_person_agrees(self._context(AcceptedElicitation(data="send")))

        assert await confirm("Send it?", "Send it?") is None

    async def test_declining_refuses_and_says_nothing_was_sent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        confirm = a_person_agrees(self._context(DeclinedElicitation()))

        with pytest.raises(ToolError, match=_NOTHING_SENT):
            _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=confirm)

        assert post.call_count == 0


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
        "the answer is bound to the question, so an edited message cannot be sent on a stale accept"
    )
    return key, params.message, choices[0]


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_posts(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        answer = await send_chat_message(
            client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=a_person_agrees(_modern_context())
        )

        _key, _state, _agrees_with = _the_question(answer)
        assert post.call_count == 0, "an unanswered question posted the message anyway"

    async def test_the_second_round_sends_the_message_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        key, state, agrees_with = _the_question(
            await send_chat_message(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                confirm=a_person_agrees(_modern_context()),
            )
        )

        answer = await send_chat_message(
            client,
            chat_id=_CHAT_ID,
            message=_MESSAGE,
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                )
            ),
        )

        assert post.call_count == 1, "the confirmed post did not happen exactly once"
        assert not isinstance(answer, InputRequiredResult)

    async def test_an_answer_bound_to_another_message_sends_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        key, _state, agrees_with = _the_question(
            await send_chat_message(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                confirm=a_person_agrees(_modern_context()),
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await send_chat_message(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
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

        _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees)

        assert post.call_count == 1
        assert len(graph.calls) == 1, "sending one message costs one Graph call, and nothing else"
        made = cast("Sequence[Call]", graph.calls)
        assert made[0].request.method == "POST"

    async def test_the_post_body_carries_the_message_as_plain_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees)

        body = cast("Mapping[str, object]", json.loads(post.calls.last.request.content))
        sent = cast("Mapping[str, object]", body["body"])
        assert sent["content"] == _MESSAGE
        assert sent["contentType"] == "text"

    async def test_the_chat_id_is_used_verbatim_in_the_path(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees)

        assert post.call_count == 1


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_post_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = graph.post(_SEND_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(Exception):  # noqa: B017, PT011
            _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees)

        assert post.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_post_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = graph.post(_SEND_PATH).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "12"})
        )

        with pytest.raises(Exception):  # noqa: B017, PT011
            _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees)

        assert post.call_count == 1


class TestWhatItAnswers:
    async def test_the_answer_carries_a_handle_teams_read_message_can_read_back(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)

        answer = await send_chat_message(
            client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees
        )

        assert not isinstance(answer, InputRequiredResult)
        assert answer.message_id == _SENT_MESSAGE_ID
        assert answer.chat_id == _CHAT_ID
        assert answer.uri == ("teams:///chats/19%3Arelease%40thread.v2/messages/1770000000001")

    async def test_the_answer_reports_the_text_microsoft_actually_stored(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph, _sent_payload(content="Ship it Friday, cc @Ada"))

        answer = await send_chat_message(
            client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees
        )

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
            _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees)

    async def test_a_chat_graph_will_not_post_to_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_SEND_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "ErrorItemNotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees)


class TestHowItDeclaresItself:
    def test_the_permission_is_chat_message_send_and_not_channel_message_send(self) -> None:
        assert sender.GRAPH_PERMISSIONS == ("ChatMessage.Send",)

    def test_its_one_step_is_the_one_call_it_makes(self) -> None:
        assert sender.STEP_SEND == "send_chat_message"

    async def test_it_announces_itself_as_an_addition_rather_than_a_destructive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    async def test_the_description_says_it_asks_before_sending(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        lowered = (tool.description or "").casefold()
        assert "after the user approves it" in lowered

    async def test_the_two_arguments_are_chat_id_and_message_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"chat_id", "message"}
        assert set(cast("Sequence[str]", parameters["required"])) == {"chat_id", "message"}
