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
from mcp.types import ElicitResult as CarriedAnswer
from mcp.types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION
from respx.models import Call
from starlette.applications import Starlette

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_365_mcp.tools import outlook_set_automatic_reply as automatic_reply

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"
_CLIENT_TOKEN = "synthetic-fastmcp-session-token"
_OBO_TOKEN = "synthetic-obo-graph-token"

_SETTINGS_PATH = "/me/mailboxSettings"

_TURN_ON = "turn on"

_ME = {
    "id": "00000000-0000-4000-8000-000000000001",
    "displayName": "Ada Lovelace",
    "mail": "ada@example.invalid",
    "userPrincipalName": "ada@corp.example.invalid",
}

_SETTING: Mapping[str, object] = {
    "status": "disabled",
    "externalAudience": "contactsOnly",
    "internalReplyMessage": "<p>Back on the 14th.</p>",
    "externalReplyMessage": "<p>Away until the 14th.</p>",
    "scheduledStartDateTime": {"dateTime": "2026-03-20T18:00:00.0000000", "timeZone": "UTC"},
    "scheduledEndDateTime": {"dateTime": "2026-03-28T18:00:00.0000000", "timeZone": "UTC"},
}

_TURN_ON_ARGUMENTS: Mapping[str, object] = {
    "status": "scheduled",
    "start": "2026-09-01T08:00:00",
    "end": "2026-09-14T18:00:00",
}


class _StubOboCredential:
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
    body = {"automaticRepliesSetting": dict(_SETTING)}
    with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as router:
        _ = router.get("/me").mock(return_value=httpx.Response(200, json=_ME))
        _ = router.get(_SETTINGS_PATH).mock(return_value=httpx.Response(200, json=body))
        _ = router.patch(_SETTINGS_PATH).mock(return_value=httpx.Response(200, json=body))
        yield router


def _made(router: respx.MockRouter) -> Sequence[Call]:
    return cast("Sequence[Call]", router.calls)


def _patches(router: respx.MockRouter) -> list[str]:
    return [call.request.url.path for call in _made(router) if call.request.method == "PATCH"]


def _object(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value)


def _the_word_for_yes(asked: InputRequest) -> str:
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
    return _TURN_ON


async def _decline(
    _message: str,
    _response_type: type | None,
    _params: ElicitRequestParams,
    _context: object,
) -> ElicitResult[str]:
    return ElicitResult(action="decline")


@pytest.fixture
def app() -> Starlette:
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
        surface_config=SurfaceConfig.model_validate({"tools_preset": ToolsPreset.OUTLOOK_AUTOMATE}),
    )


@pytest.fixture
async def an_agreeing_client(app: Starlette) -> AsyncIterator[Client[FastMCPTransport]]:
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
    async def test_an_agreed_reply_is_written_exactly_once(
        self, an_agreeing_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        assert an_agreeing_client.protocol_version == LATEST_MODERN_VERSION

        result = await an_agreeing_client.call_tool(
            automatic_reply.TOOL_NAME, dict(_TURN_ON_ARGUMENTS)
        )

        assert result.structured_content is not None, "the agreed reply answered nothing"
        assert _patches(graph) == [f"/v1.0{_SETTINGS_PATH}"], (
            f"an agreed reply wrote {_patches(graph)}"
        )

    async def test_a_person_who_says_no_leaves_the_mailbox_alone(
        self, a_declining_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        with pytest.raises(ToolError, match="did not agree"):
            _ = await a_declining_client.call_tool(
                automatic_reply.TOOL_NAME, dict(_TURN_ON_ARGUMENTS)
            )

        assert _patches(graph) == [], f"a declined reply wrote {_patches(graph)}"

    async def test_turning_the_reply_off_asks_nobody_and_writes(
        self, a_declining_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        result = await a_declining_client.call_tool(
            automatic_reply.TOOL_NAME, {"status": "disabled"}
        )

        assert result.structured_content is not None
        assert len(_patches(graph)) == 1, "turning the reply off was held back by a question"

    async def test_an_accept_that_omits_the_request_state_writes_nothing(
        self, an_agreeing_client: Client[FastMCPTransport], graph: respx.MockRouter
    ) -> None:
        first = await an_agreeing_client.session.call_tool(
            automatic_reply.TOOL_NAME, dict(_TURN_ON_ARGUMENTS), allow_input_required=True
        )

        assert isinstance(first, InputRequiredResult), "the question was never put to anybody"
        requests = first.input_requests or {}
        (key,) = requests
        agrees = _the_word_for_yes(requests[key])

        second = await an_agreeing_client.session.call_tool(
            automatic_reply.TOOL_NAME,
            dict(_TURN_ON_ARGUMENTS),
            input_responses={key: CarriedAnswer(action="accept", content={"value": agrees})},
            allow_input_required=True,
        )

        assert isinstance(second, CallToolResult), "the unbound retry asked again instead"
        assert second.is_error, "an accept bound to nothing was read as agreement"
        refusal = " ".join(block.text for block in second.content if isinstance(block, TextContent))

        assert "given for a different request" in refusal, refusal
        assert _patches(graph) == [], f"an accept nothing was bound to wrote {_patches(graph)}"

    async def test_a_client_pinned_to_the_handshake_era_still_asks_and_writes(
        self, app: Starlette, graph: respx.MockRouter
    ) -> None:
        server = cast("FastMCP[None]", app.state.fastmcp_server)

        async with Client(
            FastMCPTransport(server), mode="legacy", elicitation_handler=_agree
        ) as client:
            assert client.protocol_version == LATEST_HANDSHAKE_VERSION
            result = await client.call_tool(automatic_reply.TOOL_NAME, dict(_TURN_ON_ARGUMENTS))

        assert result.structured_content is not None, "the agreed reply answered nothing"
        assert len(_patches(graph)) == 1, f"a handshake-era reply wrote {_patches(graph)}"
