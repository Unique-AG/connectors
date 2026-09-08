"""The send gate driven by a real MCP client, over the connection an in-process one negotiates.

Every other test builds its own confirmation, so nothing else exercises the client's driver or the
second round trip a 2026-07-28 connection needs.

Every payload here is synthesised. No message in this file was ever sent from a real mailbox.
"""

from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from azure.core.credentials import AccessToken as GraphAccessToken
from fastmcp import Client, FastMCP
from fastmcp.client.elicitation import ElicitRequestParams, ElicitResult
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.dependencies import AccessToken
from mcp.types import (
    CallToolResult,
    ElicitRequest,
    ElicitRequestFormParams,
    InputRequest,
    InputRequiredResult,
    TextContent,
)

# The wire type a client carries an answer back in, which is not the fastmcp handler's own.
from mcp.types import ElicitResult as CarriedAnswer
from mcp.types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION
from respx.models import Call
from starlette.applications import Starlette

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_365_mcp.tools import outlook_send_draft as sender

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"
_CLIENT_TOKEN = "synthetic-fastmcp-session-token"
_OBO_TOKEN = "synthetic-obo-graph-token"

# The id in the tool's own `GRAPH_CALL_EXAMPLE`. Handles carry it percent-encoded and the SDK
# re-encodes it, so the payload holds the plain id and the route the encoded one.
_DRAFT_ID = "AAMkAGI2SYNTHETIC-draft-0001="

_DRAFT_PATH = "/me/messages/AAMkAGI2SYNTHETIC-draft-0001%3D"
_SEND_PATH = f"{_DRAFT_PATH}/send"

# respx unquotes what the SDK encoded, so a recorded call carries the plain id back.
_SEND_ROUTE = f"/v1.0/me/messages/{_DRAFT_ID}/send"

_ADA = "ada@example.invalid"
_PAM = "pam@example.invalid"

_SUBJECT = "Invoice 4471"

_ME = {
    "id": "00000000-0000-4000-8000-000000000001",
    "displayName": "Ada Lovelace",
    "mail": _ADA,
    "userPrincipalName": "ada@corp.example.invalid",
}

_DRAFT: Mapping[str, object] = {
    "id": _DRAFT_ID,
    "isDraft": True,
    "subject": _SUBJECT,
    "toRecipients": [{"emailAddress": {"name": "Ada Lovelace", "address": _ADA}}],
    "ccRecipients": [{"emailAddress": {"name": "Pam Beesly", "address": _PAM}}],
}


class _StubOboCredential:
    """Stub for azure.identity.aio.OnBehalfOfCredential."""

    async def get_token(self, *scopes: str) -> GraphAccessToken:
        _ = scopes
        return GraphAccessToken(token=_OBO_TOKEN, expires_on=0)


@pytest.fixture
def obo(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed exchange answers every call with the token advice, before any route is reached."""
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
    """A refused send answers 202 the same way, so counting POSTs is what tells the two apart."""
    with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as router:
        _ = router.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        _ = router.get(_DRAFT_PATH).mock(return_value=httpx.Response(200, json=dict(_DRAFT)))
        _ = router.post(_SEND_PATH).mock(return_value=httpx.Response(202))
        yield router


def _made(router: respx.MockRouter) -> Sequence[Call]:
    """respx types one call and leaves the list unknown, so the cast lives here, not per index."""
    return cast("Sequence[Call]", router.calls)


def _posts(router: respx.MockRouter) -> list[str]:
    return [call.request.url.path for call in _made(router) if call.request.method == "POST"]


def _object(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value)


def _the_word_for_yes(asked: InputRequest) -> str:
    """Read off the question the call minted, so round two cannot agree by coincidence."""
    assert isinstance(asked, ElicitRequest), "the question is not one a person answers"
    params = asked.params
    assert isinstance(params, ElicitRequestFormParams), "the question is not one a client can fill"
    choices = _object(_object(_object(params.requested_schema)["properties"])["value"])["enum"]
    return cast("Sequence[str]", choices)[0]


async def _agree(
    _message: str,
    _response_type: type | None,
    _params: ElicitRequestParams,
    _context: object,
) -> str:
    return sender.SEND


async def _decline(
    _message: str,
    _response_type: type | None,
    _params: ElicitRequestParams,
    _context: object,
) -> ElicitResult[str]:
    return ElicitResult(action="decline")


@pytest.fixture
def app() -> Starlette:
    """The `outlook-send` preset, composed rather than registered by hand: `EntraOBOToken`
    resolves against the server's own auth provider, and a bare `FastMCP` has none."""
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
        surface_config=SurfaceConfig.model_validate({"tools_preset": ToolsPreset.OUTLOOK_SEND}),
    )


@pytest.fixture
async def an_agreeing_client(app: Starlette) -> AsyncIterator[Client[FastMCPTransport]]:
    """No `mode`, deliberately: this negotiates the in-process default."""
    server = cast("FastMCP[None]", app.state.fastmcp_server)
    async with Client(FastMCPTransport(server), elicitation_handler=_agree) as client:
        yield client


@pytest.fixture
async def a_declining_client(app: Starlette) -> AsyncIterator[Client[FastMCPTransport]]:
    server = cast("FastMCP[None]", app.state.fastmcp_server)
    async with Client(FastMCPTransport(server), elicitation_handler=_decline) as client:
        yield client


@pytest.mark.usefixtures("obo")
class TestTheWholeConfirmationOverARealClient:
    async def test_an_agreed_send_puts_the_mail_on_the_wire_exactly_once(
        self, an_agreeing_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        """Regression: `ctx.elicit` raises on this era, which the tool read as a person
        saying no."""
        assert an_agreeing_client.protocol_version == LATEST_MODERN_VERSION, (
            "this file's whole point is a connection whose era has no back-channel"
        )

        result = await an_agreeing_client.call_tool(
            sender.TOOL_NAME, dict(sender.GRAPH_CALL_EXAMPLE)
        )

        answer = cast("Mapping[str, object] | None", result.structured_content)
        assert answer is not None, "the confirmed send answered nothing"
        assert set(sender.MailSent.model_fields) <= set(answer), (
            f"the answer is not the record of what left the mailbox: {sorted(answer)}"
        )
        assert answer["subject"] == _SUBJECT
        assert _posts(graph) == [_SEND_ROUTE], f"an agreed send posted {_posts(graph)}"

    async def test_a_person_who_says_no_leaves_the_draft_where_it_is(
        self, a_declining_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="did not agree"):
            _ = await a_declining_client.call_tool(
                sender.TOOL_NAME, dict(sender.GRAPH_CALL_EXAMPLE)
            )

        assert _posts(graph) == [], f"a declined send posted {_posts(graph)}"
        assert len(_made(graph)) > 0, "the question was asked about a draft nothing ever read"

    async def test_an_accept_that_omits_the_request_state_sends_nothing(
        self, an_agreeing_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        """Driven over the session, not the client: the client's own driver echoes the state back,
        and this is the retry that does not."""
        first = await an_agreeing_client.session.call_tool(
            sender.TOOL_NAME, dict(sender.GRAPH_CALL_EXAMPLE), allow_input_required=True
        )

        assert isinstance(first, InputRequiredResult), "the question was never put to anybody"
        requests = first.input_requests or {}
        (key,) = requests
        agrees = _the_word_for_yes(requests[key])

        second = await an_agreeing_client.session.call_tool(
            sender.TOOL_NAME,
            dict(sender.GRAPH_CALL_EXAMPLE),
            input_responses={key: CarriedAnswer(action="accept", content={"value": agrees})},
            allow_input_required=True,
        )

        assert isinstance(second, CallToolResult), "the unbound retry asked again instead"
        assert second.is_error, "an accept bound to nothing was read as agreement"
        refusal = " ".join(block.text for block in second.content if isinstance(block, TextContent))

        assert "given for a different request" in refusal, refusal
        assert _posts(graph) == [], f"an accept nothing was bound to posted {_posts(graph)}"

    async def test_a_client_pinned_to_the_handshake_era_still_asks_and_sends(
        self, app: Starlette, graph: respx.MockRouter
    ) -> None:
        """The only pinned connection here: `mode="legacy"` negotiates the handshake era, where
        one call carries the whole confirmation."""
        server = cast("FastMCP[None]", app.state.fastmcp_server)

        async with Client(
            FastMCPTransport(server), mode="legacy", elicitation_handler=_agree
        ) as client:
            assert client.protocol_version == LATEST_HANDSHAKE_VERSION, (
                "this pin no longer reaches the era it exists to cover"
            )
            result = await client.call_tool(sender.TOOL_NAME, dict(sender.GRAPH_CALL_EXAMPLE))

        assert result.structured_content is not None, "the confirmed send answered nothing"
        assert _posts(graph) == [_SEND_ROUTE], f"a handshake-era send posted {_posts(graph)}"
