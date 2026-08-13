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

from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from azure.core.credentials import AccessToken as GraphAccessToken
from fastmcp import Client, FastMCP
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import FastMCPTransport
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.dependencies import AccessToken
from mcp.types import TextContent, Tool
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
    them wrong is invisible until a real tenant refuses the exchange.
    """

    def __init__(self) -> None:
        self.requested_scopes: list[tuple[str, ...]] = []

    async def get_token(self, *scopes: str) -> GraphAccessToken:
        self.requested_scopes.append(scopes)
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


def _structured(result: CallToolResult) -> dict[str, object]:
    data = cast("dict[str, object] | None", result.structured_content)
    assert data is not None, "the tool returned no structured content"
    return data


class TestTheToolsThisServerAdvertises:
    async def test_both_tools_are_listed_and_neither_asks_for_a_token(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The Graph token is a dependency, not a parameter: if it ever leaked into the input
        schema, a model would try to invent one."""
        tools = _named(await mcp_client.list_tools())

        assert set(tools) == {"whoami", "list_chats"}
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

    async def test_both_tools_declare_their_result_shape(
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
        message = "\n".join(
            block.text for block in result.content if isinstance(block, TextContent)
        )
        assert "Chat.Read" in message
        assert "administrator" in message
        assert "synthetic-request-id" in message
        assert obo.requested_scopes, "the failure came from Graph, not from the token exchange"
