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

_CHAT_ID = "19:release@thread.v2"
_OTHER_CHAT_ID = "19:pricing@thread.v2"
_MEMBERSHIP_ID = cast("str", remover.GRAPH_CALL_EXAMPLE["membership_id"])
_OTHER_MEMBERSHIP_ID = "MCMjU1lOVEhFVElDMSMj"

_MEMBER_PATH = f"/chats/19%3Arelease%40thread.v2/members/{_MEMBERSHIP_ID.replace('=', '%3D')}"

_NOTHING_REMOVED = "Nobody was removed."


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_REMOVED


def _removes(graph: respx.MockRouter) -> respx.Route:
    return graph.delete(_MEMBER_PATH).mock(return_value=httpx.Response(204))


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
    async def test_it_deletes_the_one_membership_of_the_chat_and_nothing_else(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _removes(graph)

        _ = await remove_chat_member(
            client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=_agrees
        )

        assert route.call_count == 1
        assert len(graph.calls) == 1, "one removal costs one Graph call, and nothing else"
        request = route.calls.last.request
        assert request.url.path == f"/v1.0/chats/{_CHAT_ID}/members/{_MEMBERSHIP_ID}"
        assert request.content == b""


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
        assert len(graph.calls) == 0

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

        assert calls_when_asked == [0], "asked after the member was already removed"
        assert route.call_count == 1

    async def test_the_question_names_the_membership_the_chat_and_who_sees_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _removes(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await remove_chat_member(
            client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=capturing
        )

        assert asked == [
            f"Remove the member with the membership id {_MEMBERSHIP_ID!r} from the Teams chat "
            + f"{_CHAT_ID!r}? Everyone in the conversation can see this change."
        ]

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
        assert _MEMBERSHIP_ID in question
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
        assert len(graph.calls) == 1
        assert answer == RemovedChatMember(chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID)

    async def test_an_answer_bound_to_another_membership_removes_nobody(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _removes(graph)
        other = graph.delete(
            f"/chats/19%3Arelease%40thread.v2/members/{_OTHER_MEMBERSHIP_ID}"
        ).mock(return_value=httpx.Response(204))
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
        _ = graph.delete(_MEMBER_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await remove_chat_member(
                client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=_agrees
            )

    async def test_a_membership_graph_does_not_find_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.delete(_MEMBER_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await remove_chat_member(
                client, chat_id=_CHAT_ID, membership_id=_MEMBERSHIP_ID, confirm=_agrees
            )

    async def test_a_removal_graph_rejects_passes_on_graphs_reason(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reason = "Cannot remove members from a oneOnOne chat."
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
    def test_the_permission_is_chat_member_read_write(self) -> None:
        assert remover.GRAPH_PERMISSIONS == ("ChatMember.ReadWrite",)

    def test_its_one_step_is_the_one_call_it_makes(self) -> None:
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
