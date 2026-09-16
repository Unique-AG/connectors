"""Storing a With Intelligence session: keyed by username, locked for refresh."""

import uuid
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from pydantic import SecretStr

from tests.conftest import DatabaseFixture
from with_intelligence_mcp.db import read_session, transaction
from with_intelligence_mcp.features.auth.session_store import (
    find_subject_by_username,
    get_stored_wi_session,
    upsert_stored_wi_session,
)
from with_intelligence_mcp.with_intelligence_client import WiSession

KEY = Fernet.generate_key()


def _session(token: str, *, age: timedelta = timedelta(0)) -> WiSession:
    return WiSession(
        access_token=SecretStr(token),
        refresh_token=SecretStr(f"refresh-{token}"),
        issued_at=datetime.now(UTC) - age,
    )


def _username(tag: str) -> str:
    """Unique per test: the database is shared across the whole session."""
    return f"store-{tag}-{uuid.uuid4().hex[:8]}@example.invalid"


class TestSaving:
    async def test_a_saved_session_reads_back(self, db: DatabaseFixture) -> None:
        _, factory = db
        username = _username("read-back")
        async with transaction(factory) as session:
            subject = await upsert_stored_wi_session(
                session, str(uuid.uuid4()), username, _session("first"), KEY
            )
        async with read_session(factory) as session:
            stored = await get_stored_wi_session(session, subject, KEY)
        assert stored is not None
        assert stored.access_token.get_secret_value() == "first"
        assert stored.refresh_token.get_secret_value() == "refresh-first"

    async def test_the_issued_at_survives_the_round_trip(self, db: DatabaseFixture) -> None:
        """Freshness is inferred from it — With Intelligence sends no expiry."""
        _, factory = db
        issued = datetime.now(UTC) - timedelta(minutes=20)
        async with transaction(factory) as session:
            subject = await upsert_stored_wi_session(
                session,
                str(uuid.uuid4()),
                _username("issued-at"),
                WiSession(
                    access_token=SecretStr("a"),
                    refresh_token=SecretStr("r"),
                    issued_at=issued,
                ),
                KEY,
            )
        async with read_session(factory) as session:
            stored = await get_stored_wi_session(session, subject, KEY)
        assert stored is not None
        assert abs((stored.issued_at - issued).total_seconds()) < 1

    async def test_an_unknown_user_has_no_session(self, db: DatabaseFixture) -> None:
        _, factory = db
        async with read_session(factory) as session:
            assert await get_stored_wi_session(session, str(uuid.uuid4()), KEY) is None


class TestReconnecting:
    async def test_a_second_login_keeps_the_same_subject(self, db: DatabaseFixture) -> None:
        """Otherwise reconnecting would orphan the user's MCP tokens and history."""
        _, factory = db
        username = _username("same-id")
        async with transaction(factory) as session:
            first = await upsert_stored_wi_session(
                session, str(uuid.uuid4()), username, _session("old"), KEY
            )
        async with transaction(factory) as session:
            second = await upsert_stored_wi_session(
                session, str(uuid.uuid4()), username, _session("new"), KEY
            )
        assert first == second

    async def test_a_second_login_replaces_the_session(self, db: DatabaseFixture) -> None:
        _, factory = db
        username = _username("replace")
        async with transaction(factory) as session:
            subject = await upsert_stored_wi_session(
                session, str(uuid.uuid4()), username, _session("old"), KEY
            )
        async with transaction(factory) as session:
            _ = await upsert_stored_wi_session(
                session, str(uuid.uuid4()), username, _session("new"), KEY
            )
        async with read_session(factory) as session:
            stored = await get_stored_wi_session(session, subject, KEY)
        assert stored is not None
        assert stored.access_token.get_secret_value() == "new"

    async def test_find_subject_locates_a_returning_user(self, db: DatabaseFixture) -> None:
        _, factory = db
        username = _username("find")
        async with transaction(factory) as session:
            subject = await upsert_stored_wi_session(
                session, str(uuid.uuid4()), username, _session("t"), KEY
            )
        async with read_session(factory) as session:
            assert await find_subject_by_username(session, username) == subject

    async def test_find_subject_is_none_for_a_new_username(self, db: DatabaseFixture) -> None:
        _, factory = db
        async with read_session(factory) as session:
            assert await find_subject_by_username(session, _username("absent")) is None
