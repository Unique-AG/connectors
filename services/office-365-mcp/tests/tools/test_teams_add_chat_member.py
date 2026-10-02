import json
from collections.abc import Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError, ValidationError
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
    GraphThrottled,
    GraphUnavailable,
)
from office_365_mcp.shared.identity import Person
from office_365_mcp.shared.seam import WRITE_ADDITIVE, Confirmed
from office_365_mcp.tools import teams_add_chat_member as adder
from office_365_mcp.tools.teams_add_chat_member import (
    AddedChatMember,
    a_person_agrees,
    add_chat_member,
)

from .conftest import OTHER_USER_ID

_CHAT_ID = "19:release@thread.v2"
_OTHER_CHAT_ID = "19:pricing@thread.v2"
_MEMBERS_PATH = "/chats/19%3Arelease%40thread.v2/members"
_LOCATION = f"/chats/{_CHAT_ID}/members/MCMjU1lOVEhFVElDMCMj"

_GRACE_ID = OTHER_USER_ID
_JANE_ID = "00000000-0000-4000-8000-000000000003"
_GRACE = Person(user_id=_GRACE_ID, name="Grace Hopper")
_JANE = Person(user_id=_JANE_ID, name="Jane Doe")

_NOTHING_ADDED = "Nobody was added."

_ALL_HISTORY = "0001-01-01T00:00:00Z"


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_ADDED


def _adds(graph: respx.MockRouter) -> respx.Route:
    return graph.post(_MEMBERS_PATH).mock(
        return_value=httpx.Response(201, headers={"Location": _LOCATION})
    )


def _body(route: respx.Route) -> Mapping[str, object]:
    return cast("Mapping[str, object]", json.loads(route.calls.last.request.content))


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
    adder.register(mcp, transport)
    tool = await mcp.get_tool(adder.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    assert isinstance(tool, FunctionTool)
    return tool


class TestWhatItSendsToGraph:
    async def test_it_posts_once_to_the_members_of_the_chat(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _adds(graph)

        _ = await add_chat_member(
            client, chat_id=_CHAT_ID, member=_GRACE, share_history=False, confirm=_agrees
        )

        assert route.call_count == 1
        assert len(graph.calls) == 1, "one addition costs one Graph call, and nothing else"

    async def test_the_body_binds_the_user_as_an_owner_and_shares_no_history_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _adds(graph)

        _ = await add_chat_member(
            client, chat_id=_CHAT_ID, member=_GRACE, share_history=False, confirm=_agrees
        )

        assert _body(route) == {
            "@odata.type": "#microsoft.graph.aadUserConversationMember",
            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{_GRACE_ID}')",
            "roles": ["owner"],
        }
        assert "Grace Hopper" not in route.calls.last.request.content.decode()

    async def test_sharing_history_sends_the_all_history_value_of_the_documentation(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _adds(graph)

        _ = await add_chat_member(
            client, chat_id=_CHAT_ID, member=_GRACE, share_history=True, confirm=_agrees
        )

        assert _body(route) == {
            "@odata.type": "#microsoft.graph.aadUserConversationMember",
            "user@odata.bind": f"https://graph.microsoft.com/v1.0/users('{_GRACE_ID}')",
            "roles": ["owner"],
            "visibleHistoryStartDateTime": _ALL_HISTORY,
        }


class TestThePersonBeforeTheChange:
    async def test_a_refusal_adds_nobody(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _adds(graph)

        with pytest.raises(ToolError, match=_NOTHING_ADDED):
            _ = await add_chat_member(
                client, chat_id=_CHAT_ID, member=_GRACE, share_history=False, confirm=_refuses
            )

        assert route.call_count == 0
        assert len(graph.calls) == 0

    async def test_a_decline_adds_nobody(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _adds(graph)
        session = _Session(modern=False, elicited=DeclinedElicitation())

        with pytest.raises(ToolError, match=_NOTHING_ADDED):
            _ = await add_chat_member(
                client,
                chat_id=_CHAT_ID,
                member=_GRACE,
                share_history=False,
                confirm=a_person_agrees(session.context),
            )

        assert len(session.asked) == 1
        assert route.call_count == 0

    async def test_agreeing_over_the_back_channel_adds_the_member(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _adds(graph)
        session = _Session(modern=False, elicited=AcceptedElicitation(data="add"))

        _ = await add_chat_member(
            client,
            chat_id=_CHAT_ID,
            member=_GRACE,
            share_history=False,
            confirm=a_person_agrees(session.context),
        )

        assert route.call_count == 1

    async def test_the_question_happens_before_the_post(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _adds(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await add_chat_member(
            client, chat_id=_CHAT_ID, member=_GRACE, share_history=False, confirm=watching
        )

        assert calls_when_asked == [0], "asked after the member was already added"
        assert route.call_count == 1

    @pytest.mark.parametrize(
        ("share_history", "history"),
        [
            (False, "The new member will not see the earlier messages of the chat."),
            (True, "The new member will see all earlier messages of the chat."),
        ],
    )
    async def test_the_question_names_the_person_the_history_and_who_sees_it(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        share_history: bool,
        history: str,
    ) -> None:
        _ = _adds(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await add_chat_member(
            client,
            chat_id=_CHAT_ID,
            member=_GRACE,
            share_history=share_history,
            confirm=capturing,
        )

        assert asked == [
            f"Add 'Grace Hopper' to the Teams chat? {history} "
            + "Everyone in the conversation can see this change."
        ]

    async def test_the_question_shows_no_user_id_and_no_chat_id(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _adds(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await add_chat_member(
            client, chat_id=_CHAT_ID, member=_GRACE, share_history=False, confirm=capturing
        )

        assert _GRACE_ID not in asked[0]
        assert _CHAT_ID not in asked[0]

    async def test_the_question_cuts_a_long_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _adds(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await add_chat_member(
            client,
            chat_id=_CHAT_ID,
            member=Person(user_id=_GRACE_ID, name="G" * 200),
            share_history=False,
            confirm=capturing,
        )

        assert asked[0].startswith(f"Add {'G' * 120 + '…'!r} to the Teams chat?")

    def test_the_binding_differs_for_another_user_another_chat_and_another_history(
        self,
    ) -> None:
        about = adder._about  # pyright: ignore[reportPrivateUsage]

        bound = about(_CHAT_ID, _GRACE_ID, share_history=False)

        assert bound != about(_CHAT_ID, _JANE_ID, share_history=False)
        assert bound != about(_OTHER_CHAT_ID, _GRACE_ID, share_history=False)
        assert bound != about(_CHAT_ID, _GRACE_ID, share_history=True)


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_posts(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _adds(graph)

        answer = await add_chat_member(
            client,
            chat_id=_CHAT_ID,
            member=_GRACE,
            share_history=False,
            confirm=a_person_agrees(_Session().context),
        )

        _key, _state, agrees_with, question = _the_question(answer)
        assert agrees_with == "add"
        assert "'Grace Hopper'" in question
        assert _GRACE_ID not in question
        assert route.call_count == 0, "an unanswered question added the member anyway"

    @pytest.mark.parametrize("share_history", [False, True])
    async def test_the_second_round_posts_the_member_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter, share_history: bool
    ) -> None:
        route = _adds(graph)
        key, state, agrees_with, _question = _the_question(
            await add_chat_member(
                client,
                chat_id=_CHAT_ID,
                member=_GRACE,
                share_history=share_history,
                confirm=a_person_agrees(_Session().context),
            )
        )

        answer = await add_chat_member(
            client,
            chat_id=_CHAT_ID,
            member=_GRACE,
            share_history=share_history,
            confirm=a_person_agrees(
                _Session(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                ).context
            ),
        )

        assert route.call_count == 1, "the agreed addition did not happen exactly once"
        assert len(graph.calls) == 1
        assert answer == AddedChatMember(
            chat_id=_CHAT_ID, user_id=_GRACE_ID, shared_history=share_history
        )

    @pytest.mark.parametrize(
        ("member", "share_history"),
        [
            pytest.param(_JANE, False, id="another-user"),
            pytest.param(Person(user_id=_JANE_ID, name=_GRACE.name), False, id="same-name"),
            pytest.param(_GRACE, True, id="with-history"),
        ],
    )
    async def test_an_answer_bound_to_another_addition_adds_nobody(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        member: Person,
        share_history: bool,
    ) -> None:
        route = _adds(graph)
        key, state, agrees_with, _question = _the_question(
            await add_chat_member(
                client,
                chat_id=_CHAT_ID,
                member=_GRACE,
                share_history=False,
                confirm=a_person_agrees(_Session().context),
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await add_chat_member(
                client,
                chat_id=_CHAT_ID,
                member=member,
                share_history=share_history,
                confirm=a_person_agrees(
                    _Session(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    ).context
                ),
            )

        assert route.call_count == 0, "a member was added under an answer nobody gave for it"

    async def test_the_same_id_under_another_name_adds_the_person_the_user_agreed_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _adds(graph)
        key, state, agrees_with, _question = _the_question(
            await add_chat_member(
                client,
                chat_id=_CHAT_ID,
                member=_GRACE,
                share_history=False,
                confirm=a_person_agrees(_Session().context),
            )
        )

        _ = await add_chat_member(
            client,
            chat_id=_CHAT_ID,
            member=Person(user_id=_GRACE_ID, name="grace@example.invalid"),
            share_history=False,
            confirm=a_person_agrees(
                _Session(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                ).context
            ),
        )

        assert route.call_count == 1
        assert (
            _body(route)["user@odata.bind"]
            == f"https://graph.microsoft.com/v1.0/users('{_GRACE_ID}')"
        )


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_post_graph_answers_503_is_never_sent_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_MEMBERS_PATH).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await add_chat_member(
                client, chat_id=_CHAT_ID, member=_GRACE, share_history=False, confirm=_agrees
            )

        assert route.call_count == 1

    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_throttled_post_is_not_repeated_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(_MEMBERS_PATH).mock(
            return_value=httpx.Response(429, headers={"Retry-After": "15"})
        )

        with pytest.raises(GraphThrottled):
            _ = await add_chat_member(
                client, chat_id=_CHAT_ID, member=_GRACE, share_history=False, confirm=_agrees
            )

        assert route.call_count == 1


class TestWhatItAnswers:
    @pytest.mark.parametrize("share_history", [False, True])
    async def test_a_created_answer_with_no_body_repeats_the_request(
        self, client: GraphServiceClient, graph: respx.MockRouter, share_history: bool
    ) -> None:
        _ = _adds(graph)

        answer = await add_chat_member(
            client,
            chat_id=_CHAT_ID,
            member=_GRACE,
            share_history=share_history,
            confirm=_agrees,
        )

        assert answer == AddedChatMember(
            chat_id=_CHAT_ID, user_id=_GRACE_ID, shared_history=share_history
        )


class TestTheFailuresItPassesOn:
    async def test_a_refused_addition_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(_MEMBERS_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await add_chat_member(
                client, chat_id=_CHAT_ID, member=_GRACE, share_history=False, confirm=_agrees
            )

    async def test_an_addition_graph_rejects_passes_on_graphs_reason(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        reason = "Cannot add members to a oneOnOne chat."
        _ = graph.post(_MEMBERS_PATH).mock(
            return_value=httpx.Response(
                400, json={"error": {"code": "BadRequest", "message": reason}}
            )
        )

        with pytest.raises(GraphFailure) as rejected:
            _ = await add_chat_member(
                client, chat_id=_CHAT_ID, member=_GRACE, share_history=False, confirm=_agrees
            )

        assert rejected.value.status == 400
        assert rejected.value.reason == reason


class TestHowItDeclaresItself:
    def test_the_permission_is_chat_member_read_write(self) -> None:
        assert adder.GRAPH_PERMISSIONS == ("ChatMember.ReadWrite",)

    def test_its_one_step_is_the_one_call_it_makes(self) -> None:
        assert adder.STEP == "add_chat_member"

    def test_teams_list_chat_members_shows_the_change(self) -> None:
        assert adder.CHANGE_SHOWN_BY == ("teams_list_chat_members",)

    async def test_it_announces_itself_as_an_addition_rather_than_a_destructive_write(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_ADDITIVE["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_ADDITIVE["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_ADDITIVE["idempotentHint"]
        assert annotations.open_world_hint is WRITE_ADDITIVE["openWorldHint"]

    async def test_the_description_says_it_asks_every_time_how_to_retry_and_who_sees_it(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert (
            "This tool asks the user to agree before it adds a member, every time. This tool "
            + "adds nobody unless the user agrees."
        ) in description
        assert (
            "If a call times out, do not call this tool again first. Before you call again, make "
            + "sure that teams_list_chat_members does not already show the member."
        ) in description
        assert "Everyone in the conversation can see the change." in description

    async def test_the_description_names_the_fixed_chat_and_the_limit_of_teams(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert "keeps the members of a `oneOnOne` chat fixed" in description
        assert "at most 4 additions a minute to one chat" in description

    async def test_the_arguments_are_chat_id_member_and_share_history_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
        assert set(properties) == {"chat_id", "member", "share_history"}
        assert set(cast("Sequence[str]", tool.parameters["required"])) == {"chat_id", "member"}
        assert properties["share_history"]["default"] is False
        assert set(adder.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_the_member_says_the_owner_role_leaves_out_an_in_tenant_guest(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
        described = " ".join(str(properties["member"]["description"]).split())
        assert (
            "This tool adds the person as an owner, and Microsoft accepts no in-tenant guest as "
            + "an owner."
        ) in described
        assert 15 <= len(described.split()) <= 60

    async def test_a_user_given_by_email_address_never_reaches_graph(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        tool = await _registered(transport)

        with pytest.raises(ValidationError, match="match pattern"):
            _ = await tool.run(
                {
                    **adder.GRAPH_CALL_EXAMPLE,
                    "member": {"user_id": "grace@example.invalid", "name": "Grace Hopper"},
                }
            )

        assert len(graph.calls) == 0, "a user id the schema refuses reached Graph"

    async def test_a_person_with_no_name_never_reaches_graph(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        tool = await _registered(transport)

        with pytest.raises(ValidationError, match="at least 1 character"):
            _ = await tool.run(
                {**adder.GRAPH_CALL_EXAMPLE, "member": {"user_id": _GRACE_ID, "name": ""}}
            )

        assert len(graph.calls) == 0
