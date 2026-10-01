from collections.abc import Mapping
from typing import cast

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden, GraphNotFound
from office_365_mcp.shared.handles import message_handle
from office_365_mcp.tools import teams_list_message_replies as lister

from .conftest import GRAPH_V1, message_payload

_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"
_POST_ID = "1770000000000"

_CHANNEL_URI = f"teams:///teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2"
_POST_URI = f"{_CHANNEL_URI}/messages/{_POST_ID}"
_REPLIES_PATH = (
    f"/teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages/{_POST_ID}/replies"
)

_SYSTEM_MESSAGE: dict[str, object] = {
    "@odata.type": "#microsoft.graph.chatMessage",
    "id": "1770000009999",
    "messageType": "unknownFutureValue",
    "createdDateTime": "2026-02-11T10:00:00Z",
    "from": None,
    "body": {"contentType": "html", "content": "<systemEventMessage/>"},
    "eventDetail": {
        "@odata.type": "#microsoft.graph.membersAddedEventMessageDetail",
        "members": [{"id": "00000000-0000-4000-8000-000000000002"}],
    },
}


def _reply(
    message_id: str, *, created_at: str, content: str = "a synthetic reply"
) -> dict[str, object]:
    payload = message_payload(
        message_id=message_id, content=content, content_type="text", reply_to_id=_POST_ID
    )
    payload["createdDateTime"] = created_at
    return payload


async def _list(
    client: GraphServiceClient, *, uri: str = _POST_URI, limit: int = 20
) -> lister.ThreadReplies:
    return await lister.teams_list_message_replies(client, uri=uri, limit=limit)


class TestTheRequestItSends:
    async def test_it_reads_the_replies_collection_of_the_post_with_the_page_size(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_REPLIES_PATH).mock(return_value=httpx.Response(200, json={"value": []}))

        _ = await _list(client, limit=7)

        assert route.call_count == 1
        params = route.calls.last.request.url.params
        assert params["$top"] == "7"
        assert set(params) == {"$top"}, "Microsoft supports no other option on this collection"

    async def test_it_asks_for_the_message_type_graph_hides_by_default(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.get(_REPLIES_PATH).mock(return_value=httpx.Response(200, json={"value": []}))

        _ = await _list(client)

        assert route.calls.last.request.headers["prefer"] == "include-unknown-enum-members"

    async def test_a_page_above_graphs_ceiling_is_a_programming_error(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await _list(client, limit=lister.MAX_REPLIES + 1)

        assert graph.calls.call_count == 0


class TestReadingTheRepliesOfOnePost:
    async def test_a_reply_carries_a_handle_teams_read_message_can_resolve(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_REPLIES_PATH).mock(
            return_value=httpx.Response(
                200, json={"value": [_reply("1770000000001", created_at="2026-02-11T10:00:00Z")]}
            )
        )

        listed = await _list(client)

        reply = listed.messages[0]
        assert reply.reply_to_id == _POST_ID
        assert (reply.team_id, reply.channel_id) == (_TEAM_ID, _CHANNEL_ID)
        assert reply.chat_id is None
        assert reply.uri == f"{_POST_URI}/replies/1770000000001"
        resolved = message_handle(reply.uri)
        assert resolved is not None
        assert (resolved.message_id, resolved.reply_to_id) == ("1770000000001", _POST_ID)
        assert resolved.channel_id == _CHANNEL_ID, "the handle round-trips its decoded ids"

    async def test_a_reply_graph_named_no_parent_for_is_still_placed_under_its_post(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        unparented = message_payload(message_id="1770000000001", reply_to_id=None)
        graph.get(_REPLIES_PATH).mock(
            return_value=httpx.Response(200, json={"value": [unparented]})
        )

        listed = await _list(client)

        assert listed.messages[0].reply_to_id == _POST_ID

    async def test_replies_come_oldest_first_whatever_order_graph_sent(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        replies = [
            _reply(f"177000000{index:04d}", created_at=f"2026-02-11T10:{index:02d}:00Z")
            for index in range(13)
        ]
        graph.get(_REPLIES_PATH).mock(
            return_value=httpx.Response(200, json={"value": list(reversed(replies))})
        )

        listed = await _list(client)

        assert [message.message_id for message in listed.messages] == [
            reply["id"] for reply in replies
        ]

    async def test_system_events_are_dropped(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_REPLIES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _SYSTEM_MESSAGE,
                        _reply("1770000000001", created_at="2026-02-11T10:00:00Z"),
                    ]
                },
            )
        )

        listed = await _list(client)

        assert [message.message_id for message in listed.messages] == ["1770000000001"]
        assert all(message.event is None for message in listed.messages)

    async def test_the_post_itself_is_not_among_the_replies(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_REPLIES_PATH).mock(
            return_value=httpx.Response(
                200, json={"value": [_reply("1770000000001", created_at="2026-02-11T10:00:00Z")]}
            )
        )

        listed = await _list(client)

        assert _POST_ID not in [message.message_id for message in listed.messages]

    async def test_a_post_nobody_answered_is_an_empty_list_not_a_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_REPLIES_PATH).mock(return_value=httpx.Response(200, json={"value": []}))

        listed = await _list(client)

        assert listed.messages == []
        assert listed.more_replies is False

    async def test_a_reply_arrives_whole_rather_than_as_a_snippet(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_REPLIES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _reply(
                            "1770000000001",
                            created_at="2026-02-11T10:00:00Z",
                            content="ship it, then tell everyone",
                        )
                    ]
                },
            )
        )

        listed = await _list(client)

        assert listed.messages[0].text == "ship it, then tell everyone"
        assert listed.messages[0].sender is not None


class TestOneCallIsOneRequest:
    async def test_microsofts_cursor_says_more_replies_exist_and_is_not_followed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        second_page = graph.get(_REPLIES_PATH, params={"$skiptoken": "synthetic"}).mock(
            return_value=httpx.Response(
                200,
                json={"value": [_reply("1770000000002", created_at="2026-02-11T11:00:00Z")]},
            )
        )
        graph.get(_REPLIES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [_reply("1770000000001", created_at="2026-02-11T10:00:00Z")],
                    "@odata.nextLink": f"{GRAPH_V1}{_REPLIES_PATH}?$skiptoken=synthetic",
                },
            )
        )

        listed = await _list(client)

        assert listed.more_replies is True
        assert [message.message_id for message in listed.messages] == ["1770000000001"]
        assert len(graph.calls) == 1, "one call is one request against the channel"
        assert not second_page.called, "the cursor is read, not followed"

    async def test_an_answer_without_a_cursor_says_that_was_the_whole_thread(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_REPLIES_PATH).mock(
            return_value=httpx.Response(
                200, json={"value": [_reply("1770000000001", created_at="2026-02-11T10:00:00Z")]}
            )
        )

        listed = await _list(client)

        assert listed.more_replies is False


class TestTheHandlesItRefuses:
    @pytest.mark.parametrize(
        "uri",
        [
            pytest.param(
                "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000", id="chat"
            ),
            pytest.param(f"{_POST_URI}/replies/1770000000001", id="reply"),
            pytest.param(_CHANNEL_URI, id="channel"),
            pytest.param("outlook:///messages/AAMkAGI2", id="mail"),
            pytest.param(
                "https://teams.microsoft.com/l/message/19%3Ageneral/1770000000000", id="link"
            ),
            pytest.param(f"{_CHANNEL_URI}/messages/%20", id="blank-post-id"),
        ],
    )
    async def test_a_value_that_is_not_a_channel_post_handle_never_reaches_graph(
        self, client: GraphServiceClient, graph: respx.MockRouter, uri: str
    ) -> None:
        with pytest.raises(ToolError) as refused:
            _ = await _list(client, uri=uri)

        advice = str(refused.value)
        assert graph.calls.call_count == 0
        assert "teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}" in advice
        assert "teams_browse_channel" in advice
        assert "teams_search_messages" in advice
        assert (
            "If you call this tool again with this value, the call will fail the same way."
            in advice
        )


class TestGraphFailures:
    async def test_a_refusal_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_REPLIES_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await _list(client)

    async def test_a_post_graph_cannot_find_is_a_not_found(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_REPLIES_PATH).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "Not Found"}}
            )
        )

        with pytest.raises(GraphNotFound):
            _ = await _list(client)


class TestHowItDeclaresItself:
    def test_the_permission_is_the_one_microsoft_documents(self) -> None:
        assert lister.GRAPH_PERMISSIONS == ("ChannelMessage.Read.All",)

    def test_the_refusable_call_is_a_handle_this_tool_accepts(self) -> None:
        assert set(lister.GRAPH_CALL_EXAMPLE) == {"uri"}
        example = message_handle(cast("str", lister.GRAPH_CALL_EXAMPLE["uri"]))
        assert example is not None
        assert example.chat_id is None
        assert example.reply_to_id is None
        assert example.team_id is not None

    async def test_it_announces_itself_as_reading_and_changing_nothing(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)

        tool = await mcp.get_tool(lister.TOOL_NAME)

        assert tool is not None, "register left the tool off the server"
        assert tool.annotations is not None
        assert tool.annotations.read_only_hint is True

    async def test_it_takes_one_required_handle_and_a_bounded_limit(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)
        tool = await mcp.get_tool(lister.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"

        properties = cast("Mapping[str, Mapping[str, object]]", tool.parameters["properties"])
        assert set(properties) == {"uri", "limit"}
        assert tool.parameters["required"] == ["uri"]
        assert properties["limit"]["minimum"] == 1
        assert properties["limit"]["maximum"] == 50
        assert properties["limit"]["default"] == 20
        described = cast("str", properties["uri"]["description"])
        assert "teams_browse_channel" in described
        assert "teams_search_messages" in described

    async def test_the_description_names_the_sibling_and_the_request_limit(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)
        tool = await mcp.get_tool(lister.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"

        described = tool.description or ""
        assert "teams_browse_channel" in described
        assert (
            "One call is one request, because a given channel allows this whole connector about "
            "one request a second, across the whole tenant."
        ) in described
        assert "never follows Microsoft's cursor" in described
        assert "the list is not the whole thread" in described
        assert "oldest first" in described

    async def test_it_answers_with_the_replies_and_whether_more_exist(
        self, transport: httpx.AsyncClient
    ) -> None:
        mcp: FastMCP = FastMCP(name="schema-under-test")
        lister.register(mcp, transport)
        tool = await mcp.get_tool(lister.TOOL_NAME)
        assert tool is not None, "register left the tool off the server"

        schema = cast("Mapping[str, object]", tool.output_schema)
        assert set(cast("Mapping[str, object]", schema["properties"])) == {
            "messages",
            "more_replies",
        }
