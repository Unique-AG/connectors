"""Test the MCP protocol: client → tool → On-Behalf-Of token → Microsoft Graph.

Test app from create_app with Entra and Graph stubbed at their boundaries.
"""

import json
import logging
import re
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import respx
from azure.core.credentials import AccessToken as GraphAccessToken
from azure.core.exceptions import ClientAuthenticationError
from fastmcp import Client, FastMCP
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import FastMCPTransport
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.dependencies import AccessToken
from mcp.types import TextContent, Tool
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from starlette.applications import Starlette

from office_mcp.app import create_app
from office_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_mcp.graph_client import GraphSettings, create_graph_transport
from office_mcp.shared import meetings
from office_mcp.shared.messages import MAX_REPLIES_PER_POST

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

OBO_TOKEN = "synthetic-obo-graph-token"
_CLIENT_TOKEN = "synthetic-fastmcp-session-token"

_ME = {
    "id": "00000000-0000-4000-8000-000000000001",
    "displayName": "Ada Lovelace",
    "mail": "ada@example.invalid",
    "userPrincipalName": "ada@corp.example.invalid",
    "jobTitle": "Analyst",
}

_SEARCH_HIT_RESOURCE = {
    "@odata.type": "#microsoft.graph.chatMessage",
    "id": "1770000000000",
    "chatId": "19:release@thread.v2",
    "createdDateTime": "2026-02-11T09:15:22.31Z",
    "lastModifiedDateTime": "2026-02-11T09:15:22.31Z",
    "importance": "normal",
    "subject": None,
    # The sender is Exchange-shaped: Teams messages are indexed out of the substrate mailbox.
    "from": {"emailAddress": {"name": "Ada Lovelace", "address": "ada@example.invalid"}},
}

_SEARCH = {
    "value": [
        {
            "searchTerms": [],
            "hitsContainers": [
                {
                    "hits": [
                        {
                            "hitId": "1770000000000",
                            "rank": 1,
                            "summary": "...cut the <c0>release</c0> on Friday...",
                            "resource": _SEARCH_HIT_RESOURCE,
                        }
                    ],
                    # For Teams messages this is the page count, not a match total. It is here so
                    # a test can prove it is not reported as one.
                    "total": 1,
                    "moreResultsAvailable": False,
                }
            ],
        }
    ]
}

# The handle the search hit above carries, and what read_message has to resolve. Written out rather
# than derived: deriving it would assert only that the test agrees with itself.
_MESSAGE_URI = "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000"
_MESSAGE_PATH = "/chats/19%3Arelease%40thread.v2/messages/1770000000000"

# The same message as `GET /chats/{id}/messages/{id}` returns it: a body, and a Teams-shaped sender
# with no email at all.
_MESSAGE = {
    "@odata.type": "#microsoft.graph.chatMessage",
    "id": "1770000000000",
    "etag": "1770000000000",
    "messageType": "message",
    "createdDateTime": "2026-02-11T09:15:22.31Z",
    "lastModifiedDateTime": "2026-02-11T09:15:22.31Z",
    "importance": "normal",
    "from": {
        "user": {
            "@odata.type": "#microsoft.graph.teamworkUserIdentity",
            "id": "00000000-0000-4000-8000-000000000001",
            "displayName": "Ada Lovelace",
            "userIdentityType": "aadUser",
        }
    },
    "body": {
        "contentType": "html",
        "content": "<div><p>Let's cut the <strong>release</strong> on Friday&nbsp;&amp; tell "
        + '<at id="0">Grace Hopper</at>.</p></div>',
    },
    "mentions": [
        {
            "id": 0,
            "mentionText": "Grace Hopper",
            "mentioned": {
                "user": {
                    "id": "00000000-0000-4000-8000-000000000002",
                    "displayName": "Grace Hopper",
                    "userIdentityType": "aadUser",
                }
            },
        }
    ],
    "attachments": [],
}

# A system event message: Graph sends no author and no text, the body is the literal
# `<systemEventMessage/>`, and the Teams client writes the sentence a user sees.
_SYSTEM_MESSAGE = {
    "@odata.type": "#microsoft.graph.chatMessage",
    "id": "1770000000000",
    "messageType": "systemEventMessage",
    "createdDateTime": "2026-02-11T09:15:22.31Z",
    "from": None,
    "body": {"contentType": "html", "content": "<systemEventMessage/>"},
    "eventDetail": {
        "@odata.type": "#microsoft.graph.membersJoinedEventMessageDetail",
        "visibleHistoryStartDateTime": "0001-01-01T00:00:00Z",
        "members": [{"id": "00000000-0000-4000-8000-000000000002"}],
    },
}

_TEAM_ID = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
_CHANNEL_ID = "19:general@thread.tacv2"
_CHANNELS_PATH = f"/teams/{_TEAM_ID}/channels"
_CHANNEL_MESSAGES_PATH = f"/teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2/messages"

# Only the five properties `GET /me/joinedTeams` populates. Every other property comes back null
# there, asked for or not.
_TEAMS = {
    "value": [
        {
            "id": _TEAM_ID,
            "displayName": "Engineering",
            "description": "Ships the product",
            "isArchived": False,
            "tenantId": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
        }
    ]
}

_CHANNELS = {
    "value": [
        {
            "id": _CHANNEL_ID,
            "displayName": "General",
            "description": "Everything and nothing",
            "createdDateTime": "2026-01-04T12:00:00Z",
            "membershipType": "standard",
        }
    ]
}

_ROOT_POST_ID = "1770000000000"
_REPLY_ID = "1770000000002"

# One channel post with one reply, as `?$top=…&$expand=replies` returns it.
_CHANNEL_POSTS = {
    "value": [
        {
            "@odata.type": "#microsoft.graph.chatMessage",
            "id": _ROOT_POST_ID,
            "messageType": "message",
            "createdDateTime": "2026-02-11T09:15:22.31Z",
            "from": {
                "user": {
                    "id": "00000000-0000-4000-8000-000000000001",
                    "displayName": "Ada Lovelace",
                    "userIdentityType": "aadUser",
                }
            },
            "body": {"contentType": "html", "content": "<div><p>Release plan for Friday</p></div>"},
            "replies": [
                {
                    "@odata.type": "#microsoft.graph.chatMessage",
                    "id": _REPLY_ID,
                    "messageType": "message",
                    "createdDateTime": "2026-02-11T10:02:00Z",
                    "replyToId": _ROOT_POST_ID,
                    "from": {
                        "user": {
                            "id": "00000000-0000-4000-8000-000000000002",
                            "displayName": "Grace Hopper",
                            "userIdentityType": "aadUser",
                        }
                    },
                    "body": {"contentType": "text", "content": "agreed, Friday works"},
                }
            ],
        }
    ]
}

# The handle the reply above carries, and the path Graph serves it from. Graph addresses a reply
# under the post it answers. No other shape reaches it.
_REPLY_URI = (
    f"teams:///teams/{_TEAM_ID}/channels/19%3Ageneral%40thread.tacv2"
    + f"/messages/{_ROOT_POST_ID}/replies/{_REPLY_ID}"
)
_REPLY_PATH = f"{_CHANNEL_MESSAGES_PATH}/{_ROOT_POST_ID}/replies/{_REPLY_ID}"

_REPLY: dict[str, object] = {
    "@odata.type": "#microsoft.graph.chatMessage",
    "id": _REPLY_ID,
    "messageType": "message",
    "createdDateTime": "2026-02-11T10:02:00Z",
    "replyToId": _ROOT_POST_ID,
    "from": {
        "user": {
            "id": "00000000-0000-4000-8000-000000000002",
            "displayName": "Grace Hopper",
            "userIdentityType": "aadUser",
        }
    },
    "body": {"contentType": "text", "content": "agreed, Friday works"},
    "attachments": [],
    "mentions": [],
}

_CHATS = {
    "value": [
        {
            "id": "19:release@thread.v2",
            "chatType": "group",
            "topic": "Release planning",
            "createdDateTime": "2026-01-04T12:00:00Z",
            "lastUpdatedDateTime": "2026-02-11T09:15:22.31Z",
            "members": [
                {
                    "@odata.type": "#microsoft.graph.aadUserConversationMember",
                    "id": "member-ada",
                    "displayName": "Ada Lovelace",
                    "email": "ada@example.invalid",
                }
            ],
            "lastMessagePreview": {
                "id": "1770000000000",
                "createdDateTime": "2026-02-11T09:15:22.31Z",
                "body": {"contentType": "text", "content": "synthetic preview"},
            },
        }
    ]
}


# The join URL as Microsoft stores one: already percent-escaped `%3a` and `%40`, a `?context=`
# query, an `&` parameter. That shape is what the `$filter` has to survive. Nothing here is real.
_JOIN_WEB_URL = (
    "https://teams.microsoft.invalid/l/meetup-join/"
    + "19%3ameeting_TjAwMDAwMDAwMDAwMA%40thread.v2/0"
    + "?context=%7b%22Tid%22%3a%228a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81%22%7d&anon=true"
)
_MEETING_ID = "MSpiYTMyMWUwZC03OWVlLTQ3OGQtOGUyOC04NWExOTUwN2Y0NTYqMCoq"
_TRANSCRIPT_ID = "MSMjMCMjSYNTHETIC0001"
_RECORDING_ID = "7e31db25-bc6e-4fd8-96c7-e01264e9b6fc"
_MEETINGS_PATH = "/me/onlineMeetings"
_TRANSCRIPTS_PATH = f"/me/onlineMeetings/{_MEETING_ID}/transcripts"
_RECORDINGS_PATH = f"/me/onlineMeetings/{_MEETING_ID}/recordings"
_CONTENT_PATH = f"{_TRANSCRIPTS_PATH}/{_TRANSCRIPT_ID}/content"
# Routed and asserted to be *un*called: this connector never fetches recording content, and a
# standing route is the only way to say so over the protocol.
_RECORDING_CONTENT_PATH = f"{_RECORDINGS_PATH}/{_RECORDING_ID}/content"

_MEETING_CHATS = {
    "value": [
        {
            "id": "19:meeting_TjAwMDAwMDAwMDAwMA@thread.v2",
            "chatType": "meeting",
            "topic": "Pricing review",
            "createdDateTime": "2026-02-10T13:55:00Z",
            "lastUpdatedDateTime": "2026-02-10T15:01:00Z",
            "onlineMeetingInfo": {
                "calendarEventId": "AAMkAGSYNTHETIC",
                "joinWebUrl": _JOIN_WEB_URL,
                "organizer": {
                    "user": {
                        "id": "00000000-0000-4000-8000-000000000002",
                        "displayName": "Grace Hopper",
                    }
                },
            },
            "lastMessagePreview": {
                "id": "1770000000001",
                "createdDateTime": "2026-02-10T15:01:00Z",
                "body": {"contentType": "text", "content": "synthetic preview"},
            },
        }
    ]
}

_MEETING = {
    "value": [
        {
            "id": _MEETING_ID,
            "subject": "Pricing review",
            "meetingType": "scheduled",
            "joinWebUrl": _JOIN_WEB_URL,
            "startDateTime": "2026-02-10T14:00:00Z",
            "endDateTime": "2026-02-10T15:00:00Z",
        }
    ]
}

_TRANSCRIPTS = {
    "value": [
        {
            "id": _TRANSCRIPT_ID,
            "meetingId": _MEETING_ID,
            "callId": "af630fe0-04d3-4559-8cf9-91fe45e36296",
            "createdDateTime": "2026-02-10T14:03:11.204Z",
            "endDateTime": "2026-02-10T14:58:02.117Z",
            "contentCorrelationId": "bc842d7a-2f6e-4b18-a1c7-73ef91d5c8e3",
        }
    ]
}

# One recording of the same meeting, organised by somebody else: the common case, and where the
# organiser-only rule bites. Its `contentCorrelationId` matches the transcript's, because that
# value is Microsoft's own link between the two artifacts.
_RECORDINGS = {
    "value": [
        {
            "id": _RECORDING_ID,
            "meetingId": _MEETING_ID,
            "callId": "af630fe0-04d3-4559-8cf9-91fe45e36296",
            "createdDateTime": "2026-02-10T14:02:41.204Z",
            "endDateTime": "2026-02-10T14:49:53.117Z",
            "contentCorrelationId": "bc842d7a-2f6e-4b18-a1c7-73ef91d5c8e3",
            "recordingContentUrl": f"{GRAPH_V1}{_RECORDING_CONTENT_PATH}",
            "meetingOrganizer": {
                "application": None,
                "device": None,
                "user": {
                    # The type Microsoft's own list-recordings sample sends. The SDK does not know
                    # it, so the code falls back to the base identity rather than fail the call.
                    "@odata.type": "#Microsoft.Teams.GraphSvc.teamworkUserIdentity",
                    "id": "00000000-0000-4000-8000-000000000002",
                    "displayName": None,
                    "userIdentityType": "aadUser",
                },
            },
        }
    ]
}

# A recurring series as Microsoft holds it: one meeting, one collection, three occurrences, oldest
# first. That order is Microsoft's own, and it documents no `$orderby` here. Written out in that
# order on purpose: it makes "the newest of a series" something the lister has to work for.
_SERIES_TRANSCRIPTS: dict[str, object] = {
    "value": [
        {
            "id": f"week-{week}",
            "meetingId": _MEETING_ID,
            "createdDateTime": f"2026-02-0{2 + week}T14:00:00Z",
            "endDateTime": f"2026-02-0{2 + week}T14:50:00Z",
            "contentCorrelationId": f"bc842d7a-2f6e-4b18-a1c7-73ef91d5c8e{week}",
        }
        for week in (1, 2, 3)
    ]
}

_SERIES_RECORDINGS: dict[str, object] = {
    "value": [
        {
            "id": f"week-{week}",
            "meetingId": _MEETING_ID,
            "createdDateTime": f"2026-02-0{2 + week}T14:00:00Z",
            "endDateTime": f"2026-02-0{2 + week}T14:50:00Z",
            "contentCorrelationId": f"bc842d7a-2f6e-4b18-a1c7-73ef91d5c8e{week}",
            "meetingOrganizer": {
                "user": {"id": "00000000-0000-4000-8000-000000000002", "displayName": None}
            },
        }
        for week in (1, 2, 3)
    ]
}

# The one meeting shape that outgrows what a single call reads: a daily series, transcribed and
# recorded every time, for most of a year. Oldest first, like the weekly series above, so the
# genuinely newest occurrence sits past `MAX_ARTIFACT_SCAN` where neither lister can see it.
_PAST_THE_CAP = meetings.MAX_ARTIFACT_SCAN + 60
_DAILY_SERIES_START = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)

# The tenant switch as Graph marks it: a 403 whose outer code says nothing and whose inner code is
# the whole difference from a missing permission.
_TENANT_SWITCH_OFF = {
    "error": {
        "code": "Forbidden",
        "message": "Graph API access to transcripts is disabled for this tenant.",
        "innerError": {"code": "GraphAccessToTranscriptsDisabled"},
    }
}


def _day(index: int) -> datetime:
    """When occurrence `index` of the daily series ran."""
    return _DAILY_SERIES_START + timedelta(days=index)


def _daily_series() -> dict[str, object]:
    """`_PAST_THE_CAP` artifacts in one page, in the shape both collections share."""
    return {
        "value": [
            {
                "id": f"day-{index}",
                "meetingId": _MEETING_ID,
                "createdDateTime": _day(index).isoformat().replace("+00:00", "Z"),
                "endDateTime": (_day(index) + timedelta(minutes=50))
                .isoformat()
                .replace("+00:00", "Z"),
                "contentCorrelationId": f"bc842d7a-2f6e-4b18-a1c7-73ef91d5c8{index:03d}",
            }
            for index in range(_PAST_THE_CAP)
        ]
    }


# The meeting handle `list_chats` mints for the chat above, written out rather than derived:
# deriving it would assert only that the test agrees with itself.
_MEETING_URI = "teams:///meetings/" + quote(_JOIN_WEB_URL, safe="")

_TRANSCRIPT_VTT = """WEBVTT

00:00:16.246 --> 00:00:19.900
<v Grace Hopper>We should raise the floor price by three per cent.</v>

00:01:02.000 --> 00:01:04.500
<v Ada Lovelace>Agreed, that works.</v>
"""


class _StubOboCredential:
    """Stub for `azure.identity.aio.OnBehalfOfCredential`: records scopes, can refuse."""

    def __init__(self) -> None:
        self.requested_scopes: list[tuple[str, ...]] = []
        self.refusal: Exception | None = None

    async def get_token(self, *scopes: str) -> GraphAccessToken:
        self.requested_scopes.append(scopes)
        if self.refusal is not None:
            raise self.refusal
        return GraphAccessToken(token=OBO_TOKEN, expires_on=0)


@pytest.fixture
def obo(monkeypatch: pytest.MonkeyPatch) -> _StubOboCredential:
    """Stub the Entra on-behalf-of exchange and authenticate the in-process client."""
    credential = _StubOboCredential()

    async def get_obo_credential(
        _self: AzureProvider, *, user_assertion: str
    ) -> _StubOboCredential:
        assert user_assertion == _CLIENT_TOKEN
        return credential

    monkeypatch.setattr(AzureProvider, "get_obo_credential", get_obo_credential)
    monkeypatch.setattr(
        "fastmcp.server.dependencies.get_access_token",
        lambda: AccessToken(
            token=_CLIENT_TOKEN,
            client_id="1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061",
            scopes=["access_as_user"],
        ),
    )
    return credential


@pytest.fixture
def graph() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as router:
        yield router


@pytest.fixture
def recorded_spans() -> Iterator[InMemorySpanExporter]:
    """Every span this process finishes during a test, collected in memory.

    A privacy assertion over `get_finished_spans()` passes hardest when nothing is traced, so the
    tests that use this exporter assert a span was recorded before they assert what is not in it.

    The tracer provider is process-wide and can be set only once, so the exporter attaches to
    whichever provider is in play. The collection is emptied on the way in rather than torn down:
    an earlier test's span would otherwise read as one of this test's own.
    """
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    exporter.clear()
    yield exporter


def _build_app() -> Starlette:
    """The app with every tool there is, which is the surface these tests are written against.

    A tools preset is mandatory and has no default, so it is stated here. `teams` is every tool.
    What a narrowed preset exposes is `tests/test_tool_selection.py`'s subject.
    """
    return create_app(
        config=AppConfig.model_validate({"public_base_url": "https://office-mcp.example"}),
        database_config=DatabaseConfig.model_validate(
            {"url": "postgresql://user:pass@127.0.0.1:1/nope"}
        ),
        entra_config=EntraConfig.model_validate(
            {
                "tenant_id": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
                "client_id": "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061",
                "client_secret": "s3cr3t",
            }
        ),
        surface_config=SurfaceConfig.model_validate({"tools_preset": ToolsPreset.TEAMS}),
    )


@pytest.fixture
def app() -> Starlette:
    return _build_app()


def _server_of(app: Starlette) -> FastMCP[None]:
    return cast("FastMCP[None]", app.state.fastmcp_server)


@pytest.fixture
async def mcp_client(app: Starlette) -> AsyncIterator[Client[FastMCPTransport]]:
    async with Client(FastMCPTransport(_server_of(app))) as client:
        yield client


def _named(tools: Sequence[Tool]) -> dict[str, Tool]:
    return {tool.name: tool for tool in tools}


def _properties(schema: Mapping[str, object] | None) -> dict[str, object]:
    """The `properties` of a JSON schema, narrowed off the SDK's `dict[str, Any]`."""
    assert schema is not None, "expected a schema"
    properties = schema.get("properties")
    assert isinstance(properties, dict), f"expected an object schema, got {schema!r}"
    return cast("dict[str, object]", properties)


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict), f"expected an object, got {value!r}"
    return cast("dict[str, object]", value)


# What a tool being *named* in prose looks like, as opposed to a field. Both are `verb_noun`, so
# the verb is the discriminator: these are the verbs a tool here is named with, and no answer field
# starts with one. Deliberately not a list of the tools still to come. A stop-list of names nothing
# declares yet is one somebody forgets to add to.
_TOOL_MENTION = re.compile(r"\b(?:get|list|read|search|browse|find)_[a-z]+(?:_[a-z]+)*\b")


def _described(schema: Mapping[str, object] | None) -> list[str]:
    """Every `description` anywhere in a JSON schema: parameters, fields, nested objects.

    A model reads all of them, so a stale promise in one field's description is as harmful as one
    in the tool's own.
    """
    if schema is None:
        return []
    found: list[str] = []
    pending: list[object] = [schema]
    while pending:
        node = pending.pop()
        if isinstance(node, dict):
            for key, value in cast("Mapping[str, object]", node).items():
                if key == "description" and isinstance(value, str):
                    found.append(value)
                else:
                    pending.append(value)
        elif isinstance(node, list):
            pending.extend(cast("Sequence[object]", node))
    return found


def _fields(node: object, at: str) -> dict[str, object]:
    """Every field under a published schema, keyed by the path a model reaches it at.

    `_properties` reads one level, this reads all of them. FastMCP inlines these schemas fully: a
    nested model arrives under `items` or inside an `anyOf` branch rather than as a `$ref`, so both
    are followed. A chat member's email comes back as `list_chats.chats[].members[].email`.
    """
    schema = _object(node)
    found: dict[str, object] = {}
    properties = schema.get("properties")
    if isinstance(properties, dict):
        for name, field in cast("Mapping[str, object]", properties).items():
            where = f"{at}.{name}"
            found[where] = field
            found |= _fields(field, where)
    items = schema.get("items")
    if items is not None:
        found |= _fields(items, f"{at}[]")
    branches = schema.get("anyOf")
    if isinstance(branches, list):
        for branch in cast("Sequence[object]", branches):
            found |= _fields(branch, at)
    return found


def _optional_types(schema: object) -> list[dict[str, object]]:
    """Every non-null branch of an optional parameter's schema, in the order it declares them."""
    branches = cast("Sequence[object]", _object(schema)["anyOf"])
    return [_object(branch) for branch in branches if _object(branch).get("type") != "null"]


def _optional_type(schema: object) -> dict[str, object]:
    """The one non-null branch of an optional parameter's schema, where it has exactly one."""
    typed = _optional_types(schema)
    assert len(typed) == 1, f"expected one non-null branch, got {typed!r}"
    return typed[0]


# The tools that answer with a Teams message, and so with a sender. They are why
# `shared/messages.py` exists, and why the sender shape is asserted over the live schemas rather
# than the model class: what a model reads is the schema.
_MESSAGE_TOOLS: tuple[str, ...] = ("read_message", "browse_channel", "search_messages")


def _items(schema: object) -> dict[str, object]:
    """The element schema of an array-shaped property, e.g. one message of `messages`."""
    return _object(_object(schema)["items"])


def _sender_schema(schema: Mapping[str, object] | None) -> dict[str, object]:
    """The sender object inside a tool's answer, wherever that answer puts a message.

    `read_message` answers with one message and carries `sender` at the top. `browse_channel` and
    `search_messages` answer with a list and carry it per element. All three reach the same
    `MessageSender`.
    """
    properties = _properties(schema)
    message = properties if "sender" in properties else _properties(_items(properties["messages"]))
    sender = message["sender"]
    # Optional on a read, because a system event message has no author, and required on a search
    # hit, where such hits are dropped. Unwrap an `anyOf` only where there is one.
    return _optional_type(sender) if "anyOf" in _object(sender) else _object(sender)


def _structured(result: CallToolResult) -> dict[str, object]:
    data = cast("dict[str, object] | None", result.structured_content)
    assert data is not None, "the tool returned no structured content"
    return data


def _search_query_string(route: respx.Route) -> str:
    """The KQL string the last `/search/query` call put on the wire."""
    body = cast("dict[str, object]", json.loads(route.calls.last.request.content))
    requests = cast("Sequence[Mapping[str, object]]", body["requests"])
    assert len(requests) == 1, "Graph honours only one searchRequest per call"
    query = cast("Mapping[str, object]", requests[0]["query"])
    return cast("str", query["queryString"])


def _error_text(result: CallToolResult) -> str:
    """Everything the model would read of a failed call."""
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


def _record_text(record: logging.LogRecord) -> str:
    """A log record's whole payload: the formatted message and every field attached to it.

    A value passed as an extra never appears in the message but does reach the log sink, so
    checking `getMessage()` alone would miss it.
    """
    return f"{record.getMessage()} {record.__dict__!r}"


class TestTheToolsThisServerAdvertises:
    async def test_every_tool_is_listed_and_none_asks_for_a_client(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The Graph client, the On-Behalf-Of token inside it and the request context are
        dependencies. A model shown one as an argument would be asked for a value only this server
        can make."""
        tools = _named(await mcp_client.list_tools())

        assert set(tools) == {
            "get_me",
            "list_chats",
            "list_teams",
            "list_channels",
            "browse_channel",
            "search_messages",
            "read_message",
            "list_meeting_transcripts",
            "read_transcript",
            "list_meeting_recordings",
        }
        for tool in tools.values():
            arguments = _properties(tool.inputSchema)
            assert "client" not in arguments
            assert "ctx" not in arguments

    async def test_get_me_takes_no_arguments(self, mcp_client: Client[FastMCPTransport]) -> None:
        tools = _named(await mcp_client.list_tools())

        assert _properties(tools["get_me"].inputSchema) == {}
        assert tools["get_me"].inputSchema.get("required", []) == []

    async def test_list_chats_bounds_its_limit_where_graph_bounds_it(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """Prose ("max 50") is advice and the schema is enforcement: an out-of-range call has to
        fail loudly rather than be clamped silently."""
        tools = _named(await mcp_client.list_tools())
        limit = _object(_properties(tools["list_chats"].inputSchema)["limit"])

        assert limit["type"] == "integer", "not `number`: a fractional page size is meaningless"
        assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 50, 25)

    async def test_every_tool_declares_its_result_shape(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        tools = _named(await mcp_client.list_tools())

        assert set(_properties(tools["get_me"].outputSchema)) == {
            "user_id",
            "display_name",
            "email",
            "user_principal_name",
            "job_title",
        }
        assert set(_properties(tools["list_chats"].outputSchema)) == {"chats"}
        assert set(_properties(tools["list_teams"].outputSchema)) == {"teams"}
        assert set(_properties(tools["list_channels"].outputSchema)) == {"channels"}
        assert set(_properties(tools["browse_channel"].outputSchema)) == {
            "messages",
            "more_posts_in_channel",
            "posts_cut_to_limit",
        }
        assert set(_properties(tools["search_messages"].outputSchema)) == {
            "messages",
            "next_offset",
        }
        assert set(_properties(tools["read_message"].outputSchema)) == {
            "uri",
            "message_id",
            "chat_id",
            "team_id",
            "channel_id",
            "sender",
            "text",
            "event",
            "created_at",
            "last_edited_at",
            "deleted_at",
            "reply_to_id",
            "subject",
            "importance",
            "web_url",
            "mentions",
            "attachments",
        }
        assert set(_properties(tools["list_meeting_transcripts"].outputSchema)) == {
            "status",
            "meeting_id",
            "subject",
            "meeting_type",
            "started_at",
            "ended_at",
            "transcripts",
            "scan_incomplete",
        }
        assert set(_properties(tools["read_transcript"].outputSchema)) == {
            "uri",
            "meeting_id",
            "transcript_id",
            "speaker_attribution",
            "turns",
            "next_offset",
        }
        assert set(_properties(tools["list_meeting_recordings"].outputSchema)) == {
            "status",
            "meeting_id",
            "subject",
            "meeting_type",
            "started_at",
            "ended_at",
            "recordings",
            "scan_incomplete",
        }

    async def test_every_tool_response_field_is_described(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """A field's description is the only place its meaning gets said: the answer is JSON, with
        nowhere to put a caveat. Without one a model guesses from the name, and these are the names
        worth not guessing at. `chat_id` is not a handle, `next_offset` is not a count, and a null
        `members` does not mean nobody is in the chat. Asserted over the published schemas rather
        than the model classes: a description that never reaches the wire is not one.
        """
        tools = _named(await mcp_client.list_tools())
        published = {
            path: field
            for name, tool in tools.items()
            for path, field in _fields(tool.outputSchema, name).items()
        }

        # Guards the guard: a field two models deep is the case the walk exists for, so a walk that
        # had stopped reaching one would pass by finding nothing rather than everything described.
        assert "list_chats.chats[].members[].email" in published

        undescribed = sorted(
            path for path, field in published.items() if not _object(field).get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"

    async def test_the_whole_surface_speaks_one_language(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """Tool names are verb_noun, fields are snake_case, and no tool carries a `truncated` flag.

        A window filled to `limit` says there may be more and a short one says there is not, so
        `truncated` on top means "raise `limit`" or "nothing will help" with no way to tell which.
        `list_chats` says it by the length of its window, honest because its walk follows
        Microsoft's paging to the end of the collection. `search_messages` cannot, because for
        Teams messages Microsoft reports a page count rather than a match total, so it says it with
        `next_offset`, and `read_transcript` says it the same way over the turns of a transcript
        Graph serves in one piece. That field is asserted on both.

        A completeness fact the answer does not derive survives as an opt-in field, asserted too:
        the flag defaults to off, and each tool carries one field per fact rather than one boolean
        over several. `browse_channel` needs it because it reads a single page and drops system
        messages Microsoft counted into it, so its length says neither thing. The meeting listers
        need it because the fact is whether the read reached the end of a meeting's artifacts, and
        therefore whether "newest" is a claim about the meeting or about what was read.
        """
        tools = _named(await mcp_client.list_tools())

        for name in tools:
            assert re.fullmatch(r"[a-z]+(_[a-z]+)+", name), f"{name} is not verb_noun"
        for tool in tools.values():
            for field in _properties(tool.outputSchema):
                assert re.fullmatch(r"[a-z][a-z0-9]*(_[a-z0-9]+)*", field), f"{field} is not snake"
        for name, tool in tools.items():
            assert "truncated" not in _properties(tool.outputSchema), name
        for name in ("search_messages", "read_transcript"):
            assert "next_offset" in _properties(tools[name].outputSchema), name
        for name, flag in (
            ("browse_channel", "include_window_completeness"),
            ("list_meeting_transcripts", "include_scan_completeness"),
            ("list_meeting_recordings", "include_scan_completeness"),
        ):
            asked_for = _object(_properties(tools[name].inputSchema)[flag])
            assert asked_for["default"] is False, f"{name} would report completeness unasked"

    async def test_search_messages_makes_its_criteria_optional_but_not_all_of_them(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """Not one of the oracle connector's ten schemas uses `anyOf`, so every rule about which
        parameters may combine lives in prose a model may not read, and the illegal call validates
        cleanly and then behaves differently in silence. "At least one criterion" has a JSON Schema
        spelling, so it is spelled.
        """
        tools = _named(await mcp_client.list_tools())
        schema = tools["search_messages"].inputSchema
        properties = _properties(schema)

        assert schema.get("required", []) == [], "each criterion is individually optional"
        alternatives = cast("Sequence[Mapping[str, object]]", schema["anyOf"])
        required = [cast("Sequence[str]", option["required"]) for option in alternatives]
        assert [name for (name,) in required] == [
            "query",
            "sender",
            "recipient",
            "mentions",
            "sent_after",
            "sent_before",
            "has_attachment",
            "is_read",
            "mentions_me",
        ]
        for (name,) in required:
            assert name in properties, f"{name} is constrained but is not a parameter"

    async def test_search_messages_types_the_parameters_graph_is_fussy_about(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """A mentioned user must be an id: Microsoft matches that scope term on the id alone, so a
        display name silently matches nothing. The dates are whole days, not timestamps."""
        tools = _named(await mcp_client.list_tools())
        properties = _properties(tools["search_messages"].inputSchema)

        assert _optional_type(properties["mentions"]) == {"type": "string", "format": "uuid"}
        assert _optional_type(properties["sent_after"]) == {"type": "string", "format": "date"}
        assert _optional_type(properties["sent_before"]) == {"type": "string", "format": "date"}

    async def test_the_query_parameter_describes_the_matching_it_actually_does(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The description is the only place a model learns what `query` does, so it has to match
        what the query builder does. A description promising "matched as words" over a builder
        sending one quoted phrase is a recall loss a caller cannot see: the tool answers with fewer
        messages than exist and nothing says so. Both halves are pinned here: the words are ANDed,
        and adjacency is available by quoting.
        """
        tools = _named(await mcp_client.list_tools())
        query = _object(_properties(tools["search_messages"].inputSchema)["query"])
        description = cast("str", query["description"])

        assert "Every word must appear" in description
        assert "any order" in description
        assert "not matched as phrases unless quoted" in description
        assert '"release notes"' in description, "the phrase syntax needs an example to be usable"

    async def test_search_messages_bounds_its_page_where_microsoft_documents_it(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        tools = _named(await mcp_client.list_tools())
        properties = _properties(tools["search_messages"].inputSchema)
        size = _object(properties["size"])
        offset = _object(properties["offset"])

        assert (size["type"], size["minimum"], size["maximum"], size["default"]) == (
            "integer",
            1,
            50,
            25,
        )
        assert (offset["type"], offset["minimum"], offset["default"]) == ("integer", 0, 0)
        assert "maximum" not in offset, (
            "Microsoft documents no offset ceiling for message search; inventing one would refuse "
            + "a page Graph would have served"
        )

    async def test_the_sender_shape_teaches_both_identities_where_it_is_not_overridden(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """A sender's *shape* is guidance, not just a type, and it ships as a schema description.

        Pydantic publishes a model's docstring as the JSON-schema `description` of the object it
        describes, so `MessageSender`'s own paragraph is live protocol surface on every tool that
        does not override it. Losing it is invisible: the schema still validates and every tool
        still answers. What goes missing is the sentence that stops a model reading a null as a
        fact about the person. A search hit carries an Exchange-style `emailAddress`, a Teams read
        answers with a `teamworkUserIdentity` that has no email property at all, and a bot arrives
        as an application identity, so which fields are filled in says which shape Graph used.
        `read_message` and `browse_channel` are where that matters, because their senders normally
        arrive with `email` null.

        `search_messages` overrides at field level, so its own words are what a model reads there.
        All three share the per-field descriptions, and that is asserted too: a difference would be
        one tool explaining `user_id` differently from the next.
        """
        tools = _named(await mcp_client.list_tools())
        taught = {name: _sender_schema(tools[name].outputSchema) for name in _MESSAGE_TOOLS}

        for name in ("read_message", "browse_channel"):
            written = taught[name]["description"]
            assert isinstance(written, str)
            # A docstring reaches the schema with its own line breaks. What is pinned is the
            # sentence, not where it wrapped.
            description = " ".join(written.split())
            assert "emailAddress" in description, name
            assert "teamworkUserIdentity" in description, name
            assert "A null is not evidence that the sender has no name, no address or no id" in (
                description
            ), name
        fields = [_properties(taught[name]) for name in _MESSAGE_TOOLS]
        assert all(field == fields[0] for field in fields), (
            "every tool that reports a sender must describe its fields identically — they are one "
            + "type in shared/messages.py, and a model reads them as one server"
        )

    async def test_read_message_takes_exactly_one_required_handle(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """A reader with optional parameters would invite a model to try reading "the last message
        in this chat", which no handle expresses and this connector cannot serve."""
        tools = _named(await mcp_client.list_tools())
        schema = tools["read_message"].inputSchema

        assert set(_properties(schema)) == {"uri"}
        assert schema.get("required") == ["uri"]

    async def test_read_message_names_every_handle_shape_and_no_others(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The `uri` parameter's own description is where a model learns what it may pass, read
        immediately before it writes a value rather than at selection time. Naming the shapes is
        what stops it inventing `mail:///`, and the oracle connector's one polymorphic
        `read_resource` is the promise this connector does not make. The reply shape is named with
        the tool that mints it, because no search result carries one.
        """
        tools = _named(await mcp_client.list_tools())
        uri = _object(_properties(tools["read_message"].inputSchema)["uri"])
        described = cast("str", uri["description"])

        assert "teams:///chats/{chat_id}/messages/{message_id}" in described
        assert "teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}" in described
        assert (
            "teams:///teams/{team_id}/channels/{channel_id}/messages/{root_id}/replies/{reply_id}"
            in described
        )
        assert "search_messages" in described
        assert "browse_channel" in described, "the reply shape has exactly one source"

    async def test_read_transcript_takes_a_handle_and_a_window_and_names_its_one_shape(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """A second reader, deliberately: a transcript is read under a different permission from a
        message, and a token is exchanged per tool, so one polymorphic reader would have to redeem
        transcript access to read a chat message. Its handle shape is its own, and it has to be
        named where a model reads it before writing a value: the `uri` parameter. The description
        keeps the half a model needs at selection time, which is that the two readers exist and
        take different handles."""
        tools = _named(await mcp_client.list_tools())
        schema = tools["read_transcript"].inputSchema
        description = tools["read_transcript"].description
        handle = str(_object(_properties(schema)["uri"])["description"])
        assert description is not None

        assert set(_properties(schema)) == {
            "uri",
            "offset",
            "limit",
            "from_seconds",
            "to_seconds",
            "speaker",
        }
        assert schema.get("required") == ["uri"]
        assert "teams:///transcripts/{meeting_id}/{transcript_id}" in handle
        assert "list_meeting_transcripts" in handle, "the one tool that mints this shape"
        assert "`meeting_uri` is not readable here" in handle, "the handle a model reaches for"
        assert "list_meeting_transcripts" in description
        assert "read_message" in description, "the two readers must not be confusable"
        assert "a `meeting_uri` is not one" in description

    async def test_read_transcript_narrows_by_seconds_and_by_speaker_in_its_own_schema(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The turns are timestamped and attributed in the answer, so the filters use the units the
        answer reports: seconds from transcription start, and the speaker as the transcript spells
        them. Every filter is optional, so the unfiltered read stays the default."""
        tools = _named(await mcp_client.list_tools())
        properties = _properties(tools["read_transcript"].inputSchema)

        for bound in ("from_seconds", "to_seconds"):
            assert _optional_type(properties[bound])["type"] == "number", bound
        assert _optional_type(properties["speaker"])["type"] == "string"
        for name in ("from_seconds", "to_seconds", "speaker"):
            assert _object(properties[name]).get("description"), f"{name} is undescribed"

    async def test_browse_channel_needs_both_ids_and_bounds_its_page_where_graph_does(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """A channel id alone addresses nothing: Graph's only path to a channel's messages goes
        through its team. 20 and 50 are Graph's own default and maximum for the collection."""
        tools = _named(await mcp_client.list_tools())
        schema = tools["browse_channel"].inputSchema
        limit = _object(_properties(schema)["limit"])

        assert set(_properties(schema)) == {
            "team_id",
            "channel_id",
            "limit",
            "include_window_completeness",
        }
        assert schema.get("required") == ["team_id", "channel_id"]
        assert (limit["type"], limit["minimum"], limit["maximum"], limit["default"]) == (
            "integer",
            1,
            50,
            20,
        )

    async def test_browse_channel_says_what_the_order_actually_is(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The one thing a model cannot find out for itself. Graph orders this collection by the
        last modified date of the whole reply chain, so the first post is the most recently *active*
        thread and may be years old. A tool that let "newest first" be assumed would have a model
        reporting an old post as today's news.
        """
        tools = _named(await mcp_client.list_tools())
        description = tools["browse_channel"].description
        assert description is not None

        assert "reply-chain" in description
        assert "created_at" in description, "the field that does tell the truth about age"
        assert "search_messages" in description, "where a keyword, a person or a date goes instead"

    async def test_browse_channel_says_what_one_call_costs_and_where_it_stops(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """Microsoft allows this whole connector about one request a second on a given channel
        across the tenant, so the tool makes exactly one. `limit` is therefore the entire window,
        and a model that expects paging to reach further has to be told otherwise in the
        description and in the schema, not only in the code.

        Where it stops is asserted on `messages` rather than on the description: the reply window
        is a dead end a model meets while reading the list it got back, not while choosing a tool,
        so the instruction that ends the hunt travels with the list.
        """
        tools = _named(await mcp_client.list_tools())
        description = tools["browse_channel"].description
        limit = _object(_properties(tools["browse_channel"].inputSchema)["limit"])
        posts = _object(_properties(tools["browse_channel"].outputSchema)["messages"])
        assert description is not None

        assert "One call is one request" in description
        assert "raise `limit` rather than calling again" in description, (
            "where it stops: the window widens, it never pages deeper"
        )
        assert "one request against the channel" in str(limit["description"])
        assert "browsing again returns the same newest" in str(posts["description"]), (
            "the reply window is a dead end, not a first page"
        )
        assert "stop looking" in str(posts["description"])

    async def test_list_meeting_transcripts_names_its_five_answers_and_their_remedies(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The four absences that must stay distinct, plus "no such meeting". A model acts
        differently on them only if the tool says what each one means: the one that means wait must
        say wait and must say it is not the one that means stop, and the one that means "this was
        not knowable" must not be reportable as either.

        The vocabulary is taught on the `status` field, which is where a model reads an answer, and
        the description carries only the three-way distinction it needs to choose this tool at all.
        `not_ready` is asserted on both, because it is the one absence a model reports as its
        opposite: the negative has to sit on the `not_ready` bullet itself, not on the
        `scan_incomplete` one two lines down, which is a different status.
        """
        tools = _named(await mcp_client.list_tools())
        description = tools["list_meeting_transcripts"].description
        status = _object(_properties(tools["list_meeting_transcripts"].outputSchema)["status"])
        meeting_type = _object(
            _properties(tools["list_meeting_transcripts"].outputSchema)["meeting_type"]
        )
        assert description is not None
        taught = str(status.get("description"))
        rendered = description + taught

        for value in (
            "available",
            "not_ready",
            "not_transcribed",
            "scan_incomplete",
            "meeting_not_found",
        ):
            assert f"`{value}`" in taught, value
        for value in ("not_ready", "not_transcribed", "scan_incomplete"):
            assert f"`{value}`" in description, f"{value} decides whether to call this tool at all"
        assert "`not_ready` means wait" in description
        not_ready_bullet = (
            "`not_ready` — nothing is there yet and something may still arrive. Wait and call "
            + "again later. This is NOT 'there is no transcript'."
        )
        assert not_ready_bullet in taught, (
            "the wait and its negative, on the bullet for the status they are about"
        )
        assert "Retrying will not change this" in taught, "and the one that means stop says so"
        assert "no availability SLA" in rendered, "the inference has to be admitted as one"
        assert "recurring" in str(meeting_type["description"])
        assert "started_after" in str(meeting_type["description"])
        assert "Never report this as 'there is no transcript'" in taught
        assert "is NOT known" in taught, "the fifth answer claims nothing, and has to say so"
        assert "unknowable" in description

    @pytest.mark.parametrize(
        ("tool", "artifact", "finality"),
        [
            (
                "list_meeting_transcripts",
                "transcripts",
                "This status is final and cannot be retried",
            ),
            (
                "list_meeting_recordings",
                "recordings",
                "reads the same recordings and returns this same status",
            ),
        ],
        ids=["transcripts", "recordings"],
    )
    async def test_neither_lister_offers_a_remedy_its_mechanism_cannot_keep(
        self, mcp_client: Client[FastMCPTransport], tool: str, artifact: str, finality: str
    ) -> None:
        """Four of the five statuses tell a caller what to do next. `scan_incomplete` cannot: the
        window is applied after Microsoft has answered, so no argument sends the next call further
        into the collection. Advice that sounds actionable and is not is a loop a model runs until
        something else stops it, so the field a model reads this status off says to stop, names the
        cap that caused it, and offers nothing to change.

        Asserted per tool because identical prose drifts by being edited on one side. One says the
        dead end is final, the other names the mechanism that causes it.

        The dead end is stated on the field rather than in the tool description, which is read
        before the call and cannot act on a status nobody has seen yet.
        `list_meeting_transcripts` still names it in its own description, because a model choosing
        between the two listers is told there is a third answer that means neither yes nor no.
        """
        tools = _named(await mcp_client.list_tools())
        description = tools[tool].description
        status = str(_object(_properties(tools[tool].outputSchema)["status"]))
        assert description is not None

        assert f"more {artifact} than one call reads" in status, "the cause, where the status is"
        assert "There is nothing to try" in status
        assert "Stop" in status
        assert finality in status
        assert (
            "narrow `started_after`/`started_before` to the occurrence you mean and ask again"
            not in (description + status).lower()
        ), "the remedy that cannot work, in either place a model reads it"

    async def test_list_meeting_transcripts_takes_a_meeting_handle_and_an_occurrence_window(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        tools = _named(await mcp_client.list_tools())
        schema = tools["list_meeting_transcripts"].inputSchema
        properties = _properties(schema)
        limit = _object(properties["limit"])

        assert set(properties) == {
            "meeting_uri",
            "started_after",
            "started_before",
            "limit",
            "include_scan_completeness",
        }
        assert schema.get("required") == ["meeting_uri"]
        assert (limit["type"], limit["minimum"], limit["maximum"], limit["default"]) == (
            "integer",
            1,
            50,
            20,
        )
        assert _object(properties["include_scan_completeness"])["default"] is False, (
            "the completeness of the scan is opt-in: a client that does not want it never sees it"
        )

    @pytest.mark.parametrize("bound", ["started_after", "started_before"], ids=["after", "before"])
    async def test_each_occurrence_bound_admits_a_bare_date_in_its_own_schema(
        self, mcp_client: Client[FastMCPTransport], bound: str
    ) -> None:
        """A bare `2026-08-11` is what a model writes when scoping a series to one occurrence, the
        only reason these parameters exist, so the schema has to say a date is legal. A schema
        offering only `date-time` over code that accepts a date is a disagreement the model pays
        for: it is never told which shape was meant."""
        tools = _named(await mcp_client.list_tools())
        properties = _properties(tools["list_meeting_transcripts"].inputSchema)

        assert _optional_types(properties[bound]) == [
            {"type": "string", "format": "date"},
            {"type": "string", "format": "date-time"},
        ]

    async def test_the_occurrence_window_states_the_zone_it_resolves_against(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """`09:00` is a different instant in every zone, so a tool that picks one silently has to
        say which, in the parameter's own description: that is the only place a model reads before
        writing the value. Both halves are asserted, what an offset-less timestamp means and what a
        bare date means at each end of the window."""
        tools = _named(await mcp_client.list_tools())
        properties = _properties(tools["list_meeting_transcripts"].inputSchema)
        after = str(_object(properties["started_after"])["description"])
        before = str(_object(properties["started_before"])["description"])

        assert "READ AS UTC" in after, "the assumption a naive timestamp is resolved against"
        assert "whole UTC day" in after and "first instant" in after
        assert "END of that UTC day" in before, "the same date in both bounds must be that one day"
        assert "07:00Z" in after, "a worked example beats the word 'timezone'"

    async def test_list_meeting_transcripts_says_the_verdict_is_about_the_window(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The promise the `not_ready` inference has to keep. A recurring series' `endDateTime` can
        be in the future for years, and a caller told to wait for a transcript of an occurrence that
        ended last month polls forever. So the field says the verdict follows the window that was
        asked for, not the meeting, and says it about the series in particular.

        On the field alone: the promise is about an answer already in hand, and the description is
        read before there is one. What the description owes is only that `not_ready` means wait,
        which the test above pins.
        """
        tools = _named(await mcp_client.list_tools())
        status = _object(_properties(tools["list_meeting_transcripts"].outputSchema)["status"])
        taught = str(status["description"])

        assert "demonstrably passed is never reported this way" in taught
        assert "however far in the future a recurring series runs" in taught, (
            "the series' own end date is what the verdict must not be read off"
        )

    async def test_list_meeting_recordings_takes_the_same_handle_and_window(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        tools = _named(await mcp_client.list_tools())
        schema = tools["list_meeting_recordings"].inputSchema
        properties = _properties(schema)
        limit = _object(properties["limit"])

        assert set(properties) == {
            "meeting_uri",
            "started_after",
            "started_before",
            "limit",
            "include_scan_completeness",
        }
        assert schema.get("required") == ["meeting_uri"]
        assert (limit["type"], limit["minimum"], limit["maximum"], limit["default"]) == (
            "integer",
            1,
            50,
            20,
        )
        assert _object(properties["include_scan_completeness"])["default"] is False
        for bound in ("started_after", "started_before"):
            assert _optional_types(properties[bound]) == [
                {"type": "string", "format": "date"},
                {"type": "string", "format": "date-time"},
            ]

    async def test_the_two_meeting_listers_answer_in_the_same_shape(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """Two artifacts of one meeting, asked for by the same handle over the same window, so the
        answers differ in exactly one field: which artifact is listed. That symmetry lets a model
        that learned one tool use the other without reading it twice. The alternative (`status`
        here, `state` there, `subject` here, `topic` there) is what two tools drift into.
        """
        tools = _named(await mcp_client.list_tools())
        transcripts_schema = set(_properties(tools["list_meeting_transcripts"].outputSchema))
        recordings_schema = set(_properties(tools["list_meeting_recordings"].outputSchema))

        assert transcripts_schema - recordings_schema == {"transcripts"}
        assert recordings_schema - transcripts_schema == {"recordings"}
        assert set(_properties(tools["list_meeting_transcripts"].inputSchema)) == set(
            _properties(tools["list_meeting_recordings"].inputSchema)
        )

    async def test_list_meeting_recordings_promises_no_video_and_sends_content_elsewhere(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """A recording is an MP4 of a meeting that can run 30 hours, and a model cannot watch
        video, so no tool here returns or fetches one. A description that left that out would have
        a model asking for the file, or reporting that it could not get it as if that were a
        failure. The promise is paired with the place a question about content does get answered,
        because "no video" on its own is a dead end rather than a route.

        Only the promise, not the reasons behind it: the 30-hour meeting and the MP4 byte stream
        explain a decision already taken, and a model that reads "no video is reachable here" acts
        the same way without them.
        """
        tools = _named(await mcp_client.list_tools())
        description = tools["list_meeting_recordings"].description
        assert description is not None
        rendered = description + json.dumps(tools["list_meeting_recordings"].outputSchema)

        assert "no video is returned or reachable here" in description
        assert "list_meeting_transcripts" in description, "where a question about content goes"
        assert "content_correlation_id" in rendered, "and how to get to the right transcript"

    async def test_list_meeting_recordings_relays_the_organiser_only_rule(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """Microsoft's hard constraint, in the words a model has to be able to pass on: delegated
        download is the organiser's alone unless an administrator unblocked participants. The
        negative wording matters most. An unreachable recording is not a missing recording, and
        reporting it as one is a wrong answer nobody can detect.

        The rule itself is read off `content_access`, where the value that triggers it lands, so
        the quote and the three values are asserted over the whole surface. The description keeps
        only the warning, because the wrong answer it prevents is one a model gives before it ever
        looks at the field.
        """
        tools = _named(await mcp_client.list_tools())
        description = tools["list_meeting_recordings"].description
        assert description is not None
        # The whole output schema, `$defs` included: a recording's fields are described there, not
        # inline, and `content_access` carries its three meanings where a model reads the result.
        rendered = description + json.dumps(tools["list_meeting_recordings"].outputSchema)

        assert "Meeting participants don't have permission to download meeting recordings" in (
            rendered
        )
        assert "unless admin unblocks them" in rendered
        assert "An `organizer_only` recording exists but is out of reach" in description
        assert "never report it as missing" in description
        assert "This is NOT a missing recording" in rendered
        assert "organizer_user_id" in rendered, "who to ask for it"
        assert "you_are_the_organizer" in rendered and "organizer_only" in rendered
        assert "Meeting participants don't have permission" in json.dumps(
            tools["list_meeting_recordings"].outputSchema
        ), "the constraint belongs where the result is read, not only in the tool's prose"

    async def test_list_meeting_recordings_names_its_five_answers_and_their_remedies(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The same five-outcome vocabulary the transcript lister establishes, adapted by one word:
        `not_recorded` instead of `not_transcribed`. A model that learned when to wait and when to
        stop for one artifact must not have to learn it again for the other.

        Taught on the `status` field, as its neighbour teaches it. The description keeps one of the
        five, `not_ready`, with the negative attached: it is the answer whose opposite a model
        reports, and it has to be legible before the call rather than only after it.
        """
        tools = _named(await mcp_client.list_tools())
        description = tools["list_meeting_recordings"].description
        status = _object(_properties(tools["list_meeting_recordings"].outputSchema)["status"])
        assert description is not None
        taught = str(status.get("description"))
        rendered = description + json.dumps(tools["list_meeting_recordings"].outputSchema)

        for value in (
            "available",
            "not_ready",
            "not_recorded",
            "scan_incomplete",
            "meeting_not_found",
        ):
            assert f"`{value}`" in taught, value
        assert "`not_ready` means wait" in description
        assert 'not "the call was not recorded"' in description
        assert "Wait and retry" in taught
        assert "NOT 'the call was not recorded'" in taught
        assert "Retrying will not help" in taught
        assert "no availability SLA" in taught, "the inference has to be admitted as one"
        assert "recurring" in rendered and "started_after" in rendered
        assert "publishes no duration field" in rendered, "the duration is derived, and says so"
        assert "Never report this as 'the call was not recorded'" in taught
        assert "is NOT known" in taught, "the fifth answer claims nothing, and has to say so"

    async def test_both_meeting_listers_teach_the_same_status_vocabulary(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """Two artifacts, one vocabulary: the four words that are about neither artifact in
        particular have to be the same, or a model that learned one tool guesses at the other. Only
        the settled absence differs, because that is the only fact that differs.
        """
        tools = _named(await mcp_client.list_tools())
        shared = {"available", "not_ready", "scan_incomplete", "meeting_not_found"}
        statuses = {
            name: str(_object(_properties(tools[name].outputSchema)["status"]).get("description"))
            for name in ("list_meeting_transcripts", "list_meeting_recordings")
        }

        for name, rendered in statuses.items():
            for value in shared:
                assert f"`{value}`" in rendered, f"{name} does not name {value}"
        assert "`not_transcribed`" in statuses["list_meeting_transcripts"]
        assert "`not_recorded`" in statuses["list_meeting_recordings"]
        assert "`not_recorded`" not in statuses["list_meeting_transcripts"]
        assert "`not_transcribed`" not in statuses["list_meeting_recordings"]

    @pytest.mark.parametrize(
        ("tool", "collection"),
        [
            ("list_meeting_transcripts", "transcripts"),
            ("list_meeting_recordings", "recordings"),
        ],
        ids=["transcripts", "recordings"],
    )
    async def test_neither_lister_promises_the_newest_past_its_scan_cap(
        self, mcp_client: Client[FastMCPTransport], tool: str, collection: str
    ) -> None:
        """ "Newest first" is a property of the artifacts one call READ, not of the meeting: the
        read stops at `MAX_ARTIFACT_SCAN` and Microsoft publishes no `$orderby` to ask the newest
        for, so a meeting past that cap can hold a newer artifact than any that came back. Both
        places a model learns the ordering from, the `limit` it chooses with and the list it reads,
        have to say so. "Asking for 3 gives the 3 latest" is the sentence that would not.
        """
        tools = _named(await mcp_client.list_tools())
        limit = _object(_properties(tools[tool].inputSchema)["limit"])
        listed = _object(_properties(tools[tool].outputSchema)[collection])
        rendered = str(limit.get("description")) + str(listed.get("description"))

        assert str(meetings.MAX_ARTIFACT_SCAN) in rendered, "the cap is named where it binds"
        assert "the newest OF THE ONES READ" in str(limit.get("description"))
        assert "the latest of what was READ" in str(listed.get("description"))
        assert "so asking for 3 gives the 3 latest" not in rendered, (
            "the overstatement: past the cap those 3 are the newest of what was read"
        )

    async def test_the_transcript_switch_sends_a_refused_model_to_the_recordings_lister(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The reason the two artifacts are two tools, said where it changes what a model does: the
        tenant switch that blocks transcripts is off by default and leaves recordings alone, so a
        model refused a transcript should still ask whether the meeting was recorded.

        The arrow runs one way. Only a model that has just been refused a transcript needs it, and
        one reading the recordings lister has already chosen recordings, so the fallback is stated
        by `list_meeting_transcripts` alone. The recordings lister points back for content only,
        which is a different question and not a fallback.
        """
        tools = _named(await mcp_client.list_tools())
        recordings_description = tools["list_meeting_recordings"].description
        transcripts_description = tools["list_meeting_transcripts"].description
        assert recordings_description is not None and transcripts_description is not None

        assert "can block transcripts and never recordings" in transcripts_description
        assert "try list_meeting_recordings on refusal" in transcripts_description
        assert "for the words, call list_meeting_transcripts" in recordings_description
        assert "refus" not in recordings_description, (
            "a model reading this one has already chosen recordings; a fallback here is noise"
        )

    async def test_no_description_names_a_tool_this_server_does_not_advertise(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """A description is protocol surface a model reads as fact, so a tool named in one has to
        exist. These tools arrive one per PR, each written knowing the shape of the ones still to
        come. That is how a description comes to promise a tool this commit does not deploy, and
        the model then stops treating what it was given as the answer and calls something that is
        not there.

        Read off the advertised list rather than a written-down one, so the day a tool lands the
        assertion widens by itself and only the stale promise fails.
        """
        tools = _named(await mcp_client.list_tools())
        advertised = set(tools)
        mentioned: set[str] = set()

        for name, tool in tools.items():
            described = " ".join(
                [
                    tool.description or "",
                    *_described(tool.inputSchema),
                    *_described(tool.outputSchema),
                ]
            )
            named = set(_TOOL_MENTION.findall(described))
            mentioned |= named
            assert not named - advertised, (
                f"{name} tells a model about {sorted(named - advertised)}, which this server does "
                + "not advertise — cut the reference, or land the tool in the same PR"
            )

        # Guards the guard: these tools do point a model at one another, so a check that found
        # nothing to check would pass because the pattern stopped matching, not because the
        # descriptions are honest.
        assert len(mentioned) > 1, (
            f"nothing names another tool any more, so this proves nothing: {mentioned}"
        )

    async def test_the_tools_are_marked_read_only(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        tools = _named(await mcp_client.list_tools())

        for tool in tools.values():
            assert tool.annotations is not None
            assert tool.annotations.readOnlyHint is True


class TestCallingThem:
    async def test_get_me_calls_graph_with_the_exchanged_token(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        route = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        result = await mcp_client.call_tool("get_me", {})

        assert _structured(result)["email"] == "ada@example.invalid"
        assert route.calls.last.request.headers["authorization"] == f"Bearer {OBO_TOKEN}"
        assert obo.requested_scopes == [("https://graph.microsoft.com/User.Read",)]

    async def test_list_chats_returns_a_structured_page(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        graph.get("/me/chats").mock(return_value=httpx.Response(200, json=_CHATS))

        result = await mcp_client.call_tool("list_chats", {"limit": 5})

        body = _structured(result)
        assert "truncated" not in body, "a window says whether it may have more by being full"
        listed = cast("Sequence[Mapping[str, object]]", body["chats"])
        assert [chat["chat_id"] for chat in listed] == ["19:release@thread.v2"]
        assert listed[0]["last_message_at"] == "2026-02-11T09:15:22.310000Z"
        assert obo.requested_scopes == [("https://graph.microsoft.com/Chat.Read",)]

    async def test_list_teams_sends_no_query_and_spends_only_its_own_permission(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """Both halves are things only an end-to-end call can show.

        Nothing on the wire: `/me/joinedTeams` supports no OData query parameter at all, so a
        `$top` or a `$select` reaching Graph is a 400 rather than a narrower answer, and a request
        configuration built by one tool can leak into another's call. One scope on the exchange:
        the token is redeemed per tool, so a tenant that withholds the broad channel permission
        still lists its teams, and a tool that quietly asked for the registry's union would take
        that away without any schema changing.
        """
        route = graph.get("/me/joinedTeams").mock(return_value=httpx.Response(200, json=_TEAMS))

        listed = _structured(await mcp_client.call_tool("list_teams", {}))

        assert "truncated" not in listed, "a window says whether it may have more by being full"
        found = cast("Sequence[Mapping[str, object]]", listed["teams"])
        assert [team["team_id"] for team in found] == [_TEAM_ID]
        assert [team["is_archived"] for team in found] == [False]
        assert not route.calls.last.request.url.params
        assert route.calls.last.request.headers["authorization"] == f"Bearer {OBO_TOKEN}"
        assert obo.requested_scopes == [("https://graph.microsoft.com/Team.ReadBasic.All",)]

    async def test_a_model_walks_from_its_teams_to_a_reply_it_can_read(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """The channel side end to end, with every id taken from the previous answer exactly as a
        model would take it: which teams am I in, what channels are in this team, what was posted
        in this channel, and then the reply's own handle, resolved.

        Graph addresses a reply under the post it answers, so only browsing can produce a handle
        for one: a search hit on a reply carries the root-post shape and Graph answers it 404. The
        browse mints the reply's handle and `read_message` resolves it.

        The token is redeemed per tool, so a tenant that grants the two basic channel scopes and
        withholds the broad message one is refused at the third step rather than the first.
        """
        teams = graph.get("/me/joinedTeams").mock(return_value=httpx.Response(200, json=_TEAMS))
        listing = graph.get(_CHANNELS_PATH).mock(return_value=httpx.Response(200, json=_CHANNELS))
        posts = graph.get(_CHANNEL_MESSAGES_PATH).mock(
            return_value=httpx.Response(200, json=_CHANNEL_POSTS)
        )
        read = graph.get(_REPLY_PATH).mock(return_value=httpx.Response(200, json=_REPLY))

        listed = _structured(await mcp_client.call_tool("list_teams", {}))
        found = cast("Sequence[Mapping[str, object]]", listed["teams"])
        team_id = found[0]["team_id"]
        channels = _structured(await mcp_client.call_tool("list_channels", {"team_id": team_id}))
        in_team = cast("Sequence[Mapping[str, object]]", channels["channels"])
        channel_id = in_team[0]["channel_id"]
        browsed = _structured(
            await mcp_client.call_tool(
                "browse_channel", {"team_id": team_id, "channel_id": channel_id}
            )
        )
        messages = cast("Sequence[Mapping[str, object]]", browsed["messages"])
        result = _structured(
            await mcp_client.call_tool("read_message", {"uri": messages[1]["uri"]})
        )

        assert (team_id, channel_id) == (_TEAM_ID, _CHANNEL_ID)
        assert in_team[0]["display_name"] == "General"
        assert in_team[0]["membership_type"] == "standard"
        assert all(route.called for route in (teams, listing, posts, read))
        assert [message["message_id"] for message in messages] == [_ROOT_POST_ID, _REPLY_ID]
        assert messages[0]["text"] == "Release plan for Friday", "browsing returns the whole post"
        assert messages[1]["reply_to_id"] == _ROOT_POST_ID
        assert messages[1]["uri"] == _REPLY_URI
        assert result["text"] == "agreed, Friday works"
        assert result["uri"] == _REPLY_URI
        assert read.calls.last.request.headers["authorization"] == f"Bearer {OBO_TOKEN}"
        assert obo.requested_scopes == [
            ("https://graph.microsoft.com/Team.ReadBasic.All",),
            ("https://graph.microsoft.com/Channel.ReadBasic.All",),
            ("https://graph.microsoft.com/ChannelMessage.Read.All",),
            (
                "https://graph.microsoft.com/Chat.Read",
                "https://graph.microsoft.com/ChannelMessage.Read.All",
            ),
        ], "each tool exchanges a token for the permissions its own request needs"

    @pytest.mark.usefixtures("obo")
    async def test_the_same_channel_page_answers_differently_with_and_without_microsofts_cursor(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """The signal this tool cannot infer. Without it these two answers are byte-identical: one
        page of posts WITH an `@odata.nextLink` and the same page without one, so a caller could
        not tell "that was the whole channel" from "Microsoft says there is more".

        It is the one list here where that is not derivable. Everywhere else the walk underneath
        followed Microsoft's paging to the end of the collection, so a short answer IS the end.
        This tool makes one request against a channel Microsoft rate-limits to about one a second
        for the whole connector, and drops system messages out of the page after Microsoft counted
        them into it. So the cursor is read and reported when asked for, and it is accurate.
        """
        posts = {"value": [{**_CHANNEL_POSTS["value"][0], "replies": []}]}
        with_more = {
            **posts,
            "@odata.nextLink": f"{GRAPH_V1}{_CHANNEL_MESSAGES_PATH}?$skiptoken=synthetic",
        }
        route = graph.get(_CHANNEL_MESSAGES_PATH).mock(
            return_value=httpx.Response(200, json=with_more)
        )
        ids = {"team_id": _TEAM_ID, "channel_id": _CHANNEL_ID}

        unasked = _structured(await mcp_client.call_tool("browse_channel", ids))
        told = _structured(
            await mcp_client.call_tool(
                "browse_channel", {**ids, "include_window_completeness": True}
            )
        )
        route.mock(return_value=httpx.Response(200, json=posts))
        whole = _structured(
            await mcp_client.call_tool(
                "browse_channel", {**ids, "include_window_completeness": True}
            )
        )

        assert unasked["more_posts_in_channel"] is None, "null unless a caller asks"
        assert unasked["posts_cut_to_limit"] is None
        assert told["more_posts_in_channel"] is True, "Microsoft's own cursor, read as it came"
        assert whole["more_posts_in_channel"] is False, "the same page, its cursor taken off"
        assert told["posts_cut_to_limit"] is False, "the window closed over nothing Microsoft sent"
        assert told["messages"] == unasked["messages"] == whole["messages"], (
            "asking about completeness changes what is reported and never what was read"
        )
        assert route.call_count == 3, "one request per call, and the cursor still never followed"

    @pytest.mark.usefixtures("obo")
    async def test_a_collection_microsoft_never_ends_is_refused_in_eleven_requests(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """The bound on pages carrying nothing, measured where it is spent rather than read off the
        constant that claims it. An empty page carrying a cursor means keep going, so a collection
        that answers only those has to be given up on, and it must FAIL rather than answer: every
        short answer above this walk means a cap. From `list_chats` it would mean the user has no
        more chats, and from `list_meeting_transcripts` it would mean a meeting was never
        transcribed. Eleven requests each, the caller's own first page and the run of empty ones
        this walk follows before refusing. Both tools are here because they pass different
        `max_scanned` values and this bound must not vary with either: an empty page spends no scan
        budget at all.
        """
        chats = graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200, json={"value": [], "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=loop"}
            )
        )

        meeting = graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        listing = graph.get(_TRANSCRIPTS_PATH).mock(
            return_value=httpx.Response(
                200,
                json={
                    "value": [],
                    "@odata.nextLink": f"{GRAPH_V1}{_TRANSCRIPTS_PATH}?$skiptoken=loop",
                },
            )
        )

        listed = await mcp_client.call_tool("list_chats", {}, raise_on_error=False)
        transcribed = await mcp_client.call_tool(
            "list_meeting_transcripts", {"meeting_uri": _MEETING_URI}, raise_on_error=False
        )

        assert listed.is_error, "a walk that gave up must not answer short: a short answer is a cap"
        assert "pages in a row" in _error_text(listed), "and the count is what an operator needs"
        assert chats.call_count == 11, "the caller's own page and the run of empty ones followed"
        assert transcribed.is_error, (
            "and a transcript listing that answered short would report a meeting as never "
            "transcribed on the strength of a collection nobody reached the end of"
        )
        assert meeting.called
        assert listing.call_count == 11, (
            "the same eleven, whatever `max_scanned` this tool passes: an empty page spends no "
            "scan budget, so the two bounds are counted separately"
        )

    async def test_search_messages_returns_hits_with_handles_and_no_invented_total(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """The search call end to end: one POST to Microsoft's search index, hits carrying a handle
        that names the exact message matched, and both search permissions on the exchanged
        token."""
        route = graph.post("/search/query").mock(return_value=httpx.Response(200, json=_SEARCH))

        result = await mcp_client.call_tool("search_messages", {"query": "release"})

        body = _structured(result)
        assert body["next_offset"] is None, "the last page of results, and the whole of saying so"
        assert "truncated" not in body
        assert "total" not in body, "Graph's `total` is a page count for Teams, not a match count"
        found = cast("Sequence[Mapping[str, object]]", body["messages"])
        assert [message["uri"] for message in found] == [
            "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000"
        ]
        assert route.calls.last.request.headers["authorization"] == f"Bearer {OBO_TOKEN}"
        assert obo.requested_scopes == [
            (
                "https://graph.microsoft.com/Chat.Read",
                "https://graph.microsoft.com/ChannelMessage.Read.All",
            )
        ]

    async def test_a_handle_from_a_search_result_reads_the_message_behind_it(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """Search returns a handle and no body, and the handle, passed back verbatim as a model
        would, resolves into the text."""
        search = graph.post("/search/query").mock(return_value=httpx.Response(200, json=_SEARCH))
        read = graph.get(_MESSAGE_PATH).mock(return_value=httpx.Response(200, json=_MESSAGE))

        found = _structured(await mcp_client.call_tool("search_messages", {"query": "release"}))
        hits = cast("Sequence[Mapping[str, object]]", found["messages"])
        uri = hits[0]["uri"]
        result = await mcp_client.call_tool("read_message", {"uri": uri})

        assert search.called
        body = _structured(result)
        assert body["uri"] == _MESSAGE_URI == uri
        assert body["text"] == "Let's cut the release on Friday & tell @Grace Hopper."
        assert body["event"] is None
        mentions = cast("Sequence[Mapping[str, object]]", body["mentions"])
        assert [mention["user_id"] for mention in mentions] == [
            "00000000-0000-4000-8000-000000000002"
        ]
        sender = cast("Mapping[str, object]", body["sender"])
        assert sender["display_name"] == "Ada Lovelace"
        assert read.calls.last.request.headers["authorization"] == f"Bearer {OBO_TOKEN}"
        assert obo.requested_scopes[-1] == (
            "https://graph.microsoft.com/Chat.Read",
            "https://graph.microsoft.com/ChannelMessage.Read.All",
        ), "the exchange happens before the handle is parsed, so it asks for both surfaces"

    @pytest.mark.usefixtures("obo")
    async def test_reading_a_system_event_says_what_happened_rather_than_nothing(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """A handle can resolve to a message Graph gives no author and no text for. Answering with
        an empty message would read as "they said nothing". The event is what happened."""
        _ = graph.get(_MESSAGE_PATH).mock(return_value=httpx.Response(200, json=_SYSTEM_MESSAGE))

        result = await mcp_client.call_tool("read_message", {"uri": _MESSAGE_URI})

        body = _structured(result)
        assert body["event"] == "members joined"
        assert body["text"] is None
        assert body["sender"] is None
        assert "systemEventMessage" not in json.dumps(body), (
            "the literal tag Graph puts in the body is not an answer"
        )

    @pytest.mark.usefixtures("obo")
    async def test_the_message_text_reaches_the_caller_and_no_log_or_span(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        caplog: pytest.LogCaptureFixture,
        recorded_spans: InMemorySpanExporter,
    ) -> None:
        """A message body is as sensitive as the query that found it, so the rule search is held to
        holds here too, over the whole call and both destinations."""
        secret = "acquisition-of-northwind-traders"
        payload = {**_MESSAGE, "body": {"contentType": "text", "content": secret}}
        _ = graph.get(_MESSAGE_PATH).mock(return_value=httpx.Response(200, json=payload))
        caplog.set_level(logging.DEBUG)

        result = await mcp_client.call_tool("read_message", {"uri": _MESSAGE_URI})

        assert _structured(result)["text"] == secret, "the text has to have been returned"
        for record in caplog.records:
            assert secret not in _record_text(record), f"logged by {record.name}"
        spans = recorded_spans.get_finished_spans()
        assert spans, "nothing was traced, so the span half of this test asserts over an empty list"
        for span in spans:
            assert secret not in str(span.attributes), f"on span {span.name}"

    @pytest.mark.usefixtures("obo")
    async def test_a_channel_post_reaches_the_caller_and_no_log_or_span(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        caplog: pytest.LogCaptureFixture,
        recorded_spans: InMemorySpanExporter,
    ) -> None:
        """A channel post is message content like any other, and this tool returns a page of it at
        once, so the rule search and read are held to holds here too, over the whole call."""
        secret = "acquisition-of-northwind-traders"
        post = {
            **_CHANNEL_POSTS["value"][0],
            "body": {"contentType": "text", "content": secret},
            "replies": [],
        }
        _ = graph.get(_CHANNEL_MESSAGES_PATH).mock(
            return_value=httpx.Response(200, json={"value": [post]})
        )
        caplog.set_level(logging.DEBUG)

        result = await mcp_client.call_tool(
            "browse_channel", {"team_id": _TEAM_ID, "channel_id": _CHANNEL_ID}
        )

        messages = cast("Sequence[Mapping[str, object]]", _structured(result)["messages"])
        assert messages[0]["text"] == secret, "the post has to have been returned"
        for record in caplog.records:
            assert secret not in _record_text(record), f"logged by {record.name}"
        spans = recorded_spans.get_finished_spans()
        assert spans, "nothing was traced, so the span half of this test asserts over an empty list"
        for span in spans:
            assert secret not in str(span.attributes), f"on span {span.name}"

    @pytest.mark.usefixtures("obo")
    async def test_a_multi_word_query_reaches_graph_as_words_over_the_real_protocol(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """A two-word question has to arrive at Microsoft's index as two terms it will AND, not as
        one quoted phrase that only matches them side by side."""
        route = graph.post("/search/query").mock(return_value=httpx.Response(200, json=_SEARCH))

        _ = await mcp_client.call_tool("search_messages", {"query": "cut the release"})

        assert _search_query_string(route) == "cut the release"

    @pytest.mark.usefixtures("obo")
    async def test_a_search_with_no_criteria_is_refused_and_says_what_to_add(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """FastMCP validates arguments against the signature, not the advertised schema, so the
        `anyOf` alone would not stop this. Graph would answer with an arbitrary slice of everything
        the user can read, which looks exactly like a result set."""
        route = graph.post("/search/query").mock(return_value=httpx.Response(200, json=_SEARCH))

        result = await mcp_client.call_tool("search_messages", {"size": 5}, raise_on_error=False)

        assert result.is_error
        assert not route.called
        assert "query" in _error_text(result) and "sent_after" in _error_text(result)

    @pytest.mark.usefixtures("obo")
    async def test_the_search_text_reaches_graph_and_nothing_else(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        caplog: pytest.LogCaptureFixture,
        recorded_spans: InMemorySpanExporter,
    ) -> None:
        """What a user searched their own messages for is as sensitive as the messages: it names
        people, deals and diagnoses. `services/teams-mcp` had to go back and strip query terms out
        of its spans and logs, so this connector never puts them there. Both destinations are
        checked: the log capture covers everything this process emits during the call, ours and
        FastMCP's own, and the Graph SDK opens a dozen spans per request, so `recorded_spans`
        refuses to pass on an empty list.
        """
        route = graph.post("/search/query").mock(return_value=httpx.Response(200, json=_SEARCH))
        secret = "acquisition-of-northwind-traders"
        caplog.set_level(logging.DEBUG)

        _ = await mcp_client.call_tool(
            "search_messages", {"query": secret, "sender": "ada@example.invalid"}
        )

        assert secret in route.calls.last.request.content.decode(), (
            "the query has to have reached Graph, or this test proves nothing"
        )
        for record in caplog.records:
            assert secret not in _record_text(record), f"logged by {record.name}"
        spans = recorded_spans.get_finished_spans()
        assert spans, "nothing was traced, so the span half of this test asserts over an empty list"
        for span in spans:
            assert secret not in str(span.attributes), f"on span {span.name}"

    async def test_an_argument_this_tool_does_not_have_is_refused(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        route = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        result = await mcp_client.call_tool(
            "get_me", {"user_id": "00000000-0000-4000-8000-000000000002"}, raise_on_error=False
        )

        assert result.is_error
        assert not route.called
        assert not obo.requested_scopes

    async def test_a_model_walks_from_a_meeting_chat_to_what_was_said_in_the_meeting(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """The meeting path end to end, with every value taken from the previous answer exactly as
        a model would take it: which meetings are there (`list_chats`, because a meeting chat *is*
        the index), what transcripts does this one have, and then the words, speaker-attributed and
        timestamped rather than a link to a file. The oracle connector reaches a transcript only
        through an opaque URI it got from a calendar read. This walk needs no calendar permission
        at all, and it ends in text.
        """
        chats_route = graph.get("/me/chats").mock(
            return_value=httpx.Response(200, json=_MEETING_CHATS)
        )
        meeting = graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        listing = graph.get(_TRANSCRIPTS_PATH).mock(
            return_value=httpx.Response(200, json=_TRANSCRIPTS)
        )
        content = graph.get(_CONTENT_PATH).mock(
            return_value=httpx.Response(
                200, content=_TRANSCRIPT_VTT.encode(), headers={"content-type": "text/vtt"}
            )
        )

        listed = _structured(await mcp_client.call_tool("list_chats", {"limit": 5}))
        found = cast("Sequence[Mapping[str, object]]", listed["chats"])
        meeting_uri = found[0]["meeting_uri"]
        available = _structured(
            await mcp_client.call_tool("list_meeting_transcripts", {"meeting_uri": meeting_uri})
        )
        listed_transcripts = cast("Sequence[Mapping[str, object]]", available["transcripts"])
        read = _structured(
            await mcp_client.call_tool("read_transcript", {"uri": listed_transcripts[0]["uri"]})
        )

        assert all(route.called for route in (chats_route, meeting, listing, content))
        assert found[0]["chat_type"] == "meeting"
        assert meeting_uri == _MEETING_URI, "the handle one tool minted is what the other took"
        assert available["status"] == "available"
        assert available["subject"] == "Pricing review"
        assert available["meeting_id"] == _MEETING_ID
        assert available["scan_incomplete"] is None, "nobody asked how far the read got"
        assert [item["transcript_id"] for item in listed_transcripts] == [_TRANSCRIPT_ID]
        assert read["speaker_attribution"] is True
        turns = cast("Sequence[Mapping[str, object]]", read["turns"])
        assert [(turn["speaker"], turn["start_seconds"]) for turn in turns] == [
            ("Grace Hopper", 16.246),
            ("Ada Lovelace", 62.0),
        ]
        assert turns[0]["text"] == "We should raise the floor price by three per cent."
        assert read["next_offset"] is None
        assert content.calls.last.request.headers["authorization"] == f"Bearer {OBO_TOKEN}"
        assert content.calls.last.request.headers["accept"] == "text/vtt"
        assert obo.requested_scopes == [
            ("https://graph.microsoft.com/Chat.Read",),
            (
                "https://graph.microsoft.com/OnlineMeetings.Read",
                "https://graph.microsoft.com/OnlineMeetingTranscript.Read.All",
            ),
            ("https://graph.microsoft.com/OnlineMeetingTranscript.Read.All",),
        ], "the reader needs only transcript access; resolving a join URL is the lister's job"

    @pytest.mark.usefixtures("obo")
    @pytest.mark.parametrize(
        ("tool", "path", "collection", "items", "identifier"),
        [
            (
                "list_meeting_transcripts",
                _TRANSCRIPTS_PATH,
                "transcripts",
                _SERIES_TRANSCRIPTS,
                "transcript_id",
            ),
            (
                "list_meeting_recordings",
                _RECORDINGS_PATH,
                "recordings",
                _SERIES_RECORDINGS,
                "recording_id",
            ),
        ],
        ids=["transcripts", "recordings"],
    )
    async def test_asking_for_the_latest_of_a_series_answers_with_the_latest(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        tool: str,
        path: str,
        collection: str,
        items: dict[str, object],
        identifier: str,
    ) -> None:
        """ "The latest transcript of this series", the question both listers exist for. Microsoft
        answers these collections in an order of its own, so a `limit` applied before ordering
        returns an arbitrary handful sorted among themselves: a model asking for the newest one
        gets whichever occurrence Microsoft happened to put first, with nothing in the answer to
        say so. Microsoft's order here puts the oldest first, which is what that shape would
        return.
        """
        _ = graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        _ = graph.get(path).mock(return_value=httpx.Response(200, json=items))
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        answer = _structured(
            await mcp_client.call_tool(
                tool,
                {"meeting_uri": _MEETING_URI, "limit": 1, "include_scan_completeness": True},
            )
        )

        listed = cast("Sequence[Mapping[str, object]]", answer[collection])
        assert [item[identifier] for item in listed] == ["week-3"], "the newest, not the first"
        assert answer["status"] == "available"
        assert len(listed) == 1, "a full window: the two older occurrences are behind it"
        assert answer["scan_incomplete"] is False, (
            "and the collection was read to the end, so this IS the meeting's latest — the two "
            "facts one flag could not tell apart"
        )

    @pytest.mark.parametrize(
        ("tool", "path", "collection", "identifier"),
        [
            ("list_meeting_transcripts", _TRANSCRIPTS_PATH, "transcripts", "transcript_id"),
            ("list_meeting_recordings", _RECORDINGS_PATH, "recordings", "recording_id"),
        ],
        ids=["transcripts", "recordings"],
    )
    async def test_a_meeting_larger_than_one_call_reads_answers_within_what_it_read(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
        tool: str,
        path: str,
        collection: str,
        identifier: str,
    ) -> None:
        """The rare meeting both promises have to be exact about: a series that ran daily for most
        of a year, so its collection is longer than one call reads. Asking for the newest returns
        `day-199`, the newest of the artifacts READ, never the meeting's actual newest, which sits
        past the cap where nothing here can see it. The opt-in `scan_incomplete` is the answer's
        own admission of that. A window over the part that was not read answers `scan_incomplete`
        whether it is wide or narrow, because the window is applied to what came back. Narrowing it
        is not a remedy, so neither tool offers it as one.
        """
        _ = graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        _ = graph.get(path).mock(return_value=httpx.Response(200, json=_daily_series()))
        _ = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        newest = _structured(
            await mcp_client.call_tool(
                tool,
                {"meeting_uri": _MEETING_URI, "limit": 1, "include_scan_completeness": True},
            )
        )
        wide = _structured(
            await mcp_client.call_tool(
                tool,
                {
                    "meeting_uri": _MEETING_URI,
                    "started_after": _day(meetings.MAX_ARTIFACT_SCAN).date().isoformat(),
                    "started_before": _day(_PAST_THE_CAP - 1).date().isoformat(),
                },
            )
        )
        narrow = _structured(
            await mcp_client.call_tool(
                tool,
                {
                    "meeting_uri": _MEETING_URI,
                    "started_after": _day(250).date().isoformat(),
                    "started_before": _day(250).date().isoformat(),
                },
            )
        )

        listed = cast("Sequence[Mapping[str, object]]", newest[collection])
        assert len(obo.requested_scopes) == 3, "one delegated exchange per call, all three made"
        assert [item[identifier] for item in listed] == ["day-199"], "the newest of what was read"
        assert newest["scan_incomplete"] is True, (
            "the read stopped at the cap, and a caller that asked has to be told"
        )
        assert wide["status"] == "scan_incomplete"
        assert wide["scan_incomplete"] is None, "nothing asked about the scan on these two calls"
        assert (narrow["status"], narrow[collection]) == (wide["status"], wide[collection]), (
            "a narrower window is the same call over the same artifacts, so it is not a remedy"
        )

    async def test_a_model_walks_from_a_meeting_chat_to_whether_the_call_was_recorded(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """The question this tool exists to answer, end to end: was Tuesday's call recorded, how
        long is it, and can I get at it. Every value is taken from the previous answer, and the
        meeting chat's `meeting_uri` is the same handle the transcript lister takes.

        The recording here is somebody else's, the common case: Microsoft permits only the
        organiser to download a recording, so the answer has to be "there is a 47-minute recording,
        the organiser has it, and here is the transcript instead", never "there is no recording".
        No byte of video is fetched, and the mocked content route proves it.
        """
        chats_route = graph.get("/me/chats").mock(
            return_value=httpx.Response(200, json=_MEETING_CHATS)
        )
        meeting = graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        listing = graph.get(_RECORDINGS_PATH).mock(
            return_value=httpx.Response(200, json=_RECORDINGS)
        )
        me = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        video = graph.get(_RECORDING_CONTENT_PATH).mock(
            return_value=httpx.Response(200, content=b"synthetic mp4 bytes")
        )

        listed = _structured(await mcp_client.call_tool("list_chats", {"limit": 5}))
        found = cast("Sequence[Mapping[str, object]]", listed["chats"])
        meeting_uri = found[0]["meeting_uri"]
        available = _structured(
            await mcp_client.call_tool("list_meeting_recordings", {"meeting_uri": meeting_uri})
        )

        assert all(route.called for route in (chats_route, meeting, listing, me))
        assert not video.called, "listing a recording must never fetch it"
        assert available["status"] == "available"
        assert available["subject"] == "Pricing review"
        assert available["scan_incomplete"] is None, "nobody asked how far the read got"
        recorded = cast("Sequence[Mapping[str, object]]", available["recordings"])
        assert len(recorded) == 1
        assert recorded[0]["duration_seconds"] == pytest.approx(2831.913)
        assert recorded[0]["content_access"] == "organizer_only"
        assert recorded[0]["organizer_user_id"] == "00000000-0000-4000-8000-000000000002"
        assert (
            recorded[0]["content_correlation_id"]
            == _TRANSCRIPTS["value"][0]["contentCorrelationId"]
        ), "the bridge to the readable artifact is Microsoft's own, and both tools report it"
        assert listing.calls.last.request.headers["authorization"] == f"Bearer {OBO_TOKEN}"
        assert obo.requested_scopes == [
            ("https://graph.microsoft.com/Chat.Read",),
            (
                "https://graph.microsoft.com/OnlineMeetings.Read",
                "https://graph.microsoft.com/OnlineMeetingRecording.Read.All",
                "https://graph.microsoft.com/User.Read",
            ),
        ], "resolving the meeting, listing recordings, and finding out who is asking"

    @pytest.mark.usefixtures("obo")
    async def test_the_tenant_transcript_switch_does_not_take_the_recording_answer_with_it(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """The reason these are two tools rather than one. Microsoft's Graph access to transcripts
        is a tenant switch that is OFF BY DEFAULT and applies to transcript resources only, so in
        the commonest tenant the transcript listing 403s while the recording listing answers. One
        tool listing both artifacts would fail the whole call here, and a model would be told
        nothing about a recording that is right there.
        """
        graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        graph.get(_TRANSCRIPTS_PATH).mock(return_value=httpx.Response(403, json=_TENANT_SWITCH_OFF))
        graph.get(_RECORDINGS_PATH).mock(return_value=httpx.Response(200, json=_RECORDINGS))
        graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        refused = await mcp_client.call_tool(
            "list_meeting_transcripts", {"meeting_uri": _MEETING_URI}, raise_on_error=False
        )
        answered = await mcp_client.call_tool(
            "list_meeting_recordings", {"meeting_uri": _MEETING_URI}, raise_on_error=False
        )

        assert refused.is_error
        assert "EnableGraphTranscriptAccess" in _error_text(refused)
        assert not answered.is_error, "the switch Microsoft scopes to transcripts must stop there"
        body = _structured(answered)
        assert body["status"] == "available"
        assert len(cast("Sequence[object]", body["recordings"])) == 1

    @pytest.mark.usefixtures("obo")
    async def test_nothing_about_a_recording_reaches_a_log_or_a_span(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        caplog: pytest.LogCaptureFixture,
        recorded_spans: InMemorySpanExporter,
    ) -> None:
        """A meeting's subject is content: "Northwind acquisition: final terms" says most of what
        the meeting was about, and this tool returns one for a meeting nobody may even download. So
        the rule the rest of the surface is held to holds here too, over the whole call: the
        subject reaches the caller and no log line and no span attribute anywhere in the process."""
        secret = "acquisition-of-northwind-traders"
        meeting = {"value": [{**_MEETING["value"][0], "subject": secret}]}
        graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=meeting))
        graph.get(_RECORDINGS_PATH).mock(return_value=httpx.Response(200, json=_RECORDINGS))
        graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        caplog.set_level(logging.DEBUG)

        result = await mcp_client.call_tool(
            "list_meeting_recordings", {"meeting_uri": _MEETING_URI}
        )

        assert _structured(result)["subject"] == secret, "the subject has to have been returned"
        for record in caplog.records:
            assert secret not in _record_text(record), f"logged by {record.name}"
        spans = recorded_spans.get_finished_spans()
        assert spans, "nothing was traced, so the span half of this test asserts over an empty list"
        for span in spans:
            assert secret not in str(span.attributes), f"on span {span.name}"

    @pytest.mark.usefixtures("obo")
    async def test_the_transcript_text_reaches_the_caller_and_no_log_or_span(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        caplog: pytest.LogCaptureFixture,
        recorded_spans: InMemorySpanExporter,
    ) -> None:
        """A transcript is the most sensitive content this connector touches, a verbatim record of
        what people said in a room, so the rule search and read are held to is tightest here: the
        words reach the caller and no log line and no span attribute anywhere in the process."""
        secret = "acquisition-of-northwind-traders"
        vtt = f"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v Ada Lovelace>{secret}</v>\n"
        graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        graph.get(_TRANSCRIPTS_PATH).mock(return_value=httpx.Response(200, json=_TRANSCRIPTS))
        _ = graph.get(_CONTENT_PATH).mock(return_value=httpx.Response(200, content=vtt.encode()))
        caplog.set_level(logging.DEBUG)

        result = await mcp_client.call_tool(
            "read_transcript",
            {"uri": f"teams:///transcripts/{_MEETING_ID}/{_TRANSCRIPT_ID}"},
        )

        turns = cast("Sequence[Mapping[str, object]]", _structured(result)["turns"])
        assert turns[0]["text"] == secret, "the transcript has to have been returned"
        for record in caplog.records:
            assert secret not in _record_text(record), f"logged by {record.name}"
        spans = recorded_spans.get_finished_spans()
        assert spans, "nothing was traced, so the span half of this test asserts over an empty list"
        for span in spans:
            assert secret not in str(span.attributes), f"on span {span.name}"

    @pytest.mark.usefixtures("obo")
    async def test_a_transcript_is_read_narrowed_to_a_speaker_and_to_a_stretch_of_the_meeting(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """The two shapes a model reaches for: "what did she say" and "what was said after that
        point". An hour of meeting is thousands of turns, and a model that can only ask for all of
        them spends its context on the transcript instead of the answer.
        """
        content = graph.get(_CONTENT_PATH).mock(
            return_value=httpx.Response(200, content=_TRANSCRIPT_VTT.encode())
        )
        uri = f"teams:///transcripts/{_MEETING_ID}/{_TRANSCRIPT_ID}"

        by_speaker = _structured(
            await mcp_client.call_tool("read_transcript", {"uri": uri, "speaker": "grace"})
        )
        by_time = _structured(
            await mcp_client.call_tool("read_transcript", {"uri": uri, "from_seconds": 20})
        )

        assert [
            turn["speaker"] for turn in cast("Sequence[Mapping[str, object]]", by_speaker["turns"])
        ] == ["Grace Hopper"]
        assert by_speaker["speaker_attribution"] is True
        assert by_speaker["next_offset"] is None, "one turn matched and one turn came back"
        turns = cast("Sequence[Mapping[str, object]]", by_time["turns"])
        assert [turn["start_seconds"] for turn in turns] == [62.0]
        assert content.call_count == 2, "paging and filtering are over the parsed turns, not Graph"

    @pytest.mark.usefixtures("obo")
    async def test_a_padded_speaker_filter_still_names_the_speaker_over_the_protocol(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """Padding survives the boundary: nothing between the client and the filter trims it. A miss
        here answers "she said nothing", the outcome the blank-speaker refusal exists to prevent."""
        _ = graph.get(_CONTENT_PATH).mock(
            return_value=httpx.Response(200, content=_TRANSCRIPT_VTT.encode())
        )

        read = _structured(
            await mcp_client.call_tool(
                "read_transcript",
                {
                    "uri": f"teams:///transcripts/{_MEETING_ID}/{_TRANSCRIPT_ID}",
                    "speaker": " grace ",
                },
            )
        )

        assert [
            turn["speaker"] for turn in cast("Sequence[Mapping[str, object]]", read["turns"])
        ] == ["Grace Hopper"]

    @pytest.mark.usefixtures("obo")
    @pytest.mark.parametrize(
        ("filters", "named"),
        [
            ({"from_seconds": 60, "to_seconds": 30}, "from_seconds"),
            ({"speaker": ""}, "speaker"),
            ({"speaker": "   "}, "speaker"),
            ({"speaker": "\t\n"}, "speaker"),
        ],
        ids=["inverted-window", "empty-speaker", "blank-speaker", "tabbed-speaker"],
    )
    async def test_a_filter_no_transcript_could_satisfy_is_refused_before_any_graph_request(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        filters: Mapping[str, object],
        named: str,
    ) -> None:
        """A window that ends before it starts, and a speaker that names nobody, both match nothing
        by construction. An empty page would read as "she said nothing in the meeting", a wrong
        answer nobody can detect. The refusal names the parameter and costs no Graph request."""
        content = graph.get(_CONTENT_PATH).mock(
            return_value=httpx.Response(200, content=_TRANSCRIPT_VTT.encode())
        )

        result = await mcp_client.call_tool(
            "read_transcript",
            {"uri": f"teams:///transcripts/{_MEETING_ID}/{_TRANSCRIPT_ID}", **filters},
            raise_on_error=False,
        )

        assert result.is_error
        assert named in _error_text(result), _error_text(result)
        assert not content.called


class TestTheTransportTheToolsShare:
    """One transport for the whole process, and why nothing here asserts that it is closed.

    This class used to assert `is_closed` after the lifespan exited, and it passed on a lie.
    `httpx.AsyncClient.aclose()` sets that flag on the client and then delegates to
    `self._transport.aclose()`, and the transport a Graph client carries is `AsyncGraphTransport`,
    which never overrides `aclose` and so inherits the `pass` in `httpx.AsyncBaseTransport`. The
    connection pool underneath survives every shutdown. Upstream bug, open and unanswered:
    microsoft/kiota-python#494. So the lifespan no longer calls `aclose()`, and with it went the
    only thing that set the flag.
    """

    async def test_every_tool_is_handed_the_same_transport(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One transport, built once, for every tool in the process.

        A transport per call would mean a cold TLS handshake and a leaked connection pool per call.
        """
        built: list[httpx.AsyncClient] = []

        def record(settings: GraphSettings) -> httpx.AsyncClient:
            transport = create_graph_transport(settings)
            built.append(transport)
            return transport

        monkeypatch.setattr("office_mcp.app.create_graph_transport", record)

        async with Client(FastMCPTransport(_server_of(_build_app()))) as client:
            tools = await client.list_tools()

        assert tools, "no tools registered, so sharing one transport asserts nothing"
        assert len(built) == 1, f"{len(built)} transports built for one app"


class TestWhatAModelIsToldWhenGraphRefuses:
    async def test_a_missing_permission_names_the_permission(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        graph.get("/me").mock(
            return_value=httpx.Response(
                403,
                headers={"request-id": "synthetic-request-id"},
                json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}},
            )
        )

        result = await mcp_client.call_tool("get_me", {}, raise_on_error=False)

        assert result.is_error
        message = _error_text(result)
        assert "User.Read" in message
        assert "administrator" in message
        assert "synthetic-request-id" in message
        assert obo.requested_scopes

    @pytest.mark.parametrize(
        ("tool", "arguments", "path", "permission", "not_named"),
        [
            ("list_teams", {}, "/me/joinedTeams", "Team.ReadBasic.All", "Channel.ReadBasic.All"),
            (
                "list_channels",
                {"team_id": _TEAM_ID},
                _CHANNELS_PATH,
                "Channel.ReadBasic.All",
                "Team.ReadBasic.All",
            ),
            (
                "browse_channel",
                {"team_id": _TEAM_ID, "channel_id": _CHANNEL_ID},
                _CHANNEL_MESSAGES_PATH,
                "ChannelMessage.Read.All",
                "Channel.ReadBasic.All",
            ),
        ],
    )
    @pytest.mark.usefixtures("obo")
    async def test_each_channel_tool_names_only_the_permission_its_own_request_needs(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        tool: str,
        arguments: dict[str, str],
        path: str,
        permission: str,
        not_named: str,
    ) -> None:
        """Three requests, three delegated permissions. A tenant that grants the two basic ones and
        withholds the broad message permission is the common case, so naming the wrong one sends an
        administrator after a permission that was never missing. Graph's 403 says only that
        something was forbidden.
        """
        _ = graph.get(path).mock(
            return_value=httpx.Response(
                403,
                headers={"request-id": "synthetic-request-id"},
                json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}},
            )
        )

        result = await mcp_client.call_tool(tool, arguments, raise_on_error=False)

        assert result.is_error
        message = _error_text(result)
        assert permission in message
        assert not_named not in message
        assert "administrator" in message
        assert "synthetic-request-id" in message

    async def test_an_unconsented_channel_browse_names_the_message_permission(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """The same missing permission one step earlier, on the tool most likely to hit it:
        `ChannelMessage.Read.All` is the broad scope an administrator has to consent to, and Entra
        refuses the exchange before Graph is reached at all."""
        route = graph.get(_CHANNEL_MESSAGES_PATH).mock(
            return_value=httpx.Response(200, json=_CHANNEL_POSTS)
        )
        obo.refusal = ClientAuthenticationError(
            message=(
                "AADSTS65001: The user or administrator has not consented to use the application "
                + "with ID '1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061'."
            )
        )

        result = await mcp_client.call_tool(
            "browse_channel",
            {"team_id": _TEAM_ID, "channel_id": _CHANNEL_ID},
            raise_on_error=False,
        )

        assert result.is_error
        message = _error_text(result)
        assert "ChannelMessage.Read.All" in message, message
        assert "administrator" in message
        assert "AADSTS65001" in message
        assert "resolve dependency" not in message
        assert not route.called, "no token means no Graph request was ever made"

    @pytest.mark.usefixtures("obo")
    async def test_a_refused_search_names_both_permissions_it_was_made_under(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """The first tool here to need two permissions, and the first refusal that has to name two.
        A tenant that grants `Chat.Read` and withholds `ChannelMessage.Read.All` is the ordinary
        case, because the broad one needs an administrator in most tenants, and Graph's 403 says
        only that something was forbidden. So the remedy has to name both: handed one name, an
        administrator may grant the permission that was never missing and watch the identical
        failure. The single-permission tools must NOT name both, so the wording is taken from each
        tool's own declared tuple rather than from the registry's union.
        """
        graph.post("/search/query").mock(
            return_value=httpx.Response(
                403,
                headers={"request-id": "synthetic-request-id"},
                json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}},
            )
        )

        result = await mcp_client.call_tool(
            "search_messages", {"query": "release"}, raise_on_error=False
        )

        assert result.is_error
        message = _error_text(result)
        assert "Chat.Read" in message, message
        assert "ChannelMessage.Read.All" in message, message
        assert "delegated permissions" in message, "plural, or it reads as one of them"
        assert "administrator" in message
        assert "synthetic-request-id" in message

    async def test_an_unconsented_search_names_both_permissions_it_asked_for(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """The tenant that grants `Chat.Read` and withholds `ChannelMessage.Read.All`. Entra
        redeems a two-scope exchange as a whole and refuses it as a whole, naming no more than the
        application: which of the two was missing is not in AADSTS65001 any more than it is in a
        Graph 403. So the refusal has to name both, exactly as the 403 path does.

        The wording is also asserted to be *ours*. The exchange happens inside FastMCP's dependency
        resolution, so without the wrapper the model reads "Failed to resolve dependency 'client'
        for search_teams_messages", a parameter of a function the model never sees.
        """
        route = graph.post("/search/query").mock(return_value=httpx.Response(200, json=_SEARCH))
        obo.refusal = ClientAuthenticationError(
            message=(
                "AADSTS65001: The user or administrator has not consented to use the application "
                + "with ID '1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061'."
            )
        )

        result = await mcp_client.call_tool(
            "search_messages", {"query": "release"}, raise_on_error=False
        )

        assert result.is_error
        message = _error_text(result)
        assert "Chat.Read" in message, message
        assert "ChannelMessage.Read.All" in message, message
        assert "administrator" in message
        assert "AADSTS65001" in message
        assert "resolve dependency" not in message
        assert not route.called, "no token means no search was ever made"

    @pytest.mark.usefixtures("obo")
    @pytest.mark.parametrize(
        "tool", ["list_meeting_transcripts", "read_transcript"], ids=["listing", "reading"]
    )
    async def test_the_tenant_transcript_switch_sends_the_caller_to_a_teams_administrator(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        tool: str,
    ) -> None:
        """The refusal every other 403 on this server would be answered wrongly for, on both of the
        calls that can meet it. Microsoft Graph access to Teams meeting transcripts is a
        tenant-wide Teams setting that is OFF BY DEFAULT, and Graph reports it with the same status
        and the same outer code as a missing permission. In the commonest tenant this is the
        *first* answer a model gets from either tool, so it has to name the Teams admin centre
        rather than a Graph permission, and it has to rule out the re-consent a model would
        otherwise infer from every other refusal here. The reader meets it on a different endpoint
        from the lister, so both are driven: a remedy that reached only the listing would leave the
        reader answering the ordinary 403.
        """
        graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        graph.get(_TRANSCRIPTS_PATH).mock(
            return_value=httpx.Response(
                403, headers={"request-id": "synthetic-request-id"}, json=_TENANT_SWITCH_OFF
            )
        )
        graph.get(_CONTENT_PATH).mock(
            return_value=httpx.Response(
                403, headers={"request-id": "synthetic-request-id"}, json=_TENANT_SWITCH_OFF
            )
        )
        arguments = {
            "list_meeting_transcripts": {"meeting_uri": _MEETING_URI},
            "read_transcript": {"uri": f"teams:///transcripts/{_MEETING_ID}/{_TRANSCRIPT_ID}"},
        }[tool]

        refused = await mcp_client.call_tool(tool, arguments, raise_on_error=False)

        assert refused.is_error
        message = _error_text(refused)
        assert "EnableGraphTranscriptAccess" in message
        assert "Teams administrator" in message
        assert "sign in again will not change it" in message
        assert "OnlineMeetingTranscript.Read.All" not in message, (
            "no permission is missing; naming one sends an administrator after nothing"
        )
        assert "synthetic-request-id" in message, "an operator still needs the evidence"

    @pytest.mark.usefixtures("obo")
    @pytest.mark.parametrize(
        ("tool", "argument", "uri"),
        [
            ("list_meeting_transcripts", "meeting_uri", "teams:///transcripts/a/b"),
            ("list_meeting_transcripts", "meeting_uri", "19:meeting_x@thread.v2"),
            ("read_transcript", "uri", "teams:///meetings/https%3A%2F%2Fx.invalid%2Fa"),
            ("read_transcript", "uri", "teams:///chats/19%3Ax%40thread.v2/messages/1"),
            ("list_meeting_recordings", "meeting_uri", "teams:///transcripts/a/b"),
            ("list_meeting_recordings", "meeting_uri", "19:meeting_x@thread.v2"),
        ],
    )
    async def test_each_meeting_tool_refuses_the_other_ones_handle_and_says_where_to_get_its_own(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        tool: str,
        argument: str,
        uri: str,
    ) -> None:
        """Two meeting handle families exist and three tools take one of them, so a model will mix
        them up. Each refusal has to name the one shape this tool reads and the one tool that mints
        it. "Invalid handle" would leave a model guessing, and guessing between families is what
        produces a loop."""
        meetings = graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        content = graph.get(_CONTENT_PATH).mock(
            return_value=httpx.Response(200, content=_TRANSCRIPT_VTT.encode())
        )

        result = await mcp_client.call_tool(tool, {argument: uri}, raise_on_error=False)

        assert result.is_error
        assert not meetings.called and not content.called, "a bad handle costs no Graph request"
        message = _error_text(result)
        expected = {
            "list_meeting_transcripts": ("teams:///meetings/{join_web_url}", "list_chats"),
            "read_transcript": (
                "teams:///transcripts/{meeting_id}/{transcript_id}",
                "list_meeting_transcripts",
            ),
            "list_meeting_recordings": ("teams:///meetings/{join_web_url}", "list_chats"),
        }[tool]
        for fragment in expected:
            assert fragment in message, message
        assert "fail identically" in message, "and it is not worth retrying"

    @pytest.mark.usefixtures("obo")
    @pytest.mark.parametrize(
        ("tool", "clause"),
        [
            (
                "list_meeting_transcripts",
                "handle is read_transcript's; this tool is what produces it",
            ),
            (
                "list_meeting_recordings",
                "No recording is addressable here",
            ),
        ],
        ids=["transcripts", "recordings"],
    )
    async def test_each_meeting_listers_refusal_keeps_the_sentence_only_it_can_say(
        self, mcp_client: Client[FastMCPTransport], tool: str, clause: str
    ) -> None:
        """The two listers refuse a bad `meeting_uri` in almost the same words, and each keeps one
        sentence the other cannot say. The transcript one names who owns the shape it just rejected
        and says that this tool is where a caller gets one. The recordings one has to say that no
        recording handle exists at all, because nothing here returns video.

        Pinned per tool rather than as one assertion over both: near-identical prose drifts by an
        edit that improves the wording on one side only.
        """
        result = await mcp_client.call_tool(
            tool, {"meeting_uri": "teams:///transcripts/a/b"}, raise_on_error=False
        )

        assert result.is_error
        assert clause in _error_text(result), _error_text(result)

    @pytest.mark.usefixtures("obo")
    async def test_a_transcript_graph_will_not_return_blames_the_meeting_window_not_the_handle(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """A 404 on a well-formed transcript handle is almost always age: Microsoft stops serving a
        meeting's artifacts once the meeting expires. The message reader's advice would be wrong
        here in both directions. A transcript is not deleted by a user, and browsing a channel is
        not a route to one."""
        graph.get(_CONTENT_PATH).mock(
            return_value=httpx.Response(
                404,
                headers={"request-id": "synthetic-request-id"},
                json={"error": {"code": "NotFound", "message": "Not Found"}},
            )
        )

        result = await mcp_client.call_tool(
            "read_transcript",
            {"uri": f"teams:///transcripts/{_MEETING_ID}/{_TRANSCRIPT_ID}"},
            raise_on_error=False,
        )

        assert result.is_error
        message = _error_text(result)
        assert "expires" in message
        assert "list_meeting_transcripts" in message
        assert "browse_channel" not in message
        assert "synthetic-request-id" in message

    @pytest.mark.parametrize(
        "uri",
        [
            "mail:///messages/AAMkAGI2",
            "teams:///chats/19%3Arelease%40thread.v2",
            "https://teams.microsoft.com/l/message/19%3Ageneral/1770000000000",
        ],
    )
    async def test_a_handle_this_connector_cannot_read_shows_the_shapes_it_can(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        uri: str,
        obo: _StubOboCredential,
    ) -> None:
        """The first of three failures a reader has to keep apart, and the only one this connector
        explains as its own: the argument is not a handle. Graph is never called, and the remedy is
        the shape, not "try again"."""
        route = graph.get(_MESSAGE_PATH).mock(return_value=httpx.Response(200, json=_MESSAGE))

        result = await mcp_client.call_tool("read_message", {"uri": uri}, raise_on_error=False)

        assert result.is_error
        assert not route.called
        message = _error_text(result)
        assert "teams:///chats/{chat_id}/messages/{message_id}" in message
        assert "teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}" in message
        assert "search_messages" in message
        assert obo.requested_scopes, "the handle is parsed inside the tool, after the exchange"

    @pytest.mark.usefixtures("obo")
    async def test_a_message_graph_will_not_return_is_not_reported_as_never_existing(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """The second failure: a well-formed handle Graph answers 404 to. It means deleted, or
        invisible to this user, or gone, and Graph does not say which, so neither may the tool. The
        default advice for a missing item ("check the id came from a tool response verbatim") is
        wrong here, because it did.
        """
        _ = graph.get(_MESSAGE_PATH).mock(
            return_value=httpx.Response(
                404,
                headers={"request-id": "synthetic-request-id"},
                json={"error": {"code": "NotFound", "message": "Not Found"}},
            )
        )

        result = await mcp_client.call_tool(
            "read_message", {"uri": _MESSAGE_URI}, raise_on_error=False
        )

        assert result.is_error
        message = _error_text(result)
        assert "could not be read" in message
        assert "not evidence that the message does not exist" in message
        assert "synthetic-request-id" in message, "the id Microsoft support asks for first"
        assert "verbatim" not in message, "the handle did come from a tool response"

    @pytest.mark.usefixtures("obo")
    async def test_the_advice_for_an_unreadable_reply_terminates_instead_of_looping(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """The one 404 this connector predicts, and the advice that must not be circular. A search
        hit on a channel reply carries the root-post shape, because Microsoft's index does not say
        which post the reply hangs under, so Graph answers it 404. `browse_channel` is the only
        tool that mints a reply's own handle, but it returns the newest replies of each post on a
        channel's first page and follows neither of Microsoft's cursors past them, because a
        channel allows this whole connector about one request a second across the tenant. "Browse
        the channel instead" is a route for a recent reply and a loop for an older one, so the text
        names the window, says there is no route beyond it, and tells the model what to answer with.
        """
        _ = graph.get(_MESSAGE_PATH).mock(
            return_value=httpx.Response(
                404,
                headers={"request-id": "synthetic-request-id"},
                json={"error": {"code": "NotFound", "message": "Not Found"}},
            )
        )

        result = await mcp_client.call_tool(
            "read_message", {"uri": _MESSAGE_URI}, raise_on_error=False
        )

        message = _error_text(result)
        assert f"newest {MAX_REPLIES_PER_POST} replies" in message, message
        assert "no route to its full text" in message
        assert "a second browse returns the same window" in message
        assert "stop looking" in message

    @pytest.mark.usefixtures("obo")
    async def test_a_refused_read_names_only_the_permission_that_surface_needs(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """The third failure, and the one an administrator acts on. Graph's permissions for a
        message read are per surface, so a 403 reading a chat can only be about `Chat.Read`. Naming
        the channel permission too would send an administrator after one that was never missing.
        """
        _ = graph.get(_MESSAGE_PATH).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        result = await mcp_client.call_tool(
            "read_message", {"uri": _MESSAGE_URI}, raise_on_error=False
        )

        assert result.is_error
        message = _error_text(result)
        assert "Chat.Read" in message
        assert "administrator" in message
        assert "ChannelMessage.Read.All" not in message, "this read was in a chat"

    @pytest.mark.usefixtures("obo")
    async def test_a_refused_channel_read_names_the_channel_permission_instead(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """The other half of the same rule. A tenant that grants `Chat.Read` and withholds the broad
        channel permission is the common case."""
        team = "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81"
        _ = graph.get(
            f"/teams/{team}/channels/19%3Ageneral%40thread.tacv2/messages/1770000000000"
        ).mock(
            return_value=httpx.Response(
                403, json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}}
            )
        )

        result = await mcp_client.call_tool(
            "read_message",
            {
                "uri": (
                    f"teams:///teams/{team}/channels/19%3Ageneral%40thread.tacv2"
                    + "/messages/1770000000000"
                )
            },
            raise_on_error=False,
        )

        assert result.is_error
        message = _error_text(result)
        assert "ChannelMessage.Read.All" in message
        assert "Chat.Read" not in message, "this read was in a channel"

    async def test_a_permission_nobody_consented_to_names_it_too(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        route = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        obo.refusal = ClientAuthenticationError(
            message=(
                "AADSTS65001: The user or administrator has not consented to use the application "
                + "with ID '1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061'."
            )
        )

        result = await mcp_client.call_tool("get_me", {}, raise_on_error=False)

        assert result.is_error
        message = _error_text(result)
        assert "User.Read" in message, message
        assert "administrator" in message
        assert "AADSTS65001" in message
        assert "resolve dependency" not in message
        assert not route.called
