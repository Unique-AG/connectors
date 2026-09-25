import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import cast
from uuid import UUID

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphForbidden
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
        described = teams_search_messages.MessageHit.model_fields["uri"].description
        assert described is not None

        assert "teams_read_message" in described

    def test_the_summary_is_distinguished_from_the_full_message(self) -> None:
        described = teams_search_messages.MessageHit.model_fields["summary"].description
        assert described is not None

        assert "not the full message" in described


class TestWhatTheCallerIsTold:
    async def test_a_chat_hit_carries_a_chat_handle_and_a_channel_hit_a_channel_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
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
        assert found.messages[0].chat_id == "19:release@thread.v2"
        assert (found.messages[1].team_id, found.messages[1].channel_id) == (
            "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
            "19:general@thread.tacv2",
        )

    async def test_a_hit_with_neither_identity_is_kept_without_a_handle(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
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
        hit_count = teams_search_messages._HYDRATION_CONCURRENCY + 2  # pyright: ignore[reportPrivateUsage]
        hits = [chat_hit(message_id=f"177000000{index:04d}") for index in range(hit_count)]
        graph.post("/search/query").mock(
            return_value=httpx.Response(200, json=search_response(hits))
        )
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
