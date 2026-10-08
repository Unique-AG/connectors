import json
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
from office_365_mcp.shared.handles import MailMessageHandle
from office_365_mcp.tools import outlook_draft_mail, outlook_draft_reply

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"
_CLIENT_TOKEN = "synthetic-fastmcp-session-token"
_OBO_TOKEN = "synthetic-obo-graph-token"

_CREATE = "create the draft"

_SHARED_MAILBOX = "alex@example.invalid"

_MESSAGE_ID = "AAMkAGI2SYNTHETIC-immutable-0001="
_MESSAGE_PATH = "messages/AAMkAGI2SYNTHETIC-immutable-0001%3D"
_DRAFT_PATH = "messages/AAMkAGI2SYNTHETIC-reply-draft-0001%3D"

_DRAFT: Mapping[str, object] = {
    "id": "AAMkAGI2SYNTHETIC-reply-draft-0001=",
    "isDraft": True,
    "subject": "Invoice 4471",
    "toRecipients": [{"emailAddress": {"name": "Ada Lovelace", "address": "ada@example.invalid"}}],
    "ccRecipients": [],
    "body": {"contentType": "html", "content": "Friday works."},
    "webLink": "https://outlook.office365.invalid/owa/?ItemID=synthetic-draft",
}

_ORIGINAL: Mapping[str, object] = {
    "id": _MESSAGE_ID,
    "subject": "Invoice 4471",
    "from": {"emailAddress": {"name": "Ada Lovelace", "address": "ada@example.invalid"}},
    "replyTo": [],
}

_MAIL_ARGUMENTS: Mapping[str, object] = {
    "to": ["ada@example.invalid"],
    "subject": "Invoice 4471",
    "body_html": "Sending this over for review.",
}

_REPLY_ARGUMENTS: Mapping[str, object] = {
    "message_ref": MailMessageHandle(_MESSAGE_ID).uri,
    "mode": "reply",
    "body_html": "Friday works.",
}

_COPIED_AND_MARKED: Mapping[str, object] = {
    "cc": ["pam@example.invalid"],
    "importance": "high",
    "categories": ["Finance"],
}

_EACH_TOOL = pytest.mark.parametrize(
    ("tool", "arguments", "methods"),
    [
        pytest.param(
            outlook_draft_mail.TOOL_NAME, _MAIL_ARGUMENTS, ["POST"], id="outlook_draft_mail"
        ),
        pytest.param(
            outlook_draft_reply.TOOL_NAME,
            _REPLY_ARGUMENTS,
            ["POST", "PATCH"],
            id="outlook_draft_reply",
        ),
    ],
)


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
    with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as router:
        for mailbox in ("me", f"users/{_SHARED_MAILBOX}"):
            _ = router.post(f"/{mailbox}/messages").mock(
                return_value=httpx.Response(201, json=_DRAFT)
            )
            _ = router.post(f"/{mailbox}/{_MESSAGE_PATH}/createReply").mock(
                return_value=httpx.Response(201, json=_DRAFT)
            )
            _ = router.patch(f"/{mailbox}/{_DRAFT_PATH}").mock(
                return_value=httpx.Response(200, json=_DRAFT)
            )
            _ = router.get(f"/{mailbox}/{_MESSAGE_PATH}").mock(
                return_value=httpx.Response(200, json=_ORIGINAL)
            )
        yield router


def _made(router: respx.MockRouter) -> Sequence[Call]:
    return cast("Sequence[Call]", router.calls)


def _writes(router: respx.MockRouter) -> list[str]:
    return [call.request.method for call in _made(router) if call.request.method != "GET"]


def _body_of(call: Call) -> Mapping[str, object]:
    return cast("Mapping[str, object]", json.loads(call.request.content))


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
    return _CREATE


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
        surface_config=SurfaceConfig.model_validate({"tools_preset": ToolsPreset.OUTLOOK_WRITE}),
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
    @_EACH_TOOL
    async def test_an_agreed_draft_in_a_shared_mailbox_is_written_exactly_once(
        self,
        an_agreeing_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        tool: str,
        arguments: Mapping[str, object],
        methods: list[str],
    ) -> None:
        assert an_agreeing_client.protocol_version == LATEST_MODERN_VERSION

        result = await an_agreeing_client.call_tool(tool, {**arguments, "mailbox": _SHARED_MAILBOX})

        assert result.structured_content is not None, "the agreed draft answered nothing"
        assert _writes(graph) == methods, f"an agreed draft wrote {_writes(graph)}"

    @_EACH_TOOL
    async def test_a_person_who_says_no_leaves_the_shared_mailbox_alone(
        self,
        a_declining_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        tool: str,
        arguments: Mapping[str, object],
        methods: list[str],
    ) -> None:
        _ = methods

        with pytest.raises(ToolError, match="did not agree"):
            _ = await a_declining_client.call_tool(tool, {**arguments, "mailbox": _SHARED_MAILBOX})

        assert _writes(graph) == [], f"a declined draft wrote {_writes(graph)}"

    @_EACH_TOOL
    async def test_the_signed_in_users_own_mailbox_asks_nobody_and_writes(
        self,
        a_declining_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        tool: str,
        arguments: Mapping[str, object],
        methods: list[str],
    ) -> None:
        result = await a_declining_client.call_tool(tool, dict(arguments))

        assert result.structured_content is not None
        assert _writes(graph) == methods, "a draft in the own mailbox was held back by a question"

    @_EACH_TOOL
    async def test_an_accept_that_omits_the_request_state_writes_nothing(
        self,
        an_agreeing_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        tool: str,
        arguments: Mapping[str, object],
        methods: list[str],
    ) -> None:
        _ = methods
        asked_with = {**arguments, "mailbox": _SHARED_MAILBOX}

        first = await an_agreeing_client.session.call_tool(
            tool, asked_with, allow_input_required=True
        )

        assert isinstance(first, InputRequiredResult), "the question was never put to anybody"
        requests = first.input_requests or {}
        (key,) = requests
        agrees = _the_word_for_yes(requests[key])

        second = await an_agreeing_client.session.call_tool(
            tool,
            asked_with,
            input_responses={key: CarriedAnswer(action="accept", content={"value": agrees})},
            allow_input_required=True,
        )

        assert isinstance(second, CallToolResult), "the unbound retry asked again instead"
        assert second.is_error, "an accept bound to nothing was read as agreement"
        refusal = " ".join(block.text for block in second.content if isinstance(block, TextContent))

        assert "given for a different request" in refusal, refusal
        assert _writes(graph) == [], f"an accept nothing was bound to wrote {_writes(graph)}"

    @_EACH_TOOL
    async def test_a_client_pinned_to_the_handshake_era_still_asks_and_writes(
        self,
        app: Starlette,
        graph: respx.MockRouter,
        tool: str,
        arguments: Mapping[str, object],
        methods: list[str],
    ) -> None:
        server = cast("FastMCP[None]", app.state.fastmcp_server)

        async with Client(
            FastMCPTransport(server), mode="legacy", elicitation_handler=_agree
        ) as client:
            assert client.protocol_version == LATEST_HANDSHAKE_VERSION
            result = await client.call_tool(tool, {**arguments, "mailbox": _SHARED_MAILBOX})

        assert result.structured_content is not None, "the agreed draft answered nothing"
        assert _writes(graph) == methods, f"a handshake-era draft wrote {_writes(graph)}"

    @_EACH_TOOL
    async def test_an_agreed_draft_writes_its_copy_importance_and_categories_in_one_request(
        self,
        an_agreeing_client: Client[FastMCPTransport],
        graph: respx.MockRouter,
        tool: str,
        arguments: Mapping[str, object],
        methods: list[str],
    ) -> None:
        result = await an_agreeing_client.call_tool(
            tool, {**arguments, **_COPIED_AND_MARKED, "mailbox": _SHARED_MAILBOX}
        )

        assert result.structured_content is not None, "the agreed draft answered nothing"
        carrying = [
            call for call in _made(graph) if "ccRecipients" in call.request.content.decode()
        ]
        (write,) = carrying
        assert write.request.method == methods[-1]
        sent = _body_of(write)
        copied = cast("Sequence[Mapping[str, Mapping[str, object]]]", sent["ccRecipients"])
        assert [one["emailAddress"]["address"] for one in copied] == ["pam@example.invalid"]
        assert sent["importance"] == "high"
        assert sent["categories"] == ["Finance"]
