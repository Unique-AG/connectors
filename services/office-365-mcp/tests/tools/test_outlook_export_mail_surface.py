"""The export driven by a real MCP client, over the connection an in-process one negotiates.

This is the only tool in this connector whose answer is not a JSON object, and the unit tests
cannot see the part that matters: `EmlFile` is a FastMCP helper, not protocol content, and what a
client receives is whatever the framework turns it into. FastMCP renders bytes it is handed
directly as a bare base64 string with no type and no name on it, so "the tool returned the right
object" and "the caller received a mail file" are two different claims. This file asserts the
second.

Every byte here is synthesised. No message in this file came from a real mailbox.
"""

import base64
from collections.abc import AsyncIterator, Iterator
from typing import cast

import httpx
import pytest
import respx
from azure.core.credentials import AccessToken as GraphAccessToken
from fastmcp import Client, FastMCP
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.dependencies import AccessToken
from mcp.types import BlobResourceContents, EmbeddedResource
from starlette.applications import Starlette

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_365_mcp.shared.handles import MailFolderHandle
from office_365_mcp.tools import outlook_export_mail as exporter

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"
_CLIENT_TOKEN = "synthetic-fastmcp-session-token"
_OBO_TOKEN = "synthetic-obo-graph-token"

_PATH = "/me/messages/AAMkAGI2SYNTHETIC-immutable-0001%3D/$value"

_MIME = (
    b"Received: from mail.vance.invalid (10.0.0.1) by outlook.invalid\r\n"
    + b"From: Bob Vance <bob@vance.invalid>\r\n"
    + b"Subject: Invoice 4471\r\n"
    + b'Content-Type: multipart/mixed; boundary="synthetic"\r\n'
    + b"\r\n"
    + b"--synthetic\r\n"
    + b"Content-Type: text/plain\r\n"
    + b"\r\n"
    + b"The invoice never arrived.\r\n"
    + b"--synthetic\r\n"
    + b"Content-Type: application/pdf\r\n"
    + b"Content-Transfer-Encoding: base64\r\n"
    + b"\r\n"
    + b"JVBERi0xLjQK\r\n"
    + b"--synthetic--\r\n"
)


class _StubOboCredential:
    """Stub for azure.identity.aio.OnBehalfOfCredential."""

    async def get_token(self, *scopes: str) -> GraphAccessToken:
        _ = scopes
        return GraphAccessToken(token=_OBO_TOKEN, expires_on=0)


@pytest.fixture
def obo(monkeypatch: pytest.MonkeyPatch) -> None:
    credential = _StubOboCredential()

    async def get_obo_credential(
        _self: AzureProvider, *, user_assertion: str
    ) -> _StubOboCredential:
        assert user_assertion == _CLIENT_TOKEN, "the client's own token is what gets exchanged"
        return credential

    monkeypatch.setattr(AzureProvider, "get_obo_credential", get_obo_credential)
    monkeypatch.setattr(
        "fastmcp.server.dependencies.get_access_token",
        lambda: AccessToken(token=_CLIENT_TOKEN, client_id=_CLIENT_ID, scopes=["access_as_user"]),
    )


@pytest.fixture
def graph() -> Iterator[respx.MockRouter]:
    with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as router:
        _ = router.get(_PATH).mock(
            return_value=httpx.Response(
                200, content=_MIME, headers={"Content-Type": "application/octet-stream"}
            )
        )
        yield router


@pytest.fixture
def app() -> Starlette:
    """The `outlook-read` preset, composed rather than registered by hand: `EntraOBOToken` resolves
    against the server's own auth provider, and a bare `FastMCP` has none."""
    return create_app(
        config=AppConfig.model_validate({"public_base_url": "https://office-365-mcp.example"}),
        database_config=DatabaseConfig.model_validate(
            {"url": "postgresql://user:pass@127.0.0.1:1/nope"}
        ),
        entra_config=EntraConfig.model_validate(
            {
                "tenant_id": "8a9c3c47-0f9e-4a24-9b1e-2f0d5c6b7a81",
                "client_id": _CLIENT_ID,
                "client_secret": "s3cr3t",
            }
        ),
        surface_config=SurfaceConfig.model_validate({"tools_preset": ToolsPreset.OUTLOOK_READ}),
    )


@pytest.fixture
async def reader(app: Starlette) -> AsyncIterator[Client[FastMCPTransport]]:
    server = cast("FastMCP[None]", app.state.fastmcp_server)
    async with Client(FastMCPTransport(server)) as client:
        yield client


def _one_resource(answer: CallToolResult) -> BlobResourceContents:
    content = answer.content
    assert len(content) == 1, f"an export is one file, and this is {content!r}"
    block = content[0]
    assert isinstance(block, EmbeddedResource), f"a file did not survive the protocol: {block!r}"
    resource = block.resource
    assert isinstance(resource, BlobResourceContents), (
        f"MIME arrived as text rather than as bytes: {resource!r}"
    )
    return resource


@pytest.mark.usefixtures("obo")
class TestTheExportOverARealClient:
    async def test_the_caller_receives_the_mime_byte_for_byte(
        self, reader: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        answer = await reader.call_tool(exporter.TOOL_NAME, dict(exporter.GRAPH_CALL_EXAMPLE))

        assert base64.b64decode(_one_resource(answer).blob) == _MIME
        assert graph.calls.call_count == 1

    async def test_the_attachment_arrives_inside_it(
        self, reader: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        """The one thing this tool does that no other tool here does. If the parts were dropped
        anywhere between Graph and the client, the file would still open and be wrong."""
        _ = graph

        answer = await reader.call_tool(exporter.TOOL_NAME, dict(exporter.GRAPH_CALL_EXAMPLE))

        assert b"Content-Type: application/pdf" in base64.b64decode(_one_resource(answer).blob)

    async def test_it_arrives_as_a_mail_file_with_a_name(
        self, reader: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        """A client saves what the resource says it is. `application/octet-stream` with no name is
        a download nobody can open."""
        _ = graph

        answer = await reader.call_tool(exporter.TOOL_NAME, dict(exporter.GRAPH_CALL_EXAMPLE))

        resource = _one_resource(answer)
        assert resource.mime_type == "message/rfc822"
        assert str(resource.uri) == "file:///Invoice%204471.eml"

    async def test_it_carries_no_structured_answer_to_disagree_with_the_file(
        self, reader: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        """The file is the whole answer. A second copy of the message as fields would be a second
        thing to keep true."""
        _ = graph

        answer = await reader.call_tool(exporter.TOOL_NAME, dict(exporter.GRAPH_CALL_EXAMPLE))

        assert answer.structured_content is None

    async def test_a_handle_for_something_that_is_not_a_message_never_reaches_graph(
        self, reader: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError) as refusal:
            _ = await reader.call_tool(
                exporter.TOOL_NAME, {"uri": MailFolderHandle("AQMkAD-1").uri}
            )

        assert "outlook_search_mail" in str(refusal.value)
        assert graph.calls.call_count == 0
