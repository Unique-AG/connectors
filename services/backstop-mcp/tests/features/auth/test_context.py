import pytest
from cryptography.fernet import Fernet
from mcp.server.auth.provider import AccessToken
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.backstop_client import BackstopCredentialSecret
from backstop_mcp.features.auth.context import BackstopAuthContext, NotConnectedError
from backstop_mcp.features.auth.credential_store import save_credential

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


async def _noop_revoke(_subject: str) -> None:
    return None


def _access_token(subject: str | None) -> AccessToken:
    return AccessToken(token="access-token", client_id="client-1", scopes=[], subject=subject)


def _auth(
    session_factory: async_sessionmaker[AsyncSession], key: bytes | None = None
) -> BackstopAuthContext:
    return BackstopAuthContext(
        session_factory=session_factory,
        encryption_key=key if key is not None else Fernet.generate_key(),
        revoke_tokens_for_subject=_noop_revoke,
    )


class TestCurrentCredential:
    """`BackstopAuthContext` is injected, not installed globally — each test builds its own."""

    @pytest.mark.asyncio
    async def test_resolves_stored_credential_for_authenticated_user(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, session_factory = db
        key = Fernet.generate_key()
        auth = _auth(session_factory, key)
        async with session_factory() as session:
            await save_credential(
                session,
                "user-context-1",
                BackstopCredentialSecret(username="ctx-bob.smith", api_token=SecretStr("token-1")),
                key,
            )
            await session.commit()
        monkeypatch.setattr(
            "backstop_mcp.features.auth.context.get_access_token",
            lambda: _access_token("user-context-1"),
        )

        credential = await auth.current_credential()

        assert credential.username == "ctx-bob.smith"
        assert credential.api_token.get_secret_value() == "token-1"

    @pytest.mark.asyncio
    async def test_raises_when_no_access_token(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, session_factory = db
        monkeypatch.setattr("backstop_mcp.features.auth.context.get_access_token", lambda: None)

        with pytest.raises(NotConnectedError):
            await _auth(session_factory).current_credential()

    @pytest.mark.asyncio
    async def test_raises_when_access_token_has_no_subject(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, session_factory = db
        monkeypatch.setattr(
            "backstop_mcp.features.auth.context.get_access_token", lambda: _access_token(None)
        )

        with pytest.raises(NotConnectedError):
            await _auth(session_factory).current_credential()

    @pytest.mark.asyncio
    async def test_raises_when_no_credential_stored_for_subject(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, session_factory = db
        monkeypatch.setattr(
            "backstop_mcp.features.auth.context.get_access_token",
            lambda: _access_token("user-with-no-credential"),
        )

        with pytest.raises(NotConnectedError):
            await _auth(session_factory).current_credential()


class TestRevokeCurrentSubjectTokens:
    @pytest.mark.asyncio
    async def test_revokes_for_the_active_subject(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, session_factory = db
        revoked: list[str] = []

        async def record(subject: str) -> None:
            revoked.append(subject)

        auth = BackstopAuthContext(
            session_factory=session_factory,
            encryption_key=Fernet.generate_key(),
            revoke_tokens_for_subject=record,
        )
        monkeypatch.setattr(
            "backstop_mcp.features.auth.context.get_access_token", lambda: _access_token("user-9")
        )

        await auth.revoke_current_subject_tokens()

        assert revoked == ["user-9"]

    @pytest.mark.asyncio
    async def test_is_a_noop_without_a_subject(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, session_factory = db
        revoked: list[str] = []

        async def record(subject: str) -> None:
            revoked.append(subject)

        auth = BackstopAuthContext(
            session_factory=session_factory,
            encryption_key=Fernet.generate_key(),
            revoke_tokens_for_subject=record,
        )
        monkeypatch.setattr("backstop_mcp.features.auth.context.get_access_token", lambda: None)

        await auth.revoke_current_subject_tokens()

        assert revoked == []


class TestActiveSubject:
    def test_returns_the_access_token_subject(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, session_factory = db
        monkeypatch.setattr(
            "backstop_mcp.features.auth.context.get_access_token",
            lambda: _access_token("user-9"),
        )

        assert _auth(session_factory).active_subject() == "user-9"
