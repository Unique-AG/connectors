import json
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

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.handles import MessageHandle, message_handle
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE, Confirmed
from office_365_mcp.tools import teams_react_to_message as reactor
from office_365_mcp.tools.teams_react_to_message import (
    ChangedReaction,
    a_person_agrees,
    react_to_message,
)

_CHAT_ID = "19:release@thread.v2"
_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"
_MESSAGE_ID = "1770000000000"
_REPLY_ID = "1770000000002"

_CHAT_HANDLE = MessageHandle(message_id=_MESSAGE_ID, chat_id=_CHAT_ID)
_CHANNEL_HANDLE = MessageHandle(message_id=_MESSAGE_ID, team_id=_TEAM_ID, channel_id=_CHANNEL_ID)
_REPLY_HANDLE = MessageHandle(
    message_id=_REPLY_ID, team_id=_TEAM_ID, channel_id=_CHANNEL_ID, reply_to_id=_MESSAGE_ID
)

_CHAT_PATH = f"/chats/19%3Arelease%40thread.v2/messages/{_MESSAGE_ID}"
_CHANNEL_PATH = f"/teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages/{_MESSAGE_ID}"
_REPLY_PATH = f"{_CHANNEL_PATH}/replies/{_REPLY_ID}"

_THUMBS_UP = "\U0001f44d"
_HEART = "❤️"

_NOTHING_CHANGED = "No reaction was changed."

_EVERY_ENDPOINT: tuple[str, ...] = tuple(
    f"{path}/{action}"
    for path in (_CHAT_PATH, _CHANNEL_PATH, _REPLY_PATH)
    for action in ("setReaction", "unsetReaction")
)


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_CHANGED


def _every_endpoint(graph: respx.MockRouter) -> Mapping[str, respx.Route]:
    return {
        endpoint: graph.post(endpoint).mock(return_value=httpx.Response(204))
        for endpoint in _EVERY_ENDPOINT
    }


def _reacts(graph: respx.MockRouter, endpoint: str = f"{_CHAT_PATH}/setReaction") -> respx.Route:
    return graph.post(endpoint).mock(return_value=httpx.Response(204))


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
        self.narrowed: list[object] = []
        self.asked: list[str] = []
        self._elicited: object = elicited

    async def set_state(self, key: str, value: object, *, serializable: bool = True) -> None:
        assert key and not serializable
        self.narrowed.append(value)

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
    reactor.register(mcp, transport)
    tool = await mcp.get_tool(reactor.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    assert isinstance(tool, FunctionTool)
    return tool


class TestTheRequestItMakes:
    @pytest.mark.parametrize(
        ("handle", "remove", "endpoint"),
        [
            pytest.param(_CHAT_HANDLE, False, f"{_CHAT_PATH}/setReaction", id="chat-set"),
            pytest.param(_CHAT_HANDLE, True, f"{_CHAT_PATH}/unsetReaction", id="chat-unset"),
            pytest.param(_CHANNEL_HANDLE, False, f"{_CHANNEL_PATH}/setReaction", id="post-set"),
            pytest.param(_CHANNEL_HANDLE, True, f"{_CHANNEL_PATH}/unsetReaction", id="post-unset"),
            pytest.param(_REPLY_HANDLE, False, f"{_REPLY_PATH}/setReaction", id="reply-set"),
            pytest.param(_REPLY_HANDLE, True, f"{_REPLY_PATH}/unsetReaction", id="reply-unset"),
        ],
    )
    async def test_each_handle_and_action_posts_once_to_its_own_endpoint(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        handle: MessageHandle,
        remove: bool,
        endpoint: str,
    ) -> None:
        routes = _every_endpoint(graph)

        _ = await react_to_message(
            client, handle=handle, reaction=_THUMBS_UP, remove=remove, confirm=_agrees
        )

        assert {path: route.call_count for path, route in routes.items()} == {
            path: 1 if path == endpoint else 0 for path in _EVERY_ENDPOINT
        }
        assert len(graph.calls) == 1, "one reaction change costs one Graph call, and nothing else"
        body = cast("Mapping[str, object]", json.loads(routes[endpoint].calls.last.request.content))
        assert body == {"reactionType": _THUMBS_UP}

    async def test_the_reaction_reaches_graph_as_the_unicode_it_was_given(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _reacts(graph)

        _ = await react_to_message(
            client, handle=_CHAT_HANDLE, reaction=_HEART, remove=False, confirm=_agrees
        )

        body = cast("Mapping[str, object]", json.loads(route.calls.last.request.content))
        assert body["reactionType"] == _HEART


class TestThePersonBeforeTheChange:
    async def test_a_refusal_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        routes = _every_endpoint(graph)

        with pytest.raises(ToolError, match=_NOTHING_CHANGED):
            _ = await react_to_message(
                client, handle=_CHAT_HANDLE, reaction=_THUMBS_UP, remove=False, confirm=_refuses
            )

        assert all(route.call_count == 0 for route in routes.values())
        assert len(graph.calls) == 0

    async def test_a_decline_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        routes = _every_endpoint(graph)
        session = _Session(modern=False, elicited=DeclinedElicitation())

        with pytest.raises(ToolError, match=_NOTHING_CHANGED):
            _ = await react_to_message(
                client,
                handle=_CHANNEL_HANDLE,
                reaction=_THUMBS_UP,
                remove=True,
                confirm=a_person_agrees(session.context, remove=True),
            )

        assert len(session.asked) == 1
        assert all(route.call_count == 0 for route in routes.values())

    async def test_agreeing_over_the_back_channel_changes_the_reaction(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _reacts(graph)
        session = _Session(modern=False, elicited=AcceptedElicitation(data="add"))

        _ = await react_to_message(
            client,
            handle=_CHAT_HANDLE,
            reaction=_THUMBS_UP,
            remove=False,
            confirm=a_person_agrees(session.context, remove=False),
        )

        assert route.call_count == 1

    async def test_the_question_happens_before_the_post(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _reacts(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await react_to_message(
            client, handle=_CHAT_HANDLE, reaction=_THUMBS_UP, remove=False, confirm=watching
        )

        assert calls_when_asked == [0], "asked after the reaction already changed"
        assert route.call_count == 1

    @pytest.mark.parametrize(("remove", "verb"), [(False, "Add"), (True, "Remove")])
    async def test_the_question_names_the_reaction_the_action_the_message_and_who_sees_it(
        self, client: GraphServiceClient, graph: respx.MockRouter, remove: bool, verb: str
    ) -> None:
        _ = _every_endpoint(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await react_to_message(
            client, handle=_REPLY_HANDLE, reaction=_THUMBS_UP, remove=remove, confirm=capturing
        )

        assert len(asked) == 1
        assert asked[0].startswith(f"{verb} the reaction {_THUMBS_UP!r}")
        assert _REPLY_HANDLE.uri in asked[0]
        assert "Everyone in the conversation can see this change." in asked[0]

    def test_the_binding_differs_for_another_reaction_another_action_and_another_message(
        self,
    ) -> None:
        about = reactor._about  # pyright: ignore[reportPrivateUsage]

        bound = about(_CHAT_HANDLE, _THUMBS_UP, remove=False)

        assert bound != about(_CHAT_HANDLE, _HEART, remove=False)
        assert bound != about(_CHAT_HANDLE, _THUMBS_UP, remove=True)
        assert bound != about(_CHANNEL_HANDLE, _THUMBS_UP, remove=False)


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_posts(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        routes = _every_endpoint(graph)

        answer = await react_to_message(
            client,
            handle=_CHAT_HANDLE,
            reaction=_THUMBS_UP,
            remove=False,
            confirm=a_person_agrees(_Session().context, remove=False),
        )

        _key, _state, agrees_with, question = _the_question(answer)
        assert agrees_with == "add"
        assert _THUMBS_UP in question
        assert all(route.call_count == 0 for route in routes.values()), (
            "an unanswered question changed the reaction anyway"
        )

    @pytest.mark.parametrize(
        ("remove", "endpoint"),
        [
            pytest.param(False, f"{_CHAT_PATH}/setReaction", id="add"),
            pytest.param(True, f"{_CHAT_PATH}/unsetReaction", id="remove"),
        ],
    )
    async def test_the_second_round_posts_the_change_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter, remove: bool, endpoint: str
    ) -> None:
        routes = _every_endpoint(graph)
        key, state, agrees_with, _question = _the_question(
            await react_to_message(
                client,
                handle=_CHAT_HANDLE,
                reaction=_THUMBS_UP,
                remove=remove,
                confirm=a_person_agrees(_Session().context, remove=remove),
            )
        )

        answer = await react_to_message(
            client,
            handle=_CHAT_HANDLE,
            reaction=_THUMBS_UP,
            remove=remove,
            confirm=a_person_agrees(
                _Session(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                ).context,
                remove=remove,
            ),
        )

        assert routes[endpoint].call_count == 1, "the agreed change did not happen exactly once"
        assert len(graph.calls) == 1
        assert answer == ChangedReaction(uri=_CHAT_HANDLE.uri, reaction=_THUMBS_UP, removed=remove)

    async def test_an_answer_bound_to_another_reaction_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        routes = _every_endpoint(graph)
        key, state, agrees_with, _question = _the_question(
            await react_to_message(
                client,
                handle=_CHAT_HANDLE,
                reaction=_THUMBS_UP,
                remove=False,
                confirm=a_person_agrees(_Session().context, remove=False),
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await react_to_message(
                client,
                handle=_CHAT_HANDLE,
                reaction=_HEART,
                remove=False,
                confirm=a_person_agrees(
                    _Session(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    ).context,
                    remove=False,
                ),
            )

        assert all(route.call_count == 0 for route in routes.values()), (
            "a reaction changed under an answer nobody gave for it"
        )


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    async def test_a_reaction_graph_answers_503_is_never_posted_a_second_time(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post(f"{_CHAT_PATH}/setReaction").mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await react_to_message(
                client, handle=_CHAT_HANDLE, reaction=_THUMBS_UP, remove=False, confirm=_agrees
            )

        assert route.call_count == 1


class TestWhatItAnswers:
    @pytest.mark.parametrize("remove", [False, True])
    async def test_the_answer_repeats_the_handle_the_reaction_and_the_action(
        self, client: GraphServiceClient, graph: respx.MockRouter, remove: bool
    ) -> None:
        _ = _every_endpoint(graph)

        answer = await react_to_message(
            client, handle=_REPLY_HANDLE, reaction=_HEART, remove=remove, confirm=_agrees
        )

        assert answer == ChangedReaction(uri=_REPLY_HANDLE.uri, reaction=_HEART, removed=remove)


class TestTheFailuresItPassesOn:
    async def test_a_refused_reaction_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(f"{_CHANNEL_PATH}/setReaction").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await react_to_message(
                client, handle=_CHANNEL_HANDLE, reaction=_THUMBS_UP, remove=False, confirm=_agrees
            )

    async def test_a_message_graph_does_not_find_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.post(f"{_CHAT_PATH}/unsetReaction").mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await react_to_message(
                client, handle=_CHAT_HANDLE, reaction=_THUMBS_UP, remove=True, confirm=_agrees
            )


class TestHowRegisterWiresTheHandle:
    @pytest.mark.parametrize(
        ("handle", "permission"),
        [
            pytest.param(_CHAT_HANDLE, "ChatMessage.Send", id="chat"),
            pytest.param(_CHANNEL_HANDLE, "ChannelMessage.Send", id="post"),
            pytest.param(_REPLY_HANDLE, "ChannelMessage.Send", id="reply"),
        ],
    )
    async def test_the_call_is_narrowed_to_the_permission_of_its_surface(
        self,
        transport: httpx.AsyncClient,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        handle: MessageHandle,
        permission: str,
    ) -> None:
        routes = _every_endpoint(graph)
        tool = await _registered(transport)
        session = _Session()

        answer = cast(
            "ChangedReaction | InputRequiredResult",
            await tool.fn(uri=handle.uri, reaction=_THUMBS_UP, ctx=session.context, client=client),
        )

        assert isinstance(answer, InputRequiredResult)
        assert session.narrowed == [(permission,)]
        assert all(route.call_count == 0 for route in routes.values())

    @pytest.mark.parametrize(
        "uri",
        [
            "19:release@thread.v2",
            "teams:///chats/19%3Arelease%40thread.v2",
            "teams:///chats/%20/messages/1770000000000",
            "teams:///meetings/https%3A%2F%2Fteams.microsoft.invalid%2Fl%2Fmeetup-join",
            "outlook:///messages/AAMkSYNTHETIC",
        ],
    )
    async def test_a_value_that_is_not_a_message_handle_is_refused_before_any_question(
        self,
        transport: httpx.AsyncClient,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        uri: str,
    ) -> None:
        tool = await _registered(transport)
        session = _Session(modern=False)

        with pytest.raises(ToolError, match="No reaction was changed") as refused:
            _ = cast(
                "object",
                await tool.fn(uri=uri, reaction=_THUMBS_UP, ctx=session.context, client=client),
            )

        assert "teams:///chats/{chat_id}/messages/{message_id}" in str(refused.value)
        assert session.asked == []
        assert session.narrowed == []
        assert len(graph.calls) == 0


class TestHowItDeclaresItself:
    def test_it_declares_the_send_permission_of_each_surface(self) -> None:
        assert reactor.GRAPH_PERMISSIONS == ("ChatMessage.Send", "ChannelMessage.Send")

    def test_its_example_call_is_narrowed_to_the_chat_permission(self) -> None:
        example = cast("Mapping[str, str]", reactor.GRAPH_CALL_EXAMPLE)
        handle = message_handle(example["uri"])

        assert handle is not None, "GRAPH_CALL_EXAMPLE's own uri is not a message handle"
        assert handle.chat_id is not None
        assert reactor.GRAPH_CALL_NARROWS_TO == ("ChatMessage.Send",)

    def test_teams_read_message_shows_the_change(self) -> None:
        assert reactor.CHANGE_SHOWN_BY == ("teams_read_message",)

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

    async def test_the_description_says_it_asks_every_time_and_how_to_retry(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        assert (
            "This tool asks the user to agree before it changes a reaction, every time. This tool "
            + "changes nothing unless the user agrees."
        ) in " ".join(description.split())
        assert (
            "If a call times out, do not call this tool again first. Before you call again, make "
            + "sure that teams_read_message does not already show the change."
        ) in " ".join(description.split())
        assert "Everyone in the conversation can see the change." in " ".join(description.split())

    async def test_the_arguments_are_uri_reaction_and_remove_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert set(properties) == {"uri", "reaction", "remove"}
        assert set(cast("Sequence[str]", tool.parameters["required"])) == {"uri", "reaction"}
        assert set(reactor.GRAPH_CALL_EXAMPLE) <= set(properties)
