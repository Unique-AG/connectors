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
    graph_step,
)
from office_365_mcp.shared import messages
from office_365_mcp.shared.messages import ChatImportance, Mention
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirm, Confirmed
from office_365_mcp.tools import teams_send_chat_message as sender
from office_365_mcp.tools.teams_send_chat_message import a_person_agrees, send_chat_message

from .conftest import TEAMS_SENDER, message_payload

_CHAT_ID = "19:release@thread.v2"
_SEND_PATH = "/chats/19%3Arelease%40thread.v2/messages"
_MEMBERS_PATH = "/chats/19%3Arelease%40thread.v2/members"

_MESSAGE = "Ship it Friday."
_SUBJECT = "Release plan"
_SENT_MESSAGE_ID = "1770000000001"

_JANE = Mention(user_id="00000000-0000-4000-8000-000000000003", name="Jane Smith")
_ADA = Mention(user_id="00000000-0000-4000-8000-000000000001", name="Ada Lovelace")

_NOTHING_SENT = "Nothing was sent."
_NOBODY_MENTIONED = "Nobody was mentioned. Nothing was sent."


def _member(user_id: str, name: str | None) -> Mapping[str, object]:
    return {
        "@odata.type": "#microsoft.graph.aadUserConversationMember",
        "id": f"MCMj{user_id[-12:]}",
        "displayName": name,
        "userId": user_id,
        "email": None,
        "roles": ["owner"],
    }


_JANE_MEMBER = _member(_JANE.user_id, "Jane Smith")
_ADA_MEMBER = _member(_ADA.user_id, "Ada Lovelace")


def _lists_members(graph: respx.MockRouter, *members: Mapping[str, object]) -> respx.Route:
    return graph.get(_MEMBERS_PATH).mock(
        return_value=httpx.Response(200, json={"value": [dict(member) for member in members]})
    )


def _jane_and_ada_are_members(graph: respx.MockRouter) -> respx.Route:
    return _lists_members(graph, _JANE_MEMBER, _ADA_MEMBER)


def _in_question(member: Mention) -> str:
    return (
        f"the person with the Microsoft Entra object id {member.user_id!r} (the name "
        + f"{member.name!r} comes from Microsoft 365)"
    )


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


async def _listed(transport: httpx.AsyncClient) -> Mapping[str, Mapping[str, object]]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    sender.register(mcp, transport)
    (tool,) = await mcp.list_tools()
    return cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])


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
            assert about
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

    async def test_the_question_names_the_people_it_mentions(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _jane_and_ada_are_members(graph)
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await send_chat_message(
            client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=capturing, mentions=[_JANE, _ADA]
        )

        assert len(asked) == 1
        assert (
            f"It mentions the person with the Microsoft Entra object id {_JANE.user_id!r} (the "
            + "name 'Jane Smith' comes from Microsoft 365), the person with the Microsoft Entra "
            + f"object id {_ADA.user_id!r} (the name 'Ada Lovelace' comes from Microsoft 365)."
        ) in asked[0]
        assert "cannot be recalled" in asked[0]

    async def test_the_question_shows_the_name_microsoft_365_gives_and_never_the_label(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _jane_and_ada_are_members(graph)
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await send_chat_message(
            client,
            chat_id=_CHAT_ID,
            message=_MESSAGE,
            confirm=capturing,
            mentions=[Mention(user_id=_JANE.user_id, name=_ADA.name)],
        )

        assert len(asked) == 1
        assert f"It mentions {_in_question(_JANE)}." in asked[0]
        assert _ADA.name not in asked[0], "the label of the request reached the question"
        assert _ADA.user_id not in asked[0]

    @pytest.mark.parametrize(
        "members",
        [
            pytest.param((_ADA_MEMBER,), id="not-a-member"),
            pytest.param((_member(_JANE.user_id, None), _ADA_MEMBER), id="member-with-no-name"),
            pytest.param((), id="no-member"),
        ],
    )
    async def test_a_mention_of_a_person_who_is_not_a_named_member_is_refused_before_the_question(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        members: Sequence[Mapping[str, object]],
    ) -> None:
        listed = _lists_members(graph, *members)
        post = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        with pytest.raises(ToolError) as raised:
            _ = await send_chat_message(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                confirm=capturing,
                mentions=[_ADA, _JANE],
            )

        refusal = str(raised.value)
        assert repr(_JANE.user_id) in refusal
        assert _NOBODY_MENTIONED in refusal
        assert asked == [], "the user was asked to agree to a mention of a person not in the chat"
        assert listed.call_count == 1
        assert post.call_count == 0

    async def test_the_members_are_read_once_before_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        listed = _jane_and_ada_are_members(graph)
        post = _posts(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await send_chat_message(
            client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=watching, mentions=[_JANE, _ADA]
        )

        assert calls_when_asked == [1], "asked before the members were read, or after the post"
        assert (listed.call_count, post.call_count) == (1, 1)

    async def test_the_question_names_the_importance(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await send_chat_message(
            client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=capturing, importance="urgent"
        )

        assert len(asked) == 1
        assert f"Send {_MESSAGE!r} with urgent importance to chat {_CHAT_ID!r} now?" in asked[0]

    async def test_the_question_names_no_importance_when_none_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=capturing)

        assert len(asked) == 1
        assert "importance" not in asked[0]

    async def test_the_question_names_the_subject_and_the_importance(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await send_chat_message(
            client,
            chat_id=_CHAT_ID,
            message=_MESSAGE,
            confirm=capturing,
            importance="high",
            subject=_SUBJECT,
        )

        assert len(asked) == 1
        assert (
            f"Send {_MESSAGE!r} with the subject {_SUBJECT!r} and high importance to chat "
            + f"{_CHAT_ID!r} now?"
        ) in asked[0]

    async def test_the_question_names_a_subject_that_comes_alone(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await send_chat_message(
            client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=capturing, subject=_SUBJECT
        )

        expected = f"Send {_MESSAGE!r} with the subject {_SUBJECT!r} to chat {_CHAT_ID!r} now?"
        assert len(asked) == 1
        assert expected in asked[0]
        assert "importance" not in asked[0]

    async def test_the_question_names_no_subject_when_none_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await send_chat_message(
            client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=capturing, importance="normal"
        )

        assert len(asked) == 1
        assert "subject" not in asked[0]

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
    assert answer.request_state
    return key, answer.request_state, choices[0]


def _answered(key: str, state: str, agrees_with: str) -> Confirm:
    return a_person_agrees(
        _modern_context(
            answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
            state=state,
        )
    )


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

    async def test_an_accept_for_one_message_cannot_send_a_longer_message_with_the_same_preview(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        common_prefix = "x" * 120
        message_a = common_prefix + " short tail"
        message_b = common_prefix + " a very different, much longer tail than the first one"
        key, state, agrees_with = _the_question(
            await send_chat_message(
                client,
                chat_id=_CHAT_ID,
                message=message_a,
                confirm=a_person_agrees(_modern_context()),
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await send_chat_message(
                client,
                chat_id=_CHAT_ID,
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

    @pytest.mark.parametrize(
        "other",
        [
            pytest.param(_ADA, id="another-person"),
            pytest.param(Mention(user_id=_ADA.user_id, name=_JANE.name), id="same-label-other-id"),
        ],
    )
    async def test_an_accept_for_one_set_of_mentions_cannot_send_another(
        self, client: GraphServiceClient, graph: respx.MockRouter, other: Mention
    ) -> None:
        _ = _jane_and_ada_are_members(graph)
        post = _posts(graph)
        key, state, agrees_with = _the_question(
            await send_chat_message(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                confirm=a_person_agrees(_modern_context()),
                mentions=[_JANE],
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await send_chat_message(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                confirm=_answered(key, state, agrees_with),
                mentions=[other],
            )

        assert post.call_count == 0, f"{other} went out on an accept given for {_JANE}"

    async def test_an_accept_holds_for_the_same_person_under_another_label(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _jane_and_ada_are_members(graph)
        post = _posts(graph)
        key, state, agrees_with = _the_question(
            await send_chat_message(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                confirm=a_person_agrees(_modern_context()),
                mentions=[_JANE],
            )
        )

        _ = await send_chat_message(
            client,
            chat_id=_CHAT_ID,
            message=_MESSAGE,
            confirm=_answered(key, state, agrees_with),
            mentions=[Mention(user_id=_JANE.user_id, name=_ADA.name)],
        )

        assert post.call_count == 1, "the label of the request is part of what the answer binds"
        body = cast("Mapping[str, object]", json.loads(post.calls.last.request.content))
        assert body["body"] == {
            "content": '<at id="0">Jane Smith</at> Ship it Friday.',
            "contentType": "html",
        }

    async def test_an_accept_for_a_message_cannot_send_it_as_urgent(
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
                        state=state,
                    )
                ),
                importance="urgent",
            )

        assert post.call_count == 0, "an urgent message went out on an accept for a plain one"

    async def test_an_accept_for_one_subject_cannot_send_another(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)
        key, state, agrees_with = _the_question(
            await send_chat_message(
                client,
                chat_id=_CHAT_ID,
                message=_MESSAGE,
                confirm=a_person_agrees(_modern_context()),
                subject=_SUBJECT,
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
                        state=state,
                    )
                ),
                subject="Release cancelled",
            )

        assert post.call_count == 0, "a message went out under a subject nobody agreed to"


class TestWhatItAsksGraphFor:
    async def test_a_message_with_no_mention_makes_exactly_one_call(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees)

        assert post.call_count == 1
        assert len(graph.calls) == 1, (
            "a message with no mention costs one Graph call, and nothing else"
        )
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
        assert "mentions" not in body

    async def test_the_post_body_carries_the_subject_as_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await send_chat_message(
            client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees, subject=_SUBJECT
        )

        body = cast("Mapping[str, object]", json.loads(post.calls.last.request.content))
        assert body["subject"] == _SUBJECT

    @pytest.mark.parametrize("importance", ["normal", "high", "urgent"])
    async def test_the_post_body_carries_the_importance(
        self, client: GraphServiceClient, graph: respx.MockRouter, importance: ChatImportance
    ) -> None:
        post = _posts(graph)

        _ = await send_chat_message(
            client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees, importance=importance
        )

        body = cast("Mapping[str, object]", json.loads(post.calls.last.request.content))
        assert body["importance"] == importance

    async def test_the_post_body_carries_no_importance_and_no_subject_when_none_is_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _posts(graph)

        _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees)

        body = cast("Mapping[str, object]", json.loads(post.calls.last.request.content))
        assert "importance" not in body, "an unset importance reached Graph as a value or a null"
        assert "subject" not in body, "a chat message went out with a subject"

    async def test_a_mention_costs_one_read_of_the_members_before_the_post(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        listed = _jane_and_ada_are_members(graph)
        post = _posts(graph)

        _ = await send_chat_message(
            client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees, mentions=[_JANE, _ADA]
        )

        assert (listed.call_count, post.call_count) == (1, 1)
        made = cast("Sequence[Call]", graph.calls)
        assert [call.request.method for call in made] == ["GET", "POST"]

    async def test_each_call_is_measured_under_its_own_step(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _ = _jane_and_ada_are_members(graph)
        _ = _posts(graph)
        measured: list[str] = []

        def recording(step: str) -> AbstractContextManager[None]:
            measured.append(step)
            return graph_step(step)

        monkeypatch.setattr(sender, "graph_step", recording)
        monkeypatch.setattr(messages, "graph_step", recording)

        _ = await send_chat_message(
            client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees, mentions=[_JANE]
        )

        assert measured == [messages.STEP_CHAT_MEMBERS, sender.STEP_SEND]

    async def test_a_mention_goes_out_as_html_with_its_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _jane_and_ada_are_members(graph)
        post = _posts(graph)

        _ = await send_chat_message(
            client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees, mentions=[_JANE]
        )

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

    async def test_a_mention_goes_out_under_the_name_microsoft_365_gives_and_never_the_label(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _jane_and_ada_are_members(graph)
        post = _posts(graph)

        _ = await send_chat_message(
            client,
            chat_id=_CHAT_ID,
            message=_MESSAGE,
            confirm=_agrees,
            mentions=[Mention(user_id=_JANE.user_id, name=_ADA.name)],
        )

        sent = post.calls.last.request.content.decode()
        body = cast("Mapping[str, object]", json.loads(sent))
        assert body["body"] == {
            "content": '<at id="0">Jane Smith</at> Ship it Friday.',
            "contentType": "html",
        }
        mentions = cast("Sequence[Mapping[str, object]]", body["mentions"])
        assert mentions[0]["mentionText"] == "Jane Smith"
        mentioned = cast("Mapping[str, object]", mentions[0]["mentioned"])
        assert mentioned["user"] == {
            "id": _JANE.user_id,
            "displayName": "Jane Smith",
            "userIdentityType": "aadUser",
        }
        assert _ADA.name not in sent, "the label of the request reached the chat"

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

        with pytest.raises(GraphUnavailable):
            _ = await send_chat_message(client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=_agrees)

        assert post.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_post_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = graph.post(_SEND_PATH).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "12"})
        )

        with pytest.raises(GraphThrottled):
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

    async def test_a_refused_member_read_is_a_forbidden_and_asks_nobody(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_MEMBERS_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )
        post = _posts(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        with pytest.raises(GraphForbidden):
            _ = await send_chat_message(
                client, chat_id=_CHAT_ID, message=_MESSAGE, confirm=capturing, mentions=[_JANE]
            )

        assert asked == []
        assert post.call_count == 0


class TestHowItDeclaresItself:
    def test_the_permissions_are_the_chat_send_and_the_chat_read_for_the_members(self) -> None:
        assert sender.GRAPH_PERMISSIONS == ("ChatMessage.Send", "Chat.Read")

    def test_its_example_call_is_never_narrowed(self) -> None:
        assert not hasattr(sender, "GRAPH_CALL_NARROWS_TO")

    def test_its_send_step_is_send_chat_message(self) -> None:
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

        description = tool.description or ""
        assert (
            "This tool asks the user to agree before it sends anything, every time. This tool "
            + "sends nothing unless the user agrees."
        ) in " ".join(description.split())

    async def test_the_description_says_a_sent_message_cannot_be_recalled(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert "nothing here can recall it" in (tool.description or "")

    async def test_the_description_says_the_question_shows_the_object_id_and_the_member_name(
        self, transport: httpx.AsyncClient
    ) -> None:
        _parameters, tool = await _registered(transport)

        assert (
            "The question shows the Microsoft Entra object id of each person in `mentions`. This "
            + "tool reads the members of the chat. The question and the message show the name "
            + "that Microsoft 365 gives each member. If a person in `mentions` is not a member of "
            + "the chat, this tool sends nothing."
        ) in " ".join((tool.description or "").split())

    async def test_the_arguments_are_chat_id_message_and_the_optional_rest(
        self, transport: httpx.AsyncClient
    ) -> None:
        parameters, _tool = await _registered(transport)

        properties = cast("Mapping[str, object]", parameters["properties"])
        assert set(properties) == {"chat_id", "message", "mentions", "importance", "subject"}
        assert set(cast("Sequence[str]", parameters["required"])) == {"chat_id", "message"}

    async def test_the_subject_is_never_empty_and_has_no_ceiling(
        self, transport: httpx.AsyncClient
    ) -> None:
        subject = (await _listed(transport))["subject"]

        options = cast("Sequence[Mapping[str, object]]", subject["anyOf"])
        assert [option.get("type") for option in options] == ["string", "null"]
        assert options[0]["minLength"] == 1
        assert "maxLength" not in options[0], "Microsoft documents no subject limit for a chat"

    async def test_an_empty_subject_never_reaches_this_tool(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        _parameters, tool = await _registered(transport)

        with pytest.raises(ValidationError, match="subject"):
            _ = await tool.run({**sender.GRAPH_CALL_EXAMPLE, "subject": ""})

        assert len(graph.calls) == 0, "a subject the schema refuses reached Graph"

    async def test_the_importance_is_normal_high_or_urgent_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        importance = (await _listed(transport))["importance"]

        options = cast("Sequence[Mapping[str, object]]", importance["anyOf"])
        assert [option.get("enum") for option in options] == [["normal", "high", "urgent"], None]

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
