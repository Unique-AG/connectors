"""A mocked graph.microsoft.com, and a Graph client that calls it as a synthetic user.

Every payload in this directory is invented. Nothing here came from a real tenant: the ids are
obviously fake, the domains are `.invalid`, and the names are from the public domain.
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


def chat_payload(
    chat_id: str,
    *,
    chat_type: str = "group",
    topic: str | None = "Release planning",
    last_message_at: str | None = "2026-02-11T09:15:22.31Z",
    members: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, object]:
    """One `chat` as `GET /me/chats?$expand=members,lastMessagePreview` returns it."""
    payload: dict[str, object] = {
        "id": chat_id,
        "chatType": chat_type,
        "topic": topic,
        "createdDateTime": "2026-01-04T12:00:00Z",
        "lastUpdatedDateTime": "2026-02-11T09:15:22.31Z",
        "members": list(members) if members is not None else [aad_member("Ada Lovelace")],
    }
    if last_message_at is not None:
        payload["lastMessagePreview"] = {
            "id": "1770000000000",
            "createdDateTime": last_message_at,
            "body": {"contentType": "text", "content": "synthetic preview"},
        }
    return payload


def aad_member(display_name: str, *, email: str | None = None) -> dict[str, object]:
    return {
        "@odata.type": "#microsoft.graph.aadUserConversationMember",
        "id": f"member-{display_name.replace(' ', '-').lower()}",
        "displayName": display_name,
        "email": email or f"{display_name.split()[0].lower()}@example.invalid",
    }
