import json
from collections.abc import Mapping, Sequence
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

from office_365_mcp.graph_client import GraphForbidden, GraphThrottled, GraphUnavailable
from office_365_mcp.shared import identity
from office_365_mcp.shared.identity import Person
from office_365_mcp.shared.messages import CHAT_TOPIC_MAX_CHARACTERS
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirmed
from office_365_mcp.tools import teams_create_chat as creator
from office_365_mcp.tools.teams_create_chat import NewChatKind, a_person_agrees, create_chat

from .conftest import ME, OTHER_USER_ID, SIGNED_IN_USER_ID

_THIRD_USER_ID = "00000000-0000-4000-8000-000000000003"
_LETTERED_USER_ID = "abcdef00-0000-4000-8000-00000000000a"

_GRACE = Person(user_id=OTHER_USER_ID, name="Grace Hopper")
_BOB = Person(user_id=_THIRD_USER_ID, name="Bob Kelso")
_ME = Person(user_id=SIGNED_IN_USER_ID, name="Ada Lovelace")
_GRACE_ARGUMENT: Mapping[str, object] = _GRACE.model_dump()

_CREATED_CHAT_ID = "19:3f1a2b@thread.v2"

_NOTHING_CREATED = "No chat was created."


def _bind(user_id: str) -> str:
    return f"https://graph.microsoft.com/v1.0/users('{user_id}')"


def _shown(user_id: str, name: str) -> str:
    return (
        f"the person with the Microsoft Entra object id '{user_id}' "
        + f"(the name '{name}' is only a label from the request)"
    )


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_CREATED


def _chat_payload(
    *,
    chat_type: str = "oneOnOne",
    topic: str | None = None,
    created_at: str = "2026-10-01T09:30:00Z",
) -> Mapping[str, object]:
    return {
        "id": _CREATED_CHAT_ID,
        "topic": topic,
        "createdDateTime": created_at,
        "lastUpdatedDateTime": created_at,
        "chatType": chat_type,
    }


async def _binding(
    client: GraphServiceClient,
    chat_type: NewChatKind,
    members: Sequence[Person],
    topic: str | None = None,
) -> str:
    seen: list[str] = []

    async def capturing(question: str, about: str) -> Confirmed:
        assert question
        seen.append(about)
        return None

    _ = await create_chat(
        client, chat_type=chat_type, members=members, topic=topic, confirm=capturing
    )
    return seen[0]


def _signed_in(graph: respx.MockRouter) -> respx.Route:
    return graph.get("/me").mock(return_value=httpx.Response(200, json=ME))


def _creates(graph: respx.MockRouter, payload: Mapping[str, object] | None = None) -> respx.Route:
    _ = _signed_in(graph)
    return graph.post("/chats").mock(
        return_value=httpx.Response(201, json=payload if payload is not None else _chat_payload())
    )


def _sent(post: respx.Route) -> Mapping[str, object]:
    return cast("Mapping[str, object]", json.loads(post.calls.last.request.content))


def _members_sent(post: respx.Route) -> Sequence[Mapping[str, object]]:
    return cast("Sequence[Mapping[str, object]]", _sent(post)["members"])


async def _registered(transport: httpx.AsyncClient) -> Tool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    creator.register(mcp, transport)
    tool = await mcp.get_tool(creator.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    return tool


async def _listed(transport: httpx.AsyncClient) -> Mapping[str, Mapping[str, object]]:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    creator.register(mcp, transport)
    (tool,) = await mcp.list_tools()
    return cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])


class TestWhatItAsksGraphFor:
    async def test_it_reads_the_signed_in_user_and_then_posts_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph)

        _ = await create_chat(client, chat_type="oneOnOne", members=[_GRACE], confirm=_agrees)

        made = cast("Sequence[Call]", graph.calls)
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", "/v1.0/me"),
            ("POST", "/v1.0/chats"),
        ]
        assert post.call_count == 1

    async def test_the_body_binds_every_member_as_an_owner(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph, _chat_payload(chat_type="group", topic="Release"))

        _ = await create_chat(
            client,
            chat_type="group",
            members=[_GRACE, _BOB],
            topic="Release",
            confirm=_agrees,
        )

        body = _sent(post)
        assert body["chatType"] == "group"
        assert body["topic"] == "Release"
        assert _members_sent(post) == [
            {
                "@odata.type": "#microsoft.graph.aadUserConversationMember",
                "roles": ["owner"],
                "user@odata.bind": _bind(user_id),
            }
            for user_id in (SIGNED_IN_USER_ID, OTHER_USER_ID, _THIRD_USER_ID)
        ]
        assert "Grace Hopper" not in post.calls.last.request.content.decode()
        assert "Bob Kelso" not in post.calls.last.request.content.decode()

    async def test_the_bind_key_is_spelled_with_a_dot_and_not_an_underscore(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph)

        _ = await create_chat(client, chat_type="oneOnOne", members=[_GRACE], confirm=_agrees)

        raw = post.calls.last.request.content.decode()
        assert '"user@odata.bind"' in raw
        assert "user@odata_bind" not in raw

    async def test_a_one_to_one_chat_carries_no_topic(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph)

        _ = await create_chat(client, chat_type="oneOnOne", members=[_GRACE], confirm=_agrees)

        body = _sent(post)
        assert body["chatType"] == "oneOnOne"
        assert "topic" not in body, "a one-to-one chat went out with a topic or a null topic"

    @pytest.mark.parametrize(
        "members",
        [
            [_GRACE, _ME],
            [Person(user_id=SIGNED_IN_USER_ID.upper(), name="Ada"), _GRACE, _ME],
        ],
    )
    async def test_the_signed_in_user_is_bound_exactly_once(
        self, client: GraphServiceClient, graph: respx.MockRouter, members: list[Person]
    ) -> None:
        post = _creates(graph, _chat_payload(chat_type="group"))

        _ = await create_chat(client, chat_type="group", members=members, confirm=_agrees)

        bound = [member["user@odata.bind"] for member in _members_sent(post)]
        assert bound == [_bind(SIGNED_IN_USER_ID), _bind(OTHER_USER_ID)]

    async def test_a_repeated_member_is_bound_once(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph, _chat_payload(chat_type="group"))

        _ = await create_chat(
            client,
            chat_type="group",
            members=[_GRACE, _BOB, Person(user_id=OTHER_USER_ID.upper(), name="Grace"), _BOB],
            confirm=_agrees,
        )

        bound = [member["user@odata.bind"] for member in _members_sent(post)]
        assert bound == [_bind(SIGNED_IN_USER_ID), _bind(OTHER_USER_ID), _bind(_THIRD_USER_ID)]

    async def test_an_id_that_differs_only_in_case_is_bound_once_and_keeps_the_first_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph, _chat_payload(chat_type="group"))
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await create_chat(
            client,
            chat_type="group",
            members=[
                Person(user_id=_LETTERED_USER_ID.upper(), name="Grace Hopper"),
                Person(user_id=_LETTERED_USER_ID, name="Grace"),
            ],
            confirm=capturing,
        )

        bound = [member["user@odata.bind"] for member in _members_sent(post)]
        assert bound == [_bind(SIGNED_IN_USER_ID), _bind(_LETTERED_USER_ID)]
        shown = _shown(_LETTERED_USER_ID, "Grace Hopper")
        assert asked == [f"Create a group Teams chat with 1 person: {shown}?"]


class TestTheRefusalsBeforeAnyRequest:
    @pytest.mark.parametrize(
        "members",
        [
            [_GRACE, _BOB],
            [_GRACE, _ME],
        ],
    )
    async def test_a_one_to_one_chat_with_more_than_one_person_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter, members: list[Person]
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match="exactly one other person"):
            _ = await create_chat(client, chat_type="oneOnOne", members=members, confirm=_agrees)

        assert len(graph.calls) == 0, "a refused one-to-one chat still reached Graph"

    async def test_a_one_to_one_chat_with_a_topic_is_refused(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match="only on a group chat"):
            _ = await create_chat(
                client,
                chat_type="oneOnOne",
                members=[_GRACE],
                topic="Release",
                confirm=_agrees,
            )

        assert len(graph.calls) == 0, "a one-to-one chat with a topic still reached Graph"

    async def test_the_refusal_says_no_chat_was_created(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        with pytest.raises(ToolError, match=_NOTHING_CREATED):
            _ = await create_chat(
                client,
                chat_type="oneOnOne",
                members=[_GRACE, _BOB],
                confirm=_agrees,
            )

    @pytest.mark.parametrize("chat_type", ["oneOnOne", "group"])
    async def test_only_the_signed_in_user_is_refused_before_anybody_is_asked(
        self, client: GraphServiceClient, graph: respx.MockRouter, chat_type: NewChatKind
    ) -> None:
        post = _creates(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        with pytest.raises(ToolError, match="only the signed-in user"):
            _ = await create_chat(client, chat_type=chat_type, members=[_ME], confirm=capturing)

        assert asked == [], "a chat with nobody else was put to the person"
        assert post.call_count == 0


class TestTheSchemaRefusals:
    @pytest.mark.parametrize(
        ("arguments", "match"),
        [
            ({"chat_type": "group", "members": [_GRACE_ARGUMENT], "topic": "Q3: plan"}, "pattern"),
            ({"chat_type": "group", "members": [_GRACE_ARGUMENT], "topic": "x" * 251}, "at most"),
            ({"chat_type": "group", "members": [_GRACE_ARGUMENT], "topic": ""}, "at least"),
            (
                {
                    "chat_type": "group",
                    "members": [{"user_id": "jane@example.invalid", "name": "Jane"}],
                },
                "pattern",
            ),
            (
                {"chat_type": "group", "members": [{"user_id": OTHER_USER_ID, "name": ""}]},
                "at least",
            ),
            ({"chat_type": "group", "members": [OTHER_USER_ID]}, "valid dictionary"),
            ({"chat_type": "group", "members": []}, "at least"),
            ({"chat_type": "meeting", "members": [_GRACE_ARGUMENT]}, "oneOnOne"),
        ],
    )
    async def test_a_value_the_schema_refuses_never_reaches_graph(
        self,
        transport: httpx.AsyncClient,
        graph: respx.MockRouter,
        arguments: Mapping[str, object],
        match: str,
    ) -> None:
        tool = await _registered(transport)

        with pytest.raises(ValidationError, match=match):
            _ = await tool.run(dict(arguments))

        assert len(graph.calls) == 0, "a value the schema refuses reached Graph"

    async def test_the_topic_is_at_most_250_characters(self, transport: httpx.AsyncClient) -> None:
        topic = (await _listed(transport))["topic"]

        options = cast("Sequence[Mapping[str, object]]", topic["anyOf"])
        assert options[0]["maxLength"] == CHAT_TOPIC_MAX_CHARACTERS == 250


class TestThePersonBeforeTheCreate:
    async def test_a_refusal_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph)

        with pytest.raises(ToolError, match=_NOTHING_CREATED):
            _ = await create_chat(client, chat_type="oneOnOne", members=[_GRACE], confirm=_refuses)

        assert post.call_count == 0, "a declined create still reached Graph"

    async def test_the_question_names_the_members_and_the_topic(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _chat_payload(chat_type="group", topic="Release"))
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await create_chat(
            client,
            chat_type="group",
            members=[_GRACE, _BOB],
            topic="Release",
            confirm=capturing,
        )

        assert asked == [
            "Create a group Teams chat named 'Release' with 2 people: "
            + f"{_shown(OTHER_USER_ID, 'Grace Hopper')}, {_shown(_THIRD_USER_ID, 'Bob Kelso')}?"
        ]
        assert SIGNED_IN_USER_ID not in asked[0]

    async def test_a_name_that_does_not_match_its_id_still_shows_the_id_in_a_group_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph, _chat_payload(chat_type="group"))
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await create_chat(
            client,
            chat_type="group",
            members=[Person(user_id=OTHER_USER_ID, name=_BOB.name)],
            confirm=capturing,
        )

        assert asked == [
            f"Create a group Teams chat with 1 person: {_shown(OTHER_USER_ID, 'Bob Kelso')}?"
        ]
        assert _THIRD_USER_ID not in asked[0]
        assert _bind(OTHER_USER_ID) in {member["user@odata.bind"] for member in _members_sent(post)}

    async def test_the_question_for_a_one_to_one_chat_names_the_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await create_chat(client, chat_type="oneOnOne", members=[_GRACE], confirm=capturing)

        assert asked == [
            f"Create a one-to-one Teams chat with {_shown(OTHER_USER_ID, 'Grace Hopper')}?"
        ]

    async def test_a_one_to_one_name_that_does_not_match_its_id_still_shows_the_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await create_chat(
            client,
            chat_type="oneOnOne",
            members=[Person(user_id=OTHER_USER_ID, name=_BOB.name)],
            confirm=capturing,
        )

        assert asked == [
            f"Create a one-to-one Teams chat with {_shown(OTHER_USER_ID, 'Bob Kelso')}?"
        ]
        assert _THIRD_USER_ID not in asked[0]
        assert [member["user@odata.bind"] for member in _members_sent(post)] == [
            _bind(SIGNED_IN_USER_ID),
            _bind(OTHER_USER_ID),
        ]

    async def test_a_long_name_is_cut_and_the_object_id_is_kept(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await create_chat(
            client,
            chat_type="oneOnOne",
            members=[Person(user_id=OTHER_USER_ID, name="G" * 200)],
            confirm=capturing,
        )

        shown = _shown(OTHER_USER_ID, "G" * 120 + "…")
        assert asked == [f"Create a one-to-one Teams chat with {shown}?"]

    async def test_the_question_leaves_out_the_signed_in_user(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _chat_payload(chat_type="group"))
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await create_chat(
            client,
            chat_type="group",
            members=[_ME, _GRACE],
            confirm=capturing,
        )

        assert asked == [
            f"Create a group Teams chat with 1 person: {_shown(OTHER_USER_ID, 'Grace Hopper')}?"
        ]
        assert SIGNED_IN_USER_ID not in asked[0]
        assert "Ada Lovelace" not in asked[0]

    async def test_the_confirmation_happens_before_the_post(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await create_chat(client, chat_type="oneOnOne", members=[_GRACE], confirm=watching)

        assert calls_when_asked == [1], "asked after the create already went out"
        assert post.call_count == 1

    async def test_the_binding_differs_when_only_the_chat_type_differs(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        first = await _binding(client, "oneOnOne", [_GRACE])
        second = await _binding(client, "group", [_GRACE])

        assert first != second

    async def test_the_binding_differs_when_only_the_members_differ(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        first = await _binding(client, "group", [_GRACE])
        second = await _binding(client, "group", [_BOB])

        assert first != second

    async def test_the_binding_differs_when_only_the_topic_differs(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        bindings = {
            await _binding(client, "group", [_GRACE], topic)
            for topic in (None, "Release", "Release plan")
        }

        assert len(bindings) == 3

    async def test_the_binding_ignores_the_order_of_the_members(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        first = await _binding(client, "group", [_GRACE, _BOB])
        second = await _binding(client, "group", [_BOB, _GRACE])

        assert first == second

    async def test_the_binding_covers_the_object_ids_and_never_the_names(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph)

        bound = await _binding(client, "group", [_GRACE, _BOB])

        renamed = [
            Person(user_id=OTHER_USER_ID, name="grace@example.invalid"),
            Person(user_id=_THIRD_USER_ID, name="Bob"),
        ]
        assert bound == await _binding(client, "group", renamed)
        swapped = [
            Person(user_id=OTHER_USER_ID, name=_BOB.name),
            Person(user_id=_THIRD_USER_ID, name=_GRACE.name),
        ]
        assert bound == await _binding(client, "group", swapped)
        elsewhere = [Person(user_id=_LETTERED_USER_ID, name=_GRACE.name), _BOB]
        assert bound != await _binding(client, "group", elsewhere)


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
        confirm = a_person_agrees(self._context(AcceptedElicitation(data="create")))

        assert await confirm("Create it?", "Create it?") is None

    async def test_declining_refuses_and_says_no_chat_was_created(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph)
        confirm = a_person_agrees(self._context(DeclinedElicitation()))

        with pytest.raises(ToolError, match=_NOTHING_CREATED):
            _ = await create_chat(client, chat_type="oneOnOne", members=[_GRACE], confirm=confirm)

        assert post.call_count == 0

    async def test_choosing_do_not_create_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph)
        confirm = a_person_agrees(self._context(AcceptedElicitation(data="do not create")))

        with pytest.raises(ToolError, match=_NOTHING_CREATED):
            _ = await create_chat(client, chat_type="oneOnOne", members=[_GRACE], confirm=confirm)

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
        post = _creates(graph)

        answer = await create_chat(
            client,
            chat_type="oneOnOne",
            members=[_GRACE],
            confirm=a_person_agrees(_modern_context()),
        )

        _key, _state, agrees_with = _the_question(answer)
        assert agrees_with == "create"
        assert post.call_count == 0, "an unanswered question created the chat anyway"

    async def test_the_second_round_creates_the_chat_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph, _chat_payload(chat_type="group", topic="Release"))
        key, state, agrees_with = _the_question(
            await create_chat(
                client,
                chat_type="group",
                members=[_GRACE, _BOB],
                topic="Release",
                confirm=a_person_agrees(_modern_context()),
            )
        )

        answer = await create_chat(
            client,
            chat_type="group",
            members=[_BOB, _GRACE],
            topic="Release",
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                )
            ),
        )

        assert post.call_count == 1, "the agreed create did not happen exactly once"
        assert not isinstance(answer, InputRequiredResult)

    async def test_an_answer_bound_to_other_members_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph, _chat_payload(chat_type="group"))
        key, state, agrees_with = _the_question(
            await create_chat(
                client,
                chat_type="group",
                members=[_GRACE],
                confirm=a_person_agrees(_modern_context()),
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await create_chat(
                client,
                chat_type="group",
                members=[_GRACE, _BOB],
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    )
                ),
            )

        assert post.call_count == 0, "a chat with a third person went out on an accept for two"

    async def test_an_answer_bound_to_another_topic_creates_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph, _chat_payload(chat_type="group"))
        key, state, agrees_with = _the_question(
            await create_chat(
                client,
                chat_type="group",
                members=[_GRACE],
                topic="Release",
                confirm=a_person_agrees(_modern_context()),
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await create_chat(
                client,
                chat_type="group",
                members=[_GRACE],
                topic="Layoffs",
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    )
                ),
            )

        assert post.call_count == 0, "a chat with another topic went out on an accept for Release"

    async def test_the_same_ids_under_other_names_still_create_the_chat_the_user_agreed_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph, _chat_payload(chat_type="group"))
        key, state, agrees_with = _the_question(
            await create_chat(
                client,
                chat_type="group",
                members=[_GRACE, _BOB],
                confirm=a_person_agrees(_modern_context()),
            )
        )

        _ = await create_chat(
            client,
            chat_type="group",
            members=[
                Person(user_id=OTHER_USER_ID, name="grace@example.invalid"),
                Person(user_id=_THIRD_USER_ID, name="Bob"),
            ],
            confirm=a_person_agrees(
                _modern_context(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                )
            ),
        )

        assert post.call_count == 1

    async def test_the_same_names_under_other_ids_create_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        post = _creates(graph, _chat_payload(chat_type="group"))
        key, state, agrees_with = _the_question(
            await create_chat(
                client,
                chat_type="group",
                members=[_GRACE],
                confirm=a_person_agrees(_modern_context()),
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await create_chat(
                client,
                chat_type="group",
                members=[Person(user_id=_THIRD_USER_ID, name=_GRACE.name)],
                confirm=a_person_agrees(
                    _modern_context(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    )
                ),
            )

        assert post.call_count == 0, "a chat with another person went out under the same name"


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_post_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _signed_in(graph)
        post = graph.post("/chats").mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await create_chat(client, chat_type="group", members=[_GRACE], confirm=_agrees)

        assert post.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_post_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _signed_in(graph)
        post = graph.post("/chats").mock(
            return_value=httpx.Response(429, headers={"Retry-After": "12"})
        )

        with pytest.raises(GraphThrottled):
            _ = await create_chat(client, chat_type="group", members=[_GRACE], confirm=_agrees)

        assert post.call_count == 1


class TestWhatItAnswers:
    async def test_the_answer_reports_the_chat_microsoft_stored(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _chat_payload(chat_type="group", topic="Release as stored"))

        answer = await create_chat(
            client,
            chat_type="group",
            members=[_GRACE],
            topic="Release",
            confirm=_agrees,
        )

        assert not isinstance(answer, InputRequiredResult)
        assert answer.chat_id == _CREATED_CHAT_ID
        assert answer.chat_type == "group"
        assert answer.topic == "Release as stored"
        assert answer.created_at is not None
        assert answer.created_at.isoformat() == "2026-10-01T09:30:00+00:00"

    async def test_an_existing_one_to_one_chat_comes_back_with_its_own_creation_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _creates(graph, _chat_payload(created_at="2024-02-01T08:00:00Z"))

        answer = await create_chat(client, chat_type="oneOnOne", members=[_GRACE], confirm=_agrees)

        assert not isinstance(answer, InputRequiredResult)
        assert answer.chat_type == "oneOnOne"
        assert answer.topic is None
        assert answer.created_at is not None
        assert answer.created_at.year == 2024


class TestTheFailuresItPassesOn:
    async def test_a_refused_post_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _signed_in(graph)
        _ = graph.post("/chats").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await create_chat(client, chat_type="oneOnOne", members=[_GRACE], confirm=_agrees)


class TestHowItDeclaresItself:
    def test_the_permissions_are_chat_create_and_user_read(self) -> None:
        assert creator.GRAPH_PERMISSIONS == ("Chat.Create", "User.Read")

    def test_its_steps_are_the_identity_read_and_the_create(self) -> None:
        assert identity.STEP == "signed_in_user"
        assert creator.STEP_CREATE == "create_chat"

    def test_teams_list_chats_shows_the_change(self) -> None:
        assert creator.CHANGE_SHOWN_BY == ("teams_list_chats",)

    async def test_it_announces_itself_as_an_addition_rather_than_a_destructive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]

    async def test_the_description_says_it_asks_before_creating(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert (
            "This tool asks the user to agree before it creates a chat, every time. This tool "
            + "creates nothing unless the user agrees."
        ) in " ".join((tool.description or "").split())

    async def test_the_description_says_the_question_shows_the_object_id_and_the_name_as_a_label(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert (
            "The question shows the Microsoft Entra object id of each person in `members`. The "
            + "`name` in the question is only a label."
        ) in " ".join((tool.description or "").split())

    async def test_the_description_says_an_existing_one_to_one_chat_comes_back(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        assert (
            "Only one one-to-one chat can exist between two people. If that chat exists already, "
            + "Microsoft returns it and creates no new chat."
        ) in " ".join((tool.description or "").split())

    async def test_the_description_names_no_tool_that_its_preset_leaves_out(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert "it posts no message. teams_list_chats shows the new chat." in description
        assert "teams_send_chat_message" not in description

    def test_the_answer_says_where_the_chat_id_goes_without_naming_a_tool_for_it(self) -> None:
        chat_id = str(creator.CreatedChat.model_fields["chat_id"].description)

        assert "Pass this id as `chat_id` to a tool that sends chat messages" in chat_id
        assert "teams_send_chat_message" not in chat_id

    async def test_the_description_says_how_to_retry(self, transport: httpx.AsyncClient) -> None:
        tool = await _registered(transport)

        assert (
            "If a call times out, do not call this tool again first. Before you call again, make "
            + "sure that teams_list_chats does not already show the chat."
        ) in " ".join((tool.description or "").split())

    async def test_the_arguments_are_chat_type_members_and_topic_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert set(properties) == {"chat_type", "members", "topic"}
        assert set(cast("Sequence[str]", tool.parameters["required"])) == {"chat_type", "members"}

    async def test_the_chat_type_is_one_on_one_or_group_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        chat_type = (await _listed(transport))["chat_type"]

        assert chat_type["enum"] == ["oneOnOne", "group"]

    async def test_every_member_is_a_guid_with_a_name(self, transport: httpx.AsyncClient) -> None:
        members = (await _listed(transport))["members"]

        assert members["minItems"] == 1
        items = cast("Mapping[str, object]", members["items"])
        properties = cast("Mapping[str, Mapping[str, object]]", items["properties"])
        assert properties["user_id"]["pattern"] == identity.ENTRA_OBJECT_ID_PATTERN
        assert properties["name"]["minLength"] == 1
        assert items["required"] == ["user_id", "name"]

    async def test_the_name_of_a_member_is_only_a_label_and_teams_binds_the_object_id(
        self, transport: httpx.AsyncClient
    ) -> None:
        members = (await _listed(transport))["members"]

        items = cast("Mapping[str, object]", members["items"])
        properties = cast("Mapping[str, Mapping[str, str]]", items["properties"])
        described = " ".join(properties["name"]["description"].split())
        assert "as a label only. Teams identifies the person only by `user_id`." in described
        assert "never sends it to Microsoft 365" in described

    async def test_the_members_say_the_owner_role_leaves_out_an_in_tenant_guest(
        self, transport: httpx.AsyncClient
    ) -> None:
        described = " ".join(str((await _listed(transport))["members"]["description"]).split())

        assert "Do not include the signed-in user" in described
        assert (
            "This tool adds every person as an owner, and Microsoft accepts no in-tenant guest as "
            + "an owner."
        ) in described
        assert 15 <= len(described.split()) <= 60
