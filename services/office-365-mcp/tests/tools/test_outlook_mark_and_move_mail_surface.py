from collections.abc import AsyncGenerator, Iterator, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal, cast, final

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
from mcp.types import CallToolResult, InputRequiredResult, TextContent
from mcp.types import ElicitResult as CarriedAnswer
from mcp.types.version import LATEST_HANDSHAKE_VERSION, LATEST_MODERN_VERSION
from starlette.applications import Starlette

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_365_mcp.shared.handles import MailMessageHandle
from office_365_mcp.tools import outlook_mark_mail as mark
from office_365_mcp.tools import outlook_move_mail as move

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"
_CLIENT_TOKEN = "synthetic-fastmcp-session-token"
_OBO_TOKEN = "synthetic-obo-graph-token"

_MAILBOX = "alex@example.invalid"

_REFS: Sequence[str] = (
    MailMessageHandle("AAMkAGI2SYNTHETIC-immutable-0001=").uri,
    MailMessageHandle("AAMkAGI2SYNTHETIC-immutable-0002=").uri,
)

_UPDATED = {"id": "AAMkAGI2SYNTHETIC-immutable-0001=", "isRead": True}

_MOVED = {"id": "AAMkAGI2SYNTHETIC-immutable-0001-moved=", "parentFolderId": "archive"}


@dataclass(frozen=True, slots=True)
class _Tool:
    name: str
    arguments: Mapping[str, object]
    agree: str
    write: Literal["PATCH", "POST"]


_MARK = _Tool(mark.TOOL_NAME, {"is_read": True}, "change", "PATCH")
_MOVE = _Tool(move.TOOL_NAME, {"destination": "archive"}, "move", "POST")

_EITHER_TOOL = pytest.mark.parametrize(
    "tool", [pytest.param(_MARK, id="mark"), pytest.param(_MOVE, id="move")]
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
        _ = router.route(method="PATCH").mock(return_value=httpx.Response(200, json=_UPDATED))
        _ = router.route(method="POST").mock(return_value=httpx.Response(201, json=_MOVED))
        yield router


def _writes(router: respx.MockRouter, tool: _Tool) -> list[str]:
    calls = cast("Sequence[respx.models.Call]", router.calls)
    return [call.request.url.path for call in calls if call.request.method == tool.write]


@final
class _Person:
    def __init__(self, *, agrees: bool, word: str) -> None:
        self.questions: list[str] = []
        self._agrees = agrees
        self._word = word

    async def answer(
        self,
        message: str,
        _response_type: type | None,
        _params: ElicitRequestParams,
        _context: object,
    ) -> str | ElicitResult[str]:
        self.questions.append(message)
        return self._word if self._agrees else ElicitResult(action="decline")


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


@asynccontextmanager
async def _connected(
    app: Starlette, person: _Person, *, mode: Literal["auto", "legacy"] = "auto"
) -> AsyncGenerator[Client[FastMCPTransport]]:
    server = cast("FastMCP[None]", app.state.fastmcp_server)
    async with Client(
        FastMCPTransport(server), mode=mode, elicitation_handler=person.answer
    ) as client:
        yield client


def _arguments(tool: _Tool, *, mailbox: str | None) -> dict[str, object]:
    named: dict[str, object] = {"message_refs": list(_REFS), **tool.arguments}
    if mailbox is not None:
        named["mailbox"] = mailbox
    return named


@pytest.mark.usefixtures("obo")
class TestTheWholeConfirmationOverARealClient:
    @_EITHER_TOOL
    async def test_an_agreed_change_to_another_mailbox_writes_each_message_after_one_question(
        self, app: Starlette, graph: respx.MockRouter, tool: _Tool
    ) -> None:
        person = _Person(agrees=True, word=tool.agree)

        async with _connected(app, person) as client:
            assert client.protocol_version == LATEST_MODERN_VERSION
            result = await client.call_tool(tool.name, _arguments(tool, mailbox=_MAILBOX))

        assert result.structured_content is not None, "the agreed change answered nothing"
        assert len(person.questions) == 1, f"the person was asked {person.questions}"
        written = _writes(graph, tool)
        assert len(written) == len(_REFS), f"an agreed change wrote {written}"
        assert all(f"/users/{_MAILBOX}/messages/" in path for path in written), written

    @_EITHER_TOOL
    async def test_a_person_who_says_no_leaves_the_other_mailbox_alone(
        self, app: Starlette, graph: respx.MockRouter, tool: _Tool
    ) -> None:
        person = _Person(agrees=False, word=tool.agree)

        async with _connected(app, person) as client:
            with pytest.raises(ToolError, match="did not agree"):
                _ = await client.call_tool(tool.name, _arguments(tool, mailbox=_MAILBOX))

        assert len(person.questions) == 1
        assert _writes(graph, tool) == [], f"a declined change wrote {_writes(graph, tool)}"

    @_EITHER_TOOL
    async def test_the_own_mailbox_asks_nobody_and_writes(
        self, app: Starlette, graph: respx.MockRouter, tool: _Tool
    ) -> None:
        person = _Person(agrees=False, word=tool.agree)

        async with _connected(app, person) as client:
            result = await client.call_tool(tool.name, _arguments(tool, mailbox=None))

        assert result.structured_content is not None
        assert person.questions == [], f"the own mailbox asked {person.questions}"
        assert len(_writes(graph, tool)) == len(_REFS), (
            "the own mailbox was held back by a question"
        )

    @_EITHER_TOOL
    async def test_a_client_pinned_to_the_handshake_era_still_asks_and_writes(
        self, app: Starlette, graph: respx.MockRouter, tool: _Tool
    ) -> None:
        person = _Person(agrees=True, word=tool.agree)

        async with _connected(app, person, mode="legacy") as client:
            assert client.protocol_version == LATEST_HANDSHAKE_VERSION
            result = await client.call_tool(tool.name, _arguments(tool, mailbox=_MAILBOX))

        assert result.structured_content is not None, "the agreed change answered nothing"
        assert len(person.questions) == 1, f"the person was asked {person.questions}"
        assert len(_writes(graph, tool)) == len(_REFS), "a handshake-era change wrote too few"

    @_EITHER_TOOL
    async def test_a_handshake_era_refusal_writes_nothing(
        self, app: Starlette, graph: respx.MockRouter, tool: _Tool
    ) -> None:
        person = _Person(agrees=False, word=tool.agree)

        async with _connected(app, person, mode="legacy") as client:
            with pytest.raises(ToolError, match="did not agree"):
                _ = await client.call_tool(tool.name, _arguments(tool, mailbox=_MAILBOX))

        assert _writes(graph, tool) == []

    async def test_a_deletion_from_another_mailbox_says_the_messages_stay_recoverable(
        self, app: Starlette, graph: respx.MockRouter
    ) -> None:
        person = _Person(agrees=True, word=_MOVE.agree)
        arguments = _arguments(_MOVE, mailbox=_MAILBOX) | {"destination": "deleteditems"}

        async with _connected(app, person) as client:
            _ = await client.call_tool(_MOVE.name, arguments)

        assert len(person.questions) == 1
        assert "Delete 2 messages" in person.questions[0]
        assert "They stay recoverable in Deleted Items." in person.questions[0]
        assert len(_writes(graph, _MOVE)) == len(_REFS)

    @_EITHER_TOOL
    async def test_an_accept_that_omits_the_request_state_writes_nothing(
        self, app: Starlette, graph: respx.MockRouter, tool: _Tool
    ) -> None:
        person = _Person(agrees=True, word=tool.agree)
        arguments = _arguments(tool, mailbox=_MAILBOX)

        async with _connected(app, person) as client:
            first = await client.session.call_tool(tool.name, arguments, allow_input_required=True)

            assert isinstance(first, InputRequiredResult), "the question was never put to anybody"
            (key,) = first.input_requests or {}

            second = await client.session.call_tool(
                tool.name,
                arguments,
                input_responses={
                    key: CarriedAnswer(action="accept", content={"value": tool.agree})
                },
                allow_input_required=True,
            )

        assert isinstance(second, CallToolResult), "the unbound retry asked again instead"
        assert second.is_error, "an accept bound to nothing was read as agreement"
        refusal = " ".join(block.text for block in second.content if isinstance(block, TextContent))
        assert "given for a different request" in refusal, refusal
        assert _writes(graph, tool) == [], (
            f"an accept nothing was bound to wrote {_writes(graph, tool)}"
        )
