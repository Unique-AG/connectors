"""One refused Graph call per registered tool, driven through the composed app.

`tests/shared/test_seam.py` and `tests/tools/` look like they cover this, but neither crosses
`register()`, so a tool whose refusals reach the client untranslated passes both. Every case here
goes through an in-memory FastMCP client and asserts byte equality with what `shared/seam.py` words
for the same failure; the wording itself is `tests/shared/test_seam.py`'s subject.

Cases come from `graph_call_examples` over the registered surface. The hand-written table this
replaced left the file one tool short whenever a tool was registered before its row existed; a tool
publishing no such call is now a type error (`ToolModule` in `tools/__init__.py`).

The three stubs are this file's own, as they are `test_mcp_tools.py`'s own.
"""

import logging
from collections.abc import AsyncIterator, Iterator, Mapping
from typing import cast

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

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_365_mcp.graph_client import GraphForbidden
from office_365_mcp.shared.seam import (
    GraphAdviceMiddleware,
    ToolAdvice,
    graph_tool_errors,
)
from office_365_mcp.tools import GraphCallExample, Selection, graph_call_examples, resolve

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"
_CLIENT_TOKEN = "synthetic-fastmcp-session-token"
_OBO_TOKEN = "synthetic-obo-graph-token"

_REQUEST_ID = "synthetic-request-id-every-tool"
_REFUSED = {"error": {"code": "Authorization_RequestDenied", "message": "denied"}}

_SELECTION: Selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)

_EVERY_TOOL: Mapping[str, GraphCallExample] = graph_call_examples(_SELECTION)

_NAMES_SEVERAL: tuple[str, ...] = tuple(
    tool for tool, example in _EVERY_TOOL.items() if len(example.permissions) > 1
)

# The MCP middleware chain the composed app ends up with, outside-in. Two of the six belong to
# other packages, so the assertion is on names rather than on the types: `_McpMetrics` is
# `unique_mcp`'s own private class, and importing it here to compare types would be reaching past
# its front door for the sake of a name it already answers to.
#
# `BoundedNameMiddleware` is outermost of all, because it has to normalise an unresolvable tool name
# before `_McpMetrics` reads it. `tests/test_app.py` holds the rule that pins the two relative to
# each other.
_CHAIN = (
    "BoundedNameMiddleware",
    "GraphAdviceMiddleware",
    "TraceContextRestoreMiddleware",
    "MessageLogMiddleware",
    "DereferenceRefsMiddleware",
    "_McpMetrics",
)

# The two members of that chain that record what happened to a call — one log line, one set of
# counters — and so the two the advice has to stay outside of. This, rather than the whole tuple
# above, is the ordering the class below is named for.
_RECORDS_THE_OUTCOME = ("MessageLogMiddleware", "_McpMetrics")

# Two synthetic tools that refuse identically, one of them mapping its own refusal first.
_DOUBLY_MAPPED = "read_twice"
_MAPPED_ONCE = "read_once"
_PERMISSION = "Chat.Read"


class _StubOboCredential:
    """Stub for azure.identity.aio.OnBehalfOfCredential."""

    async def get_token(self, *scopes: str) -> GraphAccessToken:
        _ = scopes
        return GraphAccessToken(token=_OBO_TOKEN, expires_on=0)


@pytest.fixture
def obo(monkeypatch: pytest.MonkeyPatch) -> None:
    """The exchange has to succeed: a refusal here would answer every tool with the token advice
    instead of the 403 advice under test."""
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
    """A catch-all rather than a route per tool: a table of paths here would go stale silently, and
    a tool whose path moved would stop being refused and pass for the wrong reason."""
    with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as router:
        _ = router.route().mock(
            return_value=httpx.Response(403, headers={"request-id": _REQUEST_ID}, json=_REFUSED)
        )
        yield router


@pytest.fixture
def two_tools() -> FastMCP[None]:
    """One tool words its own refusal, the other leaves it to the middleware, so moving a mapping
    between the two stays a change nobody calling this server can see."""
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
        surface_config=SurfaceConfig.model_validate({"tools_preset": ToolsPreset.TEAMS}),
    )


@pytest.fixture
async def mcp_client(app: Starlette) -> AsyncIterator[Client[FastMCPTransport]]:
    server = cast("FastMCP[None]", app.state.fastmcp_server)
    async with Client(FastMCPTransport(server)) as client:
        yield client


def _refused() -> GraphForbidden:
    """Built per call rather than shared: it carries a traceback."""
    return GraphForbidden(
        "denied", status=403, code="Authorization_RequestDenied", request_id=_REQUEST_ID
    )


def _advice_for(permissions: tuple[str, ...]) -> str:
    with pytest.raises(ToolError) as raised, graph_tool_errors(*permissions):
        raise _refused()
    return str(raised.value)


def _chain(error: BaseException) -> list[BaseException]:
    walked: list[BaseException] = []
    cause: BaseException | None = error
    while cause is not None and not any(one is cause for one in walked):
        walked.append(cause)
        cause = cause.__cause__
    return walked


class TestEveryToolTranslatesItsOwnRefusal:
    def test_every_registered_tool_brings_its_own_refusable_call(self) -> None:
        """Against an empty mapping every parametrised test below is silently uncollected."""
        assert set(_EVERY_TOOL) == set(_SELECTION.tools), (
            "the derived cases are the registered surface — they cannot be a subset of it"
        )
        assert _EVERY_TOOL, "the widest preset derived no refusable call at all"

    @pytest.mark.usefixtures("obo")
    @pytest.mark.parametrize("tool", _SELECTION.tools)
    async def test_a_refused_call_reaches_the_client_as_advice(
        self, mcp_client: Client[FastMCPTransport], graph: respx.MockRouter, tool: str
    ) -> None:
        """Byte equality rather than a keyword: "administrator" inside a message that also carries
        a stack-shaped prefix is what an un-mapped tool looks like. Graph being reached is asserted
        rather than assumed — a tool that refuses its own example arguments never makes a request.
        """
        refused = _EVERY_TOOL[tool]

        with pytest.raises(ToolError) as raised:
            _ = await mcp_client.call_tool(tool, dict(refused.arguments))

        assert graph.calls, f"{tool} refused its own example arguments before reaching Graph"
        assert str(raised.value) == _advice_for(refused.permissions)

    @pytest.mark.usefixtures("obo", "graph")
    @pytest.mark.parametrize("tool", _SELECTION.tools)
    async def test_the_permissions_it_names_are_its_own(
        self, mcp_client: Client[FastMCPTransport], tool: str
    ) -> None:
        """A message worded from the registry's union would name permissions this call never used,
        sending an administrator after a permission that was never missing."""
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

    @pytest.mark.usefixtures("obo", "graph")
    async def test_a_narrowed_refusal_does_not_word_the_next_call_in_the_session(
        self, mcp_client: Client[FastMCPTransport]
    ) -> None:
        """`teams_read_message` narrows its declared permissions on the state of one call. Said on
        the
        session's state instead, one keyword apart, the refused search below would name `Chat.Read`
        alone. Two calls on one client, because a fresh client per call would hide that.
        """
        with pytest.raises(ToolError) as narrowed:
            _ = await mcp_client.call_tool(
                "teams_read_message", dict(_EVERY_TOOL["teams_read_message"].arguments)
            )
        with pytest.raises(ToolError) as after:
            _ = await mcp_client.call_tool(
                "teams_search_messages", dict(_EVERY_TOOL["teams_search_messages"].arguments)
            )

        assert str(narrowed.value) == _advice_for(_EVERY_TOOL["teams_read_message"].permissions)
        assert str(after.value) == _advice_for(_EVERY_TOOL["teams_search_messages"].permissions)


class TestWhereTheMappingSits:
    def _chain_of(self, app: Starlette) -> tuple[str, ...]:
        server = cast("FastMCP[None]", app.state.fastmcp_server)
        return tuple(type(middleware).__name__ for middleware in server.middleware)

    def test_the_advice_is_outside_the_operations_layer(self, app: Starlette) -> None:
        """The order is load-bearing in both directions. Outside `_McpMetrics`, a refusal is logged
        and counted as it happened, with the Graph failure still under it, and the client is handed
        the polished text; inside it, every operator-facing record of a 403 would read as the advice
        and the cause chain would be gone.

        The relation alone is asserted, not the chain: a middleware arriving between the advice and
        the operations layer changes nothing about that, and pinning it here would make this test
        fail for a reason it does not name.
        """
        chain = self._chain_of(app)
        recording = [chain.index(name) for name in _RECORDS_THE_OUTCOME]

        assert chain.index("GraphAdviceMiddleware") < min(recording), chain

    def test_the_names_that_ordering_is_asserted_over_are_in_the_chain(
        self, app: Starlette
    ) -> None:
        """Guards the guard: the ordering above is asserted between names, and a name that has been
        renamed upstream orders nothing. Said here so a rename reads as a rename rather than as a
        `ValueError` raised from the middle of the assertion it invalidated."""
        chain = self._chain_of(app)
        named = ("GraphAdviceMiddleware", *_RECORDS_THE_OUTCOME)
        missing = [name for name in named if name not in chain]

        assert not missing, f"{missing} is no longer in the chain, which is {chain}"

    def test_a_dependency_bump_that_changes_the_chain_at_all_says_so_here(
        self, app: Starlette
    ) -> None:
        """Not an ordering rule: a tripwire, so a middleware that appears or disappears underneath
        this service is read here rather than inferred later from a metric that stopped being
        emitted. Two of the six are not this repository's — `DereferenceRefsMiddleware` is
        FastMCP's, appended at construction, and `_McpMetrics` is `unique_mcp`'s, appended by
        `setup_ops`. Update this tuple deliberately when a bump moves it; the ordering above is the
        part that may not move quietly.
        """
        assert self._chain_of(app) == _CHAIN

    @pytest.mark.usefixtures("obo", "graph")
    async def test_the_operations_layer_logs_the_failure_untranslated(
        self, mcp_client: Client[FastMCPTransport], caplog: pytest.LogCaptureFixture
    ) -> None:
        """The `GraphForbidden` under the logged exception has to survive: it carries the status
        and request id that make a production 403 traceable."""
        with caplog.at_level(logging.ERROR, logger="unique_mcp"), pytest.raises(ToolError):
            _ = await mcp_client.call_tool("list_chats", {})

        logged = [record for record in caplog.records if record.exc_info is not None]
        assert logged, "the operations layer logged nothing about a failed call"
        raised = logged[-1].exc_info
        assert raised is not None and raised[1] is not None
        causes = _chain(raised[1])

        assert any(isinstance(cause, GraphForbidden) for cause in causes), causes


class TestMappingTwiceChangesNothing:
    async def test_a_tool_block_and_the_middleware_agree_word_for_word(
        self, two_tools: FastMCP[None]
    ) -> None:
        async with Client(FastMCPTransport(two_tools)) as client:
            with pytest.raises(ToolError) as doubly:
                _ = await client.call_tool(_DOUBLY_MAPPED, {})
            with pytest.raises(ToolError) as once:
                _ = await client.call_tool(_MAPPED_ONCE, {})

        assert str(doubly.value) == str(once.value)
        assert str(doubly.value) == _advice_for((_PERMISSION,))


class TestTheOrderThePermissionsAreNamed:
    """The order is prose: "OnlineMeetings.Read and OnlineMeetingTranscript.Read.All" reads as
    resolve the meeting, then read its transcript. Hence a table rather than a tool's own `tags`,
    which lose the order.

    Both routes to a message pass the permissions through the same `_named`, so a sort there leaves
    every byte-equality assertion in this file agreeing with itself. The comparison here is
    therefore against the tuple the tool module declares.
    """

    def test_a_sort_would_be_visible_in_at_least_one_of_them(self) -> None:
        """If every selected tool happened to declare its permissions already sorted, the case
        below would pass against a sorted message and read as coverage."""
        assert any(
            _EVERY_TOOL[tool].permissions != tuple(sorted(_EVERY_TOOL[tool].permissions))
            for tool in _NAMES_SEVERAL
        ), "no selected tool declares its permissions in an order a sort would change"

    @pytest.mark.usefixtures("obo", "graph")
    @pytest.mark.parametrize("tool", _NAMES_SEVERAL)
    async def test_a_refusal_names_them_in_the_order_the_tool_declares_them(
        self, mcp_client: Client[FastMCPTransport], tool: str
    ) -> None:
        declared = _EVERY_TOOL[tool].permissions

        with pytest.raises(ToolError) as raised:
            _ = await mcp_client.call_tool(tool, dict(_EVERY_TOOL[tool].arguments))

        message = str(raised.value)
        appearances = [message.index(permission) for permission in declared]

        assert appearances == sorted(appearances), (
            f"{tool} declares {declared} and its refusal names them in another order: {message}"
        )
