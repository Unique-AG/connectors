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
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import cast

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


def _optional_type(schema: object) -> dict[str, object]:
    """The non-null branch of an optional parameter's schema, which is where its type lives."""
    branches = cast("Sequence[object]", _object(schema)["anyOf"])
    typed = [_object(branch) for branch in branches if _object(branch).get("type") != "null"]
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

        assert set(tools) == {"whoami", "list_chats", "search_messages", "read_message"}
        for tool in tools.values():
            assert "graph_token" not in _properties(tool.inputSchema)

    async def test_whoami_takes_no_arguments(self, mcp_client: Client[FastMCPTransport]) -> None:
        tools = _named(await mcp_client.list_tools())

        assert _properties(tools["whoami"].inputSchema) == {}
        assert tools["whoami"].inputSchema.get("required", []) == []

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

        assert set(_properties(tools["whoami"].outputSchema)) == {
            "id",
            "display_name",
            "mail",
            "user_principal_name",
            "job_title",
        }
        assert set(_properties(tools["list_chats"].outputSchema)) == {"chats", "truncated"}
        assert set(_properties(tools["search_messages"].outputSchema)) == {
            "messages",
            "more_results_available",
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

    async def test_read_message_takes_exactly_one_required_handle(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """A reader with optional parameters would invite a model to try reading "the last message
        in this chat", which no handle expresses and this connector cannot serve."""
        tools = _named(await mcp_client.list_tools())
        schema = tools["read_message"].inputSchema

        assert set(_properties(schema)) == {"uri"}
        assert schema.get("required") == ["uri"]

    async def test_read_message_names_both_handle_shapes_and_no_others(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The description is where a model learns what it may pass. Naming the two shapes is what
        stops it inventing `mail:///` — and the oracle connector's one polymorphic `read_resource`
        is exactly the promise this connector does not make."""
        tools = _named(await mcp_client.list_tools())
        description = tools["read_message"].description
        assert description is not None

        assert "teams:///chats/{chat_id}/messages/{message_id}" in description
        assert "teams:///teams/{team_id}/channels/{channel_id}/messages/{message_id}" in description
        assert "search_messages" in description, "a handle has exactly one source"

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
    async def test_whoami_calls_graph_with_the_exchanged_token(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        route = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        result = await mcp_client.call_tool("whoami", {})

        assert _structured(result)["mail"] == "ada@example.invalid"
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
        assert body["more_results_available"] is False
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
