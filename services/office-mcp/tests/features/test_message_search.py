"""`search_messages`' feature half: the query Graph is sent, and the traps in what comes back.

Every payload is synthesised from Microsoft's own documented shapes — the reduced search
projection, the Exchange-shaped sender a search hit carries, the authorless system event message.
Nothing here came from a tenant.
"""

import json
from datetime import date
from typing import cast
from uuid import UUID

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.features import message_search
from office_mcp.features.message_search import MessageHandle, SearchCriteria
from office_mcp.graph_client import GraphForbidden

from .conftest import channel_hit, chat_hit, search_response

_CHAT_ID = "19:release@thread.v2"
_MESSAGE_ID = "1770000000000"
_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"

_CHAT_URI = f"teams:///chats/19%3Arelease%40thread.v2/messages/{_MESSAGE_ID}"
_CHANNEL_URI = (
    f"teams:///teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages/{_MESSAGE_ID}"
)

_ROOT_ID = "1760000000000"
_REPLY_URI = (
    f"teams:///teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2"
    + f"/messages/{_ROOT_ID}/replies/{_MESSAGE_ID}"
)

_CHAT_HANDLE = MessageHandle(message_id=_MESSAGE_ID, chat_id=_CHAT_ID)
_CHANNEL_HANDLE = MessageHandle(message_id=_MESSAGE_ID, team_id=_TEAM_ID, channel_id=_CHANNEL_ID)
_REPLY_HANDLE = MessageHandle(
    message_id=_MESSAGE_ID, team_id=_TEAM_ID, channel_id=_CHANNEL_ID, reply_to_id=_ROOT_ID
)

_MENTIONED = UUID("497b7a2a-9e1a-48d7-80e8-2965d2fc3a81")


def _request(route: respx.Route) -> dict[str, object]:
    """The `searchRequest` the last call put on the wire."""
    body = cast("dict[str, object]", json.loads(route.calls.last.request.content))
    requests = cast("list[dict[str, object]]", body["requests"])
    assert len(requests) == 1, "Graph honours only one searchRequest per call"
    return requests[0]


def _query_string(route: respx.Route) -> str:
    query = cast("dict[str, object]", _request(route)["query"])
    return cast("str", query["queryString"])


def _unquoted_words(query: str) -> list[str]:
    """The words of `query` that a KQL parser would read outside any quoted phrase.

    Splitting on `"` and keeping the even-numbered pieces is exactly that, given a query whose
    quotes are balanced — which every test using this asserts first, because it is the property the
    quoting exists to hold.
    """
    return [
        word
        for index, part in enumerate(query.split('"'))
        if index % 2 == 0
        for word in part.split()
    ]


class TestTheQueryItSends:
    async def test_it_asks_only_for_chat_messages_and_pages_by_offset(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph refuses to mix entity types, and its message search pages by `from`/`size`
        integers rather than by a cursor — which is what lets a stateless tool resume a search."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([chat_hit()]))
        )

        _ = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release"), offset=25, size=10
        )

        request = _request(route)
        assert request["entityTypes"] == ["chatMessage"]
        assert (request["from"], request["size"]) == (25, 10)
        assert "sortProperties" not in request, "Graph rejects sorting a chatMessage search"

    async def test_every_criterion_becomes_its_documented_scope_term(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The spellings are Microsoft's, including the inconsistent casing and the fact that
        `sent` is a comparison rather than a `term:value` pair."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await message_search.search_messages(
            client,
            criteria=SearchCriteria(
                query="release",
                sender="ada",
                recipient="alan",
                mentions=_MENTIONED,
                sent_after=date(2026, 1, 1),
                sent_before=date(2026, 1, 31),
                has_attachment=True,
                is_read=False,
                mentions_me=True,
            ),
            offset=0,
            size=25,
        )

        assert _query_string(route) == (
            "release from:ada to:alan mentions:497b7a2a9e1a48d780e82965d2fc3a81 "
            + "sent>=2026-01-01 sent<=2026-01-31 hasAttachment:true IsRead:false IsMentioned:true"
        )

    async def test_the_mentioned_user_id_loses_its_hyphens(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft's `mentions` example is a user id "without '-'" — the one scope term whose
        value is not the value the caller supplied."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await message_search.search_messages(
            client, criteria=SearchCriteria(mentions=_MENTIONED), offset=0, size=25
        )

        assert _query_string(route) == "mentions:497b7a2a9e1a48d780e82965d2fc3a81"

    async def test_date_bounds_include_the_days_they_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`sent>2026-01-01` silently drops everything sent on the 1st, which is never what a
        caller asking for "since the 1st" meant."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await message_search.search_messages(
            client,
            criteria=SearchCriteria(sent_after=date(2026, 1, 1), sent_before=date(2026, 1, 31)),
            offset=0,
            size=25,
        )

        assert _query_string(route) == "sent>=2026-01-01 sent<=2026-01-31"

    async def test_a_multi_word_query_reaches_graph_as_words_and_not_as_a_phrase(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The recall this tool would otherwise lose silently. Quoting the whole query — the guard
        a *filter value* needs — makes it an exact-adjacency phrase, so "cut the release" would
        match only messages with those three words side by side and drop "the release was cut"
        entirely, while the parameter promises the words are matched as words. Bare terms are what
        Graph ANDs, so bare terms are what it is sent.
        """
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await message_search.search_messages(
            client, criteria=SearchCriteria(query="cut the release"), offset=0, size=25
        )

        assert _query_string(route) == "cut the release"

    async def test_a_phrase_the_caller_quoted_themselves_stays_a_phrase(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Adjacency is not unavailable, it is just not the default: a caller who wants it asks
        for it, and the words outside their quotes stay words."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await message_search.search_messages(
            client, criteria=SearchCriteria(query='friday "release notes"'), offset=0, size=25
        )

        assert _query_string(route) == 'friday "release notes"'

    @pytest.mark.parametrize(
        "injection",
        [
            "sent>2020-01-01",
            "from:ceo@example.invalid",
            "release OR from:ceo",
            'release" OR IsRead:false OR "',
            "(release)",
            "IsMentioned:true",
            "release NOT IsRead:false",
            "-release",
            "rele*",
            'release" NOT "',
        ],
    )
    async def test_a_caller_cannot_smuggle_kql_through_the_free_text(
        self, client: GraphServiceClient, graph: respx.MockRouter, injection: str
    ) -> None:
        """`query` is words, and the filters a caller may set are exactly the parameters this tool
        declares. Without this guard, free text reaches Microsoft as Keyword Query Language and can
        widen the search past every filter the tool applied.

        The guard now works a word at a time rather than over the whole query, so the assertion is
        about the query string's *structure*: outside the quoted spans there is nothing a KQL parser
        would read as anything but a keyword. A word with no operator character, no wildcard, no
        leading `-` and no operator spelling is the only thing left bare, and such a word cannot
        express a restriction, a negation or a boolean.
        """
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await message_search.search_messages(
            client, criteria=SearchCriteria(query=injection), offset=0, size=25
        )

        sent = _query_string(route)
        assert sent.count('"') % 2 == 0, f"the quoting is closable from inside: {sent}"
        for word in _unquoted_words(sent):
            assert not set(word) & set(':"<>=()*'), f"operator left bare in {sent}: {word}"
            assert not word.startswith("-"), f"negation left bare in {sent}: {word}"
            assert word not in {"AND", "OR", "NOT", "NEAR", "ONEAR"}, (
                f"boolean left bare in {sent}: {word}"
            )

    async def test_the_words_of_an_injection_attempt_are_still_searched_for(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Neutralising is not dropping: the caller typed those characters, so they are looked for
        as text. A guard that silently discarded them would answer a different question."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release OR from:ceo"), offset=0, size=25
        )

        assert _query_string(route) == 'release "OR" "from:ceo"'

    async def test_a_sender_cannot_smuggle_one_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await message_search.search_messages(
            client,
            criteria=SearchCriteria(sender="ada OR IsRead:false"),
            offset=0,
            size=25,
        )

        assert _query_string(route) == 'from:"ada OR IsRead:false"'

    async def test_an_ordinary_value_is_left_as_a_keyword(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Quoting everything would turn every search into a phrase search and lose stemming, so
        only values that could be read as operators are quoted."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release", sender="ada"), offset=0, size=25
        )

        assert _query_string(route) == "release from:ada"


class TestCriteriaThatAskForNothing:
    def test_an_empty_set_knows_it_is_empty(self) -> None:
        assert SearchCriteria().is_empty is True

    def test_free_text_with_no_word_in_it_asks_for_nothing(self) -> None:
        """`is_empty` is measured on the query string, not on which arguments were passed, so a
        query that leaves nothing to look for is refused by the boundary that refuses no criteria
        at all — rather than reaching Graph as a search for everything."""
        assert SearchCriteria(query='" "').is_empty is True

    @pytest.mark.parametrize(
        "criteria",
        [
            SearchCriteria(query="release"),
            SearchCriteria(sender="ada"),
            SearchCriteria(recipient="alan"),
            SearchCriteria(mentions=_MENTIONED),
            SearchCriteria(sent_after=date(2026, 1, 1)),
            SearchCriteria(sent_before=date(2026, 1, 31)),
            SearchCriteria(has_attachment=False),
            SearchCriteria(is_read=False),
            SearchCriteria(mentions_me=False),
        ],
    )
    def test_any_single_criterion_is_enough(self, criteria: SearchCriteria) -> None:
        """`false` is a criterion — "unread messages" and "messages without attachments" are real
        questions, so only an unset value counts as absent."""
        assert criteria.is_empty is False

    async def test_searching_for_nothing_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        """The tool refuses it at the boundary, so reaching the feature with it means the
        boundary was bypassed."""
        with pytest.raises(AssertionError):
            _ = await message_search.search_messages(
                client, criteria=SearchCriteria(), offset=0, size=25
            )

    async def test_a_size_above_what_graph_documents_is_too(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await message_search.search_messages(
                client,
                criteria=SearchCriteria(query="release"),
                offset=0,
                size=message_search.MAX_RESULTS + 1,
            )


class TestTheHandleItMints:
    def test_it_reads_the_two_shapes_search_emits_and_decodes_their_ids(self) -> None:
        """A handle is this module's contract with `read_message`, which is why the shape and its
        parser live here: the ids in it are percent-encoded because a Teams id is full of `:` and
        `@`, so reading one back means decoding them."""
        chat = message_search.message_handle(_CHAT_URI)
        channel = message_search.message_handle(_CHANNEL_URI)

        assert chat == _CHAT_HANDLE
        assert channel == _CHANNEL_HANDLE

    def test_it_reads_the_reply_shape_that_only_browsing_a_channel_can_mint(self) -> None:
        """The third shape. Graph addresses a reply in a channel thread under the post it answers,
        and the search projection carries no `replyToId` — so a search hit on a reply becomes the
        root-post shape and cannot be read, while `channels.browse_channel` walks a channel post by
        post and knows each reply's parent. The grammar still lives here, with the other two: two
        modules that each knew how to write a handle would be free to disagree.
        """
        reply = message_search.message_handle(_REPLY_URI)

        assert reply == _REPLY_HANDLE
        assert reply is not None and reply.uri == _REPLY_URI

    def test_the_advice_for_a_reply_hit_stops_rather_than_pointing_back_at_browsing(self) -> None:
        """A hit that is really a channel reply carries the root-post shape, which Graph answers 404
        to — and the advice for that has to end somewhere. `channels.browse_channel` mints a reply's
        own handle but reaches only the newest replies of each post on a channel's first page and
        follows no cursor past them, so "browse the channel instead" is a route for a recent reply
        and a loop for an older one: browse, not find it, read the same advice, browse again. So the
        window is named and the terminus is stated here, where the handle that can fail is minted.
        """
        described = message_search.MessageHit.model_fields["uri"].description
        assert described is not None

        assert "browse_channel" in described, "the one tool that can, when the reply is recent"
        assert "only the newest replies" in described, "and where it stops"
        assert "no route to its full text" in described
        assert "browsing again returns the same window" in described
        assert "stop looking" in described

    def test_a_handle_survives_the_round_trip_it_came_from(self) -> None:
        chat = message_search.message_handle(_CHAT_URI)
        channel = message_search.message_handle(_CHANNEL_URI)

        assert chat is not None and chat.uri == _CHAT_URI
        assert channel is not None and channel.uri == _CHANNEL_URI

    def test_an_unencoded_id_still_resolves(self) -> None:
        """A caller that copied a handle out of a log rather than out of a response has ids that
        were never encoded; `:` and `@` are unambiguous in a path segment, so those are read too."""
        handle = message_search.message_handle(f"teams:///chats/{_CHAT_ID}/messages/{_MESSAGE_ID}")

        assert handle == _CHAT_HANDLE

    def test_it_says_which_permission_each_shape_is_read_under(self) -> None:
        """Graph's permissions for a message read are per surface and the handle is the only
        thing that knows which surface, so a 403 on a chat read can only be about `Chat.Read` —
        naming the channel permission alongside it would send an administrator after one that was
        never missing."""
        assert _CHAT_HANDLE.permission == "Chat.Read"
        assert _CHANNEL_HANDLE.permission == "ChannelMessage.Read.All"
        assert _REPLY_HANDLE.permission == "ChannelMessage.Read.All"

    @pytest.mark.parametrize(
        "uri",
        [
            # The schemes a polymorphic reader would advertise and this connector cannot serve.
            "mail:///messages/AAMkAGI2",
            "calendar:///events/AAMkAGI2",
            "drive:///items/01ABC",
            "site:///sites/contoso/pages/1",
            # Right scheme, wrong shape.
            "teams:///chats/19%3Arelease%40thread.v2",
            "teams:///messages/1770000000000",
            "teams:///chats//messages/1770000000000",
            "teams:///chats/19%3Arelease%40thread.v2/messages/",
            # A chat has no replies in Graph's addressing — only a channel thread does.
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000/replies/1770000000001",
            "teams:///teams/8a9c3c47/channels/19%3Ageneral/messages/1770000000000/replies/",
            "teams:///teams/8a9c3c47/channels/19%3Ageneral/messages//replies/1770000000001",
            "teams:///teams/8a9c3c47/messages/1770000000000",
            "teams:///chats/19%3Arelease%40thread.v2/messages/%20",
            # A Teams web link, which is what a model reaches for when it has no handle.
            "https://teams.microsoft.com/l/message/19%3Ageneral/1770000000000",
            "1770000000000",
            "",
        ],
    )
    def test_it_refuses_everything_else(self, uri: str) -> None:
        assert message_search.message_handle(uri) is None


class TestWhatTheCallerIsTold:
    async def test_a_chat_hit_carries_a_chat_handle_and_a_channel_hit_a_channel_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The handle is the whole route to the message text, since the search projection has no
        body — and the ids in it are percent-encoded because a Teams id is full of `:` and `@`."""
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                200,
                json=search_response(
                    [
                        chat_hit(chat_id="19:release@thread.v2", message_id="1770000000001"),
                        channel_hit(
                            team_id="8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
                            channel_id="19:general@thread.tacv2",
                            message_id="1770000000002",
                        ),
                    ]
                ),
            )
        )

        found = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        assert [message.uri for message in found.messages] == [
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000001",
            "teams:///teams/8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
            + "/channels/19%3Ageneral%40thread.tacv2/messages/1770000000002",
        ]
        # The raw ids are returned alongside, unencoded, so a hit can be lined up with the
        # `chat_id` list_chats reports without anyone unpicking the handle to get one back.
        assert found.messages[0].chat_id == "19:release@thread.v2"
        assert (found.messages[1].team_id, found.messages[1].channel_id) == (
            "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
            "19:general@thread.tacv2",
        )

    async def test_a_hit_with_neither_identity_is_kept_without_a_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph does occasionally return a hit with no chatId and no channelIdentity. Its snippet
        is still an answer, so it is reported — with a null `uri` saying it cannot be read in
        full, rather than being dropped or given a handle that would 404."""
        hit = chat_hit(chat_id=None)
        graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([hit]))
        )

        found = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        assert len(found.messages) == 1
        assert found.messages[0].uri is None
        assert found.messages[0].summary is not None

    async def test_the_snippet_and_the_metadata_come_through(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                200,
                json=search_response(
                    [chat_hit(summary="...cut the <c0>release</c0> on Friday...")]
                ),
            )
        )

        found = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        message = found.messages[0]
        assert message.summary == "...cut the <c0>release</c0> on Friday..."
        assert message.importance == "normal"
        assert message.created_at is not None and message.created_at.year == 2026
        assert message.last_modified_at is not None

    async def test_a_search_hits_mailbox_shaped_sender_is_understood(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Teams messages are indexed out of the substrate mailbox, so a hit's `from` is an
        Exchange `emailAddress` — a shape the Graph SDK has no field for, and one the Teams read
        APIs never return."""
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                200,
                json=search_response(
                    [
                        chat_hit(
                            sender={
                                "emailAddress": {
                                    "name": "Ada Lovelace",
                                    "address": "ada@example.invalid",
                                }
                            }
                        )
                    ]
                ),
            )
        )

        found = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        sender = found.messages[0].sender
        assert (sender.display_name, sender.email) == ("Ada Lovelace", "ada@example.invalid")
        assert sender.user_id is None, "the mailbox shape carries no directory id"

    async def test_a_teams_shaped_sender_is_understood_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The other branch: `teamworkUserIdentity` has an id and no email at all, and Microsoft
        documents its display name as optional — a null there is not an anonymous sender."""
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                200,
                json=search_response(
                    [
                        chat_hit(
                            sender={
                                "user": {
                                    "@odata.type": "#microsoft.graph.teamworkUserIdentity",
                                    "id": "00000000-0000-4000-8000-000000000001",
                                    "displayName": None,
                                    "userIdentityType": "aadUser",
                                }
                            }
                        )
                    ]
                ),
            )
        )

        found = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        sender = found.messages[0].sender
        assert sender.user_id == "00000000-0000-4000-8000-000000000001"
        assert (sender.display_name, sender.email) == (None, None)

    async def test_a_bot_is_named_by_its_application_identity(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                200,
                json=search_response(
                    [
                        chat_hit(
                            sender={
                                "application": {
                                    "id": "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061",
                                    "displayName": "Build Notifier",
                                }
                            }
                        )
                    ]
                ),
            )
        )

        found = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        sender = found.messages[0].sender
        assert sender.display_name == "Build Notifier"
        assert sender.user_id is None, "an application id is not a user id"

    async def test_system_event_messages_are_dropped(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A message nobody wrote is not a search result: for "Ada joined the chat" Graph sends a
        null `from` and a body of the literal `<systemEventMessage/>`, rendering the sentence in
        the Teams client
        from `eventDetail` — which the search projection does not even return. Left in, these are
        results with no author and no text, and a model summarising a page of them reports
        membership churn as the conversation.
        """
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                200,
                json=search_response(
                    [
                        chat_hit(message_id="1770000000001", sender=None),
                        chat_hit(message_id="1770000000002"),
                    ]
                ),
            )
        )

        found = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        assert [message.message_id for message in found.messages] == ["1770000000002"]


class TestPagingAndItsHonesty:
    async def test_the_next_offset_drives_paging_and_total_is_ignored(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Microsoft documents `total` as the count of results on the page for Teams messages, not
        the number of matches — so a tool that reports it tells a model there were 25 matches when
        there may be thousands. Nothing here reads it."""
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                200,
                json=search_response(
                    [chat_hit(message_id=f"177000000000{index}") for index in range(3)],
                    total=3,
                    more_results_available=True,
                ),
            )
        )

        found = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release"), offset=50, size=25
        )

        assert found.next_offset == 53, (
            "the offset is both the cursor and the whole 'there is more' signal: Graph said more "
            "results were available, so it is set"
        )
        assert "total" not in message_search.MessageSearchResults.model_fields
        assert "truncated" not in message_search.MessageSearchResults.model_fields, (
            "a flag saying what a non-null `next_offset` already says is a second thing to learn"
        )

    async def test_the_next_offset_counts_graphs_hits_not_the_messages_kept(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The filtering happens on our side of the offset. Advancing by the number of messages
        returned would re-read the hits that were filtered out, forever."""
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                200,
                json=search_response(
                    [
                        chat_hit(message_id="1770000000001", sender=None),
                        chat_hit(message_id="1770000000002", sender=None),
                        chat_hit(message_id="1770000000003"),
                    ],
                    more_results_available=True,
                ),
            )
        )

        found = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        assert len(found.messages) == 1
        assert found.next_offset == 3

    async def test_the_last_page_offers_no_next_offset(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                200, json=search_response([chat_hit()], more_results_available=False)
            )
        )

        found = await message_search.search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        assert found.next_offset is None

    async def test_a_search_that_matched_nothing_is_an_empty_page_not_a_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph answers a no-match search with a container holding no `hits` key at all."""
        graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response(None))
        )

        found = await message_search.search_messages(
            client, criteria=SearchCriteria(query="nothing-matches-this"), offset=0, size=25
        )

        assert found.messages == []
        assert found.next_offset is None


class TestGraphFailures:
    async def test_a_refused_search_surfaces_as_a_permission_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The case the per-chat scan this tool deliberately does not have would have hidden: a
        tenant that has not granted the search permissions must be told, not worked around."""
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden) as raised:
            _ = await message_search.search_messages(
                client, criteria=SearchCriteria(query="release"), offset=0, size=25
            )

        assert raised.value.status == 403
