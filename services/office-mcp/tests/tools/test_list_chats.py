"""`list_chats`: the query Graph is sent, and the traps in what comes back.

The chat payloads are built here rather than in the package conftest because they are this tool's
own — a chat, its expanded members and the `onlineMeetingInfo` a meeting chat carries are what
`list_chats` reads and what nothing else reads. Every one of them is invented: the ids are obviously
fake, the domains are `.invalid`, and the names are from the public domain.
"""

from collections.abc import Mapping, Sequence

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import GraphThrottled
from office_mcp.shared import handles
from office_mcp.tools import list_chats as chats

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
    """One `chat` as `GET /me/chats?$expand=members,lastMessagePreview` returns it.

    `onlineMeetingInfo` is in the default projection of this collection — Graph sends it as null for
    every chat that is not a meeting's — so it is always present here and only sometimes populated.
    """
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


# A join URL shaped like the ones Graph actually stores, and the reason the escaping is a bug class:
# it carries `%3a` and `%40` that are already percent-escaped, a `?context=` query with `%7b`/`%22`
# in its value, and an `&` parameter after it. Every one of those breaks a `$filter` that is encoded
# too little, too much, or not at all — and breaks it into `200 OK` with an empty result. Nothing
# here sends that filter; this is the URL the handle a meeting chat carries has to survive carrying.
JOIN_WEB_URL = (
    "https://teams.microsoft.invalid/l/meetup-join/"
    + "19%3ameeting_TjAwMDAwMDAwMDAwMA%40thread.v2/0"
    + "?context=%7b%22Tid%22%3a%228a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81%22%7d&anon=true"
)


def online_meeting_info(join_web_url: str | None = JOIN_WEB_URL) -> dict[str, object]:
    """A meeting chat's `onlineMeetingInfo`, with or without the one field that matters.

    A null `joinWebUrl` is the case the whole design has to survive: it is the only documented route
    from a chat to its meeting, and no live call has proved it is always populated.
    """
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

    async def test_a_member_list_full_to_graphs_cap_is_flagged_as_possibly_incomplete(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """Graph returns at most 25 members per chat on this endpoint and says nothing about it,
        so a model summarising "who is in this chat" from the list is wrong without a flag.

        The chat below has *exactly* the cap's worth of members, which is the case the flag may
        not overclaim on: nothing was dropped from it, and Graph's response is byte-for-byte what
        a 200-person chat's would be. So the flag is raised — 25-of-25 and 25-of-200 have to be
        treated alike — and says only that members may be missing.
        """
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
        """The flag's description is read by the model, so it is part of the contract: a list at
        the cap may be short of members, and Graph gives nothing that would prove it is."""
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
        """The whole of meeting discovery, and the reason there is no second tool for it: a meeting
        chat is already listed here with its subject and its recency, and `onlineMeetingInfo` is
        in this collection's default projection — so the handle that reaches the meeting behind it
        costs no extra request and no extra permission."""
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
        """The unverified half of the discovery path. `joinWebUrl` is documented on the chat
        resource and modelled by the SDK, but no live call has proved it is always populated — and
        it is the only documented route from a chat to its meeting. So a null is reported as a null:
        no handle, and nothing invented from the chat id to stand in for one."""
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
        """A model reads this description, and the honest reading of a null is "there is no route",
        not "try something else" — there is nothing else to try."""
        description = chats.ChatSummary.model_fields["meeting_uri"].description

        assert description is not None
        assert "Null when no join URL exists" in description
        assert "The only route from conversation to meeting" in description, (
            "the populated case says what it is a route to, and its being the only one is what "
            + "makes a null a dead end rather than an invitation to try something else"
        )

    async def test_an_unknown_chat_type_does_not_fail_the_listing(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """A `chatType` the SDK's generated enum has no member for deserializes to `None` rather
        than raising, so the chat arrives typeless and the listing must still name it something.
        Passing a *valid* type here would exercise nothing.
        """
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
        assert len(listed.chats) < 25, (
            "the walk reached the end of the collection, and a window short of `limit` is how that "
            "is reported now that there is no flag saying it"
        )

    async def test_an_empty_page_in_the_middle_does_not_end_the_window(
        self, client: GraphServiceClient, graph: respx.MockRouter
    ) -> None:
        """The load-bearing case for the sentence this tool's answer carries: fewer than `limit`
        chats is every chat there is.

        Graph answers the occasional page with nothing in it and a cursor still set, and the SDK's
        own page walker treats an empty page as the end of the collection. Believing it here would
        not merely drop chats — it would turn a window with more behind it into "you have one
        chat", which is a claim about the user's tenant that nothing checked.
        """
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
