"""The whole loop, over the real MCP protocol: client → tool → OBO token → Microsoft Graph.

This drives the app `create_app` actually builds — same FastMCP server, same Entra auth provider,
same registered tools, same shared Graph transport — through fastmcp's own in-process client. Only
the two external systems are stood in for, at exactly the boundary each one owns:

* **Entra's token endpoint.** The signed-in user's token and the On-Behalf-Of exchange are
  replaced, because the exchange is a network call to login.microsoftonline.com. What is *not*
  replaced is `EntraOBOToken` itself: the dependency still runs, still finds the app's
  `AzureProvider`, and the token it produces is the one the tool must put on the wire.
* **Microsoft Graph**, via respx.

Every payload is synthesised: fake ids, `.invalid` domains, public-domain names.
"""

import json
import logging
import re
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
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
from office_mcp.config import AppConfig, DatabaseConfig, EntraConfig
from office_mcp.features import channels
from office_mcp.graph_client import GraphSettings, create_graph_transport

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

# The token the (stubbed) On-Behalf-Of exchange hands back. Asserting on it is what proves the
# caller's delegated token — and not the connector's own — is what called Graph.
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

# The meeting side, end to end. The join URL is shaped like the ones Graph stores — already-escaped
# `%3a`/`%40`, a `?context=` query, an `&` parameter — because that shape is what the `$filter` has
# to survive. Nothing here is a real meeting: the words are invented and the speakers are long dead.
_JOIN_WEB_URL = (
    "https://teams.microsoft.invalid/l/meetup-join/"
    + "19%3ameeting_TjAwMDAwMDAwMDAwMA%40thread.v2/0"
    + "?context=%7b%22Tid%22%3a%228a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81%22%7d&anon=true"
)
_MEETING_ID = "MSpiYTMyMWUwZC03OWVlLTQ3OGQtOGUyOC04NWExOTUwN2Y0NTYqMCoq"
_TRANSCRIPT_ID = "MSMjMCMjSYNTHETIC0001"
_MEETINGS_PATH = "/me/onlineMeetings"
_TRANSCRIPTS_PATH = f"/me/onlineMeetings/{_MEETING_ID}/transcripts"
_CONTENT_PATH = f"{_TRANSCRIPTS_PATH}/{_TRANSCRIPT_ID}/content"

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

_TRANSCRIPT_VTT = """WEBVTT

00:00:16.246 --> 00:00:19.900
<v Grace Hopper>We should raise the floor price by three per cent.</v>

00:01:02.000 --> 00:01:04.500
<v Ada Lovelace>Agreed, that works.</v>
"""

_TENANT_SWITCH_OFF = {
    "error": {
        "code": "Forbidden",
        "message": "Graph API access to transcripts is disabled for this tenant.",
        "innerError": {"code": "GraphAccessToTranscriptsDisabled"},
    }
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


class _StubOboCredential:
    """Stands in for `azure.identity.aio.OnBehalfOfCredential`, which would call Entra.

    Records the scopes it was asked for: those are what the tool declared it needs, and getting
    them wrong is invisible until a real tenant refuses the exchange. Set `refusal` to be that
    tenant — an exchange Entra declines is the failure that happens before Graph.
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
    """Authenticate the in-process caller and stub only the Entra round trip."""
    credential = _StubOboCredential()

    async def get_obo_credential(
        _self: AzureProvider, *, user_assertion: str
    ) -> _StubOboCredential:
        assert user_assertion == _CLIENT_TOKEN, "the caller's own token is what gets exchanged"
        return credential

    monkeypatch.setattr(AzureProvider, "get_obo_credential", get_obo_credential)
    # `EntraOBOToken` reads the caller's token through this function; there is no HTTP request
    # behind an in-process client, so there is nothing for it to read it from.
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


def _build_app() -> Starlette:
    return create_app(
        config=AppConfig.model_validate({"public_base_url": "https://office-mcp.example"}),
        # Nothing in these tests reaches Postgres: the engine is lazy and the OAuth state store is
        # only touched by the HTTP auth path, which an in-process client does not go through.
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
    )


@pytest.fixture
def app() -> Starlette:
    return _build_app()


def _server_of(app: Starlette) -> FastMCP[None]:
    """The FastMCP server `create_app` mounted, which is what the MCP protocol talks to."""
    return cast("FastMCP[None]", app.state.fastmcp_server)


@pytest.fixture
async def mcp_client(app: Starlette) -> AsyncIterator[Client[FastMCPTransport]]:
    """A real MCP client speaking to that server, lifespan and all."""
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


def _optional_types(schema: object) -> list[dict[str, object]]:
    """Every non-null branch of an optional parameter's schema, in the order it declares them."""
    branches = cast("Sequence[object]", _object(schema)["anyOf"])
    return [_object(branch) for branch in branches if _object(branch).get("type") != "null"]


def _optional_type(schema: object) -> dict[str, object]:
    """The one non-null branch of an optional parameter's schema, where it has exactly one."""
    typed = _optional_types(schema)
    assert len(typed) == 1, f"expected one non-null branch, got {typed!r}"
    return typed[0]


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
    async def test_every_tool_is_listed_and_none_asks_for_a_token(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The Graph token is a dependency, not a parameter: if it ever leaked into the input
        schema, a model would try to invent one."""
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
        }
        for tool in tools.values():
            assert "graph_token" not in _properties(tool.inputSchema)

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
        """The oracle connector returns an unschematised stream of objects whose last element may
        be pagination metadata. A declared output schema is how `truncated` stops being prose."""
        tools = _named(await mcp_client.list_tools())

        assert set(_properties(tools["get_me"].outputSchema)) == {
            "user_id",
            "display_name",
            "email",
            "user_principal_name",
            "job_title",
        }
        assert set(_properties(tools["list_chats"].outputSchema)) == {"chats", "truncated"}
        assert set(_properties(tools["list_teams"].outputSchema)) == {"teams", "truncated"}
        assert set(_properties(tools["list_channels"].outputSchema)) == {"channels", "truncated"}
        assert set(_properties(tools["browse_channel"].outputSchema)) == {"messages", "truncated"}
        assert set(_properties(tools["search_messages"].outputSchema)) == {
            "messages",
            "truncated",
            "next_offset",
        }
        assert set(_properties(tools["list_meeting_transcripts"].outputSchema)) == {
            "status",
            "meeting_id",
            "subject",
            "meeting_type",
            "started_at",
            "ended_at",
            "transcripts",
            "truncated",
        }
        assert set(_properties(tools["read_transcript"].outputSchema)) == {
            "uri",
            "meeting_id",
            "transcript_id",
            "speaker_attribution",
            "turns",
            "truncated",
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

    async def test_the_whole_surface_speaks_one_language(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """These tools arrived one at a time and are read all at once, by a model choosing between
        them. So the conventions are asserted rather than merely written down: a name is verb_noun
        (`whoami` was the one exception and is now `get_me`), a result field is snake_case, and a
        tool whose answer is a list says "there is more" with the one word `truncated` — two words
        for that would be two things for a model to learn, and a reason for it to guess.
        """
        tools = _named(await mcp_client.list_tools())

        for name in tools:
            assert re.fullmatch(r"[a-z]+(_[a-z]+)+", name), f"{name} is not verb_noun"
        for tool in tools.values():
            for field in _properties(tool.outputSchema):
                assert re.fullmatch(r"[a-z][a-z0-9]*(_[a-z0-9]+)*", field), f"{field} is not snake"
        for name in (
            "list_chats",
            "list_teams",
            "list_channels",
            "browse_channel",
            "search_messages",
            "list_meeting_transcripts",
            "read_transcript",
        ):
            assert "truncated" in _properties(tools[name].outputSchema), name

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

    async def test_read_transcript_takes_a_handle_and_a_window_and_names_its_one_shape(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """A second reader, deliberately: a transcript is read under a different permission from a
        message, and a token is exchanged per tool — so one polymorphic reader would have to redeem
        transcript access to read a chat message. Its handle shape is therefore its own, and the
        description has to name it and say which tool mints it."""
        tools = _named(await mcp_client.list_tools())
        schema = tools["read_transcript"].inputSchema
        description = tools["read_transcript"].description
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
        assert "teams:///transcripts/{meeting_id}/{transcript_id}" in description
        assert "list_meeting_transcripts" in description
        assert "read_message" in description, "the two readers must not be confusable"

    async def test_read_transcript_narrows_by_seconds_and_by_speaker_in_its_own_schema(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The turns are already timestamped and attributed in the answer, so the filters are named
        in the same units the answer reports: seconds from the meeting's start, and the speaker as
        the transcript spells them. A model narrows only what it can see, and every one of these is
        optional — the unfiltered read stays the default."""
        tools = _named(await mcp_client.list_tools())
        properties = _properties(tools["read_transcript"].inputSchema)

        for bound in ("from_seconds", "to_seconds"):
            assert _optional_type(properties[bound])["type"] == "number", bound
        assert _optional_type(properties["speaker"])["type"] == "string"
        for name in ("from_seconds", "to_seconds", "speaker"):
            assert _object(properties[name]).get("description"), f"{name} is undescribed"

    async def test_list_meeting_transcripts_names_the_four_answers_and_their_remedies(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The three absences that must stay distinct, plus "no such meeting". A model can only act
        differently on them if the tool says what each one means, so the words are asserted: the
        one that means wait must say wait, and must say it is not the one that means stop."""
        tools = _named(await mcp_client.list_tools())
        description = tools["list_meeting_transcripts"].description
        status = _object(_properties(tools["list_meeting_transcripts"].outputSchema)["status"])
        assert description is not None
        rendered = description + str(status.get("description"))

        for value in ("available", "not_ready", "not_transcribed", "meeting_not_found"):
            assert value in description, value
        assert "Wait and call again later" in description
        assert 'NOT "there is no transcript"' in description
        assert "Retrying will not help" in description
        assert "no availability SLA" in rendered, "the inference has to be admitted as one"
        assert "recurring" in description and "started_after" in description

    async def test_list_meeting_transcripts_takes_a_meeting_handle_and_an_occurrence_window(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        tools = _named(await mcp_client.list_tools())
        schema = tools["list_meeting_transcripts"].inputSchema
        properties = _properties(schema)
        limit = _object(properties["limit"])

        assert set(properties) == {"meeting_uri", "started_after", "started_before", "limit"}
        assert schema.get("required") == ["meeting_uri"]
        assert (limit["type"], limit["minimum"], limit["maximum"], limit["default"]) == (
            "integer",
            1,
            50,
            20,
        )

    @pytest.mark.parametrize("bound", ["started_after", "started_before"], ids=["after", "before"])
    async def test_each_occurrence_bound_admits_a_bare_date_in_its_own_schema(
        self, mcp_client: Client[FastMCPTransport], bound: str
    ) -> None:
        """A bare `2026-08-11` is what a model writes when scoping a series to one occurrence — the
        only reason these parameters exist — so the schema has to say a date is legal. A schema
        offering only `date-time` while the code accepted a date anyway is the disagreement the
        crash came from: the model was never told which shape was meant."""
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

    async def test_browse_channel_needs_both_ids_and_bounds_its_page_where_graph_does(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """A channel id alone addresses nothing — Graph's only path to a channel's messages goes
        through its team — and 20/50 are Graph's own default and maximum for the collection."""
        tools = _named(await mcp_client.list_tools())
        schema = tools["browse_channel"].inputSchema
        limit = _object(_properties(schema)["limit"])

        assert set(_properties(schema)) == {"team_id", "channel_id", "limit"}
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

        assert "exactly one request" in description
        assert "never pages deeper" in description
        assert "one request against the channel" in str(limit["description"])
        assert "browsing again returns the same newest replies" in description, (
            "the reply window is a dead end, not a first page"
        )
        assert "do not browse again for it" in description

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
        assert "not matched as a phrase unless you quote them" in description
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
        assert body["truncated"] is False
        listed = cast("Sequence[Mapping[str, object]]", body["chats"])
        assert [chat["chat_id"] for chat in listed] == ["19:release@thread.v2"]
        assert listed[0]["last_message_at"] == "2026-02-11T09:15:22.310000Z"
        assert obo.requested_scopes == [("https://graph.microsoft.com/Chat.Read",)]

    async def test_search_messages_returns_hits_with_handles_and_no_invented_total(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """The flagship call, end to end: one POST to Microsoft's search index, hits carrying a
        handle a reader can resolve, and both search permissions on the exchanged token."""
        route = graph.post("/search/query").mock(return_value=httpx.Response(200, json=_SEARCH))

        result = await mcp_client.call_tool("search_messages", {"query": "release"})

        body = _structured(result)
        assert body["truncated"] is False
        assert body["next_offset"] is None
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

    async def test_a_model_walks_from_a_meeting_chat_to_what_was_said_in_the_meeting(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """The flagship path of this piece, over the real protocol, with every value taken from the
        previous answer exactly as a model would take it: which meetings are there (list_chats,
        because a meeting chat *is* the index), what transcripts does this one have, and then the
        words — speaker-attributed and timestamped, not a link to a file.

        The oracle connector reaches a transcript only through an opaque URI it got from a calendar
        read; this walk needs no calendar permission at all, and it ends in text.
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
        assert available["status"] == "available"
        assert available["subject"] == "Pricing review"
        assert available["meeting_id"] == _MEETING_ID
        assert read["speaker_attribution"] is True
        turns = cast("Sequence[Mapping[str, object]]", read["turns"])
        assert [(turn["speaker"], turn["start_seconds"]) for turn in turns] == [
            ("Grace Hopper", 16.246),
            ("Ada Lovelace", 62.0),
        ]
        assert turns[0]["text"] == "We should raise the floor price by three per cent."
        assert read["truncated"] is False
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

    async def test_the_join_url_reaches_graph_encoded_exactly_once_over_the_real_protocol(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """End to end, the bug class: `services/teams-mcp` sends a raw join URL and Microsoft
        answers `200 OK` with an empty result — a silent "meeting not found" — for any URL carrying
        `&` or `#`. The handle carries the URL through the protocol unchanged, and the `$filter`
        Graph receives has to decode back to exactly what Microsoft stored."""
        graph.get("/me/chats").mock(return_value=httpx.Response(200, json=_MEETING_CHATS))
        route = graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        graph.get(_TRANSCRIPTS_PATH).mock(return_value=httpx.Response(200, json=_TRANSCRIPTS))

        listed = _structured(await mcp_client.call_tool("list_chats", {}))
        found = cast("Sequence[Mapping[str, object]]", listed["chats"])
        _ = await mcp_client.call_tool(
            "list_meeting_transcripts", {"meeting_uri": found[0]["meeting_uri"]}
        )

        url = route.calls.last.request.url
        assert url.params["$filter"] == f"JoinWebUrl eq '{_JOIN_WEB_URL}'"
        raw = url.query.decode()
        assert "%253ameeting" in raw and "%2540thread" in raw and "%26anon%3Dtrue" in raw
        assert "%2525" not in raw
        assert obo.requested_scopes

    @pytest.mark.usefixtures("obo")
    async def test_the_transcript_text_reaches_the_caller_and_no_log_or_span(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A transcript is the most sensitive content this connector touches — a verbatim record of
        what people said in a room — so the rule search and read are held to is tightest here: the
        words reach the caller and no log line and no span attribute anywhere in the process."""
        exporter = InMemorySpanExporter()
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
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
        for span in exporter.get_finished_spans():
            assert secret not in str(span.attributes)

    @pytest.mark.usefixtures("obo")
    async def test_a_meeting_no_join_url_matches_is_a_status_and_not_an_error(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """Microsoft answers this filter with `200 OK` and an empty `value` rather than a 404, so
        "no match" must not arrive as a failure — and must not be reported as the meeting having
        been deleted either."""
        graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json={"value": []}))
        listing = graph.get(_TRANSCRIPTS_PATH).mock(
            return_value=httpx.Response(200, json=_TRANSCRIPTS)
        )

        result = await mcp_client.call_tool(
            "list_meeting_transcripts",
            {"meeting_uri": f"teams:///meetings/{quote(_JOIN_WEB_URL, safe='')}"},
        )

        assert not result.is_error
        body = _structured(result)
        assert body["status"] == "meeting_not_found"
        assert body["transcripts"] == []
        assert not listing.called

    @pytest.mark.usefixtures("obo")
    @pytest.mark.parametrize(
        ("started_after", "started_before"),
        [
            ("2026-02-10", "2026-02-10"),
            ("2026-02-10T14:00:00", "2026-02-10T14:30:00"),
            ("2026-02-10T15:00:00+01:00", "2026-02-10T15:30:00+01:00"),
            ("2026-02-10T14:00:00Z", None),
        ],
        ids=["bare-dates", "no-offset", "offset", "one-sided"],
    )
    async def test_the_window_shapes_a_model_writes_are_answered_and_never_raised(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        started_after: str,
        started_before: str | None,
    ) -> None:
        """Over the real protocol, in the shapes a model sends: scoping a recurring series to one
        occurrence is the only reason these parameters exist, and a model writes `2026-02-10` or
        `2026-02-10T14:00:00` as readily as an offset-bearing timestamp. Every one of them used to
        reach a naive-versus-aware comparison and come back as a raw `TypeError` — a failure naming
        no remedy, for a value the tool's own schema had accepted.
        """
        graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))
        graph.get(_TRANSCRIPTS_PATH).mock(return_value=httpx.Response(200, json=_TRANSCRIPTS))

        result = await mcp_client.call_tool(
            "list_meeting_transcripts",
            {
                "meeting_uri": f"teams:///meetings/{quote(_JOIN_WEB_URL, safe='')}",
                "started_after": started_after,
                "started_before": started_before,
            },
        )

        assert not result.is_error, "a window a model plausibly writes must not fail the call"
        body = _structured(result)
        assert body["status"] == "available"
        assert len(cast("Sequence[object]", body["transcripts"])) == 1

    @pytest.mark.usefixtures("obo")
    async def test_a_window_a_model_could_not_have_meant_is_refused_before_any_graph_request(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """The other half of "never crash": what is not a date at all is rejected by the schema, so
        the failure names the parameter and the shape rather than surfacing an exception from inside
        a comparison — and it costs no Graph request."""
        meetings = graph.get(_MEETINGS_PATH).mock(return_value=httpx.Response(200, json=_MEETING))

        result = await mcp_client.call_tool(
            "list_meeting_transcripts",
            {
                "meeting_uri": f"teams:///meetings/{quote(_JOIN_WEB_URL, safe='')}",
                "started_after": "last Tuesday",
            },
            raise_on_error=False,
        )

        assert result.is_error
        assert "started_after" in _error_text(result)
        assert not meetings.called

    @pytest.mark.usefixtures("obo")
    async def test_a_transcript_is_read_narrowed_to_a_speaker_and_to_a_stretch_of_the_meeting(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """Over the real protocol, in the two shapes a model reaches for: "what did she say" and
        "what was said after that point". An hour of meeting is thousands of turns and a model that
        can only ask for all of them spends its context on the transcript instead of the answer.
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
        assert by_speaker["truncated"] is False, "one turn matched and one turn came back"
        turns = cast("Sequence[Mapping[str, object]]", by_time["turns"])
        assert [turn["start_seconds"] for turn in turns] == [62.0]
        assert content.call_count == 2, "paging and filtering are over the parsed turns, not Graph"

    @pytest.mark.usefixtures("obo")
    @pytest.mark.parametrize(
        ("filters", "named"),
        [
            ({"from_seconds": 60, "to_seconds": 30}, "from_seconds"),
            ({"speaker": ""}, "speaker"),
            ({"speaker": "   "}, "speaker"),
        ],
        ids=["inverted-window", "empty-speaker", "blank-speaker"],
    )
    async def test_a_filter_no_transcript_could_satisfy_is_refused_before_any_graph_request(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        filters: Mapping[str, object],
        named: str,
    ) -> None:
        """A window that ends before it starts, and a speaker that names nobody, both match nothing
        by construction — answering them with an empty page would read as "she said nothing in the
        meeting", which is a wrong answer nobody can detect. The refusal names the parameter, and it
        costs no Graph request."""
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

    @pytest.mark.usefixtures("obo")
    async def test_a_channel_post_reaches_the_caller_and_no_log_or_span(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A channel post is message content like any other, and this tool returns a page of it at
        once — so the rule search and read are held to holds here too, over the whole call."""
        exporter = InMemorySpanExporter()
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
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
        for span in exporter.get_finished_spans():
            assert secret not in str(span.attributes)

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
    ) -> None:
        """A message body is as sensitive as the query that found it, and this tool is the one that
        actually returns message content — so the same rule search is held to holds here, over the
        whole call and both destinations."""
        exporter = InMemorySpanExporter()
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        secret = "acquisition-of-northwind-traders"
        payload = {**_MESSAGE, "body": {"contentType": "text", "content": secret}}
        _ = graph.get(_MESSAGE_PATH).mock(return_value=httpx.Response(200, json=payload))
        caplog.set_level(logging.DEBUG)

        result = await mcp_client.call_tool("read_message", {"uri": _MESSAGE_URI})

        assert _structured(result)["text"] == secret, "the text has to have been returned"
        for record in caplog.records:
            assert secret not in _record_text(record), f"logged by {record.name}"
        for span in exporter.get_finished_spans():
            assert secret not in str(span.attributes)

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
    ) -> None:
        """What a user searched their own messages for is as sensitive as the messages: it names
        people, deals and diagnoses. `services/teams-mcp` had to go back and strip query terms out
        of its spans and logs, so this connector never puts them there — and this test is what says
        so, over the whole call, not over one function.

        Both destinations are checked. The log capture covers everything this process emits during
        the call, ours and FastMCP's own. The span exporter is attached to whatever tracer provider
        is in play: no span is created on this path today, so that half is a ratchet — the day one
        is added carrying the query, it fails here.
        """
        exporter = InMemorySpanExporter()
        provider = trace.get_tracer_provider()
        if not isinstance(provider, TracerProvider):
            provider = TracerProvider()
            trace.set_tracer_provider(provider)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
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
        for span in exporter.get_finished_spans():
            assert secret not in str(span.attributes)

    async def test_an_out_of_range_limit_is_refused_before_graph_is_called(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        route = graph.get("/me/chats").mock(return_value=httpx.Response(200, json=_CHATS))

        result = await mcp_client.call_tool("list_chats", {"limit": 500}, raise_on_error=False)

        assert result.is_error
        assert not route.called
        assert not obo.requested_scopes, "no token is exchanged for a call that cannot run"

    async def test_an_argument_this_tool_does_not_have_is_refused(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """A misremembered parameter — `cursor`, say, which this tool deliberately does not have —
        must fail rather than be ignored, or the model believes it paged when it re-read page one.
        """
        route = graph.get("/me/chats").mock(return_value=httpx.Response(200, json=_CHATS))

        result = await mcp_client.call_tool("list_chats", {"cursor": "abc"}, raise_on_error=False)

        assert result.is_error
        assert not route.called
        assert not obo.requested_scopes


class TestTheTransportTheToolsShare:
    async def test_it_is_closed_when_the_server_shuts_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One connection pool serves every tool call, so nothing else in the process would ever
        notice it being leaked — until a pod's sockets ran out."""
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
        """End to end, the case the oracle connector handles worst: a 403 that says only that
        something was forbidden leaves a model with nothing to do but retry."""
        graph.get("/me/chats").mock(
            return_value=httpx.Response(
                403,
                headers={"request-id": "synthetic-request-id"},
                json={"error": {"code": "Authorization_RequestDenied", "message": "denied"}},
            )
        )

        result = await mcp_client.call_tool("list_chats", {}, raise_on_error=False)

        assert result.is_error
        message = _error_text(result)
        assert "Chat.Read" in message
        assert "administrator" in message
        assert "synthetic-request-id" in message
        assert obo.requested_scopes, "the failure came from Graph, not from the token exchange"

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

    async def test_a_permission_nobody_consented_to_names_it_too(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """The same missing permission, one step earlier: Entra refuses the On-Behalf-Of exchange
        (AADSTS65001) and Graph is never called.

        This runs inside FastMCP's dependency resolution rather than inside the tool body, so it
        bypasses the tool's own error handling entirely — the report a model gets by default is
        "Failed to resolve dependency 'graph_token' for list_chats", which names neither the
        permission nor anyone who could grant it. Whatever else changes, this end of the wire has
        to stay as actionable as the 403 above.
        """
        route = graph.get("/me/chats").mock(return_value=httpx.Response(200, json=_CHATS))
        obo.refusal = ClientAuthenticationError(
            message=(
                "AADSTS65001: The user or administrator has not consented to use the application "
                + "with ID '1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061'."
            )
        )

        result = await mcp_client.call_tool("list_chats", {}, raise_on_error=False)

        assert result.is_error
        message = "\n".join(
            block.text for block in result.content if isinstance(block, TextContent)
        )
        assert "Chat.Read" in message, message
        assert "administrator" in message
        assert "AADSTS65001" in message
        assert "resolve dependency" not in message
        assert not route.called, "no token means no Graph request was ever made"

    @pytest.mark.usefixtures("obo")
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
        assert f"newest {channels.MAX_REPLIES_PER_POST} replies" in message, message
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
        """The failure this connector has already paid for once, in `teams-mcp`. Microsoft Graph
        access to transcripts is a tenant switch that is off by default, and while it is off every
        transcript call returns 403 with no request-side workaround. Read as an ordinary 403 it
        would send an administrator to grant a permission that was never missing, and read as a
        consent problem it would send the user round the sign-in loop — so the remedy has to name
        the Teams admin centre, name the cmdlet, and rule both of those out.
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
            "list_meeting_transcripts": {
                "meeting_uri": f"teams:///meetings/{quote(_JOIN_WEB_URL, safe='')}"
            },
            "read_transcript": {"uri": f"teams:///transcripts/{_MEETING_ID}/{_TRANSCRIPT_ID}"},
        }[tool]

        result = await mcp_client.call_tool(tool, arguments, raise_on_error=False)

        assert result.is_error
        message = _error_text(result)
        assert "Teams administrator" in message
        assert "EnableGraphTranscriptAccess" in message
        assert "not a consent problem" in message.replace("NOT a consent", "not a consent")
        assert "sign in again will not change it" in message
        assert "OnlineMeetingTranscript.Read.All" not in message, (
            "naming the permission sends an administrator after one that was never missing"
        )
        assert "synthetic-request-id" in message

    @pytest.mark.usefixtures("obo")
    @pytest.mark.parametrize(
        ("tool", "argument", "uri"),
        [
            ("list_meeting_transcripts", "meeting_uri", "teams:///transcripts/a/b"),
            ("list_meeting_transcripts", "meeting_uri", "19:meeting_x@thread.v2"),
            ("read_transcript", "uri", "teams:///meetings/https%3A%2F%2Fx.invalid%2Fa"),
            ("read_transcript", "uri", "teams:///chats/19%3Ax%40thread.v2/messages/1"),
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
        """Four handle families now exist and a model will mix them up. Each refusal has to name the
        one shape this tool reads and the one tool that mints it — "invalid handle" would leave a
        model guessing, and guessing between families is exactly what produces a loop."""
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
        }[tool]
        for fragment in expected:
            assert fragment in message, message

    @pytest.mark.usefixtures("obo")
    async def test_a_transcript_graph_will_not_return_blames_the_meeting_window_not_the_handle(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """A 404 on a well-formed transcript handle is almost always age: Microsoft stops serving a
        meeting's artifacts once the meeting expires. The message-reader's advice would be wrong
        here in both directions — a transcript is not deleted by a user, and browsing a channel is
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
        dependency 'graph_token' for search_messages" and can act on none of it.
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
