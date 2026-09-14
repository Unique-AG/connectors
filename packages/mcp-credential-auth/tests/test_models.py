import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mcp_credential_auth import (
    AuthorizationCode,
    OAuthClient,
    OAuthToken,
    PendingAuthorization,
)


async def test_oauth_client_insert_and_fetch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        session.add(
            OAuthClient(
                client_id="client-1",
                client_metadata={"redirect_uris": ["https://client.example/callback"]},
            )
        )
        await session.commit()

    async with session_factory() as session:
        client = await session.get(OAuthClient, "client-1")
        assert client is not None
        assert client.client_metadata["redirect_uris"] == ["https://client.example/callback"]


async def test_pending_authorization_insert_and_fetch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)

    async with session_factory() as session:
        session.add(OAuthClient(client_id="client-3", client_metadata={}))
        await session.commit()

    async with session_factory() as session:
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

    async with session_factory() as session:
        pending = await session.get(PendingAuthorization, "request-1")
        assert pending is not None
        assert pending.scopes == ["backstop"]
        assert pending.state == "xyz"


async def test_authorization_code_insert_and_fetch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)

    async with session_factory() as session:
        session.add(OAuthClient(client_id="client-4", client_metadata={}))
        await session.commit()

    async with session_factory() as session:
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

    async with session_factory() as session:
        code = await session.get(AuthorizationCode, "code-1")
        assert code is not None
        assert code.subject == "user-1"
        assert code.scopes == ["backstop"]


async def test_rotated_from_links_token_family(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    family_id = uuid.uuid4()

    async with session_factory() as session:
        session.add(OAuthClient(client_id="client-2", client_metadata={}))
        await session.commit()

    async with session_factory() as session:
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

    async with session_factory() as session:
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

    async with session_factory() as session:
        result = await session.execute(
            select(OAuthToken).where(OAuthToken.rotated_from == original_id)
        )
        family = result.scalars().all()
        assert len(family) == 1
        assert family[0].access_token_hash == "hash-access-2"
