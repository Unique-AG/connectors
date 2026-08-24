"""A mocked graph.microsoft.com, a Graph client that calls it, and the payloads two tools share."""

from collections.abc import AsyncGenerator, Iterator, Mapping, Sequence

import httpx
import pytest
import respx
from msgraph.graph_service_client import GraphServiceClient

from office_365_mcp.graph_client import GraphSettings, create_graph_transport, graph_client_for

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

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


# Already percent-escaped `%3a` and `%40`, a `?context=` value holding `%7b` and `%22`, and an `&`
# after it. A `$filter` encoded too little, too much or not at all answers `200 OK` and no results.
JOIN_WEB_URL = (
    "https://teams.microsoft.invalid/l/meetup-join/"
    + "19%3ameeting_TjAwMDAwMDAwMDAwMA%40thread.v2/0"
    + "?context=%7b%22Tid%22%3a%228a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81%22%7d&anon=true"
)

MEETING_ID = "MSpiYTMyMWUwZC03OWVlLTQ3OGQtOGUyOC04NWExOTUwN2Y0NTYqMCoq"

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
    """Metadata only: the words come from `/content`."""
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
    """Metadata only, and no duration, size or media-type property exists on `callRecording`.

    `organizer_odata_type` is a parameter because Microsoft's own list-recordings sample sends
    `#Microsoft.Teams.GraphSvc.teamworkUserIdentity`, a discriminator the SDK does not know.
    """
    user = (
        None
        if organizer_user_id is None
        else {
            "@odata.type": organizer_odata_type,
            "id": organizer_user_id,
            # Null in every documented sample: an organiser can only be reported as an id.
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


# Teams messages are indexed out of the substrate mailbox, so a search hit's `from` is an Exchange
# `emailAddress` rather than a Teams identity.
MAILBOX_SENDER: dict[str, object] = {
    "emailAddress": {"name": "Ada Lovelace", "address": "ada@example.invalid"}
}

# What every Teams *read* API answers with instead: no email property exists on this shape.
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
    """`sender=None` is a system event message: the projection has no `messageType` naming it."""
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
    """Graph nests one response per request and one container per type: only ever one of each."""
    container: dict[str, object] = {"moreResultsAvailable": more_results_available}
    if hits is not None:
        container["hits"] = list(hits)
    if total is not None:
        container["total"] = total
    return {"value": [{"searchTerms": [], "hitsContainers": [container]}]}
