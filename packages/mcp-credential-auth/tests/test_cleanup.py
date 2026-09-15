import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from mcp_credential_auth import (
    AuthorizationCode,
    LoginAttempt,
    OAuthClient,
    OAuthToken,
    PendingAuthorization,
    purge_expired_auth_rows,
    read_session,
    transaction,
)

TOKEN_RETENTION = timedelta(days=30)
LOGIN_ATTEMPT_WINDOW = timedelta(minutes=15)
UNUSED_CLIENT_RETENTION = timedelta(hours=24)
NOW = datetime.now(UTC)
LONG_AGO = NOW - TOKEN_RETENTION - timedelta(days=1)


async def _register_client(
    session_factory: async_sessionmaker[AsyncSession], client_id: str
) -> None:
    async with transaction(session_factory) as session:
        session.add(OAuthClient(client_id=client_id, client_metadata={}))


def _token(
    client_id: str,
    *,
    family_id: uuid.UUID,
    access_expires_at: datetime,
    refresh_expires_at: datetime | None,
    rotated_from: uuid.UUID | None = None,
) -> OAuthToken:
    suffix = uuid.uuid4().hex
    return OAuthToken(
        id=uuid.uuid4(),
        family_id=family_id,
        access_token_hash=f"access-{suffix}",
        refresh_token_hash=f"refresh-{suffix}",
        client_id=client_id,
        scopes=[],
        subject="subject-1",
        access_token_expires_at=access_expires_at,
        refresh_token_expires_at=refresh_expires_at,
        rotated_from=rotated_from,
    )


async def _token_ids(session_factory: async_sessionmaker[AsyncSession]) -> set[uuid.UUID]:
    async with read_session(session_factory) as session:
        result = await session.execute(select(OAuthToken.id))
        return set(result.scalars().all())


async def _sweep(session_factory: async_sessionmaker[AsyncSession]) -> None:
    await purge_expired_auth_rows(
        session_factory,
        token_retention=TOKEN_RETENTION,
        login_attempt_window=LOGIN_ATTEMPT_WINDOW,
        unused_client_retention=UNUSED_CLIENT_RETENTION,
    )


async def test_drops_expired_pending_authorizations_and_keeps_live_ones(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register_client(session_factory, "cleanup-client-pending")

    async with transaction(session_factory) as session:
        for request_id, expires_at in (
            ("cleanup-pending-stale", NOW - timedelta(minutes=1)),
            ("cleanup-pending-live", NOW + timedelta(minutes=10)),
        ):
            session.add(
                PendingAuthorization(
                    request_id=request_id,
                    client_id="cleanup-client-pending",
                    scopes=[],
                    code_challenge="challenge",
                    redirect_uri="https://client.example/callback",
                    redirect_uri_provided_explicitly=True,
                    expires_at=expires_at,
                )
            )

    await _sweep(session_factory)

    async with read_session(session_factory) as session:
        assert await session.get(PendingAuthorization, "cleanup-pending-stale") is None
        assert await session.get(PendingAuthorization, "cleanup-pending-live") is not None


async def test_drops_expired_authorization_codes_and_keeps_live_ones(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register_client(session_factory, "cleanup-client-codes")

    async with transaction(session_factory) as session:
        for code, expires_at in (
            ("cleanup-code-stale", NOW - timedelta(minutes=1)),
            ("cleanup-code-live", NOW + timedelta(minutes=5)),
        ):
            session.add(
                AuthorizationCode(
                    code=code,
                    client_id="cleanup-client-codes",
                    scopes=[],
                    code_challenge="challenge",
                    redirect_uri="https://client.example/callback",
                    redirect_uri_provided_explicitly=True,
                    subject="subject-1",
                    expires_at=expires_at.timestamp(),
                )
            )

    await _sweep(session_factory)

    async with read_session(session_factory) as session:
        assert await session.get(AuthorizationCode, "cleanup-code-stale") is None
        assert await session.get(AuthorizationCode, "cleanup-code-live") is not None


async def test_keeps_a_token_family_still_inside_the_retention_window(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register_client(session_factory, "cleanup-client-recent")
    family_id = uuid.uuid4()

    async with transaction(session_factory) as session:
        session.add(
            _token(
                "cleanup-client-recent",
                family_id=family_id,
                access_expires_at=NOW - timedelta(hours=1),
                refresh_expires_at=NOW - timedelta(minutes=30),
            )
        )
    before = await _token_ids(session_factory)

    await _sweep(session_factory)

    assert await _token_ids(session_factory) == before


async def test_drops_a_whole_rotation_chain_once_every_member_is_past_retention(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register_client(session_factory, "cleanup-client-old")
    family_id = uuid.uuid4()

    async with transaction(session_factory) as session:
        ancestor = _token(
            "cleanup-client-old",
            family_id=family_id,
            access_expires_at=LONG_AGO - timedelta(days=30),
            refresh_expires_at=LONG_AGO - timedelta(days=1),
        )
        session.add(ancestor)
        await session.flush()
        session.add(
            _token(
                "cleanup-client-old",
                family_id=family_id,
                access_expires_at=LONG_AGO,
                refresh_expires_at=LONG_AGO,
                rotated_from=ancestor.id,
            )
        )

    await _sweep(session_factory)

    async with read_session(session_factory) as session:
        result = await session.execute(select(OAuthToken).where(OAuthToken.family_id == family_id))
        assert result.scalars().all() == []


async def test_spares_an_old_ancestor_whose_descendant_is_still_live(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register_client(session_factory, "cleanup-client-mixed")
    family_id = uuid.uuid4()

    async with transaction(session_factory) as session:
        ancestor = _token(
            "cleanup-client-mixed",
            family_id=family_id,
            access_expires_at=LONG_AGO,
            refresh_expires_at=LONG_AGO,
        )
        session.add(ancestor)
        await session.flush()
        session.add(
            _token(
                "cleanup-client-mixed",
                family_id=family_id,
                access_expires_at=NOW + timedelta(minutes=15),
                refresh_expires_at=NOW + timedelta(days=30),
                rotated_from=ancestor.id,
            )
        )
        ancestor_id = ancestor.id

    await _sweep(session_factory)

    async with read_session(session_factory) as session:
        assert await session.get(OAuthToken, ancestor_id) is not None


async def test_purge_is_idempotent(session_factory: async_sessionmaker[AsyncSession]) -> None:
    await _register_client(session_factory, "cleanup-client-twice")

    async with transaction(session_factory) as session:
        session.add(
            _token(
                "cleanup-client-twice",
                family_id=uuid.uuid4(),
                access_expires_at=LONG_AGO,
                refresh_expires_at=LONG_AGO,
            )
        )

    await _sweep(session_factory)
    await _sweep(session_factory)


async def test_drops_attempts_older_than_two_windows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    username = "cleanup-attempts-old"
    async with transaction(session_factory) as session:
        session.add(
            LoginAttempt(
                username=username,
                source_ip=None,
                attempted_at=datetime.now(UTC) - (2 * LOGIN_ATTEMPT_WINDOW + timedelta(minutes=1)),
            )
        )

    await _sweep(session_factory)

    async with read_session(session_factory) as session:
        result = await session.execute(
            select(LoginAttempt).where(LoginAttempt.username == username)
        )
        assert result.scalars().all() == []


async def test_keeps_attempts_the_throttle_still_counts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    username = "cleanup-attempts-recent"
    async with transaction(session_factory) as session:
        session.add(
            LoginAttempt(
                username=username,
                source_ip=None,
                attempted_at=datetime.now(UTC) - timedelta(minutes=1),
            )
        )

    await _sweep(session_factory)

    async with read_session(session_factory) as session:
        result = await session.execute(
            select(LoginAttempt).where(LoginAttempt.username == username)
        )
        assert len(result.scalars().all()) == 1


async def _client_ids(session_factory: async_sessionmaker[AsyncSession]) -> set[str]:
    async with read_session(session_factory) as session:
        result = await session.execute(select(OAuthClient.client_id))
        return set(result.scalars().all())


async def _backdate_client(
    session_factory: async_sessionmaker[AsyncSession], client_id: str, *, age: timedelta
) -> None:
    async with transaction(session_factory) as session:
        client = await session.get(OAuthClient, client_id)
        assert client is not None
        client.created_at = datetime.now(UTC) - age


async def test_drops_a_client_that_registered_and_never_came_back(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client_id = "cleanup-client-abandoned"
    await _register_client(session_factory, client_id)
    await _backdate_client(
        session_factory, client_id, age=UNUSED_CLIENT_RETENTION + timedelta(hours=1)
    )

    await _sweep(session_factory)

    assert client_id not in await _client_ids(session_factory)


async def test_keeps_a_client_that_only_just_registered(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client_id = "cleanup-client-fresh"
    await _register_client(session_factory, client_id)

    await _sweep(session_factory)

    assert client_id in await _client_ids(session_factory)


async def test_keeps_an_old_client_that_still_holds_a_live_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client_id = "cleanup-client-in-use"
    await _register_client(session_factory, client_id)
    await _backdate_client(
        session_factory, client_id, age=UNUSED_CLIENT_RETENTION + timedelta(days=30)
    )
    async with transaction(session_factory) as session:
        session.add(
            _token(
                client_id,
                family_id=uuid.uuid4(),
                access_expires_at=NOW + timedelta(minutes=15),
                refresh_expires_at=NOW + timedelta(days=30),
            )
        )

    await _sweep(session_factory)

    assert client_id in await _client_ids(session_factory)


async def test_reclaims_a_client_in_the_same_sweep_that_purges_its_last_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client_id = "cleanup-client-last-token"
    await _register_client(session_factory, client_id)
    await _backdate_client(
        session_factory, client_id, age=UNUSED_CLIENT_RETENTION + timedelta(days=1)
    )
    async with transaction(session_factory) as session:
        session.add(
            _token(
                client_id,
                family_id=uuid.uuid4(),
                access_expires_at=LONG_AGO,
                refresh_expires_at=LONG_AGO,
            )
        )

    await _sweep(session_factory)

    assert client_id not in await _client_ids(session_factory)


async def test_keeps_a_client_with_an_authorization_still_in_flight(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    client_id = "cleanup-client-inflight"
    await _register_client(session_factory, client_id)
    await _backdate_client(
        session_factory, client_id, age=UNUSED_CLIENT_RETENTION + timedelta(days=1)
    )
    async with transaction(session_factory) as session:
        session.add(
            PendingAuthorization(
                request_id="cleanup-client-inflight-request",
                client_id=client_id,
                scopes=[],
                code_challenge="challenge",
                redirect_uri="https://client.example/callback",
                redirect_uri_provided_explicitly=True,
                expires_at=NOW + timedelta(minutes=10),
            )
        )

    await _sweep(session_factory)

    assert client_id in await _client_ids(session_factory)
