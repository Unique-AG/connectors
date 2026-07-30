import os

import pytest
from mcp.server.auth.provider import AccessToken
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.auth import context as auth_context
from backstop_mcp.auth.context import NotConnectedError, get_current_backstop_credential
from backstop_mcp.auth.credential_store import save_credential
from backstop_mcp.auth.crypto import BackstopCredentialSecret

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


def _access_token(subject: str | None) -> AccessToken:
    return AccessToken(token="access-token", client_id="client-1", scopes=[], subject=subject)


class TestGetCurrentBackstopCredential:
    @pytest.mark.asyncio
    async def test_resolves_stored_credential_for_authenticated_user(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, factory = db
        key = os.urandom(32)
        auth_context.configure(
            auth_context.BackstopAuthContext(session_factory=factory, encryption_key=key)
        )
        async with factory() as session:
            await save_credential(
                session,
                "user-context-1",
                BackstopCredentialSecret(username="ctx-bob.smith", api_token=SecretStr("token-1")),
                key,
            )
            await session.commit()
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: _access_token("user-context-1"),
        )

        credential = await get_current_backstop_credential()

        assert credential.username == "ctx-bob.smith"
        assert credential.api_token.get_secret_value() == "token-1"

    @pytest.mark.asyncio
    async def test_raises_when_no_access_token(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, factory = db
        auth_context.configure(
            auth_context.BackstopAuthContext(session_factory=factory, encryption_key=os.urandom(32))
        )
        monkeypatch.setattr("backstop_mcp.auth.context.get_access_token", lambda: None)

        with pytest.raises(NotConnectedError):
            await get_current_backstop_credential()

    @pytest.mark.asyncio
    async def test_raises_when_access_token_has_no_subject(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, factory = db
        auth_context.configure(
            auth_context.BackstopAuthContext(session_factory=factory, encryption_key=os.urandom(32))
        )
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token", lambda: _access_token(None)
        )

        with pytest.raises(NotConnectedError):
            await get_current_backstop_credential()

    @pytest.mark.asyncio
    async def test_raises_when_no_credential_stored_for_subject(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, factory = db
        auth_context.configure(
            auth_context.BackstopAuthContext(session_factory=factory, encryption_key=os.urandom(32))
        )
        monkeypatch.setattr(
            "backstop_mcp.auth.context.get_access_token",
            lambda: _access_token("user-with-no-credential"),
        )

        with pytest.raises(NotConnectedError):
            await get_current_backstop_credential()
