"""Tests for `teams_browse_channel`: the single request it sends, the order it must not
change, and the traps it must avoid."""

from collections.abc import Mapping, Sequence

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.handles import message_handle
from office_365_mcp.shared.messages import MAX_REPLIES_PER_POST
from office_365_mcp.tools import teams_browse_channel as browser

from .conftest import GRAPH_V1, reaction_payload

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
    reactions: Sequence[Mapping[str, object]] = (),
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
        "reactions": [dict(reaction) for reaction in reactions],
        "eventDetail": None,
    }


def _post_payload(
    message_id: str,
    *,
    content: str = "<div><p>a synthetic post</p></div>",
    created_at: str = "2026-02-11T09:15:22.31Z",
    replies: Sequence[Mapping[str, object]] = (),
    more_replies: bool = False,
    reactions: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    payload = _message_payload(message_id=message_id, content=content, reactions=reactions)
    payload["createdDateTime"] = created_at
    payload["replies"] = [dict(reply) for reply in replies]
    if more_replies:
        payload["replies@odata.nextLink"] = f"{GRAPH_V1}{_MESSAGES_PATH}/{message_id}/replies"
    return payload


def _reply_payload(
    message_id: str,
    *,
    root_id: str,
    created_at: str,
    content: str = "a synthetic reply",
    reactions: Sequence[Mapping[str, object]] = (),
) -> dict[str, object]:
    payload = _message_payload(
        message_id=message_id, content=content, content_type="text", reactions=reactions
    )
    payload["createdDateTime"] = created_at
    payload["replyToId"] = root_id
    return payload


_SYSTEM_MESSAGE: dict[str, object] = {
    "@odata.type": "#microsoft.graph.chatMessage",
    "id": "1770000009999",
    # Without the `Prefer` header, Graph reports this message as `unknownFutureValue`. The
    # code identifies a system message by a missing `from` field and a non-null `eventDetail`
    # field.
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
        """This collection accepts only two parameters: `$top` and `$expand`."""
        route = graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(200, json={"value": [_post_payload("1770000000000")]})
        )

        _ = await browser.teams_browse_channel(
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
            _ = await browser.teams_browse_channel(
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

        browsed = await browser.teams_browse_channel(
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

    async def test_reactions_arrive_on_a_post_with_no_widening_of_the_request(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`reactions` is a plain property of the message, not a navigation property behind
        `$expand`. It arrives with the same `$top`+`$expand=replies` request that every other
        test in this file uses."""
        route = graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        _post_payload(
                            "1770000000000",
                            reactions=[
                                reaction_payload(
                                    reaction_type="\U0001f44d", display_name="Grace Hopper"
                                )
                            ],
                        )
                    ]
                },
            )
        )

        browsed = await browser.teams_browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=20,
            include_window_completeness=False,
        )

        assert route.calls.last.request.url.params["$expand"] == "replies", (
            "reactions needed no widening on top of it"
        )
        post = browsed.messages[0]
        assert len(post.reactions) == 1
        assert post.reactions[0].reaction_type == "\U0001f44d"

    async def test_a_reply_carries_its_own_reactions_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
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
                                    reactions=[reaction_payload(reaction_type="❤️")],
                                )
                            ],
                        )
                    ]
                },
            )
        )

        browsed = await browser.teams_browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=20,
            include_window_completeness=False,
        )

        reply = browsed.messages[1]
        assert [reaction.reaction_type for reaction in reply.reactions] == ["❤️"]

    async def test_a_post_nobody_reacted_to_has_an_empty_list(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(200, json={"value": [_post_payload("1770000000000")]})
        )

        browsed = await browser.teams_browse_channel(
            client,
            team_id=_TEAM_ID,
            channel_id=_CHANNEL_ID,
            limit=20,
            include_window_completeness=False,
        )

        assert browsed.messages[0].reactions == []

    async def test_one_browse_is_one_graph_request_whatever_the_channel_holds(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph allows this whole connector about one request each second, for the whole tenant,
        on a given channel. If the code follows `@odata.nextLink`, it spends part of that shared
        budget, not a budget of its own."""
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

        browsed = await browser.teams_browse_channel(
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
        """Graph sorts a channel's messages by the last-modified date of the entire reply chain.
        The `created_at` field, not the position in the list, shows the true age of a
        message."""
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

        browsed = await browser.teams_browse_channel(
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

    async def test_a_reply_carries_a_handle_teams_read_message_can_actually_resolve(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph addresses a reply under the post that the reply answers. The root-post handle
        shape cannot name a reply, so a search hit on a reply returns a 404 error. The
        `teams_browse_channel` function knows the parent of each reply."""
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

        browsed = await browser.teams_browse_channel(
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
        """Graph does not document an order for replies, so the code sorts them here."""
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

        browsed = await browser.teams_browse_channel(
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
        """If the code follows the per-post replies cursor, each post costs a separate request
        against the same channel, which allows one request each second. The cursor also needs no
        report to the caller. Graph expands up to 200 replies before it pages them, so a paged
        thread always overflows this window."""
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

        browsed = await browser.teams_browse_channel(
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
        """Graph offers no `messageType` filter here. A page can hold fewer posts than the request
        asked for. This is not evidence of a quiet channel."""
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

        browsed = await browser.teams_browse_channel(
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
        """The code removes system messages from the page after Graph counts them into it, so the
        length of the answer says nothing about completeness. The cursor from Graph shows this
        instead."""
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

        browsed = await browser.teams_browse_channel(
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
        """This test repeats the previous one with the cursor removed. Nothing else changes."""
        graph.get(_MESSAGES_PATH).mock(
            return_value=httpx.Response(200, json={"value": [_post_payload("1770000000000")]})
        )

        browsed = await browser.teams_browse_channel(
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
        """There are two fields because the remedies are opposite. A higher `limit` value returns
        the posts that this window excluded. Nothing brings back the posts behind Microsoft's
        cursor."""
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

        browsed = await browser.teams_browse_channel(
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

        browsed = await browser.teams_browse_channel(
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

        browsed = await browser.teams_browse_channel(
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
            _ = await browser.teams_browse_channel(
                client,
                team_id=_TEAM_ID,
                channel_id=_CHANNEL_ID,
                limit=20,
                include_window_completeness=False,
            )

    def test_the_permission_is_the_one_microsoft_documents(self) -> None:
        assert browser.GRAPH_PERMISSIONS == ("ChannelMessage.Read.All",)
