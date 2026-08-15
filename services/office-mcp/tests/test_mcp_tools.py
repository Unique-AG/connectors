"""Test the MCP protocol: client → tool → On-Behalf-Of token → Microsoft Graph.

Test app from create_app with Entra and Graph stubbed at their boundaries.
"""

import json
import logging
import re
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
from office_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_mcp.graph_client import GraphSettings, create_graph_transport

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
        """The Graph client, and the On-Behalf-Of token inside it, are dependencies. A model that
        was shown either one as an argument would be asked for a value only this server can make."""
        tools = _named(await mcp_client.list_tools())

        assert set(tools) == {"get_me", "list_chats", "search_messages"}
        for tool in tools.values():
            assert "client" not in _properties(tool.inputSchema)

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
        assert set(_properties(tools["search_messages"].outputSchema)) == {
            "messages",
            "next_offset",
        }

    async def test_the_whole_surface_speaks_one_language(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """Tool names are verb_noun, fields are snake_case, no truncated flag.

        The last of those was written down before there was a list-shaped tool to break it. There
        are two now, and between them they are the reason the convention was worth asserting early:
        a window filled to `limit` says there may be more and a short one says there is not,
        `next_offset` says it outright where paging exists, and `truncated` on top of either means
        "raise `limit`" or "nothing will help" with no way to tell which. `list_chats` says it by
        the length of its window, which is only honest because its walk follows Microsoft's paging
        to the end of the collection; `search_messages` cannot say it that way at all, because
        Microsoft reports a page count rather than a match total for Teams messages — so it says it
        with `next_offset` and that field is asserted to be there.
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

    @pytest.mark.usefixtures("obo")
    async def test_a_collection_microsoft_never_ends_is_refused_in_eleven_requests(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
    ) -> None:
        """The bound on pages carrying nothing, measured over the real protocol where it is
        actually spent rather than read off the constant that claims it.

        An empty page carrying a cursor means keep going, so a collection that answers only those
        has to be given up on — and it must FAIL rather than answer, because a short answer from
        this tool means the user has no more chats. Eleven requests: the caller's own first page,
        and the run of empty ones this walk will follow before refusing.
        """
        chats = graph.get("/me/chats").mock(
            return_value=httpx.Response(
                200, json={"value": [], "@odata.nextLink": f"{GRAPH_V1}/me/chats?$skiptoken=loop"}
            )
        )

        listed = await mcp_client.call_tool("list_chats", {}, raise_on_error=False)

        assert listed.is_error, "a walk that gave up must not answer short: a short answer is a cap"
        assert "pages in a row" in _error_text(listed), "and the count is what an operator needs"
        assert chats.call_count == 11, "the caller's own page and the run of empty ones followed"

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
