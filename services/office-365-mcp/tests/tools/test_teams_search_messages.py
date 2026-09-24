"""Tests for `teams_search_messages`: the query sent to Graph, and the traps in the
results."""

import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import cast
from uuid import UUID

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.messages import MAX_REPLIES_PER_POST
from office_365_mcp.tools import teams_search_messages
from office_365_mcp.tools.teams_search_messages import SearchCriteria

from .conftest import channel_hit, chat_hit, message_payload, reaction_payload, search_response

_MENTIONED = UUID("497b7a2a-9e1a-48d7-80e8-2965d2fc3a81")

_APPLICATION_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"


def _request(route: respx.Route) -> dict[str, object]:
    body = cast("dict[str, object]", json.loads(route.calls.last.request.content))
    requests = cast("list[dict[str, object]]", body["requests"])
    assert len(requests) == 1, "Graph honours only one searchRequest per call"
    return requests[0]


def _query_string(route: respx.Route) -> str:
    query = cast("dict[str, object]", _request(route)["query"])
    return cast("str", query["queryString"])


def _unquoted_words(query: str) -> list[str]:
    """This function splits the query on the `"` character and keeps the parts at even index
    numbers. Those parts hold only the words that are outside any quoted phrase, if the quotes
    are balanced. Every test that calls this function makes sure that the quotes are balanced
    first."""
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
        """Graph refuses to mix entity types. Message search also pages by `from` and `size`
        integers instead of a cursor, which lets a stateless tool resume a search."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([chat_hit()]))
        )

        _ = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=25, size=10
        )

        request = _request(route)
        assert request["entityTypes"] == ["chatMessage"]
        assert (request["from"], request["size"]) == (25, 10)
        assert "sortProperties" not in request, "Graph rejects sorting a chatMessage search"

    @pytest.mark.parametrize(
        "criteria",
        [
            SearchCriteria(query="release"),
            SearchCriteria(sender="ada", sent_after=date(2026, 1, 1)),
            SearchCriteria(
                query="release notes",
                sender="ada",
                recipient="alan",
                mentions=_MENTIONED,
                sent_after=date(2026, 1, 1),
                sent_before=date(2026, 1, 31),
                has_attachment=True,
                is_read=False,
                mentions_me=True,
            ),
        ],
    )
    async def test_it_costs_one_graph_request_whatever_it_was_asked(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        criteria: SearchCriteria,
    ) -> None:
        """Graph documents its read budget as "one request per second per app per tenant … on a
        given channel or chat." This budget is per app, not per user. A scan of one chat by a
        single user reduces the budget for every other user of the same app registration. Only a
        count of the calls shows whether a fan-out was added."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(
                200, json=search_response([chat_hit(), channel_hit()], more_results_available=True)
            )
        )

        _ = await teams_search_messages.teams_search_messages(
            client, criteria=criteria, offset=0, size=25
        )

        assert route.call_count == 1
        assert len(graph.calls) == 1, "and no request to any other Graph endpoint either"

    async def test_every_criterion_becomes_its_documented_scope_term(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The spellings come from Microsoft, with inconsistent casing. The `sent` term is a
        comparison, not a `term:value` pair like the others."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
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
        """The Microsoft example for the `mentions` term uses a user id "without '-'"."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(mentions=_MENTIONED), offset=0, size=25
        )

        assert _query_string(route) == "mentions:497b7a2a9e1a48d780e82965d2fc3a81"

    async def test_date_bounds_include_the_days_they_name(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The expression `sent>2026-01-01` drops every message sent on January 1. Graph gives no
        warning for this."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
            client,
            criteria=SearchCriteria(sent_after=date(2026, 1, 1), sent_before=date(2026, 1, 31)),
            offset=0,
            size=25,
        )

        assert _query_string(route) == "sent>=2026-01-01 sent<=2026-01-31"

    async def test_a_moment_bounds_the_second_rather_than_the_day(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """KQL documents `YYYY-MM-DDThh:mm:ssZ` as the literal form for a DateTime comparison. The
        `isoformat()` method of an aware moment writes `+00:00` instead, which is not one of the
        four forms that KQL documents."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
            client,
            criteria=SearchCriteria(
                sent_after=datetime(2026, 1, 1, 9, 30, tzinfo=UTC),
                sent_before=datetime(2026, 1, 1, 17, 0, tzinfo=UTC),
            ),
            offset=0,
            size=25,
        )

        assert _query_string(route) == "sent>=2026-01-01T09:30:00Z sent<=2026-01-01T17:00:00Z"

    async def test_a_moment_with_no_zone_is_read_as_utc_and_not_as_the_servers_own(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """This rule avoids the time zone of the pod that runs the code, because no caller chooses
        that zone and no answer names it."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
            client,
            criteria=SearchCriteria(sent_after=datetime(2026, 1, 1, 9, 30)),
            offset=0,
            size=25,
        )

        assert _query_string(route) == "sent>=2026-01-01T09:30:00Z"

    async def test_a_moment_east_of_utc_is_converted_rather_than_relabelled(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The code honors an offset that the caller wrote instead of dropping it. For example,
        09:30+02:00 becomes 07:30 UTC. Do not stamp `Z` on the wall-clock time instead: that
        method moves the bound by two hours."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
            client,
            criteria=SearchCriteria(
                sent_after=datetime(2026, 1, 1, 9, 30, tzinfo=timezone(timedelta(hours=2)))
            ),
            offset=0,
            size=25,
        )

        assert _query_string(route) == "sent>=2026-01-01T07:30:00Z"

    async def test_a_date_renders_exactly_as_it_always_has(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`datetime` is a subclass of `date`. A check in the wrong order renders every moment as
        the day that it falls on. This test makes sure that widening the type left the date form
        unchanged, which is the other half of that behavior.
        """
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
            client,
            criteria=SearchCriteria(sent_after=date(2026, 1, 1)),
            offset=0,
            size=25,
        )

        assert _query_string(route) == "sent>=2026-01-01"

    async def test_a_multi_word_query_reaches_graph_as_words_and_not_as_a_phrase(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Quoting the whole query turns it into an exact-adjacency phrase, which is the guard
        that a filter value needs. A phrase search for "cut the release" does not match "the
        release was cut". Bare, unquoted terms are what Graph combines with AND."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="cut the release"), offset=0, size=25
        )

        assert _query_string(route) == "cut the release"

    async def test_a_phrase_the_caller_quoted_themselves_stays_a_phrase(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
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
        """Free text reaches Microsoft as Keyword Query Language and can widen the search past
        every filter that the tool applied. The guard works one word at a time, so the assertion
        checks the structure of the query string. Nothing outside the quoted spans reads as
        anything but a keyword, and a bare keyword expresses no restriction, negation, or
        boolean."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
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
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release OR from:ceo"), offset=0, size=25
        )

        assert _query_string(route) == 'release "OR" "from:ceo"'

    async def test_a_sender_cannot_smuggle_one_either(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
            client,
            criteria=SearchCriteria(sender="ada OR IsRead:false"),
            offset=0,
            size=25,
        )

        assert _query_string(route) == 'from:"ada OR IsRead:false"'

    @pytest.mark.parametrize(
        ("sender", "expected"),
        [
            ("*", 'from:"*"'),
            ("ada*", 'from:"ada*"'),
            ("-ada", 'from:"-ada"'),
            ("ada@example.invalid", "from:ada@example.invalid"),
        ],
    )
    async def test_a_filter_value_is_quoted_only_where_kql_would_read_it_as_an_operator(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        sender: str,
        expected: str,
    ) -> None:
        """KQL reads `<property>:*` as a match on every item that has a value for that property, so
        `from:*` asks for every message with a sender, and no emptiness check trips on it. A
        leading `-` is quoted, because a NOT read into a filter value answers the opposite
        question. The last case must not change: quoting an ordinary address into a phrase alters
        every search that this tool already serves."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(sender=sender), offset=0, size=25
        )

        sent = _query_string(route)
        assert sent.count('"') % 2 == 0, f"the quoting is closable from inside: {sent}"
        assert sent == expected

    async def test_an_ordinary_value_is_left_as_a_keyword(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Quoting every value turns every search into a phrase search and loses stemming."""
        route = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([]))
        )

        _ = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release", sender="ada"), offset=0, size=25
        )

        assert _query_string(route) == "release from:ada"


class TestCriteriaThatAskForNothing:
    def test_an_empty_set_knows_it_is_empty(self) -> None:
        assert SearchCriteria().is_empty is True

    def test_free_text_with_no_word_in_it_asks_for_nothing(self) -> None:
        """The `is_empty` property depends on the query string, not on which arguments were
        passed."""
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
        """`false` is a criterion: only an unset value counts as absent."""
        assert criteria.is_empty is False

    async def test_searching_for_nothing_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await teams_search_messages.teams_search_messages(
                client, criteria=SearchCriteria(), offset=0, size=25
            )

    async def test_a_size_above_what_graph_documents_is_too(
        self, client: GraphServiceClient
    ) -> None:
        with pytest.raises(AssertionError):
            _ = await teams_search_messages.teams_search_messages(
                client,
                criteria=SearchCriteria(query="release"),
                offset=0,
                size=teams_search_messages.MAX_RESULTS + 1,
            )


class TestTheHandleItMints:
    def test_the_handle_names_the_reader_that_now_takes_it(self) -> None:
        """The absent phrases matter as much as the phrase that is present. A model that is told
        the snippet is all there is stops looking. Every other assertion about this tool passes
        either way."""
        described = teams_search_messages.MessageHit.model_fields["uri"].description
        assert described is not None

        assert "teams_read_message" in described
        assert "only route to the" in described and "attachments and the mentions" in described
        assert "no tool on this server takes it as an argument" not in described
        assert "no route from here to the message body" not in described

    def test_the_handle_says_include_body_reaches_the_same_wall_for_a_reply(self) -> None:
        described = teams_search_messages.MessageHit.model_fields["uri"].description
        assert described is not None

        assert "include_body" in described

    def test_the_summary_warns_against_inference_from_truncation(self) -> None:
        described = teams_search_messages.MessageHit.model_fields["summary"].description
        assert described is not None

        assert "Do not infer anything from its absence" in described

    def test_the_advice_for_a_reply_hit_stops_rather_than_pointing_back_at_browsing(self) -> None:
        """A hit on a channel reply carries the root-post shape, and Graph returns a 404 error for
        that shape. The `teams_browse_channel` function mints a handle for each reply, but it
        reaches only the newest replies of each post, and it does not follow any cursor past them.
        So "browse instead" is a good route for a recent reply, but it is a loop for an older
        one."""
        described = teams_search_messages.MessageHit.model_fields["uri"].description
        assert described is not None

        assert "teams_browse_channel" in described, (
            "the one tool that can, when the reply is recent"
        )
        assert f"just the newest {MAX_REPLIES_PER_POST} replies" in described, (
            "and where it stops, in the number the browser actually applies rather than in prose "
            + "of its own"
        )
        assert "no route to the full text" in described
        assert "A second browse of that channel returns the same window" in described
        assert "stop looking" in described


class TestWhatTheCallerIsTold:
    async def test_a_chat_hit_carries_a_chat_handle_and_a_channel_hit_a_channel_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The ids are percent-encoded because a Teams id contains the characters `:` and `@`. The
        question of which strings count as handles belongs to `shared/handles.py`, and
        `TestTheMessageHandleGrammar` in `tests/shared/test_handles.py` covers it."""
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

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        assert [message.uri for message in found.messages] == [
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000001",
            "teams:///teams/8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
            + "/channels/19%3Ageneral%40thread.tacv2/messages/1770000000002",
        ]
        # The code also returns the raw ids, not encoded, so a caller can match a hit with the
        # `chat_id` value that `teams_list_chats` reports. The caller does not need to decode the
        # handle to get that id back.
        assert found.messages[0].chat_id == "19:release@thread.v2"
        assert (found.messages[1].team_id, found.messages[1].channel_id) == (
            "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
            "19:general@thread.tacv2",
        )

    async def test_a_hit_with_neither_identity_is_kept_without_a_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph occasionally returns a hit with no `chatId` and no `channelIdentity`."""
        hit = chat_hit(chat_id=None)
        graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([hit]))
        )

        found = await teams_search_messages.teams_search_messages(
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

        found = await teams_search_messages.teams_search_messages(
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
        """Teams indexes messages from the substrate mailbox, so the `from` field of a hit is an
        Exchange `emailAddress` shape. The Graph SDK has no field for this shape."""
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

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        sender = found.messages[0].sender
        assert (sender.display_name, sender.email) == ("Ada Lovelace", "ada@example.invalid")
        assert sender.user_id is None, "the mailbox shape carries no directory id"

    async def test_a_teams_shaped_sender_is_understood_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
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

        found = await teams_search_messages.teams_search_messages(
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
                                    "id": _APPLICATION_ID,
                                    "displayName": "Build Notifier",
                                }
                            }
                        )
                    ]
                ),
            )
        )

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        sender = found.messages[0].sender
        assert sender.display_name == "Build Notifier"
        assert sender.application_id == _APPLICATION_ID
        assert sender.user_id is None, "an application id is not a user id"

    @pytest.mark.parametrize(
        "application",
        [
            {"id": _APPLICATION_ID, "displayName": None},
            {"id": _APPLICATION_ID, "displayName": ""},
            {"id": _APPLICATION_ID},
        ],
    )
    async def test_an_unnamed_application_keeps_its_id_and_its_hit(
        self,
        client: GraphServiceClient,
        graph: respx.MockRouter,
        application: dict[str, object],
    ) -> None:
        """Microsoft documents the `displayName` field of an application identity as optional, and
        the `id` field as required. So a bot with no name from Graph is still a bot that Graph
        identified."""
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                200, json=search_response([chat_hit(sender={"application": application})])
            )
        )

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        assert len(found.messages) == 1, "an application Graph named is a sender, named or not"
        sender = found.messages[0].sender
        assert sender.application_id == _APPLICATION_ID
        assert sender.display_name is None
        assert sender.user_id is None, "an application id is not a user id"

    @pytest.mark.parametrize(
        "sender",
        [
            pytest.param({}, id="no-identity-at-all"),
            pytest.param({"user": {}}, id="empty-user-object"),
            pytest.param({"application": {}}, id="empty-application-object"),
            pytest.param({"user": {"id": None, "displayName": None}}, id="user-naming-nobody"),
            pytest.param({"application": {"displayName": "   "}}, id="application-naming-nobody"),
        ],
    )
    async def test_an_identity_set_that_names_nobody_is_dropped(
        self, client: GraphServiceClient, graph: respx.MockRouter, sender: dict[str, object]
    ) -> None:
        """Graph can send an empty identity object. The presence of the object says nothing on its
        own. The content inside the object decides."""
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                200,
                json=search_response(
                    [chat_hit(sender=sender), chat_hit(message_id="1770000000009")]
                ),
            )
        )

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        assert [message.message_id for message in found.messages] == ["1770000000009"]

    async def test_system_event_messages_are_dropped(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """For these messages, Graph sends a null `from` field and a body with the literal text
        `<systemEventMessage/>`. The search projection does not return the `eventDetail` field
        that names the event."""
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

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        assert [message.message_id for message in found.messages] == ["1770000000002"]


class TestPagingAndItsHonesty:
    async def test_the_next_offset_drives_paging_and_total_is_ignored(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """For Teams messages, Microsoft documents the `total` field as the count of results on
        the page, not the number of matches."""
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

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=50, size=25
        )

        assert found.next_offset == 53, (
            "the offset is both the cursor and the whole 'there is more' signal: Graph said more "
            "results were available, so it is set"
        )
        assert "total" not in teams_search_messages.MessageSearchResults.model_fields
        assert "truncated" not in teams_search_messages.MessageSearchResults.model_fields, (
            "a flag saying what a non-null `next_offset` already says is a second thing to learn"
        )

    async def test_the_next_offset_counts_graphs_hits_not_the_messages_kept(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Do not advance `next_offset` by the number of messages kept instead of the number of
        hits from Graph. The filtering happens after Graph applies the offset, so that method
        re-reads the filtered-out hits without end."""
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

        found = await teams_search_messages.teams_search_messages(
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

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        assert found.next_offset is None

    async def test_a_search_that_matched_nothing_is_an_empty_page_not_a_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """For a search with no matches, Graph returns a container with no `hits` key at all."""
        graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response(None))
        )

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="nothing-matches-this"), offset=0, size=25
        )

        assert found.messages == []
        assert found.next_offset is None

    async def test_a_page_of_no_hits_never_offers_the_offset_it_was_asked_at(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`next_offset` advances past the hits that Graph returned. A page with no hits, with
        `moreResultsAvailable` still set, must not hand back the same offset that the caller asked
        for. This test asserts both directions, because an assertion of only one direction can
        stay wrong without a failure."""
        empty = graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([], more_results_available=True))
        )

        stalled = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=25, size=25
        )

        assert stalled.next_offset != 25, (
            "a `next_offset` equal to the offset just asked at is a loop, not a next page: the "
            "caller re-requests this same empty page for ever"
        )
        assert stalled.next_offset is None or stalled.next_offset > 25

        empty.mock(
            return_value=httpx.Response(
                200, json=search_response([chat_hit()], more_results_available=True)
            )
        )
        advanced = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=25, size=25
        )

        assert advanced.next_offset is not None and advanced.next_offset > 25


class TestGraphFailures:
    async def test_a_refused_search_surfaces_as_a_permission_failure(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden) as raised:
            _ = await teams_search_messages.teams_search_messages(
                client, criteria=SearchCriteria(query="release"), offset=0, size=25
            )

        assert raised.value.status == 403


_CHAT_MESSAGE_PATH = "/chats/19%3Arelease%40thread.v2/messages/1770000000000"
_CHANNEL_MESSAGE_PATH = (
    "/teams/8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81/channels/19%3Ageneral%40thread.tacv2"
    + "/messages/1770000000000"
)


class TestIncludeBody:
    async def test_left_off_by_default_costs_the_one_request_this_tool_promises(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([chat_hit()]))
        )

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25
        )

        assert len(graph.calls) == 1, "no hydration request without being asked for one"
        assert found.messages[0].text is None
        assert found.messages[0].reactions == []

    async def test_a_chat_hit_is_hydrated_from_the_same_endpoint_teams_read_message_uses(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([chat_hit()]))
        )
        read = graph.get(_CHAT_MESSAGE_PATH).mock(
            return_value=httpx.Response(
                200,
                json=message_payload(
                    content="cut the release on Friday",
                    content_type="text",
                    reactions=[reaction_payload(reaction_type="\U0001f44d")],
                ),
            )
        )

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25, include_body=True
        )

        assert read.called
        message = found.messages[0]
        assert message.text == "cut the release on Friday"
        assert [reaction.reaction_type for reaction in message.reactions] == ["\U0001f44d"]

    async def test_a_channel_hit_is_hydrated_too(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([channel_hit()]))
        )
        read = graph.get(_CHANNEL_MESSAGE_PATH).mock(
            return_value=httpx.Response(
                200, json=message_payload(content="the plan for Friday", content_type="text")
            )
        )

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25, include_body=True
        )

        assert read.called
        assert found.messages[0].text == "the plan for Friday"

    async def test_an_unaddressable_hit_is_never_fetched(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response([chat_hit(chat_id=None)]))
        )

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25, include_body=True
        )

        assert len(graph.calls) == 1, "a hit with no handle has nothing to hydrate from"
        assert found.messages[0].text is None

    async def test_a_hit_graph_refuses_to_hydrate_keeps_its_summary_and_the_rest_of_the_page(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """This is the shape that a search hit on a channel reply produces. Graph returns the same
        404 error for that handle that `teams_read_message` returns, and the refusal must not
        cost the whole page."""
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                200,
                json=search_response(
                    [
                        channel_hit(message_id="1770000000001"),
                        channel_hit(message_id="1770000000002"),
                    ]
                ),
            )
        )
        refused_path = (
            "/teams/8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81/channels/19%3Ageneral%40thread.tacv2"
            + "/messages/1770000000001"
        )
        answered_path = (
            "/teams/8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81/channels/19%3Ageneral%40thread.tacv2"
            + "/messages/1770000000002"
        )
        graph.get(refused_path).mock(
            return_value=httpx.Response(
                404, json={"error": {"code": "NotFound", "message": "Not Found"}}
            )
        )
        graph.get(answered_path).mock(
            return_value=httpx.Response(200, json=message_payload(message_id="1770000000002"))
        )

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25, include_body=True
        )

        refused, answered = found.messages
        assert refused.text is None and refused.reactions == []
        assert refused.summary is not None, "the snippet survives a hydration that could not"
        assert refused.uri is not None, "the handle survives too"
        assert answered.text is not None

    async def test_every_addressable_hit_on_the_page_is_hydrated(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Bounded concurrency must still reach every hit, not only the first
        `_HYDRATION_CONCURRENCY`."""
        hit_count = teams_search_messages._HYDRATION_CONCURRENCY + 2  # pyright: ignore[reportPrivateUsage]
        hits = [chat_hit(message_id=f"177000000{index:04d}") for index in range(hit_count)]
        graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response(hits))
        )
        # This test uses one catch-all route instead of a route for each id. Every hit reads a
        # different message id. The point of this test is that every hit gets fetched, not that
        # any particular path gets called.
        read = graph.route(method="GET").mock(
            return_value=httpx.Response(200, json=message_payload())
        )

        found = await teams_search_messages.teams_search_messages(
            client, criteria=SearchCriteria(query="release"), offset=0, size=25, include_body=True
        )

        assert read.call_count == hit_count
        assert all(message.text is not None for message in found.messages)

    async def test_a_refused_search_is_not_softened_by_include_body(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A refusal of the search itself differs from a refused hydration. The search found
        nothing to hydrate, so the function still raises the error."""
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        with pytest.raises(GraphForbidden):
            _ = await teams_search_messages.teams_search_messages(
                client,
                criteria=SearchCriteria(query="release"),
                offset=0,
                size=25,
                include_body=True,
            )
