import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
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

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound, GraphUnavailable
from office_365_mcp.shared.handles import MessageHandle, message_handle
from office_365_mcp.shared.prose import PREVIEW_CHARACTERS
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE, Confirmed
from office_365_mcp.tools import PRESETS, TOOL_NAMES, graph_advice, resolve
from office_365_mcp.tools import teams_delete_message as deleter
from office_365_mcp.tools.teams_delete_message import (
    DeletedMessage,
    a_person_agrees,
    delete_message,
)

from .conftest import ME, SIGNED_IN_USER_ID, message_payload

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

_CHAT_MESSAGE = f"/chats/19%3Arelease%40thread.v2/messages/{_MESSAGE_ID}"
_CHANNEL_MESSAGE = f"/teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages/{_MESSAGE_ID}"
_REPLY_MESSAGE = f"{_CHANNEL_MESSAGE}/replies/{_REPLY_ID}"

_EVERY_READ: tuple[str, ...] = (_CHAT_MESSAGE, _CHANNEL_MESSAGE, _REPLY_MESSAGE)

_CHAT_DELETE = (
    f"/users/{SIGNED_IN_USER_ID}/chats/19%3Arelease%40thread.v2/messages/{_MESSAGE_ID}/softDelete"
)
_CHANNEL_DELETE = f"{_CHANNEL_MESSAGE}/softDelete"
_REPLY_DELETE = f"{_REPLY_MESSAGE}/softDelete"

_EVERY_ENDPOINT: tuple[str, ...] = (_CHAT_DELETE, _CHANNEL_DELETE, _REPLY_DELETE)

_NOTHING_DELETED = "No message was deleted."

_SENDER = "Ada Lovelace"
_TEXT = "Ship it Monday"

_CURRENT = message_payload(content=f"<p>{_TEXT}</p>")

_CHAT_PERMISSIONS = ("Chat.ReadWrite", "User.Read")
_CHANNEL_PERMISSIONS = ("ChannelMessage.ReadWrite", "ChannelMessage.Read.All")


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_DELETED


def _asking(asked: list[str]) -> Callable[[str, str], Awaitable[Confirmed]]:
    async def capturing(question: str, about: str) -> Confirmed:
        assert about
        asked.append(question)
        return None

    return capturing


def _me(graph: respx.MockRouter) -> respx.Route:
    return graph.get("/me").mock(return_value=httpx.Response(200, json=ME))


def _methods(graph: respx.MockRouter) -> list[str]:
    return [call.request.method for call in cast("Sequence[Call]", graph.calls)]


def _reads(
    graph: respx.MockRouter, message: Mapping[str, object] = _CURRENT
) -> Mapping[str, respx.Route]:
    return {
        endpoint: graph.get(endpoint).mock(return_value=httpx.Response(200, json=message))
        for endpoint in _EVERY_READ
    }


def _every_endpoint(graph: respx.MockRouter) -> Mapping[str, respx.Route]:
    _ = _reads(graph)
    return {
        endpoint: graph.post(endpoint).mock(return_value=httpx.Response(204))
        for endpoint in _EVERY_ENDPOINT
    }


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
    deleter.register(mcp, transport)
    tool = await mcp.get_tool(deleter.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    assert isinstance(tool, FunctionTool)
    return tool


class TestTheRequestItMakes:
    @pytest.mark.parametrize(
        ("handle", "read", "endpoint"),
        [
            pytest.param(_CHAT_HANDLE, _CHAT_MESSAGE, _CHAT_DELETE, id="chat"),
            pytest.param(_CHANNEL_HANDLE, _CHANNEL_MESSAGE, _CHANNEL_DELETE, id="post"),
            pytest.param(_REPLY_HANDLE, _REPLY_MESSAGE, _REPLY_DELETE, id="reply"),
        ],
    )
    async def test_each_handle_reads_and_then_posts_once_to_its_own_endpoint_with_no_body(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        handle: MessageHandle,
        read: str,
        endpoint: str,
    ) -> None:
        _ = _me(graph)
        reads = _reads(graph)
        routes = {
            path: graph.post(path).mock(return_value=httpx.Response(204))
            for path in _EVERY_ENDPOINT
        }

        _ = await delete_message(client, handle=handle, confirm=_agrees)

        assert {path: route.call_count for path, route in reads.items()} == {
            path: 1 if path == read else 0 for path in _EVERY_READ
        }
        assert {path: route.call_count for path, route in routes.items()} == {
            path: 1 if path == endpoint else 0 for path in _EVERY_ENDPOINT
        }
        assert routes[endpoint].calls.last.request.content == b""

    async def test_the_message_is_read_with_the_message_types_graph_hides_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _reads(graph)[_CHAT_MESSAGE]

        with pytest.raises(ToolError, match=_NOTHING_DELETED):
            _ = await delete_message(client, handle=_CHAT_HANDLE, confirm=_refuses)

        assert route.calls.last.request.headers["prefer"] == "include-unknown-enum-members"

    async def test_a_chat_delete_reads_the_message_then_the_signed_in_user_then_posts(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        me = _me(graph)
        read = _reads(graph)[_CHAT_MESSAGE]
        delete = graph.post(_CHAT_DELETE).mock(return_value=httpx.Response(204))

        _ = await delete_message(client, handle=_CHAT_HANDLE, confirm=_agrees)

        assert [call.request for call in cast("Sequence[Call]", graph.calls)] == [
            read.calls.last.request,
            me.calls.last.request,
            delete.calls.last.request,
        ]

    @pytest.mark.parametrize("handle", [_CHANNEL_HANDLE, _REPLY_HANDLE], ids=["post", "reply"])
    async def test_a_channel_delete_costs_one_read_and_one_post_and_never_reads_the_signed_in_user(
        self, client: GraphServiceClient, graph: respx.MockRouter, handle: MessageHandle
    ) -> None:
        me = _me(graph)
        _ = _every_endpoint(graph)

        _ = await delete_message(client, handle=handle, confirm=_agrees)

        assert me.call_count == 0
        assert _methods(graph) == ["GET", "POST"]


class TestThePersonBeforeTheChange:
    async def test_a_refusal_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _me(graph)
        _ = _every_endpoint(graph)

        with pytest.raises(ToolError, match=_NOTHING_DELETED):
            _ = await delete_message(client, handle=_CHAT_HANDLE, confirm=_refuses)

        assert _methods(graph) == ["GET"]

    async def test_a_decline_over_the_back_channel_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _me(graph)
        routes = _every_endpoint(graph)
        session = _Session(modern=False, elicited=DeclinedElicitation())

        with pytest.raises(ToolError, match=_NOTHING_DELETED):
            _ = await delete_message(
                client, handle=_CHANNEL_HANDLE, confirm=a_person_agrees(session.context)
            )

        assert len(session.asked) == 1
        assert all(route.call_count == 0 for route in routes.values())

    async def test_agreeing_over_the_back_channel_deletes_the_message(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        routes = _every_endpoint(graph)
        session = _Session(modern=False, elicited=AcceptedElicitation(data="delete"))

        _ = await delete_message(
            client, handle=_REPLY_HANDLE, confirm=a_person_agrees(session.context)
        )

        assert routes[_REPLY_DELETE].call_count == 1

    @pytest.mark.parametrize(
        ("handle", "writes"),
        [
            pytest.param(_CHAT_HANDLE, ["GET", "POST"], id="chat"),
            pytest.param(_CHANNEL_HANDLE, ["POST"], id="post"),
            pytest.param(_REPLY_HANDLE, ["POST"], id="reply"),
        ],
    )
    async def test_the_read_happens_before_the_question_and_the_write_after_it(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        handle: MessageHandle,
        writes: list[str],
    ) -> None:
        _ = _me(graph)
        _ = _every_endpoint(graph)
        calls_when_asked: list[list[str]] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(_methods(graph))
            return None

        _ = await delete_message(client, handle=handle, confirm=watching)

        assert calls_when_asked == [["GET"]], "asked before the read, or after the delete"
        assert _methods(graph) == ["GET", *writes]

    async def test_the_question_names_the_sender_the_text_and_who_sees_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _every_endpoint(graph)
        asked: list[str] = []

        _ = await delete_message(client, handle=_REPLY_HANDLE, confirm=_asking(asked))

        assert asked == [
            f"Delete the Teams message from {_SENDER!r} that says {_TEXT!r}? "
            + "Everyone in the conversation can see this change."
        ]
        assert "teams:///" not in asked[0], "a handle means nothing to the person who agrees"

    async def test_the_question_cuts_a_long_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        text = " ".join(["word"] * 100)
        _ = _every_endpoint(graph)
        _ = _reads(graph, message_payload(content=text))
        asked: list[str] = []

        _ = await delete_message(client, handle=_CHANNEL_HANDLE, confirm=_asking(asked))

        assert len(asked) == 1
        assert f"that says {f'{text[:PREVIEW_CHARACTERS]}…'!r}?" in asked[0]

    @pytest.mark.parametrize(
        ("message", "named"),
        [
            pytest.param(
                message_payload(content="<p></p>"),
                f"Delete the Teams message from {_SENDER!r} that has no text?",
                id="no-text",
            ),
            pytest.param(
                message_payload(content=f"<p>{_TEXT}</p>", sender=None),
                f"Delete the Teams message that says {_TEXT!r}?",
                id="no-sender",
            ),
        ],
    )
    async def test_the_question_says_what_the_message_lacks(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        message: Mapping[str, object],
        named: str,
    ) -> None:
        _ = _every_endpoint(graph)
        _ = _reads(graph, message)
        asked: list[str] = []

        _ = await delete_message(client, handle=_CHANNEL_HANDLE, confirm=_asking(asked))

        assert len(asked) == 1
        assert asked[0].startswith(named)

    async def test_a_deleted_message_is_refused_before_any_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        me = _me(graph)
        routes = _every_endpoint(graph)
        _ = _reads(graph, message_payload(deleted_at="2026-02-11T10:00:00Z"))
        session = _Session(modern=False, elicited=AcceptedElicitation(data="delete"))

        with pytest.raises(ToolError) as refused:
            _ = await delete_message(
                client, handle=_CHAT_HANDLE, confirm=a_person_agrees(session.context)
            )

        assert str(refused.value) == (
            "This message is already deleted. No message was deleted. If you call this tool "
            + "again with this handle, the call will fail the same way."
        )
        assert session.asked == []
        assert me.call_count == 0
        assert all(route.call_count == 0 for route in routes.values())
        assert _methods(graph) == ["GET"]

    def test_the_binding_differs_for_another_message(self) -> None:
        about = deleter._about  # pyright: ignore[reportPrivateUsage]

        bound = about(_CHAT_HANDLE)

        assert bound == about(MessageHandle(message_id=_MESSAGE_ID, chat_id=_CHAT_ID))
        assert bound != about(_CHANNEL_HANDLE)
        assert about(_CHANNEL_HANDLE) != about(_REPLY_HANDLE)


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_posts(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _me(graph)
        _ = _every_endpoint(graph)

        answer = await delete_message(
            client, handle=_CHAT_HANDLE, confirm=a_person_agrees(_Session().context)
        )

        _key, _state, agrees_with, question = _the_question(answer)
        assert agrees_with == "delete"
        assert repr(_TEXT) in question
        assert _methods(graph) == ["GET"], "an unanswered question deleted the message anyway"

    async def test_the_second_round_deletes_the_message_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        me = _me(graph)
        routes = _every_endpoint(graph)
        key, state, agrees_with, _question = _the_question(
            await delete_message(
                client, handle=_CHAT_HANDLE, confirm=a_person_agrees(_Session().context)
            )
        )

        answer = await delete_message(
            client,
            handle=_CHAT_HANDLE,
            confirm=a_person_agrees(
                _Session(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                ).context
            ),
        )

        assert me.call_count == 1
        assert routes[_CHAT_DELETE].call_count == 1, "the agreed delete did not happen once"
        assert answer == DeletedMessage(uri=_CHAT_HANDLE.uri, deleted=True)

    async def test_a_decline_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _me(graph)
        _ = _every_endpoint(graph)
        key, state, _agrees_with, _question = _the_question(
            await delete_message(
                client, handle=_CHAT_HANDLE, confirm=a_person_agrees(_Session().context)
            )
        )

        with pytest.raises(ToolError, match=_NOTHING_DELETED):
            _ = await delete_message(
                client,
                handle=_CHAT_HANDLE,
                confirm=a_person_agrees(
                    _Session(answers={key: ElicitResult(action="decline")}, state=state).context
                ),
            )

        assert "POST" not in _methods(graph)

    async def test_an_answer_bound_to_another_message_deletes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _me(graph)
        _ = _every_endpoint(graph)
        key, state, agrees_with, _question = _the_question(
            await delete_message(
                client, handle=_CHAT_HANDLE, confirm=a_person_agrees(_Session().context)
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await delete_message(
                client,
                handle=_CHANNEL_HANDLE,
                confirm=a_person_agrees(
                    _Session(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    ).context
                ),
            )

        assert "POST" not in _methods(graph), (
            "a message was deleted under an answer nobody gave for it"
        )


class TestTheRetryItRefuses:
    @pytest.mark.usefixtures("retry_sleeps")
    @pytest.mark.parametrize(
        ("handle", "endpoint"),
        [
            pytest.param(_CHAT_HANDLE, _CHAT_DELETE, id="chat"),
            pytest.param(_CHANNEL_HANDLE, _CHANNEL_DELETE, id="post"),
            pytest.param(_REPLY_HANDLE, _REPLY_DELETE, id="reply"),
        ],
    )
    async def test_a_delete_graph_answers_503_is_never_posted_a_second_time(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        handle: MessageHandle,
        endpoint: str,
    ) -> None:
        _ = _me(graph)
        _ = _reads(graph)
        route = graph.post(endpoint).mock(return_value=httpx.Response(503))

        with pytest.raises(GraphUnavailable):
            _ = await delete_message(client, handle=handle, confirm=_agrees)

        assert route.call_count == 1


class TestWhatItAnswers:
    @pytest.mark.parametrize(
        "handle", [_CHAT_HANDLE, _CHANNEL_HANDLE, _REPLY_HANDLE], ids=["chat", "post", "reply"]
    )
    async def test_the_answer_repeats_the_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter, handle: MessageHandle
    ) -> None:
        _ = _me(graph)
        _ = _every_endpoint(graph)

        answer = await delete_message(client, handle=handle, confirm=_agrees)

        assert answer == DeletedMessage(uri=handle.uri, deleted=True)


class TestTheFailuresItPassesOn:
    async def test_a_refused_delete_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _reads(graph)
        _ = graph.post(_CHANNEL_DELETE).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await delete_message(client, handle=_CHANNEL_HANDLE, confirm=_agrees)

    async def test_a_message_graph_does_not_find_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _me(graph)
        _ = _reads(graph)
        _ = graph.post(_CHAT_DELETE).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await delete_message(client, handle=_CHAT_HANDLE, confirm=_agrees)

    @pytest.mark.parametrize(
        ("handle", "path"),
        [
            pytest.param(_CHAT_HANDLE, _CHAT_MESSAGE, id="chat"),
            pytest.param(_CHANNEL_HANDLE, _CHANNEL_MESSAGE, id="post"),
            pytest.param(_REPLY_HANDLE, _REPLY_MESSAGE, id="reply"),
        ],
    )
    async def test_a_read_graph_does_not_find_is_a_not_found_before_any_question(
        self, client: GraphServiceClient, graph: respx.MockRouter, handle: MessageHandle, path: str
    ) -> None:
        me = _me(graph)
        routes = _every_endpoint(graph)
        _ = graph.get(path).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "Not Found"}}
            )
        )
        asked: list[str] = []

        with pytest.raises(GraphNotFound):
            _ = await delete_message(client, handle=handle, confirm=_asking(asked))

        assert asked == []
        assert me.call_count == 0
        assert all(route.call_count == 0 for route in routes.values())

    async def test_a_refused_identity_read_posts_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.get("/me").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )
        routes = _every_endpoint(graph)

        with pytest.raises(GraphForbidden):
            _ = await delete_message(client, handle=_CHAT_HANDLE, confirm=_agrees)

        assert all(route.call_count == 0 for route in routes.values())


class TestHowRegisterWiresTheHandle:
    @pytest.mark.parametrize(
        ("handle", "permissions"),
        [
            pytest.param(_CHAT_HANDLE, _CHAT_PERMISSIONS, id="chat"),
            pytest.param(_CHANNEL_HANDLE, _CHANNEL_PERMISSIONS, id="post"),
            pytest.param(_REPLY_HANDLE, _CHANNEL_PERMISSIONS, id="reply"),
        ],
    )
    async def test_the_call_is_narrowed_to_the_permissions_of_its_surface(
        self,
        transport: httpx.AsyncClient,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        handle: MessageHandle,
        permissions: tuple[str, ...],
    ) -> None:
        _ = _me(graph)
        _ = _every_endpoint(graph)
        tool = await _registered(transport)
        session = _Session()

        answer = cast(
            "DeletedMessage | InputRequiredResult",
            await tool.fn(uri=handle.uri, ctx=session.context, client=client),
        )

        assert isinstance(answer, InputRequiredResult)
        assert session.narrowed == [permissions]
        assert _methods(graph) == ["GET"]

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
        _ = _me(graph)
        _ = _every_endpoint(graph)
        tool = await _registered(transport)
        session = _Session(modern=False)

        with pytest.raises(ToolError, match=_NOTHING_DELETED) as refused:
            _ = cast("object", await tool.fn(uri=uri, ctx=session.context, client=client))

        assert "teams:///chats/{chat_id}/messages/{message_id}" in str(refused.value)
        assert session.asked == []
        assert session.narrowed == []
        assert len(graph.calls) == 0


class TestHowItDeclaresItself:
    def test_it_declares_the_write_permission_of_each_surface_the_identity_and_channel_reads(
        self,
    ) -> None:
        assert deleter.GRAPH_PERMISSIONS == (
            "Chat.ReadWrite",
            "ChannelMessage.ReadWrite",
            "User.Read",
            "ChannelMessage.Read.All",
        )
        assert set(_CHAT_PERMISSIONS) | set(_CHANNEL_PERMISSIONS) == set(deleter.GRAPH_PERMISSIONS)

    def test_its_example_call_is_narrowed_to_the_chat_permissions(self) -> None:
        example = cast("Mapping[str, str]", deleter.GRAPH_CALL_EXAMPLE)
        handle = message_handle(example["uri"])

        assert handle is not None, "GRAPH_CALL_EXAMPLE's own uri is not a message handle"
        assert handle.chat_id is not None
        assert deleter.GRAPH_CALL_NARROWS_TO == _CHAT_PERMISSIONS

    def test_the_read_tools_whose_rows_carry_deleted_at_show_the_change(self) -> None:
        assert deleter.CHANGE_SHOWN_BY == (
            "teams_read_message",
            "teams_list_chat_messages",
            "teams_browse_channel",
            "teams_list_message_replies",
        )

    @pytest.mark.parametrize(
        "preset", [preset for preset, tools in PRESETS.items() if deleter.TOOL_NAME in tools]
    )
    def test_every_preset_that_holds_it_also_holds_a_tool_that_shows_the_change(
        self, preset: str
    ) -> None:
        advice = graph_advice(resolve(preset=preset, enabled=None))

        assert advice[deleter.TOOL_NAME].shown_by, preset

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

    @pytest.mark.parametrize(
        "sentence",
        [
            "This is a soft delete: Teams shows the message as deleted.",
            "Everyone in the conversation can see the change.",
            "This tool asks the user to agree before it deletes a message, every time. This tool "
            + "deletes nothing unless the user agrees.",
            "Microsoft Graph has an operation that undoes a soft delete (undoSoftDelete). This "
            + "connector does not offer that operation.",
            "If a call times out, do not call this tool again first. Before you call again, make "
            + "sure that the conversation does not already show the change.",
            "teams_edit_message replaces the text of a message instead.",
        ],
    )
    async def test_the_description_says(self, transport: httpx.AsyncClient, sentence: str) -> None:
        tool = await _registered(transport)

        assert sentence in " ".join((tool.description or "").split())

    async def test_the_retry_note_names_no_tool(self, transport: httpx.AsyncClient) -> None:
        tool = await _registered(transport)

        lines = (tool.description or "").splitlines()
        retry = [line for line in lines if line.startswith("- If a call times out")]
        assert len(retry) == 1, lines
        assert not [name for name in TOOL_NAMES if name in retry[0]], retry[0]

    async def test_no_text_sends_the_model_to_teams_read_message_to_see_the_delete(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        schema = cast("Mapping[str, object]", tool.output_schema)
        properties = cast("Mapping[str, Mapping[str, str]]", schema["properties"])
        assert "teams_read_message" not in (tool.description or "")
        assert "teams_read_message" not in properties["uri"]["description"]
        assert "`deleted_at`" in properties["uri"]["description"]

    @pytest.mark.parametrize("unregistered", ["teams_read_message", "teams_search_messages"])
    async def test_neither_the_description_nor_the_uri_names_a_reader_its_preset_lacks(
        self, transport: httpx.AsyncClient, unregistered: str
    ) -> None:
        tool = await _registered(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])

        assert not re.search(rf"\b{unregistered}\b", tool.description or "")
        assert not re.search(rf"\b{unregistered}\b", str(properties["uri"]["description"]))

    async def test_the_uri_names_the_three_tools_that_list_a_message(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
        uri = " ".join(str(properties["uri"]["description"]).split())

        assert (
            "The message to delete, as the `uri` handle from a teams_list_chat_messages, "
            + "teams_browse_channel, or teams_list_message_replies result."
        ) in uri

    async def test_the_only_argument_is_uri(self, transport: httpx.AsyncClient) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert set(properties) == {"uri"}
        assert set(cast("Sequence[str]", tool.parameters["required"])) == {"uri"}
        assert set(deleter.GRAPH_CALL_EXAMPLE) <= set(properties)
