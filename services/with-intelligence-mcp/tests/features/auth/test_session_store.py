"""Storing a vendor session: keyed by username, locked for renewal."""

import uuid
from datetime import UTC, datetime, timedelta

from cryptography.fernet import Fernet
from pydantic import SecretStr

from tests.conftest import DatabaseFixture
from with_intelligence_mcp.db import read_session, transaction
from with_intelligence_mcp.features.auth.session_store import (
    find_user_id_by_username,
    get_session,
    lock_session,
    replace_session,
    save_session,
)
from with_intelligence_mcp.with_intelligence_client import VendorSession

KEY = Fernet.generate_key()


def _session(token: str, *, age: timedelta = timedelta(0)) -> VendorSession:
    return VendorSession(
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
            user_id = await save_session(
                session, str(uuid.uuid4()), username, _session("first"), KEY
            )
        async with read_session(factory) as session:
            stored = await get_session(session, user_id, KEY)
        assert stored is not None
        assert stored.access_token.get_secret_value() == "first"
        assert stored.refresh_token.get_secret_value() == "refresh-first"

    async def test_the_issued_at_survives_the_round_trip(self, db: DatabaseFixture) -> None:
        """Freshness is inferred from it — the vendor sends no expiry."""
        _, factory = db
        issued = datetime.now(UTC) - timedelta(minutes=20)
        async with transaction(factory) as session:
            user_id = await save_session(
                session,
                str(uuid.uuid4()),
                _username("issued-at"),
                VendorSession(
                    access_token=SecretStr("a"),
                    refresh_token=SecretStr("r"),
                    issued_at=issued,
                ),
                KEY,
            )
        async with read_session(factory) as session:
            stored = await get_session(session, user_id, KEY)
        assert stored is not None
        assert abs((stored.issued_at - issued).total_seconds()) < 1

    async def test_an_unknown_user_has_no_session(self, db: DatabaseFixture) -> None:
        _, factory = db
        async with read_session(factory) as session:
            assert await get_session(session, str(uuid.uuid4()), KEY) is None


class TestReconnecting:
    async def test_a_second_login_keeps_the_same_user_id(self, db: DatabaseFixture) -> None:
        """Otherwise reconnecting would orphan the user's MCP tokens and history."""
        _, factory = db
        username = _username("same-id")
        async with transaction(factory) as session:
            first = await save_session(session, str(uuid.uuid4()), username, _session("old"), KEY)
        async with transaction(factory) as session:
            second = await save_session(session, str(uuid.uuid4()), username, _session("new"), KEY)
        assert first == second

    async def test_a_second_login_replaces_the_session(self, db: DatabaseFixture) -> None:
        _, factory = db
        username = _username("replace")
        async with transaction(factory) as session:
            user_id = await save_session(session, str(uuid.uuid4()), username, _session("old"), KEY)
        async with transaction(factory) as session:
            _ = await save_session(session, str(uuid.uuid4()), username, _session("new"), KEY)
        async with read_session(factory) as session:
            stored = await get_session(session, user_id, KEY)
        assert stored is not None
        assert stored.access_token.get_secret_value() == "new"

    async def test_find_user_id_locates_a_returning_user(self, db: DatabaseFixture) -> None:
        _, factory = db
        username = _username("find")
        async with transaction(factory) as session:
            user_id = await save_session(session, str(uuid.uuid4()), username, _session("t"), KEY)
        async with read_session(factory) as session:
            assert await find_user_id_by_username(session, username) == user_id

    async def test_find_user_id_is_none_for_a_new_username(self, db: DatabaseFixture) -> None:
        _, factory = db
        async with read_session(factory) as session:
            assert await find_user_id_by_username(session, _username("absent")) is None


class TestRenewal:
    async def test_a_locked_read_returns_the_stored_session(self, db: DatabaseFixture) -> None:
        _, factory = db
        async with transaction(factory) as session:
            user_id = await save_session(
                session, str(uuid.uuid4()), _username("lock"), _session("held"), KEY
            )
        async with transaction(factory) as session:
            locked = await lock_session(session, user_id, KEY)
        assert locked is not None
        assert locked.access_token.get_secret_value() == "held"

    async def test_locking_an_absent_row_is_none_not_an_error(self, db: DatabaseFixture) -> None:
        _, factory = db
        async with transaction(factory) as session:
            assert await lock_session(session, str(uuid.uuid4()), KEY) is None

    async def test_a_renewed_session_is_written_back(self, db: DatabaseFixture) -> None:
        """The refresh token may rotate, so the row is rewritten rather than written once."""
        _, factory = db
        async with transaction(factory) as session:
            user_id = await save_session(
                session, str(uuid.uuid4()), _username("rotate"), _session("old"), KEY
            )
        async with transaction(factory) as session:
            await replace_session(session, user_id, _session("rotated"), KEY)
        async with read_session(factory) as session:
            stored = await get_session(session, user_id, KEY)
        assert stored is not None
        assert stored.refresh_token.get_secret_value() == "refresh-rotated"

    async def test_replacing_an_absent_row_is_a_no_op(self, db: DatabaseFixture) -> None:
        _, factory = db
        async with transaction(factory) as session:
            await replace_session(session, str(uuid.uuid4()), _session("x"), KEY)
