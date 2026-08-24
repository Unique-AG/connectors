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

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_365_mcp.graph_client import GraphSettings, create_graph_transport
from office_365_mcp.shared import meetings
from office_365_mcp.shared.messages import MAX_REPLIES_PER_POST

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
                    "total": 1,
                    "moreResultsAvailable": False,
                }
            ],
        }
    ]
}

# Written out rather than derived: a derived handle asserts only that the test agrees with itself.
_MESSAGE_URI = "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000"
_MESSAGE_PATH = "/chats/19%3Arelease%40thread.v2/messages/1770000000000"

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

# The only five properties `GET /me/joinedTeams` populates; every other comes back null there.
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

# Graph addresses a reply under the post it answers; no other shape reaches it.
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


# Already-escaped `%3a` and `%40`, a `?context=` query, an `&`: the shape the `$filter` survives.
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
# Routed only to be asserted *un*called: nothing here ever fetches recording content.
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

# `contentCorrelationId` matches the transcript's: Microsoft's own link between the two artifacts.
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
                    # The SDK does not know this type, so the code falls back to the base identity.
                    "@odata.type": "#Microsoft.Teams.GraphSvc.teamworkUserIdentity",
                    "id": "00000000-0000-4000-8000-000000000002",
                    "displayName": None,
                    "userIdentityType": "aadUser",
                },
            },
        }
    ]
}

# Oldest first, Microsoft's own order — it documents no `$orderby` here — so "newest" is work.
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

# Oldest first, so the genuinely newest occurrence sits past the cap where no lister can see it.
_PAST_THE_CAP = meetings.MAX_ARTIFACT_SCAN + 60
_DAILY_SERIES_START = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)

# The outer code says nothing; the inner code is the whole difference from a missing permission.
_TENANT_SWITCH_OFF = {
    "error": {
        "code": "Forbidden",
        "message": "Graph API access to transcripts is disabled for this tenant.",
        "innerError": {"code": "GraphAccessToTranscriptsDisabled"},
    }
}


def _day(index: int) -> datetime:
    return _DAILY_SERIES_START + timedelta(days=index)


def _daily_series() -> dict[str, object]:
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


_MEETING_URI = "teams:///meetings/" + quote(_JOIN_WEB_URL, safe="")

_TRANSCRIPT_VTT = """WEBVTT

00:00:16.246 --> 00:00:19.900
<v Grace Hopper>We should raise the floor price by three per cent.</v>

00:01:02.000 --> 00:01:04.500
<v Ada Lovelace>Agreed, that works.</v>
"""


class _StubOboCredential:
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
    """The tracer provider is process-wide and settable once, so the exporter attaches to whichever
    provider is in play, and clearing on entry stops an earlier test's span reading as this one's.
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
    """`teams` is every tool, and the preset is mandatory with no default. What a narrowed one
    exposes is `tests/test_tool_selection.py`'s subject.
    """
    return create_app(
        config=AppConfig.model_validate({"public_base_url": "https://office-365-mcp.example"}),
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
    assert schema is not None, "expected a schema"
    properties = schema.get("properties")
    assert isinstance(properties, dict), f"expected an object schema, got {schema!r}"
    return cast("dict[str, object]", properties)


def _object(value: object) -> dict[str, object]:
    assert isinstance(value, dict), f"expected an object, got {value!r}"
    return cast("dict[str, object]", value)


# Tool names and field names are both `verb_noun`, so the verb discriminates: no answer field
# starts with one of these. Not a stop-list of unlanded tools — that is one somebody forgets.
_TOOL_MENTION = re.compile(r"\b(?:get|list|read|search|browse|find)_[a-z]+(?:_[a-z]+)*\b")


def _described(schema: Mapping[str, object] | None) -> list[str]:
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
    """FastMCP inlines these schemas fully: a nested model arrives under `items` or in an `anyOf`
    branch and never as a `$ref`, so neither is followed as a reference."""
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
    branches = cast("Sequence[object]", _object(schema)["anyOf"])
    return [_object(branch) for branch in branches if _object(branch).get("type") != "null"]


def _optional_type(schema: object) -> dict[str, object]:
    typed = _optional_types(schema)
    assert len(typed) == 1, f"expected one non-null branch, got {typed!r}"
    return typed[0]


_MESSAGE_TOOLS: tuple[str, ...] = ("read_message", "browse_channel", "search_messages")


def _items(schema: object) -> dict[str, object]:
    return _object(_object(schema)["items"])


def _sender_schema(schema: Mapping[str, object] | None) -> dict[str, object]:
    properties = _properties(schema)
    message = properties if "sender" in properties else _properties(_items(properties["messages"]))
    sender = message["sender"]
    # Optional on a read (a system event has no author) and required on a search hit.
    return _optional_type(sender) if "anyOf" in _object(sender) else _object(sender)


def _structured(result: CallToolResult) -> dict[str, object]:
    data = cast("dict[str, object] | None", result.structured_content)
    assert data is not None, "the tool returned no structured content"
    return data


def _search_query_string(route: respx.Route) -> str:
    body = cast("dict[str, object]", json.loads(route.calls.last.request.content))
    requests = cast("Sequence[Mapping[str, object]]", body["requests"])
    assert len(requests) == 1, "Graph honours only one searchRequest per call"
    query = cast("Mapping[str, object]", requests[0]["query"])
    return cast("str", query["queryString"])


def _error_text(result: CallToolResult) -> str:
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


def _record_text(record: logging.LogRecord) -> str:
    """A value passed as an `extra` never appears in `getMessage()` but does reach the log sink, so
    checking the formatted message alone would miss it."""
    return f"{record.getMessage()} {record.__dict__!r}"


class TestTheToolsThisServerAdvertises:
    async def test_every_tool_is_listed_and_none_asks_for_a_client(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
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
        """Asserted over the published schemas rather than the model classes: a description that
        never reaches the wire is not one."""
        tools = _named(await mcp_client.list_tools())
        published = {
            path: field
            for name, tool in tools.items()
            for path, field in _fields(tool.outputSchema, name).items()
        }

        # Guards the guard: a walk that stopped descending would pass by finding nothing to check.
        assert "list_chats.chats[].members[].email" in published

        undescribed = sorted(
            path for path, field in published.items() if not _object(field).get("description")
        )
        assert undescribed == [], "a model is handed these values with nothing to say what they are"

    async def test_the_whole_surface_speaks_one_language(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """No `truncated` flag: a window filled to `limit` already says there may be more, so a
        flag on top means either "raise `limit`" or "nothing will help", with no way to tell
        which."""
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
        """Microsoft matches a mention on the id alone: a display name silently matches nothing."""
        tools = _named(await mcp_client.list_tools())
        properties = _properties(tools["search_messages"].inputSchema)

        assert _optional_type(properties["mentions"]) == {"type": "string", "format": "uuid"}
        assert _optional_type(properties["sent_after"]) == {"type": "string", "format": "date"}
        assert _optional_type(properties["sent_before"]) == {"type": "string", "format": "date"}

    async def test_the_query_parameter_describes_the_matching_it_actually_does(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
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
        """Pydantic publishes a model's docstring as the JSON-schema `description` of the object,
        so `MessageSender`'s own paragraph is live protocol surface on every tool that does not
        override it, and editing that docstring changes the wire."""
        tools = _named(await mcp_client.list_tools())
        taught = {name: _sender_schema(tools[name].outputSchema) for name in _MESSAGE_TOOLS}

        for name in ("read_message", "browse_channel"):
            written = taught[name]["description"]
            assert isinstance(written, str)
            # A docstring keeps its line breaks in the schema; the sentence is pinned, not the wrap.
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
        tools = _named(await mcp_client.list_tools())
        schema = tools["read_message"].inputSchema

        assert set(_properties(schema)) == {"uri"}
        assert schema.get("required") == ["uri"]

    async def test_read_message_names_every_handle_shape_and_no_others(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
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
        """Two readers deliberately: a token is exchanged per tool, so one polymorphic reader
        would have to redeem transcript access to read a chat message."""
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
        """20 and 50 are Graph's own default and maximum for this collection."""
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
        """Graph orders this collection by the reply chain's last-modified date, so the first post
        is the most recently *active* thread and may be years old."""
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
        across the tenant, so the tool makes exactly one and `limit` is the entire window."""
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
        """The negative has to sit on the `not_ready` bullet itself, not on the `scan_incomplete`
        one two lines down, which is a different status."""
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
        """The window is applied after Microsoft has answered, so no argument sends the next call
        further into the collection: `scan_incomplete` is the one status with no remedy to offer."""
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
        tools = _named(await mcp_client.list_tools())
        properties = _properties(tools["list_meeting_transcripts"].inputSchema)

        assert _optional_types(properties[bound]) == [
            {"type": "string", "format": "date"},
            {"type": "string", "format": "date-time"},
        ]

    async def test_the_occurrence_window_states_the_zone_it_resolves_against(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
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
        """A recurring series' `endDateTime` can be years in the future, so a caller told to wait
        for an occurrence that ended last month polls forever."""
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
        tools = _named(await mcp_client.list_tools())
        description = tools["list_meeting_recordings"].description
        assert description is not None
        # The whole schema, `$defs` included: a recording's fields are described there, not inline.
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
        """Read off the advertised list rather than a written-down one, so the day a tool lands
        the assertion widens by itself and only the stale promise fails."""
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
        """`/me/joinedTeams` supports no OData query parameter at all: a `$top` or `$select`
        reaching Graph is a 400, not a narrower answer."""
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
        """The one list here whose length is no signal: this tool makes a single request and drops
        system messages Microsoft counted into the page, so only the cursor says there is more."""
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
        `anyOf` alone would not stop this."""
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
        """`services/teams-mcp` had to go back and strip query terms out of its spans and logs, so
        this connector never puts them there."""
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
        """A `limit` applied before ordering would return an arbitrary handful sorted among
        themselves, and Microsoft's own order here puts the oldest first."""
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
        """Graph access to transcripts is a tenant switch that is OFF BY DEFAULT and scoped to
        transcript resources, so one tool listing both artifacts would fail the whole call here."""
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
        """Padding survives the boundary: nothing between the client and the filter trims it."""
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
    """Nothing here asserts the transport is closed: `AsyncGraphTransport` never overrides
    `aclose`, so it inherits the `pass` in `httpx.AsyncBaseTransport`, the pool survives every
    shutdown, and an `is_closed` assertion passes on that lie. Upstream bug, open and unanswered:
    microsoft/kiota-python#494.
    """

    async def test_every_tool_is_handed_the_same_transport(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A transport per call would mean a cold TLS handshake and a leaked pool per call."""
        built: list[httpx.AsyncClient] = []

        def record(settings: GraphSettings) -> httpx.AsyncClient:
            transport = create_graph_transport(settings)
            built.append(transport)
            return transport

        monkeypatch.setattr("office_365_mcp.app.create_graph_transport", record)

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
        """Graph's 403 says only that something was forbidden, so naming the wrong permission
        sends an administrator after one that was never missing."""
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
        """The wording is taken from each tool's own declared tuple rather than from the
        registry's union, so a single-permission tool never names both."""
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
        """The exchange happens inside FastMCP's dependency resolution, so without the wrapper the
        model reads "Failed to resolve dependency 'client'" — a parameter it never sees."""
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
        """Microsoft stops serving a meeting's artifacts once the meeting expires, so a 404 on a
        well-formed transcript handle is almost always age."""
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
        """Microsoft's index does not say which post a reply hangs under, so a search hit on one
        carries the root-post shape and Graph answers it 404."""
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
