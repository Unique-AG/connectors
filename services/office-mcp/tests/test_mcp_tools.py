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
    # A search hit's sender is Exchange-shaped, because Teams messages are indexed out of the
    # substrate mailbox.
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
                    # Documented as the count on this page for Teams messages, not a match total.
                    # Present here precisely so a test can prove it is not reported as one.
                    "total": 1,
                    "moreResultsAvailable": False,
                }
            ],
        }
    ]
}

# The handle the search hit above carries, which is what read_message has to resolve. Written out
# rather than derived: that a search result's `uri` and a read's argument are the same string is the
# contract between the two tools, and deriving it here would assert only that the test agrees with
# itself.
_MESSAGE_URI = "teams:///chats/19%3Arelease%40thread.v2/messages/1770000000000"
_MESSAGE_PATH = "/chats/19%3Arelease%40thread.v2/messages/1770000000000"

# The same message as `GET /chats/{id}/messages/{id}` returns it: with a body, and with the
# Teams-shaped sender that carries no email at all.
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

# A system event message, which Graph sends with no author and no text: the body is the literal
# `<systemEventMessage/>` and the sentence Teams displays is written by the Teams client.
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

# Only the five properties `GET /me/joinedTeams` populates; every other property of a team comes
# back null on that endpoint, asked for or not.
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

# The handle the reply above carries, and the path Graph serves it from. A reply is addressed under
# the post it answers — no other shape reaches it — which is the whole point of the third shape.
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


# The meeting side. The join URL is written the way Microsoft actually stores one — an already
# percent-escaped `%3a`/`%40`, a `?context=` query, an `&` parameter — because that shape is what
# the `$filter` has to survive. Nothing here is a real meeting.
_JOIN_WEB_URL = (
    "https://teams.microsoft.invalid/l/meetup-join/"
    + "19%3ameeting_TjAwMDAwMDAwMDAwMA%40thread.v2/0"
    + "?context=%7b%22Tid%22%3a%228a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81%22%7d&anon=true"
)
_MEETING_ID = "MSpiYTMyMWUwZC03OWVlLTQ3OGQtOGUyOC04NWExOTUwN2Y0NTYqMCoq"
_TRANSCRIPT_ID = "MSMjMCMjSYNTHETIC0001"
_MEETINGS_PATH = "/me/onlineMeetings"
_TRANSCRIPTS_PATH = f"/me/onlineMeetings/{_MEETING_ID}/transcripts"

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

# A recurring series as Microsoft holds it: one meeting, one collection, three occurrences — and
# answered oldest-first, which is an order of Microsoft's own (it documents no `$orderby` here).
# Written out in that order on purpose: it is what makes "the newest of a series" something the
# lister has to work for rather than something it gets by accident.
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

# The one meeting shape that outgrows what a single call reads: a daily series, transcribed every
# time, for the better part of a year. Oldest-first for the same reason the weekly series above is
# — Microsoft's order is its own — which puts the genuinely newest occurrence past
# `MAX_ARTIFACT_SCAN`, where the lister cannot see it and may not claim it has.
_PAST_THE_CAP = meetings.MAX_ARTIFACT_SCAN + 60
_DAILY_SERIES_START = datetime(2026, 1, 1, 14, 0, tzinfo=UTC)

# The tenant switch, as Graph marks it: a 403 whose outer code says nothing and whose inner code is
# the whole of the difference from a missing permission.
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
    """`_PAST_THE_CAP` transcripts in one page, as Microsoft would answer them."""
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


# The meeting handle `list_chats` mints for the chat above, written out rather than derived: that
# the handle a model copies from one tool is the argument another takes is the contract between
# them, and deriving it here would assert only that the test agrees with itself.
_MEETING_URI = "teams:///meetings/" + quote(_JOIN_WEB_URL, safe="")


class _StubOboCredential:
    """Stub for azure.identity.aio.OnBehalfOfCredential.

    Records scopes requested and can simulate failure.
    """

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
    """Stub Entra on-behalf-of exchange. Authenticate the in-process client."""
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

    Trap: this used to be written out inside the test that reads it, ending in a loop over
    `get_finished_spans()` and nothing that said the list was not empty. That is a privacy assertion
    that passes hardest when nothing is traced at all — and until tracing was switched on, nothing
    was. The tests that use it therefore assert a span was recorded before they assert what is not
    in it.

    The tracer provider is process-wide and can be set only once, so the exporter is attached to
    whichever one is already in play and the collection is emptied on the way in rather than torn
    down: a span from an earlier test would otherwise read as one of this test's own.
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

    A selection is mandatory and has no default, so it is stated here. `teams` is "every tool" —
    what a *narrowed* selection exposes is `tests/test_tool_selection.py`'s subject.
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
    """Get the FastMCP server from the app."""
    return cast("FastMCP[None]", app.state.fastmcp_server)


@pytest.fixture
async def mcp_client(app: Starlette) -> AsyncIterator[Client[FastMCPTransport]]:
    """Create an MCP client connected to the server."""
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


# What a tool being *named* in prose looks like, as opposed to a field being named. Both are
# `verb_noun` — that is the convention asserted below — so the discriminator is the verb: these are
# the ones a tool on this connector is named with, and no answer field starts with any of them.
# Deliberately not a list of the tools still to come: a stop-list of names nothing declares yet is
# a list somebody forgets to add to, which is the failure it would exist to prevent.
_TOOL_MENTION = re.compile(r"\b(?:get|list|read|search|browse|find)_[a-z]+(?:_[a-z]+)*\b")


def _described(schema: Mapping[str, object] | None) -> list[str]:
    """Every `description` anywhere in a JSON schema — parameters, fields, nested objects.

    A model reads all of them, so all of them are protocol surface; a stale promise is as harmful
    in one field's description as in the tool's own.
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


def _optional_types(schema: object) -> list[dict[str, object]]:
    """Every non-null branch of an optional parameter's schema, in the order it declares them."""
    branches = cast("Sequence[object]", _object(schema)["anyOf"])
    return [_object(branch) for branch in branches if _object(branch).get("type") != "null"]


def _optional_type(schema: object) -> dict[str, object]:
    """The one non-null branch of an optional parameter's schema, where it has exactly one."""
    typed = _optional_types(schema)
    assert len(typed) == 1, f"expected one non-null branch, got {typed!r}"
    return typed[0]


# The tools that answer with a Teams message, and so with a sender. They are the reason
# `shared/messages.py` exists, and the reason the sender shape is asserted over the live schemas
# rather than over the model class: what a model reads is the schema.
_MESSAGE_TOOLS: tuple[str, ...] = ("read_message", "browse_channel", "search_messages")


def _items(schema: object) -> dict[str, object]:
    """The element schema of an array-shaped property, e.g. one message of `messages`."""
    return _object(_object(schema)["items"])


def _sender_schema(schema: Mapping[str, object] | None) -> dict[str, object]:
    """The sender object inside a tool's answer, wherever that answer puts a message.

    `read_message` answers with one message and carries `sender` at the top; `browse_channel` and
    `search_messages` answer with a list and carry it per element. All of them reach the same
    `MessageSender`, which is the point — this is what makes "does the guidance reach this tool"
    one question rather than three.
    """
    properties = _properties(schema)
    message = properties if "sender" in properties else _properties(_items(properties["messages"]))
    sender = message["sender"]
    # Optional on a read (a system event message has no author) and required on a search hit, which
    # drops those hits — so unwrap an `anyOf` only where there is one.
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

    Structured logging is what makes this necessary — a value passed as an extra never appears in
    the message but does reach the log sink, so checking `getMessage()` alone would miss it.
    """
    return f"{record.getMessage()} {record.__dict__!r}"


class TestTheToolsThisServerAdvertises:
    async def test_every_tool_is_listed_and_none_asks_for_a_client(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The Graph client, the On-Behalf-Of token inside it and the request context are all
        dependencies. A model shown any of them as an argument would be asked for a value only this
        server can make."""
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
        """Prose ("max 50") is advice; the schema is enforcement — an out-of-range call has to
        fail loudly rather than be silently clamped to something else."""
        tools = _named(await mcp_client.list_tools())
        limit = _object(_properties(tools["list_chats"].inputSchema)["limit"])

        assert limit["type"] == "integer", "not `number`: a fractional page size is meaningless"
        assert (limit["minimum"], limit["maximum"], limit["default"]) == (1, 50, 25)

    async def test_every_tool_declares_its_result_shape(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """Every tool declares its output schema."""
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

    async def test_the_whole_surface_speaks_one_language(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """Tool names are verb_noun, fields are snake_case, no truncated flag.

        The last of those was written down before there was a list-shaped tool to break it. There
        are several now, and between them they are the reason the convention was worth asserting
        early: a window filled to `limit` says there may be more and a short one says there is not,
        `next_offset` says it outright where paging exists, and `truncated` on top of either means
        "raise `limit`" or "nothing will help" with no way to tell which. `list_chats` says it by
        the length of its window, which is only honest because its walk follows Microsoft's paging
        to the end of the collection; `search_messages` cannot say it that way at all, because
        Microsoft reports a page count rather than a match total for Teams messages — so it says it
        with `next_offset` and that field is asserted to be there.

        Where a completeness fact is NOT derivable from the answer it survives as an opt-in field,
        which is asserted too: the flag that asks for it defaults to off, so no ordinary answer
        carries the caveat, and each tool that has one carries one field per fact rather than one
        boolean over several. `browse_channel` is one tool that needs it — it reads a single page
        and drops system messages out of it after Microsoft counted them in, so its length says
        neither thing — and `list_meeting_transcripts` is the other, where the fact is whether the
        read reached the end of a meeting's transcripts and therefore whether "newest" is a claim
        about the meeting or only about what was read.
        """
        tools = _named(await mcp_client.list_tools())

        for name in tools:
            assert re.fullmatch(r"[a-z]+(_[a-z]+)+", name), f"{name} is not verb_noun"
        for tool in tools.values():
            for field in _properties(tool.outputSchema):
                assert re.fullmatch(r"[a-z][a-z0-9]*(_[a-z0-9]+)*", field), f"{field} is not snake"
        for name, tool in tools.items():
            assert "truncated" not in _properties(tool.outputSchema), name
        for name in ("search_messages",):
            assert "next_offset" in _properties(tools[name].outputSchema), name
        for name, flag in (
            ("browse_channel", "include_window_completeness"),
            ("list_meeting_transcripts", "include_scan_completeness"),
        ):
            asked_for = _object(_properties(tools[name].inputSchema)[flag])
            assert asked_for["default"] is False, f"{name} would report completeness unasked"

    async def test_search_messages_makes_its_criteria_optional_but_not_all_of_them(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """Not one of the oracle connector's ten schemas uses `anyOf`, so every rule about which
        parameters may combine lives in prose a model may not read, and an illegal call validates
        cleanly and silently behaves differently. "At least one criterion" is a real constraint
        with a JSON Schema spelling, so it is spelled.
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
        """A mentioned user must be an id — Microsoft matches that scope term on the id alone, so a
        display name silently matches nothing — and the dates are whole days, not timestamps."""
        tools = _named(await mcp_client.list_tools())
        properties = _properties(tools["search_messages"].inputSchema)

        assert _optional_type(properties["mentions"]) == {"type": "string", "format": "uuid"}
        assert _optional_type(properties["sent_after"]) == {"type": "string", "format": "date"}
        assert _optional_type(properties["sent_before"]) == {"type": "string", "format": "date"}

    async def test_the_query_parameter_describes_the_matching_it_actually_does(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The description is the only place a model learns what `query` does, so it has to match
        what the query builder does. It promised "matched as words" while the whole query was being
        sent as one quoted phrase, which is a recall loss a caller cannot see: the tool answers with
        fewer messages than exist and nothing says so. Both halves are pinned here — that the words
        are ANDed, and that adjacency is available by quoting.
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

        Pydantic surfaces a model's docstring as the JSON-schema `description` of the object it
        describes, so `MessageSender`'s own paragraph is live protocol surface on every tool that
        does not override it — and losing it is invisible: the fields are all still there, the
        schema still validates, and every tool still answers. What goes missing is the sentence
        that stops a model reading a null as a fact about the person: a search hit carries an
        Exchange-style `emailAddress`, a Teams read answers with a `teamworkUserIdentity` that has
        no email property at all, and a bot arrives as an application identity, so which fields are
        filled in says which shape Graph used rather than saying the sender has no name, no address
        or no id. `read_message` and `browse_channel` are where that matters, because they are the
        two whose senders normally arrive with `email` null.

        `search_messages` is deliberately not in that list: it overrides at field level, so its
        own words are what a model reads there. The per-field descriptions are shared by all
        three either way, and that is asserted too — a difference between them would be one tool
        explaining `user_id` differently from the next.
        """
        tools = _named(await mcp_client.list_tools())
        taught = {name: _sender_schema(tools[name].outputSchema) for name in _MESSAGE_TOOLS}

        for name in ("read_message", "browse_channel"):
            written = taught[name]["description"]
            assert isinstance(written, str)
            # A docstring reaches the schema with its own line breaks; what is pinned is the
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
        """The description is where a model learns what it may pass. Naming the shapes is what
        stops it inventing `mail:///` — and the oracle connector's one polymorphic `read_resource`
        is exactly the promise this connector does not make. The reply shape is named with the tool
        that mints it, because it is the one no search result carries.
        """
        tools = _named(await mcp_client.list_tools())
        description = tools["read_message"].description
        assert description is not None

        assert "teams:///chats/{chat_id}/messages/{message_id}" in description
        assert "teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}" in description
        assert (
            "teams:///teams/{team_id}/channels/{channel_id}/messages/{root_id}/replies/{reply_id}"
            in description
        )
        assert "search_messages" in description
        assert "browse_channel" in description, "the reply shape has exactly one source"

    async def test_browse_channel_needs_both_ids_and_bounds_its_page_where_graph_does(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """A channel id alone addresses nothing — Graph's only path to a channel's messages goes
        through its team — and 20/50 are Graph's own default and maximum for the collection."""
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
        thread and may be years old — a tool that let "newest first" be assumed would have the
        model reporting an old post as today's news.
        """
        tools = _named(await mcp_client.list_tools())
        description = tools["browse_channel"].description
        assert description is not None

        assert "reply chain" in description
        assert "created_at" in description, "the field that does tell the truth about age"
        assert "search_messages" in description, "where a date-bounded question goes instead"

    async def test_browse_channel_says_what_one_call_costs_and_where_it_stops(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The budget is only a bound if the caller can see it. Microsoft allows this whole
        connector about one request a second on a given channel across the tenant, so the tool
        makes exactly one — which means `limit` is the entire window, and a model that expects
        paging to reach further has to be told it does not, in the description and in the schema
        rather than only in the code.
        """
        tools = _named(await mcp_client.list_tools())
        description = tools["browse_channel"].description
        limit = _object(_properties(tools["browse_channel"].inputSchema)["limit"])
        assert description is not None

        assert "makes one request" in description
        assert "raise `limit` rather than calling again" in description, (
            "where it stops: the window widens, it never pages deeper"
        )
        assert "one request against the channel" in str(limit["description"])
        assert "browsing again returns the same newest" in description, (
            "the reply window is a dead end, not a first page"
        )
        assert "stop looking" in description

    async def test_list_meeting_transcripts_names_its_five_answers_and_their_remedies(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The four absences that must stay distinct, plus "no such meeting". A model can only act
        differently on them if the tool says what each one means, so the words are asserted: the
        one that means wait must say wait and must say it is not the one that means stop, and the
        one that means "this was not knowable" must not be reportable as either."""
        tools = _named(await mcp_client.list_tools())
        description = tools["list_meeting_transcripts"].description
        status = _object(_properties(tools["list_meeting_transcripts"].outputSchema)["status"])
        assert description is not None
        rendered = description + str(status.get("description"))

        for value in (
            "available",
            "not_ready",
            "not_transcribed",
            "scan_incomplete",
            "meeting_not_found",
        ):
            assert value in description, value
        assert "Wait and call again later" in description
        assert 'NOT "there is no transcript"' in description
        assert "Retrying will not help" in description
        assert "no availability SLA" in rendered, "the inference has to be admitted as one"
        assert "recurring" in description and "started_after" in description
        assert 'Never report it as "there is no transcript"' in description
        assert "not known" in description, "the fifth answer claims nothing, and has to say so"

    async def test_the_answer_with_no_remedy_says_it_has_none(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """Four of the five statuses tell a caller what to do next; `scan_incomplete` cannot,
        because the window is applied after Microsoft has answered and so no argument sends the
        next call further into the collection. Advice that sounds actionable and is not is worse
        than a dead end stated plainly — it is a loop a model runs until something else stops it —
        so both the tool and the field say to stop.
        """
        tools = _named(await mcp_client.list_tools())
        description = tools["list_meeting_transcripts"].description
        status = str(_object(_properties(tools["list_meeting_transcripts"].outputSchema)["status"]))
        assert description is not None

        assert "nothing to try" in description and "Stop here" in description
        assert "There is nothing to try" in status and "do not ask again" in status
        assert "reads the same transcripts and returns this same answer" in description, (
            "a narrower window is named only as the thing that does NOT help"
        )

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
        """A bare `2026-08-11` is what a model writes when scoping a series to one occurrence — the
        only reason these parameters exist — so the schema has to say a date is legal. A schema
        offering only `date-time` while the code accepted a date anyway is a disagreement the model
        pays for: it is never told which shape was meant."""
        tools = _named(await mcp_client.list_tools())
        properties = _properties(tools["list_meeting_transcripts"].inputSchema)

        assert _optional_types(properties[bound]) == [
            {"type": "string", "format": "date"},
            {"type": "string", "format": "date-time"},
        ]

    async def test_the_occurrence_window_states_the_zone_it_resolves_against(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """`09:00` is a different instant in every zone, so a tool that silently picks one has to
        say which — in the parameter's own description, which is the only place a model reads before
        writing the value. Both halves are asserted: what an offset-less timestamp means, and what a
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
        ended last month polls forever — so both the tool and the field say the verdict follows the
        window that was asked for, not the meeting."""
        tools = _named(await mcp_client.list_tools())
        description = tools["list_meeting_transcripts"].description
        status = _object(_properties(tools["list_meeting_transcripts"].outputSchema)["status"])
        assert description is not None

        assert "window you asked about" in description
        assert "already well past never answers this" in description
        assert "demonstrably passed is never reported this way" in str(status["description"])

    async def test_no_description_names_a_tool_this_server_does_not_advertise(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """A description is protocol surface a model reads as fact, so a tool named in one has to
        exist. These tools arrive one per PR and each is written knowing the shape of the ones
        still to come, which is exactly how a description comes to promise `read_message` a
        deployment of this commit does not have — and the failure is the worst kind: the model
        stops treating what it was given as the answer and calls something that is not there.

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

        # Guards the guard, the way `tests/test_layering.py` guards each of its rules: these tools
        # do point a model at one another, so a check that found nothing to check would be passing
        # by a pattern that had stopped matching rather than by the descriptions being honest.
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
        """The whole of this tool over the real protocol, and both halves are things only an
        end-to-end call can show.

        Nothing on the wire: `/me/joinedTeams` supports no OData query parameter at all, so a
        `$top` or a `$select` reaching Graph is a 400 rather than a narrower answer — and a request
        configuration built by one tool has been able to leak into another's call before, which is
        a leak only a real registration exercises. One scope on the exchange: the token is redeemed
        per tool, so a tenant that withholds the broad channel permission still lists its teams,
        and a tool that quietly asked for the registry's union would take that away without any
        schema changing.
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
        """The channel side end to end, over the real protocol, with every id taken from the
        previous answer exactly as a model would take it: which teams am I in, what channels are in
        this team, what was posted in this channel — and then the reply's own handle, resolved.

        That last step is the gap this piece closes. Graph addresses a reply under the post it
        answers, so before browsing existed no tool could produce a handle for one: a search hit on
        a reply carries the root-post shape and Graph answers it 404. Here the browse mints the
        reply's handle and read_message resolves it, which is the whole contract between the two.

        The token is redeemed per tool, so a tenant that grants the two basic channel scopes and
        withholds the broad message one is refused at the third step rather than the first; a tool
        that quietly asked for the registry's union would take that distinction away without any
        schema changing.
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
        """The signal this tool cannot infer, over the real protocol. Without it these two answers
        are byte-identical: one page of posts WITH an `@odata.nextLink` and the same page without
        one, so a caller could not tell "that was the whole channel" from "Microsoft says there is
        more".

        It is the one list here where that is not derivable. Everywhere else the walk underneath
        followed Microsoft's paging to the end of the collection, so a short answer IS the end; this
        tool makes one request against a channel Microsoft rate-limits to about one a second for the
        whole connector, and drops system messages out of the page after Microsoft counted them into
        it. So the cursor is read and reported when asked for — and, asked for, it is accurate.
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
        """The bound on pages carrying nothing, measured over the real protocol where it is
        actually spent rather than read off the constant that claims it.

        An empty page carrying a cursor means keep going, so a collection that answers only those
        has to be given up on — and it must FAIL rather than answer, because every short answer
        above this walk means a cap: from `list_chats` it would mean the user has no more chats,
        and from `list_meeting_transcripts` it would mean a meeting was never transcribed. Eleven
        requests each: the caller's own first page, and the run of empty ones this walk will follow
        before refusing. Both tools are here because they pass different `max_scanned` values and
        this bound must not vary with either — an empty page spends no scan budget at all, which is
        why it is counted against its own number and not against that one.
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
        """The flagship call, end to end: one POST to Microsoft's search index, hits carrying a
        handle that names the exact message matched, and both search permissions on the exchanged
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
        """The whole point of the pair, over the real protocol: search returns a handle and no body,
        and the handle — passed back verbatim, exactly as a model would — resolves into the text.
        """
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
        an empty message would read as "they said nothing"; the event is what actually happened."""
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
        """A message body is as sensitive as the query that found it, and this tool is the one that
        actually returns message content — so the same rule search is held to holds here, over the
        whole call and both destinations."""
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
        once — so the rule search and read are held to holds here too, over the whole call."""
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
        """End to end, the recall bug: a two-word question has to arrive at Microsoft's index as
        two terms it will AND, not as one quoted phrase that only matches them side by side."""
        route = graph.post("/search/query").mock(return_value=httpx.Response(200, json=_SEARCH))

        _ = await mcp_client.call_tool("search_messages", {"query": "cut the release"})

        assert _search_query_string(route) == "cut the release"

    @pytest.mark.usefixtures("obo")
    async def test_a_search_with_no_criteria_is_refused_and_says_what_to_add(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """FastMCP validates arguments against the signature, not against the advertised schema, so
        the `anyOf` alone would not stop this — and Graph would answer it with an arbitrary slice of
        everything the user can read, which looks exactly like a result set."""
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
        of its spans and logs, so this connector never puts them there — and this test is what says
        so, over the whole call, not over one function.

        Both destinations are checked. The log capture covers everything this process emits during
        the call, ours and FastMCP's own. The span half is no longer a ratchet against a path that
        creates no spans: the Graph SDK opens a dozen per request, and `recorded_spans` refuses to
        pass on an empty list.
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
        """Tool rejects arguments it does not expect."""
        route = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        result = await mcp_client.call_tool(
            "get_me", {"user_id": "00000000-0000-4000-8000-000000000002"}, raise_on_error=False
        )

        assert result.is_error
        assert not route.called
        assert not obo.requested_scopes

    async def test_a_model_walks_from_a_meeting_chat_to_the_meetings_transcripts(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """The path this tool exists to complete, over the real protocol, with every value taken
        from the previous answer exactly as a model would take it: which meetings are there
        (list_chats, because a meeting chat *is* the index), and then what transcripts this one has.

        The connector this was compared against reaches a meeting only through an opaque URI it got
        from a calendar read; this walk needs no calendar permission at all.
        """
        chats_route = graph.get("/me/chats").mock(
            return_value=httpx.Response(200, json=_MEETING_CHATS)
        )
        meeting = graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        listing = graph.get(_TRANSCRIPTS_PATH).mock(
            return_value=httpx.Response(200, json=_TRANSCRIPTS)
        )

        listed = _structured(await mcp_client.call_tool("list_chats", {"limit": 5}))
        found = cast("Sequence[Mapping[str, object]]", listed["chats"])
        meeting_uri = found[0]["meeting_uri"]
        available = _structured(
            await mcp_client.call_tool("list_meeting_transcripts", {"meeting_uri": meeting_uri})
        )

        assert all(route.called for route in (chats_route, meeting, listing))
        assert found[0]["chat_type"] == "meeting"
        assert meeting_uri == _MEETING_URI, "the handle one tool minted is what the other took"
        assert available["status"] == "available"
        assert available["subject"] == "Pricing review"
        assert available["meeting_id"] == _MEETING_ID
        assert available["scan_incomplete"] is None, "nobody asked how far the read got"
        transcripts = cast("Sequence[Mapping[str, object]]", available["transcripts"])
        assert [item["transcript_id"] for item in transcripts] == [_TRANSCRIPT_ID]
        assert listing.calls.last.request.headers["authorization"] == f"Bearer {OBO_TOKEN}"
        assert obo.requested_scopes == [
            ("https://graph.microsoft.com/Chat.Read",),
            (
                "https://graph.microsoft.com/OnlineMeetings.Read",
                "https://graph.microsoft.com/OnlineMeetingTranscript.Read.All",
            ),
        ], "resolving the join URL and reading the collection are two permissions, one exchange"

    @pytest.mark.usefixtures("obo")
    async def test_asking_for_the_latest_of_a_series_answers_with_the_latest(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """ "The latest transcript of this series", over the real protocol — the question this tool
        exists for. Microsoft answers this collection in an order of its own, so a `limit` applied
        before ordering returns an arbitrary handful sorted among themselves: a model asking for the
        newest one gets whichever occurrence Microsoft happened to put first, with nothing in the
        answer to say so. Microsoft's order here puts the oldest first, which is exactly what that
        shape would return.
        """
        _ = graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        _ = graph.get(_TRANSCRIPTS_PATH).mock(
            return_value=httpx.Response(200, json=_SERIES_TRANSCRIPTS)
        )

        answer = _structured(
            await mcp_client.call_tool(
                "list_meeting_transcripts",
                {"meeting_uri": _MEETING_URI, "limit": 1, "include_scan_completeness": True},
            )
        )

        listed = cast("Sequence[Mapping[str, object]]", answer["transcripts"])
        assert [item["transcript_id"] for item in listed] == ["week-3"], "the newest, not the first"
        assert answer["status"] == "available"
        assert len(listed) == 1, "a full window: the two older occurrences are behind it"
        assert answer["scan_incomplete"] is False, (
            "and the collection was read to the end, so this IS the meeting's latest — the two "
            "facts one flag could not tell apart"
        )

    @pytest.mark.usefixtures("obo")
    async def test_a_meeting_larger_than_one_call_reads_answers_within_what_it_read(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """The rare meeting both promises have to be exact about, over the real protocol: a series
        that ran daily for most of a year, so its collection is longer than one call reads.

        Two things are asserted. Asking for the newest returns the newest of the transcripts READ —
        `day-199` — and never the meeting's actual newest, which sits past the cap where nothing
        here can see it, with the opt-in `scan_incomplete` as the answer's own admission of that.
        And a window over the part that was not read answers `scan_incomplete` whether it is wide or
        narrow, because the window is applied to what came back: narrowing it is not a remedy, which
        is why the tool does not offer it as one.
        """
        _ = graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        _ = graph.get(_TRANSCRIPTS_PATH).mock(
            return_value=httpx.Response(200, json=_daily_series())
        )

        newest = _structured(
            await mcp_client.call_tool(
                "list_meeting_transcripts",
                {"meeting_uri": _MEETING_URI, "limit": 1, "include_scan_completeness": True},
            )
        )
        wide = _structured(
            await mcp_client.call_tool(
                "list_meeting_transcripts",
                {
                    "meeting_uri": _MEETING_URI,
                    "started_after": _day(meetings.MAX_ARTIFACT_SCAN).date().isoformat(),
                    "started_before": _day(_PAST_THE_CAP - 1).date().isoformat(),
                },
            )
        )
        narrow = _structured(
            await mcp_client.call_tool(
                "list_meeting_transcripts",
                {
                    "meeting_uri": _MEETING_URI,
                    "started_after": _day(250).date().isoformat(),
                    "started_before": _day(250).date().isoformat(),
                },
            )
        )

        listed = cast("Sequence[Mapping[str, object]]", newest["transcripts"])
        assert [item["transcript_id"] for item in listed] == ["day-199"], (
            "the newest of what was read"
        )
        assert newest["scan_incomplete"] is True, (
            "the read stopped at the cap, and a caller that asked has to be told"
        )
        assert wide["status"] == "scan_incomplete"
        assert narrow["status"] == wide["status"], "a narrower window reads the same transcripts"
        assert wide["transcripts"] == [] and narrow["transcripts"] == []


class TestTheTransportTheToolsShare:
    async def test_it_is_closed_when_the_server_shuts_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Transport closes when the server shuts down."""
        built: list[httpx.AsyncClient] = []

        def record(settings: GraphSettings) -> httpx.AsyncClient:
            transport = create_graph_transport(settings)
            built.append(transport)
            return transport

        monkeypatch.setattr("office_mcp.app.create_graph_transport", record)

        async with Client(FastMCPTransport(_server_of(_build_app()))):
            assert built and not built[0].is_closed

        assert built[0].is_closed


class TestWhatAModelIsToldWhenGraphRefuses:
    async def test_a_missing_permission_names_the_permission(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """403 response names the missing permission."""
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
        """Three requests, three delegated permissions, and a tenant that grants the two basic ones
        while withholding the broad message permission is the common case — so naming the wrong one
        sends an administrator after a permission that was never missing, which is as useless as
        naming none. Graph's 403 says only that something was forbidden.
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
        case — the broad one needs an administrator in most tenants — and Graph's 403 says only
        that something was forbidden. So the remedy has to name both: handed one name, an
        administrator may grant the permission that was never missing and watch the identical
        failure. Naming both is also what the single-permission tools must NOT do, which is why
        the wording is taken from each tool's own declared tuple rather than from the registry's
        union.
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
        """The tenant that grants `Chat.Read` and withholds `ChannelMessage.Read.All`.

        Entra redeems a two-scope exchange as a whole and refuses it as a whole, naming no more than
        the application: which of the two was missing is not in AADSTS65001 any more than it is in a
        Graph 403. So the refusal has to name both, exactly as the 403 path does — an administrator
        handed one name may grant the one that was never missing and see the identical failure.

        This is also the assertion that says the wording here is *ours*: the exchange happens inside
        FastMCP's dependency resolution, so without the wrapper the model reads "Failed to resolve
        dependency 'client' for search_teams_messages" — a parameter of a function the model never
        sees — and can act on none of it.
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
    async def test_the_transcript_tenant_switch_names_a_different_administrator(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """The refusal every other 403 on this server would be answered wrongly for, end to end.

        Microsoft Graph access to Teams meeting transcripts is a tenant-wide Teams setting that is
        OFF BY DEFAULT, and Graph reports it with the same status and the same outer code as a
        missing permission. In the commonest tenant, therefore, this is the *first* answer a model
        gets from this tool — so it has to name the Teams admin centre rather than a Graph
        permission, and it has to rule out re-consent, which is what a model would otherwise infer
        from every other refusal here.
        """
        graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        graph.get(_TRANSCRIPTS_PATH).mock(
            return_value=httpx.Response(
                403, headers={"request-id": "synthetic-request-id"}, json=_TENANT_SWITCH_OFF
            )
        )

        refused = await mcp_client.call_tool(
            "list_meeting_transcripts", {"meeting_uri": _MEETING_URI}, raise_on_error=False
        )

        assert refused.is_error
        message = _error_text(refused)
        assert "EnableGraphTranscriptAccess" in message
        assert "Teams administrator" in message
        assert "sign in again will not change it" in message
        assert "OnlineMeetingTranscript.Read.All" not in message, (
            "no permission is missing; naming one sends an administrator after nothing"
        )
        assert "synthetic-request-id" in message, "an operator still needs the evidence"

    async def test_a_meeting_handle_that_was_never_one_is_refused_before_graph(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """A handle this tool cannot use is its own failure to explain, and the explanation has to
        send the caller back to where handles come from rather than invite a retry. The transcript
        shape is named as *not* one, because it is the shape this tool emits and therefore the one
        most likely to be passed back in."""
        route = graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))

        refused = await mcp_client.call_tool(
            "list_meeting_transcripts",
            {"meeting_uri": "19:meeting_TjAwMDAwMDAwMDAwMA@thread.v2"},
            raise_on_error=False,
        )

        assert refused.is_error
        message = _error_text(refused)
        assert "list_chats" in message, "where a meeting handle comes from"
        assert "teams:///meetings/" in message
        assert "fail identically" in message, "and it is not worth retrying"
        assert not route.called, "nothing reached Graph"
        assert obo.requested_scopes, "the handle is parsed inside the tool, after the exchange"

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
        """The first of three failures a reader has to keep apart, and the only one that is this
        connector's own fault to explain: the argument is not a handle. Graph is never called, and
        the remedy is the shape — not "try again"."""
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
        invisible to this user, or gone — Graph does not say which, so neither may the tool. The
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
        which post the reply hangs under — so it 404s. browse_channel is the only tool that mints a
        reply's own handle, but it returns the newest replies of each post on a channel's first page
        and follows neither of Microsoft's cursors past them, since a given channel allows this
        whole connector about one request a second across the tenant. "Browse the channel instead"
        is therefore a route for a recent reply and a loop for an older one, so this text has to
        name the window, say there is no route beyond it, and tell the model what to answer with.
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
        message read are per surface, so a 403 reading a chat can only be about `Chat.Read` —
        naming the channel permission too would send them after one that was never missing, which
        is the same defect as naming none.
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
        """The other half of the same rule: the tenant that grants `Chat.Read` and withholds the
        broad channel permission is the common case, and this is the message that gets fixed."""
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
        """Entra refusal (AADSTS65001) for unconsented permission names the permission."""
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
