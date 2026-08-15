"""A mocked graph.microsoft.com, and a Graph client that calls it as a synthetic user.

The same three fixtures the other test directories build, built here too rather than imported
across: a tool file's tests reach for nothing outside the tool and its `shared/` vocabulary, and a
test package that imported another test package's fixtures would make the directories as tangled as
the modules used to be. Every payload in this directory is invented — the ids are obviously fake,
the domains are `.invalid`, and the names are from the public domain.
"""

from collections.abc import AsyncGenerator, Iterator, Mapping, Sequence

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_mcp.graph_client import GraphSettings, create_graph_transport, graph_client_for

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

# What FastMCP's On-Behalf-Of exchange would have returned. Only its identity matters here.
CALLER_TOKEN = "synthetic-graph-access-token"


@pytest.fixture
def graph() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as router:
        yield router


@pytest.fixture
async def transport() -> AsyncGenerator[httpx.AsyncClient]:
    client = create_graph_transport(GraphSettings())
    yield client
    await client.aclose()


@pytest.fixture
def client(transport: httpx.AsyncClient) -> GraphServiceClient:
    return graph_client_for(transport, CALLER_TOKEN)


# The meeting side, shared by the two listers' test files because it is one meeting answered about
# twice: the same join URL, the same `onlineMeeting`, and one artifact payload per collection.
# Builders rather than literals per test so that the fields a test is *about* are the ones it names,
# and here rather than in either tool's own file because two copies of one meeting would let a round
# trip pass over two different meetings.

# A join URL shaped like the ones Graph actually stores, and the reason the escaping is a bug class:
# it carries `%3a` and `%40` that are already percent-escaped, a `?context=` query with `%7b`/`%22`
# in its value, and an `&` parameter after it. Every one of those breaks a `$filter` that is encoded
# too little, too much, or not at all — and breaks it into `200 OK` with an empty result.
JOIN_WEB_URL = (
    "https://teams.microsoft.invalid/l/meetup-join/"
    + "19%3ameeting_TjAwMDAwMDAwMDAwMA%40thread.v2/0"
    + "?context=%7b%22Tid%22%3a%228a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81%22%7d&anon=true"
)

MEETING_ID = "MSpiYTMyMWUwZC03OWVlLTQ3OGQtOGUyOC04NWExOTUwN2Y0NTYqMCoq"

# The signed-in user, and somebody else, as `GET /me` answers and as a recording's organiser is
# named. Two ids rather than one because the whole of the organiser-only rule is which of them the
# recording belongs to, and `ME` is here for a second reason besides: it is the unrelated call a
# tool's tests reach for when what they are proving is that a request configuration built for one
# call did not change every other one.
SIGNED_IN_USER_ID = "00000000-0000-4000-8000-000000000001"
OTHER_USER_ID = "00000000-0000-4000-8000-000000000002"

ME: dict[str, object] = {
    "id": SIGNED_IN_USER_ID,
    "displayName": "Ada Lovelace",
    "mail": "ada@example.invalid",
    "userPrincipalName": "ada@corp.example.invalid",
    "jobTitle": "Analyst",
}


def meeting_payload(
    *,
    meeting_id: str = MEETING_ID,
    subject: str | None = "Pricing review",
    meeting_type: str | None = "scheduled",
    start: str | None = "2026-02-10T14:00:00Z",
    end: str | None = "2026-02-10T15:00:00Z",
) -> dict[str, object]:
    """One `onlineMeeting`, as the `JoinWebUrl` filter returns it: inside a one-element list."""
    return {
        "id": meeting_id,
        "subject": subject,
        "meetingType": meeting_type,
        "joinWebUrl": JOIN_WEB_URL,
        "startDateTime": start,
        "endDateTime": end,
    }


def transcript_payload(
    *,
    transcript_id: str = "MSMjMCMjSYNTHETIC0001",
    meeting_id: str = MEETING_ID,
    created_at: str | None = "2026-02-10T14:03:11.204Z",
    ended_at: str | None = "2026-02-10T14:58:02.117Z",
    content_correlation_id: str | None = "bc842d7a-2f6e-4b18-a1c7-73ef91d5c8e3",
) -> dict[str, object]:
    """One `callTranscript`, which is metadata only — the words come from `/content`."""
    return {
        "id": transcript_id,
        "meetingId": meeting_id,
        "callId": "af630fe0-04d3-4559-8cf9-91fe45e36296",
        "createdDateTime": created_at,
        "endDateTime": ended_at,
        "contentCorrelationId": content_correlation_id,
    }


def recording_payload(
    *,
    recording_id: str = "7e31db25-bc6e-4fd8-96c7-e01264e9b6fc",
    meeting_id: str = MEETING_ID,
    created_at: str | None = "2026-02-10T14:02:41.204Z",
    ended_at: str | None = "2026-02-10T14:49:53.117Z",
    content_correlation_id: str | None = "bc842d7a-2f6e-4b18-a1c7-73ef91d5c8e3",
    organizer_user_id: str | None = OTHER_USER_ID,
    organizer_odata_type: str = "#microsoft.graph.teamworkUserIdentity",
) -> dict[str, object]:
    """One `callRecording`, which is metadata only — the bytes are an MP4 nothing here fetches.

    `organizer_odata_type` is a parameter because Microsoft's own list-recordings sample sends
    `#Microsoft.Teams.GraphSvc.teamworkUserIdentity` on this property, which is not a type the SDK
    knows: an unknown discriminator has to keep deserializing rather than take the listing down.
    There is no duration, size or media-type property on this resource; that is not an omission
    here.
    """
    user = (
        None
        if organizer_user_id is None
        else {
            "@odata.type": organizer_odata_type,
            "id": organizer_user_id,
            # Null in every documented sample, which is why a recording's organiser can only be
            # reported as an id.
            "displayName": None,
            "userIdentityType": "aadUser",
            "tenantId": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
        }
    )
    return {
        "id": recording_id,
        "meetingId": meeting_id,
        "callId": "af630fe0-04d3-4559-8cf9-91fe45e36296",
        "createdDateTime": created_at,
        "endDateTime": ended_at,
        "contentCorrelationId": content_correlation_id,
        "recordingContentUrl": (
            f"{GRAPH_V1}/me/onlineMeetings/{meeting_id}/recordings/{recording_id}/content"
        ),
        "meetingOrganizer": {"application": None, "device": None, "user": user},
    }


# The Teams-message payloads, here rather than in one of the two test files that use them: a search
# hit and a full message are what `search_messages` and `read_message` are respectively about, and
# each tool's tests need one of the other's — a hit to read by its own handle, a message to read it
# into. Two copies of either would let the round trip pass over two different messages.

# The sender shape a search hit carries: Teams messages are indexed out of the substrate mailbox,
# so `from` is an Exchange `emailAddress` rather than a Teams identity.
MAILBOX_SENDER: dict[str, object] = {
    "emailAddress": {"name": "Ada Lovelace", "address": "ada@example.invalid"}
}

# The sender shape every Teams *read* API answers with: a `teamworkUserIdentity`, which has an id,
# an optional display name and no email property at all.
TEAMS_SENDER: dict[str, object] = {
    "user": {
        "@odata.type": "#microsoft.graph.teamworkUserIdentity",
        "id": "00000000-0000-4000-8000-000000000001",
        "displayName": "Ada Lovelace",
        "userIdentityType": "aadUser",
    }
}


def chat_hit(
    *,
    chat_id: str | None = "19:release@thread.v2",
    message_id: str = "1770000000000",
    summary: str | None = "...cut the <c0>release</c0> on Friday...",
    sender: Mapping[str, object] | None = MAILBOX_SENDER,
) -> dict[str, object]:
    """One `searchHit` over a chat message, in the reduced projection Graph returns.

    `sender=None` produces a system event message — Graph sends `from: null` and a body of the
    literal `<systemEventMessage/>` for those, and the projection carries neither `messageType`
    nor `eventDetail` to name them by.
    """
    resource = _chat_message(message_id=message_id, sender=sender)
    if chat_id is not None:
        resource["chatId"] = chat_id
    return {"hitId": message_id, "rank": 1, "summary": summary, "resource": resource}


def channel_hit(
    *,
    team_id: str = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
    channel_id: str = "19:general@thread.tacv2",
    message_id: str = "1770000000000",
) -> dict[str, object]:
    """One `searchHit` over a channel message, which identifies its container differently."""
    resource = _chat_message(message_id=message_id, sender=MAILBOX_SENDER)
    resource["channelIdentity"] = {"teamId": team_id, "channelId": channel_id}
    # Graph populates `webUrl` for channel messages and leaves it null for chat messages.
    resource["webUrl"] = f"https://teams.microsoft.invalid/l/message/{channel_id}/{message_id}"
    return {"hitId": message_id, "rank": 1, "summary": "synthetic snippet", "resource": resource}


def _chat_message(*, message_id: str, sender: Mapping[str, object] | None) -> dict[str, object]:
    return {
        "@odata.type": "#microsoft.graph.chatMessage",
        "id": message_id,
        "createdDateTime": "2026-02-11T09:15:22.31Z",
        "lastModifiedDateTime": "2026-02-11T09:20:00Z",
        "etag": message_id,
        "importance": "normal",
        "subject": None,
        "from": dict(sender) if sender is not None else None,
    }


def message_payload(
    *,
    message_id: str = "1770000000000",
    content: str = "<div><p>cut the release on Friday</p></div>",
    content_type: str = "html",
    sender: Mapping[str, object] | None = TEAMS_SENDER,
    message_type: str = "message",
    last_modified_at: str = "2026-02-11T09:15:22.31Z",
    last_edited_at: str | None = None,
    deleted_at: str | None = None,
    reply_to_id: str | None = None,
    web_url: str | None = None,
    mentions: Sequence[Mapping[str, object]] = (),
    attachments: Sequence[Mapping[str, object]] = (),
    event_detail: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """One full `chatMessage`, as `GET /chats/{id}/messages/{id}` returns it.

    Unlike a search hit this carries a `body` — which is the whole reason a reader exists — and the
    Teams-shaped sender rather than the mailbox-shaped one.
    """
    return {
        "@odata.type": "#microsoft.graph.chatMessage",
        "id": message_id,
        "etag": message_id,
        "messageType": message_type,
        "createdDateTime": "2026-02-11T09:15:22.31Z",
        "lastModifiedDateTime": last_modified_at,
        "lastEditedDateTime": last_edited_at,
        "deletedDateTime": deleted_at,
        "subject": None,
        "importance": "normal",
        "locale": "en-us",
        "webUrl": web_url,
        "replyToId": reply_to_id,
        "from": dict(sender) if sender is not None else None,
        "body": {"contentType": content_type, "content": content},
        "mentions": [dict(mention) for mention in mentions],
        "attachments": [dict(attachment) for attachment in attachments],
        "reactions": [],
        "eventDetail": dict(event_detail) if event_detail is not None else None,
    }


def search_response(
    hits: Sequence[Mapping[str, object]] | None,
    *,
    total: int | None = None,
    more_results_available: bool = False,
) -> dict[str, object]:
    """A `POST /search/query` response around `hits`, or around no `hits` key at all.

    Graph nests one response per request and one container per entity type; since it honours a
    single request over a single entity type, there is only ever one of each.
    """
    container: dict[str, object] = {"moreResultsAvailable": more_results_available}
    if hits is not None:
        container["hits"] = list(hits)
    if total is not None:
        container["total"] = total
    return {"value": [{"searchTerms": [], "hitsContainers": [container]}]}
