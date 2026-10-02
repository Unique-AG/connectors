import json
from collections.abc import Mapping, Sequence
from contextlib import AbstractContextManager
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError, ValidationError
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

from office_365_mcp.graph_client import (
    GraphForbidden,
    GraphNotFound,
    GraphThrottled,
    GraphUnavailable,
    graph_errors,
)
from office_365_mcp.shared.handles import MessageHandle, message_handle
from office_365_mcp.shared.messages import ChannelImportance, Mention, TeamsMessage
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm, Confirmed
from office_365_mcp.tools import teams_send_channel_message as sender
from office_365_mcp.tools.teams_send_channel_message import a_person_agrees, send_channel_message

from .conftest import TEAMS_SENDER, message_payload

_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"
_SEND_PATH = f"/teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages"
_ROOT_ID = "1770000000001"
_REPLY_PATH = f"{_SEND_PATH}/{_ROOT_ID}/replies"

_MESSAGE = "Ship it Friday."
_SUBJECT = "Release plan"
_SENT_MESSAGE_ID = "1770000000002"
_SENT_WEB_URL = f"https://teams.microsoft.invalid/l/message/{_CHANNEL_ID}/{_SENT_MESSAGE_ID}"

_NOTHING_SENT = "Nothing was posted."

_JANE = Mention(user_id="00000000-0000-4000-8000-000000000003", name="Jane Smith")
_ADA = Mention(user_id="00000000-0000-4000-8000-000000000001", name="Ada Lovelace")


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
        web_url=_SENT_WEB_URL,
    )


def _posts(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    return graph.post(_SEND_PATH).mock(
        return_value=httpx.Response(201, json=payload if payload is not None else _sent_payload())
    )


def _replies(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_REPLY_PATH).mock(
        return_value=httpx.Response(
            201,
            json=message_payload(
                message_id=_SENT_MESSAGE_ID,
                content=_MESSAGE,
                content_type="text",
                sender=TEAMS_SENDER,
                reply_to_id=_ROOT_ID,
                web_url=_SENT_WEB_URL,
            ),
        )
    )


async def _registered(transport: httpx.AsyncClient) -> tuple[Mapping[str, object], Tool]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    sender.register(mcp, transport)
    tool = await mcp.get_tool(sender.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return cast("Mapping[str, object]", tool.parameters), tool


async def _listed(transport: httpx.AsyncClient) -> Mapping[str, Mapping[str, object]]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    sender.register(mcp, transport)
    (tool,) = await mcp.list_tools()
    return cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])


async def _send(
    client: GraphServiceClient,
    *,
    message: str = _MESSAGE,
    confirm: Confirm,
    mentions: Sequence[Mention] = (),
    subject: str | None = None,
    importance: ChannelImportance | None = None,
    reply_to_id: str | None = None,
) -> TeamsMessage | InputRequiredResult:
    return await send_channel_message(
        client,
        team_id=_TEAM_ID,
        channel_id=_CHANNEL_ID,
        message=message,
        confirm=confirm,
        mentions=mentions,
        subject=subject,
        importance=importance,
        reply_to_id=reply_to_id,
    )


async def _question_for(
    client: GraphServiceClient,
    *,
    subject: str | None = None,
    importance: ChannelImportance | None = None,
    reply_to_id: str | None = None,
) -> str:
    asked: list[str] = []

    async def capturing(question: str, _about: str) -> Confirmed:
        asked.append(question)
        return None

    _ = await _send(
        client,
        confirm=capturing,
        subject=subject,
        importance=importance,
        reply_to_id=reply_to_id,
    )

    assert len(asked) == 1
    return asked[0]


class TestThePersonBeforeThePost:
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
            assert about
            return None

        _ = await _send(client, confirm=capturing)

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

        _ = await _send(client, confirm=capturing)

        assert len(asked) == 1
        assert _TEAM_ID in asked[0]
        assert _CHANNEL_ID in asked[0]

    async def test_the_question_names_the_people_it_mentions(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await _send(client, confirm=capturing, mentions=[_JANE, _ADA])

        assert len(asked) == 1
        assert "It mentions 'Jane Smith', 'Ada Lovelace'." in asked[0]
        assert "cannot be recalled" in asked[0]

    async def test_the_question_names_the_subject_and_the_importance(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)

        question = await _question_for(client, subject=_SUBJECT, importance="high")

        assert (
            f"Post {_MESSAGE!r} with the subject {_SUBJECT!r} and high importance to channel "
            + f"{_CHANNEL_ID!r}"
        ) in question

    async def test_the_question_names_a_subject_that_comes_alone(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)

        question = await _question_for(client, subject=_SUBJECT)

        assert f"Post {_MESSAGE!r} with the subject {_SUBJECT!r} to channel" in question
        assert "importance" not in question

    async def test_the_question_names_an_importance_that_comes_alone(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)

        question = await _question_for(client, importance="normal")

        assert f"Post {_MESSAGE!r} with normal importance to channel" in question
        assert "subject" not in question

    async def test_the_question_names_neither_when_neither_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)

        question = await _question_for(client)

        assert "subject" not in question
        assert "importance" not in question

    async def test_the_question_for_a_reply_names_the_post_it_answers(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _replies(graph)

        question = await _question_for(client, reply_to_id=_ROOT_ID)

        assert question == (
            f"Post {_MESSAGE!r} as a reply to post {_ROOT_ID!r} in channel {_CHANNEL_ID!r} in "
            + f"team {_TEAM_ID!r} now? This cannot be recalled once posted."
        )

    async def test_a_refused_reply_posts_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reply = _replies(graph)

        with pytest.raises(ToolError, match=_NOTHING_SENT):
            _ = await _send(client, confirm=_refuses, reply_to_id=_ROOT_ID)

        assert reply.call_count == 0, "a declined reply still reached the thread"

    async def test_the_binding_differs_for_each_team_each_channel_and_each_thread(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        bound: list[str] = []

        async def capturing(question: str, about: str) -> Confirmed:
            assert question
            bound.append(about)
            return _NOTHING_SENT

        for team_id, channel_id, reply_to_id in (
            (_TEAM_ID, _CHANNEL_ID, None),
            ("0d1e2f3a-4b5c-4d6e-8f70-8192a3b4c5d6", _CHANNEL_ID, None),
            (_TEAM_ID, "19:other@thread.tacv2", None),
            (_TEAM_ID, _CHANNEL_ID, _ROOT_ID),
        ):
            with pytest.raises(ToolError, match=_NOTHING_SENT):
                _ = await send_channel_message(
                    client,
                    team_id=team_id,
                    channel_id=channel_id,
                    message=_MESSAGE,
                    confirm=capturing,
                    reply_to_id=reply_to_id,
                )

        assert len(set(bound)) == 4
        assert len(graph.calls) == 0

    async def test_a_subject_on_a_reply_is_refused_before_anybody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        with pytest.raises(ToolError) as raised:
            _ = await _send(client, confirm=capturing, subject=_SUBJECT, reply_to_id=_ROOT_ID)

        assert str(raised.value).endswith(
            "Nothing was posted. If you call this tool again with the same arguments, the call "
            + "will fail the same way."
        )
        assert asked == [], "the user was asked to agree to a call that cannot succeed"
        assert len(graph.calls) == 0, "a reply with a subject reached Graph"

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
    assert answer.request_state
    return key, answer.request_state, choices[0]


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

    async def test_an_accept_for_one_message_cannot_post_a_longer_message_with_the_same_preview(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        common_prefix = "x" * 120
        message_a = common_prefix + " short tail"
        message_b = common_prefix + " a very different, much longer tail than the first one"
        key, state, agrees_with = _the_question(
            await _send(client, message=message_a, confirm=a_person_agrees(_modern_context()))
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await _send(
                client,
                message=message_b,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    )
                ),
            )

        assert post.call_count == 0, "message B went out on an accept given for message A"

    async def test_an_accept_for_one_set_of_mentions_cannot_post_another(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        key, state, agrees_with = _the_question(
            await _send(client, confirm=a_person_agrees(_modern_context()), mentions=[_JANE])
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await _send(
                client,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    )
                ),
                mentions=[_ADA],
            )

        assert post.call_count == 0, "a mention of Ada went out on an accept given for Jane"

    async def test_an_accept_for_one_subject_cannot_post_under_another(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        key, state, agrees_with = _the_question(
            await _send(client, confirm=a_person_agrees(_modern_context()), subject=_SUBJECT)
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await _send(
                client,
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    )
                ),
                subject="Release cancelled",
            )

        assert post.call_count == 0, "a post went out under a subject nobody agreed to"

    async def test_an_accept_for_a_post_cannot_send_it_as_high_importance(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        key, state, agrees_with = _the_question(
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
                        state=state,
                    )
                ),
                importance="high",
            )

        assert post.call_count == 0, "a high-importance post went out on an accept for a plain one"

    async def test_an_accept_for_a_post_cannot_send_a_reply(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        reply = _replies(graph)
        key, state, agrees_with = _the_question(
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
                        state=state,
                    )
                ),
                reply_to_id=_ROOT_ID,
            )

        assert post.call_count == 0
        assert reply.call_count == 0, "a reply went out on an accept given for a new post"


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
        assert "mentions" not in body

    async def test_the_post_body_carries_the_subject_as_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await _send(client, confirm=_agrees, subject=_SUBJECT)

        body = cast("Mapping[str, object]", json.loads(post.calls.last.request.content))
        assert body["subject"] == _SUBJECT

    @pytest.mark.parametrize("importance", ["normal", "high"])
    async def test_the_post_body_carries_the_importance(
        self, client: GraphServiceClient, graph: respx.MockRouter, importance: ChannelImportance
    ) -> None:
        post = _posts(graph)

        _ = await _send(client, confirm=_agrees, importance=importance)

        body = cast("Mapping[str, object]", json.loads(post.calls.last.request.content))
        assert body["importance"] == importance

    async def test_the_post_body_carries_no_importance_and_no_subject_when_none_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await _send(client, confirm=_agrees)

        body = cast("Mapping[str, object]", json.loads(post.calls.last.request.content))
        assert "importance" not in body, "an unset importance reached Graph as a value or a null"
        assert "subject" not in body, "an unset subject reached Graph as a value or a null"

    async def test_a_mention_goes_out_as_html_with_its_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await _send(client, confirm=_agrees, mentions=[_JANE])

        body = cast("Mapping[str, object]", json.loads(post.calls.last.request.content))
        assert body["body"] == {
            "content": '<at id="0">Jane Smith</at> Ship it Friday.',
            "contentType": "html",
        }
        mentions = cast("Sequence[Mapping[str, object]]", body["mentions"])
        assert len(mentions) == 1
        assert mentions[0]["id"] == 0
        assert mentions[0]["mentionText"] == "Jane Smith"
        mentioned = cast("Mapping[str, object]", mentions[0]["mentioned"])
        assert mentioned["user"] == {
            "id": _JANE.user_id,
            "displayName": "Jane Smith",
            "userIdentityType": "aadUser",
        }

    async def test_the_channel_id_is_only_ever_read_together_with_its_team_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await _send(client, confirm=_agrees)

        assert post.call_count == 1

    async def test_a_reply_posts_once_to_the_replies_of_the_post(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        reply = _replies(graph)

        _ = await _send(client, confirm=_agrees, reply_to_id=_ROOT_ID)

        assert reply.call_count == 1
        assert post.call_count == 0, "a reply started a new post instead"
        assert len(graph.calls) == 1
        assert reply.calls.last.request.url.raw_path.decode() == "/v1.0" + _REPLY_PATH

    async def test_the_reply_body_carries_the_message_the_mentions_and_the_importance(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reply = _replies(graph)

        _ = await _send(
            client, confirm=_agrees, mentions=[_JANE], importance="high", reply_to_id=_ROOT_ID
        )

        body = cast("Mapping[str, object]", json.loads(reply.calls.last.request.content))
        assert body["body"] == {
            "content": '<at id="0">Jane Smith</at> Ship it Friday.',
            "contentType": "html",
        }
        assert len(cast("Sequence[object]", body["mentions"])) == 1
        assert body["importance"] == "high"
        assert "subject" not in body

    @pytest.mark.parametrize(
        ("reply_to_id", "expected"),
        [(None, sender.STEP_SEND), (_ROOT_ID, sender.STEP_REPLY)],
    )
    async def test_a_new_post_and_a_reply_are_measured_under_their_own_step(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
        reply_to_id: str | None,
        expected: str,
    ) -> None:
        _ = _posts(graph)
        _ = _replies(graph)
        measured: list[str | None] = []

        def recording(operation: str, *, step: str | None = None) -> AbstractContextManager[None]:
            measured.append(step)
            return graph_errors(operation, step=step)

        monkeypatch.setattr(sender, "graph_errors", recording)

        _ = await _send(client, confirm=_agrees, reply_to_id=reply_to_id)

        assert measured == [expected]


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_post_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = graph.post(_SEND_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _send(client, confirm=_agrees)

        assert post.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_reply_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reply = graph.post(_REPLY_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await _send(client, confirm=_agrees, reply_to_id=_ROOT_ID)

        assert reply.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_post_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = graph.post(_SEND_PATH).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "12"})
        )

        with pytest.raises(GraphThrottled):
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

    async def test_a_reply_answers_with_a_reply_handle_teams_read_message_can_read_back(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _replies(graph)

        answer = await _send(client, confirm=_agrees, reply_to_id=_ROOT_ID)

        assert not isinstance(answer, InputRequiredResult)
        assert answer.uri == (
            f"teams:///teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages/"
            + f"{_ROOT_ID}/replies/{_SENT_MESSAGE_ID}"
        )
        assert answer.reply_to_id == _ROOT_ID
        assert message_handle(answer.uri) == MessageHandle(
            _SENT_MESSAGE_ID, team_id=_TEAM_ID, channel_id=_CHANNEL_ID, reply_to_id=_ROOT_ID
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
        assert sender.GRAPH_PERMISSIONS == ("ChannelMessage.Send",)

    def test_its_two_steps_are_the_two_calls_it_can_make(self) -> None:
        assert sender.STEP_SEND == "send_channel_message"
        assert sender.STEP_REPLY == "reply_channel_message"

    async def test_it_announces_itself_as_an_addition_rather_than_a_destructive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    async def test_the_description_says_it_asks_before_posting(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "This tool asks the user to agree before it posts anything, every time. This tool "
            + "posts nothing unless the user agrees."
        ) in " ".join(description.split())

    async def test_the_description_says_a_posted_message_cannot_be_recalled(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert "nothing here can recall it" in (tool.description or "")

    async def test_the_retry_note_names_no_tool_and_the_outage_advice_names_the_reader(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        (retry,) = [
            " ".join(bullet.split())
            for bullet in (tool.description or "").split("\n- ")
            if bullet.startswith("If a call times out")
        ]
        assert retry == (
            "If a call times out, do not call this tool again first. Before you call again, make "
            + "sure that the channel does not already show the message."
        )
        assert "teams_browse_channel" not in retry
        assert sender.CHANGE_SHOWN_BY == ("teams_browse_channel",)

    async def test_the_description_says_reply_to_id_replies_in_a_thread(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert (
            "With `reply_to_id`, this tool replies in the thread of an existing post."
        ) in " ".join((tool.description or "").split())

    async def test_reply_to_id_takes_the_id_of_a_post_and_is_never_empty(
        self, transport: httpx.AsyncClient
    ) -> None:
        reply_to_id = (await _listed(transport))["reply_to_id"]

        described = str(reply_to_id["description"])
        assert "teams_browse_channel" in described
        assert "teams_read_message" in described
        assert "Give the id of a post, never the id of a reply." in described
        assert "To answer a reply, give the `reply_to_id` of that reply." in described
        text = cast("Sequence[Mapping[str, object]]", reply_to_id["anyOf"])[0]
        assert text["minLength"] == 1

    async def test_the_subject_says_it_is_refused_on_a_reply(
        self, transport: httpx.AsyncClient
    ) -> None:
        subject = (await _listed(transport))["subject"]

        assert "This tool refuses a subject together with `reply_to_id`." in str(
            subject["description"]
        )

    async def test_the_arguments_are_team_id_channel_id_message_and_the_optional_rest(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {
            "team_id",
            "channel_id",
            "message",
            "mentions",
            "subject",
            "importance",
            "reply_to_id",
        }
        assert set(cast("Sequence[str]", parameters["required"])) == {
            "team_id",
            "channel_id",
            "message",
        }

    async def test_the_importance_is_normal_or_high_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        importance = (await _listed(transport))["importance"]

        options = cast("Sequence[Mapping[str, object]]", importance["anyOf"])
        assert [option.get("enum") for option in options] == [["normal", "high"], None]

    async def test_an_urgent_importance_never_reaches_this_tool(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _parameters, tool = await _registered(transport)

        with pytest.raises(ValidationError, match="importance"):
            _ = await tool.run({**sender.GRAPH_CALL_EXAMPLE, "importance": "urgent"})

        assert len(graph.calls) == 0, "an importance the schema refuses reached Graph"

    async def test_the_subject_is_never_empty_and_has_no_ceiling(
        self, transport: httpx.AsyncClient
    ) -> None:
        subject = (await _listed(transport))["subject"]

        text = cast("Sequence[Mapping[str, object]]", subject["anyOf"])[0]
        assert text["minLength"] == 1
        assert "maxLength" not in text, "Microsoft documents no subject limit for a channel post"

    async def test_a_mention_by_email_address_never_reaches_this_tool(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _parameters, tool = await _registered(transport)

        with pytest.raises(ValidationError, match="match pattern"):
            _ = await tool.run(
                {
                    **sender.GRAPH_CALL_EXAMPLE,
                    "mentions": [{"user_id": "jane@example.invalid", "name": "Jane Smith"}],
                }
            )

        assert len(graph.calls) == 0, "a mention the schema refuses reached Graph"
