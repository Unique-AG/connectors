"""One refused Graph call per registered tool, read the way a model reads it.

This file exists because of a gap between the two suites that look like they already cover it.
`tests/shared/test_seam.py` drives the mapping directly and pins the prose. `tests/tools/` calls
each tool's inner function and asserts the raw `GraphFailure` — the word `ToolError` does not appear
in that directory at all. Neither crosses `register()`, so neither resolves a dependency and neither
enters middleware. A tool whose refusals reach the client untranslated satisfies both of them, and
what the model would then read is `Error calling tool 'list_chats': Microsoft Graph returned 403`,
which names no remedy and no permission.

So every case here goes through an in-memory FastMCP client against the real composed app:
dependency resolution, middleware, and the tool body. The assertion is byte equality with what
`shared/seam.py` says about the same failure, computed here through the mapping directly — the two
routes to one message are the property, and the prose those messages contain is
`tests/shared/test_seam.py`'s subject rather than this file's.

The table is parametrised over the resolved `Selection` and checked against it, so a tool added to
the registry fails here until it is covered.

The three stubs (Entra's exchange, a mocked Graph, the in-process client) are this file's own, as
they are `test_mcp_tools.py`'s own: a fixture shared between the two would make either file's
failure the other's to diagnose, and this one deliberately refuses every Graph request rather than
answering it.
"""

import logging
from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass
from typing import cast
from urllib.parse import quote

import httpx
import pytest
import respx
from azure.core.credentials import AccessToken as GraphAccessToken
from fastmcp import Client, FastMCP
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.dependencies import AccessToken
from starlette.applications import Starlette

from office_mcp.app import create_app
from office_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_mcp.graph_client import GraphForbidden
from office_mcp.shared.seam import (
    GraphAdviceMiddleware,
    ToolAdvice,
    graph_tool_errors,
)
from office_mcp.tools import Selection, resolve

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"
_CLIENT_TOKEN = "synthetic-fastmcp-session-token"
_OBO_TOKEN = "synthetic-obo-graph-token"

# The refusal every tool here meets, and the evidence an operator needs out of it. A 403 rather than
# any other status because its remedy is the one worded per tool: the permission named in it is the
# whole of what a caller hands their administrator.
_REQUEST_ID = "synthetic-request-id-every-tool"
_REFUSED = {"error": {"code": "Authorization_RequestDenied", "message": "denied"}}

# Arguments, invented. Every id is obviously fake; the handle is spelled the way the tool that mints
# one spells it, because a tool that rejects its argument as not-a-handle never reaches Graph and
# would pass this file while mapping nothing.
_CHAT_ID = "19:release@thread.v2"
_MESSAGE_ID = "1770000000000"
_CHAT_MESSAGE_URI = f"teams:///chats/{quote(_CHAT_ID, safe='')}/messages/{_MESSAGE_ID}"


@dataclass(frozen=True)
class _Refused:
    """One tool call that reaches Graph, and the permissions its refusal has to name.

    `permissions` is written out rather than read off the tool module. Read off the module it would
    assert that the tool agrees with itself, and the failure to catch is a message worded from
    somewhere else entirely — the registry's union, or another tool's tuple.
    """

    arguments: Mapping[str, object]
    permissions: tuple[str, ...]


# One entry per tool, and this file grows one as each tool arrives. `read_message` is the one whose
# permissions are not its declared tuple: a message read is per surface, so a chat handle's refusal
# names `Chat.Read` alone, and naming the channel permission as well would send an administrator
# after one that was never missing.
_EVERY_TOOL: Mapping[str, _Refused] = {
    "get_me": _Refused({}, ("User.Read",)),
    "list_chats": _Refused({}, ("Chat.Read",)),
    "search_messages": _Refused({"query": "release"}, ("Chat.Read", "ChannelMessage.Read.All")),
    "read_message": _Refused({"uri": _CHAT_MESSAGE_URI}, ("Chat.Read",)),
}

# The surface under test, resolved once so the parametrisation below is the deployment's own tool
# list rather than a second copy of it.
_SELECTION: Selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)

# The MCP middleware chain the composed app ends up with, outside-in. Two of the four belong to
# other packages, so the assertion is on names: what is load-bearing is which side of the operations
# layer the advice sits on rather than the types themselves.
_CHAIN = (
    "GraphAdviceMiddleware",
    "TraceContextRestoreMiddleware",
    "DereferenceRefsMiddleware",
    "_McpMetrics",
)

# Two synthetic tools that refuse identically, one of them mapping its own refusal first.
_DOUBLY_MAPPED = "read_twice"
_MAPPED_ONCE = "read_once"
_PERMISSION = "Chat.Read"


class _StubOboCredential:
    """Stub for azure.identity.aio.OnBehalfOfCredential: answers with a token, records nothing."""

    async def get_token(self, *scopes: str) -> GraphAccessToken:
        _ = scopes
        return GraphAccessToken(token=_OBO_TOKEN, expires_on=0)


@pytest.fixture
def obo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the On-Behalf-Of exchange and authenticate the in-process client.

    The exchange succeeding is the point: what is being tested is the failure after it, and a
    refusal here would answer every tool with the token advice instead.
    """
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
    """A Graph that refuses everything, whatever the path and whatever the method.

    A catch-all rather than a route per tool: the path a tool reaches for is the tool's own
    knowledge, and a table of them here would be a second copy of it that goes stale silently — a
    tool whose path moved would stop being refused and start passing for the wrong reason.
    """
    with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as router:
        _ = router.route().mock(
            return_value=httpx.Response(403, headers={"request-id": _REQUEST_ID}, json=_REFUSED)
        )
        yield router


@pytest.fixture
def two_tools() -> FastMCP[None]:
    """One server, the advice middleware, and one refusal raised on either side of a `with` block.

    This is the only place the middleware's own wording of a Graph refusal is reachable through a
    real call: every registered tool still opens its own block, and that block is what the client
    reads. So a tool without one is written here, beside a tool with one, both refused identically.
    """
    mcp: FastMCP[None] = FastMCP(
        "Two Tools",
        middleware=[
            GraphAdviceMiddleware(
                {
                    _DOUBLY_MAPPED: ToolAdvice(permissions=(_PERMISSION,)),
                    _MAPPED_ONCE: ToolAdvice(permissions=(_PERMISSION,)),
                }
            )
        ],
    )

    @mcp.tool(name=_DOUBLY_MAPPED)
    async def read_twice() -> str:
        with graph_tool_errors(_PERMISSION):
            raise _refused()

    @mcp.tool(name=_MAPPED_ONCE)
    async def read_once() -> str:
        raise _refused()

    return mcp


@pytest.fixture
def app() -> Starlette:
    """The app with every tool there is, composed as production composes it."""
    return create_app(
        config=AppConfig.model_validate({"public_base_url": "https://office-mcp.example"}),
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
        surface_config=SurfaceConfig.model_validate({"tools_preset": ToolsPreset.TEAMS}),
    )


@pytest.fixture
async def mcp_client(app: Starlette) -> AsyncIterator[Client[FastMCPTransport]]:
    server = cast("FastMCP[None]", app.state.fastmcp_server)
    async with Client(FastMCPTransport(server)) as client:
        yield client


def _refused() -> GraphForbidden:
    """The refusal as a failure rather than a response. Built per call: it carries a traceback."""
    return GraphForbidden(
        "denied", status=403, code="Authorization_RequestDenied", request_id=_REQUEST_ID
    )


def _advice_for(permissions: tuple[str, ...]) -> str:
    """What this refusal reads as, asked of the mapping directly."""
    with pytest.raises(ToolError) as raised, graph_tool_errors(*permissions):
        raise _refused()
    return str(raised.value)


def _chain(error: BaseException) -> list[BaseException]:
    """`error` and everything it was raised from."""
    walked: list[BaseException] = []
    cause: BaseException | None = error
    while cause is not None and not any(one is cause for one in walked):
        walked.append(cause)
        cause = cause.__cause__
    return walked


class TestEveryToolTranslatesItsOwnRefusal:
    def test_every_registered_tool_is_covered_here(self) -> None:
        """The guard on the guard. A tool added to the registry and not to the table above would
        leave this file one tool short and silent about it — the same failure the file exists to
        prevent, one level up."""
        assert set(_EVERY_TOOL) == set(_SELECTION.tools), (
            "every tool this deployment registers needs one refused call here"
        )

    @pytest.mark.usefixtures("obo", "graph")
    @pytest.mark.parametrize("tool", _SELECTION.tools)
    async def test_a_refused_call_reaches_the_client_as_advice(
        self, mcp_client: Client[FastMCPTransport], tool: str
    ) -> None:
        """The message a model reads is the advice, exactly — not FastMCP's report of an exception.

        Byte equality rather than a keyword: "administrator" appearing somewhere in a message that
        also carries a stack-shaped prefix is what an un-mapped tool looks like.
        """
        refused = _EVERY_TOOL[tool]

        with pytest.raises(ToolError) as raised:
            _ = await mcp_client.call_tool(tool, dict(refused.arguments))

        assert str(raised.value) == _advice_for(refused.permissions)

    @pytest.mark.usefixtures("obo", "graph")
    @pytest.mark.parametrize("tool", _SELECTION.tools)
    async def test_the_permissions_it_names_are_its_own(
        self, mcp_client: Client[FastMCPTransport], tool: str
    ) -> None:
        """The other half of the same rule, asserted directly rather than through the comparison
        above: a message worded from the registry's union would pass byte equality nowhere and
        would name permissions this call never used, which is what sends an administrator after a
        permission that was never missing.
        """
        refused = _EVERY_TOOL[tool]
        unrelated = tuple(
            permission
            for permission in _SELECTION.permissions
            if permission not in refused.permissions
        )

        with pytest.raises(ToolError) as raised:
            _ = await mcp_client.call_tool(tool, dict(refused.arguments))

        message = str(raised.value)
        for permission in refused.permissions:
            assert permission in message, message
        for permission in unrelated:
            assert permission not in message, f"{tool} named {permission}, which it never used"


class TestWhereTheMappingSits:
    def test_the_advice_is_outside_the_operations_layer(self, app: Starlette) -> None:
        """The order is load-bearing in both directions. Outside `_McpMetrics`, a refusal is logged
        and counted as it happened, with the Graph failure still under it, and the client is handed
        the polished text; inside it, every operator-facing record of a 403 would read as the advice
        and the cause chain would be gone.
        """
        server = cast("FastMCP[None]", app.state.fastmcp_server)

        assert tuple(type(middleware).__name__ for middleware in server.middleware) == _CHAIN

    @pytest.mark.usefixtures("obo", "graph")
    async def test_the_operations_layer_logs_the_failure_untranslated(
        self, mcp_client: Client[FastMCPTransport], caplog: pytest.LogCaptureFixture
    ) -> None:
        """What being outside it buys, asserted on the record rather than on the order.

        The exception type in that record is whichever layer worded the refusal and is not pinned
        here; the Graph failure under it is what has to survive, because it carries the status and
        the request id that make a production 403 traceable.
        """
        with caplog.at_level(logging.ERROR, logger="unique_mcp"), pytest.raises(ToolError):
            _ = await mcp_client.call_tool("get_me", {})

        logged = [record for record in caplog.records if record.exc_info is not None]
        assert logged, "the operations layer logged nothing about a failed call"
        raised = logged[-1].exc_info
        assert raised is not None and raised[1] is not None
        causes = _chain(raised[1])

        assert any(isinstance(cause, GraphForbidden) for cause in causes), causes


class TestMappingTwiceChangesNothing:
    async def test_a_surviving_tool_block_and_the_middleware_agree_word_for_word(
        self, two_tools: FastMCP[None]
    ) -> None:
        """What makes this stack rebasable one step at a time: the mapping can move out of a tool
        without the message moving. The tool that still maps its own refusal is mapped twice — by
        its block, then by the middleware that sees the result — and reads identically to the tool
        the middleware alone maps.
        """
        async with Client(FastMCPTransport(two_tools)) as client:
            with pytest.raises(ToolError) as doubly:
                _ = await client.call_tool(_DOUBLY_MAPPED, {})
            with pytest.raises(ToolError) as once:
                _ = await client.call_tool(_MAPPED_ONCE, {})

        assert str(doubly.value) == str(once.value)
        assert str(doubly.value) == _advice_for((_PERMISSION,))
