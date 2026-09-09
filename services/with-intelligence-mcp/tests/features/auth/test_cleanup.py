"""The sweep that keeps four tables from growing without bound."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from mcp.shared.auth import OAuthClientInformationFull
from pydantic import AnyUrl
from sqlalchemy import func, select
from sqlalchemy.orm import DeclarativeBase, InstrumentedAttribute

from tests.conftest import DatabaseFixture
from with_intelligence_mcp.db import (
    AuthorizationCode,
    LoginAttempt,
    OAuthClient,
    OAuthToken,
    PendingAuthorization,
    read_session,
    transaction,
)
from with_intelligence_mcp.features.auth import purge_expired_auth_rows

RETENTION = timedelta(days=30)
WINDOW = timedelta(minutes=15)
CLIENT_RETENTION = timedelta(hours=24)


async def _sweep(db: DatabaseFixture) -> None:
    _, factory = db
    await purge_expired_auth_rows(
        factory,
        token_retention=RETENTION,
        login_attempt_window=WINDOW,
        unused_client_retention=CLIENT_RETENTION,
    )


async def _add_client(db: DatabaseFixture, client_id: str, *, created_ago: timedelta) -> None:
    _, factory = db
    metadata = OAuthClientInformationFull(
        client_id=client_id, redirect_uris=[AnyUrl("https://client.example/cb")]
    ).model_dump(mode="json")
    async with transaction(factory) as session:
        session.add(
            OAuthClient(
                client_id=client_id,
                client_metadata=metadata,
                created_at=datetime.now(UTC) - created_ago,
            )
        )


async def _count(db: DatabaseFixture, model: type[DeclarativeBase], **where: object) -> int:
    _, factory = db
    async with read_session(factory) as session:
        statement = select(func.count()).select_from(model)
        for column, value in where.items():
            statement = statement.where(
                cast("InstrumentedAttribute[object]", getattr(model, column)) == value
            )
        result = await session.execute(statement)
        return result.scalar_one()


class TestExpiredRows:
    async def test_an_abandoned_login_is_swept(self, db: DatabaseFixture) -> None:
        _, factory = db
        client_id = f"cleanup-pending-{uuid.uuid4().hex[:8]}"
        await _add_client(db, client_id, created_ago=timedelta(0))
        request_id = f"pending-{uuid.uuid4().hex[:8]}"
        async with transaction(factory) as session:
            session.add(
                PendingAuthorization(
                    request_id=request_id,
                    client_id=client_id,
                    scopes=[],
                    code_challenge="c",
                    redirect_uri="https://client.example/cb",
                    redirect_uri_provided_explicitly=True,
                    expires_at=datetime.now(UTC) - timedelta(minutes=1),
                )
            )
        await _sweep(db)
        assert await _count(db, PendingAuthorization, request_id=request_id) == 0

    async def test_an_unexchanged_code_is_swept(self, db: DatabaseFixture) -> None:
        _, factory = db
        client_id = f"cleanup-code-{uuid.uuid4().hex[:8]}"
        await _add_client(db, client_id, created_ago=timedelta(0))
        code = f"code-{uuid.uuid4().hex[:8]}"
        async with transaction(factory) as session:
            session.add(
                AuthorizationCode(
                    code=code,
                    client_id=client_id,
                    scopes=[],
                    code_challenge="c",
                    redirect_uri="https://client.example/cb",
                    redirect_uri_provided_explicitly=True,
                    expires_at=(datetime.now(UTC) - timedelta(minutes=1)).timestamp(),
                )
            )
        await _sweep(db)
        assert await _count(db, AuthorizationCode, code=code) == 0

    async def test_a_live_pending_authorization_survives(self, db: DatabaseFixture) -> None:
        _, factory = db
        client_id = f"cleanup-live-{uuid.uuid4().hex[:8]}"
        await _add_client(db, client_id, created_ago=timedelta(0))
        request_id = f"live-{uuid.uuid4().hex[:8]}"
        async with transaction(factory) as session:
            session.add(
                PendingAuthorization(
                    request_id=request_id,
                    client_id=client_id,
                    scopes=[],
                    code_challenge="c",
                    redirect_uri="https://client.example/cb",
                    redirect_uri_provided_explicitly=True,
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            )
        await _sweep(db)
        assert await _count(db, PendingAuthorization, request_id=request_id) == 1


class TestTokenFamilies:
    async def test_a_fully_expired_family_is_swept(self, db: DatabaseFixture) -> None:
        _, factory = db
        client_id = f"cleanup-tokens-{uuid.uuid4().hex[:8]}"
        await _add_client(db, client_id, created_ago=timedelta(0))
        family = uuid.uuid4()
        long_ago = datetime.now(UTC) - RETENTION - timedelta(days=1)
        async with transaction(factory) as session:
            session.add(
                OAuthToken(
                    family_id=family,
                    access_token_hash=f"a-{uuid.uuid4().hex}",
                    refresh_token_hash=f"r-{uuid.uuid4().hex}",
                    client_id=client_id,
                    scopes=[],
                    access_token_expires_at=long_ago,
                    refresh_token_expires_at=long_ago,
                )
            )
        await _sweep(db)
        assert await _count(db, OAuthToken, family_id=family) == 0

    async def test_a_family_with_one_live_member_survives_whole(self, db: DatabaseFixture) -> None:
        """Deleting by row would strand the newest token pointing at a purged ancestor."""
        _, factory = db
        client_id = f"cleanup-mixed-{uuid.uuid4().hex[:8]}"
        await _add_client(db, client_id, created_ago=timedelta(0))
        family = uuid.uuid4()
        long_ago = datetime.now(UTC) - RETENTION - timedelta(days=1)
        soon = datetime.now(UTC) + timedelta(days=1)
        async with transaction(factory) as session:
            session.add(
                OAuthToken(
                    family_id=family,
                    access_token_hash=f"old-{uuid.uuid4().hex}",
                    refresh_token_hash=f"oldr-{uuid.uuid4().hex}",
                    client_id=client_id,
                    scopes=[],
                    access_token_expires_at=long_ago,
                    refresh_token_expires_at=long_ago,
                )
            )
            session.add(
                OAuthToken(
                    family_id=family,
                    access_token_hash=f"new-{uuid.uuid4().hex}",
                    refresh_token_hash=f"newr-{uuid.uuid4().hex}",
                    client_id=client_id,
                    scopes=[],
                    access_token_expires_at=soon,
                    refresh_token_expires_at=soon,
                )
            )
        await _sweep(db)
        assert await _count(db, OAuthToken, family_id=family) == 2


class TestLoginAttempts:
    async def test_attempts_older_than_two_windows_are_swept(self, db: DatabaseFixture) -> None:
        _, factory = db
        username = f"cleanup-old-{uuid.uuid4().hex[:8]}"
        async with transaction(factory) as session:
            session.add(
                LoginAttempt(
                    username=username,
                    source_ip=None,
                    attempted_at=datetime.now(UTC) - 3 * WINDOW,
                )
            )
        await _sweep(db)
        assert await _count(db, LoginAttempt, username=username) == 0

    async def test_a_recent_attempt_survives(self, db: DatabaseFixture) -> None:
        """Sweeping inside the window would shorten someone's effective limit."""
        _, factory = db
        username = f"cleanup-recent-{uuid.uuid4().hex[:8]}"
        async with transaction(factory) as session:
            session.add(
                LoginAttempt(username=username, source_ip=None, attempted_at=datetime.now(UTC))
            )
        await _sweep(db)
        assert await _count(db, LoginAttempt, username=username) == 1


class TestUnreferencedClients:
    async def test_a_client_nothing_references_is_swept(self, db: DatabaseFixture) -> None:
        client_id = f"cleanup-orphan-{uuid.uuid4().hex[:8]}"
        await _add_client(db, client_id, created_ago=CLIENT_RETENTION + timedelta(hours=1))
        await _sweep(db)
        assert await _count(db, OAuthClient, client_id=client_id) == 0

    async def test_a_just_registered_client_survives(self, db: DatabaseFixture) -> None:
        """It legitimately has no children yet, mid-handshake."""
        client_id = f"cleanup-fresh-{uuid.uuid4().hex[:8]}"
        await _add_client(db, client_id, created_ago=timedelta(minutes=1))
        await _sweep(db)
        assert await _count(db, OAuthClient, client_id=client_id) == 1

    async def test_a_client_with_a_live_token_survives(self, db: DatabaseFixture) -> None:
        _, factory = db
        client_id = f"cleanup-inuse-{uuid.uuid4().hex[:8]}"
        await _add_client(db, client_id, created_ago=CLIENT_RETENTION + timedelta(hours=1))
        async with transaction(factory) as session:
            session.add(
                OAuthToken(
                    family_id=uuid.uuid4(),
                    access_token_hash=f"live-{uuid.uuid4().hex}",
                    refresh_token_hash=f"liver-{uuid.uuid4().hex}",
                    client_id=client_id,
                    scopes=[],
                    access_token_expires_at=datetime.now(UTC) + timedelta(days=1),
                    refresh_token_expires_at=datetime.now(UTC) + timedelta(days=1),
                )
            )
        await _sweep(db)
        assert await _count(db, OAuthClient, client_id=client_id) == 1
