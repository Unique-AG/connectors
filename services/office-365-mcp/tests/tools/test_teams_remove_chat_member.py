from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.elicitation import AcceptedElicitation, DeclinedElicitation
from fastmcp.tools import FunctionTool
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
    GraphFailure,
    GraphForbidden,
    GraphNotFound,
    GraphUnavailable,
)
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE, Confirmed
from office_365_mcp.tools import teams_remove_chat_member as remover
from office_365_mcp.tools.teams_remove_chat_member import (
    RemovedChatMember,
    a_person_agrees,
    remove_chat_member,
)

from .conftest import OTHER_USER_ID, SIGNED_IN_USER_ID

_CHAT_ID = "19:release@thread.v2"
_OTHER_CHAT_ID = "19:pricing@thread.v2"
_MEMBERSHIP_ID = cast("str", remover.GRAPH_CALL_EXAMPLE["membership_id"])
_OTHER_MEMBERSHIP_ID = "MCMjU1lOVEhFVElDMSMj"

_CHAT_PATH = "/chats/19%3Arelease%40thread.v2"
_MEMBERS_PATH = f"{_CHAT_PATH}/members"
_MEMBER_PATH = f"{_MEMBERS_PATH}/{_MEMBERSHIP_ID.replace('=', '%3D')}"
_OTHER_MEMBER_PATH = f"{_MEMBERS_PATH}/{_OTHER_MEMBERSHIP_ID}"

_TOPIC = "Release planning"

_NOTHING_REMOVED = "Nobody was removed."
_EVERYONE_SEES_IT = "Everyone in the conversation can see this change."

_ADA: Mapping[str, object] = {
    "@odata.type": "#microsoft.graph.aadUserConversationMember",
    "id": _MEMBERSHIP_ID,
    "displayName": "Ada Lovelace",
    "email": "ada@example.invalid",
    "userId": OTHER_USER_ID,
    "roles": ["owner"],
}

_GRACE: Mapping[str, object] = {
    **_ADA,
    "id": "MCMjU1lOVEhFVElDMiMj",
    "displayName": "Grace Hopper",
    "email": "grace@example.invalid",
    "userId": SIGNED_IN_USER_ID,
}
_JANE: Mapping[str, object] = {
    **_ADA,
    "id": _OTHER_MEMBERSHIP_ID,
    "displayName": "Jane Doe",
    "email": "jane@example.invalid",
    "userId": "00000000-0000-4000-8000-000000000003",
}

_NOT_FOUND = {"error": {"code": "NotFound", "message": "Not Found"}}


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_REMOVED


def _reads(
    graph: respx.MockRouter, member: Mapping[str, object] = _ADA, path: str = _MEMBER_PATH
) -> respx.Route:
    return graph.get(path).mock(return_value=httpx.Response(200, json=dict(member)))


def _names_the_chat(graph: respx.MockRouter, topic: str | None = _TOPIC) -> respx.Route:
    return graph.get(_CHAT_PATH).mock(
        return_value=httpx.Response(200, json={"id": _CHAT_ID, "topic": topic, "chatType": "group"})
    )


def _lists_members(graph: respx.MockRouter, *members: Mapping[str, object]) -> respx.Route:
    return graph.get(_MEMBERS_PATH).mock(
        return_value=httpx.Response(200, json={"value": [dict(member) for member in members]})
    )


def _removes(graph: respx.MockRouter) -> respx.Route:
    _ = _reads(graph)
    _ = _names_the_chat(graph)
    return graph.delete(_MEMBER_PATH).mock(return_value=httpx.Response(204))


def _deletes(graph: respx.MockRouter) -> list[Call]:
    made = cast("Sequence[Call]", graph.calls)
    return [call for call in made if call.request.method == "DELETE"]


async def _asked(client: GraphServiceClient) -> list[str]:
    asked: list[str] = []

    async def capturing(question: str, _about: str) -> Confirmed:
        asked.append(question)
        return None

    _ = await remove_chat_member(
        client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=capturing
    )
    return asked


class _ModernRequest:
    protocol_version: str = LATEST_MODERN_VERSION


class _Session:
    def __init__(
        self,
        *,
        modern: bool = True,
        answers: Mapping[str, InputResponse] | None = None,
        state: str | None = None,
        elicited: object = None,
    ) -> None:
        self.request_context: _ModernRequest | None = _ModernRequest() if modern else None
        self.input_responses: Mapping[str, InputResponse] | None = answers
        self.request_state: str | None = state
        self.asked: list[str] = []
        self._elicited: object = elicited

    async def elicit(self, message: str, response_type: object = None) -> object:
        assert response_type is not None
        self.asked.append(message)
        if self._elicited is None:
            raise AssertionError(f"a connection with no back-channel was asked {message!r}")
        return self._elicited

    @property
    def context(self) -> Context:
        return cast("Context", cast("object", self))


def _the_question(answer: object) -> tuple[str, str, str, str]:
    assert isinstance(answer, InputRequiredResult), "the question was never put to anybody"
    requests = answer.input_requests or {}
    assert len(requests) == 1, f"one question per call, and this one asked {sorted(requests)}"
    key = next(iter(requests))
    request = requests[key]
    assert isinstance(request, ElicitRequest)
    params = request.params
    assert isinstance(params, ElicitRequestFormParams)
    schema = cast("Mapping[str, object]", params.requested_schema)
    properties = cast("Mapping[str, object]", schema["properties"])
    choices = cast("Sequence[str]", cast("Mapping[str, object]", properties["value"])["enum"])
    assert answer.request_state
    return key, answer.request_state, choices[0], params.message


async def _registered(transport: httpx.AsyncClient) -> FunctionTool:
    mcp: FastMCP = FastMCP(name="schema-under-test")
    remover.register(mcp, transport)
    tool = await mcp.get_tool(remover.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    assert isinstance(tool, FunctionTool)
    return tool


class TestWhatItSendsToGraph:
    async def test_it_reads_the_membership_and_the_chat_and_then_deletes_it_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _removes(graph)

        _ = await remove_chat_member(
            client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=_agrees
        )

        made = cast("Sequence[Call]", graph.calls)
        chat = f"/v1.0/chats/{_CHAT_ID}"
        member = f"{chat}/members/{_MEMBERSHIP_ID}"
        assert [(call.request.method, call.request.url.path) for call in made] == [
            ("GET", member),
            ("GET", chat),
            ("DELETE", member),
        ]
        assert route.call_count == 1
        assert route.calls.last.request.content == b""

    async def test_a_membership_graph_does_not_find_is_refused_before_the_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_MEMBER_PATH).mock(return_value=httpx.Response(404, json=_NOT_FOUND))
        route = graph.delete(_MEMBER_PATH).mock(return_value=httpx.Response(204))
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        with pytest.raises(ToolError) as refused:
            _ = await remove_chat_member(
                client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=capturing
            )

        assert str(refused.value) == (
            "Microsoft 365 has no member with this `membership_id` in this chat. Nobody was "
            + "removed. Call teams_list_chat_members to see the current members of the chat. "
            + "Copy the `membership_id` from that list. If you call this tool again with the "
            + "same arguments, the call will fail the same way."
        )
        assert refused.value.__cause__ is None, "the advice of the server would replace it"
        assert asked == [], "a member that Graph does not find was put to the person"
        assert route.call_count == 0
        assert [call.request.method for call in cast("Sequence[Call]", graph.calls)] == ["GET"]


class TestThePersonBeforeTheChange:
    async def test_a_refusal_removes_nobody(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _removes(graph)

        with pytest.raises(ToolError, match=_NOTHING_REMOVED):
            _ = await remove_chat_member(
                client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=_refuses
            )

        assert route.call_count == 0
        assert _deletes(graph) == []

    async def test_a_decline_removes_nobody(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _removes(graph)
        session = _Session(modern=False, elicited=DeclinedElicitation())

        with pytest.raises(ToolError, match=_NOTHING_REMOVED):
            _ = await remove_chat_member(
                client,
                chat_id=_CHAT_ID,
                membership_id=_MEMBERSHIP_ID,
                confirm=a_person_agrees(session.context),
            )

        assert len(session.asked) == 1
        assert route.call_count == 0

    async def test_agreeing_over_the_back_channel_removes_the_member(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _removes(graph)
        session = _Session(modern=False, elicited=AcceptedElicitation(data="remove"))

        _ = await remove_chat_member(
            client,
            chat_id=_CHAT_ID,
            membership_id=_MEMBERSHIP_ID,
            confirm=a_person_agrees(session.context),
        )

        assert route.call_count == 1

    async def test_the_question_happens_before_the_delete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _removes(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await remove_chat_member(
            client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=watching
        )

        assert calls_when_asked == [2], "asked before the member and the chat were read"
        assert route.call_count == 1

    @pytest.mark.parametrize(
        ("member", "named"),
        [
            pytest.param(_ADA, "'Ada Lovelace' (ada@example.invalid)", id="name-and-email"),
            pytest.param({**_ADA, "email": None}, "'Ada Lovelace'", id="name-only"),
            pytest.param({**_ADA, "displayName": None}, "ada@example.invalid", id="email-only"),
            pytest.param(
                {**_ADA, "displayName": None, "email": None}, "a member with no name", id="neither"
            ),
            pytest.param(
                {
                    "@odata.type": "#microsoft.graph.anonymousGuestConversationMember",
                    "id": _MEMBERSHIP_ID,
                    "displayName": "Guest 1",
                },
                "'Guest 1'",
                id="anonymous-guest",
            ),
        ],
    )
    async def test_the_question_names_the_member_and_who_sees_it(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        member: Mapping[str, object],
        named: str,
    ) -> None:
        _ = _removes(graph)
        _ = _reads(graph, member)

        asked = await _asked(client)

        assert asked == [
            f"Remove {named} from the Teams chat 'Release planning'? {_EVERYONE_SEES_IT}"
        ]

    @pytest.mark.parametrize("topic", [None, "", "   "], ids=["null", "empty", "blank"])
    async def test_a_chat_with_no_topic_is_named_by_the_members_that_stay(
        self, client: GraphServiceClient, graph: respx.MockRouter, topic: str | None
    ) -> None:
        _ = _removes(graph)
        _ = _names_the_chat(graph, topic)
        _ = _lists_members(graph, _GRACE, _ADA, _JANE)

        asked = await _asked(client)

        assert asked == [
            "Remove 'Ada Lovelace' (ada@example.invalid) from the Teams chat with "
            + f"'Grace Hopper, Jane Doe'? {_EVERYONE_SEES_IT}"
        ]

    async def test_a_long_topic_is_cut(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _removes(graph)
        _ = _names_the_chat(graph, "R" * 200)

        (question,) = await _asked(client)

        assert question == (
            f"Remove 'Ada Lovelace' (ada@example.invalid) from the Teams chat {'R' * 120 + '…'!r}? "
            + _EVERYONE_SEES_IT
        )

    @pytest.mark.parametrize("topic", [_TOPIC, None], ids=["topic", "no-topic"])
    async def test_the_question_shows_no_membership_id_and_no_user_id(
        self, client: GraphServiceClient, graph: respx.MockRouter, topic: str | None
    ) -> None:
        _ = _removes(graph)
        _ = _names_the_chat(graph, topic)
        _ = _lists_members(graph, _GRACE, _ADA, _JANE)

        (question,) = await _asked(client)

        assert _MEMBERSHIP_ID not in question
        assert _OTHER_MEMBERSHIP_ID not in question
        assert OTHER_USER_ID not in question
        assert SIGNED_IN_USER_ID not in question
        assert _CHAT_ID not in question

    async def test_the_question_cuts_a_long_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _removes(graph)
        _ = _reads(graph, {**_ADA, "displayName": "A" * 200, "email": None})

        (question,) = await _asked(client)

        assert question == (
            f"Remove {'A' * 120 + '…'!r} from the Teams chat 'Release planning'? "
            + _EVERYONE_SEES_IT
        )

    @pytest.mark.parametrize(
        ("status", "failure"),
        [(404, GraphNotFound), (403, GraphForbidden)],
        ids=["not-found", "forbidden"],
    )
    async def test_a_chat_read_that_fails_asks_nothing_and_removes_nobody(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        status: int,
        failure: type[GraphFailure],
    ) -> None:
        route = _removes(graph)
        _ = graph.get(_CHAT_PATH).mock(
            return_value=httpx.Response(status, json={"error": {"code": "x", "message": "x"}})
        )
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        with pytest.raises(failure):
            _ = await remove_chat_member(
                client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=capturing
            )

        assert asked == []
        assert route.call_count == 0
        assert _deletes(graph) == []

    def test_the_binding_differs_for_another_membership_and_another_chat(self) -> None:
        about = remover._about  # pyright: ignore[reportPrivateUsage]

        bound = about(_CHAT_ID, _MEMBERSHIP_ID)

        assert bound != about(_CHAT_ID, _OTHER_MEMBERSHIP_ID)
        assert bound != about(_OTHER_CHAT_ID, _MEMBERSHIP_ID)


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_deletes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _removes(graph)

        answer = await remove_chat_member(
            client,
            chat_id=_CHAT_ID,
            membership_id=_MEMBERSHIP_ID,
            confirm=a_person_agrees(_Session().context),
        )

        _key, _state, agrees_with, question = _the_question(answer)
        assert agrees_with == "remove"
        assert "'Ada Lovelace' (ada@example.invalid) from the Teams chat 'Release planning'" in (
            question
        )
        assert _MEMBERSHIP_ID not in question
        assert route.call_count == 0, "an unanswered question removed the member anyway"

    async def test_the_second_round_deletes_the_membership_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _removes(graph)
        key, state, agrees_with, _question = _the_question(
            await remove_chat_member(
                client,
                chat_id=_CHAT_ID,
                membership_id=_MEMBERSHIP_ID,
                confirm=a_person_agrees(_Session().context),
            )
        )

        answer = await remove_chat_member(
            client,
            chat_id=_CHAT_ID,
            membership_id=_MEMBERSHIP_ID,
            confirm=a_person_agrees(
                _Session(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                ).context
            ),
        )

        assert route.call_count == 1, "the agreed removal did not happen exactly once"
        assert len(_deletes(graph)) == 1
        assert answer == RemovedChatMember(chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID)

    async def test_an_answer_bound_to_another_membership_removes_nobody(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _removes(graph)
        _ = _reads(graph, {**_ADA, "id": _OTHER_MEMBERSHIP_ID}, _OTHER_MEMBER_PATH)
        other = graph.delete(_OTHER_MEMBER_PATH).mock(return_value=httpx.Response(204))
        key, state, agrees_with, _question = _the_question(
            await remove_chat_member(
                client,
                chat_id=_CHAT_ID,
                membership_id=_MEMBERSHIP_ID,
                confirm=a_person_agrees(_Session().context),
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await remove_chat_member(
                client,
                chat_id=_CHAT_ID,
                membership_id=_OTHER_MEMBERSHIP_ID,
                confirm=a_person_agrees(
                    _Session(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    ).context
                ),
            )

        assert route.call_count == 0
        assert other.call_count == 0, "a member was removed under an answer nobody gave for it"


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_delete_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _names_the_chat(graph)
        route = graph.delete(_MEMBER_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await remove_chat_member(
                client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=_agrees
            )

        assert route.call_count == 1


class TestWhatItAnswers:
    async def test_a_no_content_answer_repeats_the_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _removes(graph)

        answer = await remove_chat_member(
            client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=_agrees
        )

        assert answer == RemovedChatMember(chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID)


class TestTheFailuresItPassesOn:
    async def test_a_refused_removal_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _names_the_chat(graph)
        _ = graph.delete(_MEMBER_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await remove_chat_member(
                client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=_agrees
            )

    async def test_a_refused_read_is_a_forbidden_and_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get(_MEMBER_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )
        route = graph.delete(_MEMBER_PATH).mock(return_value=httpx.Response(204))

        with pytest.raises(GraphForbidden):
            _ = await remove_chat_member(
                client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=_agrees
            )

        assert route.call_count == 0

    async def test_a_membership_gone_between_the_read_and_the_delete_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = _names_the_chat(graph)
        _ = graph.delete(_MEMBER_PATH).mock(return_value=httpx.Response(404, json=_NOT_FOUND))

        with pytest.raises(GraphNotFound):
            _ = await remove_chat_member(
                client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=_agrees
            )

    async def test_a_removal_graph_rejects_passes_on_graphs_reason(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reason = "Cannot remove members from a oneOnOne chat."
        _ = _reads(graph)
        _ = _names_the_chat(graph)
        _ = graph.delete(_MEMBER_PATH).mock(
            return_value=httpx.Response(
                400, json={"error": {"code": "BadRequest", "message": reason}}
            )
        )

        with pytest.raises(GraphFailure) as rejected:
            _ = await remove_chat_member(
                client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=_agrees
            )

        assert rejected.value.status == 400
        assert rejected.value.reason == reason


class TestHowItDeclaresItself:
    def test_the_permissions_are_chat_member_read_write_and_chat_read(self) -> None:
        assert remover.GRAPH_PERMISSIONS == ("ChatMember.ReadWrite", "Chat.Read")

    def test_its_own_steps_are_the_read_and_the_delete(self) -> None:
        assert remover.STEP_READ == "chat_member"
        assert remover.STEP == "remove_chat_member"

    def test_teams_list_chat_members_shows_the_change(self) -> None:
        assert remover.CHANGE_SHOWN_BY == ("teams_list_chat_members",)

    async def test_it_announces_itself_as_a_destructive_write_that_is_not_idempotent(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE["idempotentHint"]
        assert annotations.open_world_hint is WRITE_DESTRUCTIVE["openWorldHint"]

    async def test_the_description_says_it_asks_every_time_how_to_retry_and_who_sees_it(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert (
            "This tool asks the user to agree before it removes a member, every time. This tool "
            + "removes nobody unless the user agrees."
        ) in description
        assert (
            "If a call times out, do not call this tool again first. Before you call again, make "
            + "sure that teams_list_chat_members still shows the member."
        ) in description
        assert "Everyone in the conversation can see the change." in description

    async def test_the_description_names_the_fixed_chat_and_the_limit_of_teams(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert "keeps the members of a `oneOnOne` chat fixed" in description
        assert "at most 4 removals a minute from one chat" in description

    async def test_the_arguments_are_chat_id_and_membership_id_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert set(properties) == {"chat_id", "membership_id"}
        assert set(cast("Sequence[str]", tool.parameters["required"])) == {
            "chat_id",
            "membership_id",
        }
        assert set(remover.GRAPH_CALL_EXAMPLE) == set(properties)

    async def test_the_membership_id_says_where_it_comes_from_and_what_it_is_not(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
        described = cast("str", properties["membership_id"]["description"])
        assert "teams_list_chat_members" in described
        assert "It is not the member's `user_id`." in described
