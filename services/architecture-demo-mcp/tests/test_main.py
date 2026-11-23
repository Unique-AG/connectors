from collections.abc import Iterator
import json
import logging
from typing import cast

from fastmcp import FastMCP
from mcp_observability import RedactRequestSecretsMiddleware
from mcp_observability import RedactToolCallSecretsMiddleware
import pytest
from starlette.middleware import Middleware

from architecture_demo_mcp.main import main

UPSTREAM_API_KEY = "tiingo-api-key-0123"
ZITADEL_CLIENT_SECRET = "zitadel-client-secret-0123"
ZITADEL_JWT_SIGNING_KEY = "zitadel-jwt-signing-key-0123456789"


pytestmark = pytest.mark.usefixtures("zitadel_discovery")


@pytest.fixture(autouse=True)
def deployment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every secret a deployment configures. The database password is URL-encoded."""
    monkeypatch.setenv("MCP_AUTH_MODE", "zitadel")
    # Not test_auth's issuer: FastMCP caches each issuer's discovery for the whole session.
    monkeypatch.setenv("ZITADEL_BASE_URL", "https://sign-in.example.com")
    monkeypatch.setenv("ZITADEL_CLIENT_ID", "architecture-demo")
    monkeypatch.setenv("ZITADEL_CLIENT_SECRET", ZITADEL_CLIENT_SECRET)
    monkeypatch.setenv("ZITADEL_JWT_SIGNING_KEY", ZITADEL_JWT_SIGNING_KEY)
    monkeypatch.setenv("UPSTREAM_API_KEY", UPSTREAM_API_KEY)
    monkeypatch.setenv("DATABASE_URL", "postgresql://demo:db%2Fpassword-1@db:5432/demo")
    monkeypatch.setenv("REDIS_URL", "redis://:redis-password-1@redis:6379/0")


@pytest.fixture(autouse=True)
def root_handlers() -> Iterator[None]:
    root = logging.getLogger()
    handlers = list(root.handlers)
    root.handlers = []
    yield
    root.handlers = handlers


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> list[tuple[FastMCP, dict[str, object]]]:
    """The servers `FastMCP.run` was asked to serve, with its options, without serving them."""
    runs: list[tuple[FastMCP, dict[str, object]]] = []

    def run(mcp: FastMCP, **options: object) -> None:
        runs.append((mcp, options))

    monkeypatch.setattr(FastMCP, "run", run)
    return runs


@pytest.mark.usefixtures("served")
def test_redacts_every_secret_the_deployment_configures(
    capsys: pytest.CaptureFixture[str],
) -> None:
    main()
    logging.getLogger("architecture_demo_mcp.tests").warning(
        "secrets %s %s %s db/password-1 redis-password-1",
        UPSTREAM_API_KEY,
        ZITADEL_CLIENT_SECRET,
        ZITADEL_JWT_SIGNING_KEY,
    )

    lines = [
        cast(dict[str, object], json.loads(line)) for line in capsys.readouterr().err.splitlines()
    ]
    (line,) = [line for line in lines if line["context"] == "architecture_demo_mcp.tests"]
    assert line["msg"] == "secrets " + " ".join(["[Redacted]"] * 5)


def test_redacts_the_callers_token_around_every_request_and_tool_call(
    served: list[tuple[FastMCP, dict[str, object]]],
) -> None:
    main()

    ((mcp, options),) = served
    http_middleware = cast(list[Middleware], options["middleware"])
    assert http_middleware[0].cls is RedactRequestSecretsMiddleware
    assert isinstance(mcp.middleware[0], RedactToolCallSecretsMiddleware)
