import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
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
from respx.models import Call

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import MessageHandle, message_handle
from office_365_mcp.shared.messages import Mention
from office_365_mcp.shared.prose import PREVIEW_CHARACTERS
from office_365_mcp.shared.seam import WRITE_DESTRUCTIVE_IDEMPOTENT, Confirmed
from office_365_mcp.tools import teams_edit_message as editor
from office_365_mcp.tools.teams_edit_message import EditedMessage, a_person_agrees, edit_message

from .conftest import ME, OTHER_USER_ID, message_payload

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

_SENDER = "Ada Lovelace"
_CURRENT_TEXT = "Ship it Friday"

_CURRENT = message_payload(content=f"<p>{_CURRENT_TEXT}</p>")

_JANE = Mention(user_id="00000000-0000-4000-8000-000000000003", name="Jane Smith")
_ADA = Mention(user_id="00000000-0000-4000-8000-000000000001", name="Ada Lovelace")

_NOTHING_CHANGED = "No message was changed."

_CHAT_PERMISSIONS = ("Chat.ReadWrite", "User.Read")
_CHANNEL_PERMISSIONS = ("ChannelMessage.ReadWrite", "ChannelMessage.Read.All", "User.Read")

_LETTERED_ID = "9f8e7d6c-5b4a-4c3d-8e2f-1a0b9c8d7e6f"

_NOT_THE_SENDER = (
    "Microsoft 365 does not name the signed-in user as the sender of this message. This tool "
    + "changes only a message that the signed-in user sent. No message was changed. If you "
    + "call this tool again with this handle, the call will fail the same way."
)


def _sent_by(user_id: str) -> dict[str, object]:
    return {
        "user": {
            "@odata.type": "#microsoft.graph.teamworkUserIdentity",
            "id": user_id,
            "displayName": "Grace Hopper",
            "userIdentityType": "aadUser",
        }
    }


_FROM_AN_APPLICATION: dict[str, object] = {
    "application": {
        "@odata.type": "#microsoft.graph.teamworkApplicationIdentity",
        "id": _LETTERED_ID,
        "displayName": "Release bot",
        "applicationIdentityType": "bot",
    }
}


async def _agrees(question: str, about: str) -> Confirmed:
    assert question and about
    return None


async def _refuses(question: str, about: str) -> Confirmed:
    assert question and about
    return _NOTHING_CHANGED


def _asking(asked: list[str]) -> Callable[[str, str], Awaitable[Confirmed]]:
    async def capturing(question: str, about: str) -> Confirmed:
        assert about
        asked.append(question)
        return None

    return capturing


def _me(graph: respx.MockRouter) -> respx.Route:
    return graph.get("/me").mock(return_value=httpx.Response(200, json=ME))


def _reads(
    graph: respx.MockRouter, message: Mapping[str, object] = _CURRENT
) -> Mapping[str, respx.Route]:
    _ = _me(graph)
    return {
        endpoint: graph.get(endpoint).mock(return_value=httpx.Response(200, json=message))
        for endpoint in _EVERY_ENDPOINT
    }


def _every_endpoint(graph: respx.MockRouter) -> Mapping[str, respx.Route]:
    _ = _reads(graph)
    return {
        endpoint: graph.patch(endpoint).mock(return_value=httpx.Response(204))
        for endpoint in _EVERY_ENDPOINT
    }


def _edits(graph: respx.MockRouter, endpoint: str = _CHAT_PATH) -> respx.Route:
    _ = _reads(graph)
    return graph.patch(endpoint).mock(return_value=httpx.Response(204))


def _methods(graph: respx.MockRouter) -> list[str]:
    return [call.request.method for call in cast("Sequence[Call]", graph.calls)]


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
    async def test_each_handle_reads_and_then_patches_once_its_own_endpoint_with_the_new_text(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        handle: MessageHandle,
        endpoint: str,
    ) -> None:
        reads = _reads(graph)
        routes = {
            path: graph.patch(path).mock(return_value=httpx.Response(204))
            for path in _EVERY_ENDPOINT
        }

        _ = await edit_message(client, handle=handle, message=_TEXT, confirm=_agrees)

        assert {path: route.call_count for path, route in reads.items()} == {
            path: 1 if path == endpoint else 0 for path in _EVERY_ENDPOINT
        }
        assert {path: route.call_count for path, route in routes.items()} == {
            path: 1 if path == endpoint else 0 for path in _EVERY_ENDPOINT
        }
        assert _methods(graph) == ["GET", "GET", "PATCH"], (
            "one edit reads the message and the signed-in user, then writes once"
        )
        assert _body(routes[endpoint]) == {
            "body": {"content": _TEXT, "contentType": "text"},
            "mentions": [],
        }

    async def test_the_message_is_read_with_the_message_types_graph_hides_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _reads(graph)[_CHAT_PATH]

        with pytest.raises(ToolError, match=_NOTHING_CHANGED):
            _ = await edit_message(client, handle=_CHAT_HANDLE, message=_TEXT, confirm=_refuses)

        assert route.calls.last.request.headers["prefer"] == "include-unknown-enum-members"

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
        assert _methods(graph) == ["GET", "GET"]

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

    @pytest.mark.parametrize(
        ("handle", "endpoint"),
        [
            pytest.param(_CHAT_HANDLE, _CHAT_PATH, id="chat"),
            pytest.param(_CHANNEL_HANDLE, _CHANNEL_PATH, id="post"),
            pytest.param(_REPLY_HANDLE, _REPLY_PATH, id="reply"),
        ],
    )
    async def test_the_read_happens_before_the_question_and_the_write_after_it(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        handle: MessageHandle,
        endpoint: str,
    ) -> None:
        routes = _every_endpoint(graph)
        calls_when_asked: list[list[str]] = []

        async def watching(question: str, about: str) -> Confirmed:
            assert question and about
            calls_when_asked.append(_methods(graph))
            return None

        _ = await edit_message(client, handle=handle, message=_TEXT, confirm=watching)

        assert calls_when_asked == [["GET", "GET"]], "asked before the reads, or after the change"
        assert _methods(graph) == ["GET", "GET", "PATCH"]
        assert routes[endpoint].call_count == 1

    async def test_the_question_names_the_sender_the_current_text_the_new_text_and_who_sees_it(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _every_endpoint(graph)
        asked: list[str] = []

        _ = await edit_message(
            client,
            handle=_REPLY_HANDLE,
            message=_TEXT,
            confirm=_asking(asked),
            mentions=[_JANE, _ADA],
        )

        assert asked == [
            f"Replace the text of the Teams message from {_SENDER!r} that says "
            + f"{_CURRENT_TEXT!r} with {_TEXT!r}? It mentions 'Jane Smith', 'Ada Lovelace'. "
            + "Everyone in the conversation can see this change."
        ]
        assert "teams:///" not in asked[0], "a handle means nothing to the person who agrees"

    async def test_the_question_names_the_attachments_that_the_change_removes(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _every_endpoint(graph)
        _ = _reads(
            graph,
            message_payload(
                content=f'<p>{_CURRENT_TEXT}</p><attachment id="a1"></attachment>',
                attachments=[
                    {
                        "id": "a1",
                        "contentType": "reference",
                        "contentUrl": "https://contoso.invalid/plan.docx",
                        "name": "plan.docx",
                    },
                    {
                        "id": "c1",
                        "contentType": "application/vnd.microsoft.card.adaptive",
                        "content": "{}",
                        "name": None,
                    },
                ],
            ),
        )
        asked: list[str] = []

        _ = await edit_message(client, handle=_CHAT_HANDLE, message=_TEXT, confirm=_asking(asked))

        assert len(asked) == 1
        assert asked[0].endswith(
            "? The change can remove 'plan.docx', an attachment from the message. "
            + "Everyone in the conversation can see this change."
        )

    async def test_the_question_of_a_message_with_no_attachment_names_no_removal(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _every_endpoint(graph)
        asked: list[str] = []

        _ = await edit_message(client, handle=_CHAT_HANDLE, message=_TEXT, confirm=_asking(asked))

        assert len(asked) == 1
        assert "remove" not in asked[0]

    @pytest.mark.parametrize(
        ("message", "named"),
        [
            pytest.param(
                message_payload(content="<p></p>"),
                f"of the Teams message from {_SENDER!r} that has no text with",
                id="no-text",
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

        _ = await edit_message(client, handle=_CHAT_HANDLE, message=_TEXT, confirm=_asking(asked))

        assert len(asked) == 1
        assert named in asked[0]

    async def test_the_question_cuts_a_long_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        _ = _edits(graph)
        asked: list[str] = []
        long_text = "a" * (PREVIEW_CHARACTERS + 50)

        _ = await edit_message(
            client, handle=_CHAT_HANDLE, message=long_text, confirm=_asking(asked)
        )

        assert f"{'a' * PREVIEW_CHARACTERS}…" in asked[0]
        assert long_text not in asked[0]

    async def test_the_question_cuts_a_long_current_text(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        text = " ".join(["word"] * 100)
        _ = _every_endpoint(graph)
        _ = _reads(graph, message_payload(content=text))
        asked: list[str] = []

        _ = await edit_message(client, handle=_CHAT_HANDLE, message=_TEXT, confirm=_asking(asked))

        assert len(asked) == 1
        assert f"that says {f'{text[:PREVIEW_CHARACTERS]}…'!r} with" in asked[0]

    async def test_a_deleted_message_is_refused_before_any_question(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        routes = _every_endpoint(graph)
        _ = _reads(graph, message_payload(deleted_at="2026-02-11T10:00:00Z"))
        session = _Session(modern=False, elicited=AcceptedElicitation(data="edit"))

        with pytest.raises(ToolError) as refused:
            _ = await edit_message(
                client, handle=_CHAT_HANDLE, message=_TEXT, confirm=a_person_agrees(session.context)
            )

        assert str(refused.value) == (
            "This message is deleted, and a deleted message cannot be changed. No message was "
            + "changed. If you call this tool again with this handle, the call will fail the same "
            + "way."
        )
        assert session.asked == []
        assert all(route.call_count == 0 for route in routes.values())
        assert _methods(graph) == ["GET"]

    @pytest.mark.parametrize(
        "sender",
        [
            pytest.param(_sent_by(OTHER_USER_ID), id="another-person"),
            pytest.param(None, id="no-sender"),
            pytest.param(_FROM_AN_APPLICATION, id="application"),
        ],
    )
    @pytest.mark.parametrize(
        "handle", [_CHAT_HANDLE, _CHANNEL_HANDLE, _REPLY_HANDLE], ids=["chat", "post", "reply"]
    )
    async def test_a_message_that_the_signed_in_user_did_not_send_is_refused_before_any_question(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        sender: Mapping[str, object] | None,
        handle: MessageHandle,
    ) -> None:
        routes = _every_endpoint(graph)
        _ = _reads(graph, message_payload(content=f"<p>{_CURRENT_TEXT}</p>", sender=sender))
        session = _Session(modern=False, elicited=AcceptedElicitation(data="edit"))

        with pytest.raises(ToolError) as refused:
            _ = await edit_message(
                client, handle=handle, message=_TEXT, confirm=a_person_agrees(session.context)
            )

        assert str(refused.value) == _NOT_THE_SENDER
        assert session.asked == []
        assert all(route.call_count == 0 for route in routes.values())
        assert _methods(graph) == ["GET", "GET"]

    async def test_a_sender_id_that_differs_only_in_letter_case_is_the_signed_in_user(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = _edits(graph)
        _ = _reads(graph, message_payload(sender=_sent_by(_LETTERED_ID.upper())))
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json={**ME, "id": _LETTERED_ID}))

        _ = await edit_message(client, handle=_CHAT_HANDLE, message=_TEXT, confirm=_agrees)

        assert route.call_count == 1

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
        assert _methods(graph) == ["GET", "GET", "GET", "GET", "PATCH"], (
            "each round reads the message and the signed-in user, and one round writes"
        )
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
        _ = _reads(graph)
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
        _ = _reads(graph)
        _ = graph.patch(_CHAT_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await edit_message(client, handle=_CHAT_HANDLE, message=_TEXT, confirm=_agrees)

    @pytest.mark.parametrize(
        ("handle", "path"),
        [
            pytest.param(_CHAT_HANDLE, _CHAT_PATH, id="chat"),
            pytest.param(_CHANNEL_HANDLE, _CHANNEL_PATH, id="post"),
            pytest.param(_REPLY_HANDLE, _REPLY_PATH, id="reply"),
        ],
    )
    async def test_a_read_graph_does_not_find_is_a_not_found_before_any_question(
        self, client: GraphServiceClient, graph: respx.MockRouter, handle: MessageHandle, path: str
    ) -> None:
        routes = _every_endpoint(graph)
        _ = graph.get(path).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "Not Found"}}
            )
        )
        asked: list[str] = []

        with pytest.raises(GraphNotFound):
            _ = await edit_message(client, handle=handle, message=_TEXT, confirm=_asking(asked))

        assert asked == []
        assert all(route.call_count == 0 for route in routes.values())
        assert "PATCH" not in _methods(graph)


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
        assert session.narrowed == [permissions]
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
    def test_it_declares_the_write_permission_of_each_surface_the_identity_and_channel_reads(
        self,
    ) -> None:
        assert editor.GRAPH_PERMISSIONS == (
            "Chat.ReadWrite",
            "ChannelMessage.ReadWrite",
            "User.Read",
            "ChannelMessage.Read.All",
        )
        assert set(_CHAT_PERMISSIONS) | set(_CHANNEL_PERMISSIONS) == set(editor.GRAPH_PERMISSIONS)

    def test_its_example_call_is_narrowed_to_the_chat_permissions(self) -> None:
        example = cast("Mapping[str, str]", editor.GRAPH_CALL_EXAMPLE)
        handle = message_handle(example["uri"])

        assert handle is not None, "GRAPH_CALL_EXAMPLE's own uri is not a message handle"
        assert handle.chat_id is not None
        assert editor.GRAPH_CALL_NARROWS_TO == _CHAT_PERMISSIONS

    def test_its_write_step_is_the_patch(self) -> None:
        assert editor.STEP_EDIT == "edit_message"

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

    async def test_the_description_says_whose_message_it_changes_that_it_asks_and_what_it_removes(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)

        description = " ".join((tool.description or "").split())
        assert "The message must be one that the signed-in user sent." in description
        assert (
            "This tool asks the user to agree before it changes a message, every time. This tool "
            + "changes nothing unless the user agrees."
        ) in description
        assert "Everyone in the conversation can see the change." in description
        assert (
            "The new text replaces all of the old text. A mention stays in the message only if "
            + "`mentions` gives it again."
        ) in description
        assert (
            "This tool sends no file and no card, so the change can remove a file or a card from "
            + "the message."
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
        assert "teams_list_chat_messages" in properties["uri"]["description"]
        assert "teams_browse_channel" in properties["uri"]["description"]
        assert "`last_edited_at`" in properties["uri"]["description"]

    @pytest.mark.parametrize("unregistered", ["teams_read_message", "teams_search_messages"])
    async def test_no_text_names_a_reader_its_preset_lacks(
        self, transport: httpx.AsyncClient, unregistered: str
    ) -> None:
        tool = await _registered(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
        output = cast("Mapping[str, object]", tool.output_schema)
        answer = cast("Mapping[str, Mapping[str, object]]", output["properties"])

        assert not re.search(rf"\b{unregistered}\b", tool.description or "")
        assert not re.search(rf"\b{unregistered}\b", str(properties["uri"]["description"]))
        assert not re.search(rf"\b{unregistered}\b", str(answer["uri"]["description"]))

    async def test_the_uri_names_the_three_tools_that_list_a_message(
        self, transport: httpx.AsyncClient
    ) -> None:
        tool = await _registered(transport)
        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
        uri = " ".join(str(properties["uri"]["description"]).split())

        assert (
            "The message to change, as the `uri` handle from a teams_list_chat_messages, "
            + "teams_browse_channel, or teams_list_message_replies result."
        ) in uri

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
