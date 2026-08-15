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


# The signed-in user, as `GET /me` answers. Here rather than in a test file because it is the
# unrelated call a tool's tests reach for when what they are proving is that a request configuration
# built for one call did not change every other one.
ME: dict[str, object] = {
    "id": "00000000-0000-4000-8000-000000000001",
    "displayName": "Ada Lovelace",
    "mail": "ada@example.invalid",
    "userPrincipalName": "ada@corp.example.invalid",
    "jobTitle": "Analyst",
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
