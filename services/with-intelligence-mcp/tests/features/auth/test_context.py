"""Resolving and renewing the caller's vendor session, and what happens when it cannot be."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from tests.conftest import DatabaseFixture
from with_intelligence_mcp.db import read_session, transaction
from with_intelligence_mcp.features.auth import NotConnectedError, WithIntelligenceAuthContext
from with_intelligence_mcp.features.auth.session_store import get_session, save_session
from with_intelligence_mcp.with_intelligence_client import VendorSession

KEY = Fernet.generate_key()


def _session(token: str, *, age: timedelta = timedelta(0)) -> VendorSession:
    return VendorSession(
        access_token=SecretStr(token),
        refresh_token=SecretStr(f"refresh-{token}"),
        issued_at=datetime.now(UTC) - age,
    )


def _fixed_subject(subject: str) -> Callable[[WithIntelligenceAuthContext], str]:
    """Stands in for the access token FastMCP would have validated for a real request."""

    def current_subject(_self: WithIntelligenceAuthContext) -> str:
        return subject

    return current_subject


class Revocations:
    def __init__(self) -> None:
        self.subjects: list[str] = []

    async def __call__(self, subject: str) -> None:
        self.subjects.append(subject)


def _context(
    db: DatabaseFixture, revocations: Revocations | None = None
) -> tuple[WithIntelligenceAuthContext, Revocations]:
    _, factory = db
    recorder = revocations or Revocations()
    return (
        WithIntelligenceAuthContext(
            session_factory=factory, encryption_key=KEY, revoke_tokens_for_subject=recorder
        ),
        recorder,
    )


async def _store(db: DatabaseFixture, stored: VendorSession) -> str:
    _, factory = db
    async with transaction(factory) as session:
        return await save_session(
            session,
            str(uuid.uuid4()),
            f"ctx-{uuid.uuid4().hex[:8]}@example.invalid",
            stored,
            KEY,
        )


class TestOutsideARequest:
    async def test_an_unauthenticated_caller_is_told_to_connect(self, db: DatabaseFixture) -> None:
        """No access token is active outside a request — the same shape as not being logged in."""
        context, _ = _context(db)
        with pytest.raises(NotConnectedError, match="complete the login flow"):
            _ = await context.current_session()

    def test_the_subject_is_none_outside_a_request(self, db: DatabaseFixture) -> None:
        context, _ = _context(db)
        assert context.current_subject() is None


class TestReadingTheStoredSession:
    async def test_a_stored_session_is_returned_for_its_subject(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        user_id = await _store(db, _session("held"))
        context, _ = _context(db)
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(user_id), raising=True)
        current = await context.current_session()
        assert current.access_token.get_secret_value() == "held"

    async def test_a_subject_with_no_row_is_told_to_reconnect(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        context, _ = _context(db)
        monkeypatch.setattr(
            type(context), "current_subject", _fixed_subject(str(uuid.uuid4())), raising=True
        )
        with pytest.raises(NotConnectedError, match="please reconnect"):
            _ = await context.current_session()


class TestRenewal:
    async def test_a_stale_session_is_renewed_and_written_back(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The refresh token may rotate, so the row has to carry the new one."""
        _, factory = db
        user_id = await _store(db, _session("old", age=timedelta(hours=2)))
        context, _ = _context(db)
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(user_id), raising=True)

        async def renew(_stale: VendorSession) -> VendorSession:
            return _session("rotated")

        renewed = await context.renew_session(renew)
        assert renewed.access_token.get_secret_value() == "rotated"
        async with read_session(factory) as session:
            stored = await get_session(session, user_id, KEY)
        assert stored is not None
        assert stored.refresh_token.get_secret_value() == "refresh-rotated"

    async def test_a_session_another_replica_already_renewed_is_not_renewed_again(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What the row lock buys: the loser of the race reads the winner's result."""
        user_id = await _store(db, _session("fresh"))
        context, _ = _context(db)
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(user_id), raising=True)
        calls: list[str] = []

        async def renew(_stale: VendorSession) -> VendorSession:
            calls.append("renewed")
            return _session("should-not-happen")

        current = await context.renew_session(renew)
        assert calls == []
        assert current.access_token.get_secret_value() == "fresh"

    async def test_a_refused_renewal_revokes_the_callers_mcp_tokens(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no stored password there is nothing to retry with, so the client must re-login."""
        user_id = await _store(db, _session("dead", age=timedelta(hours=2)))
        context, revocations = _context(db)
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(user_id), raising=True)

        async def refuse(_stale: VendorSession) -> VendorSession:
            raise RuntimeError("refresh token spent")

        with pytest.raises(NotConnectedError, match="could not be renewed"):
            _ = await context.renew_session(refuse)
        assert revocations.subjects == [user_id]

    async def test_renewing_without_a_stored_session_is_reported_not_retried(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        context, _ = _context(db)
        monkeypatch.setattr(
            type(context), "current_subject", _fixed_subject(str(uuid.uuid4())), raising=True
        )

        async def renew(_stale: VendorSession) -> VendorSession:
            return _session("x")

        with pytest.raises(NotConnectedError):
            _ = await context.renew_session(renew)


class TestAnUnreadableBlob:
    async def test_a_rotated_encryption_key_reads_as_not_connected(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing can recover it, so the honest answer is to ask the user to reconnect."""
        _, factory = db
        user_id = await _store(db, _session("orphaned"))
        other_key = Fernet.generate_key()
        context = WithIntelligenceAuthContext(
            session_factory=factory,
            encryption_key=other_key,
            revoke_tokens_for_subject=Revocations(),
        )
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(user_id), raising=True)
        with pytest.raises(NotConnectedError, match="could not be read"):
            _ = await context.current_session()
