"""`list_chats`: the query Graph is sent, and the traps in what comes back."""

from collections.abc import Mapping, Sequence

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphThrottled
from office_365_mcp.shared import handles
from office_365_mcp.tools import list_chats as chats

from .conftest import GRAPH_V1

_GUEST_MEMBER = "#microsoft.graph.anonymousGuestConversationMember"


def aad_member(display_name: str, *, email: str | None = None) -> dict[str, object]:
    return {
        "@odata.type": "#microsoft.graph.aadUserConversationMember",
        "id": f"member-{display_name.replace(' ', '-').lower()}",
        "displayName": display_name,
        "email": email or f"{display_name.split()[0].lower()}@example.invalid",
    }


def chat_payload(
    chat_id: str,
    *,
    chat_type: str = "group",
    topic: str | None = "Release planning",
    last_message_at: str | None = "2026-02-11T09:15:22.31Z",
    members: Sequence[Mapping[str, object]] | None = None,
    online_meeting_info: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """`onlineMeetingInfo` is in this collection's default projection and null for every chat that
    is not a meeting's, so it is always present and only sometimes populated."""
    payload: dict[str, object] = {
        "id": chat_id,
        "chatType": chat_type,
        "topic": topic,
        "createdDateTime": "2026-01-04T12:00:00Z",
        "lastUpdatedDateTime": "2026-02-11T09:15:22.31Z",
        "onlineMeetingInfo": dict(online_meeting_info) if online_meeting_info is not None else None,
        "members": list(members) if members is not None else [aad_member("Ada Lovelace")],
    }
    if last_message_at is not None:
        payload["lastMessagePreview"] = {
            "id": "1770000000000",
            "createdDateTime": last_message_at,
            "body": {"contentType": "text", "content": "synthetic preview"},
        }
    return payload


# Already percent-escaped `%3a` and `%40`, a `?context=` value holding `%7b` and `%22`, and an `&`
# after it: everything the handle a meeting chat carries has to survive.
JOIN_WEB_URL = (
    "https://teams.microsoft.invalid/l/meetup-join/"
    + "19%3ameeting_TjAwMDAwMDAwMDAwMA%40thread.v2/0"
    + "?context=%7b%22Tid%22%3a%228a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81%22%7d&anon=true"
)


def online_meeting_info(join_web_url: str | None = JOIN_WEB_URL) -> dict[str, object]:
    """`joinWebUrl` is the only documented route from a chat to its meeting, and no live call has
    proved it is always populated."""
    return {
        "calendarEventId": "AAMkAGSYNTHETIC",
        "joinWebUrl": join_web_url,
        "organizer": {
            "user": {
                "@odata.type": "#microsoft.graph.teamworkUserIdentity",
                "id": "00000000-0000-4000-8000-000000000002",
                "displayName": "Grace Hopper",
            }
        },
    }


class TestTheQueryItSends:
    async def test_it_asks_graph_for_recency_ordering_and_both_expansions(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Dropping `$orderby` returns *some* chats instead of the recent ones, and dropping an
        expansion empties `members` or `last_message_at`. All three look like a working tool."""
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
        with pytest.raises(AssertionError):
            _ = await chats.list_recent_chats(
                client, limit=chats.MAX_CHATS + 1, include_member_emails=False
            )


class TestWhatTheCallerIsTold:
    async def test_the_sort_key_is_in_the_payload(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`lastUpdatedDateTime` is also in the payload and is not what the order is by."""
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

    async def test_a_blank_topic_is_reported_as_no_topic_and_gets_a_roster(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """kiota reads a string as a string, so `""` reaches the tool intact: a name to the roster
        test and no name to the reader, leaving nothing but a thread id to identify the chat."""
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        chat_payload(
                            "19:empty@thread.v2", topic="", members=[aad_member("Ada Lovelace")]
                        ),
                        chat_payload(
                            "19:spaces@thread.v2", topic="   ", members=[aad_member("Alan Turing")]
                        ),
                    ]
                },
            )
        )

        listed = await chats.list_recent_chats(client, limit=25, include_member_emails=False)

        assert [chat.topic for chat in listed.chats] == [None, None]
        rosters = [chat.members for chat in listed.chats]
        assert all(roster is not None for roster in rosters), (
            "a chat with no usable topic is identified by who is in it"
        )
        assert [[member.display_name for member in roster or []] for roster in rosters] == [
            ["Ada Lovelace"],
            ["Alan Turing"],
        ]

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
                                # A room joins as a different member subtype, with no email.
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

    async def test_a_member_list_full_to_graphs_cap_is_flagged_as_possibly_incomplete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph returns at most 25 members per chat here and says nothing about it. The crowded
        chat below holds exactly the cap, whose response is byte-for-byte what a 200-person chat
        would send, so 25-of-25 and 25-of-200 have to be flagged alike."""
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

        crowded = listed.chats[0].members
        assert crowded is not None and len(crowded) == chats.MEMBERS_PER_CHAT
        assert listed.chats[0].members_may_be_incomplete is True
        assert listed.chats[1].members_may_be_incomplete is False

    def test_the_cap_flag_claims_only_what_graph_actually_reveals(self) -> None:
        description = chats.ChatSummary.model_fields["members_may_be_incomplete"].description

        assert description is not None
        assert f"reached Graph's cap of {chats.MEMBERS_PER_CHAT}" in description
        assert (
            f"exactly {chats.MEMBERS_PER_CHAT} members is indistinguishable from one with more"
            in description
        ), "reaching the cap is not proof that members are missing, and the flag must say so"

    async def test_a_meeting_chat_carries_the_route_to_its_transcripts(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        chat_payload(
                            "19:meeting_TjAwMDA@thread.v2",
                            chat_type="meeting",
                            topic="Pricing review",
                            online_meeting_info=online_meeting_info(),
                        ),
                        chat_payload("19:release@thread.v2", chat_type="group"),
                    ]
                },
            )
        )

        listed = await chats.list_recent_chats(client, limit=25, include_member_emails=False)

        meeting_uri = listed.chats[0].meeting_uri
        assert meeting_uri is not None
        assert handles.meeting_handle(meeting_uri) == handles.MeetingHandle(JOIN_WEB_URL)
        assert listed.chats[1].meeting_uri is None, "a group chat has no meeting behind it"

    async def test_a_meeting_chat_with_no_join_url_offers_no_route_rather_than_a_broken_one(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [
                        chat_payload(
                            "19:meeting_TjAwMDA@thread.v2",
                            chat_type="meeting",
                            topic="Pricing review",
                            online_meeting_info=online_meeting_info(join_web_url=None),
                        )
                    ]
                },
            )
        )

        listed = await chats.list_recent_chats(client, limit=25, include_member_emails=False)

        assert listed.chats[0].chat_type == "meeting"
        assert listed.chats[0].meeting_uri is None

    def test_the_handle_field_says_a_null_is_a_dead_end(self) -> None:
        description = chats.ChatSummary.model_fields["meeting_uri"].description

        assert description is not None
        assert "Null when no join URL exists" in description
        assert "The only route from conversation to meeting" in description, (
            "the populated case says what it is a route to, and its being the only one is what "
            + "makes a null a dead end rather than an invitation to try something else"
        )

    def test_the_chat_id_field_forbids_building_a_handle_rather_than_explaining_how(self) -> None:
        """The wording is the whole guardrail: `handles.message_handle` matches an unencoded
        `19:...@thread.v2`, so a hand-built handle parses and reaches Graph."""
        description = chats.ChatSummary.model_fields["chat_id"].description

        assert description is not None
        assert "cannot be assembled into one" in description
        assert "message_id" not in description, (
            "naming what a handle is missing is a recipe for assembling one, and this tool has no "
            + "message id to hand a model that follows it"
        )
        assert "teams_read_message" in description, (
            "a model told not to build a handle still needs to know where a real one comes from"
        )

    async def test_an_unknown_chat_type_does_not_fail_the_listing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A value the SDK's generated enum has no member for deserializes to `None`, not raises."""
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={"value": [chat_payload("19:future@thread.v2", chat_type="sharedChannel")]},
            )
        )

        listed = await chats.list_recent_chats(client, limit=25, include_member_emails=False)

        assert listed.chats[0].chat_type == "unknown"


class TestTheWindowAndItsHonesty:
    async def test_a_short_first_page_is_followed_rather_than_believed(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph documents that `$top` "might not return all chats within a single response"."""
        # Registered before the unconstrained route below, which would match page two as well.
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
        assert len(listed.chats) < 25, (
            "the walk reached the end of the collection, and a window short of `limit` is how that "
            "is reported now that there is no flag saying it"
        )

    async def test_an_empty_page_in_the_middle_does_not_end_the_window(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph sends the occasional empty page with a cursor still set, and the SDK's own page
        walker treats one as the end of the collection."""
        graph.get("/me/chats", params={"$skiptoken": "third"}).mock(
            return_value=httpx.Response(200, json={"value": [chat_payload("19:c@thread.v2")]})
        )
        graph.get("/me/chats", params={"$skiptoken": "second"}).mock(
            return_value=httpx.Response(
                200,
                json={"value": [], "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=third"},
            )
        )
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [chat_payload("19:a@thread.v2")],
                    "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=second",
                },
            )
        )

        listed = await chats.list_recent_chats(client, limit=25, include_member_emails=False)

        assert [chat.chat_id for chat in listed.chats] == ["19:a@thread.v2", "19:c@thread.v2"]

    async def test_a_full_window_is_all_a_full_window_promises(
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

        assert len(listed.chats) == 2, (
            "a window filled to `limit` is the whole of what a caller is told: Graph had a next "
            "link here, and the second page is not fetched to be discarded"
        )
        assert len(graph.calls) == 1


class TestGraphFailures:
    async def test_throttling_carries_graphs_own_retry_after(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """`Retry-After: 900` exceeds the SDK retry handler's 180 s ceiling, so it declines to
        wait and the failure reaches the caller."""
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
