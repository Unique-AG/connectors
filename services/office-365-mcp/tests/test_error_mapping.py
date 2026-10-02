import ast
import logging
import pathlib
import re
from collections.abc import AsyncIterator, Callable, Iterable, Iterator, Mapping
from importlib import import_module
from types import ModuleType
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
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools.base import ToolResult
from mcp.types import CallToolRequestParams, ElicitRequestFormParams
from starlette.applications import Starlette

from office_365_mcp.app import create_app
from office_365_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_365_mcp.graph_client import GraphFailure, GraphForbidden
from office_365_mcp.shared.handles import onenote_page_handle
from office_365_mcp.shared.seam import (
    Advised,
    GraphAdviceMiddleware,
    ToolAdvice,
)
from office_365_mcp.tools import (
    PRESETS,
    TOOL_NAMES,
    GraphCallExample,
    Selection,
    graph_advice,
    graph_call_examples,
    onenote_append_to_page,
    onenote_edit_page,
    onenote_rename_page,
    register_tools,
    resolve,
)

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

_EVERY_REGISTERED_TOOL: Mapping[str, GraphCallExample] = graph_call_examples(
    resolve(preset=None, enabled=TOOL_NAMES)
)

_A_REPEAT_CAN_WRITE_TWICE: frozenset[str] = frozenset(
    {
        "onenote_append_to_page",
        "onenote_copy_notebook",
        "onenote_copy_page",
        "onenote_copy_section",
        "onenote_create_notebook",
        "onenote_create_page",
        "onenote_create_section",
        "onenote_create_section_group",
        "onenote_edit_page",
        "outlook_cancel_event",
        "outlook_create_event",
        "outlook_create_event_on_behalf",
        "outlook_draft_mail",
        "outlook_draft_reply",
        "outlook_move_mail",
        "outlook_respond_to_invite",
        "outlook_send_draft",
        "outlook_update_event",
        "teams_react_to_message",
        "teams_send_channel_message",
        "teams_send_chat_message",
    }
)

_CHANNEL_WRITES_IN_PRESETS_THAT_READ_NO_CHANNEL_ON_PURPOSE: frozenset[tuple[str, str]] = frozenset(
    {
        ("teams-write", "teams_send_channel_message"),
    }
)

_OUTCOME_UNKNOWN = "Microsoft 365 can make a change and then give an error."
_CHECK_FIRST = "Do not call this tool again first."
_ASK_THE_USER = "ask the user if the Microsoft 365 app shows the change."
_RETRY_ONCE = "Retry once"

_EVERY_ADVICE: Mapping[str, ToolAdvice] = graph_advice(resolve(preset=None, enabled=TOOL_NAMES))

_CHAT_MESSAGES = "/chats/19%3Arelease%40thread.v2/messages"
_PAGE_ID = "1-SYNTHETICPAGE00000000000000000000!ABCDEF"
_PAGE_PATH = f"/me/onenote/pages/{_PAGE_ID}"
_PAGE = {
    "id": _PAGE_ID,
    "title": "Notes",
    "parentSection": {"id": "S1", "displayName": "General"},
    "parentNotebook": {"id": "NB1", "displayName": "Work"},
}
_NOTEBOOK = {"id": "NB1", "displayName": "Work", "isShared": False, "userRole": "Owner"}

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

_ORACLE = "worded_alone"

_SOURCE = pathlib.Path(__file__).parent.parent / "src" / "office_365_mcp"
_POLICED = (_SOURCE / "tools", _SOURCE / "shared")

_WRITES_THEN_REREADS: tuple[str, ...] = (
    onenote_append_to_page.TOOL_NAME,
    onenote_edit_page.TOOL_NAME,
    onenote_rename_page.TOOL_NAME,
)
_WRITTEN_BUT_UNREAD = "Then this connector did not receive the updated page from Microsoft 365."


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


def _gateway_timeout(request: httpx.Request) -> httpx.Response:
    _ = request
    return httpx.Response(504)


def _read_timeout(request: httpx.Request) -> httpx.Response:
    raise httpx.ReadTimeout("timed out", request=request)


_A_WRITE_FAILS = pytest.mark.parametrize(
    "failing", [_gateway_timeout, _read_timeout], ids=["504", "read-timeout"]
)


async def _agree_to_it(
    _message: str,
    _response_type: type | None,
    params: ElicitRequestParams,
    _context: object,
) -> ElicitResult[dict[str, str]]:
    assert isinstance(params, ElicitRequestFormParams)
    options = cast("list[str]", params.requested_schema["properties"]["value"]["enum"])
    return ElicitResult(action="accept", content={"value": options[0]})


@pytest.fixture
async def agreeing_client() -> AsyncIterator[Client[FastMCPTransport]]:
    app = _composed(SurfaceConfig.model_validate({"tools_enabled": ",".join(TOOL_NAMES)}))
    server = cast("FastMCP[None]", app.state.fastmcp_server)
    async with Client(FastMCPTransport(server), elicitation_handler=_agree_to_it) as client:
        yield client


@pytest.fixture
def app() -> Starlette:
    return _composed(SurfaceConfig.model_validate({"tools_preset": ToolsPreset.TEAMS}))


def _composed(surface: SurfaceConfig) -> Starlette:
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
        surface_config=surface,
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


async def _advice_for(permissions: tuple[str, ...]) -> str:
    async def refuse(context: MiddlewareContext[CallToolRequestParams]) -> ToolResult:
        _ = context
        raise _refused()

    advice = GraphAdviceMiddleware({_ORACLE: ToolAdvice(permissions=permissions)})
    context = MiddlewareContext(message=CallToolRequestParams(name=_ORACLE, arguments={}))
    with pytest.raises(ToolError) as raised:
        _ = await advice.on_call_tool(context, refuse)
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
        assert str(raised.value) == await _advice_for(refused.permissions)

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

        assert str(narrowed.value) == await _advice_for(
            _EVERY_TOOL["teams_read_message"].permissions
        )
        assert str(after.value) == await _advice_for(
            _EVERY_TOOL["teams_search_messages"].permissions
        )


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
            _ = await mcp_client.call_tool("teams_list_chats", {})

        logged = [record for record in caplog.records if record.exc_info is not None]
        assert logged, "the operations layer logged nothing about a failed call"
        raised = logged[-1].exc_info
        assert raised is not None and raised[1] is not None
        causes = _chain(raised[1])

        assert any(isinstance(cause, GraphForbidden) for cause in causes), causes


class TestTheOrderThePermissionsAreNamed:
    """The order is prose: "OnlineMeetings.Read and OnlineMeetingTranscript.Read.All" reads as
    resolve the meeting, then read its transcript. Hence a table rather than a tool's own `tags`,
    which lose the order.
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


def _in_scope(nodes: Iterable[ast.AST]) -> Iterator[ast.AST]:
    for node in nodes:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef | ast.Lambda):
            continue
        yield node
        yield from _in_scope(ast.iter_child_nodes(node))


def _module_at(path: pathlib.Path) -> ModuleType:
    parts = path.relative_to(_SOURCE).with_suffix("").parts
    return import_module(".".join(("office_365_mcp", *(p for p in parts if p != "__init__"))))


def _named(node: ast.expr | None, module: ModuleType) -> tuple[object, ...]:
    if isinstance(node, ast.Tuple):
        return tuple(value for element in node.elts for value in _named(element, module))
    if isinstance(node, ast.Name):
        return (cast("object", getattr(module, node.id, None)),)
    return ()


def _is(value: object, kind: type[BaseException]) -> bool:
    return isinstance(value, type) and issubclass(value, kind)


def _raised_from_a_graph_failure(path: pathlib.Path) -> Iterator[tuple[int, tuple[object, ...]]]:
    module = _module_at(path)
    for handler in ast.walk(ast.parse(path.read_text())):
        if not isinstance(handler, ast.ExceptHandler) or handler.name is None:
            continue
        if not any(_is(caught, GraphFailure) for caught in _named(handler.type, module)):
            continue
        for node in _in_scope(handler.body):
            if (
                isinstance(node, ast.Raise)
                and isinstance(node.cause, ast.Name)
                and node.cause.id == handler.name
                and isinstance(node.exc, ast.Call)
            ):
                yield node.lineno, _named(node.exc.func, module)


class TestAToolsOwnWordsForALandedWrite:
    @pytest.mark.usefixtures("obo", "retry_sleeps")
    @pytest.mark.parametrize("status", [404, 503])
    @pytest.mark.parametrize("tool", _WRITES_THEN_REREADS)
    async def test_a_failed_reread_after_the_write_reaches_the_client_as_written(
        self, agreeing_client: Client[FastMCPTransport], tool: str, status: int
    ) -> None:
        example = _EVERY_REGISTERED_TOOL[tool]
        handle = onenote_page_handle(str(example.arguments["page"]))
        assert handle is not None, f"{tool}'s own call example names no page"
        page_path = f"/me/onenote/pages/{handle.page_id}"
        page = {"id": handle.page_id, "title": "Synthetic", "parentNotebook": _NOTEBOOK}
        failed = httpx.Response(status, json={"error": {"code": "synthetic", "message": "x"}})

        with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as graph:
            _ = graph.get(page_path).mock(
                side_effect=[httpx.Response(200, json=page), *([failed] * 4)]
            )
            _ = graph.get(f"/me/onenote/notebooks/{_NOTEBOOK['id']}").mock(
                return_value=httpx.Response(200, json=_NOTEBOOK)
            )
            written = graph.post(f"{page_path}/onenotePatchContent").mock(
                return_value=httpx.Response(204)
            )
            with pytest.raises(ToolError) as raised:
                _ = await agreeing_client.call_tool(tool, dict(example.arguments))

        assert written.call_count == 1, f"{tool} did not write exactly once"
        assert _WRITTEN_BUT_UNREAD in str(raised.value), (
            f"{tool} wrote once and told the client: {raised.value}"
        )

    def test_a_tool_that_words_a_graph_failure_itself_raises_advised(self) -> None:
        sources = sorted(path for directory in _POLICED for path in directory.rglob("*.py"))
        raised = [
            (f"{path.relative_to(_SOURCE)}:{line}", named)
            for path in sources
            for line, named in _raised_from_a_graph_failure(path)
        ]
        reworded = [
            where
            for where, named in raised
            if any(_is(one, ToolError) and not _is(one, Advised) for one in named)
        ]

        assert raised, "no raise chains a caught Graph failure, so this check guards nothing"
        assert not reworded, (
            "GraphAdviceMiddleware replaces a ToolError chained to a Graph failure with its "
            + f"generic advice. Raise Advised instead at {reworded}"
        )


async def _registered_descriptions(selection: Selection) -> dict[str, str]:
    server: FastMCP = FastMCP("descriptions-under-test", version="0")
    async with httpx.AsyncClient() as transport:
        register_tools(server, transport, selection)
        return {tool.name: tool.description or "" for tool in await server.list_tools()}


def _tools_named_by_the_retry_advice(description: str) -> set[str]:
    bullets = [
        line
        for line in description.partition("Notes:")[2].splitlines()
        if line.startswith("- ") and "times out" in line
    ]
    return {
        name
        for name in TOOL_NAMES
        for bullet in bullets
        if re.search(rf"\b{re.escape(name)}\b", bullet)
    }


class TestAWriteThatFailsCanAlreadyBeDone:
    @pytest.mark.usefixtures("obo")
    @_A_WRITE_FAILS
    async def test_a_teams_message_is_posted_once_and_the_model_checks_before_a_repeat(
        self,
        agreeing_client: Client[FastMCPTransport],
        failing: Callable[[httpx.Request], httpx.Response],
    ) -> None:
        with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as graph:
            post = graph.post(_CHAT_MESSAGES).mock(side_effect=failing)
            with pytest.raises(ToolError) as raised:
                _ = await agreeing_client.call_tool(
                    "teams_send_chat_message",
                    dict(_EVERY_REGISTERED_TOOL["teams_send_chat_message"].arguments),
                )

        message = str(raised.value)
        assert post.call_count == 1
        assert _OUTCOME_UNKNOWN in message
        assert _CHECK_FIRST in message
        assert _RETRY_ONCE not in message

    @pytest.mark.usefixtures("obo")
    @_A_WRITE_FAILS
    async def test_a_onenote_append_is_posted_once_and_the_model_checks_before_a_repeat(
        self,
        agreeing_client: Client[FastMCPTransport],
        failing: Callable[[httpx.Request], httpx.Response],
    ) -> None:
        with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as graph:
            _ = graph.get(_PAGE_PATH).mock(return_value=httpx.Response(200, json=_PAGE))
            _ = graph.get("/me/onenote/notebooks/NB1").mock(
                return_value=httpx.Response(200, json=_NOTEBOOK)
            )
            post = graph.post(f"{_PAGE_PATH}/onenotePatchContent").mock(side_effect=failing)
            with pytest.raises(ToolError) as raised:
                _ = await agreeing_client.call_tool(
                    "onenote_append_to_page",
                    dict(_EVERY_REGISTERED_TOOL["onenote_append_to_page"].arguments),
                )

        message = str(raised.value)
        assert post.call_count == 1
        assert _OUTCOME_UNKNOWN in message
        assert _CHECK_FIRST in message
        assert _RETRY_ONCE not in message

    async def test_the_writes_that_a_repeat_can_do_twice_are_the_ones_annotated_so(
        self, agreeing_client: Client[FastMCPTransport]
    ) -> None:
        annotated = {
            tool.name
            for tool in await agreeing_client.list_tools()
            if tool.annotations is not None
            and not tool.annotations.read_only_hint
            and not tool.annotations.idempotent_hint
        }

        assert annotated == _A_REPEAT_CAN_WRITE_TWICE

    def test_the_writes_that_declare_what_shows_their_change_are_the_ones_a_repeat_can_do_twice(
        self,
    ) -> None:
        declared = {
            tool
            for tool in TOOL_NAMES
            if hasattr(import_module(f"office_365_mcp.tools.{tool}"), "CHANGE_SHOWN_BY")
        }

        assert declared == _A_REPEAT_CAN_WRITE_TWICE

    async def test_a_tool_that_shows_a_change_is_a_read_only_tool_of_this_server(
        self, agreeing_client: Client[FastMCPTransport]
    ) -> None:
        read_only = {
            tool.name
            for tool in await agreeing_client.list_tools()
            if tool.annotations is not None and tool.annotations.read_only_hint
        }
        named = {
            shown
            for tool in _A_REPEAT_CAN_WRITE_TWICE
            for shown in cast(
                "tuple[str, ...]", import_module(f"office_365_mcp.tools.{tool}").CHANGE_SHOWN_BY
            )
        }

        assert named <= read_only, named - read_only

    def test_the_advice_names_only_the_tools_that_the_deployment_turns_on(self) -> None:
        channel = "teams_send_channel_message"

        assert _EVERY_ADVICE[channel].shown_by == ("teams_browse_channel",)
        assert graph_advice(resolve(preset="teams-write", enabled=None))[channel].shown_by == ()

    async def test_a_retry_bullet_that_names_a_tool_is_in_the_registered_descriptions(self) -> None:
        descriptions = await _registered_descriptions(resolve(preset=None, enabled=TOOL_NAMES))

        assert any(_tools_named_by_the_retry_advice(text) for text in descriptions.values())

    @pytest.mark.parametrize("preset", list(PRESETS))
    async def test_the_retry_advice_of_a_tool_names_only_tools_that_its_preset_registers(
        self, preset: str
    ) -> None:
        selection = resolve(preset=preset, enabled=None)
        descriptions = await _registered_descriptions(selection)

        unregistered = {
            tool: sorted(named)
            for tool, text in descriptions.items()
            if (named := _tools_named_by_the_retry_advice(text) - set(selection.tools))
        }

        assert not unregistered, f"{preset} sends the model to tools it lacks: {unregistered}"

    def test_a_write_shows_its_change_in_every_preset_but_the_ones_that_read_no_channel(
        self,
    ) -> None:
        shown_by_nothing = {
            (preset, tool)
            for preset in PRESETS
            for tool, advice in graph_advice(resolve(preset=preset, enabled=None)).items()
            if tool in _A_REPEAT_CAN_WRITE_TWICE and not advice.shown_by
        }

        assert shown_by_nothing == _CHANNEL_WRITES_IN_PRESETS_THAT_READ_NO_CHANNEL_ON_PURPOSE

    @pytest.mark.usefixtures("obo", "retry_sleeps")
    @pytest.mark.parametrize("tool", TOOL_NAMES)
    async def test_a_tool_gets_the_outage_advice_that_its_annotation_calls_for(
        self, agreeing_client: Client[FastMCPTransport], tool: str
    ) -> None:
        with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as graph:
            _ = graph.route().mock(return_value=httpx.Response(504))
            with pytest.raises(ToolError) as raised:
                _ = await agreeing_client.call_tool(
                    tool, dict(_EVERY_REGISTERED_TOOL[tool].arguments)
                )
            reached = bool(graph.calls)

        message = str(raised.value)
        assert reached, f"{tool} refused its own example arguments before reaching Graph"
        if tool in _A_REPEAT_CAN_WRITE_TWICE:
            assert _OUTCOME_UNKNOWN in message, message
            assert _CHECK_FIRST in message, message
            assert _RETRY_ONCE not in message, message
            shown_by = _EVERY_ADVICE[tool].shown_by
            assert all(shown in message for shown in shown_by), message
            assert (_ASK_THE_USER in message) == (not shown_by), message
        else:
            assert _RETRY_ONCE in message, message
            assert _OUTCOME_UNKNOWN not in message, message
