"""The real app keeps the deployment's secrets and each caller's tokens out of every log line."""

import io
import json
import logging
import re
import uuid
from collections.abc import Iterator, Mapping
from typing import Protocol, cast
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from mcp.server.auth.provider import AccessToken
from mcp_observability import PinoJsonFormatter
from pydantic import SecretStr
from starlette.testclient import TestClient

from tests.conftest import DatabaseFixture
from tests.helpers import BASE_URL, sign_in_ok
from with_intelligence_mcp.app import create_app
from with_intelligence_mcp.db import transaction
from with_intelligence_mcp.features.auth.provider import WithIntelligenceOAuthProvider
from with_intelligence_mcp.features.auth.session_store import upsert_stored_wi_session
from with_intelligence_mcp.with_intelligence_client import WiSession

_MCP_ACCESS_TOKEN = "mcp-access-token-0123"
_WI_ACCESS_TOKEN = "wi-access-token-0123"
_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "authorization": f"Bearer {_MCP_ACCESS_TOKEN}",
}


class _HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...
    @property
    def text(self) -> str: ...


def _post(client: TestClient, body: dict[str, object], headers: Mapping[str, str]) -> _HttpResponse:
    return cast("_HttpResponse", client.post("/mcp", json=body, headers=dict(headers)))


def _redirected_logs() -> io.StringIO:
    logs = io.StringIO()
    (output,) = [
        cast("logging.StreamHandler[io.TextIOBase]", handler)
        for handler in logging.getLogger().handlers
        if isinstance(handler.formatter, PinoJsonFormatter)
    ]
    output.setStream(logs)
    return logs


def _lines(logs: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in logs.getvalue().splitlines()]


@pytest.fixture(autouse=True)
def stderr_restored() -> Iterator[None]:
    """`create_app` reuses the output handler, which these tests point at a buffer."""
    yield
    for handler in logging.getLogger().handlers:
        if isinstance(handler.formatter, PinoJsonFormatter):
            cast("logging.StreamHandler[io.TextIOBase]", handler).setStream(io.StringIO())


@pytest.fixture
def app_env(database_url: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """The app's environment, with error messages disclosed so a quoted secret reaches a line."""
    encryption_key = Fernet.generate_key().decode()
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DB_URL", database_url)
    monkeypatch.setenv("WITH_INTELLIGENCE_MCP_ENCRYPTION_KEY", encryption_key)
    monkeypatch.setenv("WITH_INTELLIGENCE_BASE_URL", BASE_URL)
    monkeypatch.setenv("ERROR_DETAILS_POLICY", "disclose")
    return encryption_key


class TestDeploymentSecrets:
    def test_the_encryption_key_and_database_password_are_redacted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        encryption_key = Fernet.generate_key().decode()
        monkeypatch.setenv("APP_ENV", "development")
        monkeypatch.setenv("DB_URL", "postgresql+asyncpg://app:wi-db-password-1@127.0.0.1:1/wi")
        monkeypatch.setenv("WITH_INTELLIGENCE_MCP_ENCRYPTION_KEY", encryption_key)
        _ = create_app()
        logs = _redirected_logs()

        logging.getLogger("with_intelligence_mcp.tests").warning(
            "secrets %s %s", encryption_key, "wi-db-password-1"
        )

        (line,) = _lines(logs)
        assert line["msg"] == "secrets [Redacted] [Redacted]"


class TestCallerSecrets:
    @respx.mock
    async def test_a_tool_error_quoting_the_tokens_logs_neither(
        self, db: DatabaseFixture, app_env: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, factory = db
        stored = WiSession(
            access_token=SecretStr(_WI_ACCESS_TOKEN), refresh_token=SecretStr("wi-refresh-0123")
        )
        async with transaction(factory) as session:
            subject = await upsert_stored_wi_session(
                session,
                f"subject-{uuid.uuid4()}",
                f"user-{uuid.uuid4().hex[:8]}",
                stored,
                app_env.encode(),
            )

        async def load_access_token(
            _self: WithIntelligenceOAuthProvider, token: str
        ) -> AccessToken:
            return AccessToken(token=token, client_id="client-1", scopes=[], subject=subject)

        monkeypatch.setattr(WithIntelligenceOAuthProvider, "load_access_token", load_access_token)
        _ = respx.get(f"{BASE_URL}/v3/funds/1").mock(
            side_effect=RuntimeError(f"rejected {_WI_ACCESS_TOKEN} for {_MCP_ACCESS_TOKEN}")
        )
        app = create_app()
        logs = _redirected_logs()

        with TestClient(app) as client:
            session_id = _initialized_session(client)
            response = _post(
                client,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "get_fund", "arguments": {"fund_id": 1}},
                },
                {**_HEADERS, "mcp-session-id": session_id},
            )

        assert '"isError":true' in response.text.replace(" ", ""), response.text
        (failed,) = [line for line in _lines(logs) if line["msg"] == "Tool call failed"]
        assert "rejected [Redacted] for [Redacted]" in json.dumps(failed["err"])
        logged = logs.getvalue()
        assert _WI_ACCESS_TOKEN not in logged
        assert _MCP_ACCESS_TOKEN not in logged

    @respx.mock
    @pytest.mark.usefixtures("app_env")
    async def test_the_login_password_is_redacted_from_what_the_sign_in_logs(self) -> None:
        password = "wi-login-password-0123"

        def sign_in(request: httpx.Request) -> httpx.Response:
            logging.getLogger("with_intelligence_mcp.tests").info(
                "sign-in body %s", request.content.decode()
            )
            return sign_in_ok()

        _ = respx.post(f"{BASE_URL}/v3/auth/sign-in").mock(side_effect=sign_in)
        app = create_app()
        logs = _redirected_logs()

        with TestClient(app) as client:
            status = _submit_login(
                client, username=f"analyst-{uuid.uuid4().hex[:8]}", password=password
            )

        assert status == 302
        (body,) = [
            line for line in _lines(logs) if line["context"] == "with_intelligence_mcp.tests"
        ]
        assert '"[Redacted]"' in str(body["msg"])
        assert password not in logs.getvalue()


def _initialized_session(client: TestClient) -> str:
    initialize = _post(
        client,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        _HEADERS,
    )
    assert initialize.status_code == 200, initialize.text
    session_id = initialize.headers["mcp-session-id"]
    initialized = _post(
        client,
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {**_HEADERS, "mcp-session-id": session_id},
    )
    assert initialized.status_code == 202, initialized.text
    return session_id


def _submit_login(client: TestClient, *, username: str, password: str) -> int:
    """Register a client, start the authorization and submit the real login form."""
    redirect_uri = "https://client.example/callback"
    registered = client.post(
        "/register",
        json={
            "redirect_uris": [redirect_uri],
            "client_name": "redaction",
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert registered.status_code == 201, registered.text
    authorized = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": cast("dict[str, str]", registered.json())["client_id"],
            "redirect_uri": redirect_uri,
            "code_challenge": "x" * 43,
            "code_challenge_method": "S256",
            "state": "state-1",
        },
        follow_redirects=False,
    )
    assert authorized.status_code == 302, authorized.text
    login_url = urlparse(authorized.headers["location"])
    form = client.get(f"{login_url.path}?{login_url.query}")
    csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', form.text)
    assert csrf_token is not None, form.text
    submitted = client.post(
        login_url.path,
        data={
            "request_id": parse_qs(login_url.query)["request_id"][0],
            "csrf_token": csrf_token.group(1),
            "username": username,
            "password": password,
        },
        follow_redirects=False,
    )
    return submitted.status_code
