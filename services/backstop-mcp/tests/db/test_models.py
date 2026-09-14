import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


class TestBackstopCredential:
    @pytest.mark.asyncio
    async def test_upsert_by_user_id(self, db: DatabaseFixture) -> None:
        from backstop_mcp.db import BackstopCredential

        _, factory = db
        async with factory() as session:
            session.add(
                BackstopCredential(
                    user_id="user-42",
                    backstop_username="bob.smith",
                    encrypted_blob=b"\x00fake-ciphertext",
                )
            )
            await session.commit()

        async with factory() as session:
            credential = await session.get(BackstopCredential, "user-42")
            assert credential is not None
            assert credential.backstop_username == "bob.smith"
            assert credential.encrypted_blob == b"\x00fake-ciphertext"

    @pytest.mark.asyncio
    async def test_backstop_username_is_unique(self, db: DatabaseFixture) -> None:
        from sqlalchemy.exc import IntegrityError

        from backstop_mcp.db import BackstopCredential

        _, factory = db
        async with factory() as session:
            session.add(
                BackstopCredential(
                    user_id="user-unique-a",
                    backstop_username="unique.user",
                    encrypted_blob=b"\x00a",
                )
            )
            await session.commit()

        async with factory() as session:
            session.add(
                BackstopCredential(
                    user_id="user-unique-b",
                    backstop_username="unique.user",
                    encrypted_blob=b"\x00b",
                )
            )
            with pytest.raises(IntegrityError):
                await session.commit()
