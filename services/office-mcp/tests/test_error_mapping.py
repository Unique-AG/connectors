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

from collections.abc import AsyncIterator, Iterator, Mapping
from dataclasses import dataclass
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

from office_mcp.app import create_app
from office_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset
from office_mcp.graph_client import GraphForbidden
from office_mcp.shared.seam import graph_tool_errors
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


@dataclass(frozen=True)
class _Refused:
    """One tool call that reaches Graph, and the permissions its refusal has to name.

    `permissions` is written out rather than read off the tool module. Read off the module it would
    assert that the tool agrees with itself, and the failure to catch is a message worded from
    somewhere else entirely — the registry's union, or another tool's tuple.
    """

    arguments: Mapping[str, object]
    permissions: tuple[str, ...]


# One entry per tool, and this file grows one as each tool arrives.
_EVERY_TOOL: Mapping[str, _Refused] = {
    "get_me": _Refused({}, ("User.Read",)),
}

# The surface under test, resolved once so the parametrisation below is the deployment's own tool
# list rather than a second copy of it.
_SELECTION: Selection = resolve(preset=ToolsPreset.TEAMS, enabled=None)


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


def _advice_for(permissions: tuple[str, ...]) -> str:
    """What this refusal reads as, asked of the mapping directly."""
    with pytest.raises(ToolError) as raised, graph_tool_errors(*permissions):
        raise GraphForbidden(
            "denied", status=403, code="Authorization_RequestDenied", request_id=_REQUEST_ID
        )
    return str(raised.value)


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
