"""Resolving and refreshing the caller's WI session, and what happens when it cannot be."""

import asyncio
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import select

from tests.conftest import DatabaseFixture
from with_intelligence_mcp.db import WithIntelligenceSession, read_session, transaction
from with_intelligence_mcp.features.auth import NotConnectedError, WithIntelligenceAuthContext
from with_intelligence_mcp.features.auth.session_store import (
    get_stored_wi_session,
    upsert_stored_wi_session,
)
from with_intelligence_mcp.with_intelligence_client import (
    AuthenticationRejected,
    Unreachable,
    WiSession,
)

KEY = Fernet.generate_key()


def _session(token: str, *, age: timedelta = timedelta(0)) -> WiSession:
    return WiSession(
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


async def _store(db: DatabaseFixture, stored: WiSession, *, username: str | None = None) -> str:
    _, factory = db
    async with transaction(factory) as session:
        return await upsert_stored_wi_session(
            session,
            str(uuid.uuid4()),
            username or f"ctx-{uuid.uuid4().hex[:8]}@example.invalid",
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
        subject = await _store(db, _session("held"))
        context, _ = _context(db)
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(subject), raising=True)
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


class TestRefresh:
    async def test_a_stale_session_is_refreshed_and_written_back(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The refresh token may rotate, so the row has to carry the new one."""
        _, factory = db
        subject = await _store(db, _session("old", age=timedelta(hours=2)))
        context, _ = _context(db)
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(subject), raising=True)

        async def refresh(_stale: WiSession) -> WiSession:
            return _session("rotated")

        refreshed = await context.refresh_session(refresh)
        assert refreshed.access_token.get_secret_value() == "rotated"
        async with read_session(factory) as session:
            stored = await get_stored_wi_session(session, subject, KEY)
        assert stored is not None
        assert stored.refresh_token.get_secret_value() == "refresh-rotated"

    async def test_a_session_another_replica_already_refreshed_is_not_refreshed_again(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """What the row lock buys: the loser of the race reads the winner's result."""
        subject = await _store(db, _session("fresh"))
        context, _ = _context(db)
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(subject), raising=True)
        calls: list[str] = []

        async def refresh(_stale: WiSession) -> WiSession:
            calls.append("refreshed")
            return _session("should-not-happen")

        current = await context.refresh_session(refresh)
        assert calls == []
        assert current.access_token.get_secret_value() == "fresh"

    async def test_a_rejected_fresh_session_is_refreshed(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        stale = _session("rejected")
        subject = await _store(db, stale)
        context, _ = _context(db)
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(subject), raising=True)

        async def refresh(_stale: WiSession) -> WiSession:
            return _session("refreshed")

        current = await context.refresh_session(refresh, stale.model_copy())
        assert current.access_token.get_secret_value() == "refreshed"

    async def test_http_refresh_does_not_hold_the_session_row_lock(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, factory = db
        subject = await _store(db, _session("old", age=timedelta(hours=2)))
        context, _ = _context(db)
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(subject), raising=True)
        started = asyncio.Event()
        release = asyncio.Event()
        refreshed = _session("refreshed")

        async def refresh(_stale: WiSession) -> WiSession:
            started.set()
            await release.wait()
            return refreshed

        refresh_task = asyncio.create_task(context.refresh_session(refresh))
        await started.wait()
        async with transaction(factory) as session:
            locked_subject = await asyncio.wait_for(
                session.scalar(
                    select(WithIntelligenceSession.user_id)
                    .where(WithIntelligenceSession.user_id == subject)
                    .with_for_update()
                ),
                timeout=0.2,
            )
        assert locked_subject == subject

        release.set()
        assert await refresh_task == refreshed

    async def test_concurrent_replicas_share_one_refresh(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        subject = await _store(db, _session("old", age=timedelta(hours=2)))
        first, _ = _context(db)
        second, _ = _context(db)
        monkeypatch.setattr(type(first), "current_subject", _fixed_subject(subject), raising=True)
        calls = 0

        async def refresh(_stale: WiSession) -> WiSession:
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return _session("refreshed")

        sessions = await asyncio.gather(
            first.refresh_session(refresh),
            second.refresh_session(refresh),
        )

        assert calls == 1
        assert {session.access_token.get_secret_value() for session in sessions} == {"refreshed"}

    async def test_concurrent_login_wins_over_a_successful_refresh(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, factory = db
        username = f"ctx-{uuid.uuid4().hex[:8]}@example.invalid"
        subject = await _store(
            db,
            _session("old", age=timedelta(hours=2)),
            username=username,
        )
        context, _ = _context(db)
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(subject), raising=True)
        started = asyncio.Event()
        release = asyncio.Event()

        async def refresh(_stale: WiSession) -> WiSession:
            started.set()
            await release.wait()
            return _session("refresh")

        refresh_task = asyncio.create_task(context.refresh_session(refresh))
        await started.wait()
        async with transaction(factory) as session:
            await upsert_stored_wi_session(
                session, str(uuid.uuid4()), username, _session("login"), KEY
            )
        release.set()

        result = await refresh_task

        assert result.access_token.get_secret_value() == "login"
        async with read_session(factory) as session:
            stored = await get_stored_wi_session(session, subject, KEY)
        assert stored is not None
        assert stored.access_token.get_secret_value() == "login"

    async def test_concurrent_login_prevents_revocation_after_a_rejected_refresh(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, factory = db
        username = f"ctx-{uuid.uuid4().hex[:8]}@example.invalid"
        stale = _session("old", age=timedelta(hours=2))
        subject = await _store(db, stale, username=username)
        context, revocations = _context(db)
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(subject), raising=True)
        started = asyncio.Event()
        release = asyncio.Event()

        async def refuse(_stale: WiSession) -> WiSession:
            started.set()
            await release.wait()
            raise AuthenticationRejected("rejected")

        refresh = asyncio.create_task(context.refresh_session(refuse, stale))
        await started.wait()
        async with transaction(factory) as session:
            await upsert_stored_wi_session(
                session, str(uuid.uuid4()), username, _session("login"), KEY
            )
        release.set()

        result = await refresh

        assert result.access_token.get_secret_value() == "login"
        assert revocations.subjects == []

    async def test_a_refused_refresh_revokes_the_callers_mcp_tokens(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The password is not stored, so a refused refresh requires another login."""
        _, factory = db
        subject = await _store(db, _session("dead", age=timedelta(hours=2)))
        revocations = Revocations()

        async def revoke(subject: str) -> None:
            async with transaction(factory) as session:
                locked_subject = await session.scalar(
                    select(WithIntelligenceSession.user_id)
                    .where(WithIntelligenceSession.user_id == subject)
                    .with_for_update()
                )
            assert locked_subject == subject
            await revocations(subject)

        context = WithIntelligenceAuthContext(
            session_factory=factory,
            encryption_key=KEY,
            revoke_tokens_for_subject=revoke,
        )
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(subject), raising=True)

        async def refuse(_stale: WiSession) -> WiSession:
            raise AuthenticationRejected("refresh token spent")

        with pytest.raises(NotConnectedError, match="could not be refreshed"):
            _ = await asyncio.wait_for(context.refresh_session(refuse), timeout=1)
        assert revocations.subjects == [subject]

    async def test_an_outage_does_not_revoke_the_callers_mcp_tokens(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, factory = db
        subject = await _store(db, _session("stale", age=timedelta(hours=2)))
        context, revocations = _context(db)
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(subject), raising=True)

        async def unavailable(_stale: WiSession) -> WiSession:
            raise Unreachable("WI is unavailable")

        with pytest.raises(Unreachable):
            _ = await context.refresh_session(unavailable)
        assert revocations.subjects == []
        async with read_session(factory) as session:
            stored = await get_stored_wi_session(session, subject, KEY)
        assert stored is not None

    async def test_refreshing_without_a_stored_session_is_reported_not_retried(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        context, _ = _context(db)
        monkeypatch.setattr(
            type(context), "current_subject", _fixed_subject(str(uuid.uuid4())), raising=True
        )

        async def refresh(_stale: WiSession) -> WiSession:
            return _session("x")

        with pytest.raises(NotConnectedError):
            _ = await context.refresh_session(refresh)


class TestAnUnreadableBlob:
    async def test_a_rotated_encryption_key_reads_as_not_connected(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Nothing can recover it, so the honest answer is to ask the user to reconnect."""
        _, factory = db
        subject = await _store(db, _session("orphaned"))
        other_key = Fernet.generate_key()
        context = WithIntelligenceAuthContext(
            session_factory=factory,
            encryption_key=other_key,
            revoke_tokens_for_subject=Revocations(),
        )
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(subject), raising=True)
        with pytest.raises(NotConnectedError, match="could not be read"):
            _ = await context.current_session()

    async def test_a_rotated_encryption_key_during_refresh_is_not_connected(
        self, db: DatabaseFixture, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _, factory = db
        subject = await _store(db, _session("orphaned"))
        context = WithIntelligenceAuthContext(
            session_factory=factory,
            encryption_key=Fernet.generate_key(),
            revoke_tokens_for_subject=Revocations(),
        )
        monkeypatch.setattr(type(context), "current_subject", _fixed_subject(subject), raising=True)

        async def refresh(_stale: WiSession) -> WiSession:
            return _session("unused")

        with pytest.raises(NotConnectedError, match="could not be read"):
            _ = await context.refresh_session(refresh)
