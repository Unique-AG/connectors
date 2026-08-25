import asyncio

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from backstop_mcp.backstop_client import BackstopCredentialSecret
from backstop_mcp.db import BackstopCredential, transaction
from backstop_mcp.features.auth.credential_store import (
    find_user_id_by_username,
    get_credential,
    save_credential,
)

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


def _random_key() -> bytes:
    return Fernet.generate_key()


class TestSaveAndGetCredential:
    @pytest.mark.asyncio
    async def test_round_trip_through_the_database(self, db: DatabaseFixture) -> None:
        _, factory = db
        key = _random_key()
        credential = BackstopCredentialSecret(
            username="cs-bob.smith", api_token=SecretStr("p@55W0rd321!")
        )

        async with factory() as session:
            user_id = await save_credential(session, "user-1", credential, key)
            await session.commit()

        assert user_id == "user-1"

        async with factory() as session:
            recovered = await get_credential(session, "user-1", key)

        assert recovered is not None
        assert recovered.username == "cs-bob.smith"
        assert recovered.api_token.get_secret_value() == "p@55W0rd321!"

    @pytest.mark.asyncio
    async def test_get_credential_returns_none_for_unknown_user(self, db: DatabaseFixture) -> None:
        _, factory = db

        async with factory() as session:
            recovered = await get_credential(session, "no-such-user", _random_key())

        assert recovered is None

    @pytest.mark.asyncio
    async def test_save_credential_upserts_existing_row(self, db: DatabaseFixture) -> None:
        _, factory = db
        key = _random_key()
        old_credential = BackstopCredentialSecret(
            username="cs-alice.jones", api_token=SecretStr("old-token")
        )
        new_credential = BackstopCredentialSecret(
            username="cs-alice.jones", api_token=SecretStr("new-token")
        )

        async with factory() as session:
            await save_credential(session, "user-2", old_credential, key)
            await session.commit()

        async with factory() as session:
            # A concurrent first login proposes a different id; username conflict keeps user-2.
            durable_id = await save_credential(session, "user-2-other", new_credential, key)
            await session.commit()

        assert durable_id == "user-2"

        async with factory() as session:
            recovered = await get_credential(session, "user-2", key)

        assert recovered is not None
        assert recovered.api_token.get_secret_value() == "new-token"

    @pytest.mark.asyncio
    async def test_concurrent_first_saves_share_one_user_id(self, db: DatabaseFixture) -> None:
        """Two first logins for the same username must not collide on the unique index."""
        _, factory = db
        key = _random_key()
        username = "cs-race.user"

        async def save_once(proposed_id: str, token: str) -> str:
            async with transaction(factory) as session:
                return await save_credential(
                    session,
                    proposed_id,
                    BackstopCredentialSecret(username=username, api_token=SecretStr(token)),
                    key,
                )

        durable_ids = await asyncio.gather(
            save_once("cs-race-a", "token-a"),
            save_once("cs-race-b", "token-b"),
            save_once("cs-race-c", "token-c"),
        )

        assert len(set(durable_ids)) == 1
        async with factory() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(BackstopCredential)
                .where(BackstopCredential.backstop_username == username)
            )
        assert count == 1
        async with factory() as session:
            recovered = await get_credential(session, durable_ids[0], key)
        assert recovered is not None
        assert recovered.username == username


class TestFindUserIdByUsername:
    @pytest.mark.asyncio
    async def test_returns_existing_user_id_for_returning_user(self, db: DatabaseFixture) -> None:
        _, factory = db
        credential = BackstopCredentialSecret(
            username="cs-carol.diaz", api_token=SecretStr("token")
        )

        async with factory() as session:
            await save_credential(session, "user-3", credential, _random_key())
            await session.commit()

        async with factory() as session:
            user_id = await find_user_id_by_username(session, "cs-carol.diaz")

        assert user_id == "user-3"

    @pytest.mark.asyncio
    async def test_returns_none_for_first_time_username(self, db: DatabaseFixture) -> None:
        _, factory = db

        async with factory() as session:
            user_id = await find_user_id_by_username(session, "never-seen-before")

        assert user_id is None
