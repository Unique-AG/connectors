"""`list_chats`' feature half: the query Graph is sent, and the traps in what comes back."""

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.features import chats
from office_mcp.graph_client import GraphThrottled

from .conftest import GRAPH_V1, aad_member, chat_payload

_GUEST_MEMBER = "#microsoft.graph.anonymousGuestConversationMember"


class TestTheQueryItSends:
    async def test_it_asks_graph_for_recency_ordering_and_both_expansions(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The three query parameters this tool's contract rests on.

        Dropping `$orderby` silently returns *some* chats instead of the recent ones, and dropping
        an expansion silently empties `members` or `last_message_at` — all three failures look
        like a working tool.
        """
        route = graph.get("/me/chats").mock(
            return_value=httpx.Response(200, json={"value": [chat_payload("19:a@thread.v2")]})
        )

        _ = await chats.list_recent_chats(client, limit=7, include_member_emails=False)

        params = route.calls.last.request.url.params
        assert params["$orderby"] == "lastMessagePreview/createdDateTime desc"
        assert params["$expand"] == "members,lastMessagePreview"
        assert params["$top"] == "7"
        assert "$select" not in params, "$select is rejected on this collection"

    async def test_a_limit_above_graphs_ceiling_is_a_programming_error(
        self, client: GraphServiceClient
    ) -> None:
        """The tool's schema bounds `limit` at Graph's own maximum, so a larger value can only
        arrive from code that bypassed it."""
        with pytest.raises(AssertionError):
            _ = await chats.list_recent_chats(
                client, limit=chats.MAX_CHATS + 1, include_member_emails=False
            )


class TestWhatTheCallerIsTold:
    async def test_the_sort_key_is_in_the_payload(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The oracle connector sorts by last-message time but returns `lastUpdatedDateTime`, so
        its list looks unsorted. `last_message_at` is the value the order is by."""
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        chat_payload("19:a@thread.v2", last_message_at="2026-02-11T09:15:22.31Z"),
                        chat_payload("19:b@thread.v2", last_message_at=None),
                    ]
                },
            )
        )

        listed = await chats.list_recent_chats(client, limit=25, include_member_emails=False)

        assert [chat.chat_id for chat in listed.chats] == ["19:a@thread.v2", "19:b@thread.v2"]
        first = listed.chats[0].last_message_at
        assert first is not None and first.year == 2026
        assert listed.chats[1].last_message_at is None, (
            "a chat nobody posted in has no last message"
        )

    async def test_members_identify_the_chats_that_have_no_topic(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        chat_payload("19:named@thread.v2", topic="Release planning"),
                        chat_payload(
                            "19:unnamed@unq.gbl.spaces",
                            chat_type="oneOnOne",
                            topic=None,
                            members=[aad_member("Ada Lovelace"), aad_member("Alan Turing")],
                        ),
                    ]
                },
            )
        )

        listed = await chats.list_recent_chats(client, limit=25, include_member_emails=False)

        assert listed.chats[0].members is None, "a named chat needs no roster to be identified"
        unnamed = listed.chats[1].members
        assert unnamed is not None
        assert [member.display_name for member in unnamed] == ["Ada Lovelace", "Alan Turing"]
        assert [member.email for member in unnamed] == [None, None], "emails are opt-in"

    async def test_emails_are_returned_only_when_asked_for(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        chat_payload(
                            "19:unnamed@unq.gbl.spaces",
                            topic=None,
                            members=[
                                aad_member("Ada Lovelace", email="ada@example.invalid"),
                                # A meeting room joins as a different member subtype, with no
                                # email to disambiguate it by.
                                {
                                    "@odata.type": _GUEST_MEMBER,
                                    "id": "member-room",
                                    "displayName": "Room 3",
                                },
                            ],
                        )
                    ]
                },
            )
        )

        listed = await chats.list_recent_chats(client, limit=25, include_member_emails=True)

        members = listed.chats[0].members
        assert members is not None
        assert [(m.display_name, m.email) for m in members] == [
            ("Ada Lovelace", "ada@example.invalid"),
            ("Room 3", None),
        ]

    async def test_graphs_silent_member_cap_is_reported(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph returns at most 25 members per chat on this endpoint and says nothing about it,
        so a model summarising "who is in this chat" from the list is wrong without a flag."""
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        chat_payload(
                            "19:crowded@thread.v2",
                            topic=None,
                            members=[
                                aad_member(f"Person {index}")
                                for index in range(chats.MEMBERS_PER_CHAT)
                            ],
                        ),
                        chat_payload(
                            "19:quiet@thread.v2", topic=None, members=[aad_member("Ada Lovelace")]
                        ),
                    ]
                },
            )
        )

        listed = await chats.list_recent_chats(client, limit=25, include_member_emails=False)

        assert listed.chats[0].members_truncated is True
        assert listed.chats[1].members_truncated is False

    async def test_an_unknown_chat_type_does_not_fail_the_listing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={"value": [chat_payload("19:future@thread.v2", chat_type="meeting")]},
            )
        )

        listed = await chats.list_recent_chats(client, limit=25, include_member_emails=False)

        assert listed.chats[0].chat_type == "meeting"


class TestTheWindowAndItsHonesty:
    async def test_a_short_first_page_is_followed_rather_than_believed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph documents that `$top` "might not return all chats within a single response" — so
        a page shorter than `limit` with a next link is a paging artefact, not the end of the
        collection. Believing it truncates the window for no reason."""
        # Registered before the unconstrained route below, which would otherwise also match the
        # second request and hand back page one again.
        graph.get("/me/chats", params={"$skiptoken": "synthetic"}).mock(
            return_value=httpx.Response(200, json={"value": [chat_payload("19:b@thread.v2")]})
        )
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [chat_payload("19:a@thread.v2")],
                    "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=synthetic",
                },
            )
        )

        listed = await chats.list_recent_chats(client, limit=25, include_member_emails=False)

        assert [chat.chat_id for chat in listed.chats] == ["19:a@thread.v2", "19:b@thread.v2"]
        assert listed.truncated is False, "the walk reached the end of the collection"

    async def test_a_full_window_with_more_behind_it_says_so(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [chat_payload(f"19:{index}@thread.v2") for index in range(2)],
                    "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=synthetic",
                },
            )
        )

        listed = await chats.list_recent_chats(client, limit=2, include_member_emails=False)

        assert len(listed.chats) == 2
        assert listed.truncated is True


class TestGraphFailures:
    async def test_throttling_carries_graphs_own_retry_after(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`Retry-After: 900` exceeds the SDK retry handler's 180 s ceiling, so it declines to
        wait and the failure reaches the caller — which is the only case a tool has to explain."""
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                429,
                headers={"Retry-After": "900"},
                json={"error": {"code": "activityLimitReached", "message": "slow down"}},
            )
        )

        with pytest.raises(GraphThrottled) as raised:
            _ = await chats.list_recent_chats(client, limit=25, include_member_emails=False)

        assert raised.value.retry_after_seconds == 900
