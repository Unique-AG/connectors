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

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import MessageHandle, message_handle
from office_365_mcp.shared.messages import Mention
from office_365_mcp.shared.prose import PREVIEW_CHARACTERS
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirmed
from office_365_mcp.tools import teams_edit_message as editor
from office_365_mcp.tools.teams_edit_message import EditedMessage, a_person_agrees, edit_message

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

_EVERY_ENDPOINT: tuple[str, ...] = (_CHAT_PATH, _CHANNEL_PATH, _REPLY_PATH)

_TEXT = "Ship it Monday."
_OTHER_TEXT = "Ship it Tuesday."

_JANE = Mention(user_id="00000000-0000-4000-8000-000000000003", name="Jane Smith")
_ADA = Mention(user_id="00000000-0000-4000-8000-000000000001", name="Ada Lovelace")

_NOTHING_CHANGED = "No message was changed."


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_CHANGED


def _every_endpoint(graph: respx.MockRouter) -> Mapping[str, respx.Route]:
    return {
        endpoint: graph.patch(endpoint).mock(return_value=httpx.Response(204))
        for endpoint in _EVERY_ENDPOINT
    }


def _edits(graph: respx.MockRouter, endpoint: str = _CHAT_PATH) -> respx.Route:
    return graph.patch(endpoint).mock(return_value=httpx.Response(204))


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
    editor.register(mcp, transport)
    tool = await mcp.get_tool(editor.TOOL_NAME)
    assert tool is not None, "register left the tool off the server"
    assert isinstance(tool, FunctionTool)
    return tool


class TestTheRequestItMakes:
    @pytest.mark.parametrize(
        ("handle", "endpoint"),
        [
            pytest.param(_CHAT_HANDLE, _CHAT_PATH, id="chat"),
            pytest.param(_CHANNEL_HANDLE, _CHANNEL_PATH, id="post"),
            pytest.param(_REPLY_HANDLE, _REPLY_PATH, id="reply"),
        ],
    )
    async def test_each_handle_patches_once_its_own_endpoint_with_the_new_text(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        handle: MessageHandle,
        endpoint: str,
    ) -> None:
        routes = _every_endpoint(graph)

        _ = await edit_message(client, handle=handle, message=_TEXT, confirm=_agrees)

        assert {path: route.call_count for path, route in routes.items()} == {
            path: 1 if path == endpoint else 0 for path in _EVERY_ENDPOINT
        }
        assert len(graph.calls) == 1, "one edit costs one Graph call, and nothing else"
        assert routes[endpoint].calls.last.request.method == "PATCH"
        assert _body(routes[endpoint]) == {
            "body": {"content": _TEXT, "contentType": "text"},
            "mentions": [],
        }

    async def test_a_mention_goes_out_as_html_with_its_person(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _edits(graph)

        _ = await edit_message(
            client, handle=_CHAT_HANDLE, message=_TEXT, confirm=_agrees, mentions=[_JANE]
        )

        body = _body(route)
        assert body["body"] == {
            "content": '<at id="0">Jane Smith</at> Ship it Monday.',
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

    async def test_the_text_next_to_a_mention_is_escaped_as_in_a_send(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _edits(graph)

        _ = await edit_message(
            client,
            handle=_CHAT_HANDLE,
            message="1 < 2 & <b>done</b>\nnext",
            confirm=_agrees,
            mentions=[_JANE],
        )

        body = cast("Mapping[str, object]", _body(route)["body"])
        assert body["content"] == (
            '<at id="0">Jane Smith</at> 1 &lt; 2 &amp; &lt;b&gt;done&lt;/b&gt;<br>next'
        )


class TestThePersonBeforeTheChange:
    async def test_a_refusal_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        routes = _every_endpoint(graph)

        with pytest.raises(ToolError, match=_NOTHING_CHANGED):
            _ = await edit_message(client, handle=_CHAT_HANDLE, message=_TEXT, confirm=_refuses)

        assert all(route.call_count == 0 for route in routes.values())
        assert len(graph.calls) == 0

    async def test_a_decline_changes_nothing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        routes = _every_endpoint(graph)
        session = _Session(modern=False, elicited=DeclinedElicitation())

        with pytest.raises(ToolError, match=_NOTHING_CHANGED):
            _ = await edit_message(
                client,
                handle=_CHANNEL_HANDLE,
                message=_TEXT,
                confirm=a_person_agrees(session.context),
            )

        assert len(session.asked) == 1
        assert all(route.call_count == 0 for route in routes.values())

    async def test_agreeing_over_the_back_channel_changes_the_message(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _edits(graph)
        session = _Session(modern=False, elicited=AcceptedElicitation(data="edit"))

        _ = await edit_message(
            client, handle=_CHAT_HANDLE, message=_TEXT, confirm=a_person_agrees(session.context)
        )

        assert route.call_count == 1

    async def test_the_question_happens_before_the_patch(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _edits(graph)
        calls_when_asked: list[int] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(len(graph.calls))
            return None

        _ = await edit_message(client, handle=_CHAT_HANDLE, message=_TEXT, confirm=watching)

        assert calls_when_asked == [0], "asked after the message already changed"
        assert route.call_count == 1

    async def test_the_question_names_the_message_the_text_the_mentions_and_who_sees_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _every_endpoint(graph)
        asked: list[str] = []

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await edit_message(
            client,
            handle=_REPLY_HANDLE,
            message=_TEXT,
            confirm=capturing,
            mentions=[_JANE, _ADA],
        )

        assert len(asked) == 1
        assert _REPLY_HANDLE.uri in asked[0]
        assert repr(_TEXT) in asked[0]
        assert "It mentions 'Jane Smith', 'Ada Lovelace'." in asked[0]
        assert asked[0].endswith("Everyone in the conversation can see this change.")

    async def test_the_question_cuts_a_long_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _edits(graph)
        asked: list[str] = []
        long_text = "a" * (PREVIEW_CHARACTERS + 50)

        async def capturing(question: str, _about: str) -> Confirmed:
            asked.append(question)
            return None

        _ = await edit_message(client, handle=_CHAT_HANDLE, message=long_text, confirm=capturing)

        assert f"{'a' * PREVIEW_CHARACTERS}…" in asked[0]
        assert long_text not in asked[0]

    def test_the_binding_differs_for_another_text_another_mention_and_another_message(
        self,
    ) -> None:
        about = editor._about  # pyright: ignore[reportPrivateUsage]

        bound = about(_CHAT_HANDLE, _TEXT, (_JANE, _ADA))

        assert bound != about(_CHAT_HANDLE, _OTHER_TEXT, (_JANE, _ADA))
        assert bound != about(_CHAT_HANDLE, _TEXT, (_JANE,))
        assert bound != about(_CHAT_HANDLE, _TEXT, (_ADA, _JANE))
        assert bound != about(
            _CHAT_HANDLE, _TEXT, (Mention(user_id=_JANE.user_id, name="Jane S"), _ADA)
        )
        assert bound != about(_CHANNEL_HANDLE, _TEXT, (_JANE, _ADA))


class TestTheEraWithNoBackChannel:
    async def test_the_first_round_asks_and_never_patches(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        routes = _every_endpoint(graph)

        answer = await edit_message(
            client,
            handle=_CHAT_HANDLE,
            message=_TEXT,
            confirm=a_person_agrees(_Session().context),
        )

        _key, _state, agrees_with, question = _the_question(answer)
        assert agrees_with == "edit"
        assert _TEXT in question
        assert all(route.call_count == 0 for route in routes.values()), (
            "an unanswered question changed the message anyway"
        )

    async def test_the_second_round_patches_the_change_the_answer_was_bound_to(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _edits(graph)
        key, state, agrees_with, _question = _the_question(
            await edit_message(
                client,
                handle=_CHAT_HANDLE,
                message=_TEXT,
                confirm=a_person_agrees(_Session().context),
                mentions=[_JANE],
            )
        )

        answer = await edit_message(
            client,
            handle=_CHAT_HANDLE,
            message=_TEXT,
            confirm=a_person_agrees(
                _Session(
                    answers={key: ElicitResult(action="accept", content={"value": agrees_with})},
                    state=state,
                ).context
            ),
            mentions=[_JANE],
        )

        assert route.call_count == 1, "the agreed change did not happen exactly once"
        assert len(graph.calls) == 1
        assert answer == EditedMessage(uri=_CHAT_HANDLE.uri, text=_TEXT, mentions=[_JANE])

    @pytest.mark.parametrize(
        ("message", "mentions"),
        [
            pytest.param(_OTHER_TEXT, [_JANE], id="another-text"),
            pytest.param(_TEXT, [_ADA], id="another-mention"),
        ],
    )
    async def test_an_answer_bound_to_another_edit_changes_nothing(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        message: str,
        mentions: list[Mention],
    ) -> None:
        routes = _every_endpoint(graph)
        key, state, agrees_with, _question = _the_question(
            await edit_message(
                client,
                handle=_CHAT_HANDLE,
                message=_TEXT,
                confirm=a_person_agrees(_Session().context),
                mentions=[_JANE],
            )
        )

        with pytest.raises(ToolError, match="given for a different request"):
            _ = await edit_message(
                client,
                handle=_CHAT_HANDLE,
                message=message,
                confirm=a_person_agrees(
                    _Session(
                        answers={
                            key: ElicitResult(action="accept", content={"value": agrees_with})
                        },
                        state=state,
                    ).context
                ),
                mentions=mentions,
            )

        assert all(route.call_count == 0 for route in routes.values()), (
            "a message changed under an answer nobody gave for it"
        )


class TestWhatItAnswers:
    async def test_the_answer_repeats_the_handle_the_text_and_the_mentions(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _every_endpoint(graph)

        answer = await edit_message(
            client,
            handle=_REPLY_HANDLE,
            message=_TEXT,
            confirm=_agrees,
            mentions=[_ADA, _JANE],
        )

        assert answer == EditedMessage(uri=_REPLY_HANDLE.uri, text=_TEXT, mentions=[_ADA, _JANE])


class TestTheFailuresItPassesOn:
    async def test_a_refused_edit_is_a_forbidden(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.patch(_CHANNEL_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Forbidden", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await edit_message(client, handle=_CHANNEL_HANDLE, message=_TEXT, confirm=_agrees)

    async def test_a_message_graph_does_not_find_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = graph.patch(_CHAT_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await edit_message(client, handle=_CHAT_HANDLE, message=_TEXT, confirm=_agrees)


class TestHowRegisterWiresTheHandle:
    @pytest.mark.parametrize(
        ("handle", "permission"),
        [
            pytest.param(_CHAT_HANDLE, "Chat.ReadWrite", id="chat"),
            pytest.param(_CHANNEL_HANDLE, "ChannelMessage.ReadWrite", id="post"),
            pytest.param(_REPLY_HANDLE, "ChannelMessage.ReadWrite", id="reply"),
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
            "EditedMessage | InputRequiredResult",
            await tool.fn(
                uri=handle.uri, message=_TEXT, mentions=[], ctx=session.context, client=client
            ),
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

        with pytest.raises(ToolError, match=_NOTHING_CHANGED) as refused:
            _ = cast(
                "object",
                await tool.fn(
                    uri=uri, message=_TEXT, mentions=[], ctx=session.context, client=client
                ),
            )

        assert "teams:///chats/{chat_id}/messages/{message_id}" in str(refused.value)
        assert session.asked == []
        assert session.narrowed == []
        assert len(graph.calls) == 0


class TestHowItDeclaresItself:
    def test_it_declares_the_read_write_permission_of_each_surface(self) -> None:
        assert editor.GRAPH_PERMISSIONS == ("Chat.ReadWrite", "ChannelMessage.ReadWrite")

    def test_its_example_call_is_narrowed_to_the_chat_permission(self) -> None:
        example = cast("Mapping[str, str]", editor.GRAPH_CALL_EXAMPLE)
        handle = message_handle(example["uri"])

        assert handle is not None, "GRAPH_CALL_EXAMPLE's own uri is not a message handle"
        assert handle.chat_id is not None
        assert editor.GRAPH_CALL_NARROWS_TO == ("Chat.ReadWrite",)

    def test_its_one_step_is_the_one_call_it_makes(self) -> None:
        assert editor.STEP == "edit_message"

    async def test_it_announces_itself_as_a_destructive_write_that_is_safe_to_repeat(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        annotations = tool.annotations
        assert annotations is not None
        assert annotations.read_only_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["readOnlyHint"]
        assert annotations.destructive_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["destructiveHint"]
        assert annotations.idempotent_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["idempotentHint"]
        assert annotations.open_world_hint is WRITE_DESTRUCTIVE_IDEMPOTENT["openWorldHint"]

    async def test_the_description_says_it_asks_every_time_and_what_the_edit_replaces(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert (
            "This tool asks the user to agree before it changes a message, every time. This tool "
            + "changes nothing unless the user agrees."
        ) in description
        assert "Everyone in the conversation can see the change." in description
        assert (
            "The new text replaces all of the old text. A mention stays in the message only if "
            + "`mentions` gives it again."
        ) in description

    async def test_the_description_names_the_tools_that_send_and_remove_a_message(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = tool.description or ""
        assert "teams_send_chat_message" in description
        assert "teams_send_channel_message" in description
        assert "teams_delete_message" in description

    async def test_the_arguments_are_uri_message_and_mentions_and_nothing_else(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        properties = cast("Mapping[str, object]", tool.parameters["properties"])
        assert set(properties) == {"uri", "message", "mentions"}
        assert set(cast("Sequence[str]", tool.parameters["required"])) == {"uri", "message"}
        assert set(editor.GRAPH_CALL_EXAMPLE) <= set(properties)

    async def test_the_answer_field_names_where_the_edit_shows(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        schema = cast("Mapping[str, object]", tool.output_schema)
        properties = cast("Mapping[str, Mapping[str, str]]", schema["properties"])
        assert set(properties) == {"uri", "text", "mentions"}
        assert "teams_read_message" in properties["uri"]["description"]
        assert "`last_edited_at`" in properties["uri"]["description"]

    async def test_a_mention_by_email_address_never_reaches_this_tool(
        self, transport: httpx.AsyncClient, graph: respx.MockRouter
    ) -> None:
        tool = await _registered(transport)

        with pytest.raises(ValidationError, match="match pattern"):
            _ = await tool.run(
                {
                    **editor.GRAPH_CALL_EXAMPLE,
                    "mentions": [{"user_id": "jane@example.invalid", "name": "Jane Smith"}],
                }
            )

        assert len(graph.calls) == 0, "a mention the schema refuses reached Graph"
