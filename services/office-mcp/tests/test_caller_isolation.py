"""Two callers, one registration: every Graph request carries the token of the caller who asked.

Failure here is a data breach, not an outage. A tool is registered once, at startup, but the Graph
client it calls with is a FastMCP *dependency* resolved per call: `graph_client_for_caller` in
`shared/seam.py` closes over the process-wide transport and builds a client around this call's own
On-Behalf-Of token. The call site shows none of that. A tool body receives
`client: GraphServiceClient = graph` either way.

So the change that breaks it is small, plausible and silent. Building the client once inside
`register`, or memoising it in the dependency, sends every later caller's Graph requests under the
*first* caller's token. Memoising looks like an obvious saving, because the transport and the
permissions are the same every time. Both callers get a `200`. One of them is reading the other's
Teams data. Before this file existed, no test in the suite caught that: the tool tests inject a
client built from a fixed token, and the protocol tests use one caller, so the token every Graph
request carries is the only token there is.

These tests assert what the vulnerability changes and nothing else: the same tool, on the same
composed app and the same registration, called by two callers, and the `Authorization` header respx
captured off each outbound Graph request. The mocked Graph answers as Graph does, returning the
profile of whoever the bearer token names, so the second assertion is the incident itself. Caller B
must not read caller A's profile.
"""

from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import cast

import httpx
import pytest
import respx
from azure.core.credentials import AccessToken as GraphAccessToken
from fastmcp import Client, FastMCP
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import FastMCPTransport
from fastmcp.server.auth.providers.azure import AzureProvider
from fastmcp.server.dependencies import AccessToken
from respx.models import Call
from starlette.applications import Starlette

from office_mcp.app import create_app
from office_mcp.config import AppConfig, DatabaseConfig, EntraConfig, SurfaceConfig, ToolsPreset

GRAPH_V1 = "https://graph.microsoft.com/v1.0"

_CLIENT_ID = "1f2e3d4c-5b6a-7988-9a0b-1c2d3e4f5061"

# Two callers of one deployment, each with their own session token: what a client presents to this
# server, and what Entra exchanges for a Graph token. Different values, because telling the two
# callers apart is the whole of this file.
_ADA_SESSION_TOKEN = "synthetic-session-token-ada"
_GRACE_SESSION_TOKEN = "synthetic-session-token-grace"


def _graph_token_for(session_token: str) -> str:
    """The Graph token the On-Behalf-Of exchange answers one caller's session token with.

    A function rather than two constants: a caller's Graph token is theirs because it was derived
    from their own assertion, and a client cached across callers stops deriving it.
    """
    return f"synthetic-obo-graph-token-for-{session_token}"


_ADA = {
    "id": "00000000-0000-4000-8000-000000000001",
    "displayName": "Ada Lovelace",
    "mail": "ada@example.invalid",
    "userPrincipalName": "ada@corp.example.invalid",
    "jobTitle": "Analyst",
}

_GRACE = {
    "id": "00000000-0000-4000-8000-000000000002",
    "displayName": "Grace Hopper",
    "mail": "grace@example.invalid",
    "userPrincipalName": "grace@corp.example.invalid",
    "jobTitle": "Rear Admiral",
}

# Whose profile each Graph token opens. This makes the leak observable rather than inferred: a
# request is answered from its own bearer token, so a client carrying the wrong token reads the
# wrong user.
_PROFILES: Mapping[str, Mapping[str, object]] = {
    _graph_token_for(_ADA_SESSION_TOKEN): _ADA,
    _graph_token_for(_GRACE_SESSION_TOKEN): _GRACE,
}


class _StubOboCredential:
    """Stub for `azure.identity.aio.OnBehalfOfCredential`, holding the assertion it was built for.

    One instance per caller, as the real provider does it: `get_obo_credential` caches a credential
    per user assertion, so the Azure SDK's own token cache is per caller (fastmcp 3.4.5,
    `fastmcp/server/auth/providers/azure.py:628-683`).
    """

    def __init__(self, user_assertion: str) -> None:
        self._user_assertion: str = user_assertion

    async def get_token(self, *scopes: str) -> GraphAccessToken:
        _ = scopes
        return GraphAccessToken(token=_graph_token_for(self._user_assertion), expires_on=0)


class _Callers:
    """Which caller the server is serving right now, and every exchange it has asked for.

    The test writes `calling` between calls, and the stubbed `get_access_token` reads it: a
    module-level function, patchable only once for both callers. This file drives calls
    sequentially, so a plain value is enough and no contextvar is needed.
    """

    def __init__(self) -> None:
        self.calling: str = _ADA_SESSION_TOKEN
        self.exchanged: list[str] = []


@pytest.fixture
def callers(monkeypatch: pytest.MonkeyPatch) -> _Callers:
    """Entra's exchange, answering each caller's own assertion with each caller's own token."""
    callers = _Callers()

    async def get_obo_credential(
        _self: AzureProvider, *, user_assertion: str
    ) -> _StubOboCredential:
        callers.exchanged.append(user_assertion)
        return _StubOboCredential(user_assertion)

    monkeypatch.setattr(AzureProvider, "get_obo_credential", get_obo_credential)
    monkeypatch.setattr(
        "fastmcp.server.dependencies.get_access_token",
        lambda: AccessToken(token=callers.calling, client_id=_CLIENT_ID, scopes=["access_as_user"]),
    )
    return callers


def _bearer_token(request: httpx.Request) -> str:
    """The token one outbound Graph request presented, without its scheme.

    The cast is for httpx's `Headers.get`, whose default-carrying overload is annotated to return
    `Any`. A header value is a string or is missing.
    """
    return cast("str", request.headers.get("authorization", "")).removeprefix("Bearer ")


def _authorizations(route: respx.Route) -> list[str]:
    """The `Authorization` header of every Graph request this route was sent, in order.

    `respx.CallList` subclasses a bare `list`, so what it records arrives untyped. The cast states
    what respx puts in it rather than what its annotation promises.
    """
    return [call.request.headers["authorization"] for call in cast("Sequence[Call]", route.calls)]


def _profile_of_whoever_asked(request: httpx.Request) -> httpx.Response:
    """Graph as Graph behaves: the bearer token decides whose profile is returned."""
    profile = _PROFILES.get(_bearer_token(request))
    if profile is None:
        return httpx.Response(
            401,
            json={
                "error": {
                    "code": "InvalidAuthenticationToken",
                    "message": "Access token is empty or unknown.",
                }
            },
        )
    return httpx.Response(200, json=dict(profile))


@pytest.fixture
def graph() -> Iterator[respx.Route]:
    """`GET /me`, answered per bearer token, and recording every request it was sent."""
    with respx.mock(base_url=GRAPH_V1, assert_all_called=False) as router:
        yield router.get("/me").mock(side_effect=_profile_of_whoever_asked)


@pytest.fixture
def app() -> Starlette:
    """One composed app, registered once: the lifetime the hazard lives in."""
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
def server(app: Starlette) -> FastMCP[None]:
    return cast("FastMCP[None]", app.state.fastmcp_server)


@pytest.fixture
async def sessions(
    server: FastMCP[None],
) -> AsyncIterator[tuple[Client[FastMCPTransport], Client[FastMCPTransport]]]:
    """One MCP session per caller, both open at once: two people using one deployment.

    Both open before either closes, on purpose: two live sessions on one registration is the shape
    the hazard lives in. Nothing in the app forces that order. `FastMCPTransport` runs the server's
    lifespan per connection, and that lifespan closes only the On-Behalf-Of credentials, so the
    shared Graph transport outlives every session either way.
    """
    async with (
        Client(FastMCPTransport(server)) as ada,
        Client(FastMCPTransport(server)) as grace,
    ):
        yield ada, grace


def _structured(result: CallToolResult) -> Mapping[str, object]:
    data = cast("dict[str, object] | None", result.structured_content)
    assert data is not None, "the tool returned no structured content"
    return data


async def _get_me_as(
    callers: _Callers, session: Client[FastMCPTransport], session_token: str
) -> Mapping[str, object]:
    """Call the one tool in one caller's own session, as that caller."""
    callers.calling = session_token
    return _structured(await session.call_tool("get_me", {}))


class TestEveryCallerReachesGraphAsThemselves:
    async def test_two_callers_of_one_tool_send_two_different_bearer_tokens(
        self,
        sessions: tuple[Client[FastMCPTransport], Client[FastMCPTransport]],
        callers: _Callers,
        graph: respx.Route,
    ) -> None:
        """The assertion a cached Graph client cannot pass.

        One tool, one registration, two callers, and the header read back off each outbound request.
        Cached per registration, both requests carry Ada's token and this reads `[ada, ada]`.
        """
        ada, grace = sessions

        _ = await _get_me_as(callers, ada, _ADA_SESSION_TOKEN)
        _ = await _get_me_as(callers, grace, _GRACE_SESSION_TOKEN)

        sent = _authorizations(graph)

        assert sent == [
            f"Bearer {_graph_token_for(_ADA_SESSION_TOKEN)}",
            f"Bearer {_graph_token_for(_GRACE_SESSION_TOKEN)}",
        ], "each caller's Graph request has to carry that caller's own On-Behalf-Of token"
        assert sent[0] != sent[1], (
            "two callers sent Graph one token, so one of them read the other's Microsoft 365 data"
        )

    async def test_the_second_caller_reads_their_own_profile_and_not_the_first_caller_s(
        self,
        sessions: tuple[Client[FastMCPTransport], Client[FastMCPTransport]],
        callers: _Callers,
        graph: respx.Route,
    ) -> None:
        """The same failure stated as the incident rather than as the header.

        Graph answers whoever the token names, so a client cached across callers does not fail. It
        succeeds, and answers Grace with Ada's name, mail and Entra object id.
        """
        ada_session, grace_session = sessions

        ada = await _get_me_as(callers, ada_session, _ADA_SESSION_TOKEN)
        grace = await _get_me_as(callers, grace_session, _GRACE_SESSION_TOKEN)

        assert ada["user_id"] == _ADA["id"]
        assert grace["user_id"] == _GRACE["id"], (
            f"the second caller was answered with {grace['display_name']!r}, "
            + "which is another user's profile"
        )
        assert graph.calls.call_count == 2, "each call reaches Graph on its own"

    @pytest.mark.usefixtures("graph")
    async def test_each_caller_s_call_is_exchanged_for_a_token_of_its_own(
        self,
        sessions: tuple[Client[FastMCPTransport], Client[FastMCPTransport]],
        callers: _Callers,
    ) -> None:
        """The other half of the same lifetime, one layer up: the token is a dependency too.

        A token memoised at registration would leave the client per call and still send Ada's
        bearer for Grace. So this pins the exchange itself, one per call on that call's own
        assertion, rather than inferring it from the header the test above reads.
        """
        ada, grace = sessions

        _ = await _get_me_as(callers, ada, _ADA_SESSION_TOKEN)
        _ = await _get_me_as(callers, grace, _GRACE_SESSION_TOKEN)

        assert callers.exchanged == [_ADA_SESSION_TOKEN, _GRACE_SESSION_TOKEN]
