from collections.abc import Iterator
import json
import logging
from typing import cast

from fastmcp import FastMCP
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from mcp_observability import RateLimitMiddleware
from mcp_observability import RedactRequestSecretsMiddleware
from mcp_observability import RedactToolCallSecretsMiddleware
import pytest
from starlette.middleware import Middleware

from kyckr_mcp.main import main

UPSTREAM_API_KEY = "kyckr-api-key-0123"
ZITADEL_CLIENT_SECRET = "zitadel-client-secret-0123"
ZITADEL_JWT_SIGNING_KEY = "zitadel-jwt-signing-key-0123456789"


pytestmark = pytest.mark.usefixtures("zitadel_discovery")


@pytest.fixture(autouse=True)
def deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every secret a deployment configures. The database password is URL-encoded."""
    monkeypatch.setenv("HOST", "0.0.0.0")
    monkeypatch.setenv("MCP_BASE_URL", "https://kyckr.example.com")
    monkeypatch.setenv("MCP_AUTH_MODE", "zitadel")
    # Not test_auth's issuer: FastMCP caches each issuer's discovery for the whole session.
    monkeypatch.setenv("ZITADEL_BASE_URL", "https://sign-in.example.com")
    monkeypatch.setenv("ZITADEL_CLIENT_ID", "kyckr")
    monkeypatch.setenv("ZITADEL_CLIENT_SECRET", ZITADEL_CLIENT_SECRET)
    monkeypatch.setenv("ZITADEL_JWT_SIGNING_KEY", ZITADEL_JWT_SIGNING_KEY)
    monkeypatch.setenv("UPSTREAM_API_KEY", UPSTREAM_API_KEY)
    monkeypatch.setenv("UPSTREAM_API_URL", "https://test-api.kyckr.com/v2")
    monkeypatch.setenv("DATABASE_URL", "postgresql://kyckr:db%2Fpassword-1@db:5432/kyckr")


@pytest.fixture(autouse=True)
def root_handlers() -> Iterator[None]:
    root = logging.getLogger()
    handlers = list(root.handlers)
    root.handlers = []
    yield
    root.handlers = handlers


type Runs = list[tuple[FastMCP, dict[str, object]]]


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> Runs:
    """The servers `FastMCP.run` was asked to serve, with their options, without serving them."""
    runs: Runs = []

    def run(mcp: FastMCP, **options: object) -> None:
        runs.append((mcp, options))

    monkeypatch.setattr(FastMCP, "run", run)
    return runs


def _rate_limited(mcp: FastMCP) -> bool:
    return any(isinstance(middleware, RateLimitMiddleware) for middleware in mcp.middleware)


@pytest.mark.usefixtures("served")
def test_redacts_every_secret_the_deployment_configures(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main()
    logging.getLogger("kyckr_mcp.tests").warning(
        "secrets %s %s %s db/password-1",
        UPSTREAM_API_KEY,
        ZITADEL_CLIENT_SECRET,
        ZITADEL_JWT_SIGNING_KEY,
    )

    lines = [
        cast(dict[str, object], json.loads(line)) for line in capsys.readouterr().err.splitlines()
    ]
    (line,) = [line for line in lines if line["context"] == "kyckr_mcp.tests"]
    assert line["msg"] == "secrets " + " ".join(["[Redacted]"] * 4)


def test_redacts_the_callers_token_around_every_request_and_tool_call(served: Runs) -> None:
    main()

    ((mcp, options),) = served
    http_middleware = cast(list[Middleware], options["middleware"])
    assert http_middleware[0].cls is RedactRequestSecretsMiddleware
    assert isinstance(mcp.middleware[0], RedactToolCallSecretsMiddleware)


def test_serves_beyond_loopback_with_zitadel_sign_in_by_default(
    monkeypatch: pytest.MonkeyPatch, served: Runs
) -> None:
    monkeypatch.delenv("MCP_AUTH_MODE")

    main()

    ((mcp, options),) = served
    assert isinstance(mcp.auth, OIDCProxy)
    assert options["host"] == "0.0.0.0"
    assert _rate_limited(mcp)


def test_serves_without_sign_in_or_rate_limit_on_loopback(
    monkeypatch: pytest.MonkeyPatch, served: Runs
) -> None:
    monkeypatch.setenv("MCP_AUTH_MODE", "none")
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("MCP_BASE_URL", "http://127.0.0.1:8000")

    main()

    ((mcp, options),) = served
    assert mcp.auth is None
    assert options["host"] == "127.0.0.1"
    assert not _rate_limited(mcp)


def test_refuses_to_serve_beyond_loopback_without_sign_in(
    monkeypatch: pytest.MonkeyPatch, served: Runs
) -> None:
    monkeypatch.setenv("MCP_AUTH_MODE", "none")

    with pytest.raises(RuntimeError, match="has no auth provider"):
        main()

    assert served == []
