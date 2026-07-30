import os

import httpx
import pytest
import respx
from mcp.server.auth.provider import AccessToken
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.auth import context as auth_context
from backstop_mcp.auth.context import NotConnectedError
from backstop_mcp.auth.credential_store import save_credential
from backstop_mcp.auth.crypto import BackstopCredentialSecret
from backstop_mcp.backstop_client import BackstopAuthError
from backstop_mcp.tools.system_info import get_system_info

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]

_BASE_URL = "https://example.backstopsolutions.com"


async def _connect_user(db: DatabaseFixture, subject: str, username: str, api_token: str) -> bytes:
    _, factory = db
    key = os.urandom(32)
    auth_context.configure(
        auth_context.BackstopAuthContext(session_factory=factory, encryption_key=key)
    )
    async with factory() as session:
        await save_credential(
            session,
            subject,
            BackstopCredentialSecret(username=username, api_token=SecretStr(api_token)),
            key,
        )
        await session.commit()
    return key


class TestGetSystemInfo:
    @pytest.mark.asyncio
    @respx.mock
    async def test_returns_backstop_response_for_connected_user(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _connect_user(db, "user-tool-1", "tool-bob.smith", "token-1")
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: _fake_access_token("user-tool-1"),
        )
        monkeypatch.setenv("BACKSTOP_BASE_URL", _BASE_URL)
        respx.get(f"{_BASE_URL}/system-info").mock(
            return_value=httpx.Response(200, json={"version": "1.0"})
        )

        result = await get_system_info()

        assert result == {"version": "1.0"}

    @pytest.mark.asyncio
    async def test_raises_not_connected_when_no_credential(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, factory = db
        auth_context.configure(
            auth_context.BackstopAuthContext(session_factory=factory, encryption_key=os.urandom(32))
        )
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: _fake_access_token("user-never-connected"),
        )

        with pytest.raises(NotConnectedError):
            await get_system_info()

    @pytest.mark.asyncio
    @respx.mock
    async def test_raises_backstop_auth_error_when_credential_revoked(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        await _connect_user(db, "user-tool-2", "tool-carol.diaz", "revoked-token")
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: _fake_access_token("user-tool-2"),
        )
        monkeypatch.setenv("BACKSTOP_BASE_URL", _BASE_URL)
        respx.get(f"{_BASE_URL}/system-info").mock(return_value=httpx.Response(401))

        with pytest.raises(BackstopAuthError):
            await get_system_info()


def _fake_access_token(subject: str) -> AccessToken:
    return AccessToken(token="access-token", client_id="client-1", scopes=[], subject=subject)
