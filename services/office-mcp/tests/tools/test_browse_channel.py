"""`browse_channel`: the one request it spends, the order it must not correct, and the traps."""

from collections.abc import Mapping, Sequence

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import GraphForbidden
from office_mcp.shared.handles import message_handle
from office_mcp.shared.messages import MAX_REPLIES_PER_POST
from office_mcp.tools import browse_channel as browser

from .conftest import GRAPH_V1

_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"
_MESSAGES_PATH = f"/teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages"

_TEAMS_SENDER: dict[str, object] = {
    "user": {
        "@odata.type": "#microsoft.graph.teamworkUserIdentity",
        "id": "00000000-0000-4000-8000-000000000001",
        "displayName": "Ada Lovelace",
        "userIdentityType": "aadUser",
    }
}


def _message_payload(
    *,
    message_id: str,
    content: str,
    content_type: str = "html",
) -> dict[str, object]:
    return {
        "@odata.type": "#microsoft.graph.chatMessage",
        "id": message_id,
        "etag": message_id,
        "messageType": "message",
        "createdDateTime": "2026-02-11T09:15:22.31Z",
        "lastModifiedDateTime": "2026-02-11T09:15:22.31Z",
        "lastEditedDateTime": None,
        "deletedDateTime": None,
        "subject": None,
        "importance": "normal",
        "locale": "en-us",
        "webUrl": None,
        "replyToId": None,
        "from": dict(_TEAMS_SENDER),
        "body": {"contentType": content_type, "content": content},
        "mentions": [],
        "attachments": [],
        "reactions": [],
        "eventDetail": None,
    }


def _post_payload(
    message_id: str,
    *,
    content: str = "<div><p>a synthetic post</p></div>",
    created_at: str = "2026-02-11T09:15:22.31Z",
    replies: Sequence[Mapping[str, object]] = (),
    more_replies: bool = False,
) -> dict[str, object]:
    payload = _message_payload(message_id=message_id, content=content)
    payload["createdDateTime"] = created_at
    payload["replies"] = [dict(reply) for reply in replies]
    if more_replies:
        payload["replies@odata.nextLink"] = f"{GRAPH_V1}{_MESSAGES_PATH}/{message_id}/replies"
    return payload


def _reply_payload(
    message_id: str, *, root_id: str, created_at: str, content: str = "a synthetic reply"
) -> dict[str, object]:
    payload = _message_payload(message_id=message_id, content=content, content_type="text")
    payload["createdDateTime"] = created_at
    payload["replyToId"] = root_id
    return payload


_SYSTEM_MESSAGE: dict[str, object] = {
    "@odata.type": "#microsoft.graph.chatMessage",
    "id": "1770000009999",
    # Without the `Prefer` header Graph types this `unknownFutureValue`, which is why the
    # authorless `from` and the populated `eventDetail` are the signals filtered on.
    "messageType": "unknownFutureValue",
    "createdDateTime": "2026-02-11T10:00:00Z",
    "from": None,
    "body": {"contentType": "html", "content": "<systemEventMessage/>"},
    "eventDetail": {
        "@odata.type": "#microsoft.graph.membersAddedEventMessageDetail",
        "members": [{"id": "00000000-0000-4000-8000-000000000002"}],
    },
    "replies": [],
}


class TestTheQueryItSends:
    async def test_browsing_a_channel_asks_for_replies_and_a_page_size(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`$top` and `$expand` are the only two parameters this collection takes."""
        route = graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(200, json={"value": [_post_payload("1770000000000")]})
        )

        _ = await browser.browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=7,
            include_window_completeness=False,
        )

        params = route.calls.last.request.url.params
        assert params["$top"] == "7"
        assert params["$expand"] == "replies"
        assert "$orderby" not in params, "no ordering is supported here"
        assert "$filter" not in params, "no filter is supported here, which is why no date is taken"

    async def test_a_page_of_posts_above_graphs_ceiling_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await browser.browse_channel(
                client,
                team_id=_TEAM_ID,
                channel_id=_CHANNEL_ID,
                limit=browser.MAX_POSTS + 1,
                include_window_completeness=False,
            )


class TestBrowsingOneChannel:
    async def test_a_post_arrives_whole_rather_than_as_a_snippet(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _post_payload(
                            "1770000000000",
                            content="<div><p>ship it&nbsp;&amp; tell everyone</p></div>",
                        )
                    ]
                },
            )
        )

        browsed = await browser.browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=20,
            include_window_completeness=False,
        )

        post = browsed.messages[0]
        assert post.text == "ship it & tell everyone"
        assert (post.team_id, post.channel_id) == (_TEAM_ID, _CHANNEL_ID)
        assert post.chat_id is None
        assert post.reply_to_id is None, "a root post answers nothing"

    async def test_one_browse_is_one_graph_request_whatever_the_channel_holds(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph allows this whole connector about one request a second on a given channel *for
        the tenant*, so following `@odata.nextLink` spends a budget that is not this call's."""
        second_page = graph.get(_MESSAGES_PATH, params={"$skiptoken": "synthetic"}).mock(
            return_value=httpx.Response(200, json={"value": [_post_payload("1770000000002")]})
        )
        graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [_SYSTEM_MESSAGE, _post_payload("1770000000000")],
                    "@odata.nextLink": f"{GRAPH_V1}{_MESSAGES_PATH}?$skiptoken=synthetic",
                },
            )
        )

        browsed = await browser.browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=20,
            include_window_completeness=False,
        )

        assert [message.message_id for message in browsed.messages] == ["1770000000000"]
        assert len(graph.calls) == 1, "one browse is one request against the channel"
        assert not second_page.called, "the collection's cursor is deliberately not followed"

    async def test_the_order_is_graphs_reply_chain_order_and_the_dates_say_so(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph sorts a channel's messages by the last modified date of the *entire reply
        chain*, so `created_at` and not the position is what tells the truth about age."""
        graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _post_payload(
                            "1600000000000",
                            created_at="2024-03-01T08:00:00Z",
                            replies=[
                                _reply_payload(
                                    "1770000000001",
                                    root_id="1600000000000",
                                    created_at="2026-02-11T09:00:00Z",
                                )
                            ],
                        ),
                        _post_payload("1770000000000", created_at="2026-02-10T09:00:00Z"),
                    ]
                },
            )
        )

        browsed = await browser.browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=20,
            include_window_completeness=False,
        )

        assert [message.message_id for message in browsed.messages] == [
            "1600000000000",
            "1770000000001",
            "1770000000000",
        ]
        first = browsed.messages[0].created_at
        assert first is not None and first.year == 2024, (
            "the first message is the oldest post, revived by a reply"
        )

    async def test_a_reply_carries_a_handle_read_message_can_actually_resolve(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph addresses a reply under the post it answers, so the root-post handle shape cannot
        name one and a search hit on a reply 404s. Browsing knows each reply's parent."""
        graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _post_payload(
                            "1770000000000",
                            replies=[
                                _reply_payload(
                                    "1770000000001",
                                    root_id="1770000000000",
                                    created_at="2026-02-11T10:00:00Z",
                                )
                            ],
                        )
                    ]
                },
            )
        )

        browsed = await browser.browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=20,
            include_window_completeness=False,
        )

        reply = browsed.messages[1]
        assert reply.reply_to_id == "1770000000000"
        assert reply.uri == (
            f"teams:///teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2"
            + "/messages/1770000000000/replies/1770000000001"
        )
        resolved = message_handle(reply.uri)
        assert resolved is not None
        assert (resolved.message_id, resolved.reply_to_id) == (
            "1770000000001",
            "1770000000000",
        )
        assert resolved.channel_id == _CHANNEL_ID, "the handle round-trips its decoded ids"

    async def test_replies_are_sorted_and_the_newest_of_a_long_thread_are_kept(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph publishes no order for replies, so they are sorted here."""
        replies = [
            _reply_payload(
                f"177000000{index:04d}",
                root_id="1770000000000",
                created_at=f"2026-02-11T10:{index:02d}:00Z",
            )
            for index in range(MAX_REPLIES_PER_POST + 3)
        ]
        graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={"value": [_post_payload("1770000000000", replies=list(reversed(replies)))]},
            )
        )

        browsed = await browser.browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=20,
            include_window_completeness=False,
        )

        kept = [message.message_id for message in browsed.messages[1:]]
        assert kept == [reply["id"] for reply in replies[-MAX_REPLIES_PER_POST:]], (
            "the newest replies, oldest first"
        )
        assert len(kept) == MAX_REPLIES_PER_POST, (
            "a thread filled to the window is how a caller sees that it may have older replies"
        )

    async def test_a_thread_graph_itself_paged_is_not_chased(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Following the per-post replies cursor would be a request per post against the same
        one-a-second channel. The cursor needs no reporting either: Graph expands up to 200 replies
        before it pages them, so a thread it paged overflows this window regardless."""
        replies = graph.get(f"{_MESSAGES_PATH}/1770000000000/replies").mock(
            return_value=httpx.Response(200, json={"value": []})
        )
        graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _post_payload(
                            "1770000000000",
                            replies=[
                                _reply_payload(
                                    "1770000000001",
                                    root_id="1770000000000",
                                    created_at="2026-02-11T10:00:00Z",
                                )
                            ],
                            more_replies=True,
                        )
                    ]
                },
            )
        )

        browsed = await browser.browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=20,
            include_window_completeness=False,
        )

        assert len(browsed.messages) == 2
        assert not replies.called, "a post's own replies cursor is not followed either"
        assert len(graph.calls) == 1

    async def test_system_messages_are_dropped_wherever_they_appear(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph offers no `messageType` filter here, so a page can hold fewer posts than asked
        for, which is not evidence of a quiet channel."""
        graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _SYSTEM_MESSAGE,
                        _post_payload(
                            "1770000000000",
                            replies=[
                                _SYSTEM_MESSAGE,
                                _reply_payload(
                                    "1770000000001",
                                    root_id="1770000000000",
                                    created_at="2026-02-11T10:00:00Z",
                                ),
                            ],
                        ),
                    ]
                },
            )
        )

        browsed = await browser.browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=20,
            include_window_completeness=False,
        )

        assert [message.message_id for message in browsed.messages] == [
            "1770000000000",
            "1770000000001",
        ]
        assert all(message.event is None for message in browsed.messages)

    async def test_microsofts_own_cursor_is_what_says_the_channel_holds_more(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """System messages are dropped out of the page after Graph counted them into it, so this
        answer's own length says nothing about completeness. Graph's cursor does."""
        second_page = graph.get(_MESSAGES_PATH, params={"$skiptoken": "synthetic"}).mock(
            return_value=httpx.Response(200, json={"value": [_post_payload("1770000000002")]})
        )
        graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [_post_payload("1770000000000")],
                    "@odata.nextLink": f"{GRAPH_V1}{_MESSAGES_PATH}?$skiptoken=synthetic",
                },
            )
        )

        browsed = await browser.browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=20,
            include_window_completeness=True,
        )

        assert browsed.more_posts_in_channel is True
        assert browsed.posts_cut_to_limit is False, "the window closed over nothing Graph sent"
        assert len(browsed.messages) == 1, "a short answer, and Graph said there is more"
        assert len(graph.calls) == 1 and not second_page.called, "the cursor is read, not followed"

    async def test_the_same_page_without_a_cursor_says_that_was_the_channel(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The page above with its cursor taken off, and nothing else changed."""
        graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(200, json={"value": [_post_payload("1770000000000")]})
        )

        browsed = await browser.browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=20,
            include_window_completeness=True,
        )

        assert browsed.more_posts_in_channel is False
        assert browsed.posts_cut_to_limit is False

    async def test_a_page_holding_more_posts_than_the_window_is_the_other_fact(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Two fields because the remedies are opposite: raising `limit` returns what this window
        closed over, and nothing returns what is behind Microsoft's cursor."""
        graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _post_payload("1770000000000"),
                        _post_payload("1770000000001"),
                        _post_payload("1770000000002"),
                    ]
                },
            )
        )

        browsed = await browser.browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=2,
            include_window_completeness=True,
        )

        assert [message.message_id for message in browsed.messages] == [
            "1770000000000",
            "1770000000001",
        ]
        assert browsed.posts_cut_to_limit is True, "raise `limit` and the third post comes back"
        assert browsed.more_posts_in_channel is False, "Microsoft offered no continuation"

    async def test_neither_fact_is_reported_unless_it_was_asked_for(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [_post_payload("1770000000000")],
                    "@odata.nextLink": f"{GRAPH_V1}{_MESSAGES_PATH}?$skiptoken=synthetic",
                },
            )
        )

        browsed = await browser.browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=1,
            include_window_completeness=False,
        )

        assert browsed.more_posts_in_channel is None
        assert browsed.posts_cut_to_limit is None
        assert len(browsed.messages) == 1, "the answer itself is unchanged either way"

    async def test_a_channel_nobody_has_posted_in_is_an_empty_page_not_a_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_MESSAGES_PATH).mock(return_value=httpx.Response(200, json={"value": []}))

        browsed = await browser.browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=20,
            include_window_completeness=False,
        )

        assert browsed.messages == []


class TestGraphFailures:
    async def test_a_refusal_arrives_classified_for_the_tool_to_explain(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        denied = httpx.Response(
            403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
        )
        graph.get(_MESSAGES_PATH).mock(return_value=denied)

        with pytest.raises(GraphForbidden):
            _ = await browser.browse_channel(
                client,
                team_id=_TEAM_ID,
                channel_id=_CHANNEL_ID,
                limit=20,
                include_window_completeness=False,
            )

    def test_the_permission_is_the_one_microsoft_documents(self) -> None:
        assert browser.GRAPH_PERMISSIONS == ("ChannelMessage.Read.All",)
