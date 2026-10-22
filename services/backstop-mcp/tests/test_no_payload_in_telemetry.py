"""A canary planted in inputs, mocked Backstop bodies, the stored Backstop username, or a login
form never reaches a log or a span.

Each case also proves its code path ran (a specific record, a response field), so the absence
check is not vacuous.
"""

import base64
import logging
import re
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from typing import Protocol, cast

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from mcp.server.auth.provider import AccessToken
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.testclient import TestClient
from testcontainers.community.postgres import PostgresContainer

from backstop_mcp.app import create_app
from backstop_mcp.db import BackstopCredential, transaction
from backstop_mcp.features.auth import BackstopOAuthProvider
from tests.helpers import assert_canary_absent, logged_field
from tests.test_app import _set_app_env  # pyright: ignore[reportPrivateUsage]

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]

_API = "https://api.backstopsolutions.com"
_USERNAME_CANARY = "zq-canary-username"
_KEYED_PSEUDONYM = "hmac-sha256:"
_REDIRECT_URI = "https://client.example/callback"


class _HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...
    @property
    def text(self) -> str: ...
    def json(self) -> object: ...


def _post(client: TestClient, body: dict[str, object], headers: Mapping[str, str]) -> _HttpResponse:
    return cast("_HttpResponse", client.post("/mcp", json=body, headers=dict(headers)))


@asynccontextmanager
async def _connected_client(
    db: DatabaseFixture,
    postgres_container: PostgresContainer,
    monkeypatch: pytest.MonkeyPatch,
    exporter: InMemorySpanExporter,
    *,
    username: str,
) -> AsyncGenerator[tuple[TestClient, str]]:
    """The real app with an initialized MCP session whose stored credential is `username`."""
    key = Fernet.generate_key()
    subject = f"subject-{uuid.uuid4()}"
    system_user_id = f"su-{uuid.uuid4().hex[:12]}"
    _set_app_env(monkeypatch, postgres_container)
    monkeypatch.setenv("BACKSTOP_MCP_ENCRYPTION_KEY", key.decode())
    _engine, factory = db
    blob = Fernet(key).encrypt(f'{{"username":"{username}","api_token":"tok"}}'.encode())
    async with transaction(factory) as session:
        session.add(
            BackstopCredential(
                user_id=subject,
                backstop_username=username,
                encrypted_blob=blob,
                external_user_id=system_user_id,
                raw={
                    "id": system_user_id,
                    "name": "Service User",
                    "user_name": username,
                    "email": "svc@example.com",
                    "disabled": False,
                },
            )
        )

    async def load_access_token(_self: BackstopOAuthProvider, token: str) -> AccessToken:
        return AccessToken(token=token, client_id="client-1", scopes=["backstop"], subject=subject)

    monkeypatch.setattr(BackstopOAuthProvider, "load_access_token", load_access_token)
    app = create_app()
    with TestClient(app) as client:
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "authorization": "Bearer synthetic-access-token",
        }
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
            headers,
        )
        assert initialize.status_code == 200, initialize.text
        session_headers = {**headers, "mcp-session-id": initialize.headers["mcp-session-id"]}
        initialized = _post(
            client,
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            session_headers,
        )
        assert initialized.status_code == 202, initialized.text
        exporter.clear()
        yield client, session_headers["mcp-session-id"]


@pytest.fixture
async def mcp_client(
    db: DatabaseFixture,
    postgres_container: PostgresContainer,
    monkeypatch: pytest.MonkeyPatch,
    exporter: InMemorySpanExporter,
) -> AsyncIterator[tuple[TestClient, str]]:
    async with _connected_client(
        db, postgres_container, monkeypatch, exporter, username=f"svc-{uuid.uuid4().hex[:12]}"
    ) as connected:
        yield connected


@pytest.fixture
async def canary_user_client(
    db: DatabaseFixture,
    postgres_container: PostgresContainer,
    monkeypatch: pytest.MonkeyPatch,
    exporter: InMemorySpanExporter,
) -> AsyncIterator[tuple[TestClient, str]]:
    """A session whose stored Backstop username is the canary."""
    async with _connected_client(
        db, postgres_container, monkeypatch, exporter, username=_USERNAME_CANARY
    ) as connected:
        yield connected


@pytest.fixture
def app_client(
    postgres_container: PostgresContainer,
    monkeypatch: pytest.MonkeyPatch,
    exporter: InMemorySpanExporter,
) -> Iterator[TestClient]:
    """The real app, unauthenticated: what a browser on the login form talks to."""
    _set_app_env(monkeypatch, postgres_container)
    with TestClient(create_app()) as client:
        exporter.clear()
        yield client


def _call(
    client: TestClient,
    session_id: str,
    name: str,
    arguments: dict[str, object],
    *,
    expect_error: bool = False,
) -> str:
    response = _post(
        client,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
        {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
            "authorization": "Bearer synthetic-access-token",
            "mcp-session-id": session_id,
        },
    )
    assert response.status_code == 200, response.text
    is_error = '"isError": true' in response.text or '"isError":true' in response.text
    assert is_error is expect_error, response.text
    return response.text


def _assert_failed_at_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Proves the error path ran, so the absence check is not vacuous."""
    (failed,) = [record for record in caplog.records if record.message == "tool.call.failed"]
    assert failed.levelno == logging.WARNING


def _only_record(caplog: pytest.LogCaptureFixture, message: str) -> logging.LogRecord:
    (record,) = [record for record in caplog.records if record.message == message]
    return record


def _collection(*resources: dict[str, object]) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "data": list(resources),
            "included": [],
            "links": {"next": None},
            "meta": {"totalResourceCount": len(resources)},
        },
    )


class TestCanaryStaysOutOfTelemetry:
    @pytest.mark.asyncio
    @respx.mock
    async def test_search_people(
        self,
        mcp_client: tuple[TestClient, str],
        caplog: pytest.LogCaptureFixture,
        exporter: InMemorySpanExporter,
    ) -> None:
        canary = "zq-canary-people"
        caplog.set_level(logging.DEBUG)
        person = {
            "type": "people",
            "id": "p1",
            "attributes": {
                "name": canary,
                "firstName": canary,
                "lastName": canary,
                "email": f"{canary}@example.com",
                "email2": canary,
                "email3": canary,
            },
        }
        respx.get(url__regex=rf"{_API}/people").mock(
            return_value=httpx.Response(
                200,
                json={"data": [person], "links": {"next": None}, "meta": {"totalResourceCount": 1}},
            )
        )
        client, session_id = mcp_client
        exporter.clear()

        _call(
            client,
            session_id,
            "search_people",
            {
                "last_name": canary,
                "email": f"{canary}@example.com",
                "exclude_custom_fields": True,
            },
        )

        assert_canary_absent(caplog, exporter, canary)

    @pytest.mark.asyncio
    @respx.mock
    async def test_log_activity_note(
        self,
        mcp_client: tuple[TestClient, str],
        caplog: pytest.LogCaptureFixture,
        exporter: InMemorySpanExporter,
    ) -> None:
        canary = "zq-canary-note"
        caplog.set_level(logging.DEBUG)
        respx.post(f"{_API}/notes").mock(
            return_value=httpx.Response(
                201,
                json={
                    "data": {
                        "type": "notes",
                        "id": "n1",
                        "attributes": {"title": canary, "description": canary},
                    }
                },
            )
        )
        client, session_id = mcp_client
        exporter.clear()

        _call(
            client,
            session_id,
            "log_activity",
            {
                "activity": {
                    "kind": "note",
                    "search_type": "organizations",
                    "party_id": "org-1",
                    "title": canary,
                    "description": canary,
                }
            },
        )

        assert_canary_absent(caplog, exporter, canary)

    @pytest.mark.asyncio
    @respx.mock
    async def test_attach_file(
        self,
        mcp_client: tuple[TestClient, str],
        caplog: pytest.LogCaptureFixture,
        exporter: InMemorySpanExporter,
    ) -> None:
        canary = "zq-canary-file"
        caplog.set_level(logging.DEBUG)
        respx.post(f"{_API}/documents").mock(
            return_value=httpx.Response(
                201,
                json={
                    "data": {
                        "type": "documents",
                        "id": "d1",
                        "attributes": {"title": canary, "description": canary},
                    }
                },
            )
        )
        client, session_id = mcp_client
        exporter.clear()

        _call(
            client,
            session_id,
            "attach_file",
            {
                "activity": {
                    "kind": "document",
                    "search_type": "organizations",
                    "party_id": "org-1",
                    "file_name": f"{canary}.pdf",
                    "content": base64.b64encode(canary.encode()).decode(),
                }
            },
        )

        assert_canary_absent(caplog, exporter, canary)

    @pytest.mark.asyncio
    @respx.mock
    async def test_unknown_stage_name(
        self,
        mcp_client: tuple[TestClient, str],
        caplog: pytest.LogCaptureFixture,
        exporter: InMemorySpanExporter,
    ) -> None:
        canary = "zq-canary-stage"
        caplog.set_level(logging.DEBUG)
        respx.get(url__regex=rf"{_API}/opportunities/opp-1").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "type": "opportunities",
                        "id": "opp-1",
                        "attributes": {"name": canary, "description": canary},
                    }
                },
            )
        )
        respx.get(url__regex=rf"{_API}/opportunity-stages").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "type": "opportunity-stages",
                            "id": "st-1",
                            "attributes": {"name": "Prospect"},
                        }
                    ],
                    "links": {"next": None},
                },
            )
        )
        client, session_id = mcp_client
        exporter.clear()

        _call(
            client,
            session_id,
            "update_opportunity",
            {"opportunity": {"opportunity_id": "opp-1", "stage": canary}},
            expect_error=True,
        )

        _assert_failed_at_warning(caplog)
        assert_canary_absent(caplog, exporter, canary)

    @pytest.mark.asyncio
    async def test_invalid_argument_value(
        self,
        mcp_client: tuple[TestClient, str],
        caplog: pytest.LogCaptureFixture,
        exporter: InMemorySpanExporter,
    ) -> None:
        canary = "zq-canary-invalid"
        caplog.set_level(logging.DEBUG)
        client, session_id = mcp_client
        exporter.clear()

        _call(
            client,
            session_id,
            "parse_backstop_link",
            {"url": [canary]},
            expect_error=True,
        )

        _assert_failed_at_warning(caplog)
        assert_canary_absent(caplog, exporter, canary)

    @pytest.mark.asyncio
    @respx.mock
    async def test_backstop_error_body(
        self,
        mcp_client: tuple[TestClient, str],
        caplog: pytest.LogCaptureFixture,
        exporter: InMemorySpanExporter,
    ) -> None:
        canary = "zq-canary-backstop-error"
        caplog.set_level(logging.DEBUG)
        respx.post(f"{_API}/notes").mock(
            return_value=httpx.Response(
                422,
                json={
                    "errors": [
                        {
                            "status": "422",
                            "code": "ValidationException",
                            "title": f"Title {canary}",
                            "detail": f"Detail {canary}",
                        }
                    ]
                },
            )
        )
        client, session_id = mcp_client
        exporter.clear()

        _call(
            client,
            session_id,
            "log_activity",
            {
                "activity": {
                    "kind": "note",
                    "search_type": "organizations",
                    "party_id": "org-1",
                    "title": "Quarterly call",
                    "description": "Discussed the pipeline.",
                }
            },
            expect_error=True,
        )

        _assert_failed_at_warning(caplog)
        failed_request = _only_record(caplog, "backstop.request.failed")
        assert failed_request.__dict__["status_code"] == 422
        assert_canary_absent(caplog, exporter, canary)

    @pytest.mark.asyncio
    @respx.mock
    async def test_ambiguous_party_search_term(
        self,
        mcp_client: tuple[TestClient, str],
        caplog: pytest.LogCaptureFixture,
        exporter: InMemorySpanExporter,
    ) -> None:
        canary = "zq-canary-ambiguous"
        caplog.set_level(logging.DEBUG)
        respx.get(url__regex=rf"{_API}/quick-search").mock(
            return_value=_collection(
                {"type": "organizations", "id": "org-a", "attributes": {"name": f"{canary} A"}},
                {"type": "organizations", "id": "org-b", "attributes": {"name": f"{canary} B"}},
            )
        )
        client, session_id = mcp_client
        exporter.clear()

        response = _call(
            client,
            session_id,
            "get_tasks_for_party",
            {"search_type": "organizations", "search": canary},
        )

        assert "ambiguous" in response
        skipped = _only_record(caplog, "resolution.elicit.skipped")
        assert skipped.__dict__["candidates"] == 2
        assert logged_field(skipped, "query").startswith(_KEYED_PSEUDONYM)
        assert_canary_absent(caplog, exporter, canary)

    @pytest.mark.asyncio
    @respx.mock
    async def test_search_opportunities_representative(
        self,
        mcp_client: tuple[TestClient, str],
        caplog: pytest.LogCaptureFixture,
        exporter: InMemorySpanExporter,
    ) -> None:
        canary = "zq-canary-representative"
        caplog.set_level(logging.DEBUG)
        opportunities = respx.get(url__regex=rf"{_API}/opportunities(\?|$)").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "type": "opportunities",
                            "id": "opp-1",
                            "attributes": {"name": "Harbor Select", "isOpen": True},
                            "relationships": {
                                "representative": {"data": {"id": "u1", "type": "system-users"}}
                            },
                        }
                    ],
                    "included": [
                        {"type": "system-users", "id": "u1", "attributes": {"userName": canary}}
                    ],
                    "links": {"next": None},
                    "meta": {"totalResourceCount": 1},
                },
            )
        )
        respx.get(url__regex=rf"{_API}/opportunity-stages").mock(return_value=_collection())
        respx.get(url__regex=rf"{_API}/custom-field-definitions").mock(return_value=_collection())
        client, session_id = mcp_client
        exporter.clear()

        _call(
            client,
            session_id,
            "search_opportunities",
            {"representative": canary, "exclude_custom_fields": True},
        )

        assert opportunities.call_count == 1
        completed = _only_record(caplog, "tool.call.completed")
        assert logged_field(completed, "representative").startswith(_KEYED_PSEUDONYM)
        assert_canary_absent(caplog, exporter, canary)

    @pytest.mark.asyncio
    @respx.mock
    async def test_stored_backstop_username(
        self,
        canary_user_client: tuple[TestClient, str],
        caplog: pytest.LogCaptureFixture,
        exporter: InMemorySpanExporter,
    ) -> None:
        caplog.set_level(logging.DEBUG)
        respx.get(url__regex=rf"{_API}/people").mock(
            return_value=_collection(
                {"type": "people", "id": "p1", "attributes": {"name": "Alex Example"}}
            )
        )
        client, session_id = canary_user_client
        exporter.clear()

        _call(
            client,
            session_id,
            "search_people",
            {"last_name": "Example", "exclude_custom_fields": True},
        )

        request_records = [
            record for record in caplog.records if record.message.startswith("backstop.request.")
        ]
        assert request_records
        for record in request_records:
            assert logged_field(record, "username").startswith(_KEYED_PSEUDONYM)
        assert_canary_absent(caplog, exporter, _USERNAME_CANARY)

    @pytest.mark.asyncio
    @respx.mock
    async def test_rejected_login_username(
        self,
        app_client: TestClient,
        caplog: pytest.LogCaptureFixture,
        exporter: InMemorySpanExporter,
    ) -> None:
        canary = "zq-canary-login-rejected"
        api_token = "zq-canary-login-token-rejected"
        caplog.set_level(logging.DEBUG)
        respx.get(f"{_API}/system-info").mock(return_value=httpx.Response(401))
        pending = _pending_login(app_client)
        exporter.clear()

        response = _submit_login(app_client, pending, username=canary, api_token=api_token)

        assert response.status_code == 200
        assert "Invalid username or API token" in response.text
        rejected = _only_record(caplog, "auth.login.rejected")
        assert rejected.levelno == logging.INFO
        _assert_login_usernames_are_keyed(caplog)
        assert_canary_absent(caplog, exporter, canary)
        assert_canary_absent(caplog, exporter, api_token)
        assert_canary_absent(caplog, exporter, pending.csrf_token)

    @pytest.mark.asyncio
    @respx.mock
    async def test_successful_login_username(
        self,
        app_client: TestClient,
        caplog: pytest.LogCaptureFixture,
        exporter: InMemorySpanExporter,
    ) -> None:
        canary = f"zq-canary-login-{uuid.uuid4().hex[:8]}"
        api_token = "zq-canary-login-token-accepted"
        caplog.set_level(logging.DEBUG)
        respx.get(f"{_API}/system-info").mock(return_value=httpx.Response(200, json={}))
        respx.get(url__regex=rf"{_API}/system-users").mock(
            return_value=_collection(
                {
                    "type": "system-users",
                    "id": "su-login",
                    "attributes": {"name": "Alex Example", "userName": canary},
                }
            )
        )
        pending = _pending_login(app_client)
        exporter.clear()

        response = _submit_login(app_client, pending, username=canary, api_token=api_token)

        assert response.status_code == 302, response.text
        succeeded = _only_record(caplog, "auth.login.succeeded")
        assert succeeded.levelno == logging.INFO
        _assert_login_usernames_are_keyed(caplog)
        assert_canary_absent(caplog, exporter, canary)
        assert_canary_absent(caplog, exporter, api_token)
        assert_canary_absent(caplog, exporter, pending.csrf_token)

    @pytest.mark.asyncio
    @respx.mock
    async def test_run_report_name(
        self,
        mcp_client: tuple[TestClient, str],
        caplog: pytest.LogCaptureFixture,
        exporter: InMemorySpanExporter,
    ) -> None:
        canary = "zq-canary-report"
        caplog.set_level(logging.DEBUG)
        respx.get(url__regex=rf"{_API}/reports").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "type": "reports",
                            "id": "r1",
                            "attributes": {
                                "result": {
                                    "header": [{"name": "Company", "title": canary}],
                                    "values": [{"Company": canary}],
                                }
                            },
                        }
                    ],
                    "included": [],
                    "links": {},
                    "meta": {"totalResourceCount": 1},
                },
            )
        )
        client, session_id = mcp_client
        exporter.clear()

        _call(
            client,
            session_id,
            "run_report",
            {"report_name": canary, "as_of_date": "2026-08-31"},
        )

        fetched = _only_record(caplog, "reports.fetched")
        assert fetched.__dict__["row_count"] == 1
        assert logged_field(fetched, "report_name").startswith(_KEYED_PSEUDONYM)
        assert_canary_absent(caplog, exporter, canary)

    @pytest.mark.asyncio
    @respx.mock
    async def test_create_opportunity_landed_stage_name(
        self,
        mcp_client: tuple[TestClient, str],
        caplog: pytest.LogCaptureFixture,
        exporter: InMemorySpanExporter,
    ) -> None:
        canary = "zq-canary-landed-stage"
        caplog.set_level(logging.DEBUG)
        landed = {
            "data": {
                "type": "opportunities",
                "id": "opp-9",
                "attributes": {"name": "Harbor Select"},
                "relationships": {
                    "stage": {"data": {"id": "st-landed", "type": "opportunity-stages"}}
                },
            },
            "included": [
                {"type": "opportunity-stages", "id": "st-landed", "attributes": {"name": canary}}
            ],
        }
        respx.post(f"{_API}/opportunities").mock(return_value=httpx.Response(201, json=landed))
        respx.get(url__regex=rf"{_API}/opportunities/opp-9").mock(
            return_value=httpx.Response(200, json=landed)
        )
        respx.get(url__regex=rf"{_API}/opportunity-stages").mock(
            return_value=_collection(
                {"type": "opportunity-stages", "id": "st-1", "attributes": {"name": "Prospect"}}
            )
        )
        client, session_id = mcp_client
        exporter.clear()

        _call(
            client,
            session_id,
            "create_opportunity",
            {
                "opportunity": {
                    "name": "Harbor Select",
                    "currency_code": "USD",
                    "is_erisa": False,
                    "search_type": "contacts",
                    "party_id": "c-1",
                }
            },
        )

        created = _only_record(caplog, "opportunity_writes.opportunity.created")
        assert created.__dict__["stage_id"] == "st-landed"
        assert "stage" not in created.__dict__
        assert_canary_absent(caplog, exporter, canary)


class _PendingLogin:
    def __init__(self, *, request_id: str, csrf_token: str, cookie: str) -> None:
        self.request_id: str = request_id
        self.csrf_token: str = csrf_token
        self.cookie: str = cookie


def _pending_login(client: TestClient) -> _PendingLogin:
    """Register a client, start an authorization, and load the login form it redirects to.

    The CSRF cookie is `Secure` and the test client speaks http, so the cookie jar would not
    send it back: the cookie is carried by hand instead.
    """
    registered = cast(
        "_HttpResponse",
        client.post(
            "/register",
            json={
                "redirect_uris": [_REDIRECT_URI],
                "client_name": "Canary Client",
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
            },
        ),
    )
    assert registered.status_code == 201, registered.text
    client_id = cast("dict[str, object]", registered.json())["client_id"]
    authorized = cast(
        "_HttpResponse",
        client.get(
            "/authorize",
            params={
                "response_type": "code",
                "client_id": str(client_id),
                "redirect_uri": _REDIRECT_URI,
                "code_challenge": "c" * 43,
                "code_challenge_method": "S256",
                "state": "state-canary",
            },
            follow_redirects=False,
        ),
    )
    assert authorized.status_code == 302, authorized.text
    location = authorized.headers["location"]
    request_id_match = re.search(r"request_id=([^&]+)", location)
    assert request_id_match is not None, location
    form = cast("_HttpResponse", client.get(location, follow_redirects=False))
    assert form.status_code == 200, form.text
    csrf_match = re.search(r'name="csrf_token" value="([^"]+)"', form.text)
    assert csrf_match is not None, form.text
    cookie = form.headers["set-cookie"].split(";", 1)[0]
    return _PendingLogin(
        request_id=request_id_match.group(1), csrf_token=csrf_match.group(1), cookie=cookie
    )


def _submit_login(
    client: TestClient, pending: _PendingLogin, *, username: str, api_token: str
) -> _HttpResponse:
    return cast(
        "_HttpResponse",
        client.post(
            "/backstop/login",
            data={
                "request_id": pending.request_id,
                "username": username,
                "api_token": api_token,
                "csrf_token": pending.csrf_token,
            },
            headers={"cookie": pending.cookie},
            follow_redirects=False,
        ),
    )


def _assert_login_usernames_are_keyed(caplog: pytest.LogCaptureFixture) -> None:
    login_records = [
        record
        for record in caplog.records
        if record.message.startswith("auth.login.") and "username" in record.__dict__
    ]
    assert login_records
    for record in login_records:
        assert logged_field(record, "username").startswith(_KEYED_PSEUDONYM)
