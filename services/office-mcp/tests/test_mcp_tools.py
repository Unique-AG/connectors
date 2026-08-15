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


def _structured(result: CallToolResult) -> dict[str, object]:
    data = cast("dict[str, object] | None", result.structured_content)
    assert data is not None, "the tool returned no structured content"
    return data


def _error_text(result: CallToolResult) -> str:
    """Everything the model would read of a failed call."""
    return "\n".join(block.text for block in result.content if isinstance(block, TextContent))


class TestTheToolsThisServerAdvertises:
    async def test_every_tool_is_listed_and_none_asks_for_a_token(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The Graph token is a dependency, not a parameter: if it ever leaked into the input
        schema, a model would try to invent one."""
        tools = _named(await mcp_client.list_tools())

        assert set(tools) == {"get_me"}
        for tool in tools.values():
            assert "graph_token" not in _properties(tool.inputSchema)

    async def test_get_me_takes_no_arguments(self, mcp_client: Client[FastMCPTransport]) -> None:
        tools = _named(await mcp_client.list_tools())

        assert _properties(tools["get_me"].inputSchema) == {}
        assert tools["get_me"].inputSchema.get("required", []) == []

    async def test_every_tool_declares_its_result_shape(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """The oracle connector returns an unschematised stream of objects whose last element may
        be pagination metadata. A declared output schema is how a `next_offset` or a
        `members_may_be_incomplete` stops being prose."""
        tools = _named(await mcp_client.list_tools())

        assert set(_properties(tools["get_me"].outputSchema)) == {
            "user_id",
            "display_name",
            "email",
            "user_principal_name",
            "job_title",
        }

    async def test_the_whole_surface_speaks_one_language(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """These tools arrive one at a time and are read all at once, by a model choosing between
        them. So the conventions are asserted from the first one rather than merely written down: a
        name is verb_noun (which is why this tool is `get_me` and not the shell idiom `whoami`), a
        result field is snake_case, and no answer carries a "there is more" flag of its own.

        That last one is a convention a single-object answer cannot break, and it is asserted here
        anyway, because the tool that breaks it is the first list-shaped one and by then the word is
        already on the surface. A window filled to `limit` says there may be more and a short one
        says there is not; `next_offset` says it outright where paging exists; and `truncated` on
        top of either means "raise `limit`" or "nothing will help" with no way to tell which.
        """
        tools = _named(await mcp_client.list_tools())

        for name in tools:
            assert re.fullmatch(r"[a-z]+(_[a-z]+)+", name), f"{name} is not verb_noun"
        for tool in tools.values():
            for field in _properties(tool.outputSchema):
                assert re.fullmatch(r"[a-z][a-z0-9]*(_[a-z0-9]+)*", field), f"{field} is not snake"
        for name, tool in tools.items():
            assert "truncated" not in _properties(tool.outputSchema), name

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

    async def test_an_argument_this_tool_does_not_have_is_refused(
        self,
        mcp_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        obo: _StubOboCredential,
    ) -> None:
        """A misremembered parameter — `user_id`, say, which this tool deliberately does not take,
        because the whole of what it answers is who the caller already is — must fail rather than
        be ignored, or the model believes it asked about somebody else and reads the answer as
        being about them.
        """
        route = graph.get("/me").mock(return_value=httpx.Response(200, json=_ME))

        result = await mcp_client.call_tool(
            "get_me", {"user_id": "00000000-0000-4000-8000-000000000002"}, raise_on_error=False
        )

        assert result.is_error
        assert not route.called
        assert not obo.requested_scopes, "no token is exchanged for a call that cannot run"


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
        "Failed to resolve dependency 'graph_token' for get_me", which names neither the permission
        nor anyone who could grant it. Whatever else changes, this end of the wire has to stay as
        actionable as the 403 above.
        """
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
        assert not route.called, "no token means no Graph request was ever made"
