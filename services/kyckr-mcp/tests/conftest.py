# mcp-scaffold-commit: 6474bb8667dc, timestamp: 2026-11-16T10:36:30+00:00

from collections.abc import AsyncGenerator, Awaitable, Callable
import os
from pathlib import Path
from typing import Protocol

from fastmcp import Client
from fastmcp import FastMCP
from fastmcp.client.client import CallToolResult
import httpx2
from mcp_configs import ServerSettings
from pydantic import AnyHttpUrl
import pytest

from kyckr_mcp.persistence import Persistence
from kyckr_mcp.upstream import UpstreamSettings
from tests.offline_server import build_server
from tests.offline_server import fake_upstream_settings
from tests.offline_server import open_fake_persistence

_ENV_PREFIXES = ("UPSTREAM_", "MCP_", "ZITADEL_", "PG_", "DB_", "LOGS_", "OTEL_")
_ENV_NAMES = {"DATABASE_URL", "HOST", "PORT", "LOG_LEVEL"}


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No setting of the developer's shell or `.env` reaches a test. A test sets what it needs."""
    for name in os.environ:
        if name in _ENV_NAMES or name.startswith(_ENV_PREFIXES):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def server_settings() -> ServerSettings:
    """Every field given, so neither the environment nor `.env` changes what the tests see."""
    return ServerSettings(
        host="127.0.0.1",
        port=8000,
        mcp_base_url=AnyHttpUrl("http://127.0.0.1:8000"),
        mcp_allowed_origins=[AnyHttpUrl("http://localhost:6274")],
    )


@pytest.fixture
def upstream_settings() -> UpstreamSettings:
    return fake_upstream_settings()


type CallTool = Callable[[str, dict[str, object]], Awaitable[CallToolResult]]


class FakeKyckr:
    """Records the requests the tools send and answers them with `handler`, or a 404."""

    def __init__(self) -> None:
        self.requests: list[httpx2.Request] = []
        self.handler: Callable[[httpx2.Request], httpx2.Response] = lambda _: httpx2.Response(404)

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.handler(request)

    def answers(self, body: object, status: int = 200) -> None:
        self.handler = lambda _: httpx2.Response(status, json=body)


@pytest.fixture
def kyckr() -> FakeKyckr:
    return FakeKyckr()


@pytest.fixture
def upstream_transport(kyckr: FakeKyckr) -> httpx2.MockTransport:
    """Stands in for Kyckr: answer through `kyckr.handler` or `kyckr.answers`."""
    return httpx2.MockTransport(kyckr)


@pytest.fixture
async def persistence() -> AsyncGenerator[Persistence]:
    async with open_fake_persistence() as fake:
        yield fake


@pytest.fixture
def server(
    upstream_settings: UpstreamSettings,
    persistence: Persistence,
    upstream_transport: httpx2.MockTransport,
) -> FastMCP:
    return build_server(upstream_settings, persistence, upstream_transport)


def caller(server: FastMCP) -> CallTool:
    async def call(name: str, arguments: dict[str, object]) -> CallToolResult:
        async with Client(server) as client:
            return await client.call_tool(name, arguments, raise_on_error=False)

    return call


@pytest.fixture
def call_tool(server: FastMCP) -> CallTool:
    """Calls a tool through a real FastMCP client, as the platform does."""
    return caller(server)


class CallToolWith(Protocol):
    def __call__(self, **settings: object) -> CallTool: ...


@pytest.fixture
def call_tool_with(
    upstream_settings: UpstreamSettings,
    persistence: Persistence,
    upstream_transport: httpx2.MockTransport,
) -> CallToolWith:
    """`call_tool` against a server whose upstream settings carry the given overrides."""

    def configured(**settings: object) -> CallTool:
        changed = upstream_settings.model_copy(update=settings)
        return caller(build_server(changed, persistence, upstream_transport))

    return configured


def structured(result: CallToolResult) -> dict[str, object]:
    assert result.structured_content is not None
    return dict(result.structured_content)


@pytest.fixture
def zitadel_discovery(monkeypatch: pytest.MonkeyPatch) -> None:
    """Answers the proxy's discovery requests without a network, for any issuer."""

    def get(url: str, **_: object) -> httpx2.Response:
        issuer = url.removesuffix("/.well-known/openid-configuration")
        configuration = {
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/v2/authorize",
            "token_endpoint": f"{issuer}/oauth/v2/token",
            "jwks_uri": f"{issuer}/oauth/v2/keys",
            "response_types_supported": ["code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["RS256"],
        }
        return httpx2.Response(200, json=configuration, request=httpx2.Request("GET", url))

    monkeypatch.setattr(httpx2, "get", get)
