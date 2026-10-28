"""A canary in a tool's input or a mocked Backstop body never reaches a pino line or an exported
span. Each case also proves its code path ran, so the absence check is not vacuous."""

import hashlib
import io
import json
import logging
import re
import uuid
from collections.abc import AsyncGenerator, Iterator, Mapping
from contextlib import asynccontextmanager
from typing import Protocol, cast
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from mcp.server.auth.provider import AccessToken
from mcp_observability import PinoJsonFormatter
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from backstop_mcp.app import create_app
from backstop_mcp.db import BackstopCredential, transaction
from backstop_mcp.features.auth import BackstopOAuthProvider
from tests.helpers import resource
from tests.test_app import _set_app_env  # pyright: ignore[reportPrivateUsage]

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]

_API = "https://api.backstopsolutions.com"
_CANARY = "zq-canary-value"


class _HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...
    @property
    def text(self) -> str: ...


class _Session:
    def __init__(self, client: TestClient, session_id: str, logs: io.StringIO) -> None:
        self._client: TestClient = client
        self._session_id: str = session_id
        self._logs: io.StringIO = logs

    def call(self, name: str, arguments: dict[str, object], *, expect_error: bool) -> None:
        response = _post(
            self._client,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            {**_HEADERS, "mcp-session-id": self._session_id},
        )
        assert response.status_code == 200, response.text
        is_error = '"isError":true' in response.text.replace(" ", "")
        assert is_error is expect_error, response.text

    def lines(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self._logs.getvalue().splitlines()]

    def tool_call(self, message: str) -> dict[str, object]:
        (line,) = [line for line in self.lines() if line["msg"] == message]
        return line


_HEADERS = {
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "authorization": "Bearer synthetic-access-token",
}


def _post(client: TestClient, body: dict[str, object], headers: Mapping[str, str]) -> _HttpResponse:
    return cast("_HttpResponse", client.post("/mcp", json=body, headers=dict(headers)))


@asynccontextmanager
async def _connected(
    db: DatabaseFixture,
    postgres_container: PostgresContainer,
    monkeypatch: pytest.MonkeyPatch,
    *,
    username: str | None = None,
) -> AsyncGenerator[_Session]:
    """The real app at DEBUG with an initialized MCP session and a stored Backstop credential."""
    key = Fernet.generate_key()
    subject = f"subject-{uuid.uuid4()}"
    username = username or f"svc-{uuid.uuid4().hex[:12]}"
    _set_app_env(monkeypatch, postgres_container)
    monkeypatch.setenv("BACKSTOP_MCP_ENCRYPTION_KEY", key.decode())
    monkeypatch.setenv("LOG_LEVEL", "debug")
    _engine, factory = db
    blob = Fernet(key).encrypt(f'{{"username":"{username}","api_token":"tok"}}'.encode())
    async with transaction(factory) as session:
        session.add(
            BackstopCredential(
                user_id=subject,
                backstop_username=username,
                encrypted_blob=blob,
                external_user_id="su-1",
                raw={"id": "su-1", "name": "Service User", "user_name": username},
            )
        )

    async def load_access_token(_self: BackstopOAuthProvider, token: str) -> AccessToken:
        return AccessToken(token=token, client_id="client-1", scopes=["backstop"], subject=subject)

    monkeypatch.setattr(BackstopOAuthProvider, "load_access_token", load_access_token)
    app = create_app()
    logs = _redirected_logs()
    with TestClient(app) as client:
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
        yield _Session(client, session_id, logs)


def _redirected_logs() -> io.StringIO:
    logs = io.StringIO()
    (output,) = [
        cast("logging.StreamHandler[io.TextIOBase]", handler)
        for handler in logging.getLogger().handlers
        if isinstance(handler.formatter, PinoJsonFormatter)
    ]
    output.setStream(logs)
    return logs


@pytest.fixture
async def session(
    db: DatabaseFixture,
    postgres_container: PostgresContainer,
    monkeypatch: pytest.MonkeyPatch,
    exporter: InMemorySpanExporter,
) -> AsyncGenerator[_Session]:
    async with _connected(db, postgres_container, monkeypatch) as connected:
        exporter.clear()
        yield connected


@pytest.fixture
def stderr_restored() -> Iterator[None]:
    """`create_app` reuses the output handler, which this module points at a buffer."""
    yield
    for handler in logging.getLogger().handlers:
        if isinstance(handler.formatter, PinoJsonFormatter):
            cast("logging.StreamHandler[io.TextIOBase]", handler).setStream(io.StringIO())


def _assert_absent(session: _Session, exporter: InMemorySpanExporter) -> None:
    assert _CANARY not in json.dumps(session.lines())
    for span in exporter.get_finished_spans():
        assert _CANARY not in _span_text(span), span.name


def _span_text(span: ReadableSpan) -> str:
    return span.to_json()


def _tool_span(exporter: InMemorySpanExporter, tool: str) -> ReadableSpan:
    (span,) = [span for span in exporter.get_finished_spans() if span.name == f"tools/call {tool}"]
    return span


def _submit_login(client: TestClient, *, username: str, api_token: str) -> int:
    """Register a client, start the authorization and submit the real login form."""
    redirect_uri = "https://client.example/callback"
    registered = client.post(
        "/register",
        json={
            "redirect_uris": [redirect_uri],
            "client_name": "canary",
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
            "client_id": registered.json()["client_id"],
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
            "api_token": api_token,
        },
        follow_redirects=False,
    )
    return submitted.status_code


def _tasks(*attributes: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": [
                {"type": "tasks", "id": f"t{index}", "attributes": task}
                for index, task in enumerate(attributes)
            ],
            "links": {"next": None},
            "meta": {"totalResourceCount": len(attributes)},
        },
    )


_ORGANIZATION = {"data": {"type": "organizations", "id": "org-1", "attributes": {"name": "Acme"}}}
_CANARY_PSEUDONYM = f"sha256:{hashlib.sha256(_CANARY.encode()).hexdigest()}"


@pytest.mark.usefixtures("stderr_restored")
class TestCanaryStaysOutOfTelemetry:
    @respx.mock
    async def test_a_tool_argument_that_is_not_declared(
        self, session: _Session, exporter: InMemorySpanExporter
    ) -> None:
        respx.post(f"{_API}/people").mock(
            return_value=httpx.Response(
                201, json={"data": {"type": "people", "id": "p1", "attributes": {}}}
            )
        )
        respx.get(f"{_API}/people/p1").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"type": "people", "id": "p1", "attributes": {"name": _CANARY}}},
            )
        )

        session.call(
            "create_person",
            {"person": {"last_name": _CANARY, "first_name": _CANARY, "gender": "Female"}},
            expect_error=False,
        )

        completed = session.tool_call("Tool call completed")
        assert completed["tool"] == "create_person"
        (command,) = [
            s for s in exporter.get_finished_spans() if s.name == "CreatePersonCommand.run"
        ]
        assert command.attributes is not None
        assert command.attributes["result.id"] == "p1"
        assert str(command.attributes["input.person.last_name"]).startswith("sha256:")
        _assert_absent(session, exporter)

    async def test_an_invalid_argument(
        self, session: _Session, exporter: InMemorySpanExporter
    ) -> None:
        session.call(
            "get_tasks_for_party",
            {"search_type": "organizations", "party_id": "org-1", "status": _CANARY},
            expect_error=True,
        )

        failed = session.tool_call("Tool call failed")
        assert failed["log_level"] == "warn"
        assert failed["failed_fields"] == ["status (literal_error, got str)"]
        _assert_absent(session, exporter)

    @respx.mock
    async def test_a_tool_error_text(
        self, session: _Session, exporter: InMemorySpanExporter
    ) -> None:
        respx.get(url__regex=rf"{_API}/opportunities/opp-1").mock(
            return_value=httpx.Response(
                200,
                json={"data": {"type": "opportunities", "id": "opp-1", "attributes": {}}},
            )
        )
        respx.get(url__regex=rf"{_API}/opportunity-stages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"type": "opportunity-stages", "id": "st-1", "attributes": {"name": "Lead"}}
                    ],
                    "links": {"next": None},
                },
            )
        )

        session.call(
            "update_opportunity",
            {"opportunity": {"opportunity_id": "opp-1", "stage": _CANARY}},
            expect_error=True,
        )

        failed = session.tool_call("Tool call failed")
        assert failed["error_type"] == "ToolError"
        assert _tool_span(exporter, "update_opportunity").events
        _assert_absent(session, exporter)

    @respx.mock
    async def test_a_backstop_record_that_fails_our_schema(
        self, session: _Session, exporter: InMemorySpanExporter
    ) -> None:
        respx.get(url__regex=rf"{_API}/organizations/org-1").mock(
            return_value=httpx.Response(200, json=_ORGANIZATION)
        )
        respx.get(url__regex=rf"{_API}/tasks").mock(
            return_value=_tasks({"title": {_CANARY: _CANARY}})
        )

        session.call(
            "get_tasks_for_party",
            {"search_type": "organizations", "party_id": "org-1"},
            expect_error=True,
        )

        failed = session.tool_call("Tool call failed")
        assert failed["error_type"] == "BackstopResponseSchemaError"
        assert failed["failed_fields"] == [
            "data.0.attributes.title (string_type, got dict[str, str])"
        ]
        _assert_absent(session, exporter)

    @respx.mock
    async def test_a_backstop_error_body(
        self, session: _Session, exporter: InMemorySpanExporter
    ) -> None:
        respx.get(url__regex=rf"{_API}/organizations/org-1").mock(
            return_value=httpx.Response(200, json=_ORGANIZATION)
        )
        respx.get(url__regex=rf"{_API}/tasks").mock(
            return_value=httpx.Response(
                422,
                json={"errors": [{"detail": _CANARY, "title": _CANARY, "code": "invalid"}]},
            )
        )

        session.call(
            "get_tasks_for_party",
            {"search_type": "organizations", "party_id": "org-1"},
            expect_error=True,
        )

        assert session.tool_call("Tool call failed")["error_type"] == "BackstopApiError"
        request = session.tool_call("Backstop request failed")
        assert request["log_level"] == "warn"
        assert request["status_code"] == 422
        assert request["code"] == "invalid"
        assert request["error_count"] == 1
        assert request["route"] == "/tasks"
        (client_span,) = [
            span for span in exporter.get_finished_spans() if span.name == "backstop GET /tasks"
        ]
        assert client_span.attributes is not None
        assert client_span.attributes["http.response.status_code"] == 422
        _assert_absent(session, exporter)

    @respx.mock
    async def test_a_stored_backstop_username(
        self,
        db: DatabaseFixture,
        postgres_container: PostgresContainer,
        monkeypatch: pytest.MonkeyPatch,
        exporter: InMemorySpanExporter,
    ) -> None:
        respx.get(url__regex=rf"{_API}/organizations/org-1").mock(
            return_value=httpx.Response(200, json=_ORGANIZATION)
        )
        respx.get(url__regex=rf"{_API}/tasks").mock(return_value=_tasks())

        async with _connected(db, postgres_container, monkeypatch, username=_CANARY) as session:
            exporter.clear()
            session.call(
                "get_tasks_for_party",
                {"search_type": "organizations", "party_id": "org-1"},
                expect_error=False,
            )

            requests = [
                line for line in session.lines() if line["msg"] == "Sending Backstop request"
            ]
            assert requests
            assert {line["username"] for line in requests} == {_CANARY_PSEUDONYM}
            _assert_absent(session, exporter)

    @respx.mock
    @pytest.mark.usefixtures("db")
    @pytest.mark.parametrize("accepted", [False, True])
    async def test_the_login_form(
        self,
        postgres_container: PostgresContainer,
        monkeypatch: pytest.MonkeyPatch,
        exporter: InMemorySpanExporter,
        accepted: bool,
    ) -> None:
        _set_app_env(monkeypatch, postgres_container)
        monkeypatch.setenv("LOG_LEVEL", "debug")
        respx.get(f"{_API}/system-info").mock(
            return_value=httpx.Response(200 if accepted else 401, json={})
        )
        respx.get(url__regex=rf"{_API}/system-users").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        resource("su-1", "system-users", name="Service User", userName=_CANARY)
                    ],
                    "links": {"next": None},
                },
            )
        )
        app = create_app()
        logs = _redirected_logs()
        exporter.clear()

        with TestClient(app, base_url="https://backstop-mcp.example") as client:
            status = _submit_login(client, username=_CANARY, api_token=f"{_CANARY}-token")

        lines = [
            cast("dict[str, object]", json.loads(line)) for line in logs.getvalue().splitlines()
        ]
        message = "Login succeeded" if accepted else "Login rejected"
        assert status == (302 if accepted else 200)
        (line,) = [line for line in lines if line["msg"] == message]
        assert line["username"] == _CANARY_PSEUDONYM
        assert _CANARY not in json.dumps(lines)
        for span in exporter.get_finished_spans():
            assert _CANARY not in _span_text(span), span.name


# Logs only: the tracer provider keeps the redaction once any `create_app` installed it.
class TestErrorDetailsPolicy:
    @respx.mock
    @pytest.mark.usefixtures("stderr_restored")
    @pytest.mark.parametrize(("policy", "present"), [("redact", False), ("disclose", True)])
    async def test_a_bugs_exception_text_is_logged_only_when_disclosed(
        self,
        db: DatabaseFixture,
        postgres_container: PostgresContainer,
        monkeypatch: pytest.MonkeyPatch,
        exporter: InMemorySpanExporter,
        policy: str,
        present: bool,
    ) -> None:
        monkeypatch.setenv("ERROR_DETAILS_POLICY", policy)
        respx.get(url__regex=rf"{_API}/organizations/org-1").mock(
            return_value=httpx.Response(200, json=_ORGANIZATION)
        )
        respx.get(url__regex=rf"{_API}/tasks").mock(side_effect=RuntimeError(_CANARY))

        async with _connected(db, postgres_container, monkeypatch) as session:
            exporter.clear()
            session.call(
                "get_tasks_for_party",
                {"search_type": "organizations", "party_id": "org-1"},
                expect_error=True,
            )

            failed = session.tool_call("Tool call failed")
            assert failed["log_level"] == "error"
            assert "RuntimeError" in json.dumps(failed["err"])
            assert (_CANARY in json.dumps(failed["err"])) is present
            assert (_CANARY in json.dumps(session.lines())) is present
            if not present:
                _assert_absent(session, exporter)
