"""A canary planted in inputs and mocked Backstop bodies never reaches a log or a span."""

import base64
import logging
import uuid
from collections.abc import AsyncIterator, Mapping
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
from tests.helpers import assert_canary_absent
from tests.test_app import _set_app_env  # pyright: ignore[reportPrivateUsage]

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]

_API = "https://api.backstopsolutions.com"


class _HttpResponse(Protocol):
    @property
    def status_code(self) -> int: ...
    @property
    def headers(self) -> Mapping[str, str]: ...
    @property
    def text(self) -> str: ...


def _post(client: TestClient, body: dict[str, object], headers: Mapping[str, str]) -> _HttpResponse:
    return cast("_HttpResponse", client.post("/mcp", json=body, headers=dict(headers)))


@pytest.fixture
async def mcp_client(
    db: DatabaseFixture,
    postgres_container: PostgresContainer,
    monkeypatch: pytest.MonkeyPatch,
    exporter: InMemorySpanExporter,
) -> AsyncIterator[tuple[TestClient, str]]:
    key = Fernet.generate_key()
    subject = f"subject-{uuid.uuid4()}"
    username = f"svc-{uuid.uuid4().hex[:12]}"
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


def _call(
    client: TestClient,
    session_id: str,
    name: str,
    arguments: dict[str, object],
    *,
    expect_error: bool = False,
) -> None:
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


def _assert_failed_at_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Proves the error path ran, so the absence check is not vacuous."""
    (failed,) = [record for record in caplog.records if record.message == "tool.call.failed"]
    assert failed.levelno == logging.WARNING


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
