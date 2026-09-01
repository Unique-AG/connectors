"""Storing a credential: keyed by username, so a returning user keeps their id."""

import uuid

from cryptography.fernet import Fernet
from pydantic import SecretStr

from tests.conftest import DatabaseFixture
from with_intelligence_mcp.db import read_session, transaction
from with_intelligence_mcp.features.auth.credential_store import (
    find_user_id_by_username,
    get_credential,
    save_credential,
)
from with_intelligence_mcp.with_intelligence_client import VendorCredential

KEY = Fernet.generate_key()


def _credential(username: str, password: str = "pw") -> VendorCredential:
    return VendorCredential(username=username, password=SecretStr(password))


def _username(tag: str) -> str:
    """Unique per test: the database is shared across the whole session."""
    return f"store-{tag}-{uuid.uuid4().hex[:8]}@example.invalid"


class TestSaving:
    async def test_a_saved_credential_reads_back(self, db: DatabaseFixture) -> None:
        _, factory = db
        username = _username("read-back")
        async with transaction(factory) as session:
            user_id = await save_credential(
                session, str(uuid.uuid4()), _credential(username, "first-pw"), KEY
            )
        async with read_session(factory) as session:
            stored = await get_credential(session, user_id, KEY)
        assert stored is not None
        assert stored.password.get_secret_value() == "first-pw"

    async def test_an_unknown_user_has_no_credential(self, db: DatabaseFixture) -> None:
        _, factory = db
        async with read_session(factory) as session:
            assert await get_credential(session, str(uuid.uuid4()), KEY) is None


class TestReconnecting:
    async def test_a_second_login_keeps_the_same_user_id(self, db: DatabaseFixture) -> None:
        """Otherwise a password change would orphan the user's tokens and history."""
        _, factory = db
        username = _username("same-id")
        async with transaction(factory) as session:
            first = await save_credential(
                session, str(uuid.uuid4()), _credential(username, "old-pw"), KEY
            )
        async with transaction(factory) as session:
            second = await save_credential(
                session, str(uuid.uuid4()), _credential(username, "new-pw"), KEY
            )
        assert first == second

    async def test_a_second_login_replaces_the_password(self, db: DatabaseFixture) -> None:
        _, factory = db
        username = _username("replace")
        async with transaction(factory) as session:
            user_id = await save_credential(
                session, str(uuid.uuid4()), _credential(username, "old-pw"), KEY
            )
        async with transaction(factory) as session:
            _ = await save_credential(
                session, str(uuid.uuid4()), _credential(username, "new-pw"), KEY
            )
        async with read_session(factory) as session:
            stored = await get_credential(session, user_id, KEY)
        assert stored is not None
        assert stored.password.get_secret_value() == "new-pw"

    async def test_find_user_id_locates_a_returning_user(self, db: DatabaseFixture) -> None:
        _, factory = db
        username = _username("find")
        async with transaction(factory) as session:
            user_id = await save_credential(session, str(uuid.uuid4()), _credential(username), KEY)
        async with read_session(factory) as session:
            assert await find_user_id_by_username(session, username) == user_id

    async def test_find_user_id_is_none_for_a_new_username(self, db: DatabaseFixture) -> None:
        _, factory = db
        async with read_session(factory) as session:
            assert await find_user_id_by_username(session, _username("absent")) is None
