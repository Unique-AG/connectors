from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

type DatabaseFixture = tuple[AsyncEngine, async_sessionmaker[AsyncSession]]


class TestOAuthClient:
    @pytest.mark.asyncio
    async def test_insert_and_fetch(self, db: DatabaseFixture) -> None:
        from backstop_mcp.db.models import OAuthClient

        _, factory = db
        async with factory() as session:
            session.add(
                OAuthClient(
                    client_id="client-1",
                    client_metadata_json='{"redirect_uris": ["https://client.example/callback"]}',
                )
            )
            await session.commit()

        async with factory() as session:
            client = await session.get(OAuthClient, "client-1")
            assert client is not None
            assert "client.example" in client.client_metadata_json


class TestPendingAuthorization:
    @pytest.mark.asyncio
    async def test_insert_and_fetch(self, db: DatabaseFixture) -> None:
        from backstop_mcp.db.models import OAuthClient, PendingAuthorization

        _, factory = db
        now = datetime.now(UTC)

        async with factory() as session:
            session.add(OAuthClient(client_id="client-3", client_metadata_json="{}"))
            await session.commit()

        async with factory() as session:
            session.add(
                PendingAuthorization(
                    request_id="request-1",
                    client_id="client-3",
                    scopes=["backstop"],
                    code_challenge="challenge",
                    redirect_uri="https://client.example/callback",
                    redirect_uri_provided_explicitly=True,
                    state="xyz",
                    expires_at=now + timedelta(minutes=10),
                )
            )
            await session.commit()

        async with factory() as session:
            pending = await session.get(PendingAuthorization, "request-1")
            assert pending is not None
            assert pending.scopes == ["backstop"]
            assert pending.state == "xyz"


class TestAuthorizationCode:
    @pytest.mark.asyncio
    async def test_insert_and_fetch(self, db: DatabaseFixture) -> None:
        from backstop_mcp.db.models import AuthorizationCode, OAuthClient

        _, factory = db
        now = datetime.now(UTC)

        async with factory() as session:
            session.add(OAuthClient(client_id="client-4", client_metadata_json="{}"))
            await session.commit()

        async with factory() as session:
            session.add(
                AuthorizationCode(
                    code="code-1",
                    client_id="client-4",
                    scopes=["backstop"],
                    code_challenge="challenge",
                    redirect_uri="https://client.example/callback",
                    redirect_uri_provided_explicitly=True,
                    subject="user-1",
                    expires_at=(now + timedelta(minutes=5)).timestamp(),
                )
            )
            await session.commit()

        async with factory() as session:
            code = await session.get(AuthorizationCode, "code-1")
            assert code is not None
            assert code.subject == "user-1"
            assert code.scopes == ["backstop"]


class TestOAuthTokenRotation:
    @pytest.mark.asyncio
    async def test_rotated_from_links_token_family(self, db: DatabaseFixture) -> None:
        import uuid

        from backstop_mcp.db.models import OAuthClient, OAuthToken

        _, factory = db
        now = datetime.now(UTC)
        family_id = uuid.uuid4()

        async with factory() as session:
            session.add(OAuthClient(client_id="client-2", client_metadata_json="{}"))
            await session.commit()

        async with factory() as session:
            original = OAuthToken(
                family_id=family_id,
                access_token_hash="hash-access-1",
                refresh_token_hash="hash-refresh-1",
                client_id="client-2",
                scopes=["backstop"],
                subject="user-1",
                access_token_expires_at=now + timedelta(minutes=15),
                refresh_token_expires_at=now + timedelta(days=30),
            )
            session.add(original)
            await session.commit()
            await session.refresh(original)
            original_id = original.id

        async with factory() as session:
            rotated = OAuthToken(
                family_id=family_id,
                access_token_hash="hash-access-2",
                refresh_token_hash="hash-refresh-2",
                client_id="client-2",
                scopes=["backstop"],
                subject="user-1",
                access_token_expires_at=now + timedelta(minutes=15),
                refresh_token_expires_at=now + timedelta(days=30),
                rotated_from=original_id,
            )
            session.add(rotated)
            await session.commit()

        async with factory() as session:
            result = await session.execute(
                select(OAuthToken).where(OAuthToken.rotated_from == original_id)
            )
            family = result.scalars().all()
            assert len(family) == 1
            assert family[0].access_token_hash == "hash-access-2"


class TestBackstopCredential:
    @pytest.mark.asyncio
    async def test_upsert_by_user_id(self, db: DatabaseFixture) -> None:
        from backstop_mcp.db.models import BackstopCredential

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

        from backstop_mcp.db.models import BackstopCredential

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
